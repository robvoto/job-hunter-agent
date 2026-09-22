import pytest

from job_hunter_agent import market_map_source, preferences

RUN_ISO = "2026-09-12T12:00:00+00:00"


def _item(job_id: int, *, salary_text: str, normalized: dict, salary_state: str = "known") -> dict:
    return {
        "id": job_id,
        "identity_key": f"seek:id:{job_id}",
        "source": "seek",
        "source_job_id": str(job_id),
        "canonical_url": f"https://seek.example/jobs/{job_id}",
        "title": "Business Analyst",
        "employer": "Example Co",
        "location": "Sydney NSW",
        "workplace_type": "Hybrid",
        "employment_type": "Full time",
        "salary_text": salary_text,
        "apply_method": "quick_apply",
        "posted_at": "2026-09-11T00:00:00+00:00",
        "teaser_text": "A role",
        "field_states": {
            "title": "known",
            "company": "known",
            "location": "known",
            "geography_code": "unknown",
            "posted_at": "known",
            "classification": "unknown",
            "subclassification": "unknown",
            "employment_type": "known",
            "workplace_type": "known",
            "apply_method": "known",
            "salary": salary_state,
            "description": "unknown",
        },
        "salary_normalized": normalized,
    }


def _profile(*, yearly=120000, daily=800):
    return {
        "salary_preferences": {
            "minimum_salary_yearly": yearly,
            "minimum_daily_rate": daily,
        }
    }


def _fail_reparse(*_args, **_kwargs):
    raise AssertionError("JMM salary text must not be reparsed by JH")


@pytest.mark.parametrize(
    (
        "bound",
        "period",
        "minimum",
        "maximum",
        "yearly_floor",
        "daily_floor",
        "eligible",
        "reason",
    ),
    [
        ("exact", "year", 110000, 110000, 120000, 0, False, "PREF_SALARY_BELOW_MIN"),
        ("exact", "year", 130000, 130000, 120000, 0, True, "OK"),
        ("exact", "day", 700, 700, 0, 800, False, "PREF_SALARY_BELOW_MIN"),
        ("exact", "day", 900, 900, 0, 800, True, "OK"),
        ("range", "year", 100000, 130000, 120000, 0, True, "OK"),
        ("range", "year", 90000, 110000, 120000, 0, False, "PREF_SALARY_BELOW_MIN"),
        ("range", "year", 130000, 150000, 120000, 0, True, "OK"),
        ("from", "year", 100000, None, 120000, 0, True, "OK"),
        ("from", "year", 130000, None, 120000, 0, True, "OK"),
        ("up_to", "year", None, 110000, 120000, 0, False, "PREF_SALARY_BELOW_MIN"),
        ("up_to", "year", None, 130000, 120000, 0, True, "OK"),
    ],
)
def test_jmm_explicit_bound_drives_salary_eligibility(
    bound,
    period,
    minimum,
    maximum,
    yearly_floor,
    daily_floor,
    eligible,
    reason,
    monkeypatch,
):
    normalized = {
        "state": "known",
        "min_amount": minimum,
        "max_amount": maximum,
        "period": period,
        "currency": "AUD",
        "qualifier": None,
        "bound": bound,
    }
    record = market_map_source.normalize_market_job(
        _item(1, salary_text="raw salary evidence", normalized=normalized),
        run_iso=RUN_ISO,
    )
    monkeypatch.setattr(preferences, "salary_is_total_package", _fail_reparse)
    monkeypatch.setattr(preferences, "salary_period_classification", _fail_reparse)
    monkeypatch.setattr(preferences, "salary_max_value", _fail_reparse)

    result, actual_reason = preferences.passes_preference_filters(
        record,
        _profile(yearly=yearly_floor, daily=daily_floor),
    )

    assert result is eligible
    assert actual_reason == reason
    assert record["salary"] == "raw salary evidence"
    assert record["market_map_salary_normalized"]["bound"] == bound


@pytest.mark.parametrize("bound", [None, "invalid"])
def test_missing_or_invalid_bound_is_not_reconstructed_from_min_max(bound, monkeypatch):
    normalized = {
        "state": "known",
        "min_amount": 50000,
        "max_amount": 50000,
        "period": "year",
        "currency": "AUD",
        "qualifier": None,
        "bound": bound,
    }
    record = market_map_source.normalize_market_job(
        _item(2, salary_text="$50,000 per year", normalized=normalized),
        run_iso=RUN_ISO,
    )
    monkeypatch.setattr(preferences, "salary_is_total_package", _fail_reparse)
    monkeypatch.setattr(preferences, "salary_period_classification", _fail_reparse)
    monkeypatch.setattr(preferences, "salary_max_value", _fail_reparse)

    eligible, reason = preferences.passes_preference_filters(record, _profile(yearly=120000, daily=0))

    assert eligible is True
    assert reason == "OK"
    assert record["market_map_salary_normalized"]["bound"] == bound


@pytest.mark.parametrize(
    ("salary_state", "normalized_state", "period", "currency", "qualifier", "bound"),
    [
        ("known", "unknown", "year", "AUD", None, "exact"),
        ("not_present", "not_present", None, None, None, None),
        ("not_applicable", "not_applicable", None, None, None, None),
        ("known", "known", None, "AUD", None, "exact"),
        ("known", "known", "year", "USD", None, "exact"),
        ("known", "known", "year", "AUD", "includes_super", "exact"),
        ("known", "known", "year", "AUD", "package", "exact"),
    ],
)
def test_unknown_or_incomparable_jmm_salary_remains_eligible(
    salary_state,
    normalized_state,
    period,
    currency,
    qualifier,
    bound,
    monkeypatch,
):
    normalized = {
        "state": normalized_state,
        "min_amount": 50000 if normalized_state == "known" else None,
        "max_amount": 50000 if normalized_state == "known" else None,
        "period": period,
        "currency": currency,
        "qualifier": qualifier,
        "bound": bound,
    }
    record = market_map_source.normalize_market_job(
        _item(
            3,
            salary_text="raw salary text",
            normalized=normalized,
            salary_state=salary_state,
        ),
        run_iso=RUN_ISO,
    )
    monkeypatch.setattr(preferences, "salary_is_total_package", _fail_reparse)
    monkeypatch.setattr(preferences, "salary_period_classification", _fail_reparse)
    monkeypatch.setattr(preferences, "salary_max_value", _fail_reparse)

    eligible, reason = preferences.passes_preference_filters(record, _profile())

    assert eligible is True
    assert reason == "OK"
    assert record["market_map_salary_normalized"]["state"] == normalized_state
