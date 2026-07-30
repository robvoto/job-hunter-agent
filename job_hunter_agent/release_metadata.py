"""Dependency-free owner for Job Hunter application release metadata."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def load_app_release_metadata() -> dict[str, str]:
    """Read the application version from the canonical pyproject source."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml is missing [project]")
    version = str(project.get("version", "")).strip()
    if not version:
        raise ValueError("pyproject.toml is missing project.version")
    return {"version": version}
