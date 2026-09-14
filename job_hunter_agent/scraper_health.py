"""Admin-triggered scraper configuration validation checks."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_APSJOBS_RESULTS_PER_SEARCH,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
)
from job_hunter_agent.locations import default_location_value
from job_hunter_agent.scrapers.apsjobs import (
    APSJOBS_JOB_SEARCH_URL,
    APSJOBS_LOCATION_INPUT_SELECTORS,
    APSJOBS_SEARCH_BUTTON_SELECTORS,
    APSJOBS_SEARCH_INPUT_SELECTORS,
    APSJOBS_STATE_SELECTORS,
    APSJOBS_TITLE_SELECTORS,
    build_apsjobs_search_targets,
)
from job_hunter_agent.scrapers.linkedin import (
    build_linkedin_search_targets,
    classify_linkedin_apply_method,
)
from job_hunter_agent.scrapers.seek import (
    SEEK_JOBS_BASE_URL,
    SELECTOR_APPLY_BUTTON,
    SELECTOR_CARDS,
    SELECTOR_COMPANY,
    SELECTOR_DETAILS,
    SELECTOR_LOCATION,
    SELECTOR_POSTED,
    SELECTOR_TITLE,
    build_seek_search_targets,
    classify_detail_page_text,
    classify_seek_apply_method,
    extract_posted_text_from_card,
    extract_work_type,
)
from job_hunter_agent.source_registry import (
    SOURCE_APSJOBS,
    SOURCE_JOB_MARKET_MAP,
    SOURCE_LINKEDIN,
    SOURCE_SEEK,
    load_source_registry,
)
from job_hunter_agent.system_warnings import make_system_warning_fingerprint, record_system_warning

_VALIDATION_CATEGORY = "scraper_configuration_validation"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sample_profile() -> dict[str, Any]:
    search_settings = dict(DEFAULT_SEARCH_SETTINGS)
    search_settings["keywords"] = "business analyst"
    search_settings["locations"] = [default_location_value()]
    search_settings[KEY_LINKEDIN_HOURS_OLD] = int(DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD])
    search_settings[KEY_LINKEDIN_RESULTS_PER_SEARCH] = int(
        DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH]
    )
    search_settings[KEY_APSJOBS_RESULTS_PER_SEARCH] = int(
        DEFAULT_SEARCH_SETTINGS[KEY_APSJOBS_RESULTS_PER_SEARCH]
    )
    return {"search_settings": search_settings}


def _check(condition: bool, issues: list[str], message: str) -> None:
    if not condition:
        issues.append(message)


def _check_selectors(
    source_label: str,
    selectors: list[str] | tuple[str, ...],
    issues: list[str],
    *,
    label: str,
) -> None:
    cleaned = [str(selector or "").strip() for selector in selectors]
    _check(bool(cleaned), issues, f"{source_label}: {label} is empty.")
    _check(all(cleaned), issues, f"{source_label}: {label} contains a blank selector.")
    _check(
        len(cleaned) == len(set(cleaned)),
        issues,
        f"{source_label}: {label} contains duplicate selectors.",
    )


def _build_result(source: str, checks: list[str], issues: list[str]) -> dict[str, Any]:
    status = "warning" if issues else "ok"
    summary = (
        f"{source}: {len(issues)} issue(s) found across {len(checks)} checks."
        if issues
        else f"{source}: {len(checks)} checks passed."
    )
    return {
        "source": source,
        "status": status,
        "summary": summary,
        "checks": checks,
        "issues": issues,
    }


def _validate_source_registry() -> dict[str, Any]:
    issues: list[str] = []
    checks: list[str] = []
    registry = load_source_registry()
    domain_map = registry["domain_to_source_map"]
    labels = registry["source_display_labels"]

    expected_domains = {
        "seek.com.au": SOURCE_SEEK,
        "linkedin.com": SOURCE_LINKEDIN,
        "apsjobs.gov.au": SOURCE_APSJOBS,
    }
    for domain, source in expected_domains.items():
        _check(
            domain_map.get(domain) == source,
            issues,
            f"source_registry: expected domain {domain!r} to map to {source!r}.",
        )
    checks.append("Expected source registry domains map to SEEK, LinkedIn, and APSJobs.")

    for source in (SOURCE_SEEK, SOURCE_LINKEDIN, SOURCE_APSJOBS, SOURCE_JOB_MARKET_MAP):
        _check(
            str(labels.get(source) or "").strip() != "",
            issues,
            f"source_registry: missing display label for {source!r}.",
        )
    checks.append("Expected source registry display labels are present for all supported sources.")
    return _build_result("source_registry", checks, issues)


def _validate_seek_configuration() -> dict[str, Any]:
    issues: list[str] = []
    checks: list[str] = []

    for label, selector in (
        ("card selector", SELECTOR_CARDS),
        ("title selector", SELECTOR_TITLE),
        ("company selector", SELECTOR_COMPANY),
        ("posted selector", SELECTOR_POSTED),
        ("location selector", SELECTOR_LOCATION),
        ("details selector", SELECTOR_DETAILS),
        ("apply button selector", SELECTOR_APPLY_BUTTON),
    ):
        _check(str(selector or "").strip() != "", issues, f"seek: missing {label}.")
    checks.append("Required SEEK selectors are non-empty.")

    parsed = urlsplit(SEEK_JOBS_BASE_URL)
    _check(parsed.scheme == "https", issues, "seek: SEEK_JOBS_BASE_URL must use https.")
    _check(parsed.netloc == "www.seek.com.au", issues, "seek: unexpected SEEK base host.")
    _check(parsed.path == "/jobs", issues, "seek: SEEK_JOBS_BASE_URL must point to /jobs.")
    checks.append("SEEK search base URL points to the expected host and path.")

    sample_profile = _sample_profile()
    targets = build_seek_search_targets(
        sample_profile,
        configured_date_range=3,
        sort_newest_first=True,
    )
    _check(len(targets) == 1, issues, "seek: expected one SEEK search target for sample profile.")
    if targets:
        target = targets[0]
        parsed_target = urlsplit(str(target.get("url") or ""))
        query = parse_qs(parsed_target.query)
        _check(
            query.get("keywords") == ["business analyst"],
            issues,
            "seek: sample search target lost keywords.",
        )
        _check(query.get("daterange") == ["3"], issues, "seek: sample target lost daterange.")
        _check(
            query.get("sortMode") == ["ListedDate"],
            issues,
            "seek: newest-first sample target lost sortMode.",
        )
        _check(bool(query.get("where")), issues, "seek: sample target lost location filter.")
    checks.append("SEEK search target builder preserves keywords, daterange, location, and sort mode.")

    _check(
        extract_posted_text_from_card("Posted 2d ago") != "",
        issues,
        "seek: posted-age extraction returned blank for a simple card sample.",
    )
    _check(
        extract_work_type("This is a Contract job") == "Contract",
        issues,
        "seek: work-type extraction failed on a simple card sample.",
    )
    _check(
        classify_detail_page_text("Help us keep SEEK secure") == "challenge_page",
        issues,
        "seek: challenge-page classification no longer detects the standard marker.",
    )
    _check(
        classify_detail_page_text("Senior Business Analyst role") == "ok",
        issues,
        "seek: normal detail-page text no longer classifies as ok.",
    )
    _check(
        classify_seek_apply_method("Quick apply") == "quick_apply",
        issues,
        "seek: apply-button classification no longer detects Quick Apply.",
    )
    checks.append("SEEK extraction helpers still parse key sample fields and page states.")

    return _build_result(SOURCE_SEEK, checks, issues)


def _validate_linkedin_configuration() -> dict[str, Any]:
    issues: list[str] = []
    checks: list[str] = []

    targets = build_linkedin_search_targets(_sample_profile()["search_settings"])
    _check(
        len(targets) == 1,
        issues,
        "linkedin: expected one LinkedIn search target for sample settings.",
    )
    if targets:
        target = targets[0]
        _check(
            str(target.get("search_term") or "").strip() == "business analyst",
            issues,
            "linkedin: sample search term was lost.",
        )
        _check(bool(target.get("location")), issues, "linkedin: sample location scope was empty.")
        _check(
            int(target.get("hours_old") or 0) > 0,
            issues,
            "linkedin: hours_old must remain a positive integer.",
        )
        _check(
            int(target.get("results_wanted") or 0) > 0,
            issues,
            "linkedin: results_wanted must remain a positive integer.",
        )
    checks.append("LinkedIn search target builder preserves sample keyword, location scope, and limits.")

    _check(
        classify_linkedin_apply_method("", "https://linkedin.com/jobs/view/1") == "easy_apply",
        issues,
        "linkedin: blank apply_url should still mean Easy Apply.",
    )
    _check(
        classify_linkedin_apply_method(
            "https://company.example/jobs/1",
            "https://linkedin.com/jobs/view/1",
        )
        == "external_apply",
        issues,
        "linkedin: external apply URL should still classify as external_apply.",
    )
    checks.append("LinkedIn apply-method classifier still covers Easy Apply and external apply.")

    return _build_result(SOURCE_LINKEDIN, checks, issues)


def _validate_apsjobs_configuration() -> dict[str, Any]:
    issues: list[str] = []
    checks: list[str] = []

    parsed = urlsplit(APSJOBS_JOB_SEARCH_URL)
    _check(parsed.scheme == "https", issues, "apsjobs: APSJOBS_JOB_SEARCH_URL must use https.")
    _check(parsed.netloc == "www.apsjobs.gov.au", issues, "apsjobs: unexpected APSJobs host.")
    _check(
        parsed.path.rstrip("/") == "/s/job-search",
        issues,
        "apsjobs: APSJOBS_JOB_SEARCH_URL must point to /s/job-search.",
    )
    checks.append("APSJobs search URL points to the expected host and path.")

    _check_selectors(
        SOURCE_APSJOBS,
        APSJOBS_SEARCH_INPUT_SELECTORS,
        issues,
        label="search input selectors",
    )
    _check_selectors(
        SOURCE_APSJOBS,
        APSJOBS_LOCATION_INPUT_SELECTORS,
        issues,
        label="location input selectors",
    )
    _check_selectors(
        SOURCE_APSJOBS,
        APSJOBS_STATE_SELECTORS,
        issues,
        label="state selectors",
    )
    _check_selectors(
        SOURCE_APSJOBS,
        APSJOBS_SEARCH_BUTTON_SELECTORS,
        issues,
        label="search button selectors",
    )
    _check_selectors(
        SOURCE_APSJOBS,
        APSJOBS_TITLE_SELECTORS,
        issues,
        label="title selectors",
    )
    checks.append("APSJobs selector groups are populated and deduplicated.")

    keywords, targets = build_apsjobs_search_targets(_sample_profile()["search_settings"])
    _check(keywords == "business analyst", issues, "apsjobs: sample keywords were lost.")
    _check(
        len(targets) == 1,
        issues,
        "apsjobs: expected one deduped APSJobs search target for sample settings.",
    )
    if targets:
        target = targets[0]
        _check(
            str(target.get("location") or "").strip() == "NSW",
            issues,
            "apsjobs: sample Sydney location no longer maps to NSW.",
        )
        _check(
            int(target.get("results_wanted") or 0) > 0,
            issues,
            "apsjobs: results_wanted must remain a positive integer.",
        )
    checks.append("APSJobs search target builder still maps sample locations and limits correctly.")

    return _build_result(SOURCE_APSJOBS, checks, issues)


def _record_validation_warning(result: dict[str, Any]) -> dict[str, Any]:
    issues = [str(issue).strip() for issue in result.get("issues", []) if str(issue).strip()]
    return record_system_warning(
        severity="warning",
        category=_VALIDATION_CATEGORY,
        source=str(result.get("source") or "unknown"),
        message=f"{result.get('source')}: scraper configuration validation found {len(issues)} issue(s).",
        fingerprint=make_system_warning_fingerprint(
            _VALIDATION_CATEGORY,
            result.get("source"),
            json.dumps(issues, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        ),
        context={
            "summary": result.get("summary"),
            "checks": result.get("checks", []),
            "issues": issues,
            "checked_at": _now_iso(),
        },
    )


def run_scraper_configuration_validation() -> dict[str, Any]:
    """Run deterministic scraper config checks and record warnings for failures."""

    results = [
        _validate_source_registry(),
        _validate_seek_configuration(),
        _validate_linkedin_configuration(),
        _validate_apsjobs_configuration(),
    ]
    warning_records = [
        _record_validation_warning(result)
        for result in results
        if result.get("status") == "warning"
    ]
    checked_sources = [
        str(result["source"]) for result in results if result["source"] != "source_registry"
    ]
    ok = not warning_records
    summary = (
        f"Scraper validation passed for {', '.join(checked_sources)}."
        if ok
        else f"Scraper validation found issues in {len(warning_records)} check group(s)."
    )
    return {
        "ok": ok,
        "checked_at": _now_iso(),
        "summary": summary,
        "results": results,
        "warnings_recorded": len(warning_records),
    }
