"""Convenience entry point for the local automated test suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


def _python_executable() -> str:
    candidates = [
        ROOT_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT_DIR / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local pytest suite.")
    parser.add_argument("-k", dest="keyword", default="", help="Only run tests matching this expression.")
    parser.add_argument("-m", dest="marker", default="", help="Only run tests matching this marker expression.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Run pytest in verbose mode.")
    parser.add_argument("pytest_args", nargs="*", help="Additional arguments passed to pytest.")
    args = parser.parse_args()

    command = [_python_executable(), "-m", "pytest"]
    if args.verbose:
        command.append("-v")
    if args.keyword:
        command.extend(["-k", args.keyword])
    if args.marker:
        command.extend(["-m", args.marker])
    command.extend(args.pytest_args)

    completed = subprocess.run(command, cwd=ROOT_DIR)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
