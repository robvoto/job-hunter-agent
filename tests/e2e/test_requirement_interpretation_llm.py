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
        assert row.get("decomposition", {}).get("operator") == "single", row


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
    assert row["importance"] != "mandatory"
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


BEHAVIOURAL_AD_TEXT = """Real SEEK — Example Consulting, seek:00000042
About you:
- You work autonomously with minimal supervision
- You are adaptable and comfortable working through ambiguity
- Strong attention to detail and sound judgement
- Naturally curious with a growth mindset
- A willingness to embrace new technology, including AI

What you'll do:
- Deliver projects end to end
- Facilitate stakeholder workshops and requirements elicitation sessions
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
def test_real_llm_separates_behavioural_expectations_from_professional_capabilities(
    monkeypatch,
):
    """JH-298: generic personal-conduct wording must be classified
    requirement_kind=behavioural_expectation, partitioned into
    requirement_coverage_behavioural with a not_assessed status, and kept out of
    scoring / learning. Observable professional activities in the same ad
    ("deliver projects", "facilitate stakeholder workshops") must stay
    professional_capability and score. This can only be proven through the real
    requirement-interpretation boundary — normalization alone cannot show the
    model actually made the classification.
    """
    from conftest import _cheapest_llm_model

    from job_hunter_agent import llm_gate, source_learning
    from job_hunter_agent.record_schema import (
        RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY,
        RECORD_REQUIREMENT_COVERAGE_KEY,
    )

    model = _cheapest_llm_model()
    profile = {
        "candidate_capabilities": [
            {"name": "Project delivery", "level": "strong"},
            {"name": "Stakeholder engagement", "level": "strong"},
        ],
        "candidate_eligibility": [],
        "candidate_qualifications": [],
    }
    monkeypatch.setattr(llm_gate, "load_profile", lambda: profile)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: model)

    payload = llm_gate._request_learning_payload(BEHAVIOURAL_AD_TEXT, fit_review=True)
    assert payload.get("llm_cost_usd", 0.0) <= REAL_LLM_COST_CEILING_USD

    scored = payload["requirement_coverage"]
    behavioural = payload["requirement_coverage_behavioural"]
    assert behavioural, "real model classified no behavioural expectations"

    # Every behavioural row is display-only and structurally inert.
    for row in behavioural:
        assert row["requirement_type"] == "capability", row
        assert row.get("requirement_kind") == "behavioural_expectation", row
        assert row["status"] == llm_gate.LLM_NOT_ASSESSED_COVERAGE_STATUS, row
        assert row.get("profile_action_allowed") is not True, row
        assert not row.get("canonical_requirement"), row
        assert not row.get("capability_name"), row

    behavioural_blob = " ".join(_row_text(row) for row in behavioural)
    for phrase in ("autonomous", "ambiguity", "attention to detail", "curious", "ai"):
        assert phrase in behavioural_blob, (phrase, behavioural_blob)

    # The professional activities stay scored capabilities.
    delivery_rows = _rows_with(scored, "deliver", "projects")
    workshop_rows = [r for r in scored if "workshop" in _row_text(r) or "elicitation" in _row_text(r)]
    assert delivery_rows and all(r["requirement_type"] == "capability" for r in delivery_rows)
    assert all(
        r.get("requirement_kind", "professional_capability") == "professional_capability"
        for r in delivery_rows
    )
    assert workshop_rows and all(r["requirement_type"] == "capability" for r in workshop_rows)

    # No behavioural row leaks into scoring or mints a pending capability signal.
    scored_blob = " ".join(_row_text(row) for row in scored)
    for phrase in ("work autonomously", "growth mindset", "willingness to embrace"):
        assert phrase not in scored_blob, (phrase, scored_blob)

    record = {
        RECORD_REQUIREMENT_COVERAGE_KEY: scored,
        RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY: behavioural,
    }
    signals = source_learning.build_ad_learning_signals(record, BEHAVIOURAL_AD_TEXT)
    signal_blob = " ".join(
        str(sig.get("signal") or "").lower()
        for sig in signals
        if sig.get("suggested_category") == "capability_concept"
    )
    for banned in ("ai development", "artificial intelligence", "machine learning", "genai"):
        assert banned not in signal_blob, (banned, signal_blob)


EVIDENCE_INTEGRITY_AD_TEXT = """Real SEEK — Example Digital, seek:00000099
What you'll do:
- Hands-on contribution to building AI/ML models in production
- Configure and administer SAP S/4HANA finance modules
- Build current-state process maps in Lucidchart

About you:
- A Senior Business Analyst who works autonomously and exercises sound judgement
"""


@pytest.mark.llm_e2e
@pytest.mark.timeout(120)
@pytest.mark.skipif(
    not (_ALLOW_LLM and _HAS_REAL_KEY),
    reason=(
        "Real-LLM semantic contract is opt-in only. Set JOB_HUNTER_E2E_ALLOW_LLM=1 "
        "and a real OPENAI_API_KEY to run it."
    ),
)
def test_real_llm_rejects_unsupported_semantic_evidence_for_professional_capability(
    monkeypatch,
):
    """JH-299: a positive requirement_coverage row must trace to specific
    candidate evidence for the same professional concept. Against a profile that
    only holds adjacent facts — a role title, willingness to use AI, generic SAP
    exposure, a different diagramming tool — the real model + production
    normalization must not return AI/ML development, SAP S/4HANA, or Lucidchart
    as supported, and a bare role title must not prove "works autonomously".
    """
    from conftest import _cheapest_llm_model

    from job_hunter_agent import llm_gate

    model = _cheapest_llm_model()
    profile = {
        "candidate_capabilities": [
            {"name": "Business analysis", "level": "strong", "aliases": ["Senior Business Analyst"]},
            {"name": "Data analysis", "level": "strong"},
            {"name": "Process mapping", "level": "working", "aliases": ["Visio"]},
        ],
        "candidate_eligibility": [],
        "candidate_qualifications": [],
        "role_experience": [
            {"normalized_title": "Senior Business Analyst", "total_months": 180},
        ],
    }
    monkeypatch.setattr(llm_gate, "load_profile", lambda: profile)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: model)

    payload = llm_gate._request_learning_payload(EVIDENCE_INTEGRITY_AD_TEXT, fit_review=True)
    assert payload.get("llm_cost_usd", 0.0) <= REAL_LLM_COST_CEILING_USD
    rows = payload["requirement_coverage"] + payload.get("requirement_coverage_behavioural", [])
    assert rows, "real model returned no requirement coverage"

    def _positive(row: dict) -> bool:
        return row.get("status") in {"supported", "partially_supported"}

    for terms in (("ai",), ("ml",), ("s/4hana",), ("s4hana",), ("lucidchart",)):
        for row in _rows_with(payload["requirement_coverage"], *terms):
            assert not _positive(row), row
            assert not row.get("matched_candidate_fact"), row
            assert not row.get("capability_name"), row

    for row in payload["requirement_coverage"]:
        if _positive(row):
            continue
        assert not row.get("matched_candidate_fact"), row
        assert not row.get("profile_support"), row
        for element in row.get("decomposition", {}).get("elements", []):
            assert not element.get("matched_candidate_fact"), row
