"""Tests for job type learning."""

from datetime import date
from types import SimpleNamespace

from job_hunter_agent import job_types
from job_hunter_agent.scrapers.base import _map_job_type, normalize_jobspy_record


def test_unknown_job_type_is_preserved_and_registered(monkeypatch):

    captured = {}

    def _capture(signals, category=""):

        captured["signals"] = signals

        captured["category"] = category

    monkeypatch.setattr("job_hunter_agent.signal_registry.register_signals", _capture)

    row = SimpleNamespace(
        date_posted=date(2026, 5, 6),
        min_amount=100000,
        max_amount=120000,
        interval="yearly",
        currency="AUD",
        is_remote=True,
        job_type="Fixed term",
        description="Role description",
        id="123",
        title="Senior Analyst",
        company="Acme",
        location="Sydney",
        job_url="https://example.com/job/123",
    )

    record = normalize_jobspy_record(
        row=row,
        source="linkedin",
        search_keywords="analyst",
        search_location="Sydney",
        run_iso="2026-05-07T09:00:00+10:00",
        salary_rules={
            "interval_divisor": {"yearly": 1000},
            "interval_suffix": {"yearly": "p.a."},
            "currencies_with_dollar": ["AUD"],
        },
        job_type_rules={"fulltime": "Full time"},
    )

    assert record["work_type"] == ""

    assert captured["category"] == "job_type_normalization_candidate"

    assert captured["signals"][0]["signal"] == "Fixed term"

    assert captured["signals"][0]["suggested_values"] == ["Fixed term"]


def test_upsert_job_type_entry_writes_normalized_mapping(isolated_db, monkeypatch):

    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge("job_type", {"mapping": {}, "filter_groups": []}, isolated_db)

    monkeypatch.setattr(job_types, "_cached_mapping", None)

    monkeypatch.setattr(job_types, "_cached_filter_groups", None)

    job_types.upsert_job_type_entry("Fixed term")

    assert job_types.load_job_type(force_reload=True) == {"fixedterm": "Fixed term"}


def test_page_script_job_type_candidate_is_not_registered(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "job_hunter_agent.signal_registry.register_signals",
        lambda signals, category="": captured.extend(signals),
    )

    _map_job_type(
        "window.Aura.beforeFrameworkInit.push(init);}());Skip to navigation"
        + " Job details and application information " * 40,
        {},
    )

    assert captured == []


def test_concise_unknown_job_type_candidate_is_registered(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "job_hunter_agent.signal_registry.register_signals",
        lambda signals, category="": captured.extend(signals),
    )

    _map_job_type("Seasonal rotation", {})

    assert [item["signal"] for item in captured] == ["Seasonal rotation"]


def test_plain_text_page_blob_job_type_candidate_is_not_registered(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "job_hunter_agent.signal_registry.register_signals",
        lambda signals, category="": captured.extend(signals),
    )

    blob = "job details and application information " * 10

    _map_job_type(blob.strip(), {})

    assert len(blob.strip()) >= 300
    assert captured == []


def test_jobspy_other_sentinel_is_not_registered(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "job_hunter_agent.signal_registry.register_signals",
        lambda signals, category="": captured.extend(signals),
    )

    _map_job_type("other", {})

    assert captured == []
