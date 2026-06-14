"""Tests for scraper linkedin."""

from job_hunter_agent.locations import resolve_location
from job_hunter_agent.salary import load_salary
from job_hunter_agent.scrapers.base import _build_salary_string
from job_hunter_agent.scrapers.location_adapters import to_jobspy


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
