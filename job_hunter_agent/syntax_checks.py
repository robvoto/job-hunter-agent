"""Helpers for lightweight Python syntax validation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from job_hunter_agent.paths import REPO_ROOT

PYTHON_SUFFIX = ".py"
EXCLUDED_PARTS = {".git", "__pycache__", ".venv", "node_modules"}


def iter_python_files(root: Path = REPO_ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob(f"*{PYTHON_SUFFIX}"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def check_python_syntax(paths: list[Path] | None = None) -> list[Path]:
    checked_paths = list(paths) if paths is not None else iter_python_files()
    failed: list[Path] = []
    for path in checked_paths:
        completed = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            failed.append(path)
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
    return failed
