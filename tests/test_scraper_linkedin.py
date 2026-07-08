"""Tests for scraper linkedin."""

from datetime import date

import pytest

from job_hunter_agent import job_quality
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.posting_utils import posted_display_label
from job_hunter_agent.salary import load_salary
from job_hunter_agent.scrapers.base import _build_salary_string
from job_hunter_agent.scrapers.linkedin import LinkedInScraper, classify_linkedin_apply_method
from job_hunter_agent.scrapers.location_adapters import (
    LINKEDIN_CITY_RADIUS_MILES,
    to_linkedin_search_scope,
)
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_UNKNOWN,
    RECORD_URL_KEY,
)


def test_to_linkedin_search_scope_handles_city_inputs():
    assert to_linkedin_search_scope(resolve_location("Sydney")) == {
        "location": "Sydney, Australia",
        "distance": LINKEDIN_CITY_RADIUS_MILES,
        "scope": "city_radius",
    }
    assert to_linkedin_search_scope(resolve_location("Melbourne")) == {
        "location": "Melbourne, Australia",
        "distance": LINKEDIN_CITY_RADIUS_MILES,
        "scope": "city_radius",
    }


def test_to_linkedin_search_scope_handles_state_inputs():
    assert to_linkedin_search_scope(resolve_location("NSW")) == {
        "location": "New South Wales, Australia",
        "distance": None,
        "scope": "state",
    }
    assert to_linkedin_search_scope(resolve_location("Queensland")) == {
        "location": "Queensland, Australia",
        "distance": None,
        "scope": "state",
    }


def test_jobspy_salary_string_keeps_non_yearly_amounts():
    rules = load_salary()
    assert _build_salary_string(70, 90, "hourly", "AUD", rules) == "$70\u201390 /hr"
    assert _build_salary_string(130000, 150000, "yearly", "AUD", rules) == "$130k\u2013150k p.a."


def test_classify_linkedin_apply_method_detects_external_apply():
    assert (
        classify_linkedin_apply_method(
            "https://employer.example.com/careers/123", "https://linkedin.com/jobs/view/1"
        )
        == APPLY_METHOD_EXTERNAL_APPLY
    )


def test_classify_linkedin_apply_method_detects_easy_apply_when_no_apply_url():
    assert classify_linkedin_apply_method("", "https://linkedin.com/jobs/view/1") == (
        APPLY_METHOD_EASY_APPLY
    )


def test_classify_linkedin_apply_method_unknown_when_apply_url_matches_canonical():
    url = "https://linkedin.com/jobs/view/1"
    assert classify_linkedin_apply_method(url, url) == APPLY_METHOD_UNKNOWN


def test_linkedin_closed_listing_signal_detects_no_longer_accepting_applications(monkeypatch):
    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-20T00:00:00+10:00",
    )

    monkeypatch.setattr(
        job_quality,
        "fetch_external_html",
        lambda url: "<html><body>No longer accepting applications</body></html>",
    )

    signals = scraper._detect_closed_job_signals({RECORD_URL_KEY: "https://example.com/job/1"})

    assert any(signal.get("kind") == job_quality.SIGNAL_KIND_JOB_CLOSED for signal in signals)


def test_linkedin_posted_age_parses_visible_relative_text_only():
    from job_hunter_agent.scrapers.linkedin import _extract_linkedin_posted_age_days

    assert (
        _extract_linkedin_posted_age_days(
            "<html><body><span>3 days ago</span></body></html>",
            date(2026, 6, 22),
        )
        == 3.0
    )
    assert (
        _extract_linkedin_posted_age_days(
            "<html><body><span>Posted 3 hours ago</span></body></html>",
            date(2026, 6, 22),
        )
        == pytest.approx(3 / 24)
    )


def test_linkedin_backfills_missing_posted_age_from_visible_listing_text(monkeypatch, caplog):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def sort_values(self, **_kwargs):
            return self

        def iterrows(self):
            return enumerate(self._rows)

        def __len__(self):
            return len(self._rows)

    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    monkeypatch.setattr(
        scraper,
        "_build_search_targets",
        lambda _settings: [
            {
                "search_term": "analyst",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 168,
                "sort_newest_first": False,
                "easy_apply": None,
            }
        ],
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_jobspy",
        lambda _target: _Rows(
            [
                {
                    "id": "li-1",
                    "title": "Senior Technical Business Analyst",
                    "company": "Woolworths Group",
                    "location": "Sydney",
                    "job_url": "https://www.linkedin.com/jobs/view/4431678147",
                    "description": "Example description",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        linkedin_module,
        "_fetch_job_html",
        lambda _record: "<html><body><span>Posted 3 hours ago</span></body></html>",
    )
    monkeypatch.setattr(
        linkedin_module,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )
    monkeypatch.setattr(
        linkedin_module,
        "review_post_detail_normalized_job",
        lambda record, _context, hooks=None: ({"decision": "KEEP"}, record, []),
    )
    monkeypatch.setattr(
        linkedin_module,
        "fit_score_and_breakdown_displayed",
        lambda record, _profile: (0, []),
    )
    monkeypatch.setattr(linkedin_module, "print_job_human_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(linkedin_module, "load_job_type", lambda: {})
    monkeypatch.setattr(linkedin_module, "load_salary", lambda: {})
    caplog.set_level("INFO")

    kept_records, audit_rows, skill_observations = scraper.scrape()

    assert not audit_rows
    assert not skill_observations
    assert kept_records[0]["posted_age_days"] == pytest.approx(3 / 24)
    assert posted_display_label(kept_records[0]) == "22 Jun 2026"
    assert "STARTING LINKEDIN TARGET 1/1" in caplog.text
    assert "jobspy fetch start" in caplog.text
    assert "jobspy fetch done" in caplog.text
