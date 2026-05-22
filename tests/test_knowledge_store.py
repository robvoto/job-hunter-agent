"""Tests for knowledge_store: get, set, seed, and idempotency."""

import json
import pytest

from job_hunter_agent.database import init_db
from job_hunter_agent.knowledge_store import (
    get_knowledge,
    seed_knowledge_from_dir,
    set_knowledge,
)


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


@pytest.fixture()
def knowledge_dir(tmp_path):
    d = tmp_path / "knowledge"
    d.mkdir()
    return d


def test_get_returns_none_for_missing_key(tmp_db):
    assert get_knowledge("nonexistent", tmp_db) is None


def test_set_and_get_roundtrip(tmp_db):
    data = {"entries": [{"value": "Python", "aliases": ["py"]}]}
    set_knowledge("capability_knowledge", data, tmp_db)
    result = get_knowledge("capability_knowledge", tmp_db)
    assert result == data


def test_set_overwrites_existing(tmp_db):
    set_knowledge("k", {"v": 1}, tmp_db)
    set_knowledge("k", {"v": 2}, tmp_db)
    assert get_knowledge("k", tmp_db) == {"v": 2}


def test_set_preserves_non_ascii(tmp_db):
    data = {"label": "Développement logiciel"}
    set_knowledge("unicode_key", data, tmp_db)
    assert get_knowledge("unicode_key", tmp_db) == data


def test_seed_inserts_all_json_files(tmp_db, knowledge_dir):
    (knowledge_dir / "rules_a.json").write_text('{"entries": [1]}', encoding="utf-8")
    (knowledge_dir / "rules_b.json").write_text('{"entries": [2]}', encoding="utf-8")
    seeded = seed_knowledge_from_dir(knowledge_dir, tmp_db)
    assert set(seeded) == {"rules_a", "rules_b"}
    assert get_knowledge("rules_a", tmp_db) == {"entries": [1]}
    assert get_knowledge("rules_b", tmp_db) == {"entries": [2]}


def test_seed_ignore_does_not_overwrite(tmp_db, knowledge_dir):
    set_knowledge("rules_a", {"entries": ["original"]}, tmp_db)
    (knowledge_dir / "rules_a.json").write_text('{"entries": ["updated"]}', encoding="utf-8")
    seeded = seed_knowledge_from_dir(knowledge_dir, tmp_db)
    assert seeded == []
    assert get_knowledge("rules_a", tmp_db) == {"entries": ["original"]}


def test_seed_overwrite_replaces_existing(tmp_db, knowledge_dir):
    set_knowledge("rules_a", {"entries": ["original"]}, tmp_db)
    (knowledge_dir / "rules_a.json").write_text('{"entries": ["updated"]}', encoding="utf-8")
    seeded = seed_knowledge_from_dir(knowledge_dir, tmp_db, overwrite=True)
    assert seeded == ["rules_a"]
    assert get_knowledge("rules_a", tmp_db) == {"entries": ["updated"]}


def test_seed_returns_only_newly_inserted_keys(tmp_db, knowledge_dir):
    set_knowledge("existing", {"v": 1}, tmp_db)
    (knowledge_dir / "existing.json").write_text('{"v": 2}', encoding="utf-8")
    (knowledge_dir / "new_key.json").write_text('{"v": 3}', encoding="utf-8")
    seeded = seed_knowledge_from_dir(knowledge_dir, tmp_db)
    assert seeded == ["new_key"]


def test_seed_is_idempotent(tmp_db, knowledge_dir):
    (knowledge_dir / "k.json").write_text('{"x": 1}', encoding="utf-8")
    seed_knowledge_from_dir(knowledge_dir, tmp_db)
    seed_knowledge_from_dir(knowledge_dir, tmp_db)
    assert get_knowledge("k", tmp_db) == {"x": 1}


def test_seed_handles_list_payload(tmp_db, knowledge_dir):
    (knowledge_dir / "list_data.json").write_text("[1, 2, 3]", encoding="utf-8")
    seed_knowledge_from_dir(knowledge_dir, tmp_db)
    assert get_knowledge("list_data", tmp_db) == [1, 2, 3]


def test_repo_knowledge_seeds_successfully(tmp_db):
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    knowledge_dir = repo_root / "data" / "knowledge"
    seeded = seed_knowledge_from_dir(knowledge_dir, tmp_db)
    assert len(seeded) == 24, f"Expected 24 knowledge files, got {len(seeded)}: {seeded}"


def test_match_level_defaults_loaded_from_db(tmp_db):
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    seed_knowledge_from_dir(repo_root / "data" / "knowledge", tmp_db)
    data = get_knowledge("match_level_defaults", tmp_db)
    assert isinstance(data, dict)
    assert "entries" in data
    assert len(data["entries"]) > 0
