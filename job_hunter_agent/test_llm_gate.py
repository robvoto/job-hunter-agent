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
    parsed = llm_gate._LLMReviewPayload(
        fit_review=llm_gate._LLMReviewDecision(decision="KEEP", grade="SOLID") if fit_review else None,
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

    payload = llm_gate._request_learning_payload("job description", fit_review=fit_review)

    assert fake_client.responses.calls
    assert fake_client.responses.calls[0]["text_format"] is llm_gate._LLMReviewPayload
    assert payload["learning_candidates"][0]["signal"] == "python"
    if fit_review:
        assert payload["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}
    else:
        assert payload["fit_review"] is None
