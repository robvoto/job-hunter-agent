"""JH-306 Job Market Map consumer contract tests."""

from __future__ import annotations

import json
import threading
import time
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from job_hunter_agent import market_map_source, run_context, run_control, source_runner
from job_hunter_agent.job_market_map_client import (
    JobMarketMapClient,
    JobMarketMapContractError,
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
) -> dict:
    return {
        "api_version": "v3",
        "schema_version": 6,
        "snapshot_max_id": next_cursor if snapshot_max_id is None else snapshot_max_id,
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
        jd_error_client.get_or_enrich_jd(jmm_job_id=1084)

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
        terminal_jd_client.get_or_enrich_jd(jmm_job_id=1084)


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
            _feed_page(
                items=[_item(1)],
                next_cursor=1,
                has_more=True,
                snapshot_max_id=2,
            ),
            _feed_page(
                items=[_item(2, full_description="Current canonical JD")],
                next_cursor=2,
                has_more=False,
                snapshot_max_id=2,
            ),
        ]
    )
    jd_calls: list[int] = []
    checkpoints: list[tuple[str, int]] = []
    feed_calls: list[tuple[str, int | None]] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, through_id=None, **_kwargs):
            feed_calls.append((consumer_key, through_id))
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
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )

    try:
        kept, audit, _skills = market_map_source.run_market_map_source(context, user_id="rob")
        final_progress_detail = run_control.get_run_progress_detail()
    finally:
        run_control.clear_run_progress()

    assert feed_calls == [("job-hunter:rob", None), ("job-hunter:rob", 2)]
    assert jd_calls == [1, 2]
    assert checkpoints == [("job-hunter:rob", 1), ("job-hunter:rob", 2)]
    assert [row["job_key"] for row in audit] == ["seek:1", "seek:2"]
    assert len(kept) == 2
    assert all("full_description" not in record for record in kept)
    assert all("details_text" not in record for record in kept)
    assert final_progress_detail == progress_states[-1]
    assert final_progress_detail["source"] == "job_market_map"
    assert [detail["headline"] for detail in progress_states] == [
        "Starting JMM",
        "Reading JMM jobs",
        "Reviewing job 1 of page 1",
        "Obtaining job descriptions",
        "Obtaining job description",
        "Fit review",
        "Finalising JMM results",
        "Finalising JMM results",
        "Checkpointing JMM progress",
        "Reading JMM jobs",
        "Reviewing job 1 of page 2",
        "Obtaining job descriptions",
        "Obtaining job description",
        "Fit review",
        "Finalising JMM results",
        "Finalising JMM results",
        "Checkpointing JMM progress",
        "JMM source complete",
    ]
    review_progress = progress_states[2]
    assert review_progress["current"] == 1
    assert review_progress["total"] == 1
    assert review_progress["determinate"] is True


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


def test_jmm_jd_502_preserves_completed_results_and_marks_job_retryable(monkeypatch):
    checkpoints: list[int] = []

    class FailedJdClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
            return _feed_page(items=[_item(i) for i in range(1083, 1086)], next_cursor=1085, has_more=False)

        def get_or_enrich_jd(self, *, jmm_job_id):
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


def test_jmm_jd_410_skips_terminal_job_and_checkpoints_completed_page(monkeypatch):
    checkpoints: list[int] = []

    class TerminalJdClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
            return _feed_page(items=[_item(i) for i in range(1083, 1086)], next_cursor=1085, has_more=False)

        def get_or_enrich_jd(self, *, jmm_job_id):
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
    assert checkpoints == [1085]


def _market_context(profile=None):
    return SimpleNamespace(
        profile=profile or {},
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-09-11T12:00:00+00:00",
        configured_date_range=3,
        identity_registry=None,
    )


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

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
            return _feed_page(items=items, next_cursor=4, has_more=False)

        def get_or_enrich_jd(self, *, jmm_job_id):
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

    kept, audit, _skills = market_map_source.run_market_map_source(
        _market_context(), user_id="rob"
    )

    assert maximum == {"title": 2, "jd": 2, "fit": 2}
    assert [record["job_key"] for record in kept] == [f"seek:{i}" for i in range(1, 5)]
    assert [row["job_key"] for row in audit] == [f"seek:{i}" for i in range(1, 5)]
    assert checkpoints == [4]


def test_market_source_stop_cancels_queued_jmm_work(monkeypatch):
    stop = threading.Event()
    jd_calls: list[int] = []
    checkpoints: list[int] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
            return _feed_page(items=[_item(i) for i in range(1, 5)], next_cursor=4, has_more=False)

        def get_or_enrich_jd(self, *, jmm_job_id):
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

    market_map_source.run_market_map_source(_market_context(), user_id="rob")

    assert jd_calls == [1]
    assert checkpoints == []


def test_market_source_worker_failure_does_not_mutate_shared_state_or_checkpoint(monkeypatch):
    completed: list[int] = []
    checkpoints: list[int] = []

    class FakeClient:
        @classmethod
        def from_environment(cls):
            return cls()

        def consumer_feed_page(self, *, consumer_key, **_kwargs):
            return _feed_page(items=[_item(i) for i in range(1, 4)], next_cursor=3, has_more=False)

        def get_or_enrich_jd(self, *, jmm_job_id):
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
        market_map_source.run_market_map_source(context, user_id="rob")

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
    assert context.enabled_sources == ["job_market_map"]
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
