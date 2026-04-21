from job_hunter_agent.scrapers.base import _build_salary_string
from job_hunter_agent.scrapers.linkedin import _normalize_location_for_jobspy


def test_normalize_location_for_jobspy_handles_city_state_inputs():
    assert _normalize_location_for_jobspy("Sydney NSW") == "Sydney, Australia"
    assert _normalize_location_for_jobspy("Melbourne VIC") == "Melbourne, Australia"


def test_normalize_location_for_jobspy_handles_state_inputs():
    assert _normalize_location_for_jobspy("NSW") == "New South Wales, Australia"
    assert _normalize_location_for_jobspy("Queensland") == "Queensland, Australia"


def test_jobspy_salary_string_keeps_non_yearly_amounts():
    assert _build_salary_string(70, 90, "hourly", "AUD") == "$70\u201390 /hr"
    assert _build_salary_string(130000, 150000, "yearly", "AUD") == "$130k\u2013150k p.a."
