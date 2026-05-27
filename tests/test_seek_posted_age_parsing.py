"""Tests for seek posted age parsing."""

import pytest

from job_hunter_agent.scrapers.seek import extract_posted_text_from_card
from job_hunter_agent.utils import parse_seek_posted_age_days


def test_seek_posted_age_parser_uses_managed_rules():
    assert parse_seek_posted_age_days("today") == 0.0
    assert parse_seek_posted_age_days("yesterday") == 1.0
    assert parse_seek_posted_age_days("2h ago") == pytest.approx(2 / 24)
    assert parse_seek_posted_age_days("15m") == pytest.approx(15 / (24 * 60))


def test_seek_posted_text_extraction_matches_managed_pattern():
    assert extract_posted_text_from_card("Posted 2h ago | Some role") == "2h ago"
    assert extract_posted_text_from_card("Posted yesterday | Some role") == "yesterday"
