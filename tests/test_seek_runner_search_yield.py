"""Coverage for SEEK's cross-search-term job dedup and query-yield metrics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import job_hunter_agent.record_schema as rs
from job_hunter_agent.scrapers import seek_runner


class _FakeCard:
    def __init__(self, job_key: str):
        self.job_key = job_key


class _FakeListPage:
    def __init__(self, cards_by_target: dict[str, list[_FakeCard]]):
        self._cards_by_target = cards_by_target
        self.url = ""
        self.visited_urls: list[str] = []

    def goto(self, url, wait_until=None):
        self.url = url
        self.visited_urls.append(url)

    def wait_for_selector(self, *args, **kwargs):
        pass

    def query_selector_all(self, selector):
        for target_marker, cards in self._cards_by_target.items():
            if target_marker in self.url:
                return cards
        return []


class _FakeBrowserContext:
    def __init__(self, list_page: _FakeListPage):
        self._list_page = list_page

    def new_page(self):
        return self._list_page

    def add_init_script(self, *args, **kwargs):
        pass

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self, list_page: _FakeListPage):
        self._list_page = list_page

    def new_context(self, **kwargs):
        return _FakeBrowserContext(self._list_page)

    def close(self):
        pass


class _FakeChromium:
    def __init__(self, list_page: _FakeListPage):
        self._list_page = list_page

    def launch(self, **kwargs):
        return _FakeBrowser(self._list_page)


class _FakeSyncPlaywright:
    def __init__(self, list_page: _FakeListPage):
        self.chromium = _FakeChromium(list_page)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeDetailSession:
    def __init__(self, **kwargs):
        pass

    def run_batch(self, needs_detail, review_context):
        return {}

    def close(self):
        pass


def _fake_build_seek_card_record(card, search_target, run_iso, page_num, filter_state):
    return {
        rs.RECORD_JOB_KEY: card.job_key,
        rs.RECORD_TITLE_KEY: "Business Analyst",
        rs.RECORD_COMPANY_KEY: "Acme",
        rs.RECORD_POSTED_AGE_DAYS_KEY: 1,
    }


def _reject_all_pre_detail_batch(card_records, review_context, n_workers):
    pre_decided = [
        (i, ({"decision": "REJECT"}, record, [], 0.0)) for i, record in enumerate(card_records)
    ]
    return pre_decided, []


def _patch_common_seek_internals(monkeypatch, list_page: _FakeListPage):
    monkeypatch.setattr(seek_runner, "sync_playwright", lambda: _FakeSyncPlaywright(list_page))
    monkeypatch.setattr(seek_runner, "get_playwright_browser_mode", lambda: "ephemeral")
    monkeypatch.setattr(seek_runner, "WORKSPACE_DEBUG_MODE", False)
    monkeypatch.setattr(
        seek_runner, "_wait_for_seek_bot_challenge_or_manual_verification", lambda *a, **k: True
    )
    monkeypatch.setattr(seek_runner, "extract_seek_filter_panel_state", lambda page: {})
    monkeypatch.setattr(seek_runner, "build_seek_card_record", _fake_build_seek_card_record)
    monkeypatch.setattr(seek_runner, "_review_pre_detail_batch", _reject_all_pre_detail_batch)
    monkeypatch.setattr(seek_runner, "_AsyncDetailSession", _FakeDetailSession)


def _search_targets() -> list[dict]:
    return [
        {
            "url": "https://seek.example/search?target-a",
            "location": "New South Wales",
            "keywords": "Business Analyst",
            "classification_ids": [],
        },
        {
            "url": "https://seek.example/search?target-b",
            "location": "New South Wales",
            "keywords": "Senior Business Analyst",
            "classification_ids": [],
        },
    ]


def _base_scrape_kwargs(**overrides) -> dict:
    kwargs = dict(
        profile={"search_settings": {}},
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-08-15T09:00:00+00:00",
        configured_date_range=3,
        configured_seek_max_pages=1,
        playwright_viewport_width=1400,
        playwright_viewport_height=900,
        playwright_selector_timeout=8000,
        seek_manual_verification_timeout_ms=120000,
        seek_parallel_detail_workers=1,
        headless=True,
        assisted_verification_enabled=False,
    )
    kwargs.update(overrides)
    return kwargs


def test_seek_scrape_deduplicates_job_discovered_by_multiple_search_terms(monkeypatch):
    """A job surfaced by two different role-term targets must be captured once."""
    list_page = _FakeListPage(
        {
            "target-a": [_FakeCard("seek:shared"), _FakeCard("seek:only-a")],
            "target-b": [_FakeCard("seek:shared"), _FakeCard("seek:only-b")],
        }
    )
    _patch_common_seek_internals(monkeypatch, list_page)

    discovery_capture: list[dict] = []
    seek_runner.seek_scrape_to_records(
        **_base_scrape_kwargs(
            search_targets=_search_targets(),
            discovery_capture=discovery_capture,
        )
    )

    captured_keys = [record[rs.RECORD_JOB_KEY] for record in discovery_capture]
    assert captured_keys.count("seek:shared") == 1
    assert sorted(captured_keys) == ["seek:only-a", "seek:only-b", "seek:shared"]


def test_seek_scrape_records_query_yield_metric_per_search_target(monkeypatch):
    """Each source search target must emit one diagnostic query-yield metric."""
    list_page = _FakeListPage(
        {
            "target-a": [_FakeCard("seek:shared"), _FakeCard("seek:only-a")],
            "target-b": [_FakeCard("seek:shared"), _FakeCard("seek:only-b")],
        }
    )
    _patch_common_seek_internals(monkeypatch, list_page)

    recorded_metrics = []
    monkeypatch.setattr(
        seek_runner, "record_query_yield_metric", lambda metric: recorded_metrics.append(metric)
    )

    seek_runner.seek_scrape_to_records(
        **_base_scrape_kwargs(
            search_targets=_search_targets(),
            discovery_capture=[],
        )
    )

    assert len(recorded_metrics) == 2
    by_term = {metric.search_term: metric for metric in recorded_metrics}
    assert by_term["Business Analyst"].discovered_count == 2
    assert by_term["Business Analyst"].new_unique_job_count == 2
    assert by_term["Business Analyst"].duplicate_job_count == 0

    # target-b re-discovers the job already captured by target-a: one duplicate.
    assert by_term["Senior Business Analyst"].discovered_count == 2
    assert by_term["Senior Business Analyst"].new_unique_job_count == 1
    assert by_term["Senior Business Analyst"].duplicate_job_count == 1
    assert all(metric.success for metric in recorded_metrics)


def test_seek_owned_bot_challenge_does_not_enter_second_list_page_handler(monkeypatch):
    list_page = _FakeListPage({"target-a": [_FakeCard("seek:blocked")]})
    _patch_common_seek_internals(monkeypatch, list_page)
    handler_calls = []

    monkeypatch.setattr(
        seek_runner,
        "_wait_for_seek_bot_challenge_or_manual_verification",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            seek_runner.BotChallengeDetected(
                "SEEK partial — verification timed out",
                failure_class=seek_runner.SEEK_BOT_CHALLENGE,
            )
        ),
    )
    monkeypatch.setattr(
        seek_runner,
        "_handle_seek_list_page_failure",
        lambda *args, **kwargs: handler_calls.append(True) or True,
    )

    with pytest.raises(seek_runner.BotChallengeDetected):
        seek_runner.seek_scrape_to_records(
            **_base_scrape_kwargs(
                search_targets=[_search_targets()[0]],
                discovery_capture=[],
            )
        )

    assert handler_calls == []


def test_seek_scrape_attaches_partial_results_to_late_bot_challenge(monkeypatch):
    """A challenge after one target must carry completed review output upward."""
    list_page = _FakeListPage(
        {
            "target-a": [_FakeCard("seek:partial")],
            "target-b": [_FakeCard("seek:blocked")],
        }
    )
    _patch_common_seek_internals(monkeypatch, list_page)

    def _wait_for_challenge(page, *args, **kwargs):
        if "target-b" in page.url:
            raise seek_runner.BotChallengeDetected(
                "SEEK challenge after cards",
                failure_class=seek_runner.SEEK_BOT_CHALLENGE,
            )
        return True

    monkeypatch.setattr(
        seek_runner, "_wait_for_seek_bot_challenge_or_manual_verification", _wait_for_challenge
    )
    monkeypatch.setattr(
        seek_runner,
        "_log_seek_list_page_diagnostics",
        lambda *args, **kwargs: "challenge_page",
    )
    monkeypatch.setattr(
        seek_runner,
        "_seek_list_page_diagnostics",
        lambda page: {
            "title": "Just a moment",
            "url": page.url,
            "body_text": "confirm you are human",
            "selector_count": 0,
            "page_status": "challenge_page",
            "failure_class": seek_runner.SEEK_BOT_CHALLENGE,
        },
    )
    monkeypatch.setattr(
        seek_runner,
        "_review_pre_detail_batch",
        lambda card_records, review_context, n_workers: (
            [
                (i, ({"decision": "KEEP"}, record, [], 0.0))
                for i, record in enumerate(card_records)
            ],
            [],
        ),
    )

    try:
        seek_runner.seek_scrape_to_records(
            **_base_scrape_kwargs(
                profile={"target_roles": ["Business Analyst"], "search_settings": {}},
                search_targets=_search_targets(),
                discovery_capture=[],
            )
        )
    except seek_runner.BotChallengeDetected as exc:
        assert [record[rs.RECORD_JOB_KEY] for record in exc.kept_records] == ["seek:partial"]
        assert exc.audit_rows == []
    else:  # pragma: no cover - defensive guard
        raise AssertionError("expected BotChallengeDetected")


def test_seek_scrape_uses_remembered_all_probe_plan_for_deep_pagination(monkeypatch):
    """A remembered complete-probe plan, not query order, owns page-2 expansion."""
    list_page = _FakeListPage(
        {
            "target-a": [_FakeCard("seek:only-a")],
            "target-b": [_FakeCard("seek:only-b")],
        }
    )
    _patch_common_seek_internals(monkeypatch, list_page)
    monkeypatch.setattr(
        seek_runner,
        "load_search_plan_state",
        lambda **kwargs: {
            "probe_terms": ["Business Analyst", "Senior Business Analyst"],
            "selected_terms": ["Senior Business Analyst"],
            "sample_count": 2,
            "selection_counts": {"Senior Business Analyst": 2},
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    saved_observations: list[dict] = []
    monkeypatch.setattr(
        seek_runner,
        "save_search_plan_observation",
        lambda **kwargs: saved_observations.append(kwargs) or {"sample_count": 2},
    )
    recorded_metrics = []
    monkeypatch.setattr(
        seek_runner, "record_query_yield_metric", lambda metric: recorded_metrics.append(metric)
    )

    seek_runner.seek_scrape_to_records(
        **_base_scrape_kwargs(
            search_targets=_search_targets(),
            configured_seek_max_pages=2,
            discovery_capture=[],
            search_plan_signature="signature-1",
        )
    )

    by_term = {metric.search_term: metric for metric in recorded_metrics}
    assert by_term["Business Analyst"].pages_searched == 1
    assert by_term["Senior Business Analyst"].pages_searched == 2
    assert len(saved_observations) == 1
    assert saved_observations[0]["probe_terms"] == [
        "Business Analyst",
        "Senior Business Analyst",
    ]


def test_seek_uncorroborated_remembered_plan_expands_every_probed_term(monkeypatch):
    """A remembered plan with a matching probe set but too few corroborating
    observations must not be trusted to prune deeper pagination -- every
    configured term must still expand, exactly like the bootstrap case."""
    list_page = _FakeListPage(
        {
            "target-a": [_FakeCard("seek:only-a")],
            "target-b": [_FakeCard("seek:only-b")],
        }
    )
    _patch_common_seek_internals(monkeypatch, list_page)
    monkeypatch.setattr(
        seek_runner,
        "load_search_plan_state",
        lambda **kwargs: {
            "probe_terms": ["Business Analyst", "Senior Business Analyst"],
            "selected_terms": ["Senior Business Analyst"],
            "sample_count": 1,
            "selection_counts": {"Senior Business Analyst": 1},
        },
    )
    monkeypatch.setattr(
        seek_runner,
        "save_search_plan_observation",
        lambda **kwargs: {"sample_count": 2},
    )
    recorded_metrics = []
    monkeypatch.setattr(
        seek_runner, "record_query_yield_metric", lambda metric: recorded_metrics.append(metric)
    )

    seek_runner.seek_scrape_to_records(
        **_base_scrape_kwargs(
            search_targets=_search_targets(),
            configured_seek_max_pages=2,
            discovery_capture=[],
            search_plan_signature="signature-1",
        )
    )

    by_term = {metric.search_term: metric for metric in recorded_metrics}
    assert by_term["Business Analyst"].pages_searched == 2
    assert by_term["Senior Business Analyst"].pages_searched == 2


def test_seek_high_sample_count_does_not_substitute_for_selection_corroboration(monkeypatch):
    """A high cumulative sample_count is not real corroboration by itself.

    If observation 1 selected terms A+B and observation 2 selected different
    terms C+D, sample_count reaches 2 but neither C nor D has actually been
    picked more than once. The currently remembered selection (C+D) must
    therefore still be treated as untrusted and every probed term must
    expand -- pruning may only trust a selection once selection_counts shows
    that exact selection was repeated at least the configured threshold."""
    list_page = _FakeListPage(
        {
            "target-c": [_FakeCard("seek:only-c")],
            "target-d": [_FakeCard("seek:only-d")],
        }
    )
    _patch_common_seek_internals(monkeypatch, list_page)
    monkeypatch.setattr(
        seek_runner,
        "load_search_plan_state",
        lambda **kwargs: {
            "probe_terms": ["Term C", "Term D"],
            # Latest observation selected C+D, but the first observation (not
            # reflected in "selected_terms") selected different terms A+B --
            # so each of C and D has only ever been chosen once.
            "selected_terms": ["Term C", "Term D"],
            "sample_count": 2,
            "selection_counts": {"Term A": 1, "Term B": 1, "Term C": 1, "Term D": 1},
        },
    )
    monkeypatch.setattr(
        seek_runner,
        "save_search_plan_observation",
        lambda **kwargs: {"sample_count": 3},
    )
    recorded_metrics = []
    monkeypatch.setattr(
        seek_runner, "record_query_yield_metric", lambda metric: recorded_metrics.append(metric)
    )

    seek_runner.seek_scrape_to_records(
        **_base_scrape_kwargs(
            search_targets=[
                {
                    "url": "https://seek.example/search?target-c",
                    "location": "New South Wales",
                    "keywords": "Term C",
                    "classification_ids": [],
                },
                {
                    "url": "https://seek.example/search?target-d",
                    "location": "New South Wales",
                    "keywords": "Term D",
                    "classification_ids": [],
                },
            ],
            configured_seek_max_pages=2,
            discovery_capture=[],
            search_plan_signature="signature-1",
        )
    )

    by_term = {metric.search_term: metric for metric in recorded_metrics}
    assert by_term["Term C"].pages_searched == 2
    assert by_term["Term D"].pages_searched == 2


def test_seek_bootstrap_expands_every_probed_term_regardless_of_run_order(monkeypatch):
    """Before any plan has been remembered for a signature/location, every
    probed query term must expand past page 1 -- coverage must not depend on
    which term happened to execute first this run. Uses an unrelated nursing
    profile (not BA/IT) to prove the fix is generic, not title-pattern-specific."""
    profile = {"search_settings": {}, "target_roles": ["registered nurse"]}
    targets_by_key = {
        "a": {
            "url": "https://seek.example/search?target-a",
            "location": "Queensland",
            "keywords": "Registered Nurse",
            "classification_ids": [],
        },
        "b": {
            "url": "https://seek.example/search?target-b",
            "location": "Queensland",
            "keywords": "Enrolled Nurse",
            "classification_ids": [],
        },
    }

    def _fake_build_shared_nurse_card_record(card, search_target, run_iso, page_num, filter_state):
        # Both targets surface the same underlying job under their own
        # search term, so whichever term runs first "claims" the new-match
        # credit for it under the old (buggy) order-dependent bootstrap logic.
        return {
            rs.RECORD_JOB_KEY: card.job_key,
            rs.RECORD_TITLE_KEY: "Registered Nurse",
            rs.RECORD_COMPANY_KEY: "Metro Health",
            rs.RECORD_POSTED_AGE_DAYS_KEY: 1,
        }

    for order in (["a", "b"], ["b", "a"]):
        list_page = _FakeListPage(
            {
                "target-a": [_FakeCard("seek:shared")],
                "target-b": [_FakeCard("seek:shared")],
            }
        )
        _patch_common_seek_internals(monkeypatch, list_page)
        monkeypatch.setattr(
            seek_runner, "build_seek_card_record", _fake_build_shared_nurse_card_record
        )
        recorded_metrics = []
        monkeypatch.setattr(
            seek_runner, "record_query_yield_metric", lambda metric: recorded_metrics.append(metric)
        )

        seek_runner.seek_scrape_to_records(
            **_base_scrape_kwargs(
                profile=profile,
                search_targets=[targets_by_key[key] for key in order],
                configured_seek_max_pages=2,
                discovery_capture=[],
            )
        )

        by_term = {metric.search_term: metric for metric in recorded_metrics}
        assert by_term["Registered Nurse"].pages_searched == 2, order
        assert by_term["Enrolled Nurse"].pages_searched == 2, order


def test_seek_sign_in_wall_ends_target_without_marking_query_failed(monkeypatch):
    """A SEEK sign-in boundary is an expected public-pagination limit, not a scraper failure."""
    list_page = _FakeListPage({"target-a": [_FakeCard("seek:public-card")]})
    _patch_common_seek_internals(monkeypatch, list_page)

    def _wait_for_challenge(page, *args, **kwargs):
        if "page=2" in page.url:
            raise TimeoutError("sign-in wall")
        return True

    monkeypatch.setattr(
        seek_runner, "_wait_for_seek_bot_challenge_or_manual_verification", _wait_for_challenge
    )
    monkeypatch.setattr(
        seek_runner,
        "_log_seek_list_page_diagnostics",
        lambda *args, **kwargs: "sign_in_wall",
    )
    monkeypatch.setattr(
        seek_runner,
        "_seek_list_page_diagnostics",
        lambda page: {
            "title": "SEEK jobs",
            "url": page.url,
            "body_text": "Sign in to see more jobs",
            "selector_count": 0,
            "page_status": "sign_in_wall",
            "failure_class": seek_runner.SEEK_SIGN_IN_WALL,
        },
    )
    metrics = []
    monkeypatch.setattr(seek_runner, "record_query_yield_metric", lambda metric: metrics.append(metric))

    seek_runner.seek_scrape_to_records(
        **_base_scrape_kwargs(
            search_targets=[_search_targets()[0]],
            configured_seek_max_pages=2,
            discovery_capture=[],
        )
    )

    assert len(metrics) == 1
    assert metrics[0].pages_searched == 1
    assert metrics[0].discovered_count == 1
    assert metrics[0].success is True
    assert metrics[0].failure_reason == ""
