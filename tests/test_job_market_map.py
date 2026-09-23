"""JH-306 Job Market Map consumer contract tests."""

from __future__ import annotations

import copy
import json
import threading
import time
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from job_hunter_agent import (
    market_map_source,
    preferences,
    run_context,
    run_control,
    source_runner,
    user_context,
)
from job_hunter_agent.job_market_map_client import (
    JobMarketMapClient,
    JobMarketMapContractError,
    JobMarketMapJDNotCached,
    JobMarketMapJDUnavailable,
    JobMarketMapUnavailable,
)
from job_hunter_agent.job_review_pipeline import (
    TitleGateAssessment,
    TitleJudgmentResult,
)
from job_hunter_agent.occupation_taxonomy import (
    RESULT_NEAR,
    OccupationClassification,
)
from job_hunter_agent.paths import get_active_user_id
from job_hunter_agent.source_runner import SourceRunResult


class _Response:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._raw


def _feed_page(
    *,
    items,
    next_cursor: int,
    has_more: bool,
    snapshot_max_id: int | None = None,
    total: int | None = None,
) -> dict:
    return {
        "api_version": "v3",
        "schema_version": 6,
        "snapshot_max_id": next_cursor if snapshot_max_id is None else snapshot_max_id,
        "total": len(items) if total is None else total,
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _consumer_state(*, snapshot_max_id: int, pending_count: int, last_job_id: int = 0) -> dict:
    return {
        "consumer_key": "job-hunter:rob",
        "last_job_id": last_job_id,
        "updated_at": None,
        "note": None,
        "snapshot_max_id": snapshot_max_id,
        "pending_active_primary_count": pending_count,
    }


def _item(job_id: int, *, full_description: str = "") -> dict:
    item = {
        "id": job_id,
        "identity_key": f"seek:id:{job_id}",
        "source": "seek",
        "source_job_id": str(job_id),
        "canonical_url": f"https://seek.example/jobs/{job_id}",
        "title": f"Business Analyst {job_id}",
        "employer": "Example Co",
        "location": "Sydney NSW",
        "workplace_type": "Hybrid",
        "employment_type": "Full time",
        "salary_text": "$100k",
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
            "salary": "known",
            "description": "known" if full_description else "unknown",
        },
        "salary_normalized": {
            "state": "known",
            "min_amount": 100000,
            "max_amount": 100000,
            "period": "year",
            "currency": "AUD",
            "qualifier": None,
            "bound": "exact",
        },
    }
    if full_description:
        item["full_description"] = full_description
    return item


def test_client_reads_paginated_neutral_feed_and_rejects_activity_fields():
    responses = iter(
        [
            _Response(_feed_page(items=[_item(1)], next_cursor=1, has_more=True)),
            _Response(_feed_page(items=[_item(2)], next_cursor=2, has_more=False)),
        ]
    )
    client = JobMarketMapClient(
        "https://jmm.example/v3",
        opener=lambda *_args, **_kwargs: next(responses),
    )

    assert [item["id"] for item in client.iter_feed()] == [1, 2]

    activity_page = _feed_page(items=[{**_item(1), "liked": True}], next_cursor=1, has_more=False)
    activity_client = JobMarketMapClient(
        "https://jmm.example/v3",
        opener=lambda *_args, **_kwargs: _Response(activity_page),
    )
    with pytest.raises(JobMarketMapContractError, match="personal activity"):
        activity_client.feed_page()


def test_consumer_client_reads_pending_work_summary():
    requested_urls: list[str] = []

    def opener(request, **_kwargs):
        requested_urls.append(request.full_url)
        return _Response(
            _consumer_state(snapshot_max_id=38076, pending_count=35228, last_job_id=1000)
        )

    client = JobMarketMapClient("https://jmm.example/v3", opener=opener)
    state = client.consumer_state(consumer_key="job-hunter:rob")

    assert state["last_job_id"] == 1000
    assert state["snapshot_max_id"] == 38076
    assert state["pending_active_primary_count"] == 35228
    assert requested_urls == ["https://jmm.example/v3/consumers/job-hunter%3Arob/state"]


def test_consumer_client_forwards_run_scoped_high_water():
    requested_urls: list[str] = []

    def opener(request, **_kwargs):
        requested_urls.append(request.full_url)
        return _Response(
            _feed_page(
                items=[_item(55)],
                next_cursor=55,
                has_more=False,
                snapshot_max_id=55,
            )
        )

    client = JobMarketMapClient("https://jmm.example/v3", opener=opener)
    page = client.consumer_feed_page(
        consumer_key="job-hunter:rob",
        through_id=55,
    )

    assert page["snapshot_max_id"] == 55
    assert requested_urls == [
        "https://jmm.example/v3/consumers/job-hunter%3Arob/feed?through_id=55&include_raw=False"
    ]


def test_search_client_forwards_scope_filters_as_repeated_query_values():
    requested_urls: list[str] = []

    def opener(request, **_kwargs):
        requested_urls.append(request.full_url)
        return _Response(_feed_page(items=[_item(55)], next_cursor=55, has_more=False))

    client = JobMarketMapClient("https://jmm.example/v3", opener=opener)
    page = client.search_page(
        role_terms=["Business Analyst", "Product Manager"],
        sources=["seek", "linkedin"],
        geography_codes=["NSW", "VIC"],
        locations=["Sydney", "Melbourne"],
        classifications=["Information & Communication Technology"],
        subclassifications=["Business/Systems Analysts"],
        employment_types=["Full time", "Contract/Temp"],
        workplace_types=["Hybrid", "Remote"],
        apply_methods=["quick_apply"],
        companies=["Acme"],
        posted_after="2026-09-08T12:00:00+00:00",
        salary_min=120000,
        salary_max=180000,
        salary_period="year",
        salary_currency="AUD",
    )

    assert page["items"][0]["id"] == 55
    assert requested_urls == [
        "https://jmm.example/v3/jobs/search?q=Business+Analyst&q=Product+Manager"
        "&source=seek&source=linkedin&geography_code=NSW&geography_code=VIC"
        "&location=Sydney&location=Melbourne"
        "&classification=Information+%26+Communication+Technology"
        "&subclassification=Business%2FSystems+Analysts"
        "&employment_type=Full+time&employment_type=Contract%2FTemp"
        "&workplace_type=Hybrid&workplace_type=Remote&apply_method=quick_apply"
        "&company=Acme&posted_after=2026-09-08T12%3A00%3A00%2B00%3A00"
        "&salary_min=120000&salary_max=180000&salary_period=year&salary_currency=AUD"
        "&after_id=0&include_archived=False&include_raw=False"
    ]


def test_client_requires_explicit_aws_ready_api_base(monkeypatch):
    monkeypatch.delenv("JOB_HUNTER_MARKET_MAP_BASE_URL", raising=False)
    with pytest.raises(JobMarketMapUnavailable, match="JOB_HUNTER_MARKET_MAP_BASE_URL"):
        JobMarketMapClient.from_environment()

    with pytest.raises(ValueError, match="include /v3"):
        JobMarketMapClient("https://jmm.example")


def test_client_uses_exact_lookup_and_current_jd_contract():
    requests: list[tuple[str, str]] = []
    responses = iter(
        [
            _Response(
                {
                    "api_version": "v3",
                    "schema_version": 6,
                    "job": _item(9),
                }
            ),
            _Response(
                {
                    "api_version": "v3",
                    "schema_version": 6,
                    "full_description": "Canonical current JD",
                    "jd_fetched_at": "2026-09-11T12:01:00+00:00",
                    "jd_source": "seek_job_page",
                }
            ),
        ]
    )

    def opener(request, **_kwargs):
        requests.append((request.method, request.full_url))
        return next(responses)

    client = JobMarketMapClient("https://jmm.example/v3", opener=opener)

    assert client.lookup_job(identity_key="seek:id:9")["job"]["id"] == 9
    assert client.get_cached_jd(jmm_job_id=9, identity_key="seek:id:9")["jd_source"] == "seek_job_page"
    assert requests == [
        ("GET", "https://jmm.example/v3/jobs/lookup?identity_key=seek%3Aid%3A9"),
        ("GET", "https://jmm.example/v3/jobs/9/jd?identity_key=seek%3Aid%3A9"),
    ]


def test_client_fails_closed_for_transport_and_unsupported_jd_responses():
    unavailable_client = JobMarketMapClient(
        "https://jmm.example/v3",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(JobMarketMapUnavailable, match="request failed"):
        unavailable_client.feed_page()

    invalid_jd_client = JobMarketMapClient(
        "https://jmm.example/v3",
        opener=lambda *_args, **_kwargs: _Response(
            {
                "api_version": "v3",
                "schema_version": 6,
                "full_description": "",
                "jd_source": "seek_job_page",
            }
        ),
    )
    with pytest.raises(JobMarketMapContractError, match="empty canonical JD"):
        invalid_jd_client.get_cached_jd(jmm_job_id=9, identity_key="seek:id:9")

    jd_error = HTTPError(
        "https://jmm.example/v3/jobs/1084/jd",
        502,
        "Bad Gateway",
        {},
        BytesIO(
            b'{"detail":"all linked JD sources failed: seek: SEEK JD fetch failed: '
            b'SEEK job 94519870 is unavailable (not_found)"}'
        ),
    )
    jd_error_client = JobMarketMapClient(
        "https://jmm.example/v3",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(jd_error),
    )
    with pytest.raises(JobMarketMapUnavailable, match=r"94519870 is unavailable \(not_found\)"):
        jd_error_client.get_cached_jd(jmm_job_id=1084, identity_key="seek:id:1084")

    terminal_jd_error = HTTPError(
        "https://jmm.example/v3/jobs/1084/jd",
        410,
        "Gone",
        {},
        BytesIO(b'{"detail":"all linked JD sources are terminal unavailable"}'),
    )
    terminal_jd_client = JobMarketMapClient(
        "https://jmm.example/v3",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(terminal_jd_error),
    )
    with pytest.raises(JobMarketMapJDUnavailable, match="terminal unavailable"):
        terminal_jd_client.get_cached_jd(jmm_job_id=1084, identity_key="seek:id:1084")


def test_market_record_keeps_jmm_identity_without_copying_jd():
    record = market_map_source.normalize_market_job(
        _item(7, full_description="Do not copy"), run_iso="2026-09-11T12:00:00+00:00"
    )

    assert record["job_key"] == "seek:7"
    assert record["market_map_identity_key"] == "seek:id:7"
    assert record["market_map_job_id"] == 7
    assert record["full_description"] == ""


@pytest.mark.parametrize(
    ("state", "expected_work_mode", "expected_apply_method", "needs_review"),
    [
        ("known", "hybrid", "quick_apply", False),
        ("not_present", "unknown", "unknown", False),
        ("unknown", "unknown", "unknown", True),
        ("not_applicable", "unknown", "unknown", False),
    ],
)
def test_jh312_field_states_control_work_mode_and_apply_method_without_reinference(
    state, expected_work_mode, expected_apply_method, needs_review
):
    item = _item(40)
    item["location"] = "Remote, Australia"
    item["workplace_type"] = "Hybrid"
    item["apply_method"] = "quick_apply"
    item["field_states"] = {
        **item["field_states"],
        "workplace_type": state,
        "apply_method": state,
    }

    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )

    assert record["work_mode"] == expected_work_mode
    assert record["apply_method"] == expected_apply_method
    assert record["work_mode_needs_review"] is needs_review
    assert record["market_map_field_states"]["workplace_type"] == state
    assert record["market_map_field_states"]["apply_method"] == state


@pytest.mark.parametrize("state", ["not_present", "not_applicable"])
def test_jh312_absent_employment_type_stays_eligible_without_unknown_warning(
    state, tmp_path, monkeypatch, caplog):
    item = _item(42)
    item["employment_type"] = "Contract/Temp"
    item["field_states"] = {
        **item["field_states"],
        "employment_type": state,
    }
    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )
    log_path = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(preferences, "UNCERTAINTY_LOG_PATH", log_path)
    warnings = []
    monkeypatch.setattr(
        preferences,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )

    with caplog.at_level("INFO", logger="job_hunter_agent.preferences"):
        eligible, reason = preferences.passes_preference_filters(
            record,
            {"match_preferences": {"engagement_type": ["contract"]}},
        )

    assert eligible is True
    assert reason == "OK"
    assert record["market_map_field_states"]["employment_type"] == state
    assert "[PREFERENCE][WORK_TYPE_UNKNOWN]" not in caplog.text
    assert not warnings
    assert not log_path.exists()


@pytest.mark.parametrize("state", ["not_present", "not_applicable"])
def test_jh312_absent_workplace_type_stays_eligible_without_unknown_warning(
    state, tmp_path, monkeypatch, caplog
):
    item = _item(43)
    item["workplace_type"] = "On-site"
    item["field_states"] = {
        **item["field_states"],
        "workplace_type": state,
    }
    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )
    log_path = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(preferences, "UNCERTAINTY_LOG_PATH", log_path)
    warnings = []
    monkeypatch.setattr(
        preferences,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )

    with caplog.at_level("INFO", logger="job_hunter_agent.preferences"):
        eligible, reason = preferences.passes_preference_filters(
            record,
            {"match_preferences": {"work_mode_preference": ["remote"]}},
        )

    assert eligible is True
    assert reason == "OK"
    assert record["market_map_field_states"]["workplace_type"] == state
    assert "[PREFERENCE][WORK_MODE_UNKNOWN]" not in caplog.text
    assert not warnings
    assert not log_path.exists()


def test_jh312_known_unrecognised_workplace_value_stays_reviewable_without_text_inference():
    item = _item(48)
    item["workplace_type"] = "Flexible arrangement"

    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )

    assert record["market_map_field_states"]["workplace_type"] == "known"
    assert record["source_metadata"]["raw_source_fields"]["workplace_type"] == (
        "Flexible arrangement"
    )
    assert record["work_mode"] == "unknown"
    assert record["work_mode_needs_review"] is True


def test_jh312_not_applicable_future_source_does_not_turn_stale_values_into_rejection():
    from job_hunter_agent.preferences import passes_preference_filters

    item = _item(41)
    item.update(
        {
            "source": "futureboard",
            "source_job_id": "future-41",
            "identity_key": "futureboard:id:future-41",
            "canonical_url": "https://futureboard.example/jobs/41",
            "workplace_type": "On-site",
            "apply_method": "external_apply",
        }
    )
    item["field_states"] = {
        **item["field_states"],
        "workplace_type": "not_applicable",
        "apply_method": "not_applicable",
    }

    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )
    eligible, _reason = passes_preference_filters(
        record,
        {"match_preferences": {"work_mode_preference": ["remote"]}},
    )

    assert record["source"] == "futureboard"
    assert record["work_mode"] == "unknown"
    assert record["apply_method"] == "unknown"
    assert eligible is True


@pytest.mark.parametrize("state", ["not_present", "unknown", "not_applicable"])
def test_jh312_non_known_salary_state_ignores_stale_salary_and_remains_eligible(state):
    from job_hunter_agent.preferences import passes_preference_filters

    item = _item(42)
    item["salary_text"] = "$40,000 per year"
    item["field_states"] = {**item["field_states"], "salary": state}
    item["salary_normalized"] = {
        "state": state,
        "min_amount": 40000,
        "max_amount": 40000,
        "period": "year",
        "currency": "AUD",
        "qualifier": None,
        "bound": "exact",
    }

    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )
    eligible, _reason = passes_preference_filters(
        record,
        {"salary_preferences": {"minimum_salary_yearly": 120000, "minimum_daily_rate": 0}},
    )

    assert record["salary"] == ""
    assert record["market_map_field_states"]["salary"] == state
    assert record["market_map_salary_normalized"]["state"] == state
    assert eligible is True
    assert record["source_metadata"]["raw_source_fields"]["salary_text"] == "$40,000 per year"


def test_jh312_known_normalized_salary_drives_filter_without_reparsing_text(monkeypatch):
    from job_hunter_agent import preferences

    item = _item(43)
    item["salary_text"] = "JMM already normalised this deterministic amount"
    item["salary_normalized"] = {
        "state": "known",
        "min_amount": 90000,
        "max_amount": 100000,
        "period": "year",
        "currency": "AUD",
        "qualifier": "plus_super",
        "bound": "range",
    }
    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )

    def fail_reparse(*_args, **_kwargs):
        raise AssertionError("JMM salary text must not be reparsed by JH")

    monkeypatch.setattr(preferences, "salary_is_total_package", fail_reparse)
    monkeypatch.setattr(preferences, "salary_period_classification", fail_reparse)
    monkeypatch.setattr(preferences, "salary_max_value", fail_reparse)

    eligible, reason = preferences.passes_preference_filters(
        record,
        {"salary_preferences": {"minimum_salary_yearly": 120000, "minimum_daily_rate": 0}},
    )

    assert eligible is False
    assert reason == "PREF_SALARY_BELOW_MIN"


def test_jh312_known_but_unresolved_normalized_salary_stays_eligible_without_reparse(monkeypatch):
    from job_hunter_agent import preferences

    item = _item(44)
    item["salary_text"] = "Competitive"
    item["salary_normalized"] = {
        "state": "unknown",
        "min_amount": None,
        "max_amount": None,
        "period": None,
        "currency": None,
        "qualifier": None,
        "bound": None,
    }
    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )

    monkeypatch.setattr(
        preferences,
        "salary_max_value",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("JMM salary text must not be reparsed by JH")
        ),
    )
    eligible, _reason = preferences.passes_preference_filters(
        record,
        {"salary_preferences": {"minimum_salary_yearly": 120000, "minimum_daily_rate": 0}},
    )

    assert record["salary"] == "Competitive"
    assert record["market_map_field_states"]["salary"] == "known"
    assert record["market_map_salary_normalized"]["state"] == "unknown"
    assert eligible is True


def test_jh312_non_known_classification_cannot_reuse_stale_value_for_sector():
    item = _item(45)
    item["classification_text"] = "Government & Defence"
    item["field_states"] = {**item["field_states"], "classification": "not_present"}

    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )

    assert record["sector"] != "government"
    assert record["market_map_field_states"]["classification"] == "not_present"


def test_jh312_rejects_incomplete_or_invalid_jmm_field_state_contract():
    incomplete = _item(46)
    incomplete["field_states"] = dict(incomplete["field_states"])
    incomplete["field_states"].pop("salary")
    with pytest.raises(JobMarketMapContractError, match="field_states"):
        market_map_source.normalize_market_job(
            incomplete, run_iso="2026-09-12T12:00:00+00:00"
        )

    invalid = _item(47)
    invalid["field_states"] = {**invalid["field_states"], "workplace_type": "maybe"}
    with pytest.raises(JobMarketMapContractError, match="field state"):
        market_map_source.normalize_market_job(
            invalid, run_iso="2026-09-12T12:00:00+00:00"
        )


def test_market_source_searches_selected_scope_and_requests_current_jd(monkeypatch):
    pages = iter(
        [
            _feed_page(
                items=[_item(1)],
                next_cursor=1,
                has_more=True,
                snapshot_max_id=2,
                total=2,
            ),
            _feed_page(
                items=[_item(2, full_description="Current canonical JD")],
                next_cursor=2,
                has_more=False,
                snapshot_max_id=2,
                total=2,
            ),
        ]
    )
    jd_calls: list[int] = []
    search_calls: list[dict] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **kwargs):
            search_calls.append(kwargs)
            return next(pages)

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            jd_calls.append(jmm_job_id)
            return {
                "full_description": "Enriched canonical JD",
                "jd_source": "seek_job_page",
                "jd_fetched_at": "2026-09-11T12:01:00+00:00",
            }

    def pre(record, _context):
        return ({"decision": "KEEP"}, record, [], True)

    def post(record, _context):
        return ({"decision": "KEEP"}, record, [])

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "get_job_market_map_parallel_workers", lambda: 6)
    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "review_post_detail_normalized_job", post)
    saved_caches: list[dict] = []
    monkeypatch.setattr(
        market_map_source,
        "save_llm_cache",
        lambda cache: saved_caches.append(copy.deepcopy(cache)),
    )
    progress_states: list[dict] = []
    real_set_run_progress_state = run_control.set_run_progress_state

    def capture_progress(text, **kwargs):
        real_set_run_progress_state(text, **kwargs)
        detail = run_control.get_run_progress_detail()
        assert detail is not None
        progress_states.append(detail)

    monkeypatch.setattr(market_map_source, "set_run_progress_state", capture_progress)
    run_control.clear_run_progress()
    context = SimpleNamespace(
        profile={},
        search_settings={"keywords": "Business Analyst", "locations": ["Sydney"]},
        enabled_sources=["seek"],
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )

    try:
        kept, audit, _skills = market_map_source.run_market_map_source(context)
        final_progress_detail = run_control.get_run_progress_detail()
    finally:
        run_control.clear_run_progress()

    assert [call["after_id"] for call in search_calls] == [0, 1]
    assert [call["through_id"] for call in search_calls] == [None, 2]
    assert all(call["role_terms"] == ["Business Analyst"] for call in search_calls)
    assert all(call["sources"] == ["seek"] for call in search_calls)
    assert all(call["geography_codes"] == ["NSW"] for call in search_calls)
    assert all(call["posted_after"] == "2026-09-08T12:00:00+00:00" for call in search_calls)
    assert jd_calls == [1, 2]
    # Progressive JMM paging persists title/fit cache state after each page.
    assert len(saved_caches) == 4
    assert [row["job_key"] for row in audit] == ["seek:1", "seek:2"]
    assert len(kept) == 2
    assert all("full_description" not in record for record in kept)
    assert all("details_text" not in record for record in kept)
    assert final_progress_detail == progress_states[-1]
    assert final_progress_detail["source"] == "job_market_map"
    assert progress_states[0]["headline"] == "Finding matching jobs"
    assert any(state["headline"] == "Checking job titles — 1 of 2" for state in progress_states)
    assert any(state["headline"] == "Getting job descriptions — 1 of 1" for state in progress_states)
    assert any(state["headline"] == "Reviewing job fit — 1 of 1" for state in progress_states)
    assert any(
        state["headline"] == "Finalising results — 1 of 1"
        and state["detail"] == "Business Analyst 1"
        for state in progress_states
    )
    assert all("JMM" not in state["headline"] for state in progress_states)
    assert progress_states[-1]["headline"] == "Search review complete"


def test_market_source_rejects_total_changes_inside_fixed_scope(monkeypatch):
    pages = iter(
        [
            _feed_page(
                items=[_item(1)],
                next_cursor=1,
                has_more=True,
                snapshot_max_id=2,
                total=2,
            ),
            _feed_page(
                items=[_item(2)],
                next_cursor=2,
                has_more=False,
                snapshot_max_id=2,
                total=3,
            ),
        ]
    )
    calls = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **kwargs):
            calls.append((kwargs["after_id"], kwargs["through_id"]))
            return next(pages)

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    client = FakeClient()

    with pytest.raises(JobMarketMapContractError, match="total changed"):
        list(market_map_source._iter_filtered_market_pages(_market_context(), client))

    assert calls == [(0, None), (1, 2)]


def test_market_source_processes_more_than_100_jobs_across_fixed_snapshot_pages(monkeypatch):
    pages = iter(
        [
            _feed_page(
                items=[_item(i) for i in range(1, 101)],
                next_cursor=100,
                has_more=True,
                snapshot_max_id=205,
                total=205,
            ),
            _feed_page(
                items=[_item(i) for i in range(101, 201)],
                next_cursor=200,
                has_more=True,
                snapshot_max_id=205,
                total=205,
            ),
            _feed_page(
                items=[_item(i) for i in range(201, 206)],
                next_cursor=205,
                has_more=False,
                snapshot_max_id=205,
                total=205,
            ),
        ]
    )
    search_calls: list[tuple[int, int | None]] = []
    analysed_ids: list[int] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **kwargs):
            search_calls.append((kwargs["after_id"], kwargs["through_id"]))
            return next(pages)

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "get_job_market_map_parallel_workers", lambda: 6)

    def pre(record, _context):
        analysed_ids.append(int(record["market_map_job_id"]))
        return ({"decision": "REJECT"}, record, [], False)

    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)

    kept, audit, _skills = market_map_source.run_market_map_source(_market_context())

    assert kept == []
    assert audit == []
    assert analysed_ids == list(range(1, 206))
    assert search_calls == [(0, None), (100, 205), (200, 205)]
    progress = run_control.get_run_progress_detail()
    assert progress is not None
    assert progress["current"] == 205
    assert progress["total"] == 205


def test_market_source_does_not_checkpoint_after_analysis_failure(monkeypatch):
    checkpoints: list[int] = []

    class FailedAnalysisClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(items=[_item(10)], next_cursor=10, has_more=False)

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append(last_job_id)
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FailedAnalysisClient)
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("analysis failed")),
    )
    context = SimpleNamespace(
        profile={},
        search_settings={"keywords": "Business Analyst", "locations": ["Sydney"]},
        enabled_sources=["seek"],
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )

    with pytest.raises(RuntimeError, match="analysis failed"):
        market_map_source.run_market_map_source(context)

    assert checkpoints == []


def test_jmm_jd_502_preserves_completed_results_and_marks_job_retryable(monkeypatch):
    checkpoints: list[int] = []

    class FailedJdClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(
                items=[_item(i) for i in range(1083, 1086)], next_cursor=1085, has_more=False
            )

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            if jmm_job_id == 1084:
                raise JobMarketMapUnavailable(
                    "Job Market Map request failed: HTTP Error 502: Bad Gateway"
                )
            return {
                "full_description": f"JD {jmm_job_id}",
                "jd_source": "jmm",
                "jd_fetched_at": "2026-09-14T00:00:00+00:00",
            }

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append(last_job_id)
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FailedJdClient)
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )
    monkeypatch.setattr(
        market_map_source,
        "review_post_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, []),
    )
    monkeypatch.setattr("job_hunter_agent.paths.get_active_user_id", lambda: "rob")

    result = source_runner._run_market_map_source(_market_context())

    assert [record["market_map_job_id"] for record in result.kept_records] == [1083, 1085]
    assert [row["market_map_job_id"] for row in result.audit_rows] == [1083, 1084, 1085]
    failed_row = result.audit_rows[1]
    assert failed_row["decision"] == "REJECT"
    assert failed_row["reject_reason"] == "JMM_JD_ENRICHMENT_FAILED"
    assert failed_row["retryable"] is True
    assert failed_row["retry_reason"] == "JMM_JD_ENRICHMENT_FAILED"
    assert failed_row["decision_explanation"] == (
        "Job Market Map request failed: HTTP Error 502: Bad Gateway"
    )
    assert isinstance(result.error, JobMarketMapUnavailable)
    assert str(result.error) == "Job Market Map request failed: HTTP Error 502: Bad Gateway"
    assert result.source_collection_complete is False
    assert checkpoints == []


def test_jmm_jd_410_skips_terminal_job_without_consumer_checkpoint(monkeypatch):
    checkpoints: list[int] = []

    class TerminalJdClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(
                items=[_item(i) for i in range(1083, 1086)], next_cursor=1085, has_more=False
            )

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            if jmm_job_id == 1084:
                raise JobMarketMapJDUnavailable(
                    "Job Market Map request failed: HTTP Error 410: Gone: "
                    "all linked JD sources are terminal unavailable"
                )
            return {
                "full_description": f"JD {jmm_job_id}",
                "jd_source": "jmm",
                "jd_fetched_at": "2026-09-14T00:00:00+00:00",
            }

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append(last_job_id)
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", TerminalJdClient)
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )
    monkeypatch.setattr(
        market_map_source,
        "review_post_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, []),
    )
    monkeypatch.setattr("job_hunter_agent.paths.get_active_user_id", lambda: "rob")

    result = source_runner._run_market_map_source(_market_context())

    assert [record["market_map_job_id"] for record in result.kept_records] == [1083, 1085]
    assert [row["market_map_job_id"] for row in result.audit_rows] == [1083, 1084, 1085]
    unavailable_row = result.audit_rows[1]
    assert unavailable_row["decision"] == "REJECT"
    assert unavailable_row["reject_reason"] == "JMM_JD_UNAVAILABLE"
    assert unavailable_row["retryable"] is False
    assert unavailable_row.get("retry_reason") in {None, ""}
    assert unavailable_row["decision_explanation"].endswith("terminal unavailable")
    assert result.error is None
    assert result.source_collection_complete is True
    assert checkpoints == []


def _market_context(profile=None):
    return SimpleNamespace(
        profile=profile or {},
        search_settings={"keywords": "Business Analyst", "locations": ["Sydney"]},
        enabled_sources=["seek"],
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )


def test_market_parallel_stage_propagates_user_context_without_leaking_worker_state():
    """JMM analysis workers retain the caller's user scope, independently."""
    caller_user_id = "seeded-caller"
    user_context.set_user_id(caller_user_id)
    jobs = [
        market_map_source._IndexedJob(index=index, record={}, title_assessment=None)
        for index in range(3)
    ]

    def worker(job):
        observed_user_id = get_active_user_id()
        user_context.set_user_id(f"worker-{job.index}")
        return observed_user_id

    results, stopped = market_map_source._run_parallel_stage(
        jobs,
        worker_limit=2,
        worker=worker,
    )

    assert stopped is False
    assert results == {0: caller_user_id, 1: caller_user_id, 2: caller_user_id}
    assert get_active_user_id() == caller_user_id


def test_market_source_parallel_stages_overlap_and_merge_in_input_order(monkeypatch):
    items = [_item(job_id) for job_id in range(1, 5)]
    checkpoints: list[int] = []
    active = {stage: 0 for stage in ("title", "jd", "fit")}
    maximum = {stage: 0 for stage in active}
    lock = threading.Lock()

    def delayed(stage, callback):
        with lock:
            active[stage] += 1
            maximum[stage] = max(maximum[stage], active[stage])
        try:
            time.sleep(0.05)
            return callback()
        finally:
            with lock:
                active[stage] -= 1

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(items=items, next_cursor=4, has_more=False)

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            return delayed(
                "jd",
                lambda: {
                    "full_description": f"JD {jmm_job_id}",
                    "jd_source": "jmm",
                    "jd_fetched_at": "2026-09-11T12:01:00+00:00",
                },
            )

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append(last_job_id)
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    def title_gate(_title, _profile):
        return TitleGateAssessment(
            title_analysis={"ok": False, "reason": "TITLE_NOT_TARGET"},
            onet=OccupationClassification(
                result=RESULT_NEAR,
                matched_occupation_code="13-1111.00",
                confidence=0.9,
                reason=RESULT_NEAR,
            ),
            title_judgment_cache_key=f"title:{_title}",
        )

    def title_review(title, profile, llm_cache):
        return delayed(
            "title",
            lambda: TitleJudgmentResult(
                cache_key=f"title:{title}",
                judgment={"verdict": "match", "reason": "test"},
                cache_value={"verdict": "match", "reason": "test"},
                cache_hit=False,
            ),
        )

    def pre(record, _context):
        return ({"decision": "KEEP"}, record, [], True)

    def post(record, _context):
        return delayed("fit", lambda: ({"decision": "KEEP"}, record, []))

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "get_job_market_map_parallel_workers", lambda: 2)
    monkeypatch.setattr(market_map_source, "prepare_title_gate_assessment", title_gate)
    monkeypatch.setattr(market_map_source, "review_title_judgment", title_review)
    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "review_post_detail_normalized_job", post)

    kept, audit, _skills = market_map_source.run_market_map_source(_market_context())

    assert maximum == {"title": 2, "jd": 2, "fit": 2}
    assert [record["job_key"] for record in kept] == [f"seek:{i}" for i in range(1, 5)]
    assert [row["job_key"] for row in audit] == [f"seek:{i}" for i in range(1, 5)]
    assert checkpoints == []


def test_market_source_thaws_title_worker_result_before_fit_record_copy(monkeypatch):
    """Worker snapshots stay frozen until the coordinator gives fit work normal data."""
    items = [_item(1)]

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(items=items, next_cursor=1, has_more=False)

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            return {
                "full_description": f"JD {jmm_job_id}",
                "jd_source": "jmm",
                "jd_fetched_at": "2026-09-11T12:01:00+00:00",
            }

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    def title_gate(_title, _profile):
        return TitleGateAssessment(
            title_analysis={"ok": False, "reason": "TITLE_NOT_TARGET"},
            onet=OccupationClassification(
                result=RESULT_NEAR,
                matched_occupation_code="13-1111.00",
                confidence=0.9,
                reason=RESULT_NEAR,
            ),
            title_judgment_cache_key="title:1",
        )

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "prepare_title_gate_assessment", title_gate)
    monkeypatch.setattr(
        market_map_source,
        "review_title_judgment",
        lambda *_args: TitleJudgmentResult(
            cache_key="title:1",
            judgment={"verdict": "match", "reason": "test"},
            cache_value={"verdict": "match", "reason": "test"},
            cache_hit=False,
        ),
    )

    def pre(record, context):
        assessment = context.title_assessments[str(record["job_key"])].pop(0)
        title_judgment = assessment.title_judgment
        assert title_judgment is not None
        assert isinstance(title_judgment.judgment, dict)
        record["llm_title_judgment"] = title_judgment.judgment
        return ({"decision": "KEEP"}, record, [], True)

    def post(record, _context):
        assert isinstance(record["llm_title_judgment"], dict)
        # This is the exact operation a fit worker performs before review.
        assert copy.deepcopy(record)["llm_title_judgment"] == {
            "verdict": "match",
            "reason": "test",
        }
        return ({"decision": "KEEP"}, record, [])

    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "review_post_detail_normalized_job", post)

    kept, _audit, _skills = market_map_source.run_market_map_source(
        _market_context()
    )

    assert [record["job_key"] for record in kept] == ["seek:1"]


def test_market_fit_worker_excludes_noncopyable_coordinator_identity_claim(monkeypatch):
    """The fit worker must not deep-copy the coordinator-owned lock claim."""
    registry_lock = threading.RLock()
    claim = (registry_lock, "claim-token")
    live_record = {
        "job_key": "seek:1",
        "nested": {"value": "coordinator"},
        market_map_source.RUN_IDENTITY_CLAIM_KEY: claim,
    }
    seen_worker_records: list[dict] = []

    def review(record, _context):
        seen_worker_records.append(record)
        assert market_map_source.RUN_IDENTITY_CLAIM_KEY not in record
        record["nested"]["value"] = "worker"
        return ({"decision": "KEEP"}, record, [])

    monkeypatch.setattr(market_map_source, "review_post_detail_normalized_job", review)

    result = market_map_source._run_fit_worker(
        market_map_source._IndexedJob(index=0, record=live_record, title_assessment=None),
        context=_market_context(),
        llm_cache={},
    )

    assert seen_worker_records == [{"job_key": "seek:1", "nested": {"value": "worker"}}]
    assert live_record[market_map_source.RUN_IDENTITY_CLAIM_KEY] is claim
    assert live_record["nested"] == {"value": "coordinator"}
    assert result.index == 0


def test_market_source_stop_cancels_queued_jmm_work(monkeypatch):
    stop = threading.Event()
    jd_calls: list[int] = []
    checkpoints: list[int] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(items=[_item(i) for i in range(1, 5)], next_cursor=4, has_more=False)

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            jd_calls.append(jmm_job_id)
            stop.set()
            time.sleep(0.08)
            return {
                "full_description": "JD",
                "jd_source": "jmm",
                "jd_fetched_at": "2026-09-11T12:01:00+00:00",
            }

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append(last_job_id)
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "get_job_market_map_parallel_workers", lambda: 1)
    monkeypatch.setattr(market_map_source, "run_stop_requested", stop.is_set)
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )

    market_map_source.run_market_map_source(_market_context())

    assert jd_calls == [1]
    assert checkpoints == []


def test_market_source_worker_failure_does_not_mutate_shared_state_or_checkpoint(monkeypatch):
    completed: list[int] = []
    checkpoints: list[int] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            return _feed_page(items=[_item(i) for i in range(1, 4)], next_cursor=3, has_more=False)

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            return {"full_description": "JD", "jd_source": "jmm", "jd_fetched_at": "now"}

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append(last_job_id)
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    def post(record, _context):
        job_id = int(record["market_map_job_id"])
        completed.append(job_id)
        if job_id == 2:
            raise RuntimeError("fit worker failed")
        return ({"decision": "KEEP"}, record, [])

    context = _market_context()
    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "get_job_market_map_parallel_workers", lambda: 2)
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )
    monkeypatch.setattr(market_map_source, "review_post_detail_normalized_job", post)

    with pytest.raises(RuntimeError, match="fit worker failed"):
        market_map_source.run_market_map_source(context)

    assert sorted(completed) == [1, 2, 3]
    assert checkpoints == []
    assert context.job_history == {}
    assert context.llm_cache == {}


def test_normal_runtime_builds_a_jmm_only_context(monkeypatch):
    profile = {"enabled_sources": ["seek"]}
    monkeypatch.setattr(run_context, "load_profile", lambda: profile)
    monkeypatch.setattr(run_context, "get_search_settings", lambda _profile: {})
    monkeypatch.setattr(run_context, "get_workspace_minimum_score", lambda: 50)
    monkeypatch.setattr(run_context, "get_globally_enabled_sources", lambda: ["seek"])
    monkeypatch.setattr(
        run_context,
        "run_retention_housekeeping",
        lambda *_args: pytest.fail("JMM runtime must not run legacy retention housekeeping"),
    )
    monkeypatch.setattr(
        run_context,
        "load_job_history",
        lambda: pytest.fail("JMM runtime must not load legacy job history"),
    )
    monkeypatch.setattr(run_context, "load_audit_rows", lambda: [])
    monkeypatch.setattr(run_context, "load_run_stats", lambda: {})
    monkeypatch.setattr(run_context, "load_llm_cache", lambda: {})
    monkeypatch.setattr(run_context, "write_run_attempt", lambda *_args: None)
    monkeypatch.setattr(run_context, "has_cli_flag", lambda *_args: False)

    context = run_context.build_scrape_run_context([])

    assert context.use_market_map is True
    assert context.enabled_sources == ["seek"]
    assert context.job_history == {}


def test_market_map_finalization_does_not_write_legacy_history():
    from job_hunter_agent import job_review_pipeline

    context = job_review_pipeline.ReviewPipelineContext(
        profile={},
        job_history={},
        audit_rows=[],
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        market_map_mode=True,
    )
    record = {
        "job_key": "seek:99",
        "decision": "KEEP",
        "full_description": "Current JMM JD",
    }

    job_review_pipeline._finalize(record, context)

    assert context.job_history == {}
    assert context.audit_rows == [{"job_key": "seek:99", "decision": "KEEP"}]


def test_market_map_persistence_keeps_identity_without_jd_copy():
    from job_hunter_agent.history import finalize_record

    record = market_map_source.normalize_market_job(_item(8), run_iso="2026-09-11T12:00:00+00:00")
    record.update(
        {
            "decision": "KEEP",
            "full_description": "Current JMM JD",
            "details_text": "Current JMM JD",
            "fit_source_text": "Current JMM JD",
            "market_map_jd_source": "seek_job_page",
        }
    )
    history: dict[str, dict] = {}
    audit: list[dict] = []

    finalize_record(
        history,
        audit,
        record,
        "2026-09-11T12:00:00+00:00",
        persist_full_description=False,
    )

    persisted = history["seek:8"]["last_kept_snapshot"]
    assert persisted["market_map_identity_key"] == "seek:id:8"
    assert "full_description" not in persisted
    assert "full_description" not in audit[0]
    assert "details_text" not in audit[0]
    assert "fit_source_text" not in audit[0]


def test_normal_runtime_dispatches_only_to_jmm_and_surfaces_unavailable_failure(monkeypatch):
    context = SimpleNamespace(
        use_market_map=True,
        enabled_sources=["seek"],
        source_cache_stats=None,
        source_failure_message="",
    )
    failed = JobMarketMapUnavailable("JMM unavailable")

    monkeypatch.setattr(
        source_runner,
        "_run_market_map_source",
        lambda _context: SourceRunResult(
            source="job_market_map",
            error=failed,
            source_cache_status="JMM",
            source_collection_complete=False,
        ),
    )
    monkeypatch.setattr(source_runner, "get_source_display_label", lambda source: source)
    monkeypatch.setattr(source_runner, "set_run_progress_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(source_runner, "run_stop_requested", lambda: False)

    kept, audit, skills = source_runner.run_enabled_sources(context)

    assert kept == []
    assert audit == []
    assert skills == []
    assert context.source_failure_message == "job_market_map failed: JMM unavailable"
    assert context.source_cache_stats["job_market_map"]["health"] == "full_failure"


def test_jh311_maps_existing_search_preferences_to_neutral_jmm_filters():
    context = _market_context(
        profile={
            "match_preferences": {
                "engagement_type": ["permanent"],
                "work_mode_preference": ["hybrid"],
            },
            "salary_preferences": {
                "minimum_salary_yearly": 120000,
                "minimum_daily_rate": 0,
            },
        }
    )
    context.enabled_sources = ["seek", "linkedin", "apsjobs"]
    context.search_settings.update(
        {
            "classification_ids": ["6281"],
            "classification": ["Information & Communication Technology"],
            "subclassification": ["Business/Systems Analysts"],
            "company": ["Acme"],
            "seek_quick_apply_only": True,
            "linkedin_easy_apply_only": False,
            "linkedin_hours_old": 48,
        }
    )

    scopes = market_map_source._build_market_search_scopes(context)

    assert [scope["sources"] for scope in scopes] == [["seek"], ["linkedin"], ["apsjobs"]]
    assert all(scope["role_terms"] == ["Business Analyst"] for scope in scopes)
    assert all(scope["geography_codes"] == ["NSW"] for scope in scopes)
    assert all(scope["locations"] == ["Sydney"] for scope in scopes)
    assert all(
        scope["classifications"] == ["Information & Communication Technology"]
        for scope in scopes
    )
    assert all(scope["subclassifications"] == ["Business/Systems Analysts"] for scope in scopes)
    assert all(scope["employment_types"] == ["Permanent", "Full time"] for scope in scopes)
    assert all(scope["workplace_types"] == ["Hybrid"] for scope in scopes)
    assert all(scope["companies"] == ["Acme"] for scope in scopes)
    assert scopes[0]["apply_methods"] == ["quick_apply"]
    assert scopes[1]["apply_methods"] == ["external_apply"]
    assert scopes[2]["apply_methods"] == []
    assert scopes[0]["posted_after"] == "2026-09-08T12:00:00+00:00"
    assert scopes[1]["posted_after"] == "2026-09-09T12:00:00+00:00"
    assert scopes[2]["posted_after"] == "2026-09-08T12:00:00+00:00"
    assert all(scope["salary_min"] == 120000 for scope in scopes)
    assert all(scope["salary_period"] == "year" for scope in scopes)
    assert all(scope["salary_currency"] == "AUD" for scope in scopes)
    assert all("6281" not in scope["classifications"] for scope in scopes)


def test_jh311_does_not_misroute_seek_classification_ids_into_jmm_text_filter():
    context = _market_context()
    context.search_settings.pop("classification", None)
    context.search_settings.pop("classifications", None)
    context.search_settings["classification_ids"] = ["6281"]

    scopes = market_map_source._build_market_search_scopes(context)

    assert scopes
    assert all(scope["classifications"] == [] for scope in scopes)


def test_jh311_accepts_future_jmm_sources_without_board_allowlist():
    context = _market_context()
    context.enabled_sources = ["futureboard"]

    scopes = market_map_source._build_market_search_scopes(context)

    assert [scope["sources"] for scope in scopes] == [["futureboard"]]
    assert scopes[0]["apply_methods"] == []


def test_jh311_uses_one_snapshot_boundary_across_source_scopes():
    calls: list[tuple[str, int | None]] = []

    class FakeClient:
        def search_page(self, **kwargs):
            source = kwargs["sources"][0]
            calls.append((source, kwargs["through_id"]))
            return _feed_page(
                items=[],
                next_cursor=0,
                has_more=False,
                snapshot_max_id=10,
                total=0,
            )

    context = _market_context()
    context.enabled_sources = ["seek", "linkedin"]

    list(market_map_source._iter_filtered_market_pages(context, FakeClient()))

    assert calls == [("seek", None), ("linkedin", 10)]


def test_jh311_rejects_snapshot_change_between_source_scopes():
    calls = 0

    class FakeClient:
        def search_page(self, **kwargs):
            nonlocal calls
            calls += 1
            return _feed_page(
                items=[],
                next_cursor=0,
                has_more=False,
                snapshot_max_id=10 if calls == 1 else 11,
                total=0,
            )

    context = _market_context()
    context.enabled_sources = ["seek", "linkedin"]

    with pytest.raises(JobMarketMapContractError, match="snapshot boundary changed"):
        list(market_map_source._iter_filtered_market_pages(context, FakeClient()))


def test_jh311_processes_each_cursor_page_before_requesting_the_next(monkeypatch):
    analysed_ids: list[int] = []
    calls: list[tuple[int, int | None]] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **kwargs):
            calls.append((kwargs["after_id"], kwargs["through_id"]))
            if kwargs["after_id"] == 0:
                return _feed_page(
                    items=[_item(1)],
                    next_cursor=1,
                    has_more=True,
                    snapshot_max_id=2,
                    total=2,
                )
            assert analysed_ids == [1], "JH fetched page 2 before analysing page 1"
            return _feed_page(
                items=[_item(2)],
                next_cursor=2,
                has_more=False,
                snapshot_max_id=2,
                total=2,
            )

    def pre(record, _context):
        analysed_ids.append(int(record["market_map_job_id"]))
        return ({"decision": "REJECT"}, record, [], False)

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "save_llm_cache", lambda _cache: None)

    kept, _audit, _skills = market_map_source.run_market_map_source(_market_context())

    assert kept == []
    assert analysed_ids == [1, 2]
    assert calls == [(0, None), (1, 2)]


def test_jh311_mixed_source_scopes_dedupe_the_same_canonical_vacancy(monkeypatch):
    searched_sources: list[str] = []
    analysed_ids: list[int] = []
    analysed_records: list[dict] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **kwargs):
            source = kwargs["sources"][0]
            searched_sources.append(source)
            if source == "linkedin":
                assert kwargs["through_id"] == 7
            item = {
                **_item(7),
                "matched_sources": [
                    {
                        "id": 7 if source == "seek" else 17,
                        "source": source,
                        "source_job_id": "7" if source == "seek" else "linkedin-7",
                    }
                ],
            }
            return _feed_page(
                items=[item],
                next_cursor=7,
                has_more=False,
                snapshot_max_id=7,
                total=1,
            )

    def pre(record, _context):
        analysed_ids.append(int(record["market_map_job_id"]))
        analysed_records.append(record)
        return ({"decision": "REJECT"}, record, [], False)

    context = _market_context()
    context.enabled_sources = ["seek", "linkedin"]
    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "save_llm_cache", lambda _cache: None)

    market_map_source.run_market_map_source(context)

    assert searched_sources == ["seek", "linkedin"]
    assert analysed_ids == [7]
    assert len(analysed_records) == 1
    assert [link["source"] for link in analysed_records[0]["duplicate_links"]] == ["linkedin"]
    assert [entry["source"] for entry in analysed_records[0]["source_provenance"]] == [
        "seek",
        "linkedin",
    ]


def test_jh311_preserves_cross_source_match_when_canonical_primary_is_other_board():
    item = {
        **_item(21),
        "matched_sources": [
            {"id": 31, "source": "linkedin", "source_job_id": "linkedin-21"}
        ],
    }

    record = market_map_source.normalize_market_job(
        item, run_iso="2026-09-12T12:00:00+00:00"
    )

    assert record["source"] == "seek"
    assert record["job_key"] == "seek:21"
    assert [link["source"] for link in record["duplicate_links"]] == ["linkedin"]
    assert record["duplicate_links"][0]["kind"] == "confirmed_duplicate"
    assert record["duplicate_links"][0]["job_key"] == "linkedin:linkedin-21"
    assert [entry["source"] for entry in record["source_provenance"]] == ["seek", "linkedin"]
    assert (
        record["source_provenance"][1]["source_metadata"]["raw_source_fields"]
        ["jmm_matched_source"]["id"]
        == 31
    )


def test_jh311_jmm_salary_filter_keeps_uncertain_salary_for_jh_review(monkeypatch):
    from job_hunter_agent.preferences import passes_preference_filters

    reviewed_ids: list[int] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **kwargs):
            assert kwargs["salary_min"] == 120000
            assert kwargs["salary_period"] == "year"
            assert kwargs["salary_currency"] == "AUD"
            uncertain_item = {
                **_item(9),
                "salary_text": "",
                "salary_normalized": {"state": "unknown"},
                "matched_sources": [
                    {
                        "source": "seek",
                        "source_job_id": "9",
                        "salary_match_basis": "uncertain_preserved",
                    }
                ],
            }
            uncertain_item["field_states"] = {
                **uncertain_item["field_states"],
                "salary": "unknown",
            }
            return _feed_page(
                items=[uncertain_item],
                next_cursor=9,
                has_more=False,
                snapshot_max_id=9,
                total=1,
            )

    context = _market_context(
        profile={
            "salary_preferences": {
                "minimum_salary_yearly": 120000,
                "minimum_daily_rate": 0,
            }
        }
    )

    def pre(record, _review_context):
        reviewed_ids.append(int(record["market_map_job_id"]))
        eligible, _reason = passes_preference_filters(record, context.profile)
        assert eligible is True
        return ({"decision": "REJECT"}, record, [], False)

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "save_llm_cache", lambda _cache: None)

    market_map_source.run_market_map_source(context)

    assert reviewed_ids == [9]


def test_jh311_maps_both_salary_floors_as_separate_neutral_scopes():
    context = _market_context(
        profile={
            "match_preferences": {
                "engagement_type": ["permanent", "contract", "full_time_contract"],
            },
            "salary_preferences": {
                "minimum_salary_yearly": 120000,
                "minimum_daily_rate": 900,
            },
        }
    )

    scopes = market_map_source._build_market_search_scopes(context)

    assert len(scopes) == 2
    assert {
        (scope["salary_min"], scope["salary_period"], scope["salary_currency"])
        for scope in scopes
    } == {(120000, "year", "AUD"), (900, "day", "AUD")}


def test_jh311_search_failure_propagates_without_direct_source_fallback(monkeypatch):
    class FailedClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def search_page(self, **_kwargs):
            raise JobMarketMapUnavailable("JMM unavailable during /v3/jobs/search")

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FailedClient)

    try:
        market_map_source.run_market_map_source(_market_context())
    except JobMarketMapUnavailable as exc:
        assert "/v3/jobs/search" in str(exc)
    else:
        raise AssertionError("JMM search failure was swallowed instead of failing clearly")


def test_jh313_cached_jd_409_is_not_cached_and_never_posts():
    requests = []

    def opener(request, **_kwargs):
        requests.append((request.get_method(), request.full_url))
        raise HTTPError(
            request.full_url,
            409,
            "Conflict",
            {},
            BytesIO(b'{"detail":"JD not cached yet"}'),
        )

    client = JobMarketMapClient("https://jmm.example/v3", opener=opener)

    with pytest.raises(JobMarketMapJDNotCached, match="JD not cached yet"):
        client.get_cached_jd(jmm_job_id=9, identity_key="seek:id:9")

    assert requests == [
        ("GET", "https://jmm.example/v3/jobs/9/jd?identity_key=seek%3Aid%3A9")
    ]


def test_jh313_one_409_is_audited_skipped_and_does_not_fail_run(monkeypatch):
    fit_ids = []

    class CacheMissClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def get_readiness(self):
            return {
                "source_runs": {
                    "seek": {"status": "COMPLETE"},
                    "linkedin": {"status": "COMPLETE"},
                },
                "jd_coverage": {
                    "available": 2,
                    "missing_not_cached": 1,
                    "failed": 0,
                },
            }

        def search_page(self, **_kwargs):
            return _feed_page(
                items=[_item(i) for i in range(1083, 1086)],
                next_cursor=1085,
                has_more=False,
            )

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            if jmm_job_id == 1084:
                raise JobMarketMapJDNotCached(
                    "Job Market Map request failed: HTTP Error 409: Conflict: JD not cached yet"
                )
            return {
                "full_description": f"JD {jmm_job_id}",
                "jd_source": "jmm",
                "jd_fetched_at": "2026-09-14T00:00:00+00:00",
            }

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", CacheMissClient)
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )

    def keep_after_fit(record, _context):
        fit_ids.append(record["market_map_job_id"])
        return {"decision": "KEEP"}, record, []

    monkeypatch.setattr(
        market_map_source,
        "review_post_detail_normalized_job",
        keep_after_fit,
    )
    monkeypatch.setattr("job_hunter_agent.paths.get_active_user_id", lambda: "rob")

    result = source_runner._run_market_map_source(_market_context())

    assert [record["market_map_job_id"] for record in result.kept_records] == [1083, 1085]
    assert fit_ids == [1083, 1085]
    miss_row = next(
        row for row in result.audit_rows if row["market_map_job_id"] == 1084
    )
    assert miss_row["reject_reason"] == "JMM_JD_NOT_CACHED"
    assert miss_row["retryable"] is True
    assert miss_row["retry_reason"] == "JMM_JD_NOT_CACHED"
    assert result.error is None
    assert result.source_collection_complete is True


def test_jh313_multiple_409s_are_counted_and_skipped(monkeypatch, caplog):
    class MultipleCacheMissClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def get_readiness(self):
            return {
                "source_runs": {
                    "seek": {"status": "COMPLETE"},
                    "linkedin": {"status": "COMPLETE"},
                },
                "jd_coverage": {
                    "available": 1,
                    "missing_not_cached": 2,
                    "failed": 0,
                },
            }

        def search_page(self, **_kwargs):
            return _feed_page(
                items=[_item(i) for i in range(1083, 1086)],
                next_cursor=1085,
                has_more=False,
            )

        def get_cached_jd(self, *, jmm_job_id, identity_key):
            if jmm_job_id in {1083, 1084}:
                raise JobMarketMapJDNotCached(
                    "Job Market Map request failed: HTTP Error 409: Conflict: JD not cached yet"
                )
            return {
                "full_description": f"JD {jmm_job_id}",
                "jd_source": "jmm",
                "jd_fetched_at": "2026-09-14T00:00:00+00:00",
            }

    monkeypatch.setattr(
        market_map_source, "JobMarketMapClient", MultipleCacheMissClient
    )
    monkeypatch.setattr(
        market_map_source,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )
    monkeypatch.setattr(
        market_map_source,
        "review_post_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, []),
    )
    monkeypatch.setattr("job_hunter_agent.paths.get_active_user_id", lambda: "rob")

    with caplog.at_level("INFO", logger="job_hunter_agent.market_map_source"):
        result = source_runner._run_market_map_source(_market_context())

    misses = [
        row
        for row in result.audit_rows
        if row.get("reject_reason") == "JMM_JD_NOT_CACHED"
    ]
    assert len(misses) == 2
    assert [record["market_map_job_id"] for record in result.kept_records] == [1085]
    assert result.error is None
    assert result.source_collection_complete is True
    assert "not_cached=2" in caplog.text


def test_jh313_degraded_readiness_uses_existing_system_warning_surface(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        market_map_source,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    readiness = {
        "source_runs": {
            "seek": {
                "status": "PARTIAL_JD",
                "started_at": "2026-09-22T00:00:00+00:00",
            },
            "linkedin": {
                "status": "COMPLETE",
                "started_at": "2026-09-22T01:00:00+00:00",
            },
        },
        "jd_coverage": {
            "available": 100,
            "missing_not_cached": 7,
            "failed": 2,
        },
    }

    market_map_source._record_jmm_readiness(readiness, run_id="run-313")

    assert len(warnings) == 1
    assert warnings[0]["category"] == "jmm_readiness"
    assert warnings[0]["severity"] == "warning"
    assert warnings[0]["context"]["jd_coverage"]["missing_not_cached"] == 7


def test_jh313_readiness_client_reads_get_only():
    requests = []

    def opener(request, **_kwargs):
        requests.append((request.get_method(), request.full_url))
        return _Response(
            {
                "api_version": "v3",
                "schema_version": 12,
                "source_runs": {
                    "seek": {"status": "COMPLETE"},
                    "linkedin": {"status": "COMPLETE"},
                },
                "jd_coverage": {
                    "available": 100,
                    "missing_not_cached": 7,
                    "failed": 2,
                },
            }
        )

    client = JobMarketMapClient("https://jmm.example/v3", opener=opener)

    payload = client.get_readiness()

    assert payload["jd_coverage"]["failed"] == 2
    assert requests == [("GET", "https://jmm.example/v3/readiness")]
