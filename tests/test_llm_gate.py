"""Tests for llm gate."""

import pytest
from pydantic import ValidationError

from job_hunter_agent import llm_gate


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


def test_build_capability_naming_guidance_uses_managed_defaults_only():
    prompt = llm_gate.build_capability_naming_guidance()

    assert (
        "You are reviewing and labelling candidate professional capability clusters extracted from a CV."
        in prompt
    )
    assert "Default capability naming guidance:" in prompt
    assert "Clusters:" in prompt
    assert "skip" not in prompt


def test_build_job_requirements_prompt_includes_work_type_guidance():
    prompt = llm_gate.build_job_requirements_prompt()

    assert "Permanent" in prompt
    assert "Contract" in prompt
    assert "Full Time Contract / FTC" in prompt
    assert "Temporary" in prompt
    assert "Unknown when the work type is unclear" in prompt


def test_fit_review_prompt_excludes_learning_guidance():
    prompt = llm_gate._build_learning_prompt("Job description", fit_review=True)

    assert "Learning categories available:" not in prompt
    assert "role_title_pattern" not in prompt
    assert "capability_concept" not in prompt
    assert "learning_candidates" not in prompt
    assert "Do not save anything" not in prompt
    assert "Do not invent new categories" not in prompt
    assert "requirement_coverage" in prompt
    assert "fit_review.grade" in prompt


def test_learning_only_prompt_retains_learning_guidance():
    prompt = llm_gate._build_learning_prompt("Job description", fit_review=False)

    assert "Learning categories available:" in prompt
    assert "capability_concept" in prompt
    assert "learning_candidates" in prompt
    assert "Do not save anything" in prompt
    assert "Do not invent new categories" in prompt


def test_normalize_llm_review_payload_derives_grade_from_requirement_coverage():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "learning_candidates": [
                {"signal": "platform engineer", "suggested_category": "capability_concept"},
            ],
            "job_requirements": [
                "Stakeholder engagement",
                "Process mapping",
            ],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["stakeholder management"],
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_supported",
                    "capability_name": "process mapping",
                    "matched_job_text": "map the current process",
                    "profile_support": ["process mapping"],
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
        "debug_reason": "",
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "importance": "preferred",
                "status": "supported",
                "capability_name": "Stakeholder Engagement",
                "matched_job_text": "work with stakeholders",
                "profile_support": ["stakeholder management"],
            },
            {
                "requirement": "Process mapping",
                "importance": "preferred",
                "status": "partially_supported",
                "capability_name": "Process Mapping",
                "matched_job_text": "map the current process",
                "profile_support": ["process mapping"],
            },
        ],
        "job_requirements": ["Stakeholder engagement", "Process mapping"],
    }


def test_normalize_llm_review_payload_rejects_keep_without_requirement_coverage():
    with pytest.raises(
        llm_gate.LLMReviewValidationError,
        match="LLM KEEP review requires non-empty requirement_coverage",
    ):
        llm_gate.normalize_llm_review_payload(
            {
                "fit_review": {"decision": "KEEP", "grade": "STRONG"},
                "job_requirements": ["Stakeholder engagement"],
                "requirement_coverage": [],
            }
        )


def test_normalize_llm_review_payload_debug_reason_is_capped():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "debug_reason": "  A" * 200,
            "job_requirements": ["Stakeholder engagement"],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["stakeholder management"],
                },
            ],
        },
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )

    assert len(payload["debug_reason"]) <= 300


def test_request_learning_payload_uses_single_llm_call(monkeypatch):
    called = {"count": 0}

    class _FakeParsed:
        def model_dump(self):
            return {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "job_requirements": ["Stakeholder engagement"],
                "requirement_coverage": [
                    {
                        "requirement": "Stakeholder engagement",
                        "status": "supported",
                        "capability_name": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "profile_support": ["stakeholder management"],
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


def test_request_learning_payload_retries_once_on_invalid_json(monkeypatch, caplog):
    called = {"count": 0}

    class _FakeParsed:
        def model_dump(self):
            return {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "job_requirements": ["Stakeholder engagement"],
                "requirement_coverage": [
                    {
                        "requirement": "Stakeholder engagement",
                        "status": "supported",
                        "capability_name": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "profile_support": ["stakeholder management"],
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


def test_strong_grade_requires_requirement_capability_evidence():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "job_requirements": ["Stakeholder engagement", "Process mapping"],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "not_shown",
                    "capability_name": "",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": [],
                },
                {
                    "requirement": "Process mapping",
                    "status": "not_shown",
                    "capability_name": "",
                    "matched_job_text": "map the current process",
                    "profile_support": [],
                },
            ],
        },
        valid_capability_names={},
    )

    assert payload["fit_review"]["grade"] in {"POOR", "WEAK", "SOLID", "MISMATCH"}
    assert payload["fit_review"]["grade"] not in {"STRONG", "EXCELLENT"}


def test_prospend_style_partial_coverage_does_not_become_strong():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "job_requirements": [
                "Stakeholder engagement",
                "Process mapping",
                "UAT support",
            ],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "supported",
                    "capability_name": "Stakeholder Engagement",
                    "matched_job_text": "stakeholder workshops",
                    "profile_support": ["stakeholder engagement"],
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_supported",
                    "capability_name": "Process Mapping",
                    "matched_job_text": "process mapping",
                    "profile_support": ["process mapping"],
                },
                {
                    "requirement": "UAT support",
                    "status": "partially_supported",
                    "capability_name": "Acceptance Testing",
                    "matched_job_text": "uat support",
                    "profile_support": ["user acceptance testing"],
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
    return {
        "requirement": req,
        "status": status,
        "capability_name": cap,
        "matched_job_text": "",
        "profile_support": [],
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
    return {
        "requirement": req,
        "importance": importance,
        "status": status,
        "capability_name": cap,
        "matched_job_text": "",
        "profile_support": [],
    }


def test_nice_to_have_not_shown_does_not_materially_penalise():
    # 3 mandatory fully supported + 4 nice_to_have not_shown.
    # nice_to_have weight is 0.25, so their not_shown barely reduces the ratio.
    coverage = [_cov_imp(f"m{i}", "supported", "mandatory", f"cap{i}") for i in range(3)] + [
        _cov_imp(f"n{i}", "not_shown", "nice_to_have") for i in range(4)
    ]
    grade = llm_gate.derive_fit_review_grade(coverage)
    # mandatory support_score = 3*3 = 9; max_score = 3*3 + 4*0.25 = 10
    # ratio = 0.9 → EXCELLENT not possible (total_items=7, not all supported)
    # supported_count(3) >= max(2, 7-1=6)? NO → skip STRONG
    # ratio(0.9) >= 0.5 → at least SOLID
    assert grade in {"SOLID", "STRONG", "EXCELLENT"}
    assert grade not in {"WEAK", "POOR", "MISMATCH"}


def test_mandatory_not_shown_lowers_grade():
    # 3 nice_to_have supported but 2 mandatory not_shown.
    # mandatory gaps should keep grade low despite nice_to_have coverage.
    coverage = [_cov_imp(f"n{i}", "supported", "nice_to_have", f"cap{i}") for i in range(3)] + [
        _cov_imp(f"m{i}", "not_shown", "mandatory") for i in range(2)
    ]
    # support_score = 3*0.25 = 0.75; max_score = 3*0.25 + 2*3 = 6.75; ratio = 0.11
    grade = llm_gate.derive_fit_review_grade(coverage)
    assert grade in {"WEAK", "POOR", "MISMATCH"}


def test_mandatory_mismatch_caps_at_weak():
    coverage = [
        _cov_imp("r1", "supported", "mandatory", "cap1"),
        _cov_imp("r2", "supported", "mandatory", "cap2"),
        _cov_imp("r3", "mismatch", "mandatory"),
    ]
    assert llm_gate.derive_fit_review_grade(coverage) == "WEAK"


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
        },
        {
            "requirement": "Nice portfolio",
            "importance": "nice_to_have",
            "status": "not_shown",
            "capability_name": "",
            "matched_job_text": "portfolio optional",
            "profile_support": [],
        },
    ]
    result = llm_gate.normalize_llm_requirement_coverage(
        items,
        valid_capability_names={"agile methodologies": "Agile Methodologies"},
    )
    assert result[0]["importance"] == "mandatory"
    assert result[1]["importance"] == "nice_to_have"


def test_normalize_coverage_defaults_invalid_importance_to_preferred():
    items = [
        {
            "requirement": "Python experience",
            "importance": "critical",  # not an allowed value
            "status": "supported",
            "capability_name": "python",
            "matched_job_text": "Python required",
            "profile_support": [],
        },
    ]
    result = llm_gate.normalize_llm_requirement_coverage(
        items,
        valid_capability_names={"python": "Python"},
    )
    assert result[0]["importance"] == "preferred"


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


def test_build_job_requirements_guidance_includes_work_types():
    guidance = llm_gate.build_job_requirements_guidance()
    assert "Permanent" in guidance
    assert "Full Time Contract / FTC" in guidance
    assert "Unknown when the work type is unclear" in guidance


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


# ── llm_judge_title ────────────────────────────────────────────────────────────


def _fake_title_judgment_client(output_text: str):
    class _FakeResponse:
        usage = None

    resp = _FakeResponse()
    resp.output_text = output_text

    class _FakeResponses:
        def create(self, **kwargs):
            return resp

    class _FakeClient:
        responses = _FakeResponses()

    return _FakeClient()


def test_llm_judge_title_returns_none_without_client():
    result = llm_gate.llm_judge_title("Business Analyst", ["business analyst"], [], llm_client=None)
    assert result is None


def test_llm_judge_title_returns_none_for_empty_title():
    client = _fake_title_judgment_client('{"verdict":"match","reason":"ok"}')
    result = llm_gate.llm_judge_title("", ["business analyst"], [], llm_client=client)
    assert result is None


def test_llm_judge_title_returns_none_when_no_target_roles_configured():
    client = _fake_title_judgment_client('{"verdict":"match","reason":"ok"}')
    result = llm_gate.llm_judge_title("Business Analyst", [], [], llm_client=client)
    assert result is None


def test_llm_judge_title_parses_no_match_verdict():
    client = _fake_title_judgment_client(
        '{"verdict":"no_match","reason":"Enablement/coordination role, not a target role."}'
    )
    result = llm_gate.llm_judge_title(
        "Business Enablement Coordinator", ["senior business analyst"], [], llm_client=client
    )
    assert result == {
        "verdict": "no_match",
        "reason": "Enablement/coordination role, not a target role.",
    }


def test_llm_judge_title_parses_match_verdict():
    client = _fake_title_judgment_client('{"verdict":"match","reason":"Direct match."}')
    result = llm_gate.llm_judge_title(
        "Senior Business Analyst", ["senior business analyst"], [], llm_client=client
    )
    assert result == {"verdict": "match", "reason": "Direct match."}


def test_llm_judge_title_returns_none_on_invalid_verdict():
    client = _fake_title_judgment_client('{"verdict":"maybe","reason":"unsure"}')
    result = llm_gate.llm_judge_title(
        "Business Analyst", ["senior business analyst"], [], llm_client=client
    )
    assert result is None


def test_llm_judge_title_returns_none_on_unparseable_output():
    client = _fake_title_judgment_client("not json")
    result = llm_gate.llm_judge_title(
        "Business Analyst", ["senior business analyst"], [], llm_client=client
    )
    assert result is None


def test_llm_judge_title_returns_none_on_client_exception():
    class _RaisingResponses:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class _RaisingClient:
        responses = _RaisingResponses()

    result = llm_gate.llm_judge_title(
        "Business Analyst", ["senior business analyst"], [], llm_client=_RaisingClient()
    )
    assert result is None
