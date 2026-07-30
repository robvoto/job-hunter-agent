from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from starlette.requests import Request

from job_hunter_agent.routes import pages

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPT = REPO_ROOT / "scripts" / "check-release-integrity.py"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release-jobhunter.sh"


def _load_integrity_module():
    spec = importlib.util.spec_from_file_location("release_integrity", INTEGRITY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_release_metadata(root: Path, *, project_version: str, lock_version: str) -> None:
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "job-hunter-agent"',
                f'version = "{project_version}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "\n".join(
            [
                "version = 1",
                "revision = 3",
                "",
                "[[package]]",
                'name = "job-hunter-agent"',
                f'version = "{lock_version}"',
                'source = { virtual = "." }',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_current_repository_release_metadata_is_consistent():
    integrity = _load_integrity_module()

    version = integrity.check_release_integrity(REPO_ROOT)

    assert version == integrity._project_version(REPO_ROOT)


def test_release_integrity_rejects_lock_version_mismatch(tmp_path, monkeypatch):
    integrity = _load_integrity_module()
    _write_release_metadata(tmp_path, project_version="1.5.1", lock_version="1.5.0")
    monkeypatch.setattr(integrity, "_ui_version", lambda _root: "1.5.1")

    with pytest.raises(integrity.ReleaseIntegrityError, match="uv.lock does not match"):
        integrity.check_release_integrity(tmp_path)


def test_release_integrity_rejects_tag_version_mismatch(tmp_path, monkeypatch):
    integrity = _load_integrity_module()
    _write_release_metadata(tmp_path, project_version="1.5.1", lock_version="1.5.1")
    monkeypatch.setattr(integrity, "_ui_version", lambda _root: "1.5.1")

    with pytest.raises(integrity.ReleaseIntegrityError, match="does not match project version"):
        integrity.check_release_integrity(tmp_path, tag="v1.5.0")


def test_top_utility_bar_renders_version_from_release_metadata(monkeypatch):
    monkeypatch.setattr(pages.srv, "DEBUG_MODE", False)
    monkeypatch.setattr(pages.srv, "load_app_release_metadata", lambda: {"version": "9.8.7"})
    monkeypatch.setattr(pages, "read_session_user", lambda _request: None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )

    html = pages._build_top_utility_bar_html(request)

    assert 'class="job-hunter-page-utility__release-version">v9.8.7</span>' in html


def test_release_command_owns_bump_tests_tag_and_atomic_push():
    script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert 'uv version --bump "$bump" --no-sync' in script
    assert "uv run python scripts/check-release-integrity.py" in script
    assert "uv run pytest" in script
    assert "./scripts/run-e2e.sh -q" in script
    assert 'git tag -a "$release_tag"' in script
    assert 'git push --atomic origin main "$release_tag"' in script
    assert "git status --porcelain --untracked-files=all" in script
