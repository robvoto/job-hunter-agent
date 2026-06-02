"""Tests for llm gate."""

from types import SimpleNamespace

import pytest

from job_hunter_agent import llm_gate


class _FakeResponses:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed, usage=None)


class _FakeClient:
    def __init__(self, parsed):
        self.responses = _FakeResponses(parsed)


@pytest.mark.parametrize("fit_review", [True, False])
def test_request_learning_payload_uses_parsed_output(monkeypatch, fit_review):
    if fit_review:
        parsed = llm_gate._LLMFitReviewPayload(
            fit_review=llm_gate._LLMReviewDecision(decision="KEEP", grade="SOLID"),
            contextual_capability_matches=[],
            job_requirements=["Strong stakeholder engagement"],
        )
    else:
        parsed = llm_gate._LLMReviewPayload(
            fit_review=None,
            learning_candidates=[
                llm_gate._LLMLearningCandidate(
                    signal="python",
                    suggested_category="capability_concept",
                    original_texts=["python"],
                )
            ],
        )
    fake_client = _FakeClient(parsed)

    monkeypatch.setattr(llm_gate, "client", fake_client)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: "gpt-test")
    monkeypatch.setattr(llm_gate, "build_profile_prompt_context", lambda: "Candidate profile context")
    if fit_review:
        monkeypatch.setattr(llm_gate, "load_profile", lambda: {"candidate_capabilities": [{"name": "python"}]})

    payload = llm_gate._request_learning_payload("job description", fit_review=fit_review)

    assert fake_client.responses.calls
    assert fake_client.responses.calls[0]["text_format"] is (llm_gate._LLMFitReviewPayload if fit_review else llm_gate._LLMReviewPayload)
    if fit_review:
        assert payload["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}
        assert payload["learning_candidates"] == []
        assert payload["job_requirements"] == ["Strong stakeholder engagement"]
    else:
        assert payload["learning_candidates"][0]["signal"] == "python"
        assert payload["fit_review"] is None
        assert payload["job_requirements"] == []


def test_llm_extract_job_requirements_uses_parsed_output(monkeypatch):
    parsed = llm_gate._LLMJobRequirementsPayload(job_requirements=["Strong stakeholder engagement", "Experience across BA activities"])
    fake_client = _FakeClient(parsed)

    monkeypatch.setattr(llm_gate, "client", fake_client)
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: "gpt-test")
    monkeypatch.setattr(llm_gate, "get_llm_job_requirements_max_output_tokens", lambda: 321)

    payload = llm_gate.llm_extract_job_requirements("job description")

    assert fake_client.responses.calls
    assert fake_client.responses.calls[0]["text_format"] is llm_gate._LLMJobRequirementsPayload
    assert fake_client.responses.calls[0]["max_output_tokens"] == 321
    assert payload == ["Strong stakeholder engagement", "Experience across BA activities"]


def test_request_learning_payload_requires_candidate_capabilities_for_fit_review(monkeypatch):
    monkeypatch.setattr(llm_gate, "client", SimpleNamespace())
    monkeypatch.setattr(llm_gate, "load_profile", lambda: {"candidate_capabilities": []})

    with pytest.raises(ValueError, match="Fit review cannot run because the candidate profile has no capability rules"):
        llm_gate._request_learning_payload("job description", fit_review=True)
