"""Tests for llm gate."""

from job_hunter_agent import llm_gate


def test_build_capability_naming_guidance_uses_managed_defaults_only():
    prompt = llm_gate.build_capability_naming_guidance()

    assert "You are reviewing and labelling candidate professional capability clusters extracted from a CV." in prompt
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
    assert "requirement_coverage" in prompt
    assert "fit_review.grade" in prompt
    assert "decision_summary" in prompt
    assert "positive_reasons" in prompt
    assert "score_rationale" in prompt


def test_learning_only_prompt_retains_learning_guidance():
    prompt = llm_gate._build_learning_prompt("Job description", fit_review=False)

    assert "Learning categories available:" in prompt
    assert "capability_concept" in prompt
    assert "learning_candidates" in prompt


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
                    "status": "met",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "candidate_evidence": ["stakeholder management"],
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_met",
                    "capability_name": "process mapping",
                    "matched_job_text": "map the current process",
                    "candidate_evidence": ["process mapping"],
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
        "decision_summary": "",
        "positive_reasons": [],
        "concerns": [],
        "score_rationale": [],
        "learning_candidates": [],
        "contextual_capability_matches": [],
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "status": "met",
                "capability_name": "Stakeholder Engagement",
                "matched_job_text": "work with stakeholders",
                "candidate_evidence": ["stakeholder management"],
            },
            {
                "requirement": "Process mapping",
                "status": "partially_met",
                "capability_name": "Process Mapping",
                "matched_job_text": "map the current process",
                "candidate_evidence": ["process mapping"],
            },
        ],
        "job_requirements": ["Stakeholder engagement", "Process mapping"],
    }


def test_normalize_llm_review_payload_caps_rationale_fields():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "decision_summary": "  A" * 200,
            "positive_reasons": [
                "  Matches delivery leadership across the program  ",
                "AWS and REST API experience look relevant to the role",
                "No blocker found",
                "ignored extra item",
            ],
            "concerns": [
                "  Salary not found  ",
                "AWS evidence is possible but not strongly proven",
                "Concern about commute",
                "ignored extra concern",
            ],
            "score_rationale": [
                "LLM grade placed this job in the Strong band.",
                "Preferences and freshness moved the score within that band.",
                "ignored extra rationale",
            ],
            "job_requirements": ["Stakeholder engagement"],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "met",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "candidate_evidence": ["stakeholder management"],
                },
            ],
        },
        valid_capability_names={"stakeholder engagement": "Stakeholder Engagement"},
    )

    assert len(payload["decision_summary"]) <= 240
    assert payload["positive_reasons"] == [
        "Matches delivery leadership across the program",
        "AWS and REST API experience look relevant to the role",
        "No blocker found",
    ]
    assert payload["concerns"] == [
        "Salary not found",
        "AWS evidence is possible but not strongly proven",
        "Concern about commute",
    ]
    assert payload["score_rationale"] == [
        "LLM grade placed this job in the Strong band.",
        "Preferences and freshness moved the score within that band.",
    ]


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
                        "status": "met",
                        "capability_name": "Stakeholder Engagement",
                        "matched_job_text": "work with stakeholders",
                        "candidate_evidence": ["stakeholder management"],
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
    monkeypatch.setattr(llm_gate, "load_profile", lambda: {"candidate_capabilities": [{"name": "Stakeholder Engagement"}]})

    payload = llm_gate._request_learning_payload("Business analyst role supporting stakeholders.", fit_review=True)

    assert called["count"] == 1
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "STRONG"}


def test_strong_grade_requires_requirement_capability_evidence():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "job_requirements": ["Stakeholder engagement", "Process mapping"],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "status": "not_evidenced",
                    "capability_name": "",
                    "matched_job_text": "work with stakeholders",
                    "candidate_evidence": [],
                },
                {
                    "requirement": "Process mapping",
                    "status": "not_evidenced",
                    "capability_name": "",
                    "matched_job_text": "map the current process",
                    "candidate_evidence": [],
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
                    "status": "met",
                    "capability_name": "Stakeholder Engagement",
                    "matched_job_text": "stakeholder workshops",
                    "candidate_evidence": ["stakeholder engagement"],
                },
                {
                    "requirement": "Process mapping",
                    "status": "partially_met",
                    "capability_name": "Process Mapping",
                    "matched_job_text": "process mapping",
                    "candidate_evidence": ["process mapping"],
                },
                {
                    "requirement": "UAT support",
                    "status": "partially_met",
                    "capability_name": "Acceptance Testing",
                    "matched_job_text": "uat support",
                    "candidate_evidence": ["user acceptance testing"],
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
