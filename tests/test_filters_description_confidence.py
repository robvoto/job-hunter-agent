"""Tests for filters description confidence."""

from job_hunter_agent import filters
from job_hunter_agent import hard_blocker_rules
from job_hunter_agent import signal_registry
from job_hunter_agent.paths import HARD_BLOCKER_RULES_PATH


REQUIREMENTS_ELICITATION_RULE = {
    "name": "requirements elicitation",
    "level": "strong",
    "fit": "core",
    "aliases": ["requirements elicitation", "requirements gathering"],
}

PROCESS_MAPPING_RULE = {
    "name": "process mapping",
    "level": "working",
    "fit": "core",
    "aliases": ["process mapping", "as-is", "to-be"],
}

AGILE_METHODS_RULE = {
    "name": "agile methodologies",
    "level": "strong",
    "fit": "core",
    "aliases": ["scrum", "kanban"],
}


def _load_profile(*, candidate_capabilities=None, reject_description_phrase_rules=None, must_not_require_skills=None, extra=None):
    profile = {
        "candidate_capabilities": candidate_capabilities or [],
        "reject_description_phrase_rules": reject_description_phrase_rules or [],
        "must_not_require_skills": must_not_require_skills or [],
    }
    if extra:
        profile.update(extra)
    return profile


def _hard_blocker_rules_path(tmp_path):
    return tmp_path / HARD_BLOCKER_RULES_PATH.name


def _write_hard_blocker_rules(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    hard_blocker_rules.HARD_BLOCKER_RULES_PATH = path
    return hard_blocker_rules.save_hard_blocker_rules(entries)


def test_generic_business_analyst_target_pattern_allows_common_ba_titles(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: _load_profile(extra={
            "target_roles": [r"\bbusiness\ analyst\b"],
            "also_consider_roles": [],
            "reject_title_rules": [],
        }),
    )

    ok_plain, reason_plain = filters.passes_title_filters("Business Analyst")
    ok_lead, reason_lead = filters.passes_title_filters("Lead Business Analyst")
    ok_ai, reason_ai = filters.passes_title_filters("Senior Business Analyst Senior (AI Foundations)")

    assert ok_plain is True
    assert reason_plain == "OK"
    assert ok_lead is True
    assert reason_lead == "OK"
    assert ok_ai is True
    assert reason_ai == "OK"


def test_approved_hard_blocker_rules_rejects_mandatory_requirement_text(tmp_path, monkeypatch):
    rules_path = _hard_blocker_rules_path(tmp_path)
    _write_hard_blocker_rules(rules_path, [{"value": "must have {term}", "aliases": []}])
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: _load_profile(must_not_require_skills=["SAP"]),
    )

    ok, reason = filters.passes_content_filters(
        "Must have SAP experience for this role.",
        title_reason="OK",
    )

    assert ok is False
    assert reason == "DESC_HARD_BLOCK_RULE:sap"


def test_approved_hard_blocker_rules_does_not_reject_desirable_only_text(tmp_path, monkeypatch):
    rules_path = _hard_blocker_rules_path(tmp_path)
    _write_hard_blocker_rules(rules_path, [{"value": "must have {term}", "aliases": []}])
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: _load_profile(must_not_require_skills=["SAP"]),
    )

    ok, reason = filters.passes_content_filters(
        "SAP experience would be desirable for this role.",
        title_reason="OK",
    )

    assert ok is True
    assert reason == "OK"


def test_pending_hard_blocker_pattern_does_not_affect_filtering(isolated_db, tmp_path, monkeypatch):
    rules_path = _hard_blocker_rules_path(tmp_path)
    signal_registry.save_registry(
        {
            "must have sap": {
                "signal": "must have sap",
                "normalized_key": "must have sap",
                "original_texts": ["must have sap experience"],
                "category": "hard_blocker_pattern",
                "suggested_category": "hard_blocker_pattern",
                "history": [{"action": "added", "timestamp": "2026-05-05T00:00:00+00:00"}],
            }
        }
    )
    _write_hard_blocker_rules(rules_path, [])
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: _load_profile(must_not_require_skills=["SAP"]),
    )

    ok, reason = filters.passes_content_filters(
        "Must have SAP experience for this role.",
        title_reason="OK",
    )

    assert ok is True
    assert reason == "OK"


def test_term_not_in_profile_does_not_reject_even_if_pattern_appears(tmp_path, monkeypatch):
    rules_path = _hard_blocker_rules_path(tmp_path)
    _write_hard_blocker_rules(rules_path, [{"value": "must have {term}", "aliases": []}])
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: _load_profile(),
    )

    ok, reason = filters.passes_content_filters(
        "Must have SAP experience for this role.",
        title_reason="OK",
    )

    assert ok is True
    assert reason == "OK"
