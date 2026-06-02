"""Tests for source learning payload resolution."""

from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_JOB_KEY,
    RECORD_TITLE_KEY,
)
from job_hunter_agent import source_learning


def _build_record(title: str = "Title", company: str = "Company", description: str = "Description") -> dict:
    return {
        RECORD_JOB_KEY: "job-1",
        RECORD_TITLE_KEY: title,
        RECORD_COMPANY_KEY: company,
        RECORD_FULL_DESCRIPTION_KEY: description,
        "source": "seek",
    }


def test_resolve_llm_review_payload_fit_review_cache_hit_skips_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nDescription")
    llm_cache = {
        llm_fp: {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "job_requirements": [],
        }
    }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))
    monkeypatch.setattr(source_learning, "llm_should_consider_learning_candidates", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert payload["payload_source"] == "cache"
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}


def test_resolve_llm_review_payload_learning_only_cache_hit_skips_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nDescription")
    llm_cache = {
        llm_fp: {
            "learning_candidates": [
                {
                    "signal": "python",
                    "suggested_category": "capability_concept",
                    "suggested_values": [],
                    "context_terms": [],
                    "confidence": "low",
                    "needs_review": True,
                    "original_texts": ["python"],
                }
            ],
        }
    }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))
    monkeypatch.setattr(source_learning, "llm_should_consider_learning_candidates", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    payload = source_learning.resolve_llm_review_payload(record, llm_cache, learning_only=True)

    assert payload["payload_source"] == "cache"
    assert payload["learning_candidates"][0]["signal"] == "python"


def test_resolve_llm_review_payload_cache_miss_calls_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nDescription")
    llm_cache = {}
    called = {"count": 0}

    def fake_llm(*_args, **_kwargs):
        called["count"] += 1
        return {
            "fit_review": {"decision": "KEEP", "grade": "SOLID"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "job_requirements": [],
        }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", fake_llm)

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert called["count"] == 1
    assert payload["payload_source"] == "llm"
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "SOLID"}
    assert llm_fp not in llm_cache


def test_resolve_llm_review_payload_partial_cache_calls_llm(monkeypatch):
    record = _build_record()
    llm_fp = source_learning.build_llm_cache_key("Title\nDescription")
    llm_cache = {
        llm_fp: {
            "learning_candidates": [
                {
                    "signal": "python",
                    "suggested_category": "capability_concept",
                    "suggested_values": [],
                    "context_terms": [],
                    "confidence": "low",
                    "needs_review": True,
                    "original_texts": ["python"],
                }
            ],
        }
    }
    called = {"count": 0}

    def fake_llm(*_args, **_kwargs):
        called["count"] += 1
        return {
            "fit_review": {"decision": "KEEP", "grade": "STRONG"},
            "learning_candidates": [],
            "contextual_capability_matches": [],
            "job_requirements": [],
        }

    monkeypatch.setattr(source_learning, "llm_is_enabled", lambda: True)
    monkeypatch.setattr(source_learning, "llm_should_consider_with_learning", fake_llm)

    payload = source_learning.resolve_llm_review_payload(record, llm_cache)

    assert called["count"] == 1
    assert payload["payload_source"] == "llm"
    assert payload["fit_review"] == {"decision": "KEEP", "grade": "STRONG"}
