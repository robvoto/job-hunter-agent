"""JH-306 Job Market Map consumer contract tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from job_hunter_agent import market_map_source, run_context, source_runner
from job_hunter_agent.job_market_map_client import (
    JobMarketMapClient,
    JobMarketMapContractError,
    JobMarketMapUnavailable,
)
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


def _feed_page(*, items, next_cursor: int, has_more: bool) -> dict:
    return {
        "api_version": "v3",
        "schema_version": 6,
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
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
    assert client.get_or_enrich_jd(jmm_job_id=9)["jd_source"] == "seek_job_page"
    assert requests == [
        ("GET", "https://jmm.example/v3/jobs/lookup?identity_key=seek%3Aid%3A9"),
        ("POST", "https://jmm.example/v3/jobs/9/jd"),
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
        invalid_jd_client.get_or_enrich_jd(jmm_job_id=9)


def test_market_record_keeps_jmm_identity_without_copying_jd():
    record = market_map_source.normalize_market_job(
        _item(7, full_description="Do not copy"), run_iso="2026-09-11T12:00:00+00:00"
    )

    assert record["job_key"] == "seek:7"
    assert record["market_map_identity_key"] == "seek:id:7"
    assert record["market_map_job_id"] == 7
    assert record["full_description"] == ""


def test_market_source_requests_current_jd_and_checkpoints_per_user(monkeypatch):
    pages = iter(
        [
            _feed_page(items=[_item(1)], next_cursor=1, has_more=True),
            _feed_page(
                items=[_item(2, full_description="Current canonical JD")],
                next_cursor=2,
                has_more=False,
            ),
        ]
    )
    jd_calls: list[int] = []
    checkpoints: list[tuple[str, int]] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
            return next(pages)

        def get_or_enrich_jd(self, *, jmm_job_id):
            jd_calls.append(jmm_job_id)
            return {
                "full_description": "Enriched canonical JD",
                "jd_source": "seek_job_page",
                "jd_fetched_at": "2026-09-11T12:01:00+00:00",
            }

        def checkpoint(self, *, consumer_key, last_job_id, **_kwargs):
            checkpoints.append((consumer_key, last_job_id))
            return {"consumer_key": consumer_key, "last_job_id": last_job_id}

    def pre(record, _context):
        return ({"decision": "KEEP"}, record, [], True)

    def post(record, _context):
        return ({"decision": "KEEP"}, record, [])

    monkeypatch.setattr(market_map_source, "JobMarketMapClient", FakeClient)
    monkeypatch.setattr(market_map_source, "review_pre_detail_normalized_job", pre)
    monkeypatch.setattr(market_map_source, "review_post_detail_normalized_job", post)
    context = SimpleNamespace(
        profile={},
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )

    kept, audit, _skills = market_map_source.run_market_map_source(context, user_id="rob")

    assert jd_calls == [1, 2]
    assert checkpoints == [("job-hunter:rob", 1), ("job-hunter:rob", 2)]
    assert audit == []
    assert len(kept) == 2
    assert all("full_description" not in record for record in kept)
    assert all("details_text" not in record for record in kept)


def test_market_source_does_not_checkpoint_a_page_after_analysis_failure(monkeypatch):
    checkpoints: list[int] = []

    class FailedAnalysisClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
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
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )

    with pytest.raises(RuntimeError, match="analysis failed"):
        market_map_source.run_market_map_source(context, user_id="rob")

    assert checkpoints == []


def test_normal_runtime_builds_a_jmm_only_context(monkeypatch):
    profile = {"enabled_sources": ["seek"]}
    monkeypatch.setattr(run_context, "load_profile", lambda: profile)
    monkeypatch.setattr(run_context, "get_search_settings", lambda _profile: {})
    monkeypatch.setattr(run_context, "get_workspace_minimum_score", lambda: 50)
    monkeypatch.setattr(run_context, "get_globally_enabled_sources", lambda: ["seek"])
    monkeypatch.setattr(
        run_context,
        "run_retention_housekeeping",
        lambda *_args: (set(), set()),
    )
    monkeypatch.setattr(run_context, "load_job_history", lambda: {})
    monkeypatch.setattr(run_context, "load_audit_rows", lambda: [])
    monkeypatch.setattr(run_context, "load_run_stats", lambda: {})
    monkeypatch.setattr(run_context, "load_llm_cache", lambda: {})
    monkeypatch.setattr(run_context, "write_run_attempt", lambda *_args: None)
    monkeypatch.setattr(run_context, "has_cli_flag", lambda *_args: False)

    context = run_context.build_scrape_run_context([])

    assert context.use_market_map is True
    assert context.enabled_sources == ["job_market_map"]


def test_market_map_persistence_keeps_identity_without_jd_copy():
    from job_hunter_agent.history import finalize_record

    record = market_map_source.normalize_market_job(
        _item(8), run_iso="2026-09-11T12:00:00+00:00"
    )
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
