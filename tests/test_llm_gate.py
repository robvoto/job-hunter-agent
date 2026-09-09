"""Tests for llm gate."""

import pytest
from pydantic import ValidationError

from job_hunter_agent import llm_gate

_PROFESSIONAL_KIND = "professional_capability"


def _stamp_default_kind(rows):
    """Stamp ``professional_capability`` on bare ``capability`` rows.

    Since the JH-298 fail-closed correction a capability row with no
    requirement_kind normalizes to ``unclassified`` (non-scoring) and is
    partitioned out of ``requirement_coverage``. Fixtures in this file predate
    the requirement_kind axis and build bare capability rows that are meant to
    be ordinary scored professional capabilities, so stamp the professional kind
    unless the row sets its own. Rows with an explicit kind (e.g. behavioural)
    are left untouched.
    """
    stamped = []
    for row in rows or []:
        if (
            isinstance(row, dict)
            and str(row.get("requirement_type") or "capability").strip().lower()
            == "capability"
            and not str(row.get("requirement_kind") or "").strip()
        ):
            row = {**row, "requirement_kind": _PROFESSIONAL_KIND}
        stamped.append(row)
    return stamped


def _norm_cov(items, **kwargs):
    return llm_gate.normalize_llm_requirement_coverage(
        _stamp_default_kind(items), **kwargs
    )


def _norm_payload(payload, **kwargs):
    if isinstance(payload, dict) and "requirement_coverage" in payload:
        payload = {
            **payload,
            "requirement_coverage": _stamp_default_kind(
                payload.get("requirement_coverage")
            ),
        }
    return llm_gate.normalize_llm_review_payload(payload, **kwargs)


def test_openai_environment_key_enables_llm_outside_desktop(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")

    client = llm_gate._build_openai_client()

    assert client is not None
    monkeypatch.setattr(llm_gate, "client", client)
    assert llm_gate.llm_is_enabled() is True


def test_openai_environment_key_is_ignored_in_desktop_runtime(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("JOB_HUNTER_DESKTOP_MODE", "1")

    assert llm_gate._build_openai_client() is None
    assert llm_gate.llm_is_enabled() is False


def test_llm_generation_kwargs_uses_reasoning_without_temperature_when_effort_is_active(monkeypatch):
    monkeypatch.setattr(llm_gate, "get_llm_temperature", lambda: 0.0)
    monkeypatch.setattr(llm_gate, "get_llm_reasoning_effort", lambda model: "low")

    assert llm_gate._llm_generation_kwargs("gpt-5.6-luna") == {
        "reasoning": {"effort": "low"},
    }


def test_llm_generation_kwargs_combines_temperature_with_reasoning_none(monkeypatch):
    monkeypatch.setattr(llm_gate, "get_llm_temperature", lambda: 0.0)
    monkeypatch.setattr(llm_gate, "get_llm_reasoning_effort", lambda model: "none")

    assert llm_gate._llm_generation_kwargs("gpt-5.6-luna") == {
        "temperature": 0.0,
        "reasoning": {"effort": "none"},
    }


def test_llm_generation_kwargs_keeps_temperature_when_reasoning_is_unconfigured(monkeypatch):
    monkeypatch.setattr(llm_gate, "get_llm_temperature", lambda: 0.2)
    monkeypatch.setattr(llm_gate, "get_llm_reasoning_effort", lambda model: None)

    assert llm_gate._llm_generation_kwargs("gpt-4.1-mini") == {"temperature": 0.2}


def test_build_capability_naming_guidance_uses_managed_defaults_only():
    prompt = llm_gate.build_capability_naming_guidance()

    assert (
        "You are reviewing and labelling candidate professional capability clusters extracted from a CV."
        in prompt
    )
    assert "Default capability naming guidance:" in prompt
    assert "Clusters:" in prompt
    assert "skip" not in prompt


def test_posting_channel_guidance_treats_employer_voice_as_direct_evidence():
    prompt = llm_gate.build_posting_channel_guidance()

    assert "our employees" in prompt
    assert "our business" in prompt
    assert "Do not require the literal phrase 'we are the employer'" in prompt


def test_fit_review_prompt_excludes_learning_guidance(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [{"name": "stakeholder engagement", "level": "strong"}],
            "candidate_eligibility": [{"name": "PV clearance", "value": True, "evidence": []}],
            "match_preferences": {},
            "salary_preferences": {},
            "candidate_profile_tiers": {},
            "onboarding_settings": {},
        },
    )
    prompt = llm_gate._build_learning_prompt("Job description", fit_review=True)

    assert "Learning categories available:" not in prompt
    assert "role_title_pattern" not in prompt
    assert "capability_concept" not in prompt
    assert "learning_candidates" not in prompt
    assert "Do not save anything" not in prompt
    assert "Do not invent new categories" not in prompt
    assert "requirement_coverage" in prompt
    assert "fit_review.grade" in prompt
    assert '"profile_supported":true|false' in prompt
    assert '"profile_evidence":["..."]' in prompt
    assert "exact canonical capability or eligibility name" in prompt
    assert "Eligibility matrix:" in prompt
    assert "match_source" not in prompt
    assert "matched_profile_term" not in prompt




def test_requirement_coverage_rejects_removed_profile_name_alias():
    result = _norm_cov(
        [{
            "requirement": "Stakeholder engagement",
            "importance": "preferred",
            "requirement_type": "capability",
            "status": "supported",
            "profile_name": "Stakeholder Engagement",
            "profile_support": ["Worked with senior stakeholders."],
        }],
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["capability_name"] == ""
    assert result[0]["status"] == "not_shown"


def test_requirement_coverage_rejects_type_specific_input_alias():
    result = _norm_cov(
        [{
            "requirement": "Stakeholder engagement",
            "importance": "preferred",
            "requirement_type": "capability",
            "status": "supported",
            "capability_name": "Stakeholder Engagement",
            "profile_support": ["Worked with senior stakeholders."],
        }],
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["capability_name"] == ""
    assert result[0]["status"] == "not_shown"

def test_fit_review_prompt_debug_match_diagnostics_adds_debug_schema(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [{"name": "stakeholder engagement", "level": "strong"}],
            "candidate_eligibility": [{"name": "PV clearance", "value": True, "evidence": []}],
            "match_preferences": {},
            "salary_preferences": {},
            "candidate_profile_tiers": {},
            "onboarding_settings": {},
        },
    )
    monkeypatch.setattr(
        llm_gate,
        "get_llm_fit_review_debug_match_diagnostics_enabled",
        lambda: True,
    )

    prompt = llm_gate._build_learning_prompt("Job description", fit_review=True)

    assert "match_source" in prompt
    assert "matched_profile_term" in prompt
    assert 'return match_source exactly as "capability_name", "related_skill", "eligibility", or "qualification"' in prompt
    assert "profile_support must contain only actual candidate evidence text" in prompt


def test_fit_review_prompt_includes_occupation_alignment_guidance_and_target_roles(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [{"name": "stakeholder engagement", "level": "strong"}],
            "candidate_eligibility": [],
            "match_preferences": {},
            "salary_preferences": {},
            "candidate_profile_tiers": {},
            "onboarding_settings": {},
            "target_roles": ["Delivery Manager"],
            "also_consider_roles": ["Program Manager"],
        },
    )

    prompt = llm_gate._build_learning_prompt("Job description", fit_review=True)

    assert '"occupation_alignment":"same|adjacent|different"' in prompt
    assert "occupation_alignment_reason" in prompt
    assert "Candidate target roles:" in prompt
    assert "Delivery Manager" in prompt
    assert "Program Manager" in prompt


def test_fit_review_prompt_includes_role_experience_matrix(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [{"name": "business analysis", "level": "strong"}],
            "candidate_eligibility": [],
            "role_experience": [
                {
                    "normalized_title": "business analyst",
                    "total_duration_months": 42,
                    "most_recent_end_year": 2025,
                    "segments": [{"duration_months": 42, "is_current": False}],
                    "title_variants": [
                        {
                            "normalized_title": "senior ba",
                            "total_duration_months": 24,
                            "most_recent_end_year": 2025,
                        }
                    ],
                }
            ],
            "match_preferences": {},
            "salary_preferences": {},
            "candidate_profile_tiers": {},
            "onboarding_settings": {},
        },
    )

    prompt = llm_gate._build_learning_prompt("Job description", fit_review=True)

    assert "Role experience matrix:" in prompt
    assert "business analyst: 42 months" in prompt
    assert "title variants: senior ba 24 months" in prompt
    assert "most recent end year 2025" in prompt
    assert "explicit years or months of experience" in prompt


def test_role_experience_matrix_shows_accrued_months_for_a_current_segment(monkeypatch):
    from datetime import date

    from job_hunter_agent.role_experience_duration import whole_months_between

    duration_as_of = "2024-01-01"
    stored_months = 42
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [{"name": "business analysis", "level": "strong"}],
            "candidate_eligibility": [],
            "role_experience": [
                {
                    "normalized_title": "business analyst",
                    "total_duration_months": stored_months,
                    "most_recent_end_year": 2026,
                    "segments": [
                        {
                            "duration_months": stored_months,
                            "is_current": True,
                            "duration_as_of": duration_as_of,
                        }
                    ],
                    "title_variants": [],
                }
            ],
            "match_preferences": {},
            "salary_preferences": {},
            "candidate_profile_tiers": {},
            "onboarding_settings": {},
        },
    )

    prompt = llm_gate._build_learning_prompt("Job description", fit_review=True)

    accrued = stored_months + whole_months_between(
        date.fromisoformat(duration_as_of), date.today()
    )
    assert accrued > stored_months
    assert f"business analyst: {accrued} months" in prompt


def test_learning_only_prompt_retains_learning_guidance():
    prompt = llm_gate._build_learning_prompt("Job description", fit_review=False)

    assert "Learning categories available:" in prompt
    assert "capability_concept" in prompt
    assert "learning_candidates" in prompt
    assert "Do not save anything" in prompt
    assert "Do not invent new categories" in prompt


def test_normalize_llm_review_payload_derives_grade_from_requirement_coverage():
    payload = _norm_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "learning_candidates": [
                {"signal": "platform engineer", "suggested_category": "capability_concept"},
            ],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_supported",
                    "capability_name": "process mapping",
                    "matched_job_text": "map the current process",
                    "profile_support": ["process mapping"],
                    "matched_candidate_fact": "process mapping",
                },
            ],
        },
        valid_capability_names={
            "stakeholder engagement": "Stakeholder Engagement",
            "process mapping": "Process Mapping",
        },
    )

    assert payload == {
        "fit_review": {"decision": "KEEP", "grade": "SOLID"},
        "occupation_alignment": llm_gate.LLM_INVALID_OCCUPATION_ALIGNMENT,
        "occupation_alignment_reason": "",
        "posting_channel": {"kind": llm_gate.LLM_INVALID_POSTING_CHANNEL_KIND, "confident": False, "evidence": ""},
        "debug_reason": "",
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "importance": "preferred",
                "requirement_type": "capability",
                "requirement_kind": "professional_capability",
                "canonical_requirement": "",
                "profile_action_allowed": False,
                "status": "supported",
                "matched_candidate_fact": "Stakeholder Engagement",
                "capability_name": "Stakeholder Engagement",
                "eligibility_name": "",
                "matched_job_text": "work with stakeholders",
                "profile_support": ["stakeholder management"],
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "Stakeholder engagement",
                            "capability_judgement": "capability",
                            "canonical_concept": "",
                            "canonical_fact_resolved": False,
                            "status": "",
                            "matched_candidate_fact": "",
                            "element_profile_action_allowed": False,
                        }
                    ],
                },
            },
            {
                "requirement": "Process mapping",
                "importance": "preferred",
                "requirement_type": "capability",
                "requirement_kind": "professional_capability",
                "canonical_requirement": "",
                "profile_action_allowed": False,
                "status": "partially_supported",
                "matched_candidate_fact": "Process Mapping",
                "capability_name": "Process Mapping",
                "eligibility_name": "",
                "matched_job_text": "map the current process",
                "profile_support": ["process mapping"],
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "Process mapping",
                            "capability_judgement": "capability",
                            "canonical_concept": "",
                            "canonical_fact_resolved": False,
                            "status": "",
                            "matched_candidate_fact": "",
                            "element_profile_action_allowed": False,
                        }
                    ],
                },
            },
        ],
        "requirement_coverage_hidden": [],
        "requirement_coverage_behavioural": [],
        "requirement_coverage_unclassified": [],
    }


def test_normalize_llm_review_payload_rejects_keep_without_requirement_coverage():
    with pytest.raises(
        llm_gate.LLMReviewValidationError,
        match="LLM KEEP review requires non-empty requirement_coverage",
    ):
        _norm_payload(
            {
                "fit_review": {"decision": "KEEP", "grade": "STRONG"},
                "requirement_coverage": [],
            }
        )


def test_normalize_llm_review_payload_downgrades_supported_when_role_duration_is_below_requirement():
    payload = _norm_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "requirement_coverage": [
                {
                    "requirement": "5+ years experience as a Business Analyst",
                    "status": "supported",
                    "capability_name": "business analysis",
                    "matched_job_text": "Minimum 5+ years experience as a Business Analyst in digital programs",
                    "profile_support": ["Ran BA activities across delivery teams."],
                    "experience_components": [
                        {"kind": "duration", "text": "5+ years"},
                        {
                            "kind": "role_or_activity",
                            "text": "Business Analyst",
                            "matched_role_family": "Business Analyst",
                        },
                    ],
                    "matched_candidate_fact": "business analysis",
                }
            ],
        },
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 24,
                "most_recent_end_year": 2024,
                "segments": [{"duration_months": 24, "is_current": False}],
            }
        ],
    )

    row = payload["requirement_coverage"][0]
    assert row["status"] == "partially_supported"
    assert row["required_experience_months"] == 60
    assert row["matched_role_family"] == "Business Analyst"
    assert row["matched_role_family_months"] == 24
    assert row["experience_requirement_met"] is False
    assert row["experience_duration_gap"] is True
    assert payload["fit_review"]["grade"] == "SOLID"


def test_normalize_llm_review_payload_downgrades_supported_when_years_requirement_has_no_role_duration_match():
    payload = _norm_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "requirement_coverage": [
                {
                    "requirement": "5+ years Python backend development",
                    "status": "supported",
                    "capability_name": "python",
                    "matched_job_text": "Minimum 5+ years Python backend development",
                    "profile_support": ["Built Python services."],
                    "experience_components": [
                        {"kind": "duration", "text": "5+ years"},
                        {"kind": "role_or_activity", "text": "Python backend development"},
                    ],
                    "matched_candidate_fact": "python",
                }
            ],
        },
        valid_capability_names={"python": "Python"},
        role_experience=[
            {
                "normalized_title": "business analyst",
                "total_duration_months": 24,
                "most_recent_end_year": 2024,
                "segments": [{"duration_months": 24, "is_current": False}],
            }
        ],
    )

    row = payload["requirement_coverage"][0]
    assert row["status"] == "partially_supported"
    assert row["required_experience_months"] == 60
    assert row["experience_requirement_review_needed"] is True
    assert "matched_role_family" not in row
    assert "experience_requirement_met" not in row


def test_normalize_llm_review_payload_partitions_missing_kind_capability_row():
    # JH-298 correction: a capability row the LLM returned without a valid
    # requirement_kind fails closed to `unclassified` — it is pulled out of
    # requirement_coverage into requirement_coverage_unclassified, never scored.
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "STRONG",
            "requirement_coverage": [
                {
                    "requirement": "Own the AI platform roadmap",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    # requirement_kind deliberately omitted.
                    "status": "supported",
                    "capability_name": "ai platform",
                    "matched_candidate_fact": "AI Platform",
                    "matched_job_text": "own the AI platform roadmap",
                    "profile_support": ["Ran an AI platform program."],
                },
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "requirement_kind": "professional_capability",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_candidate_fact": "Stakeholder Engagement",
                    "matched_job_text": "engage stakeholders",
                    "profile_support": ["Led stakeholder engagement."],
                },
            ],
        },
        valid_capability_names={
            "ai platform": "AI Platform",
            "stakeholder engagement": "Stakeholder Engagement",
        },
    )

    assert [r["requirement"] for r in payload["requirement_coverage"]] == [
        "Stakeholder engagement"
    ]
    unclassified = payload["requirement_coverage_unclassified"]
    assert [r["requirement"] for r in unclassified] == ["Own the AI platform roadmap"]
    leaked = unclassified[0]
    assert leaked["requirement_kind"] == llm_gate.LLM_REQUIREMENT_KIND_UNCLASSIFIED
    assert leaked["unclassified_requirement_kind"] is True
    assert leaked["status"] == llm_gate.LLM_NOT_ASSESSED_COVERAGE_STATUS
    assert leaked["capability_name"] == ""
    assert leaked["matched_candidate_fact"] == ""


def test_normalize_llm_review_payload_matches_years_requirement_against_role_variants():
    payload = _norm_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "requirement_coverage": [
                {
                    "requirement": "5+ years experience as BA",
                    "status": "supported",
                    "capability_name": "business analysis",
                    "matched_job_text": "Minimum 5+ years experience as BA",
                    "profile_support": ["Ran BA activities across delivery teams."],
                    "experience_components": [
                        {"kind": "duration", "text": "5+ years"},
                        {
                            "kind": "role_or_activity",
                            "text": "Business Analyst",
                            "matched_role_family": "senior ba",
                        },
                    ],
                    "matched_candidate_fact": "business analysis",
                }
            ],
        },
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "business analyst",
                "total_duration_months": 60,
                "most_recent_end_year": 2024,
                "segments": [{"duration_months": 60, "is_current": False}],
                "title_variants": [
                    {
                        "normalized_title": "ba",
                        "total_duration_months": 12,
                        "most_recent_end_year": 2020,
                    },
                    {
                        "normalized_title": "business analyst",
                        "total_duration_months": 24,
                        "most_recent_end_year": 2022,
                    },
                    {
                        "normalized_title": "senior ba",
                        "total_duration_months": 24,
                        "most_recent_end_year": 2024,
                    },
                ],
            }
        ],
    )

    row = payload["requirement_coverage"][0]
    assert row["required_experience_months"] == 60
    # JH-013 regression: the LLM named the "senior ba" sub-title. Only that
    # variant's own 24 months are credited, not the 60-month business analyst
    # family total it sits inside, so the 5-year bar is not met.
    assert row["matched_role_family"] == "senior ba"
    assert row["matched_role_family_months"] == 24
    assert row["experience_requirement_met"] is False
    assert row["experience_duration_gap"] is True
    assert row["status"] == "partially_supported"


def _years_experience_coverage_row(matched_role_family: str) -> dict:
    """The reported wording, decomposed the way the fit-review LLM returns it."""
    return {
        "requirement": "5+ years business analysis experience",
        "importance": "mandatory",
        "requirement_type": "capability",
        "status": "supported",
        "matched_candidate_fact": "Business Analysis",
        "capability_name": "Business Analysis",
        "matched_job_text": "5+ years business analysis experience",
        "profile_support": ["Ran BA activities across delivery teams."],
        "experience_components": [
            {"kind": "duration", "text": "5+ years"},
            {
                "kind": "role_or_activity",
                "text": "business analysis",
                "matched_role_family": matched_role_family,
            },
        ],
    }


def _ba_family_role_experience(total_duration_months: int) -> list[dict]:
    """One BA family whose accumulated history spans BA + Senior BA titles."""
    return [
        {
            "normalized_title": "Business Analyst",
            "total_duration_months": total_duration_months,
            "most_recent_end_year": 2025,
            "segments": [{"duration_months": total_duration_months, "is_current": False}],
            "title_variants": [
                {"normalized_title": "Business Analyst"},
                {"normalized_title": "Senior Business Analyst"},
            ],
        }
    ]


def test_years_subtitle_without_own_duration_is_left_for_review_not_family_total():
    # JH-013 regression: the LLM tied the requirement to the "Senior Business
    # Analyst" sub-title, which exists only as a title variant with no duration
    # of its own. The 66-month Business Analyst family total must NOT be
    # borrowed; the row stays visible but unresolved for review.
    result = _norm_cov(
        [_years_experience_coverage_row("Senior Business Analyst")],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=_ba_family_role_experience(66),
    )

    row = result[0]
    assert row["required_experience_months"] == 60
    assert row["experience_requirement_review_needed"] is True
    assert row["status"] == "partially_supported"
    assert "matched_role_family" not in row
    assert "matched_role_family_months" not in row
    assert "experience_requirement_met" not in row


def test_years_subtitle_match_credits_only_the_variants_own_stored_months():
    # A sub-title that DOES carry its own stored duration is credited with that
    # figure alone — never the parent family total.
    role_experience = [
        {
            "normalized_title": "Business Analyst",
            "total_duration_months": 216,
            "most_recent_end_year": 2025,
            "segments": [{"duration_months": 216, "is_current": False}],
            "title_variants": [
                {"normalized_title": "Business Analyst", "total_duration_months": 48},
                {
                    "normalized_title": "Senior Business Analyst",
                    "total_duration_months": 30,
                    "most_recent_end_year": 2025,
                },
            ],
        }
    ]
    result = _norm_cov(
        [_years_experience_coverage_row("Senior Business Analyst")],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=role_experience,
    )

    row = result[0]
    assert row["matched_role_family"] == "Senior Business Analyst"
    assert row["matched_role_family_months"] == 30
    assert row["experience_requirement_met"] is False
    assert row["experience_duration_gap"] is True
    assert row["status"] == "partially_supported"


def test_years_business_analysis_requirement_shows_gap_when_history_is_short():
    result = _norm_cov(
        [_years_experience_coverage_row("Business Analyst")],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=_ba_family_role_experience(36),
    )

    row = result[0]
    assert row["required_experience_months"] == 60
    assert row["matched_role_family"] == "Business Analyst"
    assert row["matched_role_family_months"] == 36
    assert row["experience_requirement_met"] is False
    assert row["experience_duration_gap"] is True
    assert row["status"] == "partially_supported"


def test_years_requirement_left_for_review_when_llm_ties_no_role_family():
    # The LLM could not safely tie the duration to any saved family (empty
    # matched_role_family). The row stays visible but unresolved for review;
    # deterministic code never guesses the role relationship.
    result = _norm_cov(
        [_years_experience_coverage_row("")],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=_ba_family_role_experience(66),
    )

    row = result[0]
    assert row["required_experience_months"] == 60
    assert row["experience_requirement_review_needed"] is True
    assert row["status"] == "partially_supported"
    assert "matched_role_family" not in row
    assert "experience_requirement_met" not in row


def test_years_requirement_for_unrelated_role_is_not_matched_from_ba_history():
    # "3+ years registered nursing experience" against a BA-only history: the
    # LLM names a nursing family that the profile does not hold, and no profile
    # evidence supports nursing at all, so the row is not credited. The review
    # flag is still recorded so the unresolved duration is visible.
    row_in = {
        "requirement": "3+ years registered nursing experience",
        "importance": "mandatory",
        "requirement_type": "capability",
        "status": "supported",
        "matched_candidate_fact": "Business Analysis",
        "capability_name": "Business Analysis",
        "matched_job_text": "3+ years registered nursing experience",
        "profile_support": ["Ran BA activities across delivery teams."],
        "experience_components": [
            {"kind": "duration", "text": "3+ years"},
            {
                "kind": "role_or_activity",
                "text": "registered nursing",
                "matched_role_family": "Registered Nurse",
            },
        ],
    }
    result = _norm_cov(
        [row_in],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=_ba_family_role_experience(120),
    )

    row = result[0]
    assert row["required_experience_months"] == 36
    assert row["experience_requirement_review_needed"] is True
    assert row["experience_requirement_review_family"] == "Registered Nurse"
    assert row["status"] == "not_shown"
    assert row["matched_candidate_fact"] == ""
    assert "experience_requirement_met" not in row


def test_normalize_llm_review_payload_falls_back_to_model_grade_without_coverage():

    # REJECT decisions can legitimately have no requirement_coverage (the KEEP-only
    # guard in _require_complete_keep_requirement_coverage doesn't apply here).
    # derive_fit_review_grade([]) always returns "POOR", so without a fallback the
    # model's own grade would be silently discarded and replaced with "POOR".

    payload = _norm_payload(
        {
            "decision": "REJECT",
            "grade": "MISMATCH",
            "requirement_coverage": [],
        }
    )

    assert payload["fit_review"] == {"decision": "REJECT", "grade": "MISMATCH"}


def test_normalize_llm_review_payload_debug_reason_is_capped():
    payload = _norm_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "debug_reason": "  A" * 200,
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
            ],
        },
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )

    assert len(payload["debug_reason"]) <= 300


def _keep_payload_with_alignment(**overrides):
    base = {
        "fit_review": {"decision": "KEEP", "grade": "STRONG"},
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "status": "supported",
                "capability_name": "stakeholder engagement",
                "matched_job_text": "work with stakeholders",
                "profile_support": ["stakeholder management"],
                "matched_candidate_fact": "stakeholder engagement",
            },
        ],
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("alignment", ["same", "adjacent", "different"])
def test_normalize_llm_review_payload_accepts_allowed_occupation_alignments(alignment):
    payload = _norm_payload(
        _keep_payload_with_alignment(
            occupation_alignment=alignment,
            occupation_alignment_reason=f"Matches {alignment} classification reasoning.",
        ),
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )

    assert payload["occupation_alignment"] == alignment
    assert payload["occupation_alignment_reason"] == f"Matches {alignment} classification reasoning."


def test_normalize_llm_review_payload_degrades_invalid_occupation_alignment(caplog):
    with caplog.at_level("WARNING"):
        payload = _norm_payload(
            _keep_payload_with_alignment(
                occupation_alignment="totally different career",
                occupation_alignment_reason="nonsense",
            ),
            valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
        )

    assert payload["occupation_alignment"] == llm_gate.LLM_INVALID_OCCUPATION_ALIGNMENT
    assert "invalid_occupation_alignment" in caplog.text


def test_normalize_llm_review_payload_degrades_missing_occupation_alignment():
    payload = _norm_payload(
        _keep_payload_with_alignment(),
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )

    assert payload["occupation_alignment"] == llm_gate.LLM_INVALID_OCCUPATION_ALIGNMENT
    assert payload["occupation_alignment_reason"] == ""


def test_normalize_llm_review_payload_never_rejects_on_occupation_alignment():
    # A KEEP with invalid occupation_alignment must still succeed — occupation
    # alignment must never gate KEEP/REJECT, only adjust score downstream.
    payload = _norm_payload(
        _keep_payload_with_alignment(occupation_alignment="not-a-real-value"),
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )

    assert payload["fit_review"]["decision"] == "KEEP"


def test_request_learning_payload_uses_single_llm_call(monkeypatch):
    called = {"count": 0}

    class _FakeParsed:
        def model_dump(self):
            return {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "requirement_coverage": [
                    {
                        "requirement": "Stakeholder engagement",
                        "requirement_type": "capability",
                        "requirement_kind": "professional_capability",
                        "status": "supported",
                        "capability_name": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "profile_support": ["stakeholder management"],
                        "matched_candidate_fact": "Stakeholder Engagement",
                    },
                ],
            }

    class _FakeResponse:
        output_parsed = _FakeParsed()
        usage = None

    class _FakeResponses:
        def parse(self, **kwargs):
            called["count"] += 1
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    monkeypatch.setattr(llm_gate, "client", _FakeClient())
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {"candidate_capabilities": [{"name": "Stakeholder Engagement"}]},
    )

    payload = llm_gate._request_learning_payload(
        "Business analyst role supporting stakeholders.", fit_review=True
    )

    assert called["count"] == 1
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "STRONG"}


def test_request_learning_payload_uses_debug_fit_review_schema_when_enabled(monkeypatch):
    captured = {}

    class _FakeParsed:
        def model_dump(self):
            return {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "requirement_coverage": [
                    {
                        "requirement": "Stakeholder engagement",
                        "requirement_type": "capability",
                        "requirement_kind": "professional_capability",
                        "status": "supported",
                        "capability_name": "Stakeholder Engagement",
                        "match_source": "capability_name",
                        "matched_profile_term": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "profile_support": ["Led stakeholder engagement."],
                        "matched_candidate_fact": "Stakeholder Engagement",
                    },
                ],
            }

    class _FakeResponse:
        output_parsed = _FakeParsed()
        usage = None

    class _FakeResponses:
        def parse(self, **kwargs):
            captured["text_format"] = kwargs.get("text_format")
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    monkeypatch.setattr(llm_gate, "client", _FakeClient())
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {"candidate_capabilities": [{"name": "Stakeholder Engagement"}]},
    )
    monkeypatch.setattr(
        llm_gate,
        "get_llm_fit_review_debug_match_diagnostics_enabled",
        lambda: True,
    )

    payload = llm_gate._request_learning_payload(
        "Business analyst role supporting stakeholders.", fit_review=True
    )

    assert captured["text_format"] is llm_gate._LLMFitReviewDebugPayload
    assert payload["requirement_coverage"][0]["match_source"] == "capability_name"
    assert payload["requirement_coverage"][0]["matched_profile_term"] == "Stakeholder Engagement"


def test_normalize_llm_review_payload_distinguishes_capability_name_and_related_skill_matches(
    monkeypatch,
):
    monkeypatch.setattr(
        llm_gate,
        "get_llm_fit_review_debug_match_diagnostics_enabled",
        lambda: True,
    )

    payload = _norm_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "match_source": "capability_name",
                    "matched_profile_term": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["Led stakeholder engagement across delivery teams."],
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Requirements traceability",
                    "status": "supported",
                    "capability_name": "business analysis",
                    "match_source": "related_skill",
                    "matched_profile_term": "requirements traceability",
                    "matched_job_text": "support technical requirements traceability",
                    "profile_support": [
                        "Owned requirements traceability matrices across delivery."
                    ],
                    "covered_requirement_elements": ["requirements traceability"],
                    "matched_candidate_fact": "business analysis",
                },
            ],
        },
        valid_capability_names={
            "stakeholder engagement": "Stakeholder Engagement",
            "business analysis": "Business Analysis",
        },
    )

    assert payload["requirement_coverage"][0]["matched_candidate_fact"] == "Stakeholder Engagement"
    assert payload["requirement_coverage"][0]["match_source"] == "capability_name"
    assert payload["requirement_coverage"][0]["matched_profile_term"] == "stakeholder engagement"
    assert payload["requirement_coverage"][1]["matched_candidate_fact"] == "Business Analysis"
    assert payload["requirement_coverage"][1]["match_source"] == "related_skill"
    assert payload["requirement_coverage"][1]["matched_profile_term"] == "requirements traceability"


def test_request_learning_payload_retries_once_on_invalid_json(monkeypatch, caplog):
    called = {"count": 0}

    class _FakeParsed:
        def model_dump(self):
            return {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "requirement_coverage": [
                    {
                        "requirement": "Stakeholder engagement",
                        "requirement_type": "capability",
                        "requirement_kind": "professional_capability",
                        "status": "supported",
                        "capability_name": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "profile_support": ["stakeholder management"],
                        "matched_candidate_fact": "Stakeholder Engagement",
                    },
                ],
            }

    class _FakeResponse:
        output_parsed = _FakeParsed()
        usage = None

    class _FakeResponses:
        def parse(self, **kwargs):
            called["count"] += 1
            if called["count"] == 1:
                raise ValidationError.from_exception_data(
                    "_LLMFitReviewPayload",
                    [
                        {
                            "type": "json_invalid",
                            "loc": (),
                            "msg": "Invalid JSON",
                            "input": '{"fit_review":{"decision":"KEEP"',
                            "ctx": {"error": "EOF while parsing a string"},
                        }
                    ],
                )
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    monkeypatch.setattr(llm_gate, "client", _FakeClient())
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {"candidate_capabilities": [{"name": "Stakeholder Engagement"}]},
    )

    with caplog.at_level("WARNING"):
        payload = llm_gate._request_learning_payload(
            "Business analyst role supporting stakeholders.", fit_review=True
        )

    assert called["count"] == 2
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "STRONG"}
    assert "[LLM][RETRY]" in caplog.text


def test_request_learning_payload_returns_usage_summary(monkeypatch):
    class _FakeUsage:
        input_tokens = 321
        output_tokens = 45

    class _FakeParsed:
        def model_dump(self):
            return {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "requirement_coverage": [
                    {
                        "requirement": "Stakeholder engagement",
                        "requirement_type": "capability",
                        "requirement_kind": "professional_capability",
                        "status": "supported",
                        "capability_name": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "profile_support": ["stakeholder management"],
                        "matched_candidate_fact": "Stakeholder Engagement",
                    },
                ],
            }

    class _FakeResponse:
        output_parsed = _FakeParsed()
        usage = _FakeUsage()

    class _FakeResponses:
        def parse(self, **kwargs):
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    monkeypatch.setattr(llm_gate, "client", _FakeClient())
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: "test-model")
    monkeypatch.setattr(
        llm_gate,
        "_get_llm_pricing_per_1m",
        lambda: {"test-model": {"input": 1.0, "output": 2.0}},
    )
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {"candidate_capabilities": [{"name": "Stakeholder Engagement"}]},
    )

    payload = llm_gate._request_learning_payload(
        "Business analyst role supporting stakeholders.", fit_review=True
    )

    assert payload["llm_input_tokens"] == 321
    assert payload["llm_output_tokens"] == 45
    assert payload["llm_cost_usd"] > 0


def test_strong_grade_requires_requirement_capability_evidence():
    payload = _norm_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "not_shown",
                    "capability_name": "",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": [],
                    "matched_candidate_fact": "",
                },
                {
                    "requirement": "Process mapping",
                    "status": "not_shown",
                    "capability_name": "",
                    "matched_job_text": "map the current process",
                    "profile_support": [],
                    "matched_candidate_fact": "",
                },
            ],
        },
        valid_capability_names={},
    )

    assert payload["fit_review"]["grade"] in {"POOR", "WEAK", "SOLID", "MISMATCH"}
    assert payload["fit_review"]["grade"] not in {"STRONG", "EXCELLENT"}


def test_prospend_style_partial_coverage_does_not_become_strong():
    payload = _norm_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "Stakeholder Engagement",
                    "matched_job_text": "stakeholder workshops",
                    "profile_support": ["stakeholder engagement"],
                    "matched_candidate_fact": "Stakeholder Engagement",
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_supported",
                    "capability_name": "Process Mapping",
                    "matched_job_text": "process mapping",
                    "profile_support": ["process mapping"],
                    "matched_candidate_fact": "Process Mapping",
                },
                {
                    "requirement": "UAT support",
                    "status": "partially_supported",
                    "capability_name": "Acceptance Testing",
                    "matched_job_text": "uat support",
                    "profile_support": ["user acceptance testing"],
                    "matched_candidate_fact": "Acceptance Testing",
                },
            ],
        },
        valid_capability_names={
            "stakeholder engagement": "Stakeholder Engagement",
            "process mapping": "Process Mapping",
            "acceptance testing": "Acceptance Testing",
        },
    )

    assert payload["fit_review"]["grade"] == "SOLID"


# ── derive_fit_review_grade contract ─────────────────────────────────────────


def _cov(req: str, status: str, cap: str = "") -> dict:
    # JH-298 correction: a capability row grades only when it is explicitly
    # professional_capability. These grade-contract fixtures are ordinary scored
    # capabilities, so stamp the kind; tests that exercise the behavioural /
    # unclassified / missing-kind axis override or omit it deliberately.
    return {
        "requirement": req,
        "status": status,
        "capability_name": cap,
        "requirement_kind": "professional_capability",
        "matched_job_text": "",
        "profile_support": [],
               "matched_candidate_fact": cap,
    }


def test_all_supported_three_reqs_gives_excellent():
    coverage = [_cov(f"req{i}", "supported", f"cap{i}") for i in range(3)]
    assert llm_gate.derive_fit_review_grade(coverage) == "EXCELLENT"


def test_all_supported_two_reqs_gives_strong():
    coverage = [_cov("req1", "supported", "cap1"), _cov("req2", "supported", "cap2")]
    assert llm_gate.derive_fit_review_grade(coverage) == "STRONG"


def test_mostly_supported_no_mismatch_gives_strong():
    # 3 supported + 1 partial out of 4 total → support_score=3.5/4=0.875 → STRONG
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "supported", "cap2"),
        _cov("req3", "supported", "cap3"),
        _cov("req4", "partially_supported", "cap4"),
    ]
    assert llm_gate.derive_fit_review_grade(coverage) == "STRONG"


def test_mixed_partial_no_mismatch_gives_solid():
    # 2 supported + 2 partial out of 4 → score=3/4=0.75 → SOLID (not STRONG: 2 partials)
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "supported", "cap2"),
        _cov("req3", "partially_supported", "cap3"),
        _cov("req4", "partially_supported", "cap4"),
    ]
    grade = llm_gate.derive_fit_review_grade(coverage)
    assert grade == "SOLID"


def test_low_support_gives_weak():
    # 1 supported out of 4 → score=1/4=0.25 → WEAK
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "not_shown"),
        _cov("req3", "not_shown"),
        _cov("req4", "not_shown"),
    ]
    assert llm_gate.derive_fit_review_grade(coverage) == "WEAK"


def test_no_support_gives_poor():
    coverage = [_cov("req1", "not_shown"), _cov("req2", "not_shown")]
    assert llm_gate.derive_fit_review_grade(coverage) == "POOR"


def test_no_support_with_mismatch_gives_mismatch():
    coverage = [_cov("req1", "mismatch"), _cov("req2", "not_shown")]
    assert llm_gate.derive_fit_review_grade(coverage) == "MISMATCH"


def test_explicit_non_professional_capability_rows_never_grade():
    # JH-298 correction: a behavioural / unclassified capability row that leaked
    # past the upstream partition must neither lift nor dilute the grade.
    base = [_cov("req1", "supported", "cap1"), _cov("req2", "supported", "cap2")]
    assert llm_gate.derive_fit_review_grade(base) == "STRONG"

    behavioural = {
        **_cov("beh", "not_shown"),
        "requirement_type": "capability",
        "requirement_kind": llm_gate.LLM_REQUIREMENT_KIND_BEHAVIOURAL,
    }
    unclassified = {
        **_cov("unk", "not_shown"),
        "requirement_type": "capability",
        "requirement_kind": llm_gate.LLM_REQUIREMENT_KIND_UNCLASSIFIED,
    }
    # not_shown leaked rows must not drag STRONG down.
    assert (
        llm_gate.derive_fit_review_grade(base + [behavioural, unclassified]) == "STRONG"
    )

    # A leaked *supported* behavioural row must not manufacture EXCELLENT either.
    supported_behavioural = {
        **_cov("beh2", "supported", "capX"),
        "requirement_type": "capability",
        "requirement_kind": llm_gate.LLM_REQUIREMENT_KIND_BEHAVIOURAL,
    }
    assert llm_gate.derive_fit_review_grade(base + [supported_behavioural]) == "STRONG"


def test_mismatch_with_high_support_caps_at_weak():
    # Even with 3 supported + 1 mismatch, grade must be WEAK
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "supported", "cap2"),
        _cov("req3", "supported", "cap3"),
        _cov("req4", "mismatch"),
    ]
    assert llm_gate.derive_fit_review_grade(coverage) == "WEAK"


def test_mismatch_with_partial_support_caps_at_weak():
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "partially_supported", "cap2"),
        _cov("req3", "mismatch"),
    ]
    assert llm_gate.derive_fit_review_grade(coverage) == "WEAK"


def test_mismatch_cannot_become_solid():
    # support_ratio=0.5 with mismatch → must stay WEAK, never SOLID
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "mismatch"),
    ]
    grade = llm_gate.derive_fit_review_grade(coverage)
    assert grade not in {"SOLID", "STRONG", "EXCELLENT"}
    assert grade == "WEAK"


def test_mismatch_cannot_become_strong():
    coverage = [
        _cov("req1", "supported", "cap1"),
        _cov("req2", "supported", "cap2"),
        _cov("req3", "supported", "cap3"),
        _cov("req4", "supported", "cap4"),
        _cov("req5", "mismatch"),
    ]
    grade = llm_gate.derive_fit_review_grade(coverage)
    assert grade not in {"STRONG", "EXCELLENT"}


def test_empty_coverage_gives_poor():
    assert llm_gate.derive_fit_review_grade([]) == "POOR"


# ── importance-aware grade rules ──────────────────────────────────────────────


def _cov_imp(req: str, status: str, importance: str, cap: str = "") -> dict:
    # JH-298 correction: see _cov — capability rows grade only when explicitly
    # professional_capability.
    return {
        "requirement": req,
        "importance": importance,
        "status": status,
        "capability_name": cap,
        "requirement_kind": "professional_capability",
        "matched_job_text": "",
        "profile_support": [],
               "matched_candidate_fact": cap,
    }


def test_bonus_not_shown_does_not_materially_penalise():
    # 3 required fully supported + 4 bonus not_shown.
    # bonus weight is 0.25, so their not_shown barely reduces the ratio.
    coverage = [_cov_imp(f"m{i}", "supported", "mandatory", f"cap{i}") for i in range(3)] + [
        _cov_imp(f"n{i}", "not_shown", "bonus") for i in range(4)
    ]
    grade = llm_gate.derive_fit_review_grade(coverage)
    # required support_score = 3*3 = 9; max_score = 3*3 + 4*0.25 = 10
    # ratio = 0.9 → EXCELLENT not possible (total_items=7, not all supported)
    # supported_count(3) >= max(2, 7-1=6)? NO → skip STRONG
    # ratio(0.9) >= 0.5 → at least SOLID
    assert grade in {"SOLID", "STRONG", "EXCELLENT"}
    assert grade not in {"WEAK", "POOR", "MISMATCH"}


def test_required_not_shown_lowers_grade():
    # 3 bonus supported but 2 required not_shown.
    # mandatory gaps should keep grade low despite bonus coverage.
    coverage = [_cov_imp(f"n{i}", "supported", "bonus", f"cap{i}") for i in range(3)] + [
        _cov_imp(f"m{i}", "not_shown", "mandatory") for i in range(2)
    ]
    # support_score = 3*0.25 = 0.75; max_score = 3*0.25 + 2*3 = 6.75; ratio = 0.11
    grade = llm_gate.derive_fit_review_grade(coverage)
    assert grade in {"WEAK", "POOR", "MISMATCH"}


def test_required_mismatch_caps_at_weak():
    coverage = [
        _cov_imp("r1", "supported", "mandatory", "cap1"),
        _cov_imp("r2", "supported", "mandatory", "cap2"),
        _cov_imp("r3", "mismatch", "mandatory"),
    ]
    assert llm_gate.derive_fit_review_grade(coverage) == "WEAK"


# ── eligibility vs capability separation ──────────────────────────────────────


def _cov_elig(req: str, status: str, importance: str = "mandatory") -> dict:
    return {
        "requirement": req,
        "importance": importance,
        "requirement_type": "eligibility",
        "status": status,
        "matched_candidate_fact": req,
        "matched_job_text": "",
        "profile_support": [],
    }


def test_requirement_coverage_prompt_reserves_dedicated_eligibility_output():
    guidance = llm_gate.build_requirement_coverage_guidance()
    assert "eligibility_requirements are separate and do not consume this limit" in guidance
    assert '"eligibility_requirements"' in llm_gate.LLM_FIT_REVIEW_PROMPT_SHAPE
    assert (
        '"decomposition":{"operator":"single|and|or","elements":['
        in llm_gate.LLM_FIT_REVIEW_PROMPT_SHAPE
    )
    assert (
        '"capability_judgement":"capability|uncertain|non_capability"'
        in llm_gate.LLM_FIT_REVIEW_PROMPT_SHAPE
    )
    assert '"requirement_subtype":"..."' in llm_gate.LLM_FIT_REVIEW_PROMPT_SHAPE


def test_fit_review_preserves_and_splits_eligibility_outside_general_row_budget():
    general_rows = [
        {
            "requirement": f"Capability requirement {index}",
            "importance": "mandatory",
            "requirement_type": "capability",
            "canonical_requirement": f"Capability {index}",
            "status": "not_shown",
            "matched_job_text": f"Capability requirement {index}",
        }
        for index in range(8)
    ]
    result = _norm_payload(
        {
            "fit_review": {"decision": "MAYBE", "grade": "WEAK"},
            "requirement_coverage": general_rows,
            "eligibility_requirements": [
                {
                    "requirement": "Australian citizenship with Baseline Security Clearance",
                    "importance": "mandatory",
                    "requirement_type": "eligibility",
                    "canonical_requirement": "Baseline Security Clearance",
                    "status": "supported",
                    "matched_candidate_fact": "Baseline",
                    "matched_job_text": "Candidates must be Australian citizens with Baseline Security Clearance",
                    "profile_support": ["Baseline Security Clearance"],
                    "covered_requirement_elements": [
                        "Australian citizenship",
                        "Baseline Security Clearance",
                    ],
                }
            ],
        },
        valid_eligibility_names={
            "australian citizenship": "Australian Citizenship",
            "australian citizen": "Australian Citizenship",
            "baseline": "Baseline",
            "baseline security clearance": "Baseline",
        },
    )
    coverage = result["requirement_coverage"]
    eligibility_rows = [row for row in coverage if row["requirement_type"] == "eligibility"]
    capability_rows = [row for row in coverage if row["requirement_type"] == "capability"]
    assert len(capability_rows) == 8
    assert {row["matched_candidate_fact"] for row in eligibility_rows} == {
        "Australian Citizenship",
        "Baseline",
    }


def test_eligibility_row_after_general_limit_is_not_dropped():
    rows = [
        {
            "requirement": f"Capability requirement {index}",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "not_shown",
        }
        for index in range(8)
    ]
    rows.append(
        {
            "requirement": "Australian Citizenship is required",
            "importance": "mandatory",
            "requirement_type": "eligibility",
            "canonical_requirement": "Australian Citizenship",
            "status": "supported",
            "matched_candidate_fact": "Australian Citizenship",
            "matched_job_text": "Australian Citizenship is required",
            "profile_support": ["Australian Citizenship"],
        }
    )
    result = _norm_cov(
        rows,
        valid_eligibility_names={"australian citizenship": "Australian Citizenship"},
        max_items=8,
    )
    assert len(result) == 9
    assert result[-1]["requirement_type"] == "eligibility"


def test_required_eligibility_not_shown_caps_at_weak_despite_high_capability_support():
    # 9 required capabilities fully supported + 1 required eligibility fact never
    # surfaced. Support ratio alone would read 0.9 (STRONG territory), but an unresolved
    # required eligibility fact must not be diluted away by unrelated capability support.
    coverage = [
        _cov_imp(f"cap{i}", "supported", "mandatory", f"cap{i}") for i in range(9)
    ] + [_cov_elig("security clearance", "not_shown")]
    assert llm_gate.derive_fit_review_grade(coverage) == "WEAK"


def test_required_capability_not_shown_still_only_dilutes_ratio():
    # Same shape, but the unresolved required item is a capability, not eligibility —
    # existing dilution behaviour (not an auto-cap) must be unchanged.
    coverage = [
        _cov_imp(f"cap{i}", "supported", "mandatory", f"cap{i}") for i in range(9)
    ] + [_cov_imp("some other tool", "not_shown", "mandatory")]
    grade = llm_gate.derive_fit_review_grade(coverage)
    assert grade != "WEAK"


def test_has_eligibility_mismatch_true_for_eligibility_mismatch():
    coverage = [_cov_elig("work rights", "mismatch")]
    assert llm_gate.has_eligibility_mismatch(coverage) is True


def test_has_eligibility_mismatch_false_for_capability_mismatch():
    # A capability mismatch is not an eligibility mismatch — the two must stay separate.
    coverage = [_cov_imp("some skill", "mismatch", "mandatory")]
    assert llm_gate.has_eligibility_mismatch(coverage) is False


def test_has_eligibility_mismatch_false_for_eligibility_not_shown():
    coverage = [_cov_elig("work rights", "not_shown")]
    assert llm_gate.has_eligibility_mismatch(coverage) is False


def test_normalize_llm_review_payload_overrides_keep_to_reject_on_eligibility_mismatch():
    # The LLM itself said KEEP/EXCELLENT, but an eligibility fact is an explicit
    # mismatch (e.g. no security clearance). The deterministic gate must override the
    # model's own decision — eligibility is a hard boolean gate, not a scoring input.
    payload = _norm_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "requirement_coverage": [
                {
                    "requirement": "Security clearance",
                    "status": "mismatch",
                    "importance": "mandatory",
                    "requirement_type": "eligibility",
                    "matched_candidate_fact": "security clearance",
                },
            ],
        },
        valid_eligibility_names={"security clearance": "Security Clearance"},
    )
    assert payload["fit_review"]["decision"] == "REJECT"


def test_normalize_llm_review_payload_rejects_keep_when_all_capability_coverage_is_mismatch():
    # A derived MISMATCH grade is authoritative: a job with no supported requirement
    # coverage cannot remain KEEP just because the model returned KEEP.
    payload = _norm_payload(
        {
            "decision": "KEEP",
            "grade": "STRONG",
            "requirement_coverage": [
                {
                    "requirement": "Some tool",
                    "status": "mismatch",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "capability_name": "some tool",
                    "matched_candidate_fact": "some tool",
                },
            ],
        },
        valid_capability_names={"some tool": "Some Tool"},
    )
    assert payload["fit_review"]["grade"] == "MISMATCH"
    assert payload["fit_review"]["decision"] == "REJECT"


def test_importance_defaults_to_preferred_when_missing():
    # Items without importance should behave exactly as preferred (weight 1.0).
    coverage_with = [_cov_imp(f"r{i}", "supported", "preferred", f"cap{i}") for i in range(3)]
    coverage_without = [_cov(f"r{i}", "supported", f"cap{i}") for i in range(3)]
    assert llm_gate.derive_fit_review_grade(coverage_with) == llm_gate.derive_fit_review_grade(
        coverage_without
    )


def test_normalize_coverage_includes_importance_field():
    items = [
        {
            "requirement": "Agile delivery",
            "importance": "mandatory",
            "status": "supported",
            "capability_name": "agile methodologies",
            "matched_job_text": "agile ceremonies",
            "profile_support": [],
            "matched_candidate_fact": "agile methodologies",
        },
        {
            "requirement": "Nice portfolio",
            "importance": "bonus",
            "status": "not_shown",
            "capability_name": "",
            "matched_job_text": "portfolio optional",
            "profile_support": [],
            "matched_candidate_fact": "",
        },
    ]
    result = _norm_cov(
        items,
        valid_capability_names={"agile methodologies": "Agile Methodologies"},
    )
    assert result[0]["importance"] == "mandatory"
    assert result[1]["importance"] == "bonus"


def test_normalize_coverage_supports_eligibility_items():
    items = [
        {
            "requirement": "PV clearance",
            "importance": "mandatory",
            "requirement_type": "eligibility",
            "status": "supported",
            "matched_candidate_fact": "PV clearance",
            "matched_job_text": "Must hold PV clearance",
            "profile_support": ["PV clearance"],
        }
    ]
    result = _norm_cov(
        items,
        valid_eligibility_names={"pv clearance": "PV clearance"},
    )
    assert result[0]["requirement_type"] == "eligibility"
    assert result[0]["matched_candidate_fact"] == "PV clearance"
    assert result[0]["eligibility_name"] == "PV clearance"
    assert result[0]["capability_name"] == ""


def test_normalize_coverage_converts_invalid_eligibility_match_to_not_shown(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    items = [
        {
            "requirement": "Hold PV security clearance",
            "importance": "mandatory",
            "requirement_type": "eligibility",
            "status": "supported",
            "matched_candidate_fact": "government environments",
            "matched_job_text": "Must hold PV security clearance",
            "profile_support": ["government environments"],
        }
    ]
    result = _norm_cov(
        items,
        valid_eligibility_names={"pv clearance": "PV clearance"},
    )
    assert result[0]["requirement_type"] == "eligibility"
    assert result[0]["status"] == "not_shown"
    assert result[0]["requirement"] == "Hold PV security clearance"
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["eligibility_name"] == ""
    assert result[0]["capability_name"] == ""
    assert warnings
    assert warnings[0]["severity"] == "info"
    assert warnings[0]["category"] == "llm_requirement_coverage"
    assert warnings[0]["source"] == "llm_gate"
    assert warnings[0]["context"]["reason"] == "invalid_eligibility_match"
    assert warnings[0]["context"]["requirement_type_before"] == "eligibility"
    assert warnings[0]["context"]["status_before"] == "supported"
    assert warnings[0]["context"]["status_after"] == "not_shown"
    assert warnings[0]["fingerprint"] == llm_gate.make_system_warning_fingerprint(
        "Hold PV security clearance",
        "eligibility",
        "supported",
        "government environments",
        "Must hold PV security clearance",
    )


def test_normalize_coverage_defaults_invalid_importance_to_preferred():
    items = [
        {
            "requirement": "Python experience",
            "importance": "critical",  # not an allowed value
            "status": "supported",
            "capability_name": "python",
            "matched_job_text": "Python required",
            "profile_support": [],
            "matched_candidate_fact": "python",
        },
    ]
    result = _norm_cov(
        items,
        valid_capability_names={"python": "Python"},
    )
    assert result[0]["importance"] == "preferred"


def test_normalize_coverage_converts_invalid_capability_match_to_not_shown(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    items = [
        {
            "requirement": "SAP experience",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "finance transformation",
            "matched_job_text": "SAP experience",
            "profile_support": ["finance transformation"],
        }
    ]
    result = _norm_cov(
        items,
        valid_capability_names={"python": "Python"},
    )
    assert result[0]["requirement_type"] == "capability"
    assert result[0]["status"] == "not_shown"
    assert result[0]["requirement"] == "SAP experience"
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["capability_name"] == ""
    assert result[0]["eligibility_name"] == ""
    assert warnings
    # This fixture is stamped with an explicit professional_capability kind by
    # _stamp_default_kind, so the only warning is the invalid-match one; select
    # it by reason to stay robust if other warnings are added later.
    match_warning = next(
        w for w in warnings if w["context"]["reason"] == "invalid_capability_match"
    )
    assert match_warning["severity"] == "info"
    assert match_warning["category"] == "llm_requirement_coverage"
    assert match_warning["source"] == "llm_gate"
    assert match_warning["context"]["requirement_type_before"] == "capability"
    assert match_warning["context"]["status_before"] == "supported"
    assert match_warning["context"]["status_after"] == "not_shown"
    assert match_warning["fingerprint"] == llm_gate.make_system_warning_fingerprint(
        "SAP experience",
        "capability",
        "supported",
        "finance transformation",
        "SAP experience",
    )


def test_normalize_coverage_recovers_canonical_capability_from_profile_support():
    result = _norm_cov(
        [
            {
                "requirement": "Python experience",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "",
                "matched_job_text": "Python and Django",
                "profile_support": [
                    "Experienced backend development with Python and FastAPI"
                ],
            }
        ],
        valid_capability_names={
            "backend development": "Backend Development",
            "server-side development": "Backend Development",
        },
    )

    assert result[0]["status"] == "supported"
    assert result[0]["matched_candidate_fact"] == "Backend Development"
    assert result[0]["capability_name"] == "Backend Development"


def test_normalize_coverage_accepts_profile_capability_aliases():
    result = _norm_cov(
        [
            {
                "requirement": "API experience",
                "importance": "preferred",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "api development",
                "profile_support": ["Built REST APIs"],
            }
        ],
        valid_capability_names={
            "rest api design and development": "Rest Api Design And Development",
            "api development": "Rest Api Design And Development",
        },
    )

    assert result[0]["matched_candidate_fact"] == "Rest Api Design And Development"
    assert result[0]["capability_name"] == "Rest Api Design And Development"


def test_normalize_coverage_allows_profile_action_for_clear_single_fact():
    # A requirement that decomposes to exactly one atomic element, with an
    # explicit element canonical_fact_resolved=True capability judgement, is
    # safe to offer as an Add-to-profile action.
    result = _norm_cov(
        [
            {
                "requirement": "CBAP certification is required.",
                "importance": "mandatory",
                "requirement_type": "qualification",
                "canonical_requirement": "CBAP",
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "CBAP certification",
                            "capability_judgement": "capability",
                            "canonical_concept": "CBAP",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "CBAP certification is required.",
                "profile_support": [],
            }
        ],
        valid_qualification_names={},
    )

    assert result[0]["canonical_requirement"] == "CBAP"
    assert result[0]["profile_action_allowed"] is True
    assert result[0]["decomposition"]["operator"] == "single"


def test_normalize_coverage_allows_short_atomic_requirement_echoing_its_own_text():
    # A short atomic requirement's canonical name can legitimately equal the
    # requirement text verbatim (e.g. "Java"). The LLM owns that semantic
    # judgement via the element canonical_fact_resolved flag; deterministic code
    # must not guess it from text equality.
    result = _norm_cov(
        [
            {
                "requirement": "Java",
                "importance": "mandatory",
                "requirement_type": "capability",
                "canonical_requirement": "Java",
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "Java",
                            "capability_judgement": "capability",
                            "canonical_concept": "Java",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "Java",
                "profile_support": [],
            }
        ],
        valid_capability_names={},
    )

    assert result[0]["canonical_requirement"] == "Java"
    assert result[0]["profile_action_allowed"] is True


def test_normalize_coverage_blocks_profile_action_for_compound_row_with_existing_partial_evidence():
    """A collapsed AND row must not offer a duplicate/incorrect profile action."""
    result = _norm_cov(
        [
            {
                "requirement": "Experience with Jira, Confluence and Microsoft Office 365",
                "importance": "preferred",
                "requirement_type": "capability",
                "canonical_requirement": "jira & confluence",
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "Jira, Confluence and Microsoft Office 365",
                            "capability_judgement": "capability",
                            "canonical_concept": "jira & confluence",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": (
                    "Strong knowledge of Jira, Confluence and Microsoft Office 365, "
                    "with exposure to tools such as Figma and Miro highly regarded."
                ),
                "profile_support": [],
                "experience_components": [
                    {
                        "kind": "qualifier",
                        "text": "Jira, Confluence, Microsoft Office 365",
                        "profile_supported": True,
                        "profile_evidence": ["jira & confluence"],
                    }
                ],
            }
        ],
        valid_capability_names={"jira & confluence": "jira & confluence"},
    )

    assert len(result) == 1
    assert result[0]["status"] == "not_shown"
    assert result[0]["canonical_requirement"] == "jira & confluence"
    assert result[0]["profile_action_allowed"] is False


def test_normalize_coverage_blocks_profile_action_when_canonical_fact_resolved_is_missing():
    # A canonical label alone is not a profile-learning decision. With no
    # decomposition the row falls back to a synthesized non-actionable element,
    # so profile_action_allowed fails closed.
    result = _norm_cov(
        [
            {
                "requirement": "CBAP certification is required.",
                "importance": "mandatory",
                "requirement_type": "qualification",
                "canonical_requirement": "CBAP",
                "status": "not_shown",
                "matched_job_text": "CBAP certification is required.",
                "profile_support": [],
            }
        ],
        valid_qualification_names={},
    )

    assert result[0]["canonical_requirement"] == "CBAP"
    assert result[0]["profile_action_allowed"] is False


def test_normalize_coverage_blocks_profile_action_for_or_group_of_alternatives():
    # A disjunctive clause (any one of several certifications) decomposes to an
    # operator="or" row. An OR row is never directly actionable: it carries no
    # row-level canonical_requirement and profile_action_allowed stays False,
    # while every branch is preserved as its own element.
    result = _norm_cov(
        [
            {
                "requirement": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.",
                "importance": "bonus",
                "requirement_type": "qualification",
                "canonical_requirement": "",
                "decomposition": {
                    "operator": "or",
                    "elements": [
                        {
                            "text": name,
                            "capability_judgement": "capability",
                            "canonical_concept": name,
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                        for name in ("IIBA", "CBAP", "CCBA", "CSPO", "PSM")
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.",
                "profile_support": [],
            }
        ],
        valid_qualification_names={},
    )

    assert result[0]["canonical_requirement"] == ""
    assert result[0]["profile_action_allowed"] is False
    assert result[0]["decomposition"]["operator"] == "or"
    assert [el["canonical_concept"] for el in result[0]["decomposition"]["elements"]] == [
        "IIBA",
        "CBAP",
        "CCBA",
        "CSPO",
        "PSM",
    ]
    # Each branch is independently resolvable even though the row is not.
    assert all(
        el["element_profile_action_allowed"] is True
        for el in result[0]["decomposition"]["elements"]
    )


def test_normalize_coverage_blocks_row_profile_action_for_or_group_but_keeps_branches():
    # A certifying body name (IIBA) that is one branch of an OR clause must not
    # become a standalone profile-actionable qualification at the row level; the
    # row stays non-actionable while each branch is preserved.
    result = _norm_cov(
        [
            {
                "requirement": "IIBA, CBAP, or CCBA certification preferred.",
                "importance": "preferred",
                "requirement_type": "qualification",
                "canonical_requirement": "",
                "decomposition": {
                    "operator": "or",
                    "elements": [
                        {
                            "text": name,
                            "capability_judgement": "capability",
                            "canonical_concept": name,
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                        for name in ("IIBA", "CBAP", "CCBA")
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "IIBA, CBAP, or CCBA certification preferred.",
                "profile_support": [],
            }
        ],
        valid_qualification_names={},
    )

    assert result[0]["profile_action_allowed"] is False
    assert result[0]["decomposition"]["operator"] == "or"
    assert len(result[0]["decomposition"]["elements"]) == 3


def test_normalize_coverage_blocks_profile_action_for_single_branch_or_clause():
    # "CBAP or equivalent" is still a disjunctive clause even though only one
    # branch could be named. An operator="or" row is never a single actionable
    # concept, so profile_action_allowed must stay False.
    result = _norm_cov(
        [
            {
                "requirement": "CBAP or equivalent certification required.",
                "importance": "mandatory",
                "requirement_type": "qualification",
                "canonical_requirement": "",
                "decomposition": {
                    "operator": "or",
                    "elements": [
                        {
                            "text": "CBAP",
                            "capability_judgement": "capability",
                            "canonical_concept": "CBAP",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "CBAP or equivalent certification required.",
                "profile_support": [],
            }
        ],
        valid_qualification_names={},
    )

    assert result[0]["profile_action_allowed"] is False


def test_normalize_coverage_keeps_and_joined_requirements_independently_actionable():
    # Genuinely independent AND-joined requirements must each keep their own
    # correct profile_action_allowed value — the vague-alternatives gate must
    # not bleed across unrelated rows in the same payload.
    result = _norm_cov(
        [
            {
                "requirement": "Australian Citizenship is required",
                "importance": "mandatory",
                "requirement_type": "eligibility",
                "canonical_requirement": "Australian Citizenship",
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "Australian Citizenship",
                            "capability_judgement": "capability",
                            "canonical_concept": "Australian Citizenship",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "Australian Citizenship is required",
                "profile_support": [],
            },
            {
                "requirement": "NV2 Security Clearance is required",
                "importance": "mandatory",
                "requirement_type": "eligibility",
                "canonical_requirement": "NV2",
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "NV2 Security Clearance",
                            "capability_judgement": "capability",
                            "canonical_concept": "NV2",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "NV2 Security Clearance is required",
                "profile_support": [],
            },
        ],
        valid_eligibility_names={},
    )

    assert result[0]["profile_action_allowed"] is True
    assert result[1]["profile_action_allowed"] is True


def test_normalize_coverage_marks_invalid_requirement_type_for_review(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    items = [
        {
            "requirement": "PV clearance",
            "importance": "mandatory",
            "requirement_type": "credential",
            "status": "supported",
            "matched_candidate_fact": "PV clearance",
            "matched_job_text": "Must hold PV clearance",
            "profile_support": ["PV clearance"],
        }
    ]
    result = _norm_cov(
        items,
        valid_capability_names={"pv clearance": "PV clearance"},
        valid_eligibility_names={"pv clearance": "PV clearance"},
    )
    assert result[0]["requirement_type"] == "invalid"
    assert result[0]["status"] == "invalid"
    assert result[0]["requirement"] == "PV clearance"
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["eligibility_name"] == ""
    assert result[0]["capability_name"] == ""
    assert warnings
    assert warnings[0]["severity"] == "info"
    assert warnings[0]["category"] == "llm_requirement_coverage"
    assert warnings[0]["source"] == "llm_gate"
    assert warnings[0]["context"]["reason"] == "invalid_requirement_type"
    assert warnings[0]["context"]["requirement_type_before"] == "credential"
    assert warnings[0]["context"]["status_before"] == "supported"
    assert warnings[0]["context"]["status_after"] == "invalid"
    assert warnings[0]["fingerprint"] == llm_gate.make_system_warning_fingerprint(
        "PV clearance",
        "credential",
        "supported",
        "PV clearance",
        "Must hold PV clearance",
    )


def test_normalize_coverage_reclassifies_experience_wording_as_capability(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    result = _norm_cov(
        [
            {
                "requirement": "5+ years supporting client outcomes",
                "importance": "mandatory",
                "requirement_type": "eligibility",
                "status": "supported",
                "matched_candidate_fact": "",
            }
        ]
    )

    assert result[0]["requirement_type"] == "capability"
    assert warnings
    assert warnings[0]["context"]["reason"] == "deterministic_classification_override"
    assert warnings[0]["context"]["requirement_type_before"] == "eligibility"
    assert warnings[0]["context"]["requirement_type_after"] == "capability"


def test_normalize_coverage_reclassifies_security_clearance_as_eligibility(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    result = _norm_cov(
        [
            {
                "requirement": "Ability to obtain Baseline security clearance",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "",
            }
        ]
    )

    assert result[0]["requirement_type"] == "eligibility"
    assert warnings
    assert warnings[0]["context"]["reason"] == "deterministic_classification_override"
    assert warnings[0]["context"]["requirement_type_before"] == "capability"
    assert warnings[0]["context"]["requirement_type_after"] == "eligibility"


def test_normalize_coverage_marks_conflicting_classification_uncertain(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        llm_gate,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    result = _norm_cov(
        [
            {
                "requirement": "5+ years working in a security clearance environment",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "",
            }
        ]
    )

    assert result[0]["requirement_type"] == "uncertain"
    assert result[0]["status"] == "invalid"
    assert result[0]["llm_proposed_requirement_type"] == "capability"
    assert warnings
    assert warnings[0]["context"]["reason"] == "deterministic_classification_uncertain"
    assert warnings[0]["context"]["requirement_type_after"] == "uncertain"


def test_normalize_coverage_preserves_managed_eligibility_subtype_without_extra_llm_call():
    result = _norm_cov(
        [
            {
                "requirement": "Ability to obtain Baseline security clearance",
                "importance": "mandatory",
                "requirement_type": "eligibility",
                "status": "not_shown",
                "matched_candidate_fact": "",
            }
        ]
    )

    assert result[0]["requirement_type"] == "eligibility"
    assert result[0]["requirement_subtype"] == "clearance"


def test_normalize_coverage_keeps_valid_llm_other_eligibility_subtype():
    result = _norm_cov(
        [
            {
                "requirement": "Must satisfy a formal entry condition",
                "importance": "mandatory",
                "requirement_type": "eligibility",
                "requirement_subtype": "other",
                "status": "not_shown",
                "matched_candidate_fact": "",
            }
        ]
    )

    assert result[0]["requirement_subtype"] == "other"


def test_normalize_coverage_drops_eligibility_subtype_from_qualification():
    result = _norm_cov(
        [
            {
                "requirement": "CBAP certification",
                "importance": "preferred",
                "requirement_type": "qualification",
                "requirement_subtype": "clearance",
                "status": "not_shown",
                "matched_candidate_fact": "",
            }
        ],
        valid_qualification_names={},
    )

    assert result[0]["requirement_type"] == "qualification"
    assert "requirement_subtype" not in result[0]


def test_normalize_coverage_payload_without_decomposition_fails_closed():
    result = _norm_cov(
        [
            {
                "requirement": "Unresolved requirement with no decomposition supplied",
                "importance": "mandatory",
                "requirement_type": "capability",
                "canonical_requirement": "Some Concept",
                "status": "not_shown",
                "matched_candidate_fact": "",
            }
        ]
    )

    # No decomposition -> one synthesized non-actionable single element.
    assert result[0]["decomposition"]["operator"] == "single"
    assert result[0]["profile_action_allowed"] is False


def test_normalize_coverage_preserves_malformed_required_requirement():
    result = _norm_cov(
        [
            {
                "requirement": "Must hold an unfamiliar professional registration",
                "importance": "mandatory",
                "requirement_type": "credential",
                "status": "unexpected_status",
                "matched_candidate_fact": "",
            }
        ]
    )

    assert len(result) == 1
    assert result[0]["requirement"] == "Must hold an unfamiliar professional registration"
    assert result[0]["importance"] == "mandatory"
    assert result[0]["requirement_type"] == "invalid"
    assert result[0]["status"] == "invalid"


# ── managed prompt line loading ───────────────────────────────────────────────


def test_load_managed_prompt_lines_raises_on_missing_key(monkeypatch):
    monkeypatch.setattr("job_hunter_agent.knowledge_store.get_knowledge", lambda key: None)
    with pytest.raises(RuntimeError, match="seed the DB first"):
        llm_gate._load_managed_prompt_lines("nonexistent_key")


def test_load_managed_prompt_lines_raises_on_empty_lines(monkeypatch):
    monkeypatch.setattr("job_hunter_agent.knowledge_store.get_knowledge", lambda key: {"lines": []})
    with pytest.raises(ValueError, match="at least one prompt line"):
        llm_gate._load_managed_prompt_lines("any_key")


def test_build_requirement_coverage_guidance_includes_key_phrases():
    guidance = llm_gate.build_requirement_coverage_guidance()
    assert "requirement_coverage" in guidance
    assert "atomic" in guidance
    assert "Use at most" in guidance
    assert "capability or eligibility" in guidance
    assert "Do not mark every row mandatory" in guidance


def test_build_fit_review_grade_guidance_includes_key_phrase():
    guidance = llm_gate.build_fit_review_grade_guidance()
    assert "fit_review.grade" in guidance
    assert "MISMATCH" in guidance


def test_build_learning_guidance_includes_categories():
    guidance = llm_gate.build_learning_guidance()
    assert "capability_concept" in guidance
    assert "cv_farming_pattern" in guidance


def test_build_rejection_suggestions_guidance_includes_key_phrase():
    guidance = llm_gate.build_rejection_suggestions_guidance()
    assert "blocker" in guidance.lower()


def test_build_profile_storage_guidance_binds_mutations_to_atomic_canonical_fact():
    guidance = llm_gate.build_profile_storage_resolution_guidance()
    assert "one atomic candidate fact represented by canonical_hint" in guidance
    assert "only fact that may be persisted" in guidance
    assert "Financial Services Experience must not be placed under Governance" in guidance


# ── llm_judge_title ────────────────────────────────────────────────────────────


def _fake_title_judgment_client(payload: dict | None, *, output_text: str = ""):
    class _FakeParsed:
        def model_dump(self):
            return dict(payload or {})

    class _FakeResponse:
        usage = None
        output_parsed = _FakeParsed() if payload is not None else None

    resp = _FakeResponse()
    resp.output_text = output_text

    class _FakeResponses:
        def parse(self, **kwargs):
            return resp

    class _FakeClient:
        responses = _FakeResponses()

    return _FakeClient()

def test_llm_judge_title_returns_none_without_client():
    result = llm_gate.llm_judge_title("Business Analyst", ["business analyst"], [], llm_client=None)
    assert result is None


def test_llm_judge_title_returns_none_for_empty_title():
    client = _fake_title_judgment_client({"verdict": "match", "reason": "ok"})
    result = llm_gate.llm_judge_title("", ["business analyst"], [], llm_client=client)
    assert result is None


def test_llm_judge_title_returns_none_when_no_target_roles_configured():
    client = _fake_title_judgment_client({"verdict": "match", "reason": "ok"})
    result = llm_gate.llm_judge_title("Business Analyst", [], [], llm_client=client)
    assert result is None


def test_llm_judge_title_parses_no_match_verdict():
    client = _fake_title_judgment_client(
        {"verdict": "no_match", "reason": "Enablement/coordination role, not a target role."},
        output_text='```json\n{"verdict":"no_match","reason":"ignored raw text"}\n```',
    )
    result = llm_gate.llm_judge_title(
        "Business Enablement Coordinator", ["senior business analyst"], [], llm_client=client
    )
    assert result == {
        "verdict": "no_match",
        "reason": "Enablement/coordination role, not a target role.",
    }


def test_llm_judge_title_parses_match_verdict():
    client = _fake_title_judgment_client({"verdict": "match", "reason": "Direct match."})
    result = llm_gate.llm_judge_title(
        "Senior Business Analyst", ["senior business analyst"], [], llm_client=client
    )
    assert result == {"verdict": "match", "reason": "Direct match."}


def test_llm_judge_title_retries_retryable_structured_output_failure(caplog):
    calls = []

    class _FakeParsed:
        def model_dump(self):
            return {"verdict": "match", "reason": "Recovered response."}

    class _FakeResponse:
        usage = None
        output_parsed = _FakeParsed()

    class _FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ValueError("EOF while parsing structured JSON")
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    with caplog.at_level("WARNING"):
        result = llm_gate.llm_judge_title(
            "Business Analyst",
            ["business analyst"],
            [],
            llm_client=_FakeClient(),
        )

    assert result == {"verdict": "match", "reason": "Recovered response."}
    assert len(calls) == 2
    assert "[LLM][RETRY] purpose=title_judgment" in caplog.text




def test_llm_judge_title_prompt_treats_role_lists_as_direction_not_whitelist():
    captured = {}

    class _FakeParsed:
        def model_dump(self):
            return {"verdict": "uncertain", "reason": "Could be adjacent delivery work."}

    class _FakeResponse:
        usage = None
        output_parsed = _FakeParsed()

    class _FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    result = llm_gate.llm_judge_title(
        "Technology Delivery Specialist",
        ["business analyst"],
        ["ai implementation consultant"],
        ["Business Analysis", "Agile Delivery Management", "Stakeholder Management"],
        explore_adjacent_roles=True,
        llm_client=_FakeClient(),
    )

    prompt = captured["input"][0]["content"]
    assert captured["text_format"] is llm_gate._LLMTitleJudgment
    assert result["verdict"] == "uncertain"
    assert "NOT an exhaustive whitelist" in prompt
    assert "Agile Delivery Management" in prompt
    assert "Do not reject merely because the exact title is absent" in prompt

def test_llm_judge_title_strict_mode_keeps_original_whitelist_style_contract():
    captured = {}

    class _FakeParsed:
        def model_dump(self):
            return {"verdict": "no_match", "reason": "Not a target role."}

    class _FakeResponse:
        usage = None
        output_parsed = _FakeParsed()

    class _FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    llm_gate.llm_judge_title(
        "Technology Delivery Specialist",
        ["business analyst"],
        ["technical business analyst"],
        ["Agile Delivery Management"],
        llm_client=_FakeClient(),
    )

    prompt = captured["input"][0]["content"]
    assert "Target roles: business analyst" in prompt
    assert "Secondary target roles: technical business analyst" in prompt
    assert "NOT an exhaustive whitelist" not in prompt
    assert "Candidate capability signals" not in prompt


def test_normalize_review_rejects_model_keep_when_derived_grade_is_mismatch():
    payload = _norm_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "requirement_coverage": [
                {
                    "requirement": "Must have Salesforce",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "status": "mismatch",
                    "matched_candidate_fact": "",
                    "matched_job_text": "Must have Salesforce",
                    "profile_support": [],
                }
            ],
        }
    )

    assert payload["fit_review"]["grade"] == "MISMATCH"
    assert payload["fit_review"]["decision"] == "REJECT"


def test_llm_judge_title_returns_none_on_invalid_verdict():
    client = _fake_title_judgment_client({"verdict": "maybe", "reason": "unsure"})
    result = llm_gate.llm_judge_title(
        "Business Analyst", ["senior business analyst"], [], llm_client=client
    )
    assert result is None


def test_llm_judge_title_returns_none_on_unparseable_output():
    client = _fake_title_judgment_client(None, output_text="not json")
    result = llm_gate.llm_judge_title(
        "Business Analyst", ["senior business analyst"], [], llm_client=client
    )
    assert result is None


def test_llm_judge_title_returns_none_on_client_exception():
    class _RaisingResponses:
        def parse(self, **kwargs):
            raise RuntimeError("boom")

    class _RaisingClient:
        responses = _RaisingResponses()

    result = llm_gate.llm_judge_title(
        "Business Analyst", ["senior business analyst"], [], llm_client=_RaisingClient()
    )
    assert result is None


@pytest.mark.parametrize(
    "requirement, qualifier, profile_support",
    [
        (
            "5+ years’ experience as a Senior Business Analyst within the Australian Life Insurance industry",
            "Australian Life Insurance industry",
            ["Led business analysis in Australian Federal Government programs."],
        ),
        (
            "5+ years’ experience as a Senior Business Analyst within the Australian Life Insurance industry",
            "Australian Life Insurance industry",
            ["Worked on general insurance governance and compliance."],
        ),
        (
            "5+ years as a Business Analyst within telecommunications",
            "telecommunications",
            ["Led business analysis across delivery teams."],
        ),
    ],
)
def test_experience_duration_does_not_prove_missing_qualifier(
    requirement, qualifier, profile_support
):
    result = _norm_cov(
        [
            {
                "requirement": requirement,
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": requirement,
                "profile_support": profile_support,
                "experience_components": [
                    {"kind": "duration", "text": "5+ years"},
                    {
                        "kind": "role_or_activity",
                        "text": "Business Analyst",
                        "matched_role_family": "Senior Business Analyst",
                    },
                    {
                        "kind": "qualifier",
                        "text": qualifier,
                        "profile_supported": False,
                        "profile_evidence": [],
                    },
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Senior Business Analyst",
                "total_duration_months": 72,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 72, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "not_shown"
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["profile_support"] == []
    assert result[0]["experience_requirement_met"] is True


def test_unqualified_business_analyst_duration_remains_supported_from_role_history():
    result = _norm_cov(
        [
            {
                "requirement": "5+ years as a Business Analyst",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": "5+ years as a Business Analyst",
                "profile_support": [],
                "experience_components": [
                    {"kind": "duration", "text": "5+ years"},
                    {
                        "kind": "role_or_activity",
                        "text": "Business Analyst",
                        "matched_role_family": "Business Analyst",
                    },
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 60,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 60, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "supported"
    assert result[0]["experience_requirement_met"] is True


def test_met_experience_requirement_reconciles_not_shown_to_supported():
    requirement = "3+ years experience as Business Analyst"
    result = _norm_cov(
        [
            {
                "requirement": requirement,
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "not_shown",
                "matched_candidate_fact": "",
                "matched_job_text": requirement,
                "profile_support": [],
                "experience_components": [
                    {"kind": "duration", "text": "3+ years"},
                    {
                        "kind": "role_or_activity",
                        "text": "Business Analyst",
                        "matched_role_family": "Business Analyst",
                    },
                ],
            }
        ],
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 120,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 120, "is_current": False}],
            }
        ],
    )

    row = result[0]
    assert row["status"] == "supported"
    assert row["required_experience_months"] == 36
    assert row["matched_role_family"] == "Business Analyst"
    assert row["matched_role_family_months"] == 120
    assert row["experience_requirement_met"] is True


def test_incomplete_decomposition_without_qualifier_keeps_role_history_proof():
    """LLM omitted the role_or_activity fragment but tied the duration component
    to a real saved family and named no qualifier: the row must stay visible on
    the role-history proof, not be forced to a self-contradictory not_shown."""
    result = _norm_cov(
        [
            {
                "requirement": "Functional Business Analysis experience",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": "Minimum 5 years Functional Business Analysis experience",
                "profile_support": ["Ran BA activities across delivery teams."],
                "experience_components": [
                    {
                        "kind": "duration",
                        "text": "5 years",
                        "matched_role_family": "Business Analyst",
                    }
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 120,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 120, "is_current": False}],
            }
        ],
    )

    row = result[0]
    assert row["status"] == "supported"
    assert row["matched_role_family"] == "Business Analyst"
    assert row["matched_role_family_months"] == 120
    assert row["required_experience_months"] == 60
    assert row["experience_requirement_met"] is True


def test_incomplete_decomposition_with_qualifier_still_forces_not_shown():
    """The completeness guard stays active when a qualifier is in play: an
    incomplete decomposition around a qualifier cannot be trusted, so role
    history alone must not carry the row."""
    result = _norm_cov(
        [
            {
                "requirement": "5 years Business Analysis in health insurance",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": "5 years Business Analysis in health insurance",
                "profile_support": ["Ran BA activities across delivery teams."],
                "experience_components": [
                    {
                        "kind": "duration",
                        "text": "5 years",
                        "matched_role_family": "Business Analyst",
                    },
                    {
                        "kind": "qualifier",
                        "text": "health insurance",
                        "profile_supported": False,
                        "profile_evidence": [],
                    },
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 120,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 120, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "not_shown"
    assert result[0]["matched_candidate_fact"] == ""


def test_incomplete_decomposition_with_unresolved_family_still_forces_not_shown():
    """No qualifier, but the LLM tied the duration to a family the profile does
    not hold: the arithmetic never resolved, so the row cannot be carried on
    role history and stays held as before."""
    result = _norm_cov(
        [
            {
                "requirement": "5+ years Python backend development",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Python",
                "matched_job_text": "Minimum 5+ years Python backend development",
                "profile_support": ["Built Python services."],
                "experience_components": [
                    {
                        "kind": "duration",
                        "text": "5+ years",
                        "matched_role_family": "Python Developer",
                    }
                ],
            }
        ],
        valid_capability_names={"python": "Python"},
        role_experience=[
            {
                "normalized_title": "business analyst",
                "total_duration_months": 120,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 120, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "not_shown"
    assert result[0]["matched_candidate_fact"] == ""


def test_experience_qualifier_evidence_preserves_a_legitimate_partial_match():
    result = _norm_cov(
        [
            {
                "requirement": "5+ years as a Business Analyst within telecommunications",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": "5+ years as a Business Analyst within telecommunications",
                "profile_support": ["Delivered business analysis for telecommunications programs."],
                "experience_components": [
                    {"kind": "duration", "text": "5+ years"},
                    {
                        "kind": "role_or_activity",
                        "text": "Business Analyst",
                        "matched_role_family": "Business Analyst",
                    },
                    {
                        "kind": "qualifier",
                        "text": "telecommunications",
                        "profile_supported": True,
                        "profile_evidence": [
                            "Delivered business analysis for telecommunications programs."
                        ],
                    },
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 24,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 24, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "partially_supported"
    assert result[0]["matched_candidate_fact"] == "Business Analysis"
    assert result[0]["experience_requirement_met"] is False


def test_experience_qualifier_explicit_profile_support_preserves_a_full_match():
    requirement = (
        "5+ years’ experience as a Senior Business Analyst within the Australian Life Insurance industry"
    )
    evidence = "Delivered Senior Business Analyst work in the Australian Life Insurance industry."
    result = _norm_cov(
        [
            {
                "requirement": requirement,
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": requirement,
                "profile_support": [evidence],
                "experience_components": [
                    {"kind": "duration", "text": "5+ years"},
                    {
                        "kind": "role_or_activity",
                        "text": "Senior Business Analyst",
                        "matched_role_family": "Senior Business Analyst",
                    },
                    {
                        "kind": "qualifier",
                        "text": "Australian Life Insurance industry",
                        "profile_supported": True,
                        "profile_evidence": [evidence],
                    },
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Senior Business Analyst",
                "total_duration_months": 72,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 72, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "supported"
    assert result[0]["matched_candidate_fact"] == "Business Analysis"
    assert result[0]["experience_requirement_met"] is True


def test_experience_qualifier_support_requires_explicit_profile_evidence():
    requirement = "5+ years as a Business Analyst within telecommunications"
    result = _norm_cov(
        [
            {
                "requirement": requirement,
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Business Analysis",
                "matched_job_text": requirement,
                "profile_support": ["Delivered telecommunications business analysis."],
                "experience_components": [
                    {"kind": "duration", "text": "5+ years"},
                    {"kind": "role_or_activity", "text": "Business Analyst"},
                    {
                        "kind": "qualifier",
                        "text": "telecommunications",
                        "profile_supported": True,
                        "profile_evidence": [],
                    },
                ],
            }
        ],
        valid_capability_names={"business analysis": "Business Analysis"},
        role_experience=[
            {
                "normalized_title": "Business Analyst",
                "total_duration_months": 72,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 72, "is_current": False}],
            }
        ],
    )

    assert result[0]["status"] == "not_shown"
    assert result[0]["matched_candidate_fact"] == ""
    assert result[0]["profile_support"] == []


def test_requirement_coverage_rejects_broad_transferable_capability_as_partial_evidence():
    examples = [
        (
            "Commercial thinker understanding investment appraisals and ROI",
            "agile delivery management",
            ["Led agile delivery across technology projects."],
        ),
        (
            "Experience in banking, financial services or telecommunications",
            "business analysis",
            ["Performed business analysis across delivery projects."],
        ),
        (
            "Experience with complaints handling, dispute resolution, fraud or case management",
            "policy interpretation and translation",
            ["Translated policy into business rules."],
        ),
    ]
    for requirement, capability, support in examples:
        result = _norm_cov(
            [{
                "requirement": requirement,
                "importance": "preferred",
                "requirement_type": "capability",
                "status": "partially_supported",
                "matched_candidate_fact": capability,
                "matched_job_text": requirement,
                "profile_support": support,
            }],
            valid_capability_names={capability: capability.title()},
        )
        assert result[0]["status"] == "not_shown"
        assert result[0]["matched_candidate_fact"] == ""


def test_requirement_coverage_keeps_partial_match_when_evidence_covers_real_requirement_component():
    result = _norm_cov(
        [{
            "requirement": "Experience designing operational workflows and case management processes",
            "importance": "preferred",
            "requirement_type": "capability",
            "status": "partially_supported",
            "matched_candidate_fact": "process modelling",
            "matched_job_text": "Experience designing operational workflows and case management processes",
            "profile_support": ["Designed and modelled operational processes."],
            "covered_requirement_elements": ["operational processes"],
        }],
        valid_capability_names={"process modelling": "Process Modelling"},
    )
    assert result[0]["status"] == "partially_supported"


@pytest.mark.parametrize(
    "label, requirement, matched_job_text, matched_candidate_fact, profile_support, covered, expected",
    [
        (
            "one shared generic token is not evidence",
            "Hands-on AI model development",
            "Hands-on AI model development",
            "Data analysis",
            ["Comfortable adopting AI tools in day-to-day work."],
            ["AI"],
            False,
        ),
        (
            "resolved concept named in the requirement wording",
            "Requirements traceability across delivery",
            "support technical requirements traceability across delivery",
            "Requirements traceability",
            [],
            [],
            True,
        ),
        (
            "whole single-token requirement concept present in the evidence",
            "BPMN",
            "Model business processes in BPMN",
            "Process modelling",
            ["Documented current-state flows in BPMN 2.0."],
            [],
            True,
        ),
        (
            "two substantive shared tokens carry a broader match",
            "Operational workflow design and case management",
            "Operational workflow design and case management",
            "Process modelling",
            ["Designed operational workflow models for case management."],
            [],
            True,
        ),
        (
            "versioned identifier needs its own evidence",
            "SAP S/4HANA finance configuration",
            "SAP S/4HANA finance configuration",
            "SAP",
            ["Configured SAP finance modules for month-end close."],
            ["SAP"],
            False,
        ),
        # JH-299 correction: a resolved candidate concept that only shares the
        # modifier word with the requirement does not prove the same professional
        # concept. These three were verified false positives on the production
        # normalizer and must all come back non-positive.
        (
            "AI governance <- AI development",
            "AI governance",
            "AI governance",
            "AI development",
            [],
            [],
            False,
        ),
        (
            "Stakeholder facilitation <- Stakeholder management",
            "Stakeholder facilitation",
            "Stakeholder facilitation",
            "Stakeholder management",
            [],
            [],
            False,
        ),
        (
            "Data governance <- Data analysis",
            "Data governance",
            "Data governance",
            "Data analysis",
            [],
            [],
            False,
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else "",
)
def test_has_meaningful_requirement_evidence(
    label, requirement, matched_job_text, matched_candidate_fact, profile_support, covered, expected
):
    assert (
        llm_gate._has_meaningful_requirement_evidence(
            requirement,
            matched_job_text,
            matched_candidate_fact,
            profile_support,
            covered,
        )
        is expected
    ), label


def _storage_profile():
    return {
        "candidate_capabilities": [
            {
                "name": "Business Analysis",
                "level": "strong",
                "aliases": ["Requirements Analysis", "User stories"],
            },
        ],
        "candidate_qualifications": [
            {"name": "CBAP", "value": True, "aliases": []},
        ],
        "candidate_eligibility": [
            {"name": "Australian Citizenship", "value": True},
        ],
    }


def test_normalize_profile_storage_resolution_existing_requires_profile_owned_target():
    # Spec section C's core safety check: an EXISTING resolution target must be
    # literally present in the profile (name or alias) — an LLM hallucinating a
    # plausible-sounding name must fail closed, not write.
    with pytest.raises(ValueError, match="not profile-owned"):
        llm_gate.normalize_llm_profile_storage_resolution(
            {"resolution": "existing", "existing_name": "Java"},
            profile=_storage_profile(),
            requirement_type="capability",
        )


def test_normalize_profile_storage_resolution_existing_matches_via_any_alias():
    resolved_via_first_alias = llm_gate.normalize_llm_profile_storage_resolution(
        {"resolution": "existing", "existing_name": "Requirements Analysis"},
        profile=_storage_profile(),
        requirement_type="capability",
    )
    assert resolved_via_first_alias["profile_target"] == "Business Analysis"

    resolved_via_second_alias = llm_gate.normalize_llm_profile_storage_resolution(
        {"resolution": "existing", "existing_name": "User stories"},
        profile=_storage_profile(),
        requirement_type="capability",
    )
    assert resolved_via_second_alias["profile_target"] == "Business Analysis"


def test_normalize_profile_storage_resolution_rejects_model_generated_related_terms():
    with pytest.raises(ValueError, match="unsupported fields"):
        llm_gate.normalize_llm_profile_storage_resolution(
            {
                "resolution": "existing",
                "existing_name": "Business Analysis",
                "related_terms": ["Communication"],
            },
            profile=_storage_profile(),
            requirement_type="capability",
        )


def test_normalize_profile_storage_resolution_new_rejects_name_collision():
    with pytest.raises(ValueError, match="duplicates an existing profile name or alias"):
        llm_gate.normalize_llm_profile_storage_resolution(
            {"resolution": "new", "new_name": "requirements analysis"},
            profile=_storage_profile(),
            requirement_type="capability",
        )


def test_normalize_profile_storage_resolution_new_accepts_genuinely_new_name():
    resolved = llm_gate.normalize_llm_profile_storage_resolution(
        {"resolution": "new", "new_name": "Java"},
        profile=_storage_profile(),
        requirement_type="capability",
    )
    assert resolved == {"resolution": "new", "profile_target": "Java"}


def test_normalize_profile_storage_resolution_unresolved_rejects_any_proposed_change():
    with pytest.raises(ValueError, match="must not propose profile changes"):
        llm_gate.normalize_llm_profile_storage_resolution(
            {"resolution": "unresolved", "new_name": "Java"},
            profile=_storage_profile(),
            requirement_type="capability",
        )

    resolved = llm_gate.normalize_llm_profile_storage_resolution(
        {"resolution": "unresolved"},
        profile=_storage_profile(),
        requirement_type="capability",
    )
    assert resolved == {"resolution": "unresolved", "profile_target": ""}


class _FakeProfileStorageParsed:
    def __init__(self, **fields):
        # Mirrors _LLMProfileStorageResolution's pydantic defaults.
        self._fields = {"existing_name": "", "new_name": "", **fields}

    def model_dump(self):
        return dict(self._fields)


class _FakeProfileStorageClient:
    def __init__(self, **fields):
        self._parsed = _FakeProfileStorageParsed(**fields)

    class _Responses:
        def __init__(self, parsed):
            self._parsed = parsed

        def parse(self, **kwargs):
            response = type("_Resp", (), {"output_parsed": self._parsed, "usage": None})()
            return response

    @property
    def responses(self):
        return self._Responses(self._parsed)


def test_llm_resolve_profile_storage_logs_request_and_timing(monkeypatch, caplog):
    calls = []

    class _Parsed:
        def model_dump(self):
            return {"resolution": "new", "existing_name": "", "new_name": "Java"}

    class _Responses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return type("_Resp", (), {"output_parsed": _Parsed(), "usage": None})()

    class _Client:
        responses = _Responses()

    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        llm_gate,
        "get_llm_model_override_for_purpose",
        lambda purpose: "gpt-5.6-luna" if purpose == "profile_storage_resolution" else None,
    )
    monkeypatch.setattr(
        llm_gate,
        "_log_llm_model_once",
        lambda: (_ for _ in ()).throw(AssertionError("account model fallback must not be used")),
    )
    caplog.set_level("DEBUG", logger="job_hunter_agent.llm_gate")

    result = llm_gate.llm_resolve_profile_storage(
        {
            "requirement_type": "capability",
            "requirement": "Java development experience",
            "matched_job_text": "Java development experience",
            "canonical_requirement": "Java",
        },
        _storage_profile(),
        llm_client=_Client(),
    )

    assert result == {"resolution": "new", "profile_target": "Java"}
    assert calls[0]["model"] == "gpt-5.6-luna"
    assert "[LLM][REQUEST] purpose=profile_storage_resolution" in caplog.text
    assert "[LLM][TIMING] purpose=profile_storage_resolution" in caplog.text


def test_llm_resolve_profile_storage_returns_validated_existing_resolution(monkeypatch):
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    client = _FakeProfileStorageClient(resolution="existing", existing_name="Business Analysis")

    result = llm_gate.llm_resolve_profile_storage(
        {
            "requirement_type": "capability",
            "requirement": "Write clear business requirements",
            "matched_job_text": "Write clear business requirements",
            "canonical_requirement": "Business requirements analysis",
        },
        _storage_profile(),
        llm_client=client,
    )

    assert result == {
        "resolution": "existing",
        "profile_target": "Business Analysis",
    }


def test_llm_resolve_profile_storage_fails_closed_when_llm_hallucinates_unowned_target(monkeypatch):
    # Even if the LLM call itself succeeds, a hallucinated existing_name that
    # is not actually in the profile must never reach save_profile — the
    # deterministic validator inside llm_resolve_profile_storage must raise.
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    client = _FakeProfileStorageClient(resolution="existing", existing_name="Java")

    with pytest.raises(ValueError, match="not profile-owned"):
        llm_gate.llm_resolve_profile_storage(
            {
                "requirement_type": "capability",
                "requirement": "Java development experience is required.",
                "matched_job_text": "Java development experience is required.",
                "canonical_requirement": "Java",
            },
            _storage_profile(),
            llm_client=client,
        )


def test_llm_resolve_profile_storage_raises_without_an_available_client(monkeypatch):
    monkeypatch.setattr(llm_gate, "client", None)
    with pytest.raises(RuntimeError, match="Profile storage resolution requires an available LLM client"):
        llm_gate.llm_resolve_profile_storage(
            {
                "requirement_type": "capability",
                "requirement": "Java development experience is required.",
                "matched_job_text": "Java development experience is required.",
            },
            _storage_profile(),
            llm_client=None,
        )


def test_llm_resolve_profile_storage_wraps_client_exception_as_llm_call_error(monkeypatch):
    class _RaisingResponses:
        def parse(self, **kwargs):
            raise RuntimeError("boom")

    class _RaisingClient:
        responses = _RaisingResponses()

    with pytest.raises(llm_gate.LLMCallError):
        llm_gate.llm_resolve_profile_storage(
            {
                "requirement_type": "capability",
                "requirement": "Java development experience is required.",
                "matched_job_text": "Java development experience is required.",
                "canonical_requirement": "Java",
            },
            _storage_profile(),
            llm_client=_RaisingClient(),
        )


def test_llm_resolve_profile_storage_returns_unresolved_without_calling_llm_when_canonical_requirement_is_empty():
    class _FailingResponses:
        def parse(self, **kwargs):
            raise AssertionError("LLM must not be called when canonical_requirement is empty")

    class _FailingClient:
        responses = _FailingResponses()

    result = llm_gate.llm_resolve_profile_storage(
        {
            "requirement_type": "capability",
            "requirement": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM)",
            "matched_job_text": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM)",
            "canonical_requirement": "",
        },
        _storage_profile(),
        llm_client=_FailingClient(),
    )

    assert result == {"resolution": "unresolved", "profile_target": ""}


def test_profile_storage_lookup_folds_all_aliases():
    lookup = llm_gate._profile_storage_lookup(_storage_profile(), "capability")
    assert lookup["business analysis"] == "Business Analysis"
    assert lookup["requirements analysis"] == "Business Analysis"
    assert lookup["user stories"] == "Business Analysis"


def test_profile_storage_items_groups_aliases_under_canonical_name():
    items = llm_gate._profile_storage_items(_storage_profile(), "capability")
    assert items == [
        {
            "name": "Business Analysis",
            "aliases": ["requirements analysis", "user stories"],
        }
    ]
