"""Tests for title_normalization_rules.

normalize_title_text only performs mechanical cleanup:
trim, lowercase, collapse whitespace.
It does not expand abbreviations or read from managed knowledge.
"""

from job_hunter_agent import title_normalization_rules


def test_normalize_title_text_trims_and_lowercases():
    assert (
        title_normalization_rules.normalize_title_text("  Senior Business Analyst  ")
        == "senior business analyst"
    )


def test_normalize_title_text_collapses_whitespace():
    assert (
        title_normalization_rules.normalize_title_text("Senior  Business   Analyst")
        == "senior business analyst"
    )


def test_normalize_title_text_does_not_expand_abbreviations():
    assert title_normalization_rules.normalize_title_text("Sr BA") == "sr ba"
    assert title_normalization_rules.normalize_title_text("PM") == "pm"
    assert title_normalization_rules.normalize_title_text("PO") == "po"
    assert title_normalization_rules.normalize_title_text("SRVA") == "srva"


def test_normalize_title_text_handles_empty():
    assert title_normalization_rules.normalize_title_text("") == ""
    assert title_normalization_rules.normalize_title_text(None) == ""


def test_normalize_title_text_ignores_source_text_param():
    # source_text param is accepted for call-site compatibility but has no effect
    assert title_normalization_rules.normalize_title_text("Sr BA", "delivery project") == "sr ba"
