"""Tests for results runtime config."""

import re
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_hunter_agent import workspace_rebuild_service, workspace_renderer, workspace_service


def test_format_llm_usage_metric_compacts_token_counts_and_rounds_currency():
    assert workspace_service.format_llm_usage_metric(999) == "999"
    assert workspace_service.format_llm_usage_metric(84_188) == "84.2K"
    assert workspace_service.format_llm_usage_metric(5_126_350) == "5.13M"
    assert workspace_service.format_llm_usage_metric(2_000_000_000) == "2B"
    assert workspace_service.format_llm_usage_metric(3.8084, currency=True) == "$3.81"
    assert workspace_service.format_llm_usage_metric(0.0633, currency=True) == "$0.06"


def test_results_page_uses_runtime_workspace_config():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results" / "results-page.js").read_text(
        encoding="utf-8"
    )
    results_html = (root / "templates" / "results.html").read_text(encoding="utf-8")

    assert "window.__JOB_HUNTER_WORKSPACE__" in results_html
    assert 'href="/settings#section-search"' in results_html
    assert 'class="rejection-panel-actions"' in results_html
    assert 'class="jh-button jh-button--primary rejection-btn-save"' in results_html
    assert 'class="jh-button jh-button--secondary rejection-btn-cancel"' in results_html
    assert 'class="block-admin-tip"' in results_html
    assert 'id="reset_workspace_filters"' in results_html
    assert 'class="jh-button jh-button--neutral jh-button--compact workspace-text-action workspace-text-action--reset"' in results_html
    assert 'class="workspace-text-action__icon"' in results_html
    assert 'class="ws-hero-panel"' not in results_html
    assert 'class="ws-hero-title"' not in results_html
    assert "workspace-controls-panel" in results_html
    assert "$RUN_EFFICIENCY_PANEL_HTML" in results_html
    assert "$MATCH_LEVEL_GUIDE_HTML" not in results_html
    assert 'How Match Levels Work' not in results_html
    assert results_html.index('class="rejection-panel-actions"') < results_html.index(
        'class="block-admin-tip"'
    )
    assert "SEEK Settings" not in results_html
    assert "LinkedIn Settings" not in results_html
    assert "Run Search Now" not in results_html
    assert "Edit Configuration" not in results_html
    assert "$LABEL_WS_APPLIED_JOBS_HEADING" not in results_html
    assert "$LABEL_WS_APPLIED_JOBS_COPY" not in results_html
    assert "$LABEL_WS_HIDDEN_JOBS_HEADING" not in results_html
    assert "$LABEL_WS_HIDDEN_JOBS_COPY" not in results_html
    assert "$WORKSPACE_RUN_ID_JSON" not in results_js
    assert "$VIEWED_BADGE_HTML_JSON" not in results_js
    assert "search_settings_" not in results_js
    assert "Run Search Now" not in results_js
    assert "WORKSPACE_PAGINATION_KEY" in results_js
    assert "loadWorkspacePagination();" in results_js
    assert "saveWorkspacePagination();" in results_js
    assert "window.location.reload();" in results_js


def test_results_page_related_card_action_focuses_existing_workspace_card():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results" / "results-page.js").read_text(
        encoding="utf-8"
    )

    assert "function focusRelatedCard(action)" in results_js
    assert "data-related-card-target" in results_js
    assert "setActiveWorkspace(targetWorkspace, true, false)" in results_js
    assert "target.scrollIntoView({ behavior: 'smooth', block: 'start' })" in results_js
    assert "target.classList.add('is-related-target')" in results_js


def test_workspace_page_size_select_is_content_sized_in_pagination_cluster():
    root = Path(__file__).resolve().parent.parent
    workspace_css = (
        root / "templates" / "static" / "workspace" / "workspace-page.css"
    ).read_text(encoding="utf-8")

    compact_rule = re.search(
        r"\.results-header \.panel-select-control--page-size \.jh-select \{(?P<body>.*?)\n\}",
        workspace_css,
        flags=re.DOTALL,
    )

    assert compact_rule is not None
    assert "width: auto;" in compact_rule.group("body")
    assert "min-width: 0;" in compact_rule.group("body")


def test_workspace_pagination_footer_aligns_with_panel_content_and_separates_counts():
    root = Path(__file__).resolve().parent.parent
    workspace_css = (
        root / "templates" / "static" / "workspace" / "workspace-page.css"
    ).read_text(encoding="utf-8")

    footer_rule = re.search(
        r"\.results-pagination-footer \{(?P<body>.*?)\n\}",
        workspace_css,
        flags=re.DOTALL,
    )
    controls_rule = re.search(
        r"\.results-pagination-footer \.section-tools \{(?P<body>.*?)\n\}",
        workspace_css,
        flags=re.DOTALL,
    )

    assert footer_rule is not None
    assert "padding-inline: var(--surface-gap-lg);" in footer_rule.group("body")
    assert controls_rule is not None
    assert "display: flex;" in controls_rule.group("body")
    assert "justify-content: flex-end;" in controls_rule.group("body")
    assert "gap: var(--control-space-md);" in controls_rule.group("body")


def test_render_section_uses_results_header_sibling_layout_for_tools_and_pagination():
    with patch(
        "job_hunter_agent.workspace_renderer.render_job_card",
        return_value='<article class="job-card">Card</article>',
    ):
        html = workspace_renderer.render_section(
            "Job Results",
            [{"job_key": "seek:1"}],
            "No jobs right now.",
            header_tools_html=workspace_renderer.render_page_size_select_html(),
            header_nav_html=workspace_renderer.render_workspace_tabs_html(4, 0, 0),
        )

    assert 'class="results-header"' in html
    assert 'class="results-header__left"' in html
    assert 'class="scope-tabs"' in html
    assert 'class="section-head-tools"' in html
    assert 'class="results-section-panel"' in html
    assert 'class="results-section-body"' in html
    assert 'class="panel-select-control panel-select-control--page-size"' in html
    assert 'class="pagination-label pagination-page-label"' in html
    assert 'class="pagination-match-count"' in html
    assert 'section-head--with-tools' not in html
    assert re.search(
        r'<div class="results-header"><div class="results-header__left">.*?class="scope-tabs".*?</div><div class="section-tools">.*?class="pagination-match-count".*?class="section-head-tools".*?class="pagination-label pagination-page-label"',
        html,
    )
    assert 'class="results-pagination-footer"' in html
    assert html.count('data-page-direction="prev"') == 2
    assert html.count('data-page-direction="next"') == 2


def test_render_empty_results_keeps_count_controls_but_omits_footer_pagination():
    html = workspace_renderer.render_section(
        "Job Results",
        [],
        "No jobs right now.",
        header_tools_html=workspace_renderer.render_page_size_select_html(),
        header_nav_html=workspace_renderer.render_workspace_tabs_html(0, 0, 0),
    )

    assert 'data-section-id="job-results"' in html
    assert 'class="pagination-label pagination-page-label"' in html
    assert 'class="pagination-match-count"' in html
    assert 'data-page-direction="prev"' in html
    assert 'data-page-direction="next"' in html
    assert 'class="empty-state">No jobs right now.</p>' in html
    assert 'class="results-pagination-footer"' not in html


def test_render_results_includes_hidden_empty_state_for_filtered_zero_matches():
    with patch(
        "job_hunter_agent.workspace_renderer.render_job_card",
        return_value='<article class="job-card">Card</article>',
    ):
        html = workspace_renderer.render_section(
            "Job Results",
            [{"job_key": "seek:1"}],
            "No jobs match these filters.",
            header_tools_html=workspace_renderer.render_page_size_select_html(),
            header_nav_html=workspace_renderer.render_workspace_tabs_html(1, 0, 0),
        )

    assert '<p class="empty-state" hidden>No jobs match these filters.</p>' in html


def test_pagination_hides_page_controls_at_zero_and_footer_on_single_page():
    root = Path(__file__).resolve().parent.parent
    results_js = (
        root / "templates" / "static" / "results" / "results-page.js"
    ).read_text(encoding="utf-8")

    assert "const totalPages = matchingCards.length ? Math.ceil(matchingCards.length / pageSize) : 0;" in results_js
    assert "pageLabel.hidden = matchingCards.length === 0;" in results_js
    assert "prevButton.hidden = matchingCards.length === 0;" in results_js
    assert "nextButton.hidden = matchingCards.length === 0;" in results_js
    assert "emptyState.hidden = matchingCards.length !== 0;" in results_js
    assert "footer.hidden = totalPages <= 1;" in results_js
    assert "usedFooterPagination" in results_js
    assert "firstVisibleCard.scrollIntoView({ block: 'start' });" in results_js


def test_render_section_keeps_multiple_job_cards_inside_shared_results_panel():
    with patch(
        "job_hunter_agent.workspace_renderer.render_job_card",
        side_effect=[
            '<article class="job-card" id="card-1">Card 1</article>',
            '<article class="job-card" id="card-2">Card 2</article>',
        ],
    ):
        html = workspace_renderer.render_section(
            "Job Results",
            [{"job_key": "seek:1"}, {"job_key": "seek:2"}],
            "No jobs right now.",
            header_tools_html=workspace_renderer.render_page_size_select_html(),
            header_nav_html=workspace_renderer.render_workspace_tabs_html(2, 0, 0),
        )

    assert 'class="results-section-panel"' in html
    assert 'class="results-section-body"' in html
    assert '<div class="job-grid">' in html
    assert html.count('class="job-card"') == 2
    assert html.index('class="results-header"') < html.index('class="results-section-body"')


def test_render_section_passes_debug_mode_through_to_job_cards():
    with patch(
        "job_hunter_agent.workspace_renderer.render_job_card",
        return_value='<article class="job-card">Card</article>',
    ) as render_job_card:
        workspace_renderer.render_section(
            "Job Results",
            [{"job_key": "seek:1"}],
            "No jobs right now.",
            debug_mode=True,
            header_tools_html=workspace_renderer.render_page_size_select_html(),
            header_nav_html=workspace_renderer.render_workspace_tabs_html(1, 0, 0),
        )

    assert render_job_card.call_args.kwargs["debug_mode"] is True


def test_results_page_javascript_moves_reviewed_cards_without_waiting_for_workspace_reload():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results" / "results-page.js").read_text(
        encoding="utf-8"
    )

    assert "const WORKSPACE_PAGINATION_KEY" in results_js
    assert "window.localStorage.removeItem(WORKSPACE_PAGINATION_KEY);" in results_js
    assert "loadWorkspacePagination();" in results_js
    assert "setActiveWorkspace((window.location.hash || '#potential').replace('#', ''), false, false);" in results_js
    assert re.search(
        r"if \(payload\?\.reload_workspace && !payload\?\.workspace_refresh_async\) \{\s+saveWorkspaceFilters\(\);\s+saveWorkspacePagination\(\);\s+window\.location\.reload\(\);",
        results_js,
    )
    assert "function moveCardAfterReview(card, action)" in results_js
    assert "targetGrid.appendChild(card);" in results_js
    assert "moveCardAfterReview(card, action);" in results_js
    assert "reloadAfterWorkspaceRefresh(payload?.workspace_refresh_id);" not in results_js


def test_results_styles_keep_debug_match_tile_number_visible():
    root = Path(__file__).resolve().parent.parent
    results_css = (root / "templates" / "static" / "results" / "results-page.css").read_text(
        encoding="utf-8"
    )

    assert ".match-tile-number {" in results_css
    assert "display: block;" in results_css


def test_job_link_click_marks_viewed_without_immediate_resort():
    root = Path(__file__).resolve().parent.parent
    results_js = (root / "templates" / "static" / "results" / "results-page.js").read_text(
        encoding="utf-8"
    )

    start = results_js.index("function markCardViewed")
    end = results_js.index("async function hydrateViewedState")
    mark_viewed_js = results_js[start:end]

    assert "card.dataset.viewed = '1';" in mark_viewed_js
    assert "badges.insertAdjacentHTML('beforeend', WORKSPACE_CONTEXT.viewedBadgeHtml || '');" in mark_viewed_js
    assert "applyWorkspaceControls();" not in mark_viewed_js
    assert "markCardViewed(link);" in results_js
    assert "sendViewedBeacon(link);" in results_js


def test_candidate_application_history_loader_failure_is_not_silently_masked():
    records = [{"job_key": "seek:1"}, {"job_key": "seek:2"}]

    with patch(
        "job_hunter_agent.candidate_application_history.load_candidate_job_rejection_history",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            workspace_service._enrich_records_with_candidate_application_history(records)


def test_candidate_application_history_enrichment_never_syncs_from_sheet():
    records = [{"job_key": "seek:1"}]

    with (
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
        "work_mode_labels": {
            "remote_label": "Remote",
            "hybrid_label": "Hybrid",
            "onsite_label": "On-site",
        },
        "workspace_card_labels": {
            "applied_badge": "Applied",
            "hidden_badge": "Hidden",
        },
        "workspace_page_labels": {
            "hero_title": "Jobs Workspace",
            "potential_jobs_tab": "Potential Jobs",
            "top_level_workspace_views_aria_label": "Top-level workspace views",
            "match_controls_heading": "Match Controls",
            "reset_all_filters_button": "Reset All Filters",
            "sort_label": "Sort",
            "sort_option_best_match": "Best match first",
            "sort_option_newest": "Newest posted first",
            "sort_option_highest_salary": "Highest salary first",
            "jobs_per_page_label": "Jobs Per page",
            "filters_label": "Filters",
            "quick_filters_label": "Quick filters",
            "quick_filter_new_to_you": "New to you",
            "quick_filter_direct_employer": "Direct employer",
            "quick_filter_easy_apply": "Easy apply",
            "more_filters_label": "More filters",
            "job_boards_label": "Job boards",
            "job_boards_all_label": "All",
            "show_label": "Show",
            "show_option_all_potential": "All potential jobs",
            "show_option_matches_last_run": "Matches last run",
            "posted_label": "Posted",
            "type_label": "Type",
            "work_mode_label": "Work mode",
            "work_mode_option_any": "Any",
            "sector_label": "Sector",
            "sector_option_any": "Any sector",
            "sector_option_public": "Public sector",
            "sector_option_private": "Private sector",
            "match_level_label": "Match level",
            "potential_jobs_empty_state": "No shortlist matches right now. Check your filters or broaden your search settings.",
            "results_helper_copy": "Job sites often return broad results even when the search is correct. If a title clearly doesn't match what you want, you can block similar roles directly from the title. This helps remove repeated noise from future results.",
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
            "last_run_cards_seen_label": "Jobs found",
            "last_run_details_checked_label": "Job details checked",
            "last_run_accepted_label": "Accepted",
            "last_run_rejected_label": "Rejected",
            "last_run_llm_cost_label": "LLM cost",
            "last_run_input_tokens_label": "Input tokens",
            "last_run_output_tokens_label": "Output tokens",
            "workspace_status_heading": "Workspace",
            "workspace_status_helper": "These counts describe the jobs currently in your workspace.",
            "workspace_visible_label": "Visible matches",
            "workspace_new_label": "New to you",
            "workspace_opened_label": "Opened by you",
            "workspace_saved_label": "Saved from earlier run",
            "lifetime_llm_heading": "Total LLM usage",
            "lifetime_llm_helper": "Total recorded LLM usage.",
            "lifetime_llm_cost_label": "Total LLM cost",
            "lifetime_input_tokens_label": "Total input tokens",
            "lifetime_output_tokens_label": "Total output tokens",
            "run_efficiency_summary": "Run Efficiency",
            "show_hide_hint": "Show / hide",
            "run_efficiency_intro": "Search targets this run: ",
            "run_efficiency_separator": ". ",
            "how_match_levels_work_summary": "How scoring works",
            "how_match_levels_work_copy": "Job Hunter compares each job's requirements with evidence in your profile. Mandatory requirements and stronger evidence carry more weight. Missing, partial, or weak mandatory requirements lower the result, which is then grouped into the match level shown on the card. Location, posted date, viewed status, and Easy or Quick Apply help you review jobs, but they do not prove fit.",
            "rejection_panel_title": "Why isn&#39;t this a fit for you?",
            "rejection_panel_copy": "Choose required terms you do not want the app to accept again.",
            "rejection_how_this_works_summary": "How this works",
            "rejection_how_this_works_body": "If you save a term here, future jobs are filtered only when it looks required. To block any mention, use global description blockers in Settings.",
            "rejection_loading_suggestions": "Loading suggestions&#8230;",
            "rejection_add_own_term_label": "Add your own required term",
            "rejection_add_own_term_placeholder": "e.g. SAP, payroll, cold calling",
            "rejection_add_button": "Add",
            "rejection_save_button": "Save &amp; Continue",
            "rejection_skip_button": "Continue Without Extra Blocks",
            "rejection_cancel_button": "Cancel",
            "rejection_admin_tip_prefix": "Need to edit saved rules? ",
            "rejection_admin_tip_link_text": "Open Settings",
            "profile_gap_added_new_template": "Added {target} to your profile",
            "profile_gap_added_existing_template": "Added {fact} under {target}",
            "profile_gap_already_present_template": "{fact} is already in your profile",
            "profile_gap_not_have_saved_template": "Marked {fact} as not in your profile",
            "profile_gap_error_label": "Could not update profile.",
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
        header_nav_html="",
    ):
        if title == "Job Results":
            captured_tools["header_tools_html"] = header_tools_html
            captured_tools["header_nav_html"] = header_nav_html
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
            "job_hunter_agent.workspace_service.get_cost_summary",
            return_value={
                "grand_total_usd": 0.0633,
                "grand_input_tokens": 1_140_569,
                "grand_output_tokens": 2_000_000_000,
            },
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
            run_stats={
                "llm_total_cost_usd": 3.8084,
                "llm_total_input_tokens": 84_188,
                "llm_total_output_tokens": 5_126_350,
            },
            job_history={},
            applied_job_keys=set(),
            hidden_job_keys=set(),
            workspace_reference_at=mock_reference_time,
        )

        rendered_html = mock_output_path.read_text(encoding="utf-8")

        assert 'class="ws-hero-title"' not in rendered_html
        assert 'class="ws-hero-panel"' not in rendered_html
        assert 'workspace-controls-panel' in rendered_html
        assert rendered_html.index('workspace-controls-panel') < rendered_html.index(
            "<section>Rendered Section</section>"
        )
        assert "Run Efficiency" not in rendered_html
        assert "How scoring works" in rendered_html
        assert "How Match Levels Work" not in rendered_html
        assert "Mandatory requirements and stronger evidence carry more weight." in rendered_html
        assert "Easy or Quick Apply help you review jobs, but they do not prove fit." in rendered_html
        assert (
            '<button class="scope-tab is-active" type="button" '
            'data-workspace-target="potential" data-tab-label="Potential Jobs">'
            "Potential Jobs (0)</button>" in captured_tools["header_nav_html"]
        )
        assert 'data-workspace-target="potential"' in captured_tools["header_nav_html"]
        assert "Jobs found" in rendered_html
        assert "Job details checked" in rendered_html
        assert "Total recorded LLM usage." in rendered_html
        assert "LLM cost" in rendered_html
        assert "$3.81" in rendered_html
        assert "Input tokens" in rendered_html
        assert ">84.2K<" in rendered_html
        assert "Output tokens" in rendered_html
        assert ">5.13M<" in rendered_html
        assert "$0.06" in rendered_html
        assert ">1.14M<" in rendered_html
        assert ">2B<" in rendered_html
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
        assert 'id="reset_workspace_filters"' in rendered_html
        assert ">Reset All Filters<" in rendered_html
        assert 'class="workspace-text-action__icon"' in rendered_html
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


def test_workspace_rebuild_refreshes_llm_totals_from_current_audit_rows(monkeypatch, tmp_path):
    captured = {}
    workspace_path = tmp_path / "workspace_results.html"

    monkeypatch.setattr(workspace_rebuild_service, "configure_console_output", lambda: None)
    monkeypatch.setattr(workspace_rebuild_service, "get_user_id_for_runtime", lambda: "user-1")
    monkeypatch.setattr(workspace_rebuild_service, "load_profile", lambda: {})
    monkeypatch.setattr(
        workspace_rebuild_service,
        "get_search_settings",
        lambda profile: {"date_range_days": 7, "sort_newest_first": True},
    )
    monkeypatch.setattr(
        workspace_rebuild_service,
        "load_run_stats",
        lambda: {
            "run_started_at": "2026-07-10T18:28:58+10:00",
            "run_finished_at": "2026-07-10T18:30:00+10:00",
            "seek_max_pages": 1,
            "llm_total_cost_usd": 0.999999,
            "llm_total_input_tokens": None,
            "llm_total_output_tokens": None,
        },
    )
    monkeypatch.setattr(workspace_rebuild_service, "get_manual_skip_sets", lambda profile: (set(), set()))
    monkeypatch.setattr(workspace_rebuild_service, "load_job_history", lambda: {})
    monkeypatch.setattr(
        workspace_rebuild_service,
        "load_audit_rows",
        lambda: [
            {
                "source": "seek",
                "search_location": "Sydney",
                "page": 1,
                "decision": "KEEP",
                "llm_cost_usd": 0.001234,
                "llm_input_tokens": 1200,
                "llm_output_tokens": 220,
            },
            {
                "source": "linkedin",
                "search_location": "Sydney",
                "page": 1,
                "decision": "REJECT",
                "llm_cost_usd": 0.002001,
                "llm_input_tokens": 800,
                "llm_output_tokens": 125,
            },
        ],
    )
    monkeypatch.setattr(
        workspace_service,
        "load_last_kept_records",
        lambda: [{"job_key": "seek:1"}, {"job_key": "linkedin:1"}],
    )
    monkeypatch.setattr(workspace_service, "load_saved_workspace_pool", lambda: [])
    monkeypatch.setattr(
        workspace_rebuild_service,
        "write_run_stats",
        lambda payload: captured.setdefault("written_run_stats", payload),
    )
    monkeypatch.setattr(workspace_rebuild_service, "get_workspace_results_path", lambda: workspace_path)

    def fake_render_html(
        output_path,
        kept_records,
        run_started_at,
        date_range_days,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    ):
        captured["render_run_stats"] = run_stats

    monkeypatch.setattr(workspace_service, "render_html", fake_render_html)

    result = workspace_rebuild_service.rebuild_workspace_results(
        reason="test rebuild refreshes llm totals"
    )

    assert result == str(workspace_path)
    assert captured["written_run_stats"]["llm_total_cost_usd"] == 0.003235
    assert captured["written_run_stats"]["llm_total_input_tokens"] == 2000
    assert captured["written_run_stats"]["llm_total_output_tokens"] == 345
    assert captured["render_run_stats"]["llm_total_cost_usd"] == 0.003235
    assert captured["render_run_stats"]["llm_total_input_tokens"] == 2000
    assert captured["render_run_stats"]["llm_total_output_tokens"] == 345


def test_workspace_rebuild_renders_saved_workspace_pool_when_present(monkeypatch, tmp_path):
    captured = {}
    workspace_path = tmp_path / "workspace_results.html"
    saved_pool = [{"job_key": "linkedin:saved-1"}, {"job_key": "linkedin:saved-2"}]
    latest_run_keeps = [{"job_key": "linkedin:audit-1"}]

    monkeypatch.setattr(workspace_rebuild_service, "configure_console_output", lambda: None)
    monkeypatch.setattr(workspace_rebuild_service, "get_user_id_for_runtime", lambda: "user-1")
    monkeypatch.setattr(workspace_rebuild_service, "load_profile", lambda: {})
    monkeypatch.setattr(
        workspace_rebuild_service,
        "get_search_settings",
        lambda profile: {"date_range_days": 7, "sort_newest_first": True},
    )
    monkeypatch.setattr(
        workspace_rebuild_service,
        "load_run_stats",
        lambda: {
            "run_started_at": "2026-07-10T18:28:58+10:00",
            "run_finished_at": "2026-07-10T18:30:00+10:00",
            "seek_max_pages": 1,
        },
    )
    monkeypatch.setattr(workspace_rebuild_service, "get_manual_skip_sets", lambda profile: (set(), set()))
    monkeypatch.setattr(workspace_rebuild_service, "load_job_history", lambda: {})
    monkeypatch.setattr(
        workspace_rebuild_service,
        "load_audit_rows",
        lambda: [{"source": "linkedin", "search_location": "Sydney", "page": 1, "decision": "KEEP"}],
    )
    monkeypatch.setattr(workspace_service, "load_last_kept_records", lambda: latest_run_keeps)
    monkeypatch.setattr(workspace_service, "load_saved_workspace_pool", lambda: saved_pool)
    monkeypatch.setattr(workspace_rebuild_service, "write_run_stats", lambda payload: None)
    monkeypatch.setattr(workspace_rebuild_service, "get_workspace_results_path", lambda: workspace_path)

    def fake_render_html(
        output_path,
        kept_records,
        run_started_at,
        date_range_days,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    ):
        captured["render_kept_records"] = kept_records

    monkeypatch.setattr(workspace_service, "render_html", fake_render_html)

    result = workspace_rebuild_service.rebuild_workspace_results(reason="test rebuild uses pool")

    assert result == str(workspace_path)
    assert captured["render_kept_records"] == saved_pool
