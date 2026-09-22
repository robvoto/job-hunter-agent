"""Tests for sector preference hard filtering."""

from job_hunter_agent.market_map_source import normalize_market_job
from job_hunter_agent.preferences import passes_preference_filters
from job_hunter_agent.sector_utils import (
    SECTOR_GOVERNMENT,
    SECTOR_PRIVATE,
    SECTOR_UNKNOWN,
    classify_market_sector,
)
from job_hunter_agent.workspace_renderer import humanize_reject_reason


def _profile(selected):
    return {"match_preferences": {"prefer_sector": selected}}


def test_public_only_accepts_public_and_rejects_private():
    assert passes_preference_filters(
        {"sector": SECTOR_GOVERNMENT}, _profile([SECTOR_GOVERNMENT])
    ) == (True, "OK")
    assert passes_preference_filters(
        {"sector": SECTOR_PRIVATE}, _profile([SECTOR_GOVERNMENT])
    ) == (False, "PREF_SECTOR_OUTSIDE_SELECTED")


def test_private_only_accepts_private_and_rejects_public():
    assert passes_preference_filters(
        {"sector": SECTOR_PRIVATE}, _profile([SECTOR_PRIVATE])
    ) == (True, "OK")
    assert passes_preference_filters(
        {"sector": SECTOR_GOVERNMENT}, _profile([SECTOR_PRIVATE])
    ) == (False, "PREF_SECTOR_OUTSIDE_SELECTED")


def test_both_selected_does_not_restrict_sector():
    assert passes_preference_filters(
        {"sector": "not supplied"}, _profile([SECTOR_GOVERNMENT, SECTOR_PRIVATE])
    ) == (True, "OK")


def test_unknown_sector_is_rejected_when_one_sector_is_selected():
    result = passes_preference_filters(
        {"sector": "not supplied"}, _profile([SECTOR_GOVERNMENT])
    )
    assert result == (False, "SECTOR_UNKNOWN_FOR_HARD_FILTER")
    assert humanize_reject_reason(result[1]) == (
        "Rejected because the job sector could not be confirmed."
    )


def test_market_sector_uses_explicit_value_before_source_classification():
    assert classify_market_sector(
        {"sector": "private", "classification_text": "Government & Defence"},
        ["government"],
    ) == SECTOR_PRIVATE


def test_market_sector_uses_government_evidence_and_private_classification():
    assert classify_market_sector(
        {"classification_text": "Government & Defence"},
        ["government"],
    ) == SECTOR_GOVERNMENT
    assert classify_market_sector(
        {"classification_text": "Information & Communication Technology"},
        ["government"],
    ) == SECTOR_PRIVATE
    assert classify_market_sector({}, ["government"]) == SECTOR_UNKNOWN


def test_market_adapter_preserves_source_backed_sector_classification():
    record = normalize_market_job(
        {
            "id": 12,
            "identity_key": "seek:id:12",
            "source": "seek",
            "source_job_id": "12",
            "canonical_url": "https://seek.example/jobs/12",
            "title": "Business Analyst",
            "employer": "Example Co",
            "location": "Sydney NSW",
            "classification_text": "Government & Defence",
        },
        run_iso="2026-09-21T00:00:00+00:00",
    )
    assert record["sector"] == SECTOR_GOVERNMENT
