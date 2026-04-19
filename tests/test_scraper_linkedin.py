from job_hunter_agent.scrapers.linkedin import _normalize_location_for_jobspy


def test_normalize_location_for_jobspy_handles_city_state_inputs():
    assert _normalize_location_for_jobspy("Sydney NSW") == "Sydney, Australia"
    assert _normalize_location_for_jobspy("Melbourne VIC") == "Melbourne, Australia"


def test_normalize_location_for_jobspy_handles_state_inputs():
    assert _normalize_location_for_jobspy("NSW") == "New South Wales, Australia"
    assert _normalize_location_for_jobspy("Queensland") == "Queensland, Australia"

