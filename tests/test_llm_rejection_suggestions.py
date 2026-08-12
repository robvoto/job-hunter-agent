"""Tests for llm rejection suggestions."""

import json

import pytest

from job_hunter_agent import llm_gate


class _FakeResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.usage = None


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponses:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self.output_text)


class _FakeClient:
    def __init__(self, output_text: str):
        self.responses = _FakeResponses(output_text)


class _FakeParsedPayload:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class _FakeParseResponse:
    def __init__(self, payload):
        self.output_parsed = _FakeParsedPayload(payload)
        self.usage = None


class _FakeParsingResponses:
    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        text_format = kwargs["text_format"]
        if text_format.__name__ == "_LLMFitReviewPayload":
            return _FakeParseResponse(
                {
                    "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                    "job_requirements": ["Stakeholder engagement", "Process mapping"],
                    "requirement_coverage": [
                        {
                            "requirement": "Stakeholder engagement",
                            "status": "supported",
                            "capability_name": "stakeholder management",
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
                    "contextual_capability_matches": [],
                }
            )
        return _FakeParseResponse(
            {
                "fit_review": {"decision": "KEEP", "grade": "SOLID"},
                "learning_candidates": [],
            }
        )


class _FakeParsingClient:
    def __init__(self):
        self.responses = _FakeParsingResponses()


def test_llm_cost_logging_uses_managed_pricing(tmp_path, monkeypatch):
    costs_path = tmp_path / "llm_costs.jsonl"
    monkeypatch.setattr(llm_gate, "_LLM_COSTS_PATH", costs_path)
    monkeypatch.setattr(llm_gate, "_session_cost_usd", 0.0)
    monkeypatch.setattr(
        llm_gate,
        "load_global_settings",
        lambda: {
            "llm_settings": {
                "pricing_per_1m": {
                    "gpt-4o-mini": {"input": 1.0, "output": 2.0},
                },
                "pricing_metadata": {"unit": "per_1m_tokens"},
            },
        },
    )

    resp = _FakeResponse("ok")
    resp.usage = _FakeUsage(10, 20)

    llm_gate._log_llm_call(resp, "job_review", "gpt-4o-mini")

    payload = json.loads(costs_path.read_text(encoding="utf-8").strip())
    assert payload["cost_usd"] == 0.00005
    assert payload["session_usd"] == 0.00005


def test_normalize_rejection_blocker_suggestions_accepts_json_shape():
    suggestions = llm_gate.normalize_rejection_blocker_suggestions(
        '{"blockers":['
        '{"term":"restricted platform"},'
        '{"term":"specialist certification"},'
        '{"term":"restricted platform"}'
        "]}"
    )

    assert suggestions == ["restricted platform", "specialist certification"]


def test_normalize_rejection_blocker_suggestions_deduplicates_and_limits_words():
    suggestions = llm_gate.normalize_rejection_blocker_suggestions(
        '{"blockers":['
        '{"term":"regulated sector experience"},'
        '{"term":"regulated sector experience"},'
        '{"term":"ahpra registration"}'
        "]}",
        max_items=5,
    )

    assert suggestions == ["regulated sector experience", "ahpra registration"]


def test_managed_llm_prompt_knowledge_files_contain_lines():
    from job_hunter_agent.knowledge_store import get_knowledge

    fit_payload = get_knowledge("llm_fit_review_defaults")
    capability_payload = get_knowledge("llm_capability_naming_defaults")

    assert fit_payload["kind"] == "system_config"
    assert capability_payload["kind"] == "system_config"
    assert any(str(line).strip() for line in fit_payload["lines"])
    assert any(str(line).strip() for line in capability_payload["lines"])


def test_build_fit_review_guidance_uses_current_header():
    guidance = llm_gate.build_fit_review_guidance()

    assert guidance.startswith("Fit review guidance:")


def test_build_profile_prompt_context_uses_structured_profile_sources(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [
                {
                    "name": "Python",
                    "level": "strong",
                    "fit": "good",
                    "aliases": ["python"],
                }
            ],
            "salary_preferences": {
                "minimum_salary_yearly": 150000,
                "minimum_daily_rate": 900,
            },
            "match_preferences": {
                "home_location": "Sydney",
                "prefer_permanent": True,
            },
        },
    )
    monkeypatch.setattr(
        llm_gate,
        "get_candidate_profile_tiers",
        lambda profile: {
            "primary_candidate_profile_context": "Primary evidence",
            "secondary_candidate_profile_context": "Secondary evidence",
            "supplementary_candidate_profile_context": "Supplementary evidence",
        },
    )
    monkeypatch.setattr(
        llm_gate,
        "get_candidate_profile_tier_weights",
        lambda profile: {
            "primary_candidate_profile_context": 0.9,
            "secondary_candidate_profile_context": 0.5,
            "supplementary_candidate_profile_context": 0.2,
        },
    )
    monkeypatch.setattr(
        llm_gate,
        "load_global_settings",
        lambda: {
            "llm_settings": {
                "llm_prompt_settings": {
                    "match_preference_templates": {
                        "compensation_target_yearly": "Yearly target {value}.",
                        "compensation_target_daily": "Daily target {value}.",
                        "home_location": "Base {home_location}.",
                        "prefer_permanent": "Prefer permanent.",
                    },
                    "evidence_tiers": [
                        {
                            "profile_key": "primary_candidate_profile_context",
                            "label": "Primary context",
                            "weight_label": "strongest",
                            "default_weight": 1.0,
                            "limit": 50,
                        },
                        {
                            "profile_key": "secondary_candidate_profile_context",
                            "label": "Secondary context",
                            "weight_label": "lower",
                            "default_weight": 0.5,
                            "limit": 40,
                        },
                    ],
                    "learning_candidates_max_items": 6,
                    "rejection_blocker_suggestions_max_items": 6,
                    "rejection_blocker_suggestions_max_words": 6,
                },
            },
        },
    )

    context = llm_gate.build_profile_prompt_context()

    assert "Capability matrix:" in context
    assert "Python: strong, good (python)" in context
    assert "Yearly target 150000." in context
    assert "Daily target 900." in context
    assert "Base Sydney." in context
    assert "Prefer permanent." in context
    assert "Match preferences:" in context
    assert "Primary evidence" in context


def test_normalize_llm_learning_candidates_uses_managed_max_items(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.global_settings.load_global_settings",
        lambda: {
            "llm_settings": {
                "llm_prompt_settings": {
                    "match_preference_templates": {},
                    "evidence_tiers": [],
                    "learning_candidates_max_items": 1,
                    "rejection_blocker_suggestions_max_items": 6,
                    "rejection_blocker_suggestions_max_words": 6,
                },
            },
        },
    )

    candidates = llm_gate.normalize_llm_learning_candidates(
        [
            {"signal": "platform engineer", "suggested_category": "capability_concept"},
            {"signal": "delivery manager", "suggested_category": "capability_concept"},
        ]
    )

    assert len(candidates) == 1


def test_normalize_rejection_blocker_suggestions_uses_managed_max_items(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.global_settings.load_global_settings",
        lambda: {
            "llm_settings": {
                "llm_prompt_settings": {
                    "match_preference_templates": {},
                    "evidence_tiers": [],
                    "learning_candidates_max_items": 6,
                    "rejection_blocker_suggestions_max_items": 1,
                    "rejection_blocker_suggestions_max_words": 6,
                },
            },
        },
    )

    suggestions = llm_gate.normalize_rejection_blocker_suggestions(
        '{"blockers":[{"term":"specialist platform","kind":"platform"},{"term":"regulated sector","kind":"industry_platform"}]}'
    )

    assert suggestions == ["specialist platform"]


def test_llm_suggest_rejection_blockers_uses_llm_response(monkeypatch):
    monkeypatch.setattr(
        llm_gate, "build_profile_prompt_context", lambda: "Candidate profile context"
    )
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: "test-model")
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    fake_client = _FakeClient('{"blockers":[{"term":"specialist platform","kind":"platform"}]}')

    suggestions = llm_gate.llm_suggest_rejection_blockers(
        "This role requires a specialist platform.",
        llm_client=fake_client,
    )

    assert suggestions == ["specialist platform"]
    assert fake_client.responses.calls
    system_prompt = fake_client.responses.calls[0]["input"][0]["content"]
    assert "platform" in system_prompt
    assert "industry" in system_prompt


def test_normalize_llm_review_payload_fit_review_shape():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "SOLID",
            "job_requirements": [
                "Strong stakeholder engagement",
                "Strong stakeholder engagement",
            ],
            "requirement_coverage": [
                {
                    "requirement": "Strong stakeholder engagement",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "stakeholder engagement",
                    "profile_support": ["stakeholder management"],
                },
            ],
        },
        valid_capability_names={"stakeholder engagement": "Stakeholder engagement"},
    )

    assert payload == {
        "fit_review": {"decision": "KEEP", "grade": "STRONG"},
        "debug_reason": "",
        "occupation_alignment": llm_gate.LLM_INVALID_OCCUPATION_ALIGNMENT,
        "occupation_alignment_reason": "",
        "posting_channel": {"kind": llm_gate.LLM_INVALID_POSTING_CHANNEL_KIND, "confident": False, "evidence": ""},
        "requirement_coverage": [
            {
                "requirement": "Strong stakeholder engagement",
                "importance": "preferred",
                "requirement_type": "capability",
                "canonical_requirement": "",
                "profile_action_allowed": False,
                "status": "supported",
                "matched_candidate_fact": "Stakeholder engagement",
                "capability_name": "Stakeholder engagement",
                "eligibility_name": "",
                "matched_job_text": "stakeholder engagement",
                "profile_support": ["stakeholder management"],
            }
        ],
        "job_requirements": ["Strong stakeholder engagement"],
    }


def test_normalize_llm_review_payload_rejects_missing_grade():
    with pytest.raises(ValueError):
        llm_gate.normalize_llm_review_payload({"decision": "KEEP"}, valid_capability_names={})


def test_request_learning_payload_uses_fit_review_only_schema(monkeypatch):
    fake_client = _FakeParsingClient()
    monkeypatch.setattr(llm_gate, "client", fake_client)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: "test-model")
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        llm_gate, "build_profile_prompt_context", lambda: "Candidate profile context"
    )
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "candidate_capabilities": [
                {"name": "stakeholder management", "level": "strong"},
                {"name": "process mapping", "level": "working"},
            ]
        },
    )

    payload = llm_gate._request_learning_payload("Example role description", fit_review=True)

    assert payload == {
        "fit_review": {"decision": "KEEP", "grade": "SOLID"},
        "debug_reason": "",
        "occupation_alignment": llm_gate.LLM_INVALID_OCCUPATION_ALIGNMENT,
        "occupation_alignment_reason": "",
        "posting_channel": {"kind": llm_gate.LLM_INVALID_POSTING_CHANNEL_KIND, "confident": False, "evidence": ""},
        "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "preferred",
                    "requirement_type": "capability",
                    "canonical_requirement": "",
                    "profile_action_allowed": False,
                    "status": "supported",
                    "matched_candidate_fact": "stakeholder management",
                    "capability_name": "stakeholder management",
                    "eligibility_name": "",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["stakeholder management"],
                },
                {
                "requirement": "Process mapping",
                    "importance": "preferred",
                    "requirement_type": "capability",
                    "canonical_requirement": "",
                    "profile_action_allowed": False,
                    "status": "partially_supported",
                    "matched_candidate_fact": "process mapping",
                    "capability_name": "process mapping",
                    "eligibility_name": "",
                    "matched_job_text": "map the current process",
                    "profile_support": ["process mapping"],
                },
        ],
        "job_requirements": ["Stakeholder engagement", "Process mapping"],
    }
    assert fake_client.responses.calls[0]["text_format"].__name__ == "_LLMFitReviewPayload"
