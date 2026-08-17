"""Coverage for SEEK's cross-search-term job dedup and query-yield metrics."""

from __future__ import annotations

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
