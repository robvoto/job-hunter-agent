"""Tests for the capability evidence scoring layer.

Covers:
- LLM high-confidence confirmed matches get credited using profile level weights
- LLM medium/low-confidence matches are logged and skipped — no credit
- Unknown capability name from LLM is logged as a gate breach error and skipped
- Stop-at-cap: accumulation stops once max_score is reached
- Per-capability breakdown entries show llm_confirmed match type tag
- normalize_llm_contextual_capability_matches filters by valid_capability_names
"""

import logging

import pytest

from job_hunter_agent import fit_scoring
from job_hunter_agent.fit_scoring import (
    capability_evidence_score,
    fit_score_breakdown,
)
from job_hunter_agent.llm_gate import normalize_llm_contextual_capability_matches


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _profile(rules):
    return {
        "candidate_capabilities": rules,
        "dominant_signal_clusters": [],
        "match_preferences": {"home_location": "Sydney NSW"},
        "preference_weights": {},
        "salary_preferences": {},
    }


def _rule(name, level="strong", aliases=None):
    return {"name": name, "level": level, "fit": "core", "aliases": aliases or []}


def _base_record(**kwargs):
    return {
        "title": "Business Analyst",
        "title_reason": "OK",
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "llm_decision": "KEEP",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "competitive_signals": [],
        **kwargs,
    }


def _contextual_match(name, confidence="high", matched_text="", reason=""):
    return {
        "capability_name": name,
        "confidence": confidence,
        "matched_text": matched_text,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# capability_evidence_score — LLM-confirmed matches
# ---------------------------------------------------------------------------

def test_high_confidence_match_is_credited():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match("requirements elicitation", "high", "run discovery workshops", "Workshops are elicitation.")
        ],
    )
    score, matches = capability_evidence_score(record, profile)
    assert score > 0
    assert len(matches) == 1
    assert matches[0]["match_type"] == "llm_confirmed"
    assert matches[0]["matched_text"] == "run discovery workshops"


def test_medium_confidence_match_gets_zero_credit(caplog):
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match("requirements elicitation", "medium", "run discovery workshops", "Possibly related.")
        ],
    )
    with caplog.at_level(logging.INFO, logger="job_hunter_agent.fit_scoring"):
        score, matches = capability_evidence_score(record, profile)

    assert score == 0
    assert matches == []
    assert "BELOW_THRESHOLD" in caplog.text
    assert "requirements elicitation" in caplog.text


def test_low_confidence_match_gets_zero_credit(caplog):
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match("requirements elicitation", "low", "support the team", "Very loose.")
        ],
    )
    with caplog.at_level(logging.INFO, logger="job_hunter_agent.fit_scoring"):
        score, matches = capability_evidence_score(record, profile)

    assert score == 0
    assert matches == []


def test_unknown_capability_name_from_llm_is_logged_as_gate_breach(caplog):
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match("magic capability that does not exist", "high", "support the team", "Invented.")
        ],
    )
    with caplog.at_level(logging.ERROR, logger="job_hunter_agent.fit_scoring"):
        score, matches = capability_evidence_score(record, profile)

    assert score == 0
    assert matches == []
    assert "GATE_BREACH" in caplog.text


def test_same_capability_not_credited_twice():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match("requirements elicitation", "high", "text one", "First."),
            _contextual_match("requirements elicitation", "high", "text two", "Second."),
        ],
    )
    score, matches = capability_evidence_score(record, profile)
    assert len(matches) == 1


def test_no_contextual_matches_returns_zero():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(contextual_capability_matches=[])
    score, matches = capability_evidence_score(record, profile)
    assert score == 0
    assert matches == []


# ---------------------------------------------------------------------------
# Stop-at-cap
# ---------------------------------------------------------------------------

def test_evidence_score_stops_at_cap():
    rules = [_rule(f"capability {i}", level="strong") for i in range(6)]
    profile = _profile(rules)
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match(f"capability {i}", "high", f"evidence {i}", "Clear.") for i in range(6)
        ],
    )
    score, matches = capability_evidence_score(record, profile)
    assert score == 20  # capped at max_score
    total_points = sum(m["points"] for m in matches)
    assert total_points == 20


# ---------------------------------------------------------------------------
# fit_score_breakdown — requires LLM review
# ---------------------------------------------------------------------------

def test_fit_score_breakdown_raises_without_llm_review():
    profile = _profile([_rule("stakeholder management", level="strong")])
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "content_reason": "OK",
        # no llm_fit_grade
    }
    with pytest.raises(RuntimeError, match="Cannot score job without LLM review"):
        fit_score_breakdown(record, profile)


def test_breakdown_shows_llm_confirmed_tag():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        contextual_capability_matches=[
            _contextual_match("requirements elicitation", "high", "run discovery workshops", "Workshops are elicitation.")
        ],
    )
    breakdown = fit_score_breakdown(record, profile)
    labels = [item["label"] for item in breakdown]
    assert any("[llm_confirmed]" in label and "requirements elicitation" in label.lower() for label in labels)


# ---------------------------------------------------------------------------
# normalize_llm_contextual_capability_matches
# ---------------------------------------------------------------------------

def test_normalizer_accepts_valid_entries():
    raw = [
        {"capability_name": "stakeholder management", "confidence": "high", "matched_text": "stakeholder workshops", "reason": "Workshops."},
        {"capability_name": "agile methodologies", "confidence": "medium", "matched_text": "scrum", "reason": "Scrum is agile."},
    ]
    result = normalize_llm_contextual_capability_matches(raw)
    assert len(result) == 2
    assert result[0]["capability_name"] == "stakeholder management"
    assert result[1]["confidence"] == "medium"


def test_normalizer_rejects_invalid_confidence():
    raw = [{"capability_name": "stakeholder management", "confidence": "very high", "matched_text": "x", "reason": "y"}]
    result = normalize_llm_contextual_capability_matches(raw)
    assert result == []


def test_normalizer_rejects_entries_not_in_valid_set():
    raw = [{"capability_name": "unknown capability xyz", "confidence": "high", "matched_text": "x", "reason": "y"}]
    valid = frozenset({"stakeholder management"})
    result = normalize_llm_contextual_capability_matches(raw, valid_capability_names=valid)
    assert result == []


def test_normalizer_skips_non_dict_items():
    raw = ["not a dict", None, {"capability_name": "stakeholder management", "confidence": "high", "matched_text": "x", "reason": "y"}]
    result = normalize_llm_contextual_capability_matches(raw)
    assert len(result) == 1


def test_normalizer_normalizes_capability_name_to_lowercase():
    raw = [{"capability_name": "Stakeholder Management", "confidence": "high", "matched_text": "x", "reason": "y"}]
    result = normalize_llm_contextual_capability_matches(raw)
    assert result[0]["capability_name"] == "stakeholder management"
