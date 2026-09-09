"""Tests for profile store llm guidance."""

import json

import pytest

from job_hunter_agent import llm_gate, profile_store, review_insights
from job_hunter_agent.io_utils import load_ui_labels


def test_save_profile_rejects_unknown_top_level_field(isolated_db):
    with pytest.raises(ValueError, match="unsupported top-level fields: llm_capability_naming_guidance"):
        profile_store.save_profile(
            {
                **profile_store.DEFAULT_PROFILE,
                "llm_capability_naming_guidance": "obsolete guidance",
            }
        )


def test_save_profile_does_not_persist_scoring_rules(isolated_db):
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.user_context import get_user_id_for_runtime

    profile_store.save_profile({**profile_store.DEFAULT_PROFILE})

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM user_profile WHERE user_id = ?", (get_user_id_for_runtime(),)
        ).fetchone()
    persisted = json.loads(row["data"])
    assert "scoring_rules" not in persisted


def test_save_profile_rejects_llm_classified_compound_capability(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.llm_validate_profile_capability_atomicity",
        lambda capabilities: [False for _ in capabilities],
    )

    with pytest.raises(ValueError, match="atomic concept"):
        profile_store.save_profile(
            {
                **profile_store.DEFAULT_PROFILE,
                "candidate_capabilities": [
                    {"name": "Power BI, Excel and GIS", "level": "working"}
                ],
            }
        )


def test_save_profile_calls_atomicity_validator_for_new_capability(isolated_db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_gate,
        "llm_validate_profile_capability_atomicity",
        lambda capabilities: calls.append(capabilities) or [True for _ in capabilities],
    )

    saved = profile_store.save_profile(
        {
            **profile_store.DEFAULT_PROFILE,
            "candidate_capabilities": [
                {"name": "Power BI", "level": "working"}
            ],
        }
    )

    assert len(calls) == 1
    assert calls[0][0]["name"] == saved["candidate_capabilities"][0]["name"]

    saved["candidate_capabilities"][0]["level"] = "basic"
    profile_store.save_profile(saved)

    assert len(calls) == 2


def test_save_profile_skips_only_explicitly_prevalidated_capability(isolated_db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_gate,
        "llm_validate_profile_capability_atomicity",
        lambda capabilities: calls.append(capabilities) or [True for _ in capabilities],
    )

    saved = profile_store.save_profile(
        {
            **profile_store.DEFAULT_PROFILE,
            "candidate_capabilities": [
                {"name": "Power BI", "level": "working"}
            ],
        },
        prevalidated_capability_names={"Power BI"},
    )

    assert calls == []

    saved["candidate_capabilities"].append({"name": "Excel", "level": "working"})
    profile_store.save_profile(
        saved,
        prevalidated_capability_names={"Power BI"},
    )

    assert len(calls) == 1
    assert [item["name"] for item in calls[0]] == ["excel"]


def test_save_profile_skips_atomicity_validator_for_unchanged_capabilities(
    isolated_db, monkeypatch
):
    monkeypatch.setattr(
        llm_gate,
        "llm_validate_profile_capability_atomicity",
        lambda capabilities: [True for _ in capabilities],
    )
    profile_store.save_profile(
        {
            **profile_store.DEFAULT_PROFILE,
            "candidate_capabilities": [
                {"name": "Power BI", "level": "working"}
            ],
        }
    )
    monkeypatch.setattr(llm_gate, "client", None)
    monkeypatch.setattr(
        llm_gate,
        "llm_validate_profile_capability_atomicity",
        lambda capabilities: pytest.fail("unchanged capabilities must not be validated"),
    )

    profile = profile_store.load_profile()
    profile["search_settings"]["date_range_days"] = 5
    profile_store.save_profile(profile)


def test_save_profile_unrelated_change_succeeds_without_llm_client(
    isolated_db, monkeypatch
):
    monkeypatch.setattr(
        llm_gate,
        "llm_validate_profile_capability_atomicity",
        lambda capabilities: [True for _ in capabilities],
    )
    profile_store.save_profile(
        {
            **profile_store.DEFAULT_PROFILE,
            "candidate_capabilities": [
                {"name": "Power BI", "level": "working"}
            ],
        }
    )
    monkeypatch.setattr(llm_gate, "client", None)

    profile = profile_store.load_profile()
    profile["salary_preferences"]["minimum_salary_yearly"] = 100000
    saved = profile_store.save_profile(profile)

    assert saved["salary_preferences"]["minimum_salary_yearly"] == 100000


def test_load_profile_rejects_unknown_top_level_field(isolated_db):
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.user_context import get_user_id_for_runtime

    user_id = get_user_id_for_runtime()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_profile (user_id, data) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data""",
            (user_id, json.dumps({"llm_profile_brief": "obsolete"})),
        )

    with pytest.raises(ValueError, match="unsupported top-level fields: llm_profile_brief"):
        profile_store.load_profile()


def test_normalize_full_profile_rejects_multiple_unknown_fields():
    with pytest.raises(
        ValueError,
        match="unsupported top-level fields: llm_profile_brief, llm_profile_brief_mode, star_evidence_text",
    ):
        profile_store.normalize_full_profile(
            {
                "llm_profile_brief_mode": "manual",
                "llm_profile_brief": "obsolete prompt text",
                "star_evidence_text": "obsolete evidence text",
            }
        )


def test_load_profile_rejects_removed_target_occupation_queries(isolated_db):
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.user_context import get_user_id_for_runtime

    user_id = get_user_id_for_runtime()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_profile (user_id, data) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data""",
            (user_id, json.dumps({"target_occupation_queries": ["Data Analyst"]})),
        )

    with pytest.raises(ValueError, match="unsupported top-level fields: target_occupation_queries"):
        profile_store.load_profile()


def test_load_profile_raises_for_non_object_data(isolated_db):
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.user_context import get_user_id_for_runtime

    user_id = get_user_id_for_runtime()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_profile (user_id, data) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data""",
            (user_id, json.dumps([1, 2, 3])),
        )

    with pytest.raises(profile_store.ProfileLoadError):
        profile_store.load_profile()


def test_default_profile_declares_current_rejection_rule_fields():
    assert profile_store.DEFAULT_PROFILE["reject_title_rules"] == []
    assert profile_store.DEFAULT_PROFILE["reject_description_phrase_rules"] == []
    assert "candidate_eligibility" in profile_store.DEFAULT_PROFILE


def test_normalize_capability_rules_preserves_needs_review_when_aliases_exist():
    rules = profile_store.normalize_capability_rules(
        [
            {
                "name": "Agile delivery",
                "level": "working",
                "aliases": ["scrum"],
                "needs_review": False,
            }
        ]
    )

    assert rules[0]["aliases"] == ["scrum"]
    assert rules[0]["needs_review"] is True


def test_normalize_eligibility_rules_preserves_positive_and_negative_facts():
    rules = profile_store.normalize_eligibility_rules(
        [
            {"name": "PV clearance", "value": True, "evidence": ["Baseline Security Clearance"]},
            {"name": "AHPRA registration", "value": False, "evidence": []},
        ]
    )

    assert rules[0]["name"] == "PV clearance"
    assert rules[0]["value"] is True
    assert rules[0]["evidence"] == ["Baseline Security Clearance"]
    assert rules[1]["name"] == "AHPRA registration"
    assert rules[1]["value"] is False


def test_selecting_nv2_implies_holding_nv1_and_baseline():
    rules = profile_store.normalize_eligibility_rules(
        [
            {"name": "Baseline", "value": False, "evidence": []},
            {"name": "NV1", "value": False, "evidence": []},
            {"name": "NV2", "value": True, "evidence": []},
        ]
    )

    by_name = {rule["name"]: rule["value"] for rule in rules}
    assert by_name == {"Baseline": True, "NV1": True, "NV2": True}


def test_clearance_hierarchy_never_downgrades_an_explicit_true():
    # Baseline is explicitly held even though nothing higher is held — the
    # upward-only invariant must never turn a submitted True into False.
    rules = profile_store.apply_clearance_hierarchy(
        [
            {"name": "Baseline", "value": True, "evidence": []},
            {"name": "NV1", "value": False, "evidence": []},
            {"name": "NV2", "value": False, "evidence": []},
        ]
    )

    by_name = {rule["name"]: rule["value"] for rule in rules}
    assert by_name == {"Baseline": True, "NV1": False, "NV2": False}


def test_clearance_hierarchy_ignores_rows_not_present_in_the_submitted_list():
    # A caller that only submits PV clearance and an unrelated eligibility fact
    # must not have Baseline/NV1/NV2 rows invented for it.
    rules = profile_store.apply_clearance_hierarchy(
        [
            {"name": "PV clearance", "value": True, "evidence": []},
            {"name": "AHPRA registration", "value": False, "evidence": []},
        ]
    )

    assert [rule["name"] for rule in rules] == ["PV clearance", "AHPRA registration"]
    assert rules[0]["value"] is True
    assert rules[1]["value"] is False


def test_capability_level_tokens_and_display_labels_are_standardized():
    labels = load_ui_labels()["level_labels"]

    assert profile_store.LEVEL_STRONG == "strong"
    assert profile_store.LEVEL_WORKING == "working"
    assert profile_store.LEVEL_BASIC == "basic"
    assert labels["strong"] == "Strong"
    assert labels["working"] == "Working"
    assert labels["basic"] == "Basic"


def test_apply_capability_tuning_decisions_uses_internal_level_tokens():
    profile = {"candidate_capabilities": []}

    updated = review_insights.apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working"}],
    )

    assert updated["candidate_capabilities"][0]["level"] == "working"


def test_apply_capability_tuning_decisions_preserves_aliases():
    profile = {"candidate_capabilities": []}

    updated = review_insights.apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", "aliases": ["workflow design"]}],
    )

    assert updated["candidate_capabilities"][0]["aliases"] == ["workflow design"]


def test_apply_capability_tuning_decisions_rejects_legacy_low_choice():
    profile = {"candidate_capabilities": []}

    updated = review_insights.apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "low"}],
    )

    assert updated["candidate_capabilities"] == []


_ROUTING_FIXTURE = {
    "candidate_profile_section_routing": {
        "default_bucket": "primary_candidate_profile_context",
        "primary_labels": ["primary", "current", "main"],
        "secondary_labels": ["supporting"],
        "supplementary_labels": ["background", "education"],
    }
}


def test_classify_candidate_profile_section_label_uses_parsing_rules(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)

    assert (
        profile_store.classify_candidate_profile_section_label("Supporting Background")
        == "secondary_candidate_profile_context"
    )
    assert (
        profile_store.classify_candidate_profile_section_label("Education")
        == "supplementary_candidate_profile_context"
    )
    assert (
        profile_store.classify_candidate_profile_section_label("Main CV")
        == "primary_candidate_profile_context"
    )


def test_classify_unknown_section_label_llm_confident(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)

    captured = {}

    def fake_classify(label, llm_client=None):
        captured["label"] = label
        return {"bucket": "secondary", "confident": True}

    def fake_upsert(word, bucket):
        captured["upserted"] = (word, bucket)

    monkeypatch.setattr("job_hunter_agent.llm_gate.llm_classify_section_label", fake_classify)
    monkeypatch.setattr(
        "job_hunter_agent.signal_registry.upsert_profile_section_label", fake_upsert
    )

    result = profile_store.classify_candidate_profile_section_label("Career History")
    assert result == "secondary_candidate_profile_context"
    assert captured["upserted"] == ("career history", "secondary")


def test_classify_unknown_section_label_llm_uncertain(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)

    registered = []

    def fake_classify(label, llm_client=None):
        return {"bucket": "primary", "confident": False}

    def fake_register(signals):
        registered.extend(signals)

    monkeypatch.setattr("job_hunter_agent.llm_gate.llm_classify_section_label", fake_classify)
    monkeypatch.setattr("job_hunter_agent.signal_registry.register_signals", fake_register)

    result = profile_store.classify_candidate_profile_section_label("Overview")
    assert result == "primary_candidate_profile_context"
    assert len(registered) == 1
    assert registered[0]["category"] == "profile_section_label"
    assert registered[0]["suggested_values"] == ["primary"]


def test_classify_unknown_section_label_llm_unavailable(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)
    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.llm_classify_section_label", lambda label, llm_client=None: None
    )

    result = profile_store.classify_candidate_profile_section_label("Overview")
    assert result == "primary_candidate_profile_context"
