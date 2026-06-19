"""Integration tests for candidate application history sync and local store flow."""

from __future__ import annotations

import json

from job_hunter_agent import candidate_application_history as cah


def _set_history_paths(monkeypatch, tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    cache_path = tmp_path / "candidate_application_history_cache.json"
    monkeypatch.setattr(cah, "_CANDIDATE_APPLICATION_HISTORY_PATH", store_path)
    monkeypatch.setattr(cah, "CANDIDATE_APPLICATION_HISTORY_CACHE_PATH", cache_path)
    monkeypatch.setattr(cah, "is_candidate_application_history_enabled", lambda: True)
    return store_path, cache_path


def _sheet_row(message_id: str, company: str, role: str, *, run_date: str = "2026-06-12") -> dict:
    return {
        "Run Date": run_date,
        "Company": company,
        "From": "recruiter@example.com",
        "Subject": role,
        "Content": f"{role} at {company}",
        "Thread ID": f"thread-{message_id}",
        "Message ID": message_id,
        "Status": "rejected",
    }


def _normalized_row(
    raw_row: dict,
    *,
    company: str | None = None,
    role: str | None = None,
    needs_review: bool = False,
) -> dict:
    return {
        "run_date": raw_row["Run Date"],
        "raw_company": raw_row["Company"],
        "from": raw_row["From"],
        "subject": raw_row["Subject"],
        "content": raw_row["Content"],
        "thread_id": raw_row["Thread ID"],
        "message_id": raw_row["Message ID"],
        "status": raw_row["Status"],
        "llm_company": company or raw_row["Company"],
        "llm_role": role or raw_row["Subject"],
        "llm_is_rejection": True,
        "llm_application_status": "rejection",
        "llm_confidence": "high",
        "llm_evidence": raw_row["Content"],
        "llm_needs_review": needs_review,
        "llm_review_reason": None,
    }


def test_import_command_returns_error_when_sheet_fetch_fails(monkeypatch, tmp_path, capsys):
    _set_history_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cah,
        "fetch_candidate_job_rejection_rows",
        lambda: (_ for _ in ()).throw(RuntimeError("sheet unavailable")),
    )

    result = cah.main(["import-from-sheet"])

    output = capsys.readouterr().out
    assert result == 1
    assert "[candidate_application_history] unavailable: sheet unavailable" in output
    assert "[candidate_application_history] rows_fetched: 0" in output
    assert "[candidate_application_history] records_total: 0" in output


def test_import_recovers_from_corrupt_cache_and_partial_row_failure(monkeypatch, tmp_path):
    store_path, cache_path = _set_history_paths(monkeypatch, tmp_path)
    cache_path.write_text("{not json}", encoding="utf-8")

    raw_rows = [
        _sheet_row("m-1", "Acme", "Business Analyst"),
        _sheet_row("m-2", "Beacon", "Data Analyst"),
    ]

    def normalize(raw_row: dict) -> dict:
        if raw_row["Message ID"] == "m-2":
            raise ValueError("bad row")
        return _normalized_row(raw_row, company="Acme", role="Business Analyst")

    monkeypatch.setattr(cah, "fetch_candidate_job_rejection_rows", lambda: raw_rows)
    monkeypatch.setattr(cah, "normalize_job_rejection_row", normalize)

    summary = cah.import_candidate_rejections_from_sheet()

    stored = json.loads(store_path.read_text(encoding="utf-8"))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert summary["rows_fetched"] == 2
    assert summary["rows_loaded_from_cache"] == 0
    assert summary["rows_sent_to_llm"] == 1
    assert summary["rows_marked_rejection"] == 2
    assert summary["rows_needing_review"] == 1
    assert summary["records_added"] == 2
    assert summary["records_updated"] == 0
    assert summary["records_total"] == 2
    assert len(stored) == 2
    assert stored[1]["needs_review"] is True
    assert stored[1]["review_reason"] == "Row processing failed: bad row"
    assert len(cache) == 2


def test_status_command_reads_only_local_store(monkeypatch, tmp_path, capsys):
    store_path, _ = _set_history_paths(monkeypatch, tmp_path)
    store_path.write_text(
        json.dumps(
            [
                {
                    "id": "m-1",
                    "message_id": "m-1",
                    "date": "2026-06-12",
                    "company": "Acme",
                    "role": "Business Analyst",
                    "status": "rejection",
                    "recruiter": None,
                    "source": "sheet_import",
                    "evidence": "We regret to inform you",
                    "job_key": None,
                    "created_at": "2026-06-12T10:00:00+00:00",
                    "updated_at": "2026-06-12T10:00:00+00:00",
                    "confidence": "high",
                    "needs_review": False,
                    "review_reason": None,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    called = []
    monkeypatch.setattr(
        cah,
        "fetch_candidate_job_rejection_rows",
        lambda: called.append(True),
    )

    result = cah.main(["status"])

    output = capsys.readouterr().out
    assert result == 0
    assert called == []
    assert "[candidate_application_history] rows_fetched: 0" in output
    assert "[candidate_application_history] rows_marked_rejection: 1" in output
    assert "[candidate_application_history] records_total: 1" in output


def test_load_candidate_history_skips_invalid_store_rows(monkeypatch, tmp_path, capsys):
    store_path, _ = _set_history_paths(monkeypatch, tmp_path)
    store_path.write_text(
        json.dumps(
            [
                {
                    "id": "m-1",
                    "message_id": "m-1",
                    "date": "2026-06-12",
                    "company": "Acme",
                    "role": "Business Analyst",
                    "status": "rejection",
                    "recruiter": None,
                    "source": "sheet_import",
                    "evidence": "We regret to inform you",
                    "job_key": None,
                    "created_at": "2026-06-12T10:00:00+00:00",
                    "updated_at": "2026-06-12T10:00:00+00:00",
                    "confidence": "high",
                    "needs_review": False,
                    "review_reason": None,
                },
                {
                    "id": "bad-1",
                    "message_id": "bad-1",
                    "date": "2026-06-12",
                    "company": "",
                    "role": "Business Analyst",
                    "status": "rejection",
                    "recruiter": None,
                    "source": "sheet_import",
                    "evidence": "Broken row — company is empty so this should be skipped",
                    "job_key": None,
                    "created_at": "2026-06-12T10:00:00+00:00",
                    "updated_at": "2026-06-12T10:00:00+00:00",
                    "confidence": "high",
                    "needs_review": False,
                    "review_reason": None,
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    rows = cah.load_candidate_job_rejection_history()

    output = capsys.readouterr().out
    assert len(rows) == 1
    assert rows[0]["llm_company"] == "Acme"
    assert "invalid store rows skipped: 1" in output
