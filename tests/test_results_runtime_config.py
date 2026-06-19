"""Tests for results runtime config."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_hunter_agent import workspace_renderer, workspace_service


def test_results_page_uses_runtime_workspace_config():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results" / "results-page.js").read_text(
        encoding="utf-8"
    )
    results_html = (root / "templates" / "results.html").read_text(encoding="utf-8")

    assert "window.__JOB_HUNTER_WORKSPACE__" in results_html
    assert 'href="/settings#section-search"' in results_html
    assert 'class="rejection-panel-actions"' in results_html
    assert 'class="block-admin-tip"' in results_html
    assert results_html.index('class="rejection-panel-actions"') < results_html.index(
        'class="block-admin-tip"'
    )
    assert "SEEK Settings" not in results_html
    assert "LinkedIn Settings" not in results_html
    assert "Run Search Now" not in results_html
    assert "Edit Configuration" not in results_html
    assert "$WORKSPACE_RUN_ID_JSON" not in results_js
    assert "$VIEWED_BADGE_HTML_JSON" not in results_js
    assert "search_settings_" not in results_js
    assert "Run Search Now" not in results_js


def test_candidate_application_history_loader_failure_returns_original_records(capsys):
    records = [{"job_key": "seek:1"}, {"job_key": "seek:2"}]

    with patch(
        "job_hunter_agent.candidate_application_history.load_candidate_job_rejection_history",
        side_effect=RuntimeError("boom"),
    ):
        result = workspace_service._enrich_records_with_candidate_application_history(records)

    assert result is records
    assert result == [{"job_key": "seek:1"}, {"job_key": "seek:2"}]

    output = capsys.readouterr().out
    assert "[candidate_application_history] unavailable: boom" in output


def test_candidate_application_history_sync_runs_before_enrichment_when_enabled():
    records = [{"job_key": "seek:1"}]
    calls = []

    def fake_sync():
        calls.append("sync")

    def fake_load():
        calls.append("load")
        return [
            {
                "llm_company": "Acme",
                "llm_role": "Business Analyst",
                "llm_is_rejection": True,
                "llm_application_status": "rejection",
                "llm_confidence": "high",
                "llm_evidence": "Thanks for applying",
                "llm_needs_review": False,
            }
        ]

    def fake_enrich(items, history):
        calls.append("enrich")
        assert history
        return [{**items[0], "candidate_application_history": history[0]}]

    with (
        patch(
            "job_hunter_agent.workspace_service.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.workspace_service.get_candidate_application_history_sync_before_run",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.import_candidate_rejections_from_sheet",
            side_effect=fake_sync,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.load_candidate_job_rejection_history",
            side_effect=fake_load,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.enrich_records_with_application_history",
            side_effect=fake_enrich,
        ),
    ):
        result = workspace_service._enrich_records_with_candidate_application_history(records)

    assert calls == ["sync", "load", "enrich"]
    assert result[0]["candidate_application_history"]["llm_company"] == "Acme"


def test_candidate_application_history_sync_is_skipped_when_disabled():
    records = [{"job_key": "seek:1"}]

    with (
        patch(
            "job_hunter_agent.workspace_service.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.workspace_service.get_candidate_application_history_sync_before_run",
            return_value=False,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.import_candidate_rejections_from_sheet"
        ) as mock_sync,
        patch(
            "job_hunter_agent.candidate_application_history.load_candidate_job_rejection_history",
            return_value=[],
        ),
    ):
        result = workspace_service._enrich_records_with_candidate_application_history(records)

    assert result is records
    assert not mock_sync.called


def test_candidate_application_history_sync_failure_logs_warning_and_uses_local_store():
    records = [{"job_key": "seek:1"}]

    def fake_enrich(items, history):
        return [{**items[0], "candidate_application_history": history[0]}]

    with (
        patch(
            "job_hunter_agent.workspace_service.is_candidate_application_history_enabled",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.workspace_service.get_candidate_application_history_sync_before_run",
            return_value=True,
        ),
        patch(
            "job_hunter_agent.candidate_application_history.import_candidate_rejections_from_sheet",
            side_effect=RuntimeError("sheet unavailable"),
        ),
        patch(
            "job_hunter_agent.candidate_application_history.load_candidate_job_rejection_history",
            return_value=[
                {
                    "llm_company": "Acme",
                    "llm_role": "Business Analyst",
                    "llm_is_rejection": True,
                    "llm_application_status": "rejection",
                    "llm_confidence": "high",
                    "llm_evidence": "Thanks for applying",
                    "llm_needs_review": False,
                }
            ],
        ),
        patch(
            "job_hunter_agent.candidate_application_history.enrich_records_with_application_history",
            side_effect=fake_enrich,
        ),
        patch.object(workspace_service.logger, "warning") as mock_warning,
    ):
        result = workspace_service._enrich_records_with_candidate_application_history(records)

    assert result[0]["candidate_application_history"]["llm_company"] == "Acme"
    mock_warning.assert_called_once()
    assert "sheet unavailable" in str(mock_warning.call_args.args[1])


def test_rendered_workspace_html_content(tmp_path):
    mock_output_path = tmp_path / "mock_rendered_workspace.html"
    mock_run_started_at = datetime.now()
    mock_reference_time = datetime.now()

    mock_profile = {
        "match_levels": [
            {"minimum_score": 85, "label": "Strong match", "description": "High alignment"},
            {"minimum_score": 70, "label": "Good match", "description": "Solid alignment"},
            {"minimum_score": 55, "label": "Possible fit", "description": "Plausible fit"},
            {"minimum_score": 0, "label": "Stretch", "description": "Low alignment"},
        ],
        "search_settings": {
            "keywords": "Software Engineer",
            "locations": ["Sydney"],
            "date_range_days": 7,
        },
        "match_preferences": {
            "engagement_type": ["permanent"],
            "work_mode_preference": ["remote"],
            "prefer_sector": "any",
        },
        "salary_preferences": {
            "minimum_salary_yearly": 100000,
            "minimum_daily_rate": 0,
        },
    }

    mock_ui_labels_content = {
        "workspace_page_labels": {
            "hero_title": "Jobs Workspace",
            "potential_jobs_tab": "Potential Jobs",
            "applied_jobs_tab": "Applied",
            "hidden_jobs_tab": "Hidden",
            "match_controls_heading": "Match Controls",
            "reset_all_filters_button": "Reset All Filters",
            "sort_label": "Sort",
            "sort_option_best_match": "Best match first",
            "sort_option_newest": "Newest posted first",
            "sort_option_highest_salary": "Highest salary first",
            "jobs_per_page_label": "Jobs Per page",
            "filters_label": "Filters",
            "show_label": "Show",
            "show_option_all_potential": "All potential jobs",
            "show_option_matches_last_run": "Matches last run",
            "posted_label": "Posted",
            "type_label": "Type",
            "work_mode_label": "Work mode",
            "work_mode_option_any": "Any",
            "work_mode_option_remote": "Remote",
            "work_mode_option_hybrid": "Hybrid",
            "work_mode_option_on_site": "On-site",
            "sector_label": "Sector",
            "sector_option_any": "Any sector",
            "sector_option_public": "Public sector",
            "sector_option_private": "Private sector",
            "match_level_label": "Match level",
            "results_helper_copy": "Job sites often return broad results even when the search is correct. If a title clearly doesn&#8217;t match what you want, you can block similar roles directly from the title. This helps remove repeated noise from future results.",
            "results_helper_dismiss_button": "Dismiss",
            "applied_jobs_heading": "Applied Jobs",
            "applied_jobs_copy": "This area is for jobs where you have already sent your CV. They are tracked separately so they do not clutter the live shortlist.",
            "hidden_jobs_heading": "Hidden Jobs",
            "hidden_jobs_copy": "This area keeps roles you have intentionally pushed out of sight for now.",
            "search_settings_heading": "Search Settings",
            "search_settings_helper": "Shared search settings used across sources.",
            "keywords_label": "Keywords",
            "locations_label": "Locations",
            "work_type_sidebar_label": "Work type",
            "work_mode_sidebar_label": "Work mode",
            "sector_sidebar_label": "Sector",
            "salary_min_label": "Salary min",
            "date_range_label": "Date range",
            "last_run_heading": "Last Run",
            "crawler_stats_heading": "Crawler Stats",
            "crawler_stats_helper": "Cards seen is the number of source cards scanned. Ads reviewed is the smaller set where Job Hunter opened or evaluated more detail.",
            "applications_heading": "Applications",
            "run_efficiency_summary": "Run Efficiency",
            "show_hide_hint": "Show / hide",
            "run_efficiency_intro": "Search targets this run: ",
            "run_efficiency_separator": ". ",
            "how_match_levels_work_summary": "How Match Levels Work",
            "how_match_levels_work_copy": "Match levels are a guide, not a final verdict. The raw score is kept internally for sorting and test mode, while normal mode uses human-friendly bands so the workspace does not pretend to be more precise than it really is.",
            "rejection_panel_title": "Why isn&#39;t this a fit for you?",
            "rejection_panel_copy": "Choose required terms you do not want the app to accept again.",
            "rejection_how_this_works_summary": "How this works",
            "rejection_how_this_works_body": "If you save a term here, future jobs are filtered only when it looks required. To block any mention, use global description blockers in Settings.",
            "rejection_loading_suggestions": "Loading suggestions&#8230;",
            "rejection_add_own_term_label": "Add your own required term",
            "rejection_add_own_term_placeholder": "e.g. SAP, payroll, NV1 clearance",
            "rejection_add_button": "Add",
            "rejection_save_button": "Save &amp; Continue",
            "rejection_skip_button": "Continue Without Extra Blocks",
            "rejection_cancel_button": "Cancel",
            "rejection_admin_tip_prefix": "Need to edit saved rules? ",
            "rejection_admin_tip_link_text": "Open Settings",
        }
    }

    captured_tools = {}

    def fake_render_section(
        title,
        records,
        empty_message,
        scoring_profile=None,
        applied_pool=None,
        history_clusters=None,
        debug_mode=None,
        header_tools_html="",
    ):
        if title == "Job Results":
            captured_tools["header_tools_html"] = header_tools_html
        return "<section>Rendered Section</section>"

    with (
        patch("job_hunter_agent.profile_store.load_profile", return_value=mock_profile),
        patch("job_hunter_agent.user_settings.get_workspace_minimum_score", return_value=55),
        patch(
            "job_hunter_agent.workspace_data.build_workspace_record_sets",
            return_value={
                "shortlist_records": [],
                "current_records": [],
                "archive_records": [],
                "recent_archive_records": [],
                "stale_archive_records": [],
                "applied_records": [],
                "hidden_records": [],
            },
        ),
        patch("job_hunter_agent.history.build_history_cluster_index", return_value={}),
        patch(
            "job_hunter_agent.workspace_renderer.render_score_filter_options",
            return_value="<option>Score Options</option>",
        ),
        patch(
            "job_hunter_agent.workspace_renderer.render_posted_filter_options",
            return_value="<option>Posted Options</option>",
        ),
        patch(
            "job_hunter_agent.workspace_renderer.render_work_type_filter_options",
            return_value="<option>Work Type Options</option>",
        ),
        patch("job_hunter_agent.workspace_service.render_section", side_effect=fake_render_section),
        patch(
            "job_hunter_agent.workspace_renderer.render_match_level_guide_html",
            return_value="<div>Match Level Guide</div>",
        ),
        patch(
            "job_hunter_agent.workspace_service._format_common_search_preferences",
            return_value=("Permanent", "Remote", "Any"),
        ),
        patch(
            "job_hunter_agent.workspace_service._format_salary_min_label",
            return_value="$100,000/yr",
        ),
        patch(
            "job_hunter_agent.workspace_renderer._workspace_ui_labels",
            return_value=mock_ui_labels_content,
        ),
        patch(
            "job_hunter_agent.paths.RESULTS_TEMPLATE_PATH", new_callable=MagicMock
        ) as mock_results_template_path,
    ):
        mock_results_template_path.read_text.return_value = (
            Path(__file__).parent.parent / "templates" / "results.html"
        ).read_text(encoding="utf-8")

        workspace_service.render_html(
            output_path=mock_output_path,
            kept_records=[],
            run_started_at=mock_run_started_at,
            date_range_days=7,
            sort_newest_first=True,
            run_stats={},
            job_history={},
            applied_job_keys=set(),
            hidden_job_keys=set(),
            workspace_reference_at=mock_reference_time,
        )

        rendered_html = mock_output_path.read_text(encoding="utf-8")

        assert '<h1 class="ws-hero-title">Jobs Workspace</h1>' in rendered_html
        assert (
            '<button class="scope-tab is-active" type="button" data-workspace-target="potential">Potential Jobs (0)</button>'
            in rendered_html
        )
        assert "Cards seen is the number of source cards scanned." in rendered_html
        assert "Ads reviewed is the smaller set" in rendered_html
        assert (
            '<span class="snapshot-meta-label">Work type</span><span class="snapshot-meta-value">Permanent</span>'
            in rendered_html
        )
        assert (
            '<span class="snapshot-meta-label">Work mode</span><span class="snapshot-meta-value">Remote</span>'
            in rendered_html
        )
        assert (
            '<span class="snapshot-meta-label">Sector</span><span class="snapshot-meta-value">Any</span>'
            in rendered_html
        )
        assert (
            '<span class="snapshot-meta-label">Salary min</span><span class="snapshot-meta-value">$100,000/yr</span>'
            in rendered_html
        )
        assert "Sort and display" not in rendered_html
        assert '<h3 class="workspace-control-group-title">Sort</h3>' in rendered_html
        assert '<h3 class="workspace-control-group-title">Filters</h3>' in rendered_html
        assert 'aria-label="Show"' in rendered_html
        assert 'aria-label="Posted"' in rendered_html
        assert 'aria-label="Type"' in rendered_html
        assert 'aria-label="Work mode"' in rendered_html
        assert 'aria-label="Sector"' in rendered_html
        assert 'aria-label="Match level"' in rendered_html
        assert 'id="page_size_select"' not in rendered_html
        assert 'id="page_size_select"' in captured_tools["header_tools_html"]
        assert "12 jobs per page" in captured_tools["header_tools_html"]

        # Assert runtime config injection structure
        assert "window.__JOB_HUNTER_WORKSPACE__" in rendered_html
        assert "labels" in rendered_html
        assert "rejectionLoadingSuggestions" in rendered_html

        assert "$LABEL_WS_HERO_TITLE" not in rendered_html
        assert "$SHORTLIST_COUNT" not in rendered_html
        assert "$CURRENT_SECTION_HTML" not in rendered_html

    mock_output_path.unlink()
