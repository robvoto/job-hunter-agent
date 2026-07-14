"""Helpers for job identity."""

import re
from functools import lru_cache
from typing import Any, Iterable, List, Optional
from urllib.parse import ParseResult, urlsplit, urlunsplit

"""Manages job identity, duplicate detection, and linking across sources.



This module provides functions for normalizing job keys, detecting confirmed

and potential duplicate job postings based on various identifiers (job key, URL,

ATS requisition ID, platform job ID), and annotating records with links to

their duplicates. It relies on managed knowledge for duplicate rules and source

priority to resolve conflicts."""


from job_hunter_agent.company_normalization import company_names_weakly_match
from job_hunter_agent.duplicate_rules import load_duplicate_rules
from job_hunter_agent.paths import UNCERTAINTY_LOG_PATH
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_JOB_KEY,
    RECORD_LOCATION_KEY,
    RECORD_RUN_STARTED_AT_KEY,
    RECORD_POTENTIAL_DUPLICATE_LINKS_KEY,
    RECORD_SOURCE_ATS_REQUISITION_ID_KEY,
    RECORD_SOURCE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_NAME_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.runtime_helpers import append_uncertainty_log, build_uncertainty_entry
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.source_registry import get_domain_to_source_map
from job_hunter_agent.title_normalization_rules import normalize_title_text


@lru_cache(maxsize=1)
def _get_identity_config() -> dict[str, Any]:
    """Load identity matching rules from managed knowledge."""

    return load_duplicate_rules()


def normalize_job_key(value: str, source: Optional[str] = None) -> str:
    """

    Strict job key normalization (canonical format: 'source:id').

    When a source is provided, raw slugs and numeric ids are namespaced to that source.

    """

    raw = str(value or "").strip().lower()

    if not raw:
        return ""

    # 1. Already follows canonical format? (e.g. 'seek:12345')

    if ":" in raw:
        if re.match(r"^[a-z]+:[a-z0-9_-]+$", raw):
            return raw

    # 1b. Some review flows store already-canonical slug keys without a source.

    if source is None and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", raw):
        return raw

    # 2. Extraction from standard URL patterns

    id_match = re.search(r"/job(?:s)?/(?:view/)?(\d+)", raw)

    # 2b. Salesforce-style listing URLs (e.g. APSJobs): the id lives in a
    # 'job-details/<id>' path segment or an 'id=' / 'jobid=' / 'job_id='
    # query parameter, not a numeric '/job/<id>' path segment.
    if not id_match:
        id_match = re.search(r"/job-?details?/([a-z0-9]+)", raw) or re.search(
            r"[?&](?:job_?id|id)=([a-z0-9]+)", raw
        )

    id_part = ""

    source_part = str(source or "").strip().lower()

    if id_match:
        id_part = id_match.group(1)

        if not source_part:
            domain_map = get_domain_to_source_map()

            for domain, mapped_source in domain_map.items():
                if domain in raw:
                    source_part = mapped_source

                    break

    elif re.fullmatch(r"\d+", raw):
        id_part = raw

    elif source_part and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", raw):
        id_part = raw

    # 3. Strict Canonical Assembly

    if id_part and source_part:
        return f"{source_part}:{id_part}"

    return ""


def _normalize_identity_text(text: str) -> str:

    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _source_label(record: dict) -> str:

    source = (
        str(record.get(RECORD_SOURCE_KEY) or record.get(RECORD_SOURCE_NAME_KEY) or "")
        .strip()
        .lower()
    )

    return source


def _source_metadata(record: dict) -> dict:

    metadata = record.get(RECORD_SOURCE_METADATA_KEY)

    return metadata if isinstance(metadata, dict) else {}


def _normalized_url(record: dict) -> str:

    raw_url = str(record.get(RECORD_URL_KEY) or "").strip()

    if not raw_url:
        return ""

    try:  # Catches ValueError for malformed URLs
        parsed: ParseResult = urlsplit(raw_url)

        parsed = urlsplit(raw_url)

    except ValueError:
        return raw_url.split("#", 1)[0].split("?", 1)[0].strip().lower()

    normalized_path = parsed.path.rstrip("/")

    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, "", ""))


def _normalized_job_key(record: dict) -> str:

    val = record.get(RECORD_JOB_KEY) or ""

    source = record.get(RECORD_SOURCE_KEY) or record.get(RECORD_SOURCE_NAME_KEY)

    return normalize_job_key(str(val), source=source)


def _confirmed_duplicate_signatures(record: dict) -> dict[str, str]:

    signatures: dict[str, str] = {}

    job_key = _normalized_job_key(record)

    if job_key:
        signatures["job_key"] = job_key

    url = _normalized_url(record)

    if url:
        signatures["url"] = url

    metadata = _source_metadata(record)

    ats_requisition_id = _normalize_identity_text(
        str(metadata.get(RECORD_SOURCE_ATS_REQUISITION_ID_KEY) or "")
    )

    if ats_requisition_id:
        ats_source = _normalize_identity_text(
            str(metadata.get("ats_source") or _source_label(record))
        )

        if ats_source:
            signatures["ats_requisition_id"] = f"{ats_source}:{ats_requisition_id}"

    platform_job_id = _normalize_identity_text(
        str(metadata.get(RECORD_SOURCE_PLATFORM_JOB_ID_KEY) or "")
    )

    if platform_job_id:
        source = _source_label(record)

        if source:
            signatures["platform_job_id"] = f"{source}:{platform_job_id}"

    return signatures


def _confirmed_duplicate_match(a: dict, b: dict) -> Optional[tuple[str, str]]:

    signatures_a = _confirmed_duplicate_signatures(a)

    signatures_b = _confirmed_duplicate_signatures(b)

    for key in ("job_key", "url", "ats_requisition_id", "platform_job_id"):
        value_a = signatures_a.get(key)

        if value_a and value_a == signatures_b.get(key):
            return key, value_a

    return None


def _duplicate_link(record: dict, matched_on: str, matched_value: str) -> dict[str, Any]:

    metadata = _source_metadata(record)

    return {
        "kind": "confirmed_duplicate",
        "matched_on": matched_on,
        "matched_value": matched_value,
        "source": _source_label(record),
        "title": str(record.get(RECORD_TITLE_KEY) or "").strip(),
        "company": str(record.get(RECORD_COMPANY_KEY) or "").strip(),
        "job_key": _normalized_job_key(record),
        "url": _normalized_url(record),
        "identity_signatures": _confirmed_duplicate_signatures(record),
        "source_metadata": {
            "ats_source": str(metadata.get("ats_source") or "").strip(),
            RECORD_SOURCE_ATS_REQUISITION_ID_KEY: str(
                metadata.get(RECORD_SOURCE_ATS_REQUISITION_ID_KEY) or ""
            ).strip(),
            RECORD_SOURCE_PLATFORM_JOB_ID_KEY: str(
                metadata.get(RECORD_SOURCE_PLATFORM_JOB_ID_KEY) or ""
            ).strip(),
        },
    }


def _duplicate_links(record: dict) -> list[dict]:

    links = record.get(RECORD_DUPLICATE_LINKS_KEY)

    return links if isinstance(links, list) else []


def _set_duplicate_links(record: dict, links: list[dict]) -> None:

    if links:
        record[RECORD_DUPLICATE_LINKS_KEY] = links

    elif RECORD_DUPLICATE_LINKS_KEY in record:
        record.pop(RECORD_DUPLICATE_LINKS_KEY, None)


def _merge_duplicate_links(*link_groups: list[dict]) -> list[dict]:

    merged: list[dict] = []

    seen: set[tuple[str, str, str, str]] = set()

    for group in link_groups:
        for link in group:
            if not isinstance(link, dict):
                continue

            dedupe_key = (
                str(link.get("kind") or ""),
                str(link.get("matched_on") or ""),
                str(link.get("matched_value") or ""),
                str(link.get("job_key") or link.get("url") or ""),
            )

            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)

            merged.append(link)

    return merged


def _append_duplicate_link(
    record: dict, linked_record: dict, matched_on: str, matched_value: str
) -> None:

    links = _duplicate_links(record)

    links.append(_duplicate_link(linked_record, matched_on, matched_value))

    _set_duplicate_links(record, _merge_duplicate_links(links))


def _potential_duplicate_signature(record: dict) -> dict[str, str]:

    title = str(record.get(RECORD_TITLE_KEY) or "").strip()

    return {"normalized_title": normalize_title_text(title)}


def _potential_duplicate_link(record: dict, matched_on: list[str]) -> dict[str, Any]:

    url = _normalized_url(record)

    link: dict[str, Any] = {
        "kind": "potential_duplicate",
        "matched_on": matched_on,
        "related_job_key": str(record.get(RECORD_JOB_KEY) or "").strip(),
        "related_title": str(record.get(RECORD_TITLE_KEY) or "").strip(),
        "related_company": str(record.get(RECORD_COMPANY_KEY) or "").strip(),
        "related_source": _source_label(record),
    }

    if url and url != "#":
        link["related_url"] = url

    return link


def _record_label(record: dict) -> str:
    """One-line description of a record for log messages: title / company / location (key)."""

    title = str(record.get(RECORD_TITLE_KEY) or "").strip()

    company = str(record.get(RECORD_COMPANY_KEY) or "").strip()

    location = str(record.get(RECORD_LOCATION_KEY) or "").strip()

    key = _normalized_job_key(record) or str(record.get(RECORD_JOB_KEY) or "")

    parts = " / ".join(p for p in [title, company, location] if p)

    return f"{parts} ({key})" if key else parts


def _log_potential_duplicate(a: dict, b: dict, matched_on: list[str]) -> None:
    """Log when two jobs match on title+company but cannot be confirmed as the same posting."""

    detail = (
        f"Two jobs matched on {', '.join(matched_on)} but could not be confirmed as the same posting. "
        f"A: {_record_label(a)}. B: {_record_label(b)}. "
        "Review whether these are the same role or distinct postings."
    )

    append_uncertainty_log(
        UNCERTAINTY_LOG_PATH,
        build_uncertainty_entry(
            reason_code="POTENTIAL_DUPLICATE_DETECTED",
            stage="deduplication",
            field="job_identity",
            raw_value=f"{_normalized_job_key(a)} | {_normalized_job_key(b)}",
            normalized_value=", ".join(matched_on),
            detail=detail,
            source="annotate_potential_duplicate_links",
            job_key=_normalized_job_key(a),
            severity="info",
        ),
    )
    record_system_warning(
        severity="info",
        category="job_identity_uncertainty",
        source="annotate_potential_duplicate_links",
        message=detail,
        fingerprint=make_system_warning_fingerprint(
            "job_identity",
            "potential_duplicate_detected",
            _normalized_job_key(a),
            _normalized_job_key(b),
            ",".join(matched_on),
            detail,
        ),
        job_key=_normalized_job_key(a),
        run_id=str(a.get(RECORD_RUN_STARTED_AT_KEY) or b.get(RECORD_RUN_STARTED_AT_KEY) or ""),
        context={
            "reason_code": "POTENTIAL_DUPLICATE_DETECTED",
            "matched_on": matched_on,
            "related_job_key": _normalized_job_key(b),
            "related_title": str(b.get(RECORD_TITLE_KEY) or "").strip(),
            "related_company": str(b.get(RECORD_COMPANY_KEY) or "").strip(),
        },
    )


def _log_dedup_company_missing(a: dict, b: dict, normalized_title: str) -> None:
    """Log when titles match but company is absent — duplicate status is unverifiable."""

    company_a = str(a.get(RECORD_COMPANY_KEY) or "").strip()

    company_b = str(b.get(RECORD_COMPANY_KEY) or "").strip()

    missing_side = "B" if not company_b else "A"

    detail = (
        f"Title normalized to '{normalized_title}' matched between two jobs but company is missing on side {missing_side} — "
        f"cannot confirm or deny duplicate. A: {_record_label(a)}. B: {_record_label(b)}."
    )

    append_uncertainty_log(
        UNCERTAINTY_LOG_PATH,
        build_uncertainty_entry(
            reason_code="DEDUP_COMPANY_MISSING",
            stage="deduplication",
            field="company",
            raw_value=f"A: '{company_a}' | B: '{company_b}'",
            normalized_value=normalized_title,
            detail=detail,
            source="_potential_duplicate_match",
            job_key=_normalized_job_key(a),
            severity="warning",
        ),
    )
    record_system_warning(
        severity="warning",
        category="job_identity_uncertainty",
        source="_potential_duplicate_match",
        message=detail,
        fingerprint=make_system_warning_fingerprint(
            "job_identity",
            "dedup_company_missing",
            _normalized_job_key(a),
            _normalized_job_key(b),
            normalized_title,
            company_a,
            company_b,
            detail,
        ),
        job_key=_normalized_job_key(a),
        run_id=str(a.get(RECORD_RUN_STARTED_AT_KEY) or b.get(RECORD_RUN_STARTED_AT_KEY) or ""),
        context={
            "reason_code": "DEDUP_COMPANY_MISSING",
            "normalized_title": normalized_title,
            "company_a": company_a,
            "company_b": company_b,
            "missing_side": missing_side,
        },
    )


def _set_potential_duplicate_links(record: dict, links: list[dict]) -> None:

    if links:
        record[RECORD_POTENTIAL_DUPLICATE_LINKS_KEY] = links

    elif RECORD_POTENTIAL_DUPLICATE_LINKS_KEY in record:
        record.pop(RECORD_POTENTIAL_DUPLICATE_LINKS_KEY, None)


def _potential_duplicate_match(a: dict, b: dict) -> Optional[list[str]]:

    signatures_a = _potential_duplicate_signature(a)

    signatures_b = _potential_duplicate_signature(b)

    matched_on: list[str] = []

    if (
        signatures_a["normalized_title"]
        and signatures_a["normalized_title"] == signatures_b["normalized_title"]
    ):
        matched_on.append("normalized_title")

    if not matched_on:
        return None

    company_a = str(a.get(RECORD_COMPANY_KEY) or "")

    company_b = str(b.get(RECORD_COMPANY_KEY) or "")

    if not company_a.strip() or not company_b.strip():
        # Title matched but company is absent — can't confirm or deny; surface it.

        _log_dedup_company_missing(a, b, signatures_a["normalized_title"])

        return None

    if not company_names_weakly_match(company_a, company_b):
        return None

    matched_on.append("company_name")

    return matched_on


def annotate_potential_duplicate_links(records: List[dict]) -> List[dict]:
    """Attach potential duplicate links without collapsing records."""

    potential_link_map: dict[int, list[dict]] = {index: [] for index in range(len(records))}

    for index, record in enumerate(records):
        for other_index in range(index + 1, len(records)):
            other = records[other_index]

            matched_on = _potential_duplicate_match(record, other)

            if not matched_on:
                continue

            potential_link_map[index].append(_potential_duplicate_link(other, matched_on))

            potential_link_map[other_index].append(_potential_duplicate_link(record, matched_on))

            _log_potential_duplicate(record, other, matched_on)

    for index, record in enumerate(records):
        _set_potential_duplicate_links(record, potential_link_map.get(index, []))

    return records


def _source_priority(record: dict) -> int:

    source_map = _get_identity_config().get("source_priority", {})

    source = _source_label(record)

    fallback_priority = (max(source_map.values()) + 1) if source_map else 1

    return source_map.get(source, fallback_priority)


def are_jobs_confirmed_duplicates(a: dict, b: dict) -> bool:
    """Return True only when two records share a deterministic identity."""

    return _confirmed_duplicate_match(a, b) is not None


def find_confirmed_duplicate(record: dict, pool: Iterable[dict]) -> Optional[dict]:
    """Return only a confirmed duplicate from the supplied pool."""

    for candidate in pool:
        if are_jobs_confirmed_duplicates(record, candidate):
            return candidate

    return None


def deduplicate_across_sources(records: List[dict]) -> List[dict]:
    """Collapse only confirmed duplicates and keep explicit duplicate links."""

    deduped: List[dict] = []

    for record in records:
        duplicate_index = None

        duplicate_match: Optional[tuple[str, str]] = None

        for index, kept in enumerate(deduped):
            match = _confirmed_duplicate_match(record, kept)

            if match:
                duplicate_index = index

                duplicate_match = match

                break

        if duplicate_index is not None and duplicate_match is not None:
            matched_on, matched_value = duplicate_match

            kept_record = deduped[duplicate_index]

            if _source_priority(record) < _source_priority(kept_record):
                _append_duplicate_link(record, kept_record, matched_on, matched_value)

                _set_duplicate_links(
                    record,
                    _merge_duplicate_links(_duplicate_links(record), _duplicate_links(kept_record)),
                )

                deduped[duplicate_index] = record

            else:
                _append_duplicate_link(kept_record, record, matched_on, matched_value)

            continue

        deduped.append(record)

    return annotate_potential_duplicate_links(deduped)
