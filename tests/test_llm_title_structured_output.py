"""Regression coverage for the pre-detail LLM title structured-output boundary."""

import job_hunter_agent.llm_gate as llm_gate


class _FakeParsed:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self):
        return dict(self._payload)


class _FakeResponse:
    usage = None

    def __init__(self, payload: dict | None, output_text: str = ""):
        self.output_parsed = _FakeParsed(payload) if payload is not None else None
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self.responses = _FakeResponses(response)


def test_title_judgment_uses_structured_output_even_when_raw_text_is_fenced_json():
    client = _FakeClient(
        _FakeResponse(
            {"verdict": "no_match", "reason": "Cloud engineering is outside the target roles."},
            output_text='```json\n{"verdict":"no_match","reason":"ignored raw text"}\n```',
        )
    )

    result = llm_gate.llm_judge_title(
        "Senior Cloud Engineer",
        ["business analyst"],
        ["technical business analyst"],
        llm_client=client,
    )

    assert result == {
        "verdict": "no_match",
        "reason": "Cloud engineering is outside the target roles.",
    }
    assert client.responses.calls[0]["text_format"] is llm_gate._LLMTitleJudgment


def test_title_judgment_missing_structured_output_fails_open():
    client = _FakeClient(_FakeResponse(None, output_text="not structured"))

    result = llm_gate.llm_judge_title(
        "Ambiguous Technology Role",
        ["business analyst"],
        [],
        llm_client=client,
    )

    assert result is None
