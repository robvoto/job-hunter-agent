"""Tests for source-specific location scope handling."""

from __future__ import annotations

import pytest

from job_hunter_agent.scrapers.apsjobs import build_apsjobs_search_targets
from job_hunter_agent.scrapers.linkedin import LinkedInScraper
from job_hunter_agent.scrapers.seek import build_seek_search_targets


@pytest.mark.parametrize(
    ("locations", "expected_locations"),
    [
        (["Sydney"], ["Sydney"]),
        (["NSW"], ["NSW"]),
        (["Sydney", "NSW"], ["Sydney", "NSW"]),
        (["Sydney", "Melbourne"], ["Sydney", "Melbourne"]),
    ],
)
def test_seek_search_targets_keep_sydney_and_nsw_distinct(locations, expected_locations):
    targets = build_seek_search_targets(
        {"search_settings": {"keywords": "policy officer", "locations": locations}},
        configured_date_range=3,
        sort_newest_first=True,
    )

    assert [target["location"] for target in targets] == expected_locations


@pytest.mark.parametrize(
    ("locations", "expected_targets"),
    [
        (
            ["Sydney"],
            [("Sydney, Australia", 50, "city_radius")],
        ),
        (
            ["NSW"],
            [("New South Wales, Australia", None, "state")],
        ),
        (
            ["Sydney", "NSW"],
            [
                ("Sydney, Australia", 50, "city_radius"),
                ("New South Wales, Australia", None, "state"),
            ],
        ),
        (
            ["Sydney", "Melbourne"],
            [
                ("Sydney, Australia", 50, "city_radius"),
                ("Melbourne, Australia", 50, "city_radius"),
            ],
        ),
    ],
)
def test_linkedin_search_targets_keep_source_specific_scope(locations, expected_targets):
    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-01T09:00:00+10:00",
    )

    targets = scraper._build_search_targets({"keywords": "policy officer", "locations": locations})

    assert [
        (target["location"], target["distance"], target["scope"])
        for target in targets
    ] == expected_targets


@pytest.mark.parametrize(
    ("locations", "expected_locations"),
    [
        (["Sydney"], ["NSW"]),
        (["NSW"], ["NSW"]),
        (["Sydney", "NSW"], ["NSW"]),
        (["Sydney", "Melbourne"], ["NSW", "VIC"]),
    ],
)
def test_apsjobs_search_targets_map_sydney_to_nsw(locations, expected_locations):
    _, targets = build_apsjobs_search_targets(
        {"keywords": "policy officer", "locations": locations}
    )

    assert [target["location"] for target in targets] == expected_locations
