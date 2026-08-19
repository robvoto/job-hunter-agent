"""Tests for candidate application history."""

import json
from copy import deepcopy
from unittest.mock import patch

from job_hunter_agent.candidate_application_history import (
    add_candidate_rejection_record,
    enrich_records_with_application_history,
    import_candidate_rejections_from_json,
    import_candidate_rejections_from_sheet,
    load_candidate_application_history,
    load_candidate_job_rejection_history,
    main,
    match_job_application_history,
    save_candidate_application_history,
)

_CANDIDATE_APPLICATION_HISTORY_KEY = "candidate_application_history"


def test_enrich_preserves_order_does_not_mutate_inputs_and_only_adds_matching_history():
    records = [
        {"job_key": "seek:1", "company": "No Match Corp", "title": "BA", "fit_score": 80},
        {
            "job_key": "seek:2",
            "company": "Police Bank",
            "title": "Technical Business Analyst",
            "fit_score": 90,
        },
    ]
    rows = [
        {
            "llm_company": "Police Bank",
            "llm_role": "Technical Business Analyst",
            "llm_is_rejection": True,
            "llm_application_status": "rejection",
            "llm_confidence": "high",
            "llm_evidence": "Your application for Technical Business Analyst at Police Bank",
            "llm_needs_review": False,
        },
        {
            "llm_company": "Another Company",
            "llm_role": "Technical Business Analyst",
            "llm_is_rejection": True,
            "llm_application_status": "rejection",
            "llm_confidence": "high",
            "llm_evidence": "Your application for Technical Business Analyst at Another Company",
            "llm_needs_review": False,
        },
    ]
    records_before = deepcopy(records)
    rows_before = deepcopy(rows)

    result = enrich_records_with_application_history(records, rows)

    assert records == records_before
    assert rows == rows_before
    assert [record["job_key"] for record in result] == ["seek:1", "seek:2"]
    assert _CANDIDATE_APPLICATION_HISTORY_KEY not in result[0]
    assert _CANDIDATE_APPLICATION_HISTORY_KEY in result[1]
    assert _CANDIDATE_APPLICATION_HISTORY_KEY not in records[0]
    assert _CANDIDATE_APPLICATION_HISTORY_KEY not in records[1]


def test_match_job_application_history_marks_exact_company_suffix_match():
    match = match_job_application_history(
        {"company": "Acme", "title": "Business Analyst"},
        [
            {
                "llm_company": "Acme Pty Ltd",
                "llm_role": "Business Analyst",
                "llm_application_status": "rejection",
            }
        ],
    )

    assert match is not None
    assert match["_match_confidence"] == "high"
    assert match["_company_match_reason"] == "Normalized company name match"


def test_match_job_application_history_uses_subject_company_match_when_company_field_differs():
    match = match_job_application_history(
        {"company": "Police Bank", "title": "Technical Business Analyst"},
        [
            {
                "llm_company": "Another Company",
                "llm_role": "Technical Business Analyst",
                "subject": "Your application with Police Bank",
                "content": "",
                "llm_application_status": "rejection",
            }
        ],
    )

    assert match is not None
    assert match["_match_confidence"] == "medium"
    assert match["_company_match_reason"] == "Company name found in rejection email subject"


def test_match_job_application_history_rejects_lookalike_company_false_positive():
    match = match_job_application_history(
        {"company": "Police Health", "title": "Technical Business Analyst"},
        [
            {
                "llm_company": "Police Bank",
                "llm_role": "Technical Business Analyst",
                "subject": "",
                "content": "",
                "llm_application_status": "rejection",
            }
        ],
    )

    assert match is None


def test_load_candidate_history_reads_local_store_and_does_not_touch_sheet(tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    store_path.write_text(
        json.dumps(
            [
                {
                    "id": "abc123",
                    "date": "2026-05-07",
                    "company": "Acme",
                    "role": "Business Analyst",
                    "status": "rejection",
                    "recruiter": None,
                    "source": "manual",
                    "evidence": "Thanks for your application",
                    "job_key": None,
                    "created_at": "2026-05-07T10:00:00+00:00",
                    "updated_at": "2026-05-07T10:00:00+00:00",
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

    with (
        patch(
            "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
            store_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.fetch_candidate_job_rejection_rows"
        ) as mock_fetch,
    ):
        rows = load_candidate_job_rejection_history()

    assert not mock_fetch.called
    assert rows[0]["llm_company"] == "Acme"
    assert rows[0]["llm_role"] == "Business Analyst"
    assert rows[0]["llm_application_status"] == "rejection"
    assert rows[0]["llm_confidence"] == "high"
    assert rows[0]["llm_needs_review"] is False


def test_save_and_load_candidate_application_history_use_local_store(tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    payload = [
        {
            "id": "abc123",
            "date": "2026-05-07",
            "company": "Acme",
            "role": "Business Analyst",
            "status": "rejection",
            "recruiter": None,
            "source": "manual",
            "evidence": "Thanks for your application",
            "job_key": None,
            "created_at": "2026-05-07T10:00:00+00:00",
            "updated_at": "2026-05-07T10:00:00+00:00",
        }
    ]

    with patch(
        "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
        store_path,
    ):
        save_candidate_application_history(payload)
        loaded = load_candidate_application_history()

    assert loaded == payload
    assert store_path.exists()


def test_import_from_sheet_populates_local_store(tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    cache_path = tmp_path / "candidate_application_history_cache.json"

    raw_rows = [
        {
            "Message ID": "m1",
            "Thread ID": "t1",
            "Subject": "A",
            "Content": "B",
            "Run Date": "2026-05-07",
            "Company": "Acme",
            "From": "",
            "Status": "rejected",
        }
    ]

    normalized_row = {
        "run_date": "2026-05-07",
        "raw_company": "Acme",
        "from": "",
        "subject": "A",
        "content": "B",
        "thread_id": "t1",
        "message_id": "m1",
        "status": "rejected",
        "llm_company": "Acme",
        "llm_role": "Business Analyst",
        "llm_is_rejection": True,
        "llm_application_status": "rejection",
        "llm_confidence": "high",
        "llm_evidence": "A",
        "llm_needs_review": False,
        "llm_review_reason": None,
    }

    with (
        patch(
            "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
            store_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.CANDIDATE_APPLICATION_HISTORY_CACHE_PATH",
            cache_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.fetch_candidate_job_rejection_rows",
            return_value=raw_rows,
        ),
        patch("job_hunter_agent.candidate_application_history._load_cache", return_value={}),
        patch(
            "job_hunter_agent.candidate_application_history.normalize_job_rejection_row",
            return_value=normalized_row,
        ),
        patch("job_hunter_agent.candidate_application_history._save_cache") as mock_save_cache,
    ):
        summary = import_candidate_rejections_from_sheet()

    assert mock_save_cache.called
    assert summary["rows_fetched"] == 1
    assert summary["rows_sent_to_llm"] == 1
    assert summary["rows_marked_rejection"] == 1
    assert summary["rows_needing_review"] == 0
    assert summary["records_added"] == 1
    assert summary["records_updated"] == 0
    assert summary["enabled"] is True
    assert store_path.exists()

    saved_rows = json.loads(store_path.read_text(encoding="utf-8"))
    assert saved_rows[0]["source"] == "sheet_import"
    assert saved_rows[0]["status"] == "rejection"
    assert saved_rows[0]["company"] == "Acme"
    assert saved_rows[0]["role"] == "Business Analyst"
    assert saved_rows[0]["id"] == "m1"
    assert saved_rows[0]["message_id"] == "m1"


def test_import_from_sheet_dedupes_by_company_role_date_when_message_id_missing(tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    cache_path = tmp_path / "candidate_application_history_cache.json"

    raw_rows = [
        {
            "Message ID": "",
            "Thread ID": "thread-1",
            "Subject": "A",
            "Content": "B",
            "Run Date": "2026-05-07",
            "Company": "Acme",
            "From": "",
            "Status": "rejected",
        }
    ]

    normalized_row = {
        "run_date": "2026-05-07",
        "raw_company": "Acme",
        "from": "",
        "subject": "A",
        "content": "B",
        "thread_id": "thread-1",
        "message_id": "",
        "status": "rejected",
        "llm_company": "Acme",
        "llm_role": "Business Analyst",
        "llm_is_rejection": True,
        "llm_application_status": "rejection",
        "llm_confidence": "high",
        "llm_evidence": "A",
        "llm_needs_review": False,
        "llm_review_reason": None,
    }

    with (
        patch(
            "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
            store_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.CANDIDATE_APPLICATION_HISTORY_CACHE_PATH",
            cache_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.fetch_candidate_job_rejection_rows",
            return_value=raw_rows,
        ),
        patch("job_hunter_agent.candidate_application_history._load_cache", return_value={}),
        patch(
            "job_hunter_agent.candidate_application_history.normalize_job_rejection_row",
            return_value=normalized_row,
        ),
        patch("job_hunter_agent.candidate_application_history._save_cache"),
    ):
        first_summary = import_candidate_rejections_from_sheet()
        second_summary = import_candidate_rejections_from_sheet()

    assert first_summary["records_added"] == 1
    assert second_summary["records_added"] == 0
    assert second_summary["records_updated"] == 1

    saved_rows = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(saved_rows) == 1
    assert saved_rows[0]["company"] == "Acme"
    assert saved_rows[0]["role"] == "Business Analyst"
    assert saved_rows[0]["id"]
    assert saved_rows[0]["message_id"] is None


def test_import_from_json_populates_local_store_without_loading_sheet(tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    cache_path = tmp_path / "candidate_application_history_cache.json"
    export_path = tmp_path / "candidate_application_history_export.json"
    export_record = {
        "date": "2026-05-07T00:00:00.000Z",
        "company": "Acme",
        "role": "Business Analyst",
        "status": "rejection",
        "recruiter": None,
        "source": "gmail_apps_script",
        "evidence": "A",
        "subject": "A",
        "message_id": "m-json",
        "thread_id": "t-json",
        "original_row_number": 2,
    }
    export_path.write_text(json.dumps([export_record]), encoding="utf-8")

    with (
        patch(
            "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
            store_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.CANDIDATE_APPLICATION_HISTORY_CACHE_PATH",
            cache_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.fetch_candidate_job_rejection_rows"
        ) as mock_fetch,
        patch(
            "job_hunter_agent.candidate_application_history.normalize_job_rejection_row"
        ) as mock_normalize,
    ):
        summary = import_candidate_rejections_from_json(export_path)

    assert not mock_fetch.called
    assert not mock_normalize.called
    assert summary["rows_fetched"] == 1
    assert summary["records_added"] == 1
    saved_rows = json.loads(store_path.read_text(encoding="utf-8"))
    assert saved_rows[0]["source"] == "gmail_apps_script"
    assert saved_rows[0]["company"] == "Acme"


def test_add_candidate_rejection_record_appends_manual_rejection_to_local_store(tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    store_path.write_text("[]", encoding="utf-8")

    with (
        patch(
            "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
            store_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history._candidate_history_now",
            return_value="2026-05-20T10:00:00+00:00",
        ),
    ):
        stored = add_candidate_rejection_record(
            {
                "date": "2026-05-20",
                "company": "Acme",
                "role": "Business Analyst",
                "evidence": "We regret to inform you",
            }
        )

    assert stored["status"] == "rejection"
    assert stored["source"] == "manual"
    assert stored["company"] == "Acme"
    assert stored["role"] == "Business Analyst"
    assert stored["created_at"] == "2026-05-20T10:00:00+00:00"
    assert stored["updated_at"] == "2026-05-20T10:00:00+00:00"

    saved_rows = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(saved_rows) == 1
    assert saved_rows[0]["source"] == "manual"
    assert saved_rows[0]["status"] == "rejection"
    assert saved_rows[0]["company"] == "Acme"


def test_candidate_history_debug_command_imports_from_sheet_and_prints_counts(capsys, tmp_path):
    store_path = tmp_path / "candidate_application_history.json"
    cache_path = tmp_path / "candidate_application_history_cache.json"

    raw_rows = [
        {
            "Message ID": "m1",
            "Thread ID": "t1",
            "Subject": "A",
            "Content": "B",
            "Run Date": "2026-05-07",
            "Company": "Acme",
            "From": "",
            "Status": "rejected",
        }
    ]
    normalized_row = {
        "run_date": "2026-05-07",
        "raw_company": "Acme",
        "from": "",
        "subject": "A",
        "content": "B",
        "thread_id": "t1",
        "message_id": "m1",
        "status": "rejected",
        "llm_company": "Acme",
        "llm_role": "Business Analyst",
        "llm_is_rejection": True,
        "llm_application_status": "rejection",
        "llm_confidence": "high",
        "llm_evidence": "A",
        "llm_needs_review": False,
        "llm_review_reason": None,
    }

    with (
        patch(
            "job_hunter_agent.candidate_application_history._CANDIDATE_APPLICATION_HISTORY_PATH",
            store_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.CANDIDATE_APPLICATION_HISTORY_CACHE_PATH",
            cache_path,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.fetch_candidate_job_rejection_rows",
            return_value=raw_rows,
        ),
        patch("job_hunter_agent.candidate_application_history._load_cache", return_value={}),
        patch(
            "job_hunter_agent.candidate_application_history.normalize_job_rejection_row",
            return_value=normalized_row,
        ),
        patch("job_hunter_agent.candidate_application_history._save_cache"),
    ):
        result = main(["import-from-sheet"])

    assert result == 0
    output = capsys.readouterr().out
    assert "[candidate_application_history] rows_fetched: 1" in output
    assert "[candidate_application_history] rows_loaded_from_cache: 0" in output
    assert "[candidate_application_history] rows_sent_to_llm: 1" in output
    assert "[candidate_application_history] rows_marked_rejection: 1" in output
    assert "[candidate_application_history] rows_needing_review: 0" in output
    assert "[candidate_application_history] records_added: 1" in output
    assert "[candidate_application_history] records_updated: 0" in output
