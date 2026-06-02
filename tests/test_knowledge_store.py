"""Tests for knowledge_store: get, set, seed, and idempotency."""

import json
import pytest

from job_hunter_agent.database import init_db
from job_hunter_agent.knowledge_store import (
    get_knowledge,
    seed_knowledge_from_dir,
    set_knowledge,
    upgrade_knowledge_from_dir,
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
    assert len(seeded) == 18, f"Expected 18 knowledge files, got {len(seeded)}: {seeded}"


def test_upgrade_seeds_missing_key(tmp_db, knowledge_dir):
    (knowledge_dir / "rules.json").write_text('{"version": 1, "entries": [{"value": "A"}]}', encoding="utf-8")
    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert updated == ["rules"]
    assert get_knowledge("rules", tmp_db)["entries"][0]["value"] == "A"


def test_upgrade_skips_when_version_current(tmp_db, knowledge_dir):
    data = {"version": 2, "entries": [{"value": "A"}]}
    set_knowledge("rules", data, tmp_db)
    (knowledge_dir / "rules.json").write_text('{"version": 2, "entries": [{"value": "B"}]}', encoding="utf-8")
    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert updated == []
    assert get_knowledge("rules", tmp_db)["entries"][0]["value"] == "A"


def test_upgrade_skips_when_db_version_ahead(tmp_db, knowledge_dir):
    set_knowledge("rules", {"version": 5, "entries": [{"value": "A"}]}, tmp_db)
    (knowledge_dir / "rules.json").write_text('{"version": 3, "entries": [{"value": "B"}]}', encoding="utf-8")
    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert updated == []


def test_upgrade_additive_appends_new_entries(tmp_db, knowledge_dir):
    set_knowledge("rules", {"version": 1, "entries": [{"value": "A"}]}, tmp_db)
    (knowledge_dir / "rules.json").write_text(
        '{"version": 2, "entries": [{"value": "A"}, {"value": "B"}]}', encoding="utf-8"
    )
    upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    entries = get_knowledge("rules", tmp_db)["entries"]
    assert len(entries) == 2
    assert {e["value"] for e in entries} == {"A", "B"}


def test_upgrade_additive_preserves_user_approved_entries(tmp_db, knowledge_dir):
    set_knowledge("rules", {"version": 1, "entries": [{"value": "A"}, {"value": "UserApproved"}]}, tmp_db)
    (knowledge_dir / "rules.json").write_text(
        '{"version": 2, "entries": [{"value": "A"}, {"value": "B"}]}', encoding="utf-8"
    )
    upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    entries = get_knowledge("rules", tmp_db)["entries"]
    values = {e["value"] for e in entries}
    assert "UserApproved" in values
    assert "B" in values


def test_upgrade_config_replaces_wholesale_on_version_bump(tmp_db, knowledge_dir):
    set_knowledge("config", {"version": 1, "threshold": 0.5}, tmp_db)
    (knowledge_dir / "config.json").write_text('{"version": 2, "threshold": 0.8}', encoding="utf-8")
    upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert get_knowledge("config", tmp_db)["threshold"] == 0.8


def test_upgrade_no_version_always_replaces(tmp_db, knowledge_dir):
    set_knowledge("ref", {"label": "old"}, tmp_db)
    (knowledge_dir / "ref.json").write_text('{"label": "new"}', encoding="utf-8")
    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert updated == ["ref"]
    assert get_knowledge("ref", tmp_db)["label"] == "new"


def test_upgrade_bumps_version_after_additive_merge(tmp_db, knowledge_dir):
    set_knowledge("rules", {"version": 1, "entries": [{"value": "A"}]}, tmp_db)
    (knowledge_dir / "rules.json").write_text(
        '{"version": 2, "entries": [{"value": "A"}, {"value": "B"}]}', encoding="utf-8"
    )
    upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert get_knowledge("rules", tmp_db)["version"] == 2


def test_match_level_defaults_loaded_from_db(tmp_db):
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    seed_knowledge_from_dir(repo_root / "data" / "knowledge", tmp_db)
    data = get_knowledge("match_level_defaults", tmp_db)
    assert isinstance(data, dict)
    assert "entries" in data
    assert len(data["entries"]) > 0


def test_upgrade_fixes_stale_ui_labels_missing_settings_alerts(isolated_db):
    from pathlib import Path
    from job_hunter_agent.server_helpers import build_bootstrap_script, load_settings_alerts_labels

    repo_root = Path(__file__).resolve().parent.parent
    knowledge_dir = repo_root / "data" / "knowledge"

    stale = {
        "kind": "ui_labels",
        "name": "ui_labels",
        "version": 16,
        "settings_alerts_labels": {},
    }
    set_knowledge("ui_labels", stale, isolated_db)

    updated = upgrade_knowledge_from_dir(knowledge_dir, isolated_db)
    assert "ui_labels" in updated

    # Direct loader must not raise.
    labels = load_settings_alerts_labels()
    assert "section_title" in labels
    assert "telegram_heading" in labels
    assert "llm_model_label" in labels

    # The actual page-render path must not raise (this is what failed at runtime).
    html = build_bootstrap_script()
    assert "__JOB_HUNTER_SETTINGS_ALERTS_LABELS__" in html


def test_upgrade_fixes_stale_ui_labels_missing_shared_labels(isolated_db):
    from pathlib import Path
    from job_hunter_agent.server_helpers import build_bootstrap_script, load_shared_ui_labels

    repo_root = Path(__file__).resolve().parent.parent
    knowledge_dir = repo_root / "data" / "knowledge"

    stale = {
        "kind": "ui_labels",
        "name": "ui_labels",
        "version": 18,
        "shared_ui_labels": {
            "select_theme_aria_label": "Select theme",
            "account_menu_aria_label": "Account",
            "account_menu_title": "Account",
            "account_menu_logout_label": "Log out",
            "account_menu_settings_shortcut_label": "⚙",
            "account_menu_settings_shortcut_aria_label": "Open settings",
            "account_menu_workspace_shortcut_label": "↩",
            "account_menu_workspace_shortcut_aria_label": "Open workspace",
            "account_menu_test_label": "Test",
            "account_menu_test_actions_label": "Test actions",
            "account_menu_reset_user_label": "Reset User",
            "add_button_label": "+",
            "add_button_aria_label": "Add item",
            "add_button_title": "+",
            "search_wait_copy": "Wait",
            "search_running_title": "Search in progress",
            "search_running_copy": "Copy",
            "search_starting_title": "Starting search",
            "search_starting_copy": "Copy",
            "search_refreshing_title": "Refreshing workspace",
            "search_refreshing_copy": "Copy",
            "search_running_subcopy": "Copy",
            "search_starting_subcopy": "Copy",
            "search_stop_label": "Stop search",
            "search_progress_prefix": "Current step:",
            "search_stopping_title": "Stopping search",
            "search_stopping_copy": "Copy",
            "search_stopping_subcopy": "Copy",
        },
    }
    set_knowledge("ui_labels", stale, isolated_db)

    updated = upgrade_knowledge_from_dir(knowledge_dir, isolated_db)
    assert "ui_labels" in updated

    html = build_bootstrap_script()
    assert "__JOB_HUNTER_SHARED_UI_LABELS__" in html


def test_build_bootstrap_script_includes_all_ui_label_sections():
    """Smoke test: the render path must include every ui_labels section.

    Any future section added to ui_labels.json that is wired into
    build_bootstrap_script() will show up here as a failing assertion
    before it ever reaches production.
    """
    from job_hunter_agent.server_helpers import build_bootstrap_script

    html = build_bootstrap_script()
    for sentinel in (
        "__JOB_HUNTER_ONBOARDING_FLOW_LABELS__",
        "__JOB_HUNTER_ONBOARDING_PAGE_LABELS__",
        "__JOB_HUNTER_TITLE_TIER_LABELS__",
        "__JOB_HUNTER_CAPABILITY_UI_LABELS__",
        "__JOB_HUNTER_SHARED_UI_LABELS__",
        "__JOB_HUNTER_SETTINGS_ALERTS_LABELS__",
    ):
        assert sentinel in html, f"build_bootstrap_script() is missing {sentinel}"
