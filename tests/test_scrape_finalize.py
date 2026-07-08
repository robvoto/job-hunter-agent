"""Tests for scrape finalize."""

from __future__ import annotations

from datetime import datetime, timezone

from job_hunter_agent import scrape_finalize, source_learning, workspace_service
from job_hunter_agent.database import db_conn
from job_hunter_agent.record_schema import (
    RECORD_FIT_LABEL_KEY,
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_FIT_TONE_CLASS_KEY,
)
from job_hunter_agent.run_context import ScrapeRunContext


def _build_context() -> ScrapeRunContext:

    run_started_at = datetime(2026, 5, 16, 8, 12, 40, tzinfo=timezone.utc)

    return ScrapeRunContext(
        profile={"name": "profile"},
        search_settings={},
        dashboard_min_score=50,
        configured_seek_max_pages=4,
        configured_date_range=3,
        sort_newest_first=True,
        playwright_viewport_width=1400,
        playwright_viewport_height=900,
        playwright_selector_timeout=8000,
        seek_parallel_detail_workers=3,
        applied_job_keys={"job:applied"},
        hidden_job_keys={"job:hidden"},
        run_started_at=run_started_at,
        run_iso=run_started_at.isoformat(timespec="seconds"),
        previous_audit_rows=[],
        previous_run_stats={},
        llm_cache={"cache-key": {"value": 1}},
        job_history={"job:1": {"times_kept": 1}},
        enabled_sources=["seek"],
        no_llm_mode=False,
        dashboard_debug_mode=False,
        reset_new_to_you=False,
    )


def test_merge_into_pool_updates_non_score_fields_and_preserves_frozen_score():
    pool = [
        {
            "job_key": "job:1",
            "title": "Old title",
            "company": "Acme",
            "url": "https://old.example/job",
            "salary": "$100k",
            RECORD_FIT_SCORE_KEY: 72,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [{"label": "Base", "value": 72}],
            RECORD_FIT_LABEL_KEY: "Strong fit",
            RECORD_FIT_TONE_CLASS_KEY: "tone-good",
        }
    ]
    new_records = [
        {
            "job_key": "job:1",
            "title": "New title",
            "company": "Acme",
            "url": "https://new.example/job",
            "salary": "$120k",
        }
    ]

    merged = scrape_finalize._merge_into_pool(pool, new_records)

    assert merged[0]["title"] == "New title"
    assert merged[0]["url"] == "https://new.example/job"
    assert merged[0]["salary"] == "$120k"
    assert merged[0][RECORD_FIT_SCORE_KEY] == 72
    assert merged[0][RECORD_FIT_SCORE_BREAKDOWN_KEY] == [{"label": "Base", "value": 72}]
    assert merged[0][RECORD_FIT_LABEL_KEY] == "Strong fit"
    assert merged[0][RECORD_FIT_TONE_CLASS_KEY] == "tone-good"


def test_finalize_scrape_run_writes_outputs(monkeypatch, tmp_path, capsys, caplog):
    import logging as _logging

    caplog.set_level(_logging.INFO)

    context = _build_context()

    workspace_path = tmp_path / "workspace.html"

    calls: list[tuple[str, object]] = []

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))

    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)

    monkeypatch.setattr(
        scrape_finalize,
        "deduplicate_across_sources",
        lambda records: [*records, {"job_key": "deduped"}],
    )

    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "build_run_stats",
        lambda *args: {"run_started_at": "2026-05-16T08:12:40", "cards_seen": 1},
    )

    def _render_html(*args, **kwargs):
        calls.append(("render_html", (args, kwargs)))

    monkeypatch.setattr(scrape_finalize.workspace_service, "render_html", _render_html)
    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "build_workspace_record_sets",
        lambda *args, **kwargs: {"shortlist_records": [{"job_key": "job:1"}]},
    )

    monkeypatch.setattr(
        scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload))
    )

    monkeypatch.setattr(
        scrape_finalize,
        "save_job_history",
        lambda payload: calls.append(("save_job_history", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_debug_json",
        lambda payload: calls.append(("write_debug_json", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_run_stats",
        lambda payload: calls.append(("write_run_stats", payload)),
    )

    monkeypatch.setattr(source_learning, "get_llm_truncation_count", lambda: 3)

    monkeypatch.setattr(
        scrape_finalize,
        "write_review_data",
        lambda payload: calls.append(("write_review_data", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "build_review_data",
        lambda audit_rows, skill_observations, profile: {
            "audit_count": len(audit_rows),
            "skill_count": len(skill_observations),
            "profile_name": profile["name"],
        },
    )

    workspace_result = scrape_finalize.finalize_scrape_run(
        context,
        kept_records=[{"job_key": "job:1"}],
        audit_rows=[{"job_key": "job:1", "decision": "KEEP"}],
        skill_observations=[{"skill": "analysis"}],
    )

    assert workspace_result == str(workspace_path)

    assert ("save_llm_cache", context.llm_cache) in calls

    assert ("save_job_history", context.job_history) in calls

    assert any(name == "write_debug_json" for name, _ in calls)

    assert any(name == "write_run_stats" for name, _ in calls)
    write_run_stats_payload = next(payload for name, payload in calls if name == "write_run_stats")
    assert write_run_stats_payload["llm_truncation_count"] == 3

    assert any(name == "write_review_data" for name, _ in calls)

    assert any(name == "render_html" for name, _ in calls)
    render_args, render_kwargs = next(payload for name, payload in calls if name == "render_html")
    assert render_args[0] == workspace_path
    assert render_kwargs["workspace_records"] == {"shortlist_records": [{"job_key": "job:1"}]}

    capsys.readouterr()
    log_text = caplog.text

    assert "Saved 2 jobs to" in log_text

    assert "Saved 1 audit rows to" in log_text


def test_finalize_scrape_run_builds_source_breakdown_from_decisions(monkeypatch, tmp_path):
    context = _build_context()

    workspace_path = tmp_path / "workspace.html"
    captured: dict[str, object] = {}

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))

    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: records)
    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "build_run_stats",
        lambda *args: {
            "run_started_at": "2026-05-16T08:12:40",
            "cards_seen": 3,
            "cards_read": 3,
            "kept_count": 2,
            "rejected_count": 1,
            "cards_with_flags_count": 0,
        },
    )
    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "render_html",
        lambda *args, **kwargs: captured.update({"run_stats": args[5]}),
    )
    monkeypatch.setattr(scrape_finalize, "save_llm_cache", lambda payload: None)
    monkeypatch.setattr(scrape_finalize, "save_job_history", lambda payload: None)
    monkeypatch.setattr(scrape_finalize, "write_debug_json", lambda payload: None)
    monkeypatch.setattr(scrape_finalize, "write_run_stats", lambda payload: None)
    monkeypatch.setattr(scrape_finalize, "write_review_data", lambda payload: None)
    monkeypatch.setattr(source_learning, "get_llm_truncation_count", lambda: 0)

    scrape_finalize.finalize_scrape_run(
        context,
        kept_records=[{"job_key": "seek:1"}, {"job_key": "linkedin:1"}],
        audit_rows=[
            {"job_key": "seek:1", "source": "seek", "decision": "KEEP", "pages_processed": 2},
            {"job_key": "linkedin:1", "source": "linkedin", "decision": "KEEP"},
            {"job_key": "linkedin:2", "source": "linkedin", "decision": "REJECT"},
        ],
        skill_observations=[],
    )

    run_stats = captured["run_stats"]
    assert isinstance(run_stats, dict)
    breakdown = {item["source"]: item for item in run_stats["source_breakdown"]}
    assert breakdown["SEEK"]["kept"] == 1
    assert breakdown["SEEK"]["rejected"] == 0
    assert breakdown["SEEK"]["pages"] == 2
    assert breakdown["LINKEDIN"]["kept"] == 1
    assert breakdown["LINKEDIN"]["rejected"] == 1
    assert breakdown["LINKEDIN"]["pages"] == 2


def test_finalize_scrape_run_preserves_previous_workspace_when_no_audit_rows(
    monkeypatch, tmp_path, capsys, caplog
):
    import logging as _logging

    caplog.set_level(_logging.INFO)

    context = _build_context()

    context.previous_audit_rows = [
        {"job_key": "job:old", "decision": "KEEP", "run_started_at": context.run_iso}
    ]

    context.previous_run_stats = {"run_started_at": "2026-05-15T08:12:40"}

    workspace_path = tmp_path / "workspace.html"
    summary_path = tmp_path / "last_run_summary.txt"

    calls: list[tuple[str, object]] = []

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))

    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(scrape_finalize, "RUN_SUMMARY_PATH", summary_path)

    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: records)

    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "load_last_kept_records",
        lambda *args, **kwargs: [{"job_key": "job:old"}],
    )

    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "render_html",
        lambda *args, **kwargs: calls.append(("render_html", (args, kwargs))),
    )

    monkeypatch.setattr(
        scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload))
    )

    monkeypatch.setattr(
        scrape_finalize,
        "save_job_history",
        lambda payload: calls.append(("save_job_history", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_debug_json",
        lambda payload: calls.append(("write_debug_json", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_run_stats",
        lambda payload: calls.append(("write_run_stats", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_review_data",
        lambda payload: calls.append(("write_review_data", payload)),
    )

    workspace_result = scrape_finalize.finalize_scrape_run(
        context,
        kept_records=[],
        audit_rows=[],
        skill_observations=[],
    )

    assert workspace_result == str(workspace_path)

    assert ("save_llm_cache", context.llm_cache) in calls

    assert ("save_job_history", context.job_history) in calls

    assert not any(name == "write_debug_json" for name, _ in calls)

    assert any(name == "write_run_stats" for name, _ in calls)

    assert any(name == "write_review_data" for name, _ in calls)

    assert any(name == "render_html" for name, _ in calls)

    capsys.readouterr()
    log_text = caplog.text

    assert "[RUN][ERROR] No fresh cards were captured in this run." in log_text

    assert "previous workspace state was preserved" in log_text

    assert summary_path.exists()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "No fresh cards were captured in this run." in summary_text


def test_finalize_scrape_run_marks_empty_first_run_as_error(monkeypatch, tmp_path, capsys, caplog):
    import logging as _logging

    caplog.set_level(_logging.INFO)

    context = _build_context()

    workspace_path = tmp_path / "workspace.html"

    calls: list[tuple[str, object]] = []

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))

    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)

    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: records)

    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "build_run_stats",
        lambda *args: {"run_started_at": "2026-05-16T08:12:40", "cards_seen": 0},
    )

    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "render_html",
        lambda *args, **kwargs: calls.append(("render_html", (args, kwargs))),
    )

    monkeypatch.setattr(
        scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload))
    )

    monkeypatch.setattr(
        scrape_finalize,
        "save_job_history",
        lambda payload: calls.append(("save_job_history", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_debug_json",
        lambda payload: calls.append(("write_debug_json", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_run_stats",
        lambda payload: calls.append(("write_run_stats", payload)),
    )

    monkeypatch.setattr(
        scrape_finalize,
        "write_review_data",
        lambda payload: calls.append(("write_review_data", payload)),
    )

    workspace_result = scrape_finalize.finalize_scrape_run(
        context,
        kept_records=[],
        audit_rows=[],
        skill_observations=[],
    )

    assert workspace_result == str(workspace_path)

    assert any(name == "write_run_stats" for name, _ in calls)

    capsys.readouterr()
    log_text = caplog.text

    assert "[RUN][ERROR] No fresh cards were captured in this run." in log_text


def test_finalize_scrape_run_treats_stop_before_fresh_cards_as_cancellation(
    monkeypatch, tmp_path, capsys, caplog
):
    import logging as _logging

    caplog.set_level(_logging.INFO)

    context = _build_context()
    context.previous_audit_rows = [
        {"job_key": "job:old", "decision": "KEEP", "run_started_at": context.run_iso}
    ]
    context.previous_run_stats = {"run_started_at": "2026-05-15T08:12:40"}

    workspace_path = tmp_path / "workspace.html"

    calls: list[tuple[str, object]] = []

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))

    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: records)
    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "load_last_kept_records",
        lambda *args, **kwargs: [{"job_key": "job:old"}],
    )
    monkeypatch.setattr(
        scrape_finalize.workspace_service,
        "render_html",
        lambda *args, **kwargs: calls.append(("render_html", (args, kwargs))),
    )
    monkeypatch.setattr(
        scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload))
    )
    monkeypatch.setattr(
        scrape_finalize,
        "save_job_history",
        lambda payload: calls.append(("save_job_history", payload)),
    )
    monkeypatch.setattr(
        scrape_finalize,
        "write_debug_json",
        lambda payload: calls.append(("write_debug_json", payload)),
    )
    monkeypatch.setattr(
        scrape_finalize,
        "write_run_stats",
        lambda payload: calls.append(("write_run_stats", payload)),
    )
    monkeypatch.setattr(
        scrape_finalize,
        "write_review_data",
        lambda payload: calls.append(("write_review_data", payload)),
    )
    monkeypatch.setattr(scrape_finalize, "run_stop_requested", lambda: True)

    workspace_result = scrape_finalize.finalize_scrape_run(
        context,
        kept_records=[],
        audit_rows=[],
        skill_observations=[],
    )

    assert workspace_result == str(workspace_path)
    run_stats_payload = next(payload for name, payload in calls if name == "write_run_stats")
    assert "last_run_error" not in run_stats_payload

    capsys.readouterr()
    log_text = caplog.text
    assert "stopped before any fresh cards were captured" in log_text
    assert "[RUN][ERROR] No fresh cards were captured in this run." not in log_text


def test_build_run_stats_counts_unique_pages_across_sources():

    run_started_at = datetime(2026, 5, 16, 8, 12, 40, tzinfo=timezone.utc)

    run_finished_at = datetime(2026, 5, 16, 8, 14, 10, tzinfo=timezone.utc)

    stats = workspace_service.build_run_stats(
        audit_rows=[
            {
                "source": "seek",
                "search_location": "Sydney",
                "page": 1,
                "decision": "KEEP",
                "onet_classification": {"result": "near"},
            },
            {"source": "seek", "search_location": "Sydney", "page": 1, "decision": "REJECT"},
            {"source": "seek", "search_location": "Sydney", "page": 2, "decision": "KEEP"},
            {"source": "linkedin", "search_location": "Sydney", "decision": "KEEP"},
            {"source": "linkedin", "search_location": "Melbourne", "page": 1, "decision": "KEEP"},
        ],
        kept_records=[],
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        date_range_days=3,
        sort_newest_first=True,
        seek_max_pages=4,
    )

    assert stats["page_count"] == 3
    assert stats["onet_match_count"] == 1


def test_derive_run_summary_metrics_counts_onet_far_rejections():

    metrics = scrape_finalize._derive_run_summary_metrics(
        [
            {"source": "seek", "reject_reason": "ONET_FAR_OCCUPATION"},
            {"source": "linkedin", "reject_reason": "TITLE_NOT_TARGET"},
            {"source": "seek", "reject_reason": "ONET_FAR_OCCUPATION"},
        ]
    )

    assert metrics["source_counts"] == {"seek": 2, "linkedin": 1}
    assert metrics["onet_far_rejected"] == 2
    assert metrics["title_rejected"] == 1


def test_print_run_summary_uses_explicit_pages_and_cost_labels(caplog, tmp_path, monkeypatch, capsys):
    import logging as _logging

    caplog.set_level(_logging.INFO)
    monkeypatch.setattr(scrape_finalize, "RUN_SUMMARY_PATH", tmp_path / "last_run_summary.txt")

    scrape_finalize._print_run_summary(
        {
            "last_run_attempt_at": "2026-05-16T08:12:40+00:00",
            "page_count": 3,
            "cards_seen": 7,
            "cards_read": 5,
            "kept_count": 2,
            "rejected_count": 3,
            "onet_far_rejected": 2,
            "cards_with_flags_count": 1,
            "llm_total_cost_usd": 0.123456,
            "llm_truncation_count": 4,
        }
    )

    log_text = caplog.text
    assert "Pages read: 3" in log_text
    assert "O*NET rejects: 2" in log_text
    assert "Total LLM cost: $0.1235" in log_text
    assert "LLM truncations: 4" in log_text

    summary_path = tmp_path / "last_run_summary.txt"
    assert summary_path.exists()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "Run ID:     2026-05-16T08:12:40+00:00" in summary_text
    assert "O*NET rejects: 2" in summary_text
    assert "Total LLM cost: $0.1235" in summary_text
    assert "Jobs seen:  7" in summary_text

    captured = capsys.readouterr()
    assert "Run complete" in captured.err
    assert "O*NET rejects: 2" in captured.err
    assert "Total LLM cost: $0.1235" in captured.err


def test_print_run_summary_includes_source_breakdown(caplog, tmp_path, monkeypatch, capsys):
    import logging as _logging

    caplog.set_level(_logging.INFO)
    monkeypatch.setattr(scrape_finalize, "RUN_SUMMARY_PATH", tmp_path / "last_run_summary.txt")

    scrape_finalize._print_run_summary(
        {
            "last_run_attempt_at": "2026-05-16T08:12:40+00:00",
            "page_count": 2,
            "cards_seen": 5,
            "cards_read": 5,
            "kept_count": 2,
            "rejected_count": 3,
            "cards_with_flags_count": 0,
            "llm_total_cost_usd": 0.0,
            "llm_truncation_count": 0,
            "source_breakdown": [
                {"source": "seek", "seen": 3, "read": 2, "pages": 2, "kept": 1, "rejected": 2},
                {"source": "linkedin", "seen": 2, "read": 1, "pages": 1, "kept": 1, "rejected": 1},
            ],
            "last_run_error": "No fresh cards were captured in this run.",
            "warnings": ["LinkedIn timed out", "SEEK had a challenge page"],
        }
    )

    captured = capsys.readouterr()
    assert "By platform" in captured.err
    assert "SEEK" in captured.err
    assert "LINKEDIN" in captured.err
    assert "seen=3" in captured.err
    assert "pages=2" in captured.err
    assert "read=2" in captured.err
    assert "kept=1" in captured.err
    assert "Errors:" in captured.err
    assert "No fresh cards were captured in this run." in captured.err
    assert "Warnings:" in captured.err
    assert "LinkedIn timed out" in captured.err
