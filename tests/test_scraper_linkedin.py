"""Tests for scraper linkedin."""

from datetime import date
import logging
from types import SimpleNamespace

import pytest

from job_hunter_agent import job_quality
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.posting_utils import posted_display_label
from job_hunter_agent.salary import load_salary
from job_hunter_agent.scrapers.base import _build_salary_string
from job_hunter_agent.scrapers.linkedin import (
    LinkedInScraper,
    _fetch_jobspy_with_timeout,
    _extract_linkedin_job_header_evidence,
    classify_linkedin_apply_method,
)
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


def test_linkedin_detail_fetch_uses_canonical_vacancy_url(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    requested_urls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"canonical vacancy page"

    monkeypatch.setattr(
        linkedin_module,
        "urlopen",
        lambda request, timeout: requested_urls.append((request.full_url, timeout)) or _Response(),
    )

    record = {
        RECORD_URL_KEY: "https://www.linkedin.com/jobs/view/123",
        "source_metadata": {
            "raw_source_fields": {
                "job_url_direct": "https://employer.example/apply/123",
            }
        },
    }

    assert linkedin_module._fetch_job_html(record) == "canonical vacancy page"
    assert requested_urls == [(record[RECORD_URL_KEY], 20)]


def test_linkedin_detail_fetch_detects_closed_listing_signal(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-20T00:00:00+10:00",
    )

    monkeypatch.setattr(
        linkedin_module,
        "_fetch_job_html",
        lambda _record: (
            '<div class="job-details-jobs-unified-top-card__container">'
            "No longer accepting applications Reposted 2 days ago"
            "</div>"
        ),
    )

    signals = scraper._fetch_linkedin_detail_evidence({RECORD_URL_KEY: "https://example.com/job/1"})

    assert any(signal.get("kind") == job_quality.SIGNAL_KIND_JOB_CLOSED for signal in signals)


def test_linkedin_header_evidence_reads_only_current_vacancy_header():
    assert (
        _extract_linkedin_job_header_evidence(
            '<div class="job-details-jobs-unified-top-card__container">'
            "Posted 3 days ago"
            "</div>",
            date(2026, 6, 22),
        )["posted_age_days"]
        == 3.0
    )
    assert (
        _extract_linkedin_job_header_evidence(
            '<div class="job-details-jobs-unified-top-card__container">'
            "Reposted 3 hours ago"
            "</div>",
            date(2026, 6, 22),
        )["posted_age_days"]
        == pytest.approx(3 / 24)
    )


def test_linkedin_related_job_dates_do_not_contaminate_header_age():
    evidence = _extract_linkedin_job_header_evidence(
        """
        <main>
          <div class="job-details-jobs-unified-top-card__container">
            <h1>Business Analyst</h1>
            <span>Posted 3 days ago</span>
          </div>
          <aside class="jobs-search-results-list">
            <article>Recommended role — Posted 60 days ago</article>
          </aside>
        </main>
        """,
        date(2026, 6, 22),
    )

    assert evidence["posted_age_days"] == 3.0
    assert evidence["is_reposted"] is False


def test_linkedin_explicit_repost_is_recorded_without_external_apply_page(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-20T00:00:00+10:00",
    )
    monkeypatch.setattr(
        linkedin_module,
        "_fetch_job_html",
        lambda _record: (
            '<div class="job-details-jobs-unified-top-card__container">'
            "Reposted 2 days ago"
            "</div>"
        ),
    )
    record = {
        RECORD_URL_KEY: "https://www.linkedin.com/jobs/view/1",
        "source_metadata": {
            "apply_url": "",
            "raw_source_fields": {
                "job_url_direct": "https://external.example/apply/1",
            },
        },
        "posted_age_days": 99.0,
    }

    signals = scraper._fetch_linkedin_detail_evidence(record)

    assert signals == []
    assert record["is_reposted"] is True
    assert record["posted_age_days"] == 2.0


def test_linkedin_closed_reposted_header_emits_hard_reject_signal(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-20T00:00:00+10:00",
    )
    monkeypatch.setattr(
        linkedin_module,
        "_fetch_job_html",
        lambda _record: (
            '<div class="job-details-jobs-unified-top-card__container">'
            "No longer accepting applications · Reposted 2 days ago"
            "</div>"
        ),
    )
    record = {RECORD_URL_KEY: "https://www.linkedin.com/jobs/view/1"}

    signals = scraper._fetch_linkedin_detail_evidence(record)

    assert signals and signals[0]["kind"] == job_quality.SIGNAL_KIND_JOB_CLOSED
    assert record["is_reposted"] is True


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
        lambda _record: (
            '<div class="job-details-jobs-unified-top-card__container">'
            "Posted 3 hours ago"
            "</div>"
        ),
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
    monkeypatch.setattr(linkedin_module, "load_job_type", lambda: {})
    monkeypatch.setattr(linkedin_module, "load_salary", lambda: {})
    caplog.set_level(logging.DEBUG, logger="job_hunter_agent.scrapers.linkedin")

    kept_records, audit_rows, skill_observations = scraper.scrape()

    assert not audit_rows
    assert not skill_observations
    assert kept_records[0]["posted_age_days"] == pytest.approx(3 / 24)
    assert posted_display_label(kept_records[0]) == "22 Jun 2026"
    assert "STARTING LINKEDIN TARGET 1/1" in caplog.text
    assert "jobspy fetch start" in caplog.text
    assert "jobspy fetch done" in caplog.text


def test_linkedin_search_targets_include_distinct_profile_roles():
    scraper = LinkedInScraper(
        profile={
            "target_roles": ["Scrum Master"],
            "also_consider_roles": ["Agile Project Coordinator"],
        },
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    targets = scraper._build_search_targets({"keywords": "scrum master", "locations": ["Sydney"]})

    assert [target["search_term"] for target in targets] == [
        "Scrum Master",
        "Agile Project Coordinator",
    ]


def test_linkedin_search_plan_prunes_trusted_redundant_role_target(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
        search_plan_signature="signature-1",
    )
    targets = [
        {
            "search_term": "Role A",
            "location": "Sydney, Australia",
            "results_wanted": 1,
            "hours_old": 24,
            "sort_newest_first": False,
            "easy_apply": None,
        },
        {
            "search_term": "Role B",
            "location": "Sydney, Australia",
            "results_wanted": 1,
            "hours_old": 24,
            "sort_newest_first": False,
            "easy_apply": None,
        },
    ]
    monkeypatch.setattr(scraper, "_build_search_targets", lambda _settings: targets)
    monkeypatch.setattr(linkedin_module, "load_search_plan_state", lambda **_kwargs: {})
    monkeypatch.setattr(
        linkedin_module,
        "planned_search_terms",
        lambda *_args, **_kwargs: (["Role B"], "remembered"),
    )
    monkeypatch.setattr(linkedin_module, "get_search_plan_min_corroboration_samples", lambda: 2)
    monkeypatch.setattr(linkedin_module, "get_search_plan_max_age_minutes", lambda: 10080)
    fetched_terms: list[str] = []
    monkeypatch.setattr(scraper, "_fetch_jobspy", lambda target: fetched_terms.append(target["search_term"]))

    scraper.scrape()

    assert fetched_terms == ["Role B"]
    assert scraper.discovery_status["total_targets"] == 1
    assert scraper.discovery_status["attempted_targets"] == 1


def test_linkedin_jobspy_fetch_stops_immediately_when_run_stop_requested(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    class _FakeConn:
        def close(self):
            return None

        def poll(self, _timeout):
            return False

        def recv(self):
            raise AssertionError("recv should not be reached after stop request")

    class _FakeWorker:
        def __init__(self):
            self.terminated = False
            self.exitcode = None

        def start(self):
            return None

        def join(self, _timeout):
            return None

        def is_alive(self):
            return not self.terminated

        def terminate(self):
            self.terminated = True

    class _FakeContext:
        def __init__(self):
            self.recv_conn = _FakeConn()
            self.send_conn = _FakeConn()
            self.worker = _FakeWorker()

        def Pipe(self, duplex=False):
            assert duplex is False
            return self.recv_conn, self.send_conn

        def Process(self, **_kwargs):
            return self.worker

    monkeypatch.setattr(
        linkedin_module.multiprocessing,
        "get_context",
        lambda _name: _FakeContext(),
    )
    monkeypatch.setattr(linkedin_module, "run_stop_requested", lambda: True)

    with pytest.raises(InterruptedError, match="cancelled due to stop request"):
        _fetch_jobspy_with_timeout({"search_term": "project manager"}, timeout_seconds=20.0)


def test_linkedin_deduplicates_cards_across_multiple_search_targets(monkeypatch):
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
                "search_term": "scrum master",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 168,
                "sort_newest_first": False,
                "easy_apply": None,
            },
            {
                "search_term": "agile project coordinator",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 168,
                "sort_newest_first": False,
                "easy_apply": None,
            },
        ],
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_jobspy",
        lambda _target: _Rows(
            [
                {
                    "id": "li-1",
                    "title": "Scrum Master",
                    "company": "Example Co",
                    "location": "Sydney",
                    "job_url": "https://www.linkedin.com/jobs/view/1",
                    "description": "Example description",
                }
            ]
        ),
    )
    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", lambda _record: [])
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

    kept_records, audit_rows, skill_observations = scraper.scrape()

    assert len(kept_records) == 1
    assert kept_records[0]["job_key"] == "linkedin:li-1"
    assert audit_rows == []
    assert skill_observations == []


def test_linkedin_step_through_pauses_on_rejected_jobs(monkeypatch):
    from job_hunter_agent import job_review_pipeline
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

    pause_calls: list[str] = []
    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    monkeypatch.setattr(
        job_review_pipeline,
        "pause_for_step_through",
        lambda label: pause_calls.append(label),
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
    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", lambda _record: [])
    monkeypatch.setattr(
        linkedin_module,
        "review_pre_detail_normalized_job",
        lambda record, _context: (
            {"decision": "REJECT", "reject_reason": "TITLE_EMPTY"},
            record,
            [],
            False,
        ),
    )
    monkeypatch.setattr(
        linkedin_module,
        "review_post_detail_normalized_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected detail review")),
    )
    monkeypatch.setattr(linkedin_module, "load_job_type", lambda: {})
    monkeypatch.setattr(linkedin_module, "load_salary", lambda: {})

    kept_records, audit_rows, skill_observations = scraper.scrape()

    assert kept_records == []
    assert audit_rows == []
    assert skill_observations == []
    assert pause_calls == []


def test_linkedin_stops_processing_rows_after_stop_request(monkeypatch):
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

    stop_requested = {"value": False}
    fetched_terms: list[str] = []
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
                "search_term": "scrum master",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 24,
                "sort_newest_first": False,
                "easy_apply": None,
            },
            {
                "search_term": "project manager",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 24,
                "sort_newest_first": False,
                "easy_apply": None,
            },
        ],
    )

    def _fake_fetch(target):
        fetched_terms.append(target["search_term"])
        return _Rows(
            [
                {
                    "id": "li-1",
                    "title": "Scrum Master",
                    "company": "Example Co",
                    "location": "Sydney",
                    "job_url": "https://www.linkedin.com/jobs/view/1",
                    "description": "Example description",
                }
            ]
        )

    monkeypatch.setattr(scraper, "_fetch_jobspy", _fake_fetch)
    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", lambda _record: [])
    monkeypatch.setattr(linkedin_module, "run_stop_requested", lambda: stop_requested["value"])
    monkeypatch.setattr(
        linkedin_module,
        "review_pre_detail_normalized_job",
        lambda record, _context: ({"decision": "KEEP"}, record, [], True),
    )

    reviewed_terms: list[str] = []

    def _fake_review(record, _context, hooks=None):
        reviewed_terms.append(record["search_keywords"])
        stop_requested["value"] = True
        return {"decision": "KEEP"}, record, []

    monkeypatch.setattr(linkedin_module, "review_post_detail_normalized_job", _fake_review)

    kept_records, _, _ = scraper.scrape()

    # Both targets' jobspy fetches may run concurrently (bounded prefetch), but once
    # the stop request fires during target 1's row review, target 2's rows must never
    # be reviewed/kept.
    assert len(kept_records) == 1
    assert reviewed_terms == ["scrum master"]


def test_linkedin_prefetches_targets_concurrently_bounded_by_setting(monkeypatch):
    import threading
    import time as time_module

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

    num_targets = 4
    configured_workers = 2
    scraper = LinkedInScraper(
        profile={"search_settings": {"linkedin_parallel_search_workers": configured_workers}},
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
                "search_term": f"role-{idx}",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 168,
                "sort_newest_first": False,
                "easy_apply": None,
            }
            for idx in range(num_targets)
        ],
    )

    concurrency_lock = threading.Lock()
    in_flight = {"current": 0, "peak": 0}

    def _fake_fetch(target):
        idx = int(target["search_term"].split("-")[1])
        with concurrency_lock:
            in_flight["current"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        try:
            # Hold the "fetch" open briefly so overlapping submissions have a
            # chance to run concurrently rather than racing straight through.
            time_module.sleep(0.05)
        finally:
            with concurrency_lock:
                in_flight["current"] -= 1
        return _Rows(
            [
                {
                    "id": f"li-{idx}",
                    "title": f"Role {idx}",
                    "company": "Example Co",
                    "location": "Sydney",
                    "job_url": f"https://www.linkedin.com/jobs/view/{idx}",
                    "description": "Example description",
                }
            ]
        )

    monkeypatch.setattr(scraper, "_fetch_jobspy", _fake_fetch)
    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", lambda _record: [])
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

    kept_records, _, _ = scraper.scrape()

    # Results must stay in original target order regardless of fetch/completion
    # timing, and at least two fetches must have genuinely overlapped in time,
    # proving the configured worker cap is actually used for real concurrency
    # (not just accepted and ignored).
    assert [record["job_key"] for record in kept_records] == [
        f"linkedin:li-{idx}" for idx in range(num_targets)
    ]
    assert in_flight["peak"] >= configured_workers


def test_linkedin_scrape_isolates_failed_target_fetch(monkeypatch):
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
                "search_term": "flaky target",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 168,
                "sort_newest_first": False,
                "easy_apply": None,
            },
            {
                "search_term": "healthy target",
                "location": "Sydney, Australia",
                "results_wanted": 1,
                "hours_old": 168,
                "sort_newest_first": False,
                "easy_apply": None,
            },
        ],
    )

    def _fake_fetch(target):
        if target["search_term"] == "flaky target":
            raise RuntimeError("jobspy blew up")
        return _Rows(
            [
                {
                    "id": "li-healthy",
                    "title": "Healthy Role",
                    "company": "Example Co",
                    "location": "Sydney",
                    "job_url": "https://www.linkedin.com/jobs/view/healthy",
                    "description": "Example description",
                }
            ]
        )

    monkeypatch.setattr(scraper, "_fetch_jobspy", _fake_fetch)
    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", lambda _record: [])
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

    kept_records, _, _ = scraper.scrape()

    assert len(kept_records) == 1
    assert kept_records[0]["job_key"] == "linkedin:li-healthy"


def test_fetch_jobspy_with_timeout_uses_timeout_worker(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    captured: dict[str, object] = {}

    monkeypatch.setattr(linkedin_module, "get_linkedin_fetch_timeout_seconds", lambda: 40.0)
    monkeypatch.setattr(
        linkedin_module,
        "_fetch_jobspy_with_timeout",
        lambda search_params, timeout_seconds: captured.update(
            {"search_params": search_params, "timeout_seconds": timeout_seconds}
        )
        or SimpleNamespace(),
    )

    scraper = LinkedInScraper(
        profile={"search_settings": {"linkedin_fetch_timeout_seconds": 20}},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )
    scraper._fetch_jobspy(
        {
            "search_term": "project manager",
            "location": "Sydney, Australia",
            "distance": 50,
            "results_wanted": 25,
            "hours_old": 24,
            "easy_apply": None,
        }
    )

    assert captured["timeout_seconds"] == 20.0
    assert captured["search_params"]["search_term"] == "project manager"
    assert captured["search_params"]["linkedin_fetch_description"] is False


def test_linkedin_progress_producer_emits_target_and_job_counts(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        linkedin_module,
        "set_run_progress_state",
        lambda text, **detail: captured.append((text, detail)),
    )

    linkedin_module._set_linkedin_run_progress(
        2,
        7,
        row_index=4,
        total_rows=6,
    )

    text, detail = captured[-1]
    assert text == "LinkedIn target 2/7\nReviewing job 4/6"
    assert detail == {
        "stage": "source_collection",
        "source": "linkedin",
        "headline": "LinkedIn target 2 of 7",
        "detail": "Reviewing job 4 of 6",
        "current": 2,
        "total": 7,
        "item_current": 4,
        "item_total": 6,
    }


def _target(term: str, **overrides) -> dict:
    target = {
        "search_term": term,
        "location": "Sydney, Australia",
        "results_wanted": 1,
        "hours_old": 168,
        "sort_newest_first": False,
        "easy_apply": None,
    }
    target.update(overrides)
    return target


class _EmptyRows:
    def sort_values(self, **_kwargs):
        return self

    def iterrows(self):
        return iter(())

    def __len__(self):
        return 0


def test_linkedin_healthy_search_with_zero_rows_is_not_a_failure(monkeypatch):
    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    monkeypatch.setattr(scraper, "_build_search_targets", lambda _settings: [_target("no results role")])
    monkeypatch.setattr(scraper, "_fetch_jobspy", lambda _target: _EmptyRows())

    kept_records, audit_rows, skill_observations = scraper.scrape()

    assert kept_records == []
    assert audit_rows == []
    assert skill_observations == []
    assert scraper.discovery_status["final_status"] == "healthy"
    assert scraper.discovery_status["succeeded_targets"] == 1
    assert scraper.discovery_status["failed_targets"] == 0
    assert scraper.discovery_status["attempted_targets"] == 1


def test_linkedin_timeout_increments_failure_counters(monkeypatch):
    scraper = LinkedInScraper(
        profile={},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    monkeypatch.setattr(scraper, "_build_search_targets", lambda _settings: [_target("slow role")])

    def _fake_fetch(_target):
        raise TimeoutError("LinkedIn jobspy fetch exceeded 20s for 'slow role'")

    monkeypatch.setattr(scraper, "_fetch_jobspy", _fake_fetch)

    kept_records, _, _ = scraper.scrape()

    assert kept_records == []
    assert scraper.discovery_status["timed_out_targets"] == 1
    assert scraper.discovery_status["failed_targets"] == 1
    assert scraper.discovery_status["succeeded_targets"] == 0
    assert scraper.discovery_status["final_status"] == "full_failure"
    assert scraper.discovery_status["complete"] is False


def test_linkedin_circuit_breaker_trips_and_skips_remaining_targets(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    scraper = LinkedInScraper(
        profile={"search_settings": {"linkedin_parallel_search_workers": 1}},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    monkeypatch.setattr(
        linkedin_module,
        "get_linkedin_max_consecutive_target_failures",
        lambda: 2,
    )
    monkeypatch.setattr(
        scraper,
        "_build_search_targets",
        lambda _settings: [_target(f"role-{idx}") for idx in range(5)],
    )

    fetched_terms: list[str] = []

    def _fake_fetch(target):
        fetched_terms.append(target["search_term"])
        if target["search_term"] in {"role-0", "role-1"}:
            raise TimeoutError(f"timed out for {target['search_term']!r}")
        return _EmptyRows()

    monkeypatch.setattr(scraper, "_fetch_jobspy", _fake_fetch)

    kept_records, _, _ = scraper.scrape()

    assert kept_records == []
    # Targets 3 and 4 must never even be submitted once the breaker trips after
    # two consecutive failures (role-0, role-1); only role-2, already in flight
    # when the breaker tripped, is drained.
    assert fetched_terms == ["role-0", "role-1", "role-2"]
    status = scraper.discovery_status
    assert status["circuit_breaker_tripped"] is True
    assert status["attempted_targets"] == 3
    assert status["failed_targets"] == 2
    assert status["timed_out_targets"] == 2
    assert status["succeeded_targets"] == 1
    assert status["skipped_after_breaker"] == 2
    assert status["final_status"] == "partial_failure"


def test_linkedin_partial_success_preserves_kept_jobs_after_later_failure(monkeypatch):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    scraper = LinkedInScraper(
        profile={"search_settings": {"linkedin_parallel_search_workers": 1}},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-06-22T09:00:00+10:00",
    )

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def sort_values(self, **_kwargs):
            return self

        def iterrows(self):
            return enumerate(self._rows)

        def __len__(self):
            return len(self._rows)

    monkeypatch.setattr(
        scraper,
        "_build_search_targets",
        lambda _settings: [_target("healthy role"), _target("flaky role")],
    )

    def _fake_fetch(target):
        if target["search_term"] == "flaky role":
            raise TimeoutError("timed out for 'flaky role'")
        return _Rows(
            [
                {
                    "id": "li-healthy",
                    "title": "Healthy Role",
                    "company": "Example Co",
                    "location": "Sydney",
                    "job_url": "https://www.linkedin.com/jobs/view/healthy",
                    "description": "Example description",
                }
            ]
        )

    monkeypatch.setattr(scraper, "_fetch_jobspy", _fake_fetch)
    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", lambda _record: [])
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

    kept_records, _, _ = scraper.scrape()

    assert len(kept_records) == 1
    assert kept_records[0]["job_key"] == "linkedin:li-healthy"
    status = scraper.discovery_status
    assert status["succeeded_targets"] == 1
    assert status["failed_targets"] == 1
    assert status["final_status"] == "partial_failure"
    assert status["complete"] is False


def test_linkedin_header_is_captured_before_pre_detail_rejection(monkeypatch):
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

    monkeypatch.setattr(scraper, "_build_search_targets", lambda _settings: [_target("analyst")])
    monkeypatch.setattr(
        scraper,
        "_fetch_jobspy",
        lambda _target: _Rows(
            [
                {
                    "id": "li-rejected",
                    "title": "",
                    "company": "Example Co",
                    "location": "Sydney",
                    "job_url": "https://www.linkedin.com/jobs/view/1",
                }
            ]
        ),
    )

    detail_fetches = []
    monkeypatch.setattr(
        scraper,
        "_fetch_linkedin_detail_evidence",
        lambda record: detail_fetches.append(record) or [],
    )
    monkeypatch.setattr(
        linkedin_module,
        "review_pre_detail_normalized_job",
        lambda record, _context: (
            {"decision": "REJECT", "reject_reason": "TITLE_EMPTY"},
            record,
            [],
            False,
        ),
    )
    monkeypatch.setattr(
        linkedin_module,
        "review_post_detail_normalized_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected detail review")),
    )

    kept_records, _, _ = scraper.scrape()

    assert kept_records == []
    assert len(detail_fetches) == 1


def test_linkedin_duplicate_native_id_causes_single_detail_fetch(monkeypatch):
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

    def _row():
        return {
            "id": "li-dup",
            "title": "Scrum Master",
            "company": "Example Co",
            "location": "Sydney",
            "job_url": "https://www.linkedin.com/jobs/view/1",
        }

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
        lambda _settings: [_target("scrum master"), _target("agile lead")],
    )
    monkeypatch.setattr(scraper, "_fetch_jobspy", lambda _target: _Rows([_row()]))

    detail_fetch_calls: list[str] = []

    def _fake_detail_fetch(record):
        detail_fetch_calls.append(record.get("job_key"))
        return []

    monkeypatch.setattr(scraper, "_fetch_linkedin_detail_evidence", _fake_detail_fetch)
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

    kept_records, _, _ = scraper.scrape()

    # Both target rows share the same native LinkedIn id: the second occurrence must
    # be dropped by native-ID dedup before it ever reaches the detail fetch, so only
    # the surviving first occurrence causes a (single) expensive detail-fetch path.
    assert len(kept_records) == 1
    assert detail_fetch_calls == ["linkedin:li-dup"]


def test_extract_linkedin_description_reads_show_more_less_markup():
    from job_hunter_agent.scrapers.linkedin import _extract_linkedin_description

    html = (
        "<html><body><div class=\"description__text\">"
        '<div class="show-more-less-html__markup">'
        "<p>We are looking for a <strong>Scrum Master</strong>.</p>"
        "<p>5+ years experience required.</p>"
        "</div></div></body></html>"
    )

    assert _extract_linkedin_description(html) == (
        "We are looking for a Scrum Master . 5+ years experience required."
    )


def test_extract_linkedin_description_stops_after_markup_with_void_tags_before_it():
    from job_hunter_agent.scrapers.linkedin import _extract_linkedin_description

    html = (
        "<html><head><meta charset='utf-8'><link rel='stylesheet'></head>"
        "<body><input type='hidden'>"
        '<div class="description__text"><section class="show-more-less-html">'
        '<div class="show-more-less-html__markup">'
        "<p>The actual job description.</p>"
        "</div></section></div>"
        "<footer>Similar jobs and LinkedIn sign-in content.</footer>"
        "</body></html>"
    )

    assert _extract_linkedin_description(html) == "The actual job description."


def test_extract_linkedin_job_url_direct_reads_apply_code_element():
    from job_hunter_agent.scrapers.linkedin import _extract_linkedin_job_url_direct

    html = (
        '<code id="applyUrl" style="display: none">'
        '"https://www.linkedin.com/job-apply/redirect?url='
        'https%3A%2F%2Femployer.example.com%2Fcareers%2F123"'
        "</code>"
    )

    assert _extract_linkedin_job_url_direct(html) == "https://employer.example.com/careers/123"


def test_fetch_jobspy_with_timeout_surfaces_jobspy_notices_as_warnings(monkeypatch, caplog):
    from job_hunter_agent.scrapers import linkedin as linkedin_module

    class _FakeConn:
        def __init__(self, payload=None):
            self._payload = payload

        def close(self):
            return None

        def poll(self, _timeout):
            return True

        def recv(self):
            return self._payload

    class _FakeWorker:
        def start(self):
            return None

        def join(self, _timeout):
            return None

        def is_alive(self):
            return False

    class _FakeContext:
        def __init__(self):
            self.recv_conn = _FakeConn(
                ("ok", SimpleNamespace(), ["429 Response - Blocked by LinkedIn"])
            )
            self.send_conn = _FakeConn()
            self.worker = _FakeWorker()

        def Pipe(self, duplex=False):
            assert duplex is False
            return self.recv_conn, self.send_conn

        def Process(self, **_kwargs):
            return self.worker

    monkeypatch.setattr(
        linkedin_module.multiprocessing, "get_context", lambda _name: _FakeContext()
    )
    caplog.set_level(logging.WARNING, logger="job_hunter_agent.scrapers.linkedin")

    result = _fetch_jobspy_with_timeout({"search_term": "project manager"}, timeout_seconds=20.0)

    assert isinstance(result, SimpleNamespace)
    assert "429 Response - Blocked by LinkedIn" in caplog.text
