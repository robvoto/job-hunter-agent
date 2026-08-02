"""Tests for knowledge_store: get, set, seed, and idempotency."""

import json
import subprocess

import pytest

from job_hunter_agent.database import init_db
from job_hunter_agent.knowledge_store import (
    get_knowledge,
    seed_knowledge_from_dir,
    set_knowledge,
    upgrade_knowledge_from_dir,
)
from job_hunter_agent.runtime_seed_manifest import (
    APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
    resolve_seed_json_paths,
)
from job_hunter_agent.server_helpers import (
    _CAPABILITY_UI_LABEL_KEYS,
    _ONBOARDING_FLOW_LABEL_KEYS,
    _ONBOARDING_PAGE_LABEL_KEYS,
    _SETTINGS_ALERTS_LABEL_KEYS,
    _SHARED_UI_LABEL_KEYS,
    load_onboarding_flow_labels,
)

_UI_LABEL_SECTION_KEYS = {
    "onboarding_flow_labels": _ONBOARDING_FLOW_LABEL_KEYS,
    "onboarding_page_labels": _ONBOARDING_PAGE_LABEL_KEYS,
    "capability_ui_labels": _CAPABILITY_UI_LABEL_KEYS,
    "shared_ui_labels": _SHARED_UI_LABEL_KEYS,
    "settings_alerts_labels": _SETTINGS_ALERTS_LABEL_KEYS,
}

# Keys the loader composes at runtime from another canonical section instead of
# storing a second literal copy in the section's own JSON block (see
# load_capability_ui_labels, load_onboarding_flow_labels, and
# load_onboarding_page_labels in server_helpers.py).
_UI_LABEL_SECTION_KEYS_COMPOSED_AT_RUNTIME = {
    "onboarding_flow_labels": {
        "capability_select_shown_label",
        "capability_clear_selection_label",
        "capability_remove_selected_label",
    },
    "capability_ui_labels": {
        "settings_select_shown_label",
        "settings_clear_selection_label",
        "settings_remove_selected_label",
    },
    "onboarding_page_labels": {
        "locations_label",
        "work_type_label",
        "work_mode_label",
    },
    "settings_alerts_labels": {
        "telegram_subscribers_empty",
    },
}


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
    seeded = seed_knowledge_from_dir(
        knowledge_dir,
        tmp_db,
        json_files=resolve_seed_json_paths(knowledge_dir, APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS),
    )
    assert len(seeded) == len(APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS), (
        f"Expected {len(APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS)} knowledge files, got {len(seeded)}: {seeded}"
    )


def test_seed_can_use_explicit_allowlist_to_skip_unapproved_json(tmp_db, knowledge_dir):
    approved = knowledge_dir / "approved.json"
    stray = knowledge_dir / "private_example.json"
    approved.write_text('{"v": 1}', encoding="utf-8")
    stray.write_text('{"v": 2}', encoding="utf-8")

    seeded = seed_knowledge_from_dir(knowledge_dir, tmp_db, json_files=[approved])

    assert seeded == ["approved"]
    assert get_knowledge("approved", tmp_db) == {"v": 1}
    assert get_knowledge("private_example", tmp_db) is None


def test_upgrade_seeds_missing_key(tmp_db, knowledge_dir):
    (knowledge_dir / "rules.json").write_text(
        '{"version": 1, "entries": [{"value": "A"}]}', encoding="utf-8"
    )
    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert updated == ["rules"]
    assert get_knowledge("rules", tmp_db)["entries"][0]["value"] == "A"


def test_upgrade_skips_when_version_current_for_additive_knowledge(tmp_db, knowledge_dir):
    data = {"version": 2, "entries": [{"value": "A"}]}
    set_knowledge("rules", data, tmp_db)
    (knowledge_dir / "rules.json").write_text(
        '{"version": 2, "entries": [{"value": "B"}]}', encoding="utf-8"
    )
    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)
    assert updated == []
    assert get_knowledge("rules", tmp_db)["entries"][0]["value"] == "A"


def test_upgrade_same_version_config_replaces_when_payload_differs(tmp_db, knowledge_dir):
    set_knowledge("config", {"version": 2, "threshold": 0.5}, tmp_db)
    (knowledge_dir / "config.json").write_text('{"version": 2, "threshold": 0.8}', encoding="utf-8")

    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)

    assert updated == ["config"]
    assert get_knowledge("config", tmp_db)["threshold"] == 0.8


def test_upgrade_same_version_config_skips_when_payload_matches(tmp_db, knowledge_dir):
    payload = {"version": 2, "threshold": 0.5}
    set_knowledge("config", payload, tmp_db)
    (knowledge_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    updated = upgrade_knowledge_from_dir(knowledge_dir, tmp_db)

    assert updated == []
    assert get_knowledge("config", tmp_db) == payload


def test_upgrade_skips_when_db_version_ahead(tmp_db, knowledge_dir):
    set_knowledge("rules", {"version": 5, "entries": [{"value": "A"}]}, tmp_db)
    (knowledge_dir / "rules.json").write_text(
        '{"version": 3, "entries": [{"value": "B"}]}', encoding="utf-8"
    )
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
    set_knowledge(
        "rules", {"version": 1, "entries": [{"value": "A"}, {"value": "UserApproved"}]}, tmp_db
    )
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


def test_ui_labels_json_contains_required_onboarding_and_server_keys():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    data = json.loads(
        (repo_root / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8")
    )
    missing = {
        section: [
            key
            for key in keys
            if key not in _UI_LABEL_SECTION_KEYS_COMPOSED_AT_RUNTIME.get(section, set())
            and not str(data.get(section, {}).get(key, "")).strip()
        ]
        for section, keys in _UI_LABEL_SECTION_KEYS.items()
    }
    missing = {section: keys for section, keys in missing.items() if keys}

    assert not missing, f"ui_labels.json is missing required keys: {missing}"


def test_seed_rejects_mojibake_ui_labels(tmp_db, knowledge_dir):
    bad_ui_labels = {
        "kind": "ui_labels",
        "name": "ui_labels",
        "version": 43,
        "workspace_page_labels": {
            "hero_title": "Build your job profile",
            "results_helper_copy": "If a title clearly doesnâ€™t match what you want, block it.",
        },
    }
    (knowledge_dir / "ui_labels.json").write_text(json.dumps(bad_ui_labels), encoding="utf-8")

    with pytest.raises(ValueError, match="mojibake"):
        seed_knowledge_from_dir(knowledge_dir, tmp_db)


def test_load_ui_labels_rejects_mojibake_from_db(tmp_db, monkeypatch):
    from job_hunter_agent.io_utils import load_ui_labels

    set_knowledge(
        "ui_labels",
        {
            "kind": "ui_labels",
            "name": "ui_labels",
            "version": 43,
            "workspace_page_labels": {
                "hero_title": "Build your job profile",
                "results_helper_copy": "If a title clearly doesnâ€™t match what you want, block it.",
            },
        },
        tmp_db,
    )
    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(tmp_db))

    with pytest.raises(ValueError, match="mojibake"):
        load_ui_labels()


def test_ui_labels_json_version_bumps_when_contents_change():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    ui_labels_path = repo_root / "data" / "knowledge" / "ui_labels.json"
    current = json.loads(ui_labels_path.read_text(encoding="utf-8"))
    head_text = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show",
            f"HEAD:{ui_labels_path.relative_to(repo_root).as_posix()}",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    head = json.loads(head_text)

    if current != head:
        assert int(current["version"]) > int(head["version"]), (
            "ui_labels.json changed but its version was not bumped"
        )


def test_match_level_defaults_loaded_from_db(tmp_db):
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    seed_knowledge_from_dir(
        repo_root / "data" / "knowledge",
        tmp_db,
        json_files=resolve_seed_json_paths(
            repo_root / "data" / "knowledge",
            APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
        ),
    )
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
            "account_menu_clean_search_label": "Clean Search",
            "account_menu_reset_user_label": "Reset User",
            "add_button_label": "+",
            "add_button_aria_label": "Add item",
            "add_button_title": "+",
            "search_wait_copy": "Wait",
            "search_wait_why_label": "Why this takes time",
            "search_wait_why_intro": "Why",
            "search_wait_why_browser": "Browser",
            "search_wait_why_pacing": "Pacing",
            "search_wait_why_details": "Details",
            "search_wait_why_scoring": "Scoring",
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


def test_upgrade_fixes_stale_ui_labels_missing_workspace_labels(isolated_db):
    from pathlib import Path

    from job_hunter_agent.knowledge_store import get_knowledge
    from job_hunter_agent.workspace_renderer import _workspace_ui_labels, load_workspace_page_labels

    repo_root = Path(__file__).resolve().parent.parent
    knowledge_dir = repo_root / "data" / "knowledge"

    stale = {
        "kind": "ui_labels",
        "name": "ui_labels",
        "version": 20,
        "workspace_page_labels": {
            "hero_title": "Jobs Workspace",
            "potential_jobs_tab": "Potential Jobs",
            "applied_jobs_tab": "Applied",
            "hidden_jobs_tab": "Hidden",
            "match_controls_heading": "Match Controls",
            "reset_all_filters_button": "Reset All Filters",
            "sort_label": "Sort",
            "sort_option_best_match": "Best match first",
            "sort_option_newest": "Newest posted first",
            "sort_option_highest_salary": "Highest salary first",
            "jobs_per_page_label": "Jobs Per page",
            "filters_label": "Filters",
            "show_label": "Show",
            "show_option_all_potential": "All potential jobs",
            "show_option_matches_last_run": "Matches last run",
            "posted_label": "Posted",
            "type_label": "Type",
            "work_mode_label": "Work mode",
            "work_mode_option_any": "Any",
            "work_mode_option_remote": "Remote",
            "work_mode_option_hybrid": "Hybrid",
            "work_mode_option_on_site": "On-site",
            "sector_label": "Sector",
            "sector_option_any": "Any sector",
            "sector_option_public": "Public sector",
            "sector_option_private": "Private sector",
            "match_level_label": "Match level",
            "potential_jobs_empty_state": "No shortlist matches right now. Check your filters or broaden your search settings.",
            "results_helper_copy": "Job sites often return broad results even when the search is correct. If a title clearly doesn't match what you want, you can block similar roles directly from the title. This helps remove repeated noise from future results.",
            "results_helper_dismiss_button": "Dismiss",
            "applied_jobs_heading": "Applied Jobs",
            "applied_jobs_copy": "This area is for jobs where you have already sent your CV. They are tracked separately so they do not clutter the live shortlist.",
            "hidden_jobs_heading": "Hidden Jobs",
            "hidden_jobs_copy": "This area keeps roles you have intentionally pushed out of sight for now.",
            "search_settings_heading": "Search Settings",
            "search_settings_helper": "Shared search settings used across sources.",
            "keywords_label": "Keywords",
            "locations_label": "Locations",
            "work_type_sidebar_label": "Work type",
            "work_mode_sidebar_label": "Work mode",
            "sector_sidebar_label": "Sector",
            "salary_min_label": "Salary min",
            "date_range_label": "Date range",
            "last_run_heading": "Last Run",
            "last_run_cards_seen_label": "Jobs found",
            "last_run_details_checked_label": "Job details checked",
            "last_run_accepted_label": "Accepted",
            "last_run_rejected_label": "Rejected",
            "last_run_llm_cost_label": "LLM cost",
            "last_run_input_tokens_label": "Input tokens",
            "last_run_output_tokens_label": "Output tokens",
            "workspace_status_heading": "Workspace",
            "workspace_status_helper": "These counts describe the jobs currently in your workspace.",
            "workspace_visible_label": "Visible matches",
            "workspace_new_label": "New to you",
            "workspace_opened_label": "Opened by you",
            "workspace_saved_label": "Saved from earlier run",
            "lifetime_llm_heading": "Total LLM usage",
            "lifetime_llm_helper": "Total recorded LLM usage.",
            "lifetime_llm_cost_label": "Total LLM cost",
            "lifetime_input_tokens_label": "Total input tokens",
            "lifetime_output_tokens_label": "Total output tokens",
            "run_efficiency_summary": "Run Efficiency",
            "show_hide_hint": "Show / hide",
            "run_efficiency_intro": "Search targets this run: ",
        },
    }
    set_knowledge("ui_labels", stale, isolated_db)

    updated = upgrade_knowledge_from_dir(knowledge_dir, isolated_db)
    assert "ui_labels" in updated

    _workspace_ui_labels.cache_clear()
    labels = load_workspace_page_labels()
    assert labels["LABEL_WS_RUN_EFFICIENCY_SEPARATOR"] == "."
    import json
    from pathlib import Path

    expected_version = json.loads(
        (Path(__file__).parent.parent / "data" / "knowledge" / "ui_labels.json").read_text()
    )["version"]
    assert get_knowledge("ui_labels", isolated_db)["version"] == expected_version


def test_create_app_bootstrap_refreshes_stale_ui_labels(isolated_db):
    from pathlib import Path

    from job_hunter_agent.fastapi_app import create_app

    repo_root = Path(__file__).resolve().parent.parent
    ui_labels_path = repo_root / "data" / "knowledge" / "ui_labels.json"
    current_version = int(json.loads(ui_labels_path.read_text(encoding="utf-8"))["version"])

    stale = {
        "kind": "ui_labels",
        "name": "ui_labels",
        "version": current_version - 1,
        "onboarding_flow_labels": {
            "create_profile_error": "Could not create profile",
        },
    }
    set_knowledge("ui_labels", stale, isolated_db)

    create_app()

    refreshed = get_knowledge("ui_labels", isolated_db)
    assert refreshed["version"] == current_version
    assert (
        load_onboarding_flow_labels()["review_capability_helper_copy"]
        == "Review the capability groups extracted from your CV."
    )


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
        "__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__",
        "__JOB_HUNTER_CLEARANCE_OPTIONS__",
    ):
        assert sentinel in html, f"build_bootstrap_script() is missing {sentinel}"


def test_onboarding_flow_labels_include_clean_search_confirm_copy():
    labels = load_onboarding_flow_labels()

    assert labels["clean_search_confirm_title"] == "Clear search results?"
    assert "current job results" in labels["clean_search_confirm_body_1"]
    assert "saved preferences" in labels["clean_search_confirm_body_2"]
    assert labels["clean_search_error"] == "Could not clear search results."
