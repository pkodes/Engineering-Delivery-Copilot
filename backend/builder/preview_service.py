"""
Preview service — runs the *generated* application for real and exposes a live URL.

No Docker on this host, so we use the local-process path: launch the generated
FastAPI backend with uvicorn on a free port, verify dependencies, poll the real
`/health` endpoint until it actually responds, and surface a Preview URL.

Guarantees (per spec): the preview is NEVER faked. Status only becomes "running"
after a genuine HTTP 200 from the generated app. On any failure the captured
process output is returned as the error, and the downloadable source is untouched.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .build_service import get_last_result, get_project_dir

HEALTH_TIMEOUT_S = 30.0
HEALTH_POLL_INTERVAL_S = 0.4
OUTPUT_BUFFER_LINES = 500


@dataclass
class PreviewState:
    status: str = "idle"  # idle | starting | running | error | stopped
    url: str | None = None
    port: int | None = None
    app_title: str = ""
    pid: int | None = None
    error: str | None = None
    logs: list[dict[str, str]] = field(default_factory=list)
    output: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "url": self.url,
            "port": self.port,
            "app_title": self.app_title,
            "pid": self.pid,
            "error": self.error,
            "logs": self.logs,
            "output": self.output[-120:],  # tail for the UI
        }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _title_from_disk(backend_dir: Path) -> str:
    """Recover the app title from the generated spec (survives platform reloads)."""
    try:
        import json

        spec = json.loads((backend_dir / "app" / "spec.json").read_text(encoding="utf-8"))
        return str(spec.get("app_title", ""))
    except Exception:
        return ""


def _health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


class PreviewService:
    """Owns at most one running preview process."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._output: list[str] = []
        self._out_lock = threading.Lock()
        self._lock = threading.Lock()
        self._logs: list[dict[str, str]] = []
        self._port: int | None = None
        self._app_title: str = ""

    # -- logging -----------------------------------------------------------
    def _log(self, level: str, message: str) -> None:
        self._logs.append({"stage": "preview", "level": level, "message": message})

    # -- process output reader --------------------------------------------
    def _drain(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if line == "":
                break
            with self._out_lock:
                self._output.append(line.rstrip("\n"))
                if len(self._output) > OUTPUT_BUFFER_LINES:
                    del self._output[0]

    def _snapshot_output(self) -> list[str]:
        with self._out_lock:
            return list(self._output)

    # -- lifecycle ---------------------------------------------------------
    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None
        self._reader = None
        self._port = None

    def status(self) -> PreviewState:
        with self._lock:
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                # The process died after it had started — reflect that.
                self._log("error", f"Preview process exited (code {proc.returncode}).")
                self._proc = None
                return PreviewState(
                    status="error",
                    app_title=self._app_title,
                    error="The preview process exited unexpectedly.",
                    logs=list(self._logs),
                    output=self._snapshot_output(),
                )
            if proc is not None and self._port is not None:
                return PreviewState(
                    status="running",
                    url=f"http://127.0.0.1:{self._port}/",
                    port=self._port,
                    app_title=self._app_title,
                    pid=proc.pid,
                    logs=list(self._logs),
                    output=self._snapshot_output(),
                )
            return PreviewState(status="idle", app_title=self._app_title, logs=list(self._logs))

    def start(self) -> PreviewState:
        with self._lock:
            self._stop_locked()
            self._logs = []
            self._output = []

            project_dir = get_project_dir()
            if project_dir is None:
                self._log("error", "No generated project found. Run a build first.")
                return PreviewState(status="error", error="No generated project. Build first.", logs=list(self._logs))

            backend_dir = project_dir / "backend"
            if not (backend_dir / "app" / "main.py").exists():
                self._log("error", "Generated backend is incomplete (app/main.py missing).")
                return PreviewState(status="error", error="Generated backend incomplete.", logs=list(self._logs))

            last = get_last_result()
            self._app_title = last.app_title if last else _title_from_disk(backend_dir)

            self._log("info", "Preparing live preview (local runtime — Docker not available).")

            # 1. Resolve dependencies honestly.
            if not self._ensure_dependencies(backend_dir):
                return PreviewState(
                    status="error",
                    app_title=self._app_title,
                    error="Could not satisfy runtime dependencies (fastapi, uvicorn).",
                    logs=list(self._logs),
                    output=self._snapshot_output(),
                )

            # 2. Launch uvicorn on a free port.
            port = _free_port()
            db_path = backend_dir / "preview.db"
            try:
                if db_path.exists():
                    db_path.unlink()  # fresh, fully-seeded database each run
            except Exception:
                pass

            env = {**os.environ, "DB_PATH": str(db_path), "PYTHONUNBUFFERED": "1"}
            cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
            self._log("info", f"Launching: uvicorn app.main:app on port {port}")

            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(backend_dir),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except Exception as exc:  # noqa: BLE001
                self._log("error", f"Failed to launch preview process: {exc}")
                return PreviewState(status="error", app_title=self._app_title, error=str(exc), logs=list(self._logs))

            self._proc = proc
            self._port = port
            self._reader = threading.Thread(target=self._drain, args=(proc,), daemon=True)
            self._reader.start()

            # 3. Wait for REAL readiness via /health.
            self._log("info", "Waiting for the application to report healthy…")
            deadline = time.time() + HEALTH_TIMEOUT_S
            while time.time() < deadline:
                if proc.poll() is not None:
                    self._log("error", f"Preview process exited during startup (code {proc.returncode}).")
                    self._proc = None
                    return PreviewState(
                        status="error",
                        app_title=self._app_title,
                        error="The application crashed during startup. See logs.",
                        logs=list(self._logs),
                        output=self._snapshot_output(),
                    )
                if _health_ok(port):
                    url = f"http://127.0.0.1:{port}/"
                    self._log("info", f"Health check passed. Live preview ready at {url}")
                    return PreviewState(
                        status="running",
                        url=url,
                        port=port,
                        app_title=self._app_title,
                        pid=proc.pid,
                        logs=list(self._logs),
                        output=self._snapshot_output(),
                    )
                time.sleep(HEALTH_POLL_INTERVAL_S)

            # 4. Timed out — never report a fake "ready".
            self._log("error", f"Application did not become healthy within {int(HEALTH_TIMEOUT_S)}s.")
            self._stop_locked()
            return PreviewState(
                status="error",
                app_title=self._app_title,
                error="Timed out waiting for the application to become healthy.",
                logs=list(self._logs),
                output=self._snapshot_output(),
            )

    def _ensure_dependencies(self, backend_dir: Path) -> bool:
        """Verify the runtime can import the generated app's deps; install if missing."""
        self._log("info", "Resolving dependencies (fastapi, uvicorn)…")
        check = subprocess.run(
            [sys.executable, "-c", "import fastapi, uvicorn"],
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            self._log("info", "Dependencies already satisfied in managed runtime — skipping install.")
            return True

        # Fall back to a real install with streamed logs.
        req = backend_dir / "requirements.txt"
        if not req.exists():
            self._log("error", "requirements.txt not found and deps unavailable.")
            return False
        self._log("info", "Installing dependencies via pip…")
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            with self._out_lock:
                self._output.append(line.rstrip("\n"))
        code = proc.wait()
        if code != 0:
            self._log("error", "pip install failed.")
            return False
        self._log("info", "Dependencies installed.")
        return True


# Module-level singleton.
preview_service = PreviewService()
