"""Opt-in semantic contract for real LLM requirement interpretation.

This is intentionally separate from the deterministic regression suite. It uses
the production fit-review request and normalization path, but only checks broad
semantic invariants because model wording and row ordering are not stable.
"""

from __future__ import annotations

import os

import pytest

_ALLOW_LLM = os.environ.get("JOB_HUNTER_E2E_ALLOW_LLM") == "1"
_HAS_REAL_KEY = bool(os.environ.get("OPENAI_API_KEY"))
REAL_LLM_COST_CEILING_USD = 0.03

CAPTURED_AD_TEXT = """Real SEEK — Worrells, seek:93806022
Requirements:
- A Bachelor Degree or equivalent in Commerce, Finance or Accounting
- CA or CPA qualified (or willing to obtain)
- ARITA Introduction to Insolvency certification
- ARITA professional qualification (or willing to obtain)
- Previous experience in insolvency is required

Real SEEK — Unisys, seek:93865558
Requirements:
- Australian Citizenship is Required
- NV2 Security Clearance Required
- Relevant qualifications in Business Analysis, Information Technology, Project Management, or a related field
- CBAP, Agile BA, or equivalent certifications are desirable

Capability controls:
- 5+ years supporting client outcomes
- Strong stakeholder management and communication skills
"""


def _row_text(row: dict) -> str:
    return " ".join(
        str(row.get(field) or "")
        for field in ("requirement", "matched_job_text", "canonical_requirement")
    ).lower()


def _rows_with(rows: list[dict], *terms: str) -> list[dict]:
    return [row for row in rows if all(term.lower() in _row_text(row) for term in terms)]


VAGUE_ALTERNATIVES_AD_TEXT = """Real SEEK — Example Co, seek:00000001
Requirements:
- Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.
- Australian Citizenship is required.

Capability controls:
- 5+ years supporting client outcomes
"""


@pytest.mark.llm_e2e
@pytest.mark.timeout(90)
@pytest.mark.skipif(
    not (_ALLOW_LLM and _HAS_REAL_KEY),
    reason=(
        "Real-LLM semantic contract is opt-in only. Set JOB_HUNTER_E2E_ALLOW_LLM=1 "
        "and a real OPENAI_API_KEY to run it."
    ),
)
def test_real_llm_does_not_explode_named_alternatives_list_into_separate_rows(monkeypatch):
    """Regression for the requirement-decomposition bug: a vague group of named
    certification alternatives/examples ("Tertiary qualifications or BA/Agile
    certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.") must stay one
    requirement_coverage item with no resolved canonical fact — not be
    exploded into a separate row (and Add-to-profile action) per named
    alternative or per issuing body. This can only be proven through the real
    requirement-interpretation LLM boundary: normalize_llm_requirement_coverage
    alone only validates already-produced output, it cannot prove the prompt
    guidance change actually changed model decomposition behaviour.
    """
    from conftest import _cheapest_llm_model

    from job_hunter_agent import llm_gate

    model = _cheapest_llm_model()
    profile = {
        "candidate_capabilities": [
            {"name": "Client outcomes", "level": "working"},
        ],
        "candidate_eligibility": [
            {"name": "Australian Citizenship", "value": True},
        ],
        "candidate_qualifications": [],
    }

    monkeypatch.setattr(llm_gate, "load_profile", lambda: profile)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: model)

    payload = llm_gate._request_learning_payload(VAGUE_ALTERNATIVES_AD_TEXT, fit_review=True)
    rows = payload["requirement_coverage"]
    assert rows, "real model returned no requirement coverage"
    assert payload.get("llm_cost_usd", 0.0) <= REAL_LLM_COST_CEILING_USD

    named_alternative_terms = ("cbap", "ccba", "cspo", "psm", "iiba")
    matching_rows = [
        row for row in rows if any(term in _row_text(row) for term in named_alternative_terms)
    ]
    assert len(matching_rows) == 1, (
        "expected the CBAP/CCBA/CSPO/PSM/IIBA alternatives clause to stay one "
        f"requirement_coverage row, got {len(matching_rows)}: {matching_rows}"
    )
    row = matching_rows[0]
    assert row["requirement_type"] == "qualification"
    assert row["importance"] != "required"
    # The model may still produce a display label for the group (e.g. an
    # invented "Agile Certification" summary) — that alone is not the safety
    # invariant. What must always hold is that a vague group with more than
    # one named alternative can never become profile-actionable, regardless
    # of whether canonical_requirement happens to be non-empty.
    assert row.get("profile_action_allowed") is not True, (
        "a vague named-alternatives group must never be profile-actionable, "
        f"got row={row}"
    )


@pytest.mark.llm_e2e
@pytest.mark.timeout(90)
@pytest.mark.skipif(
    not (_ALLOW_LLM and _HAS_REAL_KEY),
    reason=(
        "Real-LLM semantic contract is opt-in only. Set JOB_HUNTER_E2E_ALLOW_LLM=1 "
        "and a real OPENAI_API_KEY to run it."
    ),
)
def test_real_llm_requirement_semantics_use_cheap_model_and_production_normalization(
    monkeypatch,
):
    from conftest import _cheapest_llm_model

    from job_hunter_agent import llm_gate

    model = _cheapest_llm_model()
    profile = {
        "candidate_capabilities": [
            {"name": "Insolvency experience", "level": "working"},
            {"name": "Client outcomes", "level": "working"},
            {"name": "Stakeholder management", "level": "strong"},
            {"name": "Communication", "level": "strong"},
        ],
        "candidate_eligibility": [
            {"name": "Australian Citizenship", "value": True},
            {"name": "NV2", "value": True},
        ],
        "candidate_qualifications": [
            {"name": "Bachelor Degree", "value": True, "aliases": ["Commerce"]},
            {"name": "CBAP", "value": False},
        ],
    }

    monkeypatch.setattr(llm_gate, "load_profile", lambda: profile)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: model)

    payload = llm_gate._request_learning_payload(CAPTURED_AD_TEXT, fit_review=True)
    rows = payload["requirement_coverage"]
    assert rows, "real model returned no requirement coverage"
    assert payload.get("llm_cost_usd", 0.0) <= REAL_LLM_COST_CEILING_USD

    citizenship_rows = _rows_with(rows, "citizenship")
    nv2_rows = _rows_with(rows, "nv2")
    years_rows = _rows_with(rows, "client", "outcomes")
    stakeholder_rows = _rows_with(rows, "stakeholder")
    cbap_rows = _rows_with(rows, "cbap")
    willing_rows = [row for row in rows if "willing" in _row_text(row)]

    assert citizenship_rows and all(row["requirement_type"] == "eligibility" for row in citizenship_rows)
    assert nv2_rows and all(row["requirement_type"] == "eligibility" for row in nv2_rows)
    assert years_rows and all(row["requirement_type"] == "capability" for row in years_rows)
    assert stakeholder_rows and all(
        row["requirement_type"] == "capability" for row in stakeholder_rows
    )
    assert cbap_rows and len(cbap_rows) == 1
    assert cbap_rows[0]["requirement_type"] == "qualification"
    assert cbap_rows[0]["importance"] == "preferred"
    assert not llm_gate.has_eligibility_mismatch(cbap_rows)

    # Alternative acquisition wording stays reviewable rather than becoming a
    # definite current-holder mismatch or a raw ad sentence as profile canon.
    assert willing_rows and all(
        row["requirement_type"] == "qualification"
        and row["status"] != "mismatch"
        and "willing to obtain" not in str(row.get("canonical_requirement") or "").lower()
        for row in willing_rows
    )
    for row in rows:
        canonical = str(row.get("canonical_requirement") or "").lower()
        requirement = str(row.get("requirement") or "").lower()
        assert not canonical or canonical != requirement
