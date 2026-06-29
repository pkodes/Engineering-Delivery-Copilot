"""
Builder Agent — the 7th member of the engineering team.

Reads the artifacts produced by every previous agent (PRD, architecture, backend
design, etc.) and distills them into an AppSpec: the concrete data model and
identity of the application to be generated.

It uses Gemini for judgment, but is defensive: any failure degrades to a
deterministic heuristic spec so the build pipeline never hard-fails here.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from .app_spec import AppSpec, GEMINI_SCHEMA, heuristic_spec, normalize_spec

MODEL_NAME = "gemini-2.5-flash"

_SYSTEM = """You are a Principal Engineer acting as a Builder Agent.
You convert an engineering delivery package into a precise, buildable data model
for a small but REAL full-stack CRUD application (FastAPI + SQLite + React).

Rules:
- Pick 3 to 6 core domain entities that capture the heart of the product.
- Each entity gets 3 to 7 concrete fields with appropriate types.
- Allowed field types ONLY: string, text, integer, number, boolean, date.
- Do NOT include an id field; it is added automatically.
- Provide 2 to 4 realistic seed rows per entity.
- Choose a tasteful primary_color hex.
Return ONLY JSON matching the provided schema."""


def _build_prompt(requirement: str, artifacts: dict[str, str]) -> str:
    """Compose the agent prompt from the requirement + upstream artifacts (truncated)."""
    def clip(text: str, limit: int = 4000) -> str:
        text = text or ""
        return text if len(text) <= limit else text[:limit] + "\n...[truncated]"

    sections = [
        _SYSTEM,
        f"\n# Original Requirement\n{requirement.strip()}",
        f"\n# Product Requirements (PRD)\n{clip(artifacts.get('prd', ''))}",
        f"\n# System Architecture\n{clip(artifacts.get('architecture', ''))}",
        f"\n# Backend / API Design\n{clip(artifacts.get('backend', ''))}",
        "\nNow produce the JSON AppSpec.",
    ]
    return "\n".join(sections)


def generate_app_spec(
    requirement: str,
    artifacts: dict[str, str],
    *,
    log: Callable[[str, str, str], None] | None = None,
) -> AppSpec:
    """
    Produce a validated AppSpec from the requirement + upstream artifacts.

    `log(stage, level, message)` is an optional progress sink.
    Never raises: on any LLM error it returns a heuristic spec.
    """
    def emit(level: str, message: str) -> None:
        if log:
            log("builder-agent", level, message)

    api_key = _read_api_key()
    if not api_key:
        emit("warn", "GEMINI_API_KEY not found — using deterministic fallback spec.")
        return heuristic_spec(requirement)

    try:
        import google.generativeai as genai  # imported lazily to keep import time low

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(MODEL_NAME)
        emit("info", "Asking Gemini to distill artifacts into a buildable data model…")
        response = model.generate_content(
            _build_prompt(requirement, artifacts),
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": GEMINI_SCHEMA,
                "temperature": 0.4,
            },
        )
        raw: dict[str, Any] = json.loads(response.text)
        spec = normalize_spec(raw, requirement=requirement, source="llm")
        emit(
            "info",
            f"Builder Agent designed '{spec.app_title}' with "
            f"{len(spec.entities)} entities: {', '.join(e.name for e in spec.entities)}.",
        )
        return spec
    except Exception as exc:  # noqa: BLE001 — defensive by design
        emit("warn", f"Gemini spec generation failed ({type(exc).__name__}); using fallback spec.")
        return heuristic_spec(requirement)


def _read_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    # Fall back to reading .env directly (the app may not have loaded it yet).
    try:
        from dotenv import dotenv_values

        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return dotenv_values(os.path.join(here, ".env")).get("GEMINI_API_KEY")
    except Exception:  # noqa: BLE001
        return None
