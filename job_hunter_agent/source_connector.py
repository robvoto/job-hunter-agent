"""
Main job-source connector and workspace builder.

Main goals:
- fetch current job listings from all enabled source implementations
- apply deterministic filtering and optional LLM fit review
- persist audit data, run stats, review insights, and workspace HTML

Notes:
- this file orchestrates individual source connectors (e.g. SEEK, LinkedIn)
- the normalized record shape is intended to be reusable for additional sources
"""

import sys
from datetime import datetime
from typing import Any, Dict, List

from job_hunter_agent.user_settings import get_workspace_minimum_score
from job_hunter_agent import workspace_data
from job_hunter_agent.capability_matching import (
    build_risk_and_missing_evidence,
    description_watchout_reasons,
    find_profile_capability_matches,
    reviewed_signal_matches_for_text,
)
from job_hunter_agent.workspace_renderer import render_job_card, render_posted_filter_options, visible_fit_reasons
from job_hunter_agent.description_trust import (
    full_description_confidence,
    get_trusted_full_description,
    is_description_trusted,
)
from job_hunter_agent.fit_scoring import build_fit_highlights, fit_score, fit_score_breakdown
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.job_identity import deduplicate_across_sources
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_DEBUG,
    CLI_FLAG_NO_LLM,
    CLI_FLAG_REBUILD_WORKSPACE,
    has_cli_flag,
)
from job_hunter_agent.advance_settings import (
    DEFAULT_SEARCH_SETTINGS,
    DEFAULT_PLAYWRIGHT_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_ENFORCE_POSTED_AGE_LIMIT,
    KEY_SEEK_MAX_PAGES,
    KEY_SORT_NEWEST_FIRST,
    KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
    KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
    KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
)
from job_hunter_agent.profile_store import (
    get_match_levels,
    get_search_settings,
    load_profile,
)
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.source_registry import SOURCE_LINKEDIN, SOURCE_SEEK
from job_hunter_agent.source_learning import (
    build_ad_learning_signals,
    deterministic_review_outcome as _source_learning_deterministic_review_outcome,
)
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.scrapers.seek import fetch_job_details_payload
from job_hunter_agent.scrapers.seek_runner import seek_scrape_to_records
from job_hunter_agent.paths import (
    get_audit_records_path,
    get_workspace_results_path,
    get_job_history_path,
    get_review_data_path,
    get_run_stats_path,
)
from job_hunter_agent.io_utils import (
    configure_console_output,
    load_json_dict,
    load_json_list,
    load_llm_cache,
    save_llm_cache,
    load_job_history,
    save_job_history,
    write_debug_json,
    write_run_stats,
    write_run_attempt,
    write_review_data,
)
from job_hunter_agent.posting_utils import (
    parse_timestamp,
    posted_display_label,
    get_manual_skip_sets,
)


from job_hunter_agent.history import (
    TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING,
    viewed_by_user,
)
import job_hunter_agent.workspace_service as workspace_service
from job_hunter_agent.filters import passes_title_filters
from job_hunter_agent.filters import passes_content_filters
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.signal_registry import register_signals
from job_hunter_agent.signal_schema import CATEGORY_HARD_BLOCKER_PATTERN, LEARNING_ORIGINAL_TEXTS_KEY, LEARNING_SIGNAL_KEY, LEARNING_SUGGESTED_CATEGORY_KEY

from job_hunter_agent.text_processing import build_role_summary, compact_whitespace
from job_hunter_agent.preferences import (
    assess_contract_preference,
    assess_government_preference,
    salary_fit_adjustment,
)
from job_hunter_agent.score_labels import salary_fit_label, score_to_tone_class
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.scoring_utils import find_profile_experience_year_in_text, profile_recency_multiplier

NO_LLM_MODE = has_cli_flag(sys.argv, CLI_FLAG_NO_LLM)
WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)
CONSOLE_BANNER_WIDTH = 60



def deterministic_review_outcome(
    record: dict,
    fit_highlights: list[str],
    missing_evidence: list[str],
    soft_risk_reasons: list[str],
    profile: dict | None = None,
) -> dict | None:
    active_profile = profile if profile is not None else {}
    scoring_rules = active_profile.get("scoring_rules") if isinstance(active_profile, dict) else {}
    if isinstance(scoring_rules, dict) and isinstance(scoring_rules.get("deterministic_review_thresholds"), dict):
        try:
            return _source_learning_deterministic_review_outcome(
                record,
                active_profile,
                fit_highlights,
                missing_evidence,
                soft_risk_reasons,
            )
        except ValueError:
            pass

    if str(record.get("title_reason") or "").strip().upper() != "OK":
        return None
    if missing_evidence or soft_risk_reasons:
        return None
    strong_signal_count = len([
        item
        for item in fit_highlights
        if str(item or "").strip().startswith("Strong capability match:")
    ])
    if strong_signal_count >= 3:
        return {"decision": "KEEP", "grade": "SOLID"}
    return None


def _process_seek_job_details(record: dict, detail_page, profile: dict, title_reason: str) -> tuple[bool, str]:
    details_payload = fetch_job_details_payload(detail_page, record.get("url") or "")
    details_text = str(details_payload.get("text") or "")
    details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))
    if details_status != "ok":
        return False, details_status

    ok_desc, desc_reason = passes_content_filters(details_text, str(record.get("location") or ""), title_reason)
    if not ok_desc:
        if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
            hard_block_matches = find_hard_block_matches(details_text, (profile or {}).get("must_not_require_skills", []))
            signals: list[dict[str, Any]] = []
            seen: set[str] = set()
            for match in hard_block_matches or []:
                value = compact_whitespace(match.get("value") or "")
                if not value:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                signals.append(
                    {
                        LEARNING_SIGNAL_KEY: value,
                        LEARNING_SUGGESTED_CATEGORY_KEY: CATEGORY_HARD_BLOCKER_PATTERN,
                        LEARNING_ORIGINAL_TEXTS_KEY: [compact_whitespace(match.get("context") or details_text or desc_reason)],
                    }
                )
            if signals:
                register_signals(signals)
        return False, desc_reason

    return True, "OK"


def score_filter_option_label(threshold: int, scoring_profile: dict | None = None) -> str:
    active_profile = scoring_profile or load_profile()
    match_levels = get_match_levels(active_profile)
    label = score_to_match_label(threshold, match_levels)
    highest_threshold = max(int(level.get("minimum_score", 0) or 0) for level in match_levels)
    if threshold >= highest_threshold:
        return f"{label} only"
    return f"{label} or better"


def score_filter_thresholds(
    records: List[dict],
    scoring_profile: dict | None = None,
    include_borderline: bool | None = None,
) -> List[int]:
    active_profile = scoring_profile or load_profile()
    show_borderline = WORKSPACE_DEBUG_MODE if include_borderline is None else bool(include_borderline)
    scores = [fit_score(record, active_profile) for record in records]
    match_levels = get_match_levels(active_profile)
    thresholds = [int(level.get("minimum_score", 0) or 0) for level in match_levels if int(level.get("minimum_score", 0) or 0) > 0]
    lowest_band_threshold = int(match_levels[-1].get("minimum_score", 0) or 0) if match_levels else 0
    if (show_borderline or any(score < (thresholds[-1] if thresholds else 0) for score in scores)) and lowest_band_threshold not in thresholds:
        thresholds.append(lowest_band_threshold)
    return thresholds


def render_score_filter_options(
    records: List[dict],
    scoring_profile: dict | None = None,
    workspace_min_score: int | None = None,
    include_borderline: bool | None = None,
) -> str:
    active_profile = scoring_profile or load_profile()
    active_workspace_min_score = int(workspace_min_score) if workspace_min_score is not None else get_workspace_minimum_score()
    options = ['<option value="all">All match levels</option>']
    for threshold in score_filter_thresholds(records, active_profile, include_borderline=include_borderline):
        selected_attr = " selected" if active_workspace_min_score == threshold else ""
        options.append(
            f'<option value="{threshold}"{selected_attr}>'
            f'{compact_whitespace(score_filter_option_label(threshold, active_profile))}</option>'
        )
    return "".join(options)


def build_workspace_record_sets(
    kept_records: list[dict],
    job_history: dict[str, dict],
    applied_job_keys: set[str],
    hidden_job_keys: set[str],
    reference_time: datetime,
    scoring_profile: dict | None = None,
    workspace_min_score: int | None = None,
) -> dict[str, list[dict]]:
    profile = scoring_profile or load_profile()
    is_workspace_eligible_fn = is_workspace_eligible
    if workspace_min_score is not None:
        active_workspace_min_score = int(workspace_min_score)
        is_workspace_eligible_fn = (
            lambda record, current_profile=None: is_workspace_eligible(
                record,
                current_profile,
                active_workspace_min_score,
            )
        )
    return workspace_data.build_workspace_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        profile=profile,
        is_workspace_eligible_fn=is_workspace_eligible_fn,
        fit_score_fn=fit_score,
        viewed_by_user_fn=viewed_by_user,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_archive_records_fn=workspace_service.build_archive_records,
        build_applied_records_fn=workspace_service.build_applied_records,
        build_hidden_records_fn=workspace_service.build_hidden_records,
    )


def is_workspace_eligible(
    record: dict,
    profile: dict | None = None,
    workspace_min_score: int | None = None,
) -> bool:
    ok_title, _ = passes_title_filters(str(record.get("title") or ""))
    if not ok_title:
        return False
    active_workspace_min_score = int(workspace_min_score) if workspace_min_score is not None else get_workspace_minimum_score()
    return fit_score(record, profile or load_profile()) >= active_workspace_min_score



def scrape_jobs_direct(headless: bool = False) -> str:
    configure_console_output()
    from job_hunter_agent.llm_gate import get_llm_model
    workspace_min_score = get_workspace_minimum_score()
    print("=" * CONSOLE_BANNER_WIDTH)
    print("  JOB HUNTER AGENT - SCRAPE RUN")
    print("=" * CONSOLE_BANNER_WIDTH)
    print("  Trigger            : manual scrape command")
    print("  Action             : scrape fresh jobs, review them, rebuild workspace")
    print("  Fresh scrape       : YES")
    print(f"  Workspace debug    : {'ON (--debug)' if WORKSPACE_DEBUG_MODE else 'OFF'}")
    print(f"  LLM Disabled       : {'YES (--no-llm)' if NO_LLM_MODE else 'NO'}")
    if NO_LLM_MODE:
        print("  LLM Model          : disabled")
    else:
        print(f"  LLM Model          : {get_llm_model()}")
    print(f"  Score Floor        : {workspace_min_score}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}")
    print("=" * CONSOLE_BANNER_WIDTH)

    profile = load_profile()
    previous_audit_rows = load_json_list(get_audit_records_path())
    previous_run_stats = load_json_dict(get_run_stats_path())
    search_settings = get_search_settings(profile)
    configured_seek_max_pages = int(search_settings.get(KEY_SEEK_MAX_PAGES, DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES]) or DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES])
    configured_date_range = int(search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]) or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
    enforce_posted_age_limit = bool(search_settings.get(KEY_ENFORCE_POSTED_AGE_LIMIT, DEFAULT_SEARCH_SETTINGS[KEY_ENFORCE_POSTED_AGE_LIMIT]))
    sort_newest_first = bool(search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]))
    playwright_viewport_width = int(search_settings.get(KEY_PLAYWRIGHT_VIEWPORT_WIDTH, DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH]) or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH])
    playwright_viewport_height = int(search_settings.get(KEY_PLAYWRIGHT_VIEWPORT_HEIGHT, DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT]) or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT])
    playwright_selector_timeout = int(search_settings.get(KEY_PLAYWRIGHT_SELECTOR_TIMEOUT, DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT]) or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT])
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()
    run_iso = run_started_at.isoformat(timespec="seconds")
    write_run_attempt(run_started_at)
    llm_cache: Dict[str, Any] = load_llm_cache()
    job_history = load_job_history()

    enabled_sources = [s.lower().strip() for s in (profile.get("enabled_sources") or [])]

    kept_records: List[dict] = []
    audit_rows: List[dict] = []
    skill_observations: List[dict] = []

    # --- SEEK ---
    if SOURCE_SEEK in enabled_sources:
        search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
        s_kept, s_audit, s_skills = seek_scrape_to_records(
            profile=profile,
            search_targets=search_targets,
            job_history=job_history,
            llm_cache=llm_cache,
            applied_job_keys=applied_job_keys,
            hidden_job_keys=hidden_job_keys,
            run_iso=run_iso,
            configured_date_range=configured_date_range,
            enforce_posted_age_limit=enforce_posted_age_limit,
            configured_seek_max_pages=configured_seek_max_pages,
            playwright_viewport_width=playwright_viewport_width,
            playwright_viewport_height=playwright_viewport_height,
            playwright_selector_timeout=playwright_selector_timeout,
            headless=headless,
        )
        kept_records.extend(s_kept)
        audit_rows.extend(s_audit)
        skill_observations.extend(s_skills)

    # --- LinkedIn ---
    if SOURCE_LINKEDIN in enabled_sources:
        from job_hunter_agent.scrapers.linkedin import LinkedInScraper  # noqa: PLC0415
        try:
            li = LinkedInScraper(
                profile=profile,
                llm_cache=llm_cache,
                job_history=job_history,
                applied_job_keys=applied_job_keys,
                hidden_job_keys=hidden_job_keys,
                run_iso=run_iso,
            )
            li_kept, li_audit, li_skills = li.scrape()
            kept_records.extend(li_kept)
            audit_rows.extend(li_audit)
            skill_observations.extend(li_skills)
        except Exception as exc:
            print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {exc}")

    # --- Finalize ---
    # Final deterministic deduplication pass to collapse confirmed duplicates.
    kept_records = deduplicate_across_sources(kept_records)

    if not audit_rows and previous_audit_rows:
        workspace_service.render_html(
            get_workspace_results_path(),
            workspace_service.load_last_kept_records(),
            parse_timestamp(previous_run_stats.get("run_started_at")) or run_started_at,
            configured_date_range,
            sort_newest_first,
            previous_run_stats or {},
            job_history,
            applied_job_keys,
            hidden_job_keys,
            datetime.now().astimezone(),
        )
        save_llm_cache(llm_cache)
        save_job_history(job_history)
        workspace_path = get_workspace_results_path()
        print("\nNo fresh cards were captured in this run, so the previous workspace state was preserved.")
        print(f"Workspace results preserved at {workspace_path}")
        return str(workspace_path)

    run_finished_at = datetime.now().astimezone()
    run_stats = workspace_service.build_run_stats(
        audit_rows,
        kept_records,
        run_started_at,
        run_finished_at,
        configured_date_range,
        sort_newest_first,
        configured_seek_max_pages,
    )
    run_stats["last_run_attempt_at"] = run_iso

    workspace_path = get_workspace_results_path()
    workspace_service.render_html(
        workspace_path,
        kept_records,
        run_started_at,
        configured_date_range,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        run_started_at,
    )
    save_llm_cache(llm_cache)
    save_job_history(job_history)
    write_debug_json(audit_rows)
    write_run_stats(run_stats)
    write_review_data(build_review_data(audit_rows, skill_observations, profile))
    print(f"\nSaved {len(kept_records)} jobs to {workspace_path}")
    print(f"Saved {len(audit_rows)} audit rows to {get_audit_records_path()}")
    print(f"Saved run stats to {get_run_stats_path()}")
    print(f"Saved review data to {get_review_data_path()}")
    print(f"Saved history for {len(job_history)} jobs to {get_job_history_path()}")
    return str(workspace_path)


def rebuild_workspace_results(reason: str = "Manual --rebuild-workspace command") -> str:
    configure_console_output()
    print("=" * CONSOLE_BANNER_WIDTH)
    print("  JOB HUNTER AGENT - WORKSPACE RESULTS REBUILD")
    print("=" * CONSOLE_BANNER_WIDTH)
    print(f"  Trigger            : {reason}")
    print("  Action             : re-render saved results only")
    print("  Fresh scrape       : NO")
    print("  AI review          : NO")
    print(f"  Debug mode         : {'ON (--debug)' if WORKSPACE_DEBUG_MODE else 'OFF'}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}")
    print("=" * CONSOLE_BANNER_WIDTH)
    profile = load_profile()
    search_settings = get_search_settings(profile)
    configured_date_range = int(search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]) or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
    sort_newest_first = bool(search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]))
    run_stats = load_json_dict(get_run_stats_path())
    run_started_at = parse_timestamp(run_stats.get("run_started_at")) or datetime.now().astimezone()
    reference_time = datetime.now().astimezone()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    job_history = load_job_history()
    kept_records = workspace_service.load_last_kept_records()
    print(f"  Saved kept records : {len(kept_records)}")
    print(f"  Job history records: {len(job_history)}")
    print(f"  Applied keys       : {len(applied_job_keys)}")
    print(f"  Hidden keys        : {len(hidden_job_keys)}")
    print("=" * CONSOLE_BANNER_WIDTH)

    workspace_path = get_workspace_results_path()
    workspace_service.render_html(
        workspace_path,
        kept_records,
        run_started_at,
        configured_date_range,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )
    print(f"Workspace results rebuilt at {workspace_path}")
    return str(workspace_path)


if __name__ == "__main__":
    if has_cli_flag(sys.argv, CLI_FLAG_REBUILD_WORKSPACE):
        rebuild_workspace_results()
    else:
        scrape_jobs_direct()
