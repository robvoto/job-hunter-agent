"""Regression coverage for the canonical requirement `decomposition` contract.

Covers the AND / OR operator semantics, the per-element `capability_judgement`
axis, the optional / mandatory `non_capability` handling, and the OR-branch
UI + blocker/gap guarantees described in
docs/REQUIREMENT_DECOMPOSITION_RATIONALE.md.
"""

from __future__ import annotations

import json
from html import unescape

from job_hunter_agent import llm_gate, source_learning, workspace_renderer
from job_hunter_agent.paths import SCORING_RULES_PATH
from job_hunter_agent.profile_gaps import (
    CUSTOM_BLOCKER_REASON_NO_MATCH,
    compute_profile_gaps,
    resolve_custom_blocker,
)
from job_hunter_agent.record_schema import (
    RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY,
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


def _normalize(
    item: dict,
    *,
    default_capability_kind: str | None = "professional_capability",
    **kwargs,
) -> list[dict]:
    """Normalize one raw coverage item.

    Fixtures written before the JH-298 requirement_kind axis build bare
    ``capability`` rows and rely on them being scored. Since the JH-298
    fail-closed correction a capability row with no requirement_kind becomes
    ``unclassified`` (non-scoring); to keep those fixtures on the scored path
    this helper stamps ``professional_capability`` on a capability item that
    does not set its own kind. Tests that exercise the missing / invalid kind
    axis pass ``default_capability_kind=None``.
    """
    if (
        default_capability_kind is not None
        and str(item.get("requirement_type") or "").strip().lower() == "capability"
        and not str(item.get("requirement_kind") or "").strip()
    ):
        item = {**item, "requirement_kind": default_capability_kind}
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


def test_card_does_not_render_capability_action_when_requirement_kind_is_missing():
    html = workspace_renderer.render_job_card(
        _or_record(
            [
                {
                    "requirement": "Excel experience",
                    "requirement_type": "capability",
                    "requirement_kind": "",
                    "canonical_requirement": "Excel",
                    "profile_action_allowed": True,
                    "status": "not_shown",
                    "matched_job_text": "Excel experience",
                    "decomposition": _single("Excel"),
                }
            ]
        ),
        _render_profile(),
    )

    assert 'data-action="confirm_have"' not in html
    assert 'data-action="confirm_do_not_have"' not in html


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


def test_or_card_names_every_branch_and_shows_each_unresolved_confirmation_pair():
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
    # Each named, unresolved professional capability branch gets its own pair.
    assert html.count('data-action="confirm_have"') == 2
    assert html.count('data-action="confirm_do_not_have"') == 2
    assert html.count('data-capability-name="Microsoft Purview"') == 2
    assert html.count('data-capability-name="BigID"') == 2
    assert "Add Microsoft Purview" in unescape(html)
    assert "Add BigID" in unescape(html)
    assert "No, I don't have this" in unescape(html)


def test_or_card_moves_confirmation_pair_to_next_unresolved_branch():
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
    profile = _render_profile()
    profile["must_not_require_skills"] = ["Microsoft Purview"]

    html = workspace_renderer.render_job_card(_or_record(coverage), profile)

    assert html.count('data-action="confirm_have"') == 1
    assert html.count('data-action="confirm_do_not_have"') == 1
    assert 'data-capability-name="Microsoft Purview"' not in html
    assert html.count('data-capability-name="BigID"') == 2


def test_or_card_keeps_unresolved_branch_action_when_another_branch_is_supported():
    item = {
        "requirement": "Experience with Microsoft Purview or BigID",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "or",
            "elements": [
                {
                    "text": "Microsoft Purview",
                    "capability_judgement": "capability",
                    "canonical_concept": "Microsoft Purview",
                    "canonical_fact_resolved": True,
                    "status": "supported",
                },
                {
                    "text": "BigID",
                    "capability_judgement": "capability",
                    "canonical_concept": "BigID",
                    "canonical_fact_resolved": True,
                    "status": "not_shown",
                },
            ],
        },
        "status": "supported",
        "matched_job_text": "Experience with Microsoft Purview or BigID",
    }
    coverage = _normalize(item, valid_capability_names={})

    html = workspace_renderer.render_job_card(_or_record(coverage), _render_profile())

    assert 'data-capability-name="Microsoft Purview"' not in html
    assert html.count('data-capability-name="BigID"') == 2



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
        "requirement_kind": "professional_capability",
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
        "requirement_kind": "professional_capability",
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


def test_mandatory_or_all_non_capability_branches_stay_visible_as_one_pending_signal(
    monkeypatch,
):
    # The exact hole: a mandatory OR requirement whose every branch is an
    # unresolved non_capability. It must stay fully visible, never become
    # profile-actionable, and raise exactly ONE pending capability_concept
    # Signal that keeps both branches and the OR relationship — never one
    # misleading capability minted from a single branch.
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )
    or_row = {
        "requirement": "Be a cultural fit or a mission-driven self-starter",
        "importance": "mandatory",
        "requirement_type": "capability",
        "requirement_kind": "professional_capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "or",
            "elements": [
                {
                    "text": "cultural fit",
                    "capability_judgement": "non_capability",
                    "canonical_concept": "",
                    "canonical_fact_resolved": False,
                    "status": "not_shown",
                },
                {
                    "text": "mission-driven self-starter",
                    "capability_judgement": "non_capability",
                    "canonical_concept": "",
                    "canonical_fact_resolved": False,
                    "status": "not_shown",
                },
            ],
        },
        "status": "not_shown",
        "matched_job_text": "Be a cultural fit or a mission-driven self-starter",
    }
    real_row = {
        "requirement": "Experience with stakeholder management",
        "importance": "mandatory",
        "requirement_type": "capability",
        "requirement_kind": "professional_capability",
        "canonical_requirement": "Stakeholder management",
        "decomposition": _single("Stakeholder management", status="not_shown"),
        "status": "not_shown",
        "matched_job_text": "Experience with stakeholder management",
    }
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "SOLID",
            "requirement_coverage": [or_row, real_row],
        },
        valid_capability_names={},
    )

    # Never hidden — the whole OR requirement stays on the card.
    assert [row["requirement"] for row in payload["requirement_coverage"]] == [
        "Be a cultural fit or a mission-driven self-starter",
        "Experience with stakeholder management",
    ]
    assert payload["requirement_coverage_hidden"] == []
    row = payload["requirement_coverage"][0]
    assert row["decomposition"]["operator"] == "or"
    assert row["profile_action_allowed"] is False
    assert row["canonical_requirement"] == ""
    assert row["mandatory_non_capability_unresolved"] is True

    # Never surfaced as a single-concept gap or resolved by one branch name.
    gaps = compute_profile_gaps(
        payload["requirement_coverage"],
        [{"name": "Stakeholder management", "level": "working"}],
        [],
    )
    assert gaps == []
    assert (
        resolve_custom_blocker("cultural fit", payload["requirement_coverage"])[
            "reason_code"
        ]
        == CUSTOM_BLOCKER_REASON_NO_MATCH
    )

    signals = source_learning.build_ad_learning_signals(
        _learning_record(payload["requirement_coverage"]),
        "Be a cultural fit or a mission-driven self-starter",
        profile={},
    )
    concept_signals = [
        sig for sig in signals if sig["suggested_category"] == "capability_concept"
    ]
    # Exactly one Signal for the OR row — not one per branch.
    assert concept_signals == [
        {
            "signal": "cultural fit or mission-driven self-starter",
            "suggested_category": "capability_concept",
            "original_texts": [
                "cultural fit",
                "mission-driven self-starter",
                "Be a cultural fit or a mission-driven self-starter",
            ],
        }
    ]
    # No standalone single-branch capability was minted.
    assert not any(
        sig["signal"] in {"cultural fit", "mission-driven self-starter"}
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


# --------------------------------------------------------------------------- #
# JH-298 — behavioural expectations vs professional capabilities
# --------------------------------------------------------------------------- #


_NOT_ASSESSED = llm_gate.LLM_NOT_ASSESSED_COVERAGE_STATUS


def _behavioural_item(requirement: str, *, importance: str = "preferred") -> dict:
    return {
        "requirement": requirement,
        "importance": importance,
        "requirement_type": "capability",
        "requirement_kind": "behavioural_expectation",
        # The LLM over-stated all of these — normalization must discard them.
        "canonical_requirement": "made up concept",
        "capability_name": "made up concept",
        "status": "supported",
        "matched_candidate_fact": "some unrelated fact",
        "matched_job_text": requirement,
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": requirement,
                    "capability_judgement": "capability",
                    "canonical_concept": "made up concept",
                    "canonical_fact_resolved": True,
                    "status": "supported",
                }
            ],
        },
    }


def test_behavioural_capability_row_is_display_only_and_partitioned_out():
    rows = _normalize(
        _behavioural_item("Works autonomously with minimal supervision"),
        valid_capability_names={"made up concept": "Made Up Concept"},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["requirement_kind"] == "behavioural_expectation"
    assert row["behavioural_expectation"] is True
    # Display-only: never a scored status, never actionable, no canonical concept.
    assert row["status"] == _NOT_ASSESSED
    assert _NOT_ASSESSED not in llm_gate._ALLOWED_REQUIREMENT_COVERAGE_STATUSES
    assert row["profile_action_allowed"] is False
    assert row["canonical_requirement"] == ""
    assert row["capability_name"] == ""
    assert row["matched_candidate_fact"] == ""
    for element in row["decomposition"]["elements"]:
        assert element["element_profile_action_allowed"] is False
        assert element["matched_candidate_fact"] == ""

    kept, behavioural = llm_gate.partition_behavioural_requirement_coverage(rows)
    assert kept == []
    assert behavioural == rows


def test_professional_capability_kind_is_retained_and_scored():
    item = {
        "requirement": "Facilitate stakeholder workshops",
        "importance": "mandatory",
        "requirement_type": "capability",
        "requirement_kind": "professional_capability",
        "canonical_requirement": "",
        "decomposition": _single("workshop facilitation", status="supported"),
        "status": "supported",
        "matched_candidate_fact": "workshop facilitation",
        "matched_job_text": "Facilitate stakeholder workshops",
    }
    rows = _normalize(item, valid_capability_names={})
    assert rows[0]["requirement_kind"] == "professional_capability"
    assert "behavioural_expectation" not in rows[0]
    kept, behavioural = llm_gate.partition_behavioural_requirement_coverage(rows)
    assert kept == rows
    assert behavioural == []


def test_missing_requirement_kind_fails_closed_to_unclassified_with_warning(monkeypatch):
    warnings: list[dict] = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    item = {
        "requirement": "SQL query authoring",
        "importance": "preferred",
        "requirement_type": "capability",
        # The LLM omitted requirement_kind and over-stated a match — fail closed.
        "canonical_requirement": "made up concept",
        "capability_name": "made up concept",
        "status": "supported",
        "matched_candidate_fact": "some unrelated fact",
        "decomposition": _single("SQL", status="supported"),
        "matched_job_text": "SQL query authoring",
    }
    rows = _normalize(
        item,
        default_capability_kind=None,
        valid_capability_names={"made up concept": "Made Up Concept"},
    )
    assert len(rows) == 1
    row = rows[0]
    # JH-298 correction: missing kind must NOT default to professional_capability.
    assert row["requirement_kind"] == llm_gate.LLM_REQUIREMENT_KIND_UNCLASSIFIED
    assert row["unclassified_requirement_kind"] is True
    # Display-only: never a scored status, never actionable, no retained match.
    assert row["status"] == _NOT_ASSESSED
    assert _NOT_ASSESSED not in llm_gate._ALLOWED_REQUIREMENT_COVERAGE_STATUSES
    assert row["profile_action_allowed"] is False
    assert row["canonical_requirement"] == ""
    assert row["capability_name"] == ""
    assert row["matched_candidate_fact"] == ""
    for element in row["decomposition"]["elements"]:
        assert element["element_profile_action_allowed"] is False
        assert element["matched_candidate_fact"] == ""
    assert any(
        w["context"]["reason"] == "requirement_kind_unclassified" for w in warnings
    )

    kept, unclassified = llm_gate.partition_unclassified_requirement_coverage(rows)
    assert kept == []
    assert unclassified == rows


def test_unrecognised_requirement_kind_fails_closed_to_unclassified():
    item = {
        "requirement": "SQL query authoring",
        "importance": "preferred",
        "requirement_type": "capability",
        "requirement_kind": "totally_made_up_kind",
        "canonical_requirement": "",
        "decomposition": _single("SQL", status="not_shown"),
        "status": "not_shown",
        "matched_job_text": "SQL query authoring",
    }
    rows = _normalize(item, default_capability_kind=None, valid_capability_names={})
    assert rows[0]["requirement_kind"] == llm_gate.LLM_REQUIREMENT_KIND_UNCLASSIFIED
    assert rows[0]["unclassified_requirement_kind"] is True
    kept, unclassified = llm_gate.partition_unclassified_requirement_coverage(rows)
    assert kept == []
    assert unclassified == rows


def test_missing_kind_row_partitioned_out_of_payload():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "SOLID",
            "requirement_coverage": [
                {
                    "requirement": "SQL query authoring",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    # requirement_kind omitted — must fail closed.
                    "canonical_requirement": "",
                    "decomposition": _single("SQL", status="not_shown"),
                    "status": "not_shown",
                    "matched_job_text": "SQL query authoring",
                },
                {
                    "requirement": "deliver projects",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "canonical_requirement": "",
                    "decomposition": _single("project delivery", status="supported"),
                    "status": "supported",
                    "matched_candidate_fact": "project delivery",
                    "matched_job_text": "deliver projects",
                },
            ],
        },
        valid_capability_names={},
    )
    scored = [r["requirement"] for r in payload["requirement_coverage"]]
    unclassified = [
        r["requirement"] for r in payload["requirement_coverage_unclassified"]
    ]
    assert scored == ["deliver projects"]
    assert unclassified == ["SQL query authoring"]


def test_decompose_before_classify_splits_mixed_sentence():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "SOLID",
            "requirement_coverage": [
                _behavioural_item("work through ambiguity"),
                _behavioural_item("manage complexity"),
                {
                    "requirement": "deliver projects",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "canonical_requirement": "",
                    "decomposition": _single("project delivery", status="supported"),
                    "status": "supported",
                    "matched_candidate_fact": "project delivery",
                    "matched_job_text": "deliver projects",
                },
            ],
        },
        valid_capability_names={"made up concept": "Made Up Concept"},
    )
    scored = [r["requirement"] for r in payload["requirement_coverage"]]
    behavioural = [r["requirement"] for r in payload["requirement_coverage_behavioural"]]
    assert scored == ["deliver projects"]
    assert sorted(behavioural) == ["manage complexity", "work through ambiguity"]
    assert all(
        r["status"] == _NOT_ASSESSED
        for r in payload["requirement_coverage_behavioural"]
    )


def test_eligibility_and_qualification_rows_never_get_requirement_kind():
    elig = {
        "requirement": "Australian citizenship",
        "importance": "mandatory",
        "requirement_type": "eligibility",
        "requirement_kind": "behavioural_expectation",  # nonsensical — must be dropped
        "canonical_requirement": "",
        "decomposition": _single("Australian citizenship", status="not_shown"),
        "status": "not_shown",
        "matched_job_text": "Australian citizenship",
    }
    qual = {
        "requirement": "Bachelor degree",
        "importance": "mandatory",
        "requirement_type": "qualification",
        "requirement_kind": "professional_capability",
        "canonical_requirement": "",
        "decomposition": _single("Bachelor degree", status="not_shown"),
        "status": "not_shown",
        "matched_job_text": "Bachelor degree",
    }
    elig_rows = _normalize(elig, valid_eligibility_names={})
    qual_rows = _normalize(qual, valid_qualification_names={})
    assert elig_rows[0]["requirement_kind"] == ""
    assert qual_rows[0]["requirement_kind"] == ""


def test_behavioural_rows_render_read_only_under_working_style_heading():
    behavioural = _normalize(
        _behavioural_item("Excellent communication skills", importance="mandatory"),
        valid_capability_names={"made up concept": "Made Up Concept"},
    )
    record = _or_record([])
    record[RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY] = behavioural
    html = workspace_renderer.render_job_card(record, _render_profile())

    heading = "Working style / behavioural expectations"
    not_assessed_label = "Employer context — not assessed"

    assert "job-requirement-group--working-style" in html
    assert heading in html
    assert "Excellent communication skills" in html
    assert not_assessed_label in html
    # Read-only: no profile actions rendered for the behavioural row.
    working_style_fragment = html.split("job-requirement-group--working-style", 1)[1]
    assert 'data-action="confirm_have"' not in working_style_fragment
    assert 'data-action="' not in working_style_fragment
    # Not surfaced as a scored gap.
    assert "job-requirement-item--working-style" in html
    assert "job-requirement-group--attention" not in html


def test_and_card_offers_actions_only_for_unknown_child_atom():
    item = {
        "requirement": "Power BI and Excel",
        "importance": "mandatory",
        "requirement_type": "capability",
        "canonical_requirement": "",
        "decomposition": {
            "operator": "and",
            "elements": [
                {
                    "text": "Power BI",
                    "capability_judgement": "capability",
                    "canonical_concept": "Power BI",
                    "canonical_fact_resolved": True,
                    "status": "not_shown",
                },
                {
                    "text": "Excel",
                    "capability_judgement": "capability",
                    "canonical_concept": "Excel",
                    "canonical_fact_resolved": True,
                    "status": "not_shown",
                },
            ],
        },
        "status": "not_shown",
        "matched_job_text": "Power BI and Excel",
    }
    coverage = _normalize(item, valid_capability_names={})
    profile = _render_profile()
    profile["candidate_capabilities"] = [
        {"name": "Excel", "level": "working", "aliases": []}
    ]

    html = workspace_renderer.render_job_card(_or_record(coverage), profile)

    assert html.count('data-action="confirm_have"') == 1
    assert html.count('data-action="confirm_do_not_have"') == 1
    assert html.count('data-capability-name="Power BI"') == 2
    assert 'data-capability-name="Excel"' not in html
    assert "Add Power BI" in unescape(html)
    assert "Either Power BI" not in unescape(html)
