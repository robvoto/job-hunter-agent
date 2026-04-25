from job_hunter_agent import llm_gate


class _FakeResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.usage = None


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


def test_normalize_rejection_blocker_suggestions_accepts_json_shape():
    suggestions = llm_gate.normalize_rejection_blocker_suggestions(
        '{"blockers":['
        '{"term":"restricted platform","kind":"platform"},'
        '{"term":"specialist certification","kind":"credential"},'
        '{"term":"restricted platform","kind":"platform"}'
        ']}'
    )

    assert suggestions == ["restricted platform", "specialist certification"]


def test_normalize_rejection_blocker_suggestions_rejects_soft_skill_kind():
    suggestions = llm_gate.normalize_rejection_blocker_suggestions(
        '{"blockers":['
        '{"term":"strong analytical and problem-solving skills","kind":"soft_skill"},'
        '{"term":"regulated sector experience","kind":"industry"}'
        ']}'
    )

    assert suggestions == ["regulated sector experience"]


def test_llm_suggest_rejection_blockers_uses_llm_response(monkeypatch):
    monkeypatch.setattr(llm_gate, "build_profile_prompt_context", lambda: "Candidate profile context")
    monkeypatch.setattr(llm_gate, "_log_llm_model_once", lambda: "test-model")
    monkeypatch.setattr(llm_gate, "_log_llm_call", lambda *args, **kwargs: None)
    fake_client = _FakeClient('{"blockers":[{"term":"specialist platform","kind":"platform"}]}')

    suggestions = llm_gate.llm_suggest_rejection_blockers(
        "This role requires a specialist platform.",
        llm_client=fake_client,
    )

    assert suggestions == ["specialist platform"]
    assert fake_client.responses.calls
