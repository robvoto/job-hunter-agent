"""Tests for scraper linkedin."""

from job_hunter_agent import job_quality
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.salary import load_salary
from job_hunter_agent.scrapers.base import _build_salary_string
from job_hunter_agent.scrapers.linkedin import LinkedInScraper
from job_hunter_agent.scrapers.location_adapters import to_jobspy
from job_hunter_agent.record_schema import RECORD_URL_KEY


def test_to_jobspy_handles_city_inputs():
    assert to_jobspy(resolve_location("Sydney")) == "Sydney, Australia"
    assert to_jobspy(resolve_location("Melbourne")) == "Melbourne, Australia"


def test_to_jobspy_handles_state_inputs():
    assert to_jobspy(resolve_location("NSW")) == "New South Wales, Australia"
    assert to_jobspy(resolve_location("Queensland")) == "Queensland, Australia"


def test_jobspy_salary_string_keeps_non_yearly_amounts():
    rules = load_salary()
    assert _build_salary_string(70, 90, "hourly", "AUD", rules) == "$70\u201390 /hr"
    assert _build_salary_string(130000, 150000, "yearly", "AUD", rules) == "$130k\u2013150k p.a."


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
