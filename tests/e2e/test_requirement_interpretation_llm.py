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
def test_real_llm_resolves_confirmed_requirement_into_profile_storage(monkeypatch):
    """Click-time profile storage resolution (llm_resolve_profile_storage) is a
    dedicated decision, separate from fit-review. This proves its three real
    outcomes: a reworded existing skill collapses onto the existing capability
    instead of creating a duplicate, a genuinely new atomic skill becomes a new
    top-level item, and a vague/compound requirement fails closed as
    unresolved rather than guessing a storage destination.
    """
    from job_hunter_agent import llm_gate
    profile = {
        "candidate_capabilities": [
            {
                "name": "Business Analysis",
                "level": "strong",
                "aliases": ["Requirements Analysis"],
            },
            {
                "name": "Stakeholder Management",
                "level": "strong",
                "aliases": ["Communication"],
            },
        ],
        "candidate_eligibility": [],
        "candidate_eligibility_facts": [],
        "candidate_qualifications": [],
    }

    existing_row = {
        "requirement_type": "capability",
        "requirement": "Write clear business requirements and analyse stakeholder needs",
        "matched_job_text": "Write clear business requirements and analyse stakeholder needs",
        "canonical_requirement": "Business requirements analysis",
    }
    existing_result = llm_gate.llm_resolve_profile_storage(existing_row, profile, benchmark_model="gpt-5.6-luna")
    assert existing_result["resolution"] == "existing", existing_result
    assert existing_result["profile_target"] == "Business Analysis", existing_result

    new_row = {
        "requirement_type": "capability",
        "requirement": "Java development experience is required.",
        "matched_job_text": "Java development experience is required.",
        "canonical_requirement": "Java",
    }
    new_result = llm_gate.llm_resolve_profile_storage(new_row, profile, benchmark_model="gpt-5.6-luna")
    assert new_result["resolution"] == "new", new_result
    assert "java" in new_result["profile_target"].casefold(), new_result

    vague_row = {
        "requirement_type": "qualification",
        "requirement": (
            "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, "
            "CCBA, CSPO, PSM) are a bonus."
        ),
        "matched_job_text": (
            "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, "
            "CCBA, CSPO, PSM) are a bonus."
        ),
        "canonical_requirement": "",
    }
    vague_result = llm_gate.llm_resolve_profile_storage(vague_row, profile, benchmark_model="gpt-5.6-luna")
    assert vague_result["resolution"] == "unresolved", vague_result
    assert vague_result["profile_target"] == "", vague_result


@pytest.mark.llm_e2e
@pytest.mark.timeout(180)
@pytest.mark.skipif(
    not (_ALLOW_LLM and _HAS_REAL_KEY),
    reason=(
        "Real-LLM semantic contract is opt-in only. Set JOB_HUNTER_E2E_ALLOW_LLM=1 "
        "and a real OPENAI_API_KEY to run it."
    ),
)
def test_real_llm_resolves_optional_financial_examples_to_one_core_profile_fact(monkeypatch):
    """Optional banking/insurance examples never become separate confirmation facts."""
    from job_hunter_agent import llm_gate

    profile = {
        "candidate_capabilities": [
            {
                "name": "Governance and Compliance Management",
                "level": "working",
                "aliases": ["governance", "compliance", "document rigour"],
            }
        ],
        "candidate_eligibility": [],
        "candidate_eligibility_facts": [],
        "candidate_qualifications": [],
        "role_experience": [],
    }
    monkeypatch.setattr(llm_gate, "load_profile", lambda: profile)
    text = "Experience within Financial services, ideally banking or insurance."

    for _ in range(3):
        payload = llm_gate._request_learning_payload(
            text, fit_review=True, benchmark_model="gpt-4.1-mini"
        )
        rows = payload.get("requirement_coverage") or []
        assert len(rows) == 1, rows
        row = rows[0]
        canonical = str(row.get("canonical_requirement") or "").casefold()
        assert "financial" in canonical and "experience" in canonical, row
        assert "banking" not in canonical and "insurance" not in canonical, row
        assert row.get("profile_action_allowed") is True, row
        assert not row.get("named_alternatives"), row


@pytest.mark.llm_e2e
@pytest.mark.timeout(180)
@pytest.mark.skipif(
    not (_ALLOW_LLM and _HAS_REAL_KEY),
    reason=(
        "Real-LLM semantic contract is opt-in only. Set JOB_HUNTER_E2E_ALLOW_LLM=1 "
        "and a real OPENAI_API_KEY to run it."
    ),
)
def test_real_llm_keeps_financial_services_domain_out_of_governance_capability(monkeypatch):
    """The Luna storage resolver chooses only a destination for the confirmed fact."""
    from job_hunter_agent import llm_gate

    profile = {
        "candidate_capabilities": [
            {
                "name": "Governance and Compliance Management",
                "level": "working",
                "aliases": ["governance", "compliance", "document rigour"],
            }
        ],
        "candidate_eligibility": [],
        "candidate_eligibility_facts": [],
        "candidate_qualifications": [],
    }
    row = {
        "requirement_type": "capability",
        "requirement": "Experience within Financial services, ideally banking or insurance",
        "canonical_requirement": "Financial Services Experience",
        "matched_job_text": "Financial services background, ideally within banking or insurance",
    }

    for _ in range(3):
        result = llm_gate.llm_resolve_profile_storage(row, profile, benchmark_model="gpt-5.6-luna")
        target = str(result.get("profile_target") or "").casefold()
        assert result["resolution"] in {"new", "unresolved"}, result
        assert target != "governance and compliance management", result
        assert "banking" not in target, result
        assert "insurance" not in target, result
        assert "related_terms" not in result, result


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
