from job_hunter_agent import signal_detection
from job_hunter_agent.signal_schema import (
    CATEGORY_GOVERNMENT_CONTEXT,
    LEARNING_CATEGORY_KEY,
    LEARNING_SIGNAL_KEY,
)


def test_government_learning_signals_use_managed_parsing_config(monkeypatch):
    monkeypatch.setattr(signal_detection, "signal_in_approved_knowledge", lambda *args, **kwargs: (False, ""))

    record = {
        "company": "Federal Digital Service",
        "title": "Security Analyst",
        "full_description": "Government team requires negative vetting 1 or nv 2 clearance.",
    }

    signals = signal_detection._extract_government_context_learning_signals(record)
    values = [item[LEARNING_SIGNAL_KEY] for item in signals]

    assert values == ["government", "nv1", "nv2"]
    assert all(item[LEARNING_CATEGORY_KEY] == CATEGORY_GOVERNMENT_CONTEXT for item in signals)


def test_government_learning_signals_skip_missing_config(monkeypatch):
    monkeypatch.setattr(signal_detection, "load_parsing_rules", lambda: {})

    record = {
        "company": "Federal Digital Service",
        "title": "Security Analyst",
        "full_description": "Government team requires negative vetting 1 or nv 2 clearance.",
    }

    assert signal_detection._extract_government_context_learning_signals(record) == []
