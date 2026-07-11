"""Tests for approved runtime seeding boundaries."""

from __future__ import annotations

import json

from job_hunter_agent import db_seed


def _write_json(path, payload) -> None:  # type: ignore[no-untyped-def]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_sync_required_runtime_files_copies_only_allowlisted_repo_files(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    runtime_data_dir = tmp_path / "runtime-data"

    _write_json(repo_root / "data" / "config" / "global_settings.json", {"ok": True})
    _write_json(repo_root / "data" / "defaults" / "user_settings.json", {"ok": True})
    _write_json(repo_root / "data" / "knowledge" / "salary.json", {"bands": []})
    _write_json(
        repo_root / "data" / "knowledge" / "occupation_taxonomy" / "onet_index.json",
        {"entries": []},
    )
    _write_json(repo_root / "data" / "knowledge" / "private_example.json", {"secret": True})
    _write_json(
        repo_root / "data" / "knowledge" / "occupation_taxonomy" / "private_example.json",
        {"secret": True},
    )

    monkeypatch.setattr(db_seed, "REPO_ROOT", repo_root)
    monkeypatch.setattr(db_seed, "DATA_DIR", runtime_data_dir)
    monkeypatch.setattr(db_seed, "GLOBAL_SETTINGS_PATH", runtime_data_dir / "config" / "global_settings.json")
    monkeypatch.setattr(
        db_seed,
        "DEFAULT_USER_SETTINGS_PATH",
        runtime_data_dir / "defaults" / "user_settings.json",
    )
    monkeypatch.setattr(
        db_seed,
        "APPROVED_RUNTIME_KNOWLEDGE_JSON_REL_PATHS",
        ("salary.json", "occupation_taxonomy/onet_index.json"),
    )

    updated = db_seed.sync_required_runtime_files()

    assert "config/global_settings.json" in updated
    assert "defaults/user_settings.json" in updated
    assert "knowledge/salary.json" in updated
    assert "knowledge/occupation_taxonomy/onet_index.json" in updated
    assert (runtime_data_dir / "knowledge" / "salary.json").exists()
    assert (runtime_data_dir / "knowledge" / "occupation_taxonomy" / "onet_index.json").exists()
    assert not (runtime_data_dir / "knowledge" / "private_example.json").exists()
    assert not (
        runtime_data_dir / "knowledge" / "occupation_taxonomy" / "private_example.json"
    ).exists()


def test_sync_required_runtime_files_fails_when_required_knowledge_seed_is_missing(
    monkeypatch, tmp_path
):
    repo_root = tmp_path / "repo"
    runtime_data_dir = tmp_path / "runtime-data"

    _write_json(repo_root / "data" / "config" / "global_settings.json", {"ok": True})
    _write_json(repo_root / "data" / "defaults" / "user_settings.json", {"ok": True})
    _write_json(repo_root / "data" / "knowledge" / "salary.json", {"bands": []})

    monkeypatch.setattr(db_seed, "REPO_ROOT", repo_root)
    monkeypatch.setattr(db_seed, "DATA_DIR", runtime_data_dir)
    monkeypatch.setattr(db_seed, "GLOBAL_SETTINGS_PATH", runtime_data_dir / "config" / "global_settings.json")
    monkeypatch.setattr(
        db_seed,
        "DEFAULT_USER_SETTINGS_PATH",
        runtime_data_dir / "defaults" / "user_settings.json",
    )
    monkeypatch.setattr(
        db_seed,
        "APPROVED_RUNTIME_KNOWLEDGE_JSON_REL_PATHS",
        ("salary.json", "occupation_taxonomy/onet_index.json"),
    )

    try:
        db_seed.sync_required_runtime_files()
    except FileNotFoundError as exc:
        assert "onet_index.json" in str(exc)
    else:
        raise AssertionError("sync_required_runtime_files() should fail on missing required seeds")
