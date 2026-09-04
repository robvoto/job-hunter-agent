"""Regression coverage for the canonical requirement `decomposition` contract.

Covers the AND / OR operator semantics, the per-element `capability_judgement`
axis, the optional / mandatory `non_capability` handling, and the OR-branch
UI + blocker/gap guarantees described in
docs/REQUIREMENT_DECOMPOSITION_RATIONALE.md.
"""

from __future__ import annotations

import json

from job_hunter_agent import llm_gate, source_learning, workspace_renderer
from job_hunter_agent.paths import SCORING_RULES_PATH
from job_hunter_agent.profile_gaps import (
    CUSTOM_BLOCKER_REASON_NO_MATCH,
    compute_profile_gaps,
    resolve_custom_blocker,
)
from job_hunter_agent.record_schema import (
    RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)


def _single(concept: str, *, resolved: bool = True, status: str = "not_shown") -> dict:
    return {
        "operator": "single",
        "elements": [
            {
                "text": concept,
                "capability_judgement": "capability",
                "canonical_concept": concept,
                "canonical_fact_resolved": resolved,
                "status": status,
            }
        ],
    }


def _or(*concepts: str, status: str = "not_shown") -> dict:
    return {
        "operator": "or",
        "elements": [
            {
                "text": concept,
                "capability_judgement": "capability",
                "canonical_concept": concept,
                "canonical_fact_resolved": True,
                "status": status,
            }
            for concept in concepts
        ],
    }


def _normalize(item: dict, **kwargs) -> list[dict]:
    return llm_gate.normalize_llm_requirement_coverage([item], **kwargs)


# --------------------------------------------------------------------------- #
# single
# --------------------------------------------------------------------------- #


def test_single_capability_gap_surfaces_exact_concept_and_not_when_present():
    item = {
        "requirement": "Experience with Microsoft Purview",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "Microsoft Purview",
        "decomposition": _single("Microsoft Purview"),
        "status": "not_shown",
        "matched_job_text": "Experience with Microsoft Purview",
    }
    coverage = _normalize(item, valid_capability_names={})

    assert coverage[0]["decomposition"]["operator"] == "single"
    assert coverage[0]["profile_action_allowed"] is True

    absent = compute_profile_gaps(coverage, [], [])
    assert [gap["capability_name"] for gap in absent] == ["Microsoft Purview"]

    present = compute_profile_gaps(
        coverage,
        [{"name": "Microsoft Purview", "level": "working"}],
        [],
    )
    assert present == []


def test_single_row_adjacent_matched_fact_is_not_credited_as_exact_concept():
    item = {
        "requirement": "IT systems and infrastructure project management",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "IT infrastructure project management",
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": "IT systems and infrastructure project management",
                    "capability_judgement": "capability",
                    "canonical_concept": "IT infrastructure project management",
                    "canonical_fact_resolved": True,
                    "status": "partially_supported",
                    "matched_candidate_fact": "Agile delivery management",
                }
            ],
        },
        "status": "partially_supported",
        "matched_candidate_fact": "Agile delivery management",
    }
    coverage = _normalize(item, valid_capability_names={})

    # The adjacent "Agile delivery management" fact must not satisfy the exact
    # requested concept: it is still surfaced as a gap for the requested name.
    gaps = compute_profile_gaps(
        coverage,
        [{"name": "Agile delivery management", "level": "strong"}],
        [],
    )
    assert [gap["capability_name"] for gap in gaps] == ["IT infrastructure project management"]


# --------------------------------------------------------------------------- #
# or
# --------------------------------------------------------------------------- #


def _or_record(coverage: list[dict]) -> dict:
    return {
        "job_key": "decomp-or",
        "title": "Data Governance Lead",
        "company": "Acme",
        "url": "https://example.com/job",
        "title_reason": "OK",
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "full_description": "Experience with Microsoft Purview or BigID",
        "fit_highlights": [],
        "source": "seek",
        "requirement_coverage": coverage,
    }


def _render_profile() -> dict:
    return {
        "candidate_capabilities": [],
        "dominant_signal_clusters": [],
        "match_preferences": {"home_location": "Sydney NSW"},
        "preference_weights": {},
        "salary_preferences": {},
        "scoring_rules": json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8")),
    }


def test_or_row_neither_branch_in_profile_is_not_row_actionable_but_keeps_branches():
    item = {
        "requirement": "Experience with Microsoft Purview or BigID",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": _or("Microsoft Purview", "BigID"),
        "status": "supported",  # LLM over-stated; rollup must correct it
        "matched_job_text": "Experience with Microsoft Purview or BigID",
    }
    coverage = _normalize(item, valid_capability_names={})
    row = coverage[0]

    assert row["decomposition"]["operator"] == "or"
    assert row["canonical_requirement"] == ""
    assert row["profile_action_allowed"] is False
    # OR rollup = strongest branch; both branches not_shown.
    assert row["status"] == "not_shown"
    assert [el["canonical_concept"] for el in row["decomposition"]["elements"]] == [
        "Microsoft Purview",
        "BigID",
    ]
    assert all(
        el["element_profile_action_allowed"] is True
        for el in row["decomposition"]["elements"]
    )


def test_or_row_rolls_up_to_supported_when_one_branch_is_supported():
    # The LLM reports the row as satisfied by the branch that matched (row-level
    # status + matched_candidate_fact name that branch); the elements carry the
    # per-branch detail. The OR rollup keeps the strongest branch status, and the
    # row still never becomes profile-actionable (no row-level canonical concept).
    item = {
        "requirement": "Experience with Microsoft Purview or BigID",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "matched_candidate_fact": "BigID",
        "decomposition": {
            "operator": "or",
            "elements": [
                {
                    "text": "Microsoft Purview",
                    "capability_judgement": "capability",
                    "canonical_concept": "Microsoft Purview",
                    "canonical_fact_resolved": True,
                    "status": "not_shown",
                },
                {
                    "text": "BigID",
                    "capability_judgement": "capability",
                    "canonical_concept": "BigID",
                    "canonical_fact_resolved": True,
                    "status": "supported",
                    "matched_candidate_fact": "BigID",
                },
            ],
        },
        "status": "supported",
        "matched_job_text": "Experience with Microsoft Purview or BigID",
    }
    coverage = _normalize(item, valid_capability_names={"bigid": "BigID"})
    assert coverage[0]["status"] == "supported"
    assert coverage[0]["profile_action_allowed"] is False
    assert coverage[0]["canonical_requirement"] == ""


def test_or_card_names_every_branch_and_shows_one_primary_add_action():
    item = {
        "requirement": "Experience with Microsoft Purview or BigID",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": _or("Microsoft Purview", "BigID"),
        "status": "not_shown",
        "matched_job_text": "Experience with Microsoft Purview or BigID",
    }
    coverage = _normalize(item, valid_capability_names={})
    html = workspace_renderer.render_job_card(_or_record(coverage), _render_profile())

    # Both branch concepts are named and the "either / or" relationship is stated.
    assert "Microsoft Purview" in html
    assert "BigID" in html
    assert "Either Microsoft Purview or BigID satisfies this requirement." in html
    # Exactly one primary Add action, for the first (closest) branch.
    assert html.count('data-action="confirm_have"') == 1
    assert 'data-capability-name="Microsoft Purview"' in html
    assert 'data-capability-name="BigID"' not in html


def test_or_branch_is_never_resolved_as_the_whole_mandatory_requirement():
    item = {
        "requirement": "Experience with Microsoft Purview or BigID",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": _or("Microsoft Purview", "BigID"),
        "status": "not_shown",
        "matched_job_text": "Experience with Microsoft Purview or BigID",
    }
    coverage = _normalize(item, valid_capability_names={})

    # A free-text "not for me" blocker naming one branch must not resolve.
    result = resolve_custom_blocker("Microsoft Purview", coverage)
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NO_MATCH

    # And the OR row is never surfaced as a single-concept profile gap.
    assert compute_profile_gaps(coverage, [], []) == []


# --------------------------------------------------------------------------- #
# and
# --------------------------------------------------------------------------- #


def test_and_row_status_cannot_exceed_weakest_element_status():
    item = {
        "requirement": "Write user stories and acceptance criteria",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "and",
            "elements": [
                {
                    "text": "user stories",
                    "capability_judgement": "capability",
                    "canonical_concept": "User stories",
                    "canonical_fact_resolved": True,
                    "status": "supported",
                },
                {
                    "text": "acceptance criteria",
                    "capability_judgement": "capability",
                    "canonical_concept": "Acceptance criteria",
                    "canonical_fact_resolved": True,
                    "status": "not_shown",
                },
            ],
        },
        "status": "supported",  # LLM over-stated the compound row
        "matched_job_text": "Write user stories and acceptance criteria",
    }
    coverage = _normalize(item, valid_capability_names={})
    row = coverage[0]

    assert row["status"] == "not_shown"
    assert row["profile_action_allowed"] is False
    assert row["canonical_requirement"] == ""


# --------------------------------------------------------------------------- #
# capability_judgement axis
# --------------------------------------------------------------------------- #


def _learning_record(coverage: list[dict], hidden: list[dict] | None = None) -> dict:
    return {
        "title": "Business Analyst",
        "company": "Acme",
        RECORD_REQUIREMENT_COVERAGE_KEY: coverage,
        RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY: hidden or [],
    }


def test_uncertain_element_yields_pending_capability_concept_signal(monkeypatch):
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )
    item = {
        "requirement": "Responsible AI governance exposure",
        "importance": "preferred",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": "Responsible AI governance",
                    "capability_judgement": "uncertain",
                    "canonical_concept": "Responsible AI governance",
                    "canonical_fact_resolved": False,
                    "status": "not_shown",
                }
            ],
        },
        "status": "not_shown",
        "matched_job_text": "Responsible AI governance exposure",
    }
    coverage = _normalize(item, valid_capability_names={})

    # Row still scores normally on its status, never becomes profile-actionable.
    assert coverage[0]["profile_action_allowed"] is False
    assert coverage[0]["status"] == "not_shown"

    signals = source_learning.build_ad_learning_signals(
        _learning_record(coverage), "Responsible AI governance exposure", profile={}
    )
    assert {
        "signal": "Responsible AI governance",
        "suggested_category": "capability_concept",
        "original_texts": ["Responsible AI governance", "Responsible AI governance exposure"],
    } in signals


def test_optional_non_capability_row_is_hidden_but_retained():
    non_capability_row = {
        "requirement": "Be a collaborative team player who thrives on ambiguity",
        "importance": "preferred",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": "collaborative team player who thrives on ambiguity",
                    "capability_judgement": "non_capability",
                    "canonical_concept": "",
                    "canonical_fact_resolved": False,
                    "status": "not_shown",
                }
            ],
        },
        "status": "not_shown",
        "matched_job_text": "Be a collaborative team player who thrives on ambiguity",
    }
    real_row = {
        "requirement": "Experience with stakeholder management",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "Stakeholder management",
        "decomposition": _single("Stakeholder management", status="not_shown"),
        "status": "not_shown",
        "matched_job_text": "Experience with stakeholder management",
    }
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "SOLID",
            "requirement_coverage": [non_capability_row, real_row],
        },
        valid_capability_names={},
    )

    assert [row["requirement"] for row in payload["requirement_coverage"]] == [
        "Experience with stakeholder management"
    ]
    assert len(payload["requirement_coverage_hidden"]) == 1
    assert payload["requirement_coverage_hidden"][0]["hidden_reason"] == "optional_non_capability"


def test_mandatory_non_capability_with_resolved_concept_is_actionable():
    item = {
        "requirement": "Own the incident bridge",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": "incident bridge ownership",
                    "capability_judgement": "non_capability",
                    "canonical_concept": "Incident management",
                    "canonical_fact_resolved": True,
                    "status": "not_shown",
                }
            ],
        },
        "status": "not_shown",
        "matched_job_text": "Own the incident bridge",
    }
    coverage = _normalize(item, valid_capability_names={})
    row = coverage[0]

    assert row["canonical_requirement"] == "Incident management"
    assert row["profile_action_allowed"] is True
    assert "mandatory_non_capability_unresolved" not in row


def test_mandatory_non_capability_without_safe_concept_stays_visible_and_pending(monkeypatch):
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )
    item = {
        "requirement": "Be the glue across the delivery org",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": "be the glue across the delivery org",
                    "capability_judgement": "non_capability",
                    "canonical_concept": "",
                    "canonical_fact_resolved": False,
                    "status": "not_shown",
                }
            ],
        },
        "status": "not_shown",
        "matched_job_text": "Be the glue across the delivery org",
    }
    coverage = _normalize(item, valid_capability_names={})
    row = coverage[0]

    assert row["profile_action_allowed"] is False
    assert row["status"] == "not_shown"
    assert row["mandatory_non_capability_unresolved"] is True

    signals = source_learning.build_ad_learning_signals(
        _learning_record(coverage), "Be the glue across the delivery org", profile={}
    )
    assert any(
        sig["suggested_category"] == "capability_concept"
        and sig["signal"] == "be the glue across the delivery org"
        for sig in signals
    )


def test_no_removed_decomposition_fields_survive_normalization():
    item = {
        "requirement": "A degree or equivalent experience",
        "importance": "mandatory",
        "requirement_type": "qualification",
        "canonical_requirement": "",
        "decomposition": _or("Bachelor degree", "Equivalent experience"),
        "status": "not_shown",
        "matched_job_text": "A degree or equivalent experience",
    }
    coverage = _normalize(item, valid_qualification_names={})
    row = coverage[0]

    for dead_field in ("named_alternatives", "classification_reviewable"):
        assert dead_field not in row
