"""
Build service — orchestrates the Builder Agent end to end:

    artifacts ─▶ Builder Agent ─▶ AppSpec ─▶ codegen ─▶ write to disk ─▶ zip

Produces a structured BuildResult (status + manifest + logs) that the API and
frontend consume. Designed to never raise: failures are captured as an `error`
status with logs so the UI can show the error and still offer a download.
"""
from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .app_spec import AppSpec
from .builder_agent import generate_app_spec
from .codegen import render_project

BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = BACKEND_DIR / "workspace"
PROJECT_DIRNAME = "generated-project"
PROJECT_DIR = WORKSPACE / PROJECT_DIRNAME
ZIP_PATH = WORKSPACE / f"{PROJECT_DIRNAME}.zip"
OUTPUTS_DIR = BACKEND_DIR / "outputs"

# Maps on-disk artifact files to the artifact keys used across the platform.
_ARTIFACT_FILES = {
    "prd": "prd.md",
    "architecture": "architecture.md",
    "backend": "api_design.md",
    "frontend": "ui_design.md",
    "qa": "qa_report.md",
    "security": "security_review.md",
}


class BuildLogger:
    """Collects structured, ordered build/deploy log entries."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []

    def log(self, stage: str, level: str, message: str) -> None:
        self.entries.append({"stage": stage, "level": level, "message": message})

    def info(self, stage: str, message: str) -> None:
        self.log(stage, "info", message)

    def warn(self, stage: str, message: str) -> None:
        self.log(stage, "warn", message)

    def error(self, stage: str, message: str) -> None:
        self.log(stage, "error", message)


@dataclass
class BuildResult:
    status: str  # "success" | "error"
    project_name: str = ""
    slug: str = ""
    app_title: str = ""
    description: str = ""
    entities: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    file_count: int = 0
    zip_available: bool = False
    spec: dict[str, Any] | None = None
    logs: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "project_name": self.project_name,
            "slug": self.slug,
            "app_title": self.app_title,
            "description": self.description,
            "entities": self.entities,
            "files": self.files,
            "file_count": self.file_count,
            "zip_available": self.zip_available,
            "spec": self.spec,
            "logs": self.logs,
            "error": self.error,
        }


# In-process cache of the most recent build (single-user dev tool).
_last_result: BuildResult | None = None


def get_last_result() -> BuildResult | None:
    return _last_result


def get_zip_path() -> Path | None:
    return ZIP_PATH if ZIP_PATH.exists() else None


def get_project_dir() -> Path | None:
    return PROJECT_DIR if PROJECT_DIR.exists() else None


def read_cached_artifacts() -> dict[str, str]:
    """Load artifacts previously written by the engineering agents (outputs/)."""
    artifacts: dict[str, str] = {}
    for key, filename in _ARTIFACT_FILES.items():
        path = OUTPUTS_DIR / filename
        if path.exists():
            artifacts[key] = path.read_text(encoding="utf-8")
    return artifacts


def _write_files(files: dict[str, str], root: Path) -> list[str]:
    """Write {relpath: content} under root, creating directories. Returns sorted relpaths."""
    written: list[str] = []
    for relpath, content in files.items():
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(relpath)
    return sorted(written)


def _zip_project(project_dir: Path, zip_path: Path) -> None:
    """Zip project_dir so the archive contains a top-level `generated-project/` folder."""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(project_dir.parent)
                zf.write(path, arcname)


def build_project(requirement: str, artifacts: dict[str, str]) -> BuildResult:
    """Run the full Builder pipeline. Never raises; returns a BuildResult."""
    global _last_result
    logger = BuildLogger()

    try:
        logger.info("init", "Builder Agent engaged — reading upstream engineering artifacts.")
        present = [k for k, v in artifacts.items() if v]
        logger.info("init", f"Artifacts available: {', '.join(present) or 'none (using requirement only)'}.")

        # 1. LLM judgment → validated spec
        spec: AppSpec = generate_app_spec(requirement, artifacts, log=logger.log)

        # 2. Deterministic code generation
        logger.info("codegen", "Rendering FastAPI + SQLite backend, React/Vite frontend, Docker & compose…")
        files = render_project(spec)
        logger.info("codegen", f"Generated {len(files)} source files.")

        # 3. Write to disk (clean slate each build)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        if PROJECT_DIR.exists():
            shutil.rmtree(PROJECT_DIR)
        written = _write_files(files, PROJECT_DIR)
        logger.info("write", f"Wrote project to {PROJECT_DIR}.")

        # 4. Zip
        _zip_project(PROJECT_DIR, ZIP_PATH)
        size_kb = ZIP_PATH.stat().st_size / 1024
        logger.info("package", f"Packaged {PROJECT_DIRNAME}.zip ({size_kb:.0f} KB).")

        result = BuildResult(
            status="success",
            project_name=spec.app_title,
            slug=spec.slug,
            app_title=spec.app_title,
            description=spec.description,
            entities=[e.name for e in spec.entities],
            files=written,
            file_count=len(written),
            zip_available=True,
            spec=spec.to_dict(),
            logs=logger.entries,
        )
        logger.info("done", "Build complete. Project is ready to preview and download.")
        result.logs = logger.entries
        _last_result = result
        return result

    except Exception as exc:  # noqa: BLE001 — surface as structured error, never crash the API
        logger.error("error", f"Build failed: {type(exc).__name__}: {exc}")
        result = BuildResult(
            status="error",
            logs=logger.entries,
            error=f"{type(exc).__name__}: {exc}",
            zip_available=ZIP_PATH.exists(),
        )
        _last_result = result
        return result
