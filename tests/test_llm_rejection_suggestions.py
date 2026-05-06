from job_hunter_agent import llm_gate
import json
import pytest


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
        '{"term":"regulated sector experience","kind":"industry_platform"}'
        ']}'
    )

    assert suggestions == ["regulated sector experience"]


def test_rejection_rule_categories_file_contains_enabled_entries():
    payload = json.loads(llm_gate._REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert any(entry.get("enabled") for entry in payload["entries"])
    assert "platform" in llm_gate._hard_blocker_rules()
    assert "industry_platform" in llm_gate._hard_blocker_rules()


def test_managed_llm_prompt_knowledge_files_contain_lines():
    fit_payload = json.loads(llm_gate._FIT_REVIEW_DEFAULTS_PATH.read_text(encoding="utf-8"))
    capability_payload = json.loads(llm_gate._CAPABILITY_NAMING_DEFAULTS_PATH.read_text(encoding="utf-8"))

    assert fit_payload["kind"] == "managed_knowledge"
    assert capability_payload["kind"] == "managed_knowledge"
    assert any(str(line).strip() for line in fit_payload["lines"])
    assert any(str(line).strip() for line in capability_payload["lines"])


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
    system_prompt = fake_client.responses.calls[0]["input"][0]["content"]
    assert "platform" in system_prompt
    assert "industry" in system_prompt


def test_normalize_llm_review_payload_keeps_learning_candidates():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "SOLID",
            "learning_candidates": [
                {"signal": "platform engineer", "suggested_category": "role_title_token", "original_texts": ["Platform Engineer"]},
                {"signal": "platform engineer", "suggested_category": "role_title_token", "original_texts": ["Platform Engineer"]},
            ],
        }
    )

    assert payload == {
        "fit_review": {"decision": "KEEP", "grade": "SOLID"},
        "learning_candidates": [
            {
                "signal": "platform engineer",
                "suggested_category": "role_title_token",
                "original_texts": ["platform engineer"],
            }
        ],
    }


def test_normalize_llm_review_payload_rejects_missing_grade():
    with pytest.raises(ValueError, match="missing grade"):
        llm_gate.normalize_llm_review_payload({"decision": "KEEP"})
