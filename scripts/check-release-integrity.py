#!/usr/bin/env python3
"""Validate that Job Hunter release metadata has one consistent source of truth."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

RELEASE_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PROJECT_NAME = "job-hunter-agent"


class ReleaseIntegrityError(RuntimeError):
    """Raised when release metadata is inconsistent or incomplete."""


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        raise ReleaseIntegrityError(f"Missing required release file: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _project_version(root: Path) -> str:
    project = _load_toml(root / "pyproject.toml").get("project")
    if not isinstance(project, dict):
        raise ReleaseIntegrityError("pyproject.toml is missing [project]")
    name = str(project.get("name", "")).strip()
    if name != PROJECT_NAME:
        raise ReleaseIntegrityError(
            f"Expected project.name={PROJECT_NAME!r}, found {name!r}"
        )
    version = str(project.get("version", "")).strip()
    if not RELEASE_VERSION_PATTERN.fullmatch(version):
        raise ReleaseIntegrityError(
            "project.version must use release format MAJOR.MINOR.PATCH; "
            f"found {version!r}"
        )
    return version


def _lock_version(root: Path) -> str:
    packages = _load_toml(root / "uv.lock").get("package")
    if not isinstance(packages, list):
        raise ReleaseIntegrityError("uv.lock is missing package entries")
    matches = [package for package in packages if package.get("name") == PROJECT_NAME]
    if len(matches) != 1:
        raise ReleaseIntegrityError(
            f"uv.lock must contain exactly one {PROJECT_NAME!r} package entry"
        )
    version = str(matches[0].get("version", "")).strip()
    if not version:
        raise ReleaseIntegrityError(f"uv.lock entry for {PROJECT_NAME!r} has no version")
    return version


def _ui_version(root: Path) -> str:
    sys.path.insert(0, str(root))
    try:
        from job_hunter_agent.release_metadata import load_app_release_metadata

        load_app_release_metadata.cache_clear()
        metadata = load_app_release_metadata()
    finally:
        sys.path.pop(0)
    version = str(metadata.get("version", "")).strip()
    if not version:
        raise ReleaseIntegrityError("UI release metadata loader returned no version")
    return version


def check_release_integrity(
    root: Path,
    *,
    expected_version: str | None = None,
    tag: str | None = None,
) -> str:
    """Return the canonical version after validating package, lock, UI, and tag."""
    root = root.resolve()
    project_version = _project_version(root)
    lock_version = _lock_version(root)
    ui_version = _ui_version(root)

    if lock_version != project_version:
        raise ReleaseIntegrityError(
            "uv.lock does not match pyproject.toml: "
            f"{lock_version!r} != {project_version!r}. Run `uv lock`."
        )
    if ui_version != project_version:
        raise ReleaseIntegrityError(
            "The rendered UI version source does not match pyproject.toml: "
            f"{ui_version!r} != {project_version!r}."
        )
    if expected_version is not None and expected_version != project_version:
        raise ReleaseIntegrityError(
            f"Expected version {expected_version!r}, found {project_version!r}."
        )
    if tag is not None:
        expected_tag = f"v{project_version}"
        if tag != expected_tag:
            raise ReleaseIntegrityError(
                f"Release tag {tag!r} does not match project version; expected {expected_tag!r}."
            )

    return project_version


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Job Hunter pyproject, uv.lock, UI, and optional Git tag versions."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the parent of scripts/.",
    )
    parser.add_argument("--expected-version", help="Require this exact MAJOR.MINOR.PATCH value.")
    parser.add_argument("--tag", help="Require this exact vMAJOR.MINOR.PATCH Git tag.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        version = check_release_integrity(
            args.root,
            expected_version=args.expected_version,
            tag=args.tag,
        )
    except (ReleaseIntegrityError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"RELEASE INTEGRITY FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Release integrity OK: v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
