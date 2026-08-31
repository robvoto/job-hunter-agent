"""LinkedIn source connector using python-jobspy."""

from __future__ import annotations

import logging
import copy
import multiprocessing
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from typing import List
from urllib.error import URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

import sys

from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_SORT_NEWEST_FIRST,
    get_linkedin_fetch_timeout_seconds,
    get_linkedin_max_consecutive_target_failures,
    get_linkedin_parallel_search_workers,
    get_search_plan_min_corroboration_samples,
    get_source_discovery_cache_max_age_minutes,
)
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    ReviewPipelineHooks,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.logging_utils import format_debug_marker, format_log_block
from job_hunter_agent.profile_store import get_search_settings
from job_hunter_agent.search_terms import ordered_profile_search_terms
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_COMPANY_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_JOB_KEY,
    RECORD_JOB_QUALITY_SIGNALS_KEY,
    RECORD_LOCATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_SALARY_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
)
from job_hunter_agent.run_control import run_stop_requested, set_run_progress_state
from job_hunter_agent.runtime_helpers import CLI_FLAG_DEBUG, has_cli_flag
from job_hunter_agent.salary import load_salary
from job_hunter_agent.scrapers.base import BaseJobScraper, normalize_jobspy_record, _url_domain
from job_hunter_agent.scrapers.location_adapters import to_linkedin_search_scope
from job_hunter_agent.source_registry import SOURCE_LINKEDIN
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.search_metrics import QueryYieldMetric, record_query_yield_metric
from job_hunter_agent.search_plan_state import (
    load_search_plan_state,
    planned_search_terms,
    save_search_plan_observation,
    select_query_cover,
)
from job_hunter_agent.posting_utils import parse_visible_posted_age_days
from job_hunter_agent.work_mode_extraction import (
    WORK_MODE_UNKNOWN,
    extract_from_text,
    log_work_mode_result,
)

WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)


salary_rules = load_salary()
job_type_rules = load_job_type()


class _JobSpyNoticeHandler(logging.Handler):
    """Captures JobSpy's own WARNING+/ERROR+ log lines from inside the spawned worker.

    JobSpy logs to a "JobSpy:LinkedIn" logger with propagate=False, so messages
    such as a 429/blocked response are otherwise invisible outside the subprocess
    that made the request. This surfaces them back to the parent process's log.
    """

    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(self.format(record))


def _scrape_linkedin_jobs_worker(search_params: dict, send_conn) -> None:
    jobspy_notices: list[str] = []
    jobspy_logger = logging.getLogger("JobSpy:LinkedIn")
    handler = _JobSpyNoticeHandler(jobspy_notices)
    jobspy_logger.addHandler(handler)
    try:
        from jobspy import scrape_jobs  # noqa: PLC0415

        send_conn.send(("ok", scrape_jobs(**search_params), jobspy_notices))
    except Exception as exc:  # pragma: no cover - exercised through parent helper
        send_conn.send(("error", (type(exc).__name__, str(exc)), jobspy_notices))
    finally:
        jobspy_logger.removeHandler(handler)
        send_conn.close()


def _fetch_jobspy_with_timeout(search_params: dict, timeout_seconds: float):
    ctx = multiprocessing.get_context("spawn")
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    worker = ctx.Process(
        target=_scrape_linkedin_jobs_worker,
        args=(search_params, send_conn),
        daemon=True,
    )
    worker.start()
    send_conn.close()
    deadline = time.monotonic() + max(float(timeout_seconds), 0.1)
    while worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            worker.terminate()
            worker.join(1.0)
            recv_conn.close()
            raise TimeoutError(
                f"LinkedIn jobspy fetch exceeded {int(timeout_seconds)}s for {search_params['search_term']!r}"
            )
        worker.join(min(0.1, remaining))
        if worker.is_alive() and run_stop_requested():
            worker.terminate()
            worker.join(1.0)
            recv_conn.close()
            raise InterruptedError(
                f"LinkedIn jobspy fetch cancelled due to stop request for {search_params['search_term']!r}"
            )
    if not recv_conn.poll(1.0):
        recv_conn.close()
        raise RuntimeError(
            f"LinkedIn jobspy worker exited without results (exitcode={worker.exitcode})"
        )
    status, payload, jobspy_notices = recv_conn.recv()
    recv_conn.close()
    for notice in jobspy_notices:
        logger.warning("[LinkedIn jobspy] %s", notice)
    if status == "ok":
        return payload
    error_type, error_message = payload
    error_suffix = f": {error_message}" if str(error_message).strip() else ""
    raise RuntimeError(f"{error_type}{error_suffix}")


def _fetch_job_html(record: dict) -> str:
    raw_fields = record.get("source_metadata", {}).get("raw_source_fields", {})
    if not isinstance(raw_fields, dict):
        raw_fields = {}
    url = str(
        raw_fields.get("job_url_direct") or raw_fields.get("job_url") or record.get("url") or ""
    ).strip()
    if not url:
        return ""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, ValueError):
        return ""


def _extract_linkedin_posted_age_days(html: str, run_date) -> float | None:
    if not html:
        return None

    visible_text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", html, flags=re.I | re.S)
    visible_text = re.sub(r"<[^>]+>", " ", visible_text)
    visible_text = re.sub(r"\s+", " ", visible_text).strip().lower()
    return parse_visible_posted_age_days(visible_text, run_date)


_JOB_URL_DIRECT_CODE_RE = re.compile(r'<code[^>]*id="applyUrl"[^>]*>(.*?)</code>', re.I | re.S)
_JOB_URL_DIRECT_VALUE_RE = re.compile(r"(?<=\?url=)[^\"&<]+")


def _extract_linkedin_job_url_direct(html: str) -> str:
    code_match = _JOB_URL_DIRECT_CODE_RE.search(html)
    if not code_match:
        return ""
    value_match = _JOB_URL_DIRECT_VALUE_RE.search(code_match.group(1))
    if not value_match:
        return ""
    return unquote(value_match.group())


class _LinkedInDescriptionParser(HTMLParser):
    """Extracts visible text from LinkedIn's job-description container.

    Targets the same "show-more-less-html__markup" container JobSpy's own detail-page
    parser reads, via the stdlib parser (matching the pattern this codebase already uses
    for structured posting-date extraction) instead of adding a BeautifulSoup dependency.
    """

    _MARKUP_CLASS = "show-more-less-html__markup"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._capture_from_depth: int | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self._depth += 1
        if self._capture_from_depth is None:
            class_attr = str(dict(attrs).get("class") or "")
            if self._MARKUP_CLASS in class_attr:
                self._capture_from_depth = self._depth

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._capture_from_depth is not None and self._depth == self._capture_from_depth:
            self._capture_from_depth = None
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._capture_from_depth is not None:
            self._chunks.append(data)

    @property
    def description(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


def _extract_linkedin_description(html: str) -> str:
    if not html:
        return ""
    parser = _LinkedInDescriptionParser()
    try:
        parser.feed(html)
    except Exception:
        return ""
    return parser.description


def classify_linkedin_apply_method(apply_url: str, canonical_url: str) -> str:
    """Classify LinkedIn's apply signal into a normalised apply_method value.

    jobspy's ``easy_apply`` field is not reliably populated for LinkedIn results,
    so this uses ``apply_url`` (LinkedIn's external ATS link) as the proxy:
    present and different from the canonical job URL means an external apply;
    absent means LinkedIn's own UI only exposed Easy Apply.
    """
    apply_url = str(apply_url or "").strip()
    canonical_url = str(canonical_url or "").strip()
    if apply_url and apply_url != canonical_url:
        return APPLY_METHOD_EXTERNAL_APPLY
    if not apply_url:
        return APPLY_METHOD_EASY_APPLY
    return APPLY_METHOD_UNKNOWN


def build_linkedin_search_targets(
    search_settings: dict,
    profile: dict | None = None,
) -> List[dict]:
    search_terms = ordered_profile_search_terms(search_settings, profile)
    locations = [str(loc).strip() for loc in search_settings.get("locations", []) if str(loc).strip()]
    hours_old = int(
        search_settings.get(
            KEY_LINKEDIN_HOURS_OLD, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
        )
        or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
    )
    results_wanted = int(
        search_settings.get(
            KEY_LINKEDIN_RESULTS_PER_SEARCH,
            DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH],
        )
        or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH]
    )
    sort_newest_first = bool(
        search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST])
    )
    easy_apply = search_settings.get(KEY_LINKEDIN_EASY_APPLY_ONLY)

    targets = []
    for raw_loc in locations:
        location = resolve_location(raw_loc)
        scope = to_linkedin_search_scope(location)
        for search_term in search_terms:
            targets.append(
                {
                    "search_term": search_term,
                    "location": scope["location"],
                    "distance": scope["distance"],
                    "scope": scope["scope"],
                    "hours_old": hours_old,
                    "results_wanted": results_wanted,
                    "sort_newest_first": sort_newest_first,
                    "easy_apply": easy_apply,
                }
            )
    return targets


def _set_linkedin_run_progress(
    target_index: int,
    total_targets: int,
    *,
    row_index: int | None = None,
    total_rows: int | None = None,
) -> None:
    """Emit the structured LinkedIn stage used by the shared wait-state UI."""
    if (row_index is None) != (total_rows is None):
        raise ValueError("row_index and total_rows must be supplied together")
    detail = ""
    text = f"LinkedIn search {target_index}/{total_targets}"
    if row_index is not None and total_rows is not None:
        detail = f"Reviewing job {row_index} of {total_rows}"
        text = f"LinkedIn target {target_index}/{total_targets}\nReviewing job {row_index}/{total_rows}"
    set_run_progress_state(
        text,
        stage="source_collection",
        source="linkedin",
        headline=f"LinkedIn target {target_index} of {total_targets}",
        detail=detail,
        current=target_index,
        total=total_targets,
        item_current=row_index,
        item_total=total_rows,
    )


class LinkedInScraper(BaseJobScraper):
    source_name = SOURCE_LINKEDIN

    def scrape(self) -> tuple:
        """Run configured LinkedIn targets and publish target/job stage progress."""
        kept_records: List[dict] = []
        audit_rows: List[dict] = []
        skill_observations: List[dict] = []
        seen_job_keys: set[str] = set()

        search_settings = get_search_settings(self.profile)
        date_range_days = int(
            search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
            or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]
        )
        configured_targets = self._build_search_targets(search_settings)
        if not configured_targets:
            logger.debug("[LinkedIn] no search targets configured; skipping")
            return kept_records, audit_rows, skill_observations

        # A trusted plan prunes only complete source targets. A bootstrap or
        # stale plan deliberately runs every configured term so the source can
        # re-measure real job-key coverage before pruning again.
        probe_terms_by_location: dict[str, list[str]] = {}
        plan_probe_locations: set[str] = set()
        targets = list(configured_targets)
        if self.search_plan_signature:
            planned_terms_by_location: dict[str, list[str]] = {}
            for target in configured_targets:
                location = str(target.get("location") or "")
                term = str(target.get("search_term") or "").strip()
                if term:
                    probe_terms_by_location.setdefault(location, []).append(term)
            for location, probe_terms in probe_terms_by_location.items():
                state = load_search_plan_state(
                    source=self.source_name.lower(),
                    signature=self.search_plan_signature,
                    location=location,
                )
                planned_terms, plan_source = planned_search_terms(
                    state,
                    probe_terms,
                    min_corroboration_samples=get_search_plan_min_corroboration_samples(),
                    max_age_minutes=get_source_discovery_cache_max_age_minutes(),
                )
                planned_terms_by_location[location] = planned_terms
                if plan_source != "remembered":
                    plan_probe_locations.add(location)
                skipped_terms = set(probe_terms) - set(planned_terms)
                prior_term_job_counts = state.get("term_job_counts")
                estimated_jobs_avoided = (
                    sum(
                        int(prior_term_job_counts.get(term, 0))
                        for term in skipped_terms
                    )
                    if isinstance(prior_term_job_counts, dict)
                    else 0
                )
                logger.info(
                    "[LINKEDIN][SEARCH_PLAN] location=%r source=%s configured_terms=%d "
                    "planned_terms=%d skipped_terms=%d estimated_queries_avoided=%d "
                    "estimated_detail_review_work_avoided=%d",
                    location or "(all)",
                    plan_source,
                    len(probe_terms),
                    len(planned_terms),
                    max(0, len(probe_terms) - len(planned_terms)),
                    max(0, len(probe_terms) - len(planned_terms)),
                    estimated_jobs_avoided,
                )
            targets = [
                target
                for target in configured_targets
                if str(target.get("search_term") or "").strip()
                in planned_terms_by_location.get(str(target.get("location") or ""), [])
            ]

        review_context = ReviewPipelineContext(
            profile=self.profile,
            job_history=self.job_history,
            audit_rows=audit_rows,
            llm_cache=self.llm_cache,
            applied_job_keys=self.applied_job_keys,
            hidden_job_keys=self.hidden_job_keys,
            run_iso=self.run_iso,
            date_range_days=date_range_days,
            source_name="LinkedIn",
        )

        total_targets = len(targets)
        seen_discovered_job_keys: set[str] = set()
        probe_job_keys_by_location: dict[str, dict[str, set[str]]] = {}
        if self.discovery_records is not None:
            cached_collection_complete = True
            for index, cached_record in enumerate(self.discovery_records, start=1):
                if run_stop_requested():
                    cached_collection_complete = False
                    break
                self._review_discovered_record(
                    dict(cached_record),
                    review_context,
                    seen_job_keys,
                    f"[LinkedIn cached job {index}/{len(self.discovery_records)}]",
                    kept_records,
                    skill_observations,
                )
            self.discovery_status["complete"] = cached_collection_complete
            return kept_records, audit_rows, skill_observations

        parallel_search_workers = max(
            1,
            min(
                int(
                    search_settings.get(
                        KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS,
                        get_linkedin_parallel_search_workers(),
                    )
                ),
                total_targets,
            ),
        )
        logger.debug(
            format_debug_marker(
                "BOARD_START",
                {
                    "source": self.source_name,
                    "targets": total_targets,
                    "date_range_days": date_range_days,
                    "parallel_search_workers": parallel_search_workers,
                },
            )
        )

        # Targets are fetched concurrently (bounded by parallel_search_workers) so one
        # slow/timed-out jobspy search no longer blocks every later target behind it,
        # but rows are still reviewed sequentially in original target order below so
        # dedup (seen_job_keys) and shared review_context state stay deterministic.
        pending_fetches: dict[int, tuple[Future, float]] = {}
        next_to_submit = 0
        run_started_at = time.monotonic()
        attempted_targets = 0
        succeeded_targets = 0
        timed_out_targets = 0
        failed_targets = 0
        skipped_after_breaker = 0
        rows_collected = 0
        consecutive_failures = 0
        breaker_tripped = False
        max_consecutive_failures = max(1, int(get_linkedin_max_consecutive_target_failures()))

        def _log_target_banner(idx: int, tgt: dict) -> None:
            logger.debug(
                "\n"
                "================================================================\n"
                "  STARTING LINKEDIN TARGET %d/%d\n"
                "  search_term=%s\n"
                "  location=%s\n"
                "  distance=%s\n"
                "  scope=%s\n"
                "  results_wanted=%d\n"
                "================================================================",
                idx + 1,
                total_targets,
                tgt["search_term"] or "(unset)",
                tgt["location"] or "(all)",
                tgt.get("distance") if tgt.get("distance") is not None else "n/a",
                tgt.get("scope") or "n/a",
                tgt["results_wanted"],
            )

        def _record_target_metric(
            target: dict,
            started_at: float,
            discovered_count: int,
            new_unique_count: int,
            *,
            success: bool,
            failure_reason: str = "",
        ) -> None:
            record_query_yield_metric(
                QueryYieldMetric(
                    source=self.source_name.lower(),
                    search_term=target["search_term"],
                    location=target["location"],
                    elapsed_seconds=time.monotonic() - started_at,
                    discovered_count=discovered_count,
                    new_unique_job_count=new_unique_count,
                    duplicate_job_count=discovered_count - new_unique_count,
                    pages_searched=1,
                    success=success,
                    failure_reason=failure_reason,
                )
            )

        try:
            with ThreadPoolExecutor(max_workers=parallel_search_workers) as fetch_executor:

                def _submit(idx: int) -> None:
                    tgt = targets[idx]
                    logger.debug(
                        "[LinkedIn target %d/%d] jobspy fetch start | search_term=%r | location=%r | distance=%s | scope=%s | results_wanted=%d | hours_old=%d | easy_apply=%r | sort_newest_first=%s",
                        idx + 1,
                        total_targets,
                        tgt["search_term"] or "(unset)",
                        tgt["location"] or "(all)",
                        tgt.get("distance") if tgt.get("distance") is not None else "n/a",
                        tgt.get("scope") or "n/a",
                        tgt["results_wanted"],
                        tgt["hours_old"],
                        tgt.get("easy_apply"),
                        tgt["sort_newest_first"],
                    )
                    pending_fetches[idx] = (
                        fetch_executor.submit(self._fetch_jobspy, tgt),
                        time.monotonic(),
                    )

                for _ in range(parallel_search_workers):
                    _submit(next_to_submit)
                    next_to_submit += 1

                for target_index, target in enumerate(targets, start=1):
                    if run_stop_requested():
                        logger.debug("[LinkedIn] stop requested before target start; ending scrape")
                        self.discovery_status["complete"] = False
                        break

                    idx0 = target_index - 1
                    if target["location"] in plan_probe_locations:
                        probe_job_keys_by_location.setdefault(target["location"], {}).setdefault(
                            target["search_term"], set()
                        )
                    if idx0 not in pending_fetches:
                        # Circuit breaker tripped before this target was ever submitted.
                        skipped_after_breaker += 1
                        continue

                    target_tag = f"[LinkedIn target {target_index}/{total_targets}]"
                    _set_linkedin_run_progress(target_index, total_targets)
                    _log_target_banner(idx0, target)
                    target_started_at = time.monotonic()
                    target_discovered_count = 0
                    target_new_unique_count = 0

                    future, fetch_started_at = pending_fetches.pop(idx0)
                    if not breaker_tripped and next_to_submit < total_targets:
                        _submit(next_to_submit)
                        next_to_submit += 1

                    attempted_targets += 1
                    try:
                        rows = future.result()
                        logger.debug(
                            "%s jobspy fetch done | elapsed_ms=%d | rows=%s",
                            target_tag,
                            int((time.monotonic() - fetch_started_at) * 1000),
                            "none" if rows is None else len(rows),
                        )
                    except InterruptedError:
                        logger.debug("%s jobspy fetch cancelled due to stop request", target_tag)
                        self.discovery_status["complete"] = False
                        _record_target_metric(
                            target,
                            target_started_at,
                            target_discovered_count,
                            target_new_unique_count,
                            success=False,
                            failure_reason="stopped",
                        )
                        break
                    except Exception as exc:
                        logger.warning("%s jobspy call failed: %s: %s", target_tag, type(exc).__name__, exc)
                        self.discovery_status["complete"] = False
                        _record_target_metric(
                            target,
                            target_started_at,
                            target_discovered_count,
                            target_new_unique_count,
                            success=False,
                            failure_reason=type(exc).__name__,
                        )
                        failed_targets += 1
                        consecutive_failures += 1
                        if isinstance(exc, TimeoutError):
                            timed_out_targets += 1
                            self.discovery_status["timed_out_targets"] = int(
                                self.discovery_status.get("timed_out_targets", 0)
                            ) + 1
                        if not breaker_tripped and consecutive_failures >= max_consecutive_failures:
                            breaker_tripped = True
                            logger.warning(
                                "%s LinkedIn circuit breaker tripped after %d consecutive target "
                                "failures; no further targets will be submitted (%d/%d attempted so far)",
                                target_tag,
                                consecutive_failures,
                                attempted_targets,
                                total_targets,
                            )
                        continue

                    consecutive_failures = 0
                    succeeded_targets += 1
                    rows_collected += 0 if rows is None else len(rows)

                    if run_stop_requested():
                        logger.debug("%s stop requested after jobspy fetch; ending scrape", target_tag)
                        self.discovery_status["complete"] = False
                        break

                    if rows is None or len(rows) == 0:
                        logger.debug("%s no results", target_tag)
                        _record_target_metric(
                            target,
                            target_started_at,
                            0,
                            0,
                            success=True,
                        )
                        continue

                    if target.get("sort_newest_first"):
                        try:
                            rows = rows.sort_values(
                                by="date_posted",
                                ascending=False,
                                na_position="last",
                            )
                        except Exception:
                            pass

                    logger.debug("%s rows=%d", target_tag, len(rows))

                    total_rows = len(rows)
                    for row_index, (_, row) in enumerate(rows.iterrows(), start=1):
                        _set_linkedin_run_progress(
                            target_index,
                            total_targets,
                            row_index=row_index,
                            total_rows=total_rows,
                        )
                        if run_stop_requested():
                            logger.debug("[LinkedIn] stop requested; ending scrape")
                            self.discovery_status["complete"] = False
                            break
                        record = normalize_jobspy_record(
                            row,
                            source=self.source_name,
                            search_keywords=target["search_term"],
                            search_location=target["location"],
                            run_iso=self.run_iso,
                            salary_rules=salary_rules,
                            job_type_rules=job_type_rules,
                        )
                        record[RECORD_DESCRIPTION_SOURCE_KEY] = "linkedin_full_description"
                        record[RECORD_DETAILS_TEXT_KEY] = str(record.get(RECORD_DETAILS_TEXT_KEY) or "")
                        target_discovered_count += 1
                        logger.debug(
                            "[PIPELINE][CARD_NORMALIZED] source=LINKEDIN job_key=%s title=%r company=%r url=%r description_chars=%d",
                            record.get(RECORD_JOB_KEY),
                            record.get(RECORD_TITLE_KEY),
                            record.get(RECORD_COMPANY_KEY),
                            record.get(RECORD_URL_KEY),
                            len(record[RECORD_DETAILS_TEXT_KEY]),
                        )
                        job_key = str(record.get(RECORD_JOB_KEY) or "").strip()
                        if target["search_term"] in probe_terms_by_location.get(
                            target["location"], []
                        ):
                            probe_job_keys_by_location.setdefault(
                                target["location"], {}
                            ).setdefault(target["search_term"], set()).update(
                                {job_key} if job_key else set()
                            )
                        is_new_discovery = not job_key or job_key not in seen_discovered_job_keys
                        if job_key:
                            seen_discovered_job_keys.add(job_key)
                        if self.discovery_capture is not None and is_new_discovery:
                            self.discovery_capture.append(copy.deepcopy(record))
                        if is_new_discovery:
                            target_new_unique_count += 1
                            self._review_discovered_record(
                                record,
                                review_context,
                                seen_job_keys,
                                target_tag,
                                kept_records,
                                skill_observations,
                            )
                    if run_stop_requested():
                        logger.debug("%s stop requested after row review; ending scrape", target_tag)
                        self.discovery_status["complete"] = False
                        _record_target_metric(
                            target,
                            target_started_at,
                            target_discovered_count,
                            target_new_unique_count,
                            success=False,
                            failure_reason="stopped",
                        )
                        break
                    _record_target_metric(
                        target,
                        target_started_at,
                        target_discovered_count,
                        target_new_unique_count,
                        success=True,
                    )
        except Exception as exc:
            raise PartialSourceResultsError(
                self.source_name,
                kept_records=kept_records,
                audit_rows=audit_rows,
                skill_observations=skill_observations,
                original_error=exc,
            ) from exc

        elapsed_seconds = time.monotonic() - run_started_at
        full_failure = attempted_targets > 0 and succeeded_targets == 0 and failed_targets > 0
        if run_stop_requested():
            final_status = "stopped"
        elif full_failure:
            final_status = "full_failure"
        elif failed_targets > 0 or skipped_after_breaker > 0:
            final_status = "partial_failure"
        else:
            final_status = "healthy"

        if self.search_plan_signature and final_status == "healthy":
            for location in plan_probe_locations:
                probe_terms = probe_terms_by_location[location]
                observed = probe_job_keys_by_location.get(location, {})
                if set(observed) != set(probe_terms):
                    logger.warning(
                        "[LINKEDIN][SEARCH_PLAN] not updating location=%r; complete "
                        "per-term probe evidence was not collected",
                        location or "(all)",
                    )
                    continue
                selected_terms = select_query_cover(observed)
                selected_job_keys: set[str] = set()
                for term in selected_terms:
                    selected_job_keys.update(observed.get(term, set()))
                remembered = save_search_plan_observation(
                    source=self.source_name.lower(),
                    signature=self.search_plan_signature,
                    location=location,
                    probe_terms=probe_terms,
                    selected_terms=selected_terms,
                    coverage_job_count=len(set().union(*observed.values())) if observed else 0,
                    term_job_counts={term: len(job_keys) for term, job_keys in observed.items()},
                    selected_coverage_job_count=len(selected_job_keys),
                )
                logger.info(
                    "[LINKEDIN][SEARCH_PLAN] location=%r selected_terms=%r "
                    "coverage_jobs=%d samples=%d",
                    location or "(all)",
                    selected_terms,
                    len(set().union(*observed.values())) if observed else 0,
                    int(remembered.get("sample_count") or 0),
                )

        self.discovery_status.update(
            {
                "total_targets": total_targets,
                "attempted_targets": attempted_targets,
                "succeeded_targets": succeeded_targets,
                "timed_out_targets": timed_out_targets,
                "failed_targets": failed_targets,
                "skipped_after_breaker": skipped_after_breaker,
                "circuit_breaker_tripped": breaker_tripped,
                "rows_collected": rows_collected,
                "elapsed_seconds": elapsed_seconds,
                "final_status": final_status,
            }
        )

        logger.debug(
            format_debug_marker(
                "BOARD_END",
                {
                    "source": self.source_name,
                    "targets": total_targets,
                    "kept": len(kept_records),
                    "audit_rows": len(audit_rows),
                },
            )
        )
        logger.info(
            format_log_block(
                "LinkedIn][SOURCE_SUMMARY",
                {
                    "attempted": attempted_targets,
                    "succeeded": succeeded_targets,
                    "timed_out": timed_out_targets,
                    "failed": failed_targets,
                    "skipped_after_breaker": skipped_after_breaker,
                    "rows_collected": rows_collected,
                    "kept": len(kept_records),
                    "elapsed_seconds": round(elapsed_seconds, 1),
                    "final_status": final_status,
                },
            )
        )
        set_run_progress_state(
            "LinkedIn complete",
            stage="source_collection",
            source="linkedin",
            headline="LinkedIn",
            detail="Source collection complete",
            determinate=False,
        )
        return kept_records, audit_rows, skill_observations

    def _review_discovered_record(
        self,
        record: dict,
        review_context: ReviewPipelineContext,
        seen_job_keys: set[str],
        target_tag: str,
        kept_records: list[dict],
        skill_observations: list[dict],
    ) -> None:
        """Run current review logic on live or cached source evidence.

        No LinkedIn job-page network fetch happens above this point: native-ID dedup
        (seen_job_keys) and the pre-detail gate must both clear a card before
        _fetch_linkedin_detail_evidence performs the single bounded detail fetch.
        """
        job_key = str(record.get(RECORD_JOB_KEY) or "").strip()
        if job_key and job_key in seen_job_keys:
            logger.debug("%s duplicate job_key=%s across LinkedIn targets; skipping", target_tag, job_key)
            return
        if job_key:
            seen_job_keys.add(job_key)
        pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(
            record, review_context
        )
        outcome = pre_outcome
        record_skill_observations: list[dict] = []
        if pre_outcome["decision"] == "KEEP" and should_fetch_details:
            closed_signals = self._fetch_linkedin_detail_evidence(record)
            if closed_signals:
                record[RECORD_JOB_QUALITY_SIGNALS_KEY] = closed_signals
            outcome, record, record_skill_observations = review_post_detail_normalized_job(
                record, review_context, hooks=self._build_review_hooks()
            )
        if outcome["decision"] == "KEEP":
            skill_observations.extend(record_skill_observations)
            kept_records.append(record)

    def _build_search_targets(self, search_settings: dict) -> List[dict]:
        return build_linkedin_search_targets(search_settings, self.profile)

    def _build_review_hooks(self) -> ReviewPipelineHooks:
        def _after_description_loaded(current_record: dict, context: ReviewPipelineContext) -> None:
            if DEBUG_CAPTURE_SOURCE_PAYLOADS:
                try:
                    write_source_payload_debug(
                        "linkedin",
                        str(
                            current_record.get(RECORD_JOB_KEY)
                            or current_record.get(RECORD_URL_KEY)
                            or "unknown"
                        ),
                        raw_html=_fetch_job_html(current_record),
                        raw_json=current_record.get("source_metadata", {}).get(
                            "raw_source_fields", {}
                        ),
                        normalized_record=current_record,
                    )
                except Exception:
                    pass

        def _before_preference_filters(
            current_record: dict, context: ReviewPipelineContext
        ) -> None:
            from job_hunter_agent.job_quality import (  # noqa: PLC0415
                detect_broad_engagement_signal,
                detect_cv_farming_signals,
                detect_external_date_signals,
                fetch_external_html,
                load_dodgy_job_rules,
            )

            details_text = str(
                current_record.get(RECORD_DETAILS_TEXT_KEY)
                or current_record.get("full_description")
                or ""
            )
            rules = load_dodgy_job_rules()
            signals: list = [
                signal
                for signal in (current_record.get(RECORD_JOB_QUALITY_SIGNALS_KEY) or [])
                if isinstance(signal, dict)
            ]
            signals.extend(detect_cv_farming_signals(details_text, rules))
            signals.extend(detect_broad_engagement_signal(current_record))

            raw_fields = current_record.get("source_metadata", {}).get("raw_source_fields", {})
            is_easy_apply = bool(raw_fields.get("easy_apply"))
            apply_url = str(
                current_record.get("source_metadata", {}).get("apply_url") or ""
            ).strip()
            linkedin_url = str(current_record.get(RECORD_URL_KEY) or "").strip()
            current_record[RECORD_APPLY_METHOD_KEY] = classify_linkedin_apply_method(
                apply_url, linkedin_url
            )
            if not is_easy_apply and apply_url and apply_url != linkedin_url:
                ext_html = fetch_external_html(apply_url)
                if ext_html:
                    current_record["_external_apply_html"] = ext_html
                run_date = datetime.fromisoformat(context.run_iso).date()
                signals.extend(
                    detect_external_date_signals(
                        ext_html,
                        current_record.get(RECORD_POSTED_AGE_DAYS_KEY),
                        rules,
                        run_date,
                    )
                )

            current_record["job_quality_signals"] = signals
            if current_record.get(RECORD_WORK_MODE_KEY) in (WORK_MODE_UNKNOWN, "", None):
                text_result = extract_from_text(details_text)
                if text_result["work_mode"] != WORK_MODE_UNKNOWN:
                    current_record[RECORD_WORK_MODE_KEY] = text_result["work_mode"]
                    current_record["work_mode_source"] = text_result["work_mode_source"]
                    current_record["work_mode_evidence"] = text_result["work_mode_evidence"]
                    current_record["work_mode_needs_review"] = text_result["work_mode_needs_review"]
            log_work_mode_result(
                str(current_record.get(RECORD_JOB_KEY) or ""), "linkedin", current_record
            )

        return ReviewPipelineHooks(
            after_description_loaded=_after_description_loaded,
            before_preference_filters=_before_preference_filters,
        )

    def _fetch_linkedin_detail_evidence(self, record: dict) -> list[dict]:
        """One bounded LinkedIn job-page fetch, reused for every field that needs it.

        Only called once a card has survived native-ID dedup and the cheap
        pre-detail gates (review_pre_detail_normalized_job returned
        should_fetch_details=True) -- never during discovery/card review. JobSpy's
        own discovery call runs with linkedin_fetch_description=False, so this is
        the only per-job LinkedIn page fetch in the pipeline; its evidence is reused
        for description, apply-method metadata, posted-age backfill, and closed-job
        signals rather than independently re-fetching the same page multiple times.

        Returns the closed-job signals found, if any; description/apply-url/posted-age
        evidence is applied directly onto ``record``.
        """
        from job_hunter_agent.job_quality import (  # noqa: PLC0415
            SIGNAL_KIND_JOB_CLOSED,
            detect_external_date_signals,
            load_dodgy_job_rules,
        )

        html = _fetch_job_html(record)
        if not html:
            return []

        description = _extract_linkedin_description(html)
        if description:
            record[RECORD_DETAILS_TEXT_KEY] = description

        job_url_direct = _extract_linkedin_job_url_direct(html)
        if job_url_direct:
            source_metadata = dict(record.get("source_metadata") or {})
            source_metadata["apply_url"] = job_url_direct
            source_metadata["apply_domain"] = _url_domain(job_url_direct)
            source_metadata["ats_source"] = _url_domain(job_url_direct)
            raw_fields = source_metadata.get("raw_source_fields")
            if isinstance(raw_fields, dict):
                raw_fields = dict(raw_fields)
                raw_fields["job_url_direct"] = job_url_direct
                source_metadata["raw_source_fields"] = raw_fields
            record["source_metadata"] = source_metadata

        run_date = datetime.fromisoformat(self.run_iso).date()
        if record.get(RECORD_POSTED_AGE_DAYS_KEY) is None:
            posted_age_days = _extract_linkedin_posted_age_days(html, run_date)
            if posted_age_days is not None:
                record[RECORD_POSTED_AGE_DAYS_KEY] = posted_age_days

        rules = load_dodgy_job_rules()
        signals = detect_external_date_signals(html, None, rules, run_date)
        return [signal for signal in signals if signal.get("kind") == SIGNAL_KIND_JOB_CLOSED]

    def _fetch_jobspy(self, target: dict):
        search_params = {
            "site_name": ["linkedin"],
            "search_term": target["search_term"],
            "location": target["location"],
            "results_wanted": target["results_wanted"],
            "hours_old": target["hours_old"],
            "country_indeed": "Australia",
            "linkedin_fetch_description": False,
            "verbose": 0,
        }
        if target.get("distance") is not None:
            search_params["distance"] = target["distance"]
        if target.get("easy_apply") is not None:
            search_params["easy_apply"] = target["easy_apply"]
        search_settings = get_search_settings(self.profile)
        timeout_seconds = float(
            search_settings.get(
                KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS,
                get_linkedin_fetch_timeout_seconds(),
            )
        )
        return _fetch_jobspy_with_timeout(search_params, timeout_seconds)
