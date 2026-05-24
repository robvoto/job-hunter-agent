"""Tests for the capability evidence scoring layer.

Covers:
- Canonical name matches get full deterministic credit
- Alias matches get the same credit as canonical
- LLM high-confidence contextual matches get credited using existing level weights
- LLM medium-confidence contextual matches get zero credit
- LLM low-confidence contextual matches get zero credit
- Stop-at-cap: accumulation stops once max_score is reached
- Per-capability breakdown entries show match type tags
- normalize_llm_contextual_capability_matches filters invalid entries
"""

import logging

import pytest

from job_hunter_agent import fit_scoring
from job_hunter_agent.fit_scoring import (
    capability_evidence_score,
    capability_scored_matches,
    fit_score_breakdown,
)
from job_hunter_agent.llm_gate import normalize_llm_contextual_capability_matches


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _profile(rules):
    return {
        "capability_profile_rules": rules,
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
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "competitive_signals": [],
        **kwargs,
    }


# ---------------------------------------------------------------------------
# capability_scored_matches — deterministic path
# ---------------------------------------------------------------------------

def test_canonical_name_match_is_credited():
    profile = _profile([_rule("stakeholder management", level="strong")])
    matches = capability_scored_matches(
        "You will lead stakeholder management across delivery teams.", profile
    )
    assert len(matches) == 1
    assert matches[0]["match_type"] == "canonical"
    assert matches[0]["matched_text"] == "stakeholder management"
    assert matches[0]["level"] == "strong"


def test_alias_match_is_credited_same_as_canonical():
    profile = _profile([_rule("stakeholder management", level="strong", aliases=["stakeholder engagement"])])
    canonical_matches = capability_scored_matches(
        "Lead stakeholder management activities.", profile
    )
    alias_matches = capability_scored_matches(
        "Lead stakeholder engagement activities.", profile
    )
    assert len(canonical_matches) == 1
    assert len(alias_matches) == 1
    assert canonical_matches[0]["match_type"] == "canonical"
    assert alias_matches[0]["match_type"] == "alias"
    assert alias_matches[0]["matched_text"] == "stakeholder engagement"
    # Both should have the same combined_strength (same rule, same profile evidence)
    assert canonical_matches[0]["combined_strength"] == alias_matches[0]["combined_strength"]


def test_no_match_when_neither_canonical_nor_alias_present():
    profile = _profile([_rule("stakeholder management", level="strong", aliases=["stakeholder engagement"])])
    matches = capability_scored_matches("Lead workshops across delivery teams.", profile)
    assert matches == []


def test_canonical_takes_priority_over_alias_when_both_present():
    profile = _profile([_rule("agile methodologies", level="strong", aliases=["agile"])])
    matches = capability_scored_matches(
        "You will apply agile methodologies including agile delivery.", profile
    )
    assert len(matches) == 1
    assert matches[0]["match_type"] == "canonical"


# ---------------------------------------------------------------------------
# capability_evidence_score — LLM contextual matches
# ---------------------------------------------------------------------------

def test_high_confidence_contextual_match_adds_credit():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        full_description="Run discovery workshops to understand the problem space.",
        contextual_capability_matches=[
            {
                "capability_name": "requirements elicitation",
                "confidence": "high",
                "matched_text": "run discovery workshops",
                "reason": "Discovery workshops are a requirements elicitation technique.",
            }
        ],
    )
    score, matches = capability_evidence_score(record, profile)
    assert score > 0
    contextual = [m for m in matches if m["match_type"] == "contextual_llm"]
    assert len(contextual) == 1
    assert contextual[0]["matched_text"] == "run discovery workshops"


def test_high_confidence_contextual_match_not_added_if_already_credited_deterministically():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        full_description="Requirements elicitation and discovery workshops are key.",
        contextual_capability_matches=[
            {
                "capability_name": "requirements elicitation",
                "confidence": "high",
                "matched_text": "discovery workshops",
                "reason": "Workshops are an elicitation technique.",
            }
        ],
    )
    score, matches = capability_evidence_score(record, profile)
    # Only one entry — deterministic wins, contextual not duplicated
    assert len(matches) == 1
    assert matches[0]["match_type"] == "canonical"


def test_medium_confidence_contextual_match_gets_zero_credit(caplog):
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        full_description="Run discovery workshops.",
        contextual_capability_matches=[
            {
                "capability_name": "requirements elicitation",
                "confidence": "medium",
                "matched_text": "run discovery workshops",
                "reason": "Possibly related.",
            }
        ],
    )
    with caplog.at_level(logging.INFO, logger="job_hunter_agent.fit_scoring"):
        score, matches = capability_evidence_score(record, profile)

    assert score == 0
    assert not any(m["match_type"] == "contextual_llm" for m in matches)
    assert "MEDIUM" in caplog.text
    assert "requirements elicitation" in caplog.text


def test_low_confidence_contextual_match_gets_zero_credit(caplog):
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        full_description="Support the delivery team.",
        contextual_capability_matches=[
            {
                "capability_name": "requirements elicitation",
                "confidence": "low",
                "matched_text": "support the delivery team",
                "reason": "Very loose connection.",
            }
        ],
    )
    with caplog.at_level(logging.DEBUG, logger="job_hunter_agent.fit_scoring"):
        score, matches = capability_evidence_score(record, profile)

    assert score == 0
    assert not any(m["match_type"] == "contextual_llm" for m in matches)


def test_unknown_capability_name_from_llm_is_ignored(caplog):
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        full_description="Support the delivery team.",
        contextual_capability_matches=[
            {
                "capability_name": "magic capability that does not exist",
                "confidence": "high",
                "matched_text": "support the delivery team",
                "reason": "Invented.",
            }
        ],
    )
    with caplog.at_level(logging.WARNING, logger="job_hunter_agent.fit_scoring"):
        score, matches = capability_evidence_score(record, profile)

    assert score == 0
    assert "capability name not in profile rules" in caplog.text


# ---------------------------------------------------------------------------
# Stop-at-cap: accumulation stops once max_score is reached
# ---------------------------------------------------------------------------

def test_evidence_score_stops_at_cap():
    # Six STRONG capabilities — well over the max_score of 20
    rules = [_rule(f"capability {i}", level="strong") for i in range(6)]
    profile = _profile(rules)
    text = " ".join(f"capability {i}" for i in range(6))
    record = _base_record(full_description=text)
    score, matches = capability_evidence_score(record, profile)
    assert score == 20  # capped at max_score
    # Not all 6 necessarily credited — some may be cut off
    total_points = sum(m["points"] for m in matches)
    assert total_points == 20


# ---------------------------------------------------------------------------
# Per-capability breakdown labels show match type tags
# ---------------------------------------------------------------------------

def test_breakdown_shows_canonical_tag():
    profile = _profile([_rule("stakeholder management", level="strong")])
    record = _base_record(
        full_description="Lead stakeholder management across the programme."
    )
    breakdown = fit_score_breakdown(record, profile)
    labels = [item["label"] for item in breakdown]
    assert any("[canonical]" in label and "stakeholder management" in label.lower() for label in labels)


def test_breakdown_shows_alias_tag():
    profile = _profile([_rule("stakeholder management", level="strong", aliases=["stakeholder engagement"])])
    record = _base_record(
        full_description="Lead stakeholder engagement across the programme."
    )
    breakdown = fit_score_breakdown(record, profile)
    labels = [item["label"] for item in breakdown]
    assert any("[alias:" in label and "stakeholder management" in label.lower() for label in labels)


def test_breakdown_shows_contextual_llm_tag():
    profile = _profile([_rule("requirements elicitation", level="strong")])
    record = _base_record(
        full_description="Run discovery workshops.",
        contextual_capability_matches=[
            {
                "capability_name": "requirements elicitation",
                "confidence": "high",
                "matched_text": "run discovery workshops",
                "reason": "Discovery workshops are a requirements elicitation technique.",
            }
        ],
    )
    breakdown = fit_score_breakdown(record, profile)
    labels = [item["label"] for item in breakdown]
    assert any("[contextual_llm]" in label and "requirements elicitation" in label.lower() for label in labels)


def test_breakdown_has_no_fit_evidence_bullets_label():
    profile = _profile([_rule("stakeholder management", level="strong")])
    record = _base_record(
        full_description="Lead stakeholder management across the programme."
    )
    breakdown = fit_score_breakdown(record, profile)
    labels = [item["label"] for item in breakdown]
    assert "Fit evidence bullets" not in labels


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
