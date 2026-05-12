from datetime import date
from types import SimpleNamespace

from job_hunter_agent.scrapers.base import normalize_jobspy_record
from job_hunter_agent import job_types


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

    assert record["work_type"] == "Fixed term"
    assert captured["category"] == "job_type_normalization_candidate"
    assert captured["signals"][0]["signal"] == "Fixed term"
    assert captured["signals"][0]["suggested_values"] == ["Fixed term"]


def test_upsert_job_type_entry_writes_normalized_mapping(tmp_path, monkeypatch):
    store = tmp_path / "job_type.json"
    monkeypatch.setattr(job_types, "JOB_TYPE_STORE_PATH", store)
    monkeypatch.setattr(job_types, "_cached_mapping", None)

    job_types.upsert_job_type_entry("Fixed term")

    assert store.exists()
    assert job_types.load_job_type(force_reload=True) == {"fixedterm": "Fixed term"}
