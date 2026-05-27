"""Tests for scrape finalize."""



from __future__ import annotations



from datetime import datetime, timezone



from job_hunter_agent.database import db_conn

from job_hunter_agent.run_context import ScrapeRunContext

from job_hunter_agent import scrape_finalize

from job_hunter_agent import workspace_service

from job_hunter_agent.paths import LOCAL_USER_ID





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





def test_finalize_scrape_run_writes_outputs(monkeypatch, tmp_path, capsys):

    context = _build_context()

    workspace_path = tmp_path / "workspace.html"



    calls: list[tuple[str, object]] = []



    with db_conn() as conn:

        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (LOCAL_USER_ID,))



    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)

    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: [*records, {"job_key": "deduped"}])

    monkeypatch.setattr(scrape_finalize.workspace_service, "build_run_stats", lambda *args: {"run_started_at": "2026-05-16T08:12:40", "cards_seen": 1})

    monkeypatch.setattr(scrape_finalize.workspace_service, "render_html", lambda *args: calls.append(("render_html", args)))

    monkeypatch.setattr(scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload)))

    monkeypatch.setattr(scrape_finalize, "save_job_history", lambda payload: calls.append(("save_job_history", payload)))

    monkeypatch.setattr(scrape_finalize, "write_debug_json", lambda payload: calls.append(("write_debug_json", payload)))

    monkeypatch.setattr(scrape_finalize, "write_run_stats", lambda payload: calls.append(("write_run_stats", payload)))

    monkeypatch.setattr(scrape_finalize, "write_review_data", lambda payload: calls.append(("write_review_data", payload)))

    monkeypatch.setattr(scrape_finalize, "build_review_data", lambda audit_rows, skill_observations, profile: {

        "audit_count": len(audit_rows),

        "skill_count": len(skill_observations),

        "profile_name": profile["name"],

    })



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

    assert any(name == "write_review_data" for name, _ in calls)

    assert any(name == "render_html" for name, _ in calls)



    output = capsys.readouterr().out

    assert "Saved 2 jobs to" in output

    assert "Saved 1 audit rows to" in output





def test_finalize_scrape_run_preserves_previous_workspace_when_no_audit_rows(monkeypatch, tmp_path, capsys):

    context = _build_context()

    context.previous_audit_rows = [{"job_key": "job:old", "decision": "KEEP", "run_started_at": context.run_iso}]

    context.previous_run_stats = {"run_started_at": "2026-05-15T08:12:40"}

    workspace_path = tmp_path / "workspace.html"



    calls: list[tuple[str, object]] = []



    with db_conn() as conn:

        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (LOCAL_USER_ID,))



    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)

    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: records)

    monkeypatch.setattr(scrape_finalize.workspace_service, "load_last_kept_records", lambda *args, **kwargs: [{"job_key": "job:old"}])

    monkeypatch.setattr(scrape_finalize.workspace_service, "render_html", lambda *args: calls.append(("render_html", args)))

    monkeypatch.setattr(scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload)))

    monkeypatch.setattr(scrape_finalize, "save_job_history", lambda payload: calls.append(("save_job_history", payload)))

    monkeypatch.setattr(scrape_finalize, "write_debug_json", lambda payload: calls.append(("write_debug_json", payload)))

    monkeypatch.setattr(scrape_finalize, "write_run_stats", lambda payload: calls.append(("write_run_stats", payload)))

    monkeypatch.setattr(scrape_finalize, "write_review_data", lambda payload: calls.append(("write_review_data", payload)))



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



    output = capsys.readouterr().out

    assert "[RUN][ERROR] No fresh cards were captured in this run." in output

    assert "previous workspace state was preserved" in output





def test_finalize_scrape_run_marks_empty_first_run_as_error(monkeypatch, tmp_path, capsys):

    context = _build_context()

    workspace_path = tmp_path / "workspace.html"



    calls: list[tuple[str, object]] = []



    with db_conn() as conn:

        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (LOCAL_USER_ID,))



    monkeypatch.setattr(scrape_finalize, "get_workspace_results_path", lambda: workspace_path)

    monkeypatch.setattr(scrape_finalize, "deduplicate_across_sources", lambda records: records)

    monkeypatch.setattr(scrape_finalize.workspace_service, "build_run_stats", lambda *args: {"run_started_at": "2026-05-16T08:12:40", "cards_seen": 0})

    monkeypatch.setattr(scrape_finalize.workspace_service, "render_html", lambda *args: calls.append(("render_html", args)))

    monkeypatch.setattr(scrape_finalize, "save_llm_cache", lambda payload: calls.append(("save_llm_cache", payload)))

    monkeypatch.setattr(scrape_finalize, "save_job_history", lambda payload: calls.append(("save_job_history", payload)))

    monkeypatch.setattr(scrape_finalize, "write_debug_json", lambda payload: calls.append(("write_debug_json", payload)))

    monkeypatch.setattr(scrape_finalize, "write_run_stats", lambda payload: calls.append(("write_run_stats", payload)))

    monkeypatch.setattr(scrape_finalize, "write_review_data", lambda payload: calls.append(("write_review_data", payload)))



    workspace_result = scrape_finalize.finalize_scrape_run(

        context,

        kept_records=[],

        audit_rows=[],

        skill_observations=[],

    )



    assert workspace_result == str(workspace_path)

    assert any(name == "write_run_stats" for name, _ in calls)

    output = capsys.readouterr().out

    assert "[RUN][ERROR] No fresh cards were captured in this run." in output





def test_build_run_stats_counts_unique_pages_across_sources():

    run_started_at = datetime(2026, 5, 16, 8, 12, 40, tzinfo=timezone.utc)

    run_finished_at = datetime(2026, 5, 16, 8, 14, 10, tzinfo=timezone.utc)



    stats = workspace_service.build_run_stats(

        audit_rows=[

            {"source": "seek", "search_location": "Sydney", "page": 1, "decision": "KEEP"},

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

