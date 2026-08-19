"""Helpers for role analysis."""

import re
from typing import Any

from job_hunter_agent.record_schema import (
    POSTING_CHANNEL_CLASSIFIER_VERSION,
    POSTING_CHANNEL_VERSION_KEY,
    SOURCE_POSTER_COMPANY_INDUSTRY_KEY,
)
from job_hunter_agent.text_processing import compact_whitespace


def friendly_capability_label(name: str) -> str:

    normalized = compact_whitespace(name).lower()

    return normalized[:1].upper() + normalized[1:] if normalized else ""


def role_text_bundle(record: dict, details_text: str) -> str:

    return "\n".join(
        compact_whitespace(part)
        for part in [
            record.get("title"),
            record.get("company"),
            record.get("teaser"),
            details_text,
        ]
        if compact_whitespace(part)
    )


def text_contains_term(text: str, term: str) -> bool:

    cleaned_text = compact_whitespace(text).lower()

    cleaned_term = compact_whitespace(term).lower()

    if not cleaned_text or not cleaned_term:
        return False

    pattern = rf"(?<!\w){re.escape(cleaned_term)}(?!\w)"

    return re.search(pattern, cleaned_text) is not None


def _source_metadata(record: dict) -> dict:

    metadata = record.get("source_metadata")

    return metadata if isinstance(metadata, dict) else {}


def _raw_source_fields(metadata: dict) -> dict:

    raw_fields = metadata.get("raw_source_fields")

    return raw_fields if isinstance(raw_fields, dict) else {}


def _dedupe_strings(values: list[str]) -> list[str]:

    seen: set[str] = set()

    result: list[str] = []

    for value in values:
        cleaned = compact_whitespace(value)

        if not cleaned or cleaned in seen:
            continue

        seen.add(cleaned)

        result.append(cleaned)

    return result


def _collect_trusted_posting_channel_metadata(record: dict) -> tuple[list[str], bool]:

    metadata = _source_metadata(record)

    raw_fields = _raw_source_fields(metadata)

    trusted_metadata: list[str] = []

    explicit_recruiter_keys = (
        "recruiter_badge",
        "recruiterBadge",
        "agency_specific_reference",
        "agencySpecificReferences",
    )

    non_decisive_source_keys = (
        "seekPostingSourceCode",
        "seekPartnerMetadata",
        "seekHirerJobReference",
        "hirer",
        "hirer_relationship",
        "hirerRelationship",
        "company_url_direct",
        "job_url_direct",
    )

    for key in explicit_recruiter_keys:
        value = raw_fields.get(key)

        if value is not None and compact_whitespace(value):
            trusted_metadata.append(key)

    # These are useful source facts, but none proves that the publisher is the
    # end employer. Recruiters can own ATS/application URLs and hirer references,
    # so semantic classification stays with the LLM unless the board exposes an
    # explicit recruiter/agency marker.
    for key in non_decisive_source_keys:
        value = raw_fields.get(key)

        if value is not None and compact_whitespace(value):
            trusted_metadata.append(key)

    poster_industry = compact_whitespace(metadata.get(SOURCE_POSTER_COMPANY_INDUSTRY_KEY) or "")
    if poster_industry:
        trusted_metadata.append(f"poster industry = {poster_industry}")

    apply_domain = compact_whitespace(metadata.get("apply_domain") or "")

    company_profile_url = compact_whitespace(metadata.get("company_profile_url") or "")

    if apply_domain:
        trusted_metadata.append(f"apply domain = {apply_domain}")

    if company_profile_url:
        trusted_metadata.append(f"company profile link = {company_profile_url}")

    trusted_metadata = _dedupe_strings(trusted_metadata)

    trusted_recruiter = any(
        key in raw_fields and compact_whitespace(raw_fields.get(key))
        for key in explicit_recruiter_keys
    )

    return trusted_metadata, trusted_recruiter


def posting_channel_evidence_is_current(value: object) -> bool:
    """Return whether derived posting-channel evidence matches the active contract."""
    return (
        isinstance(value, dict)
        and value.get(POSTING_CHANNEL_VERSION_KEY) == POSTING_CHANNEL_CLASSIFIER_VERSION
    )


def infer_posting_channel(record: dict, llm_posting_channel: dict[str, Any] | None) -> dict[str, Any]:
    """Decide who posted this ad without inventing employer identity from URLs.

    Only explicit recruiter/agency metadata may decide deterministically. Publisher
    URLs, company profiles, industries, and hirer references remain factual evidence,
    but ambiguous meaning is delegated to the LLM review.
    """
    trusted_metadata, trusted_recruiter = _collect_trusted_posting_channel_metadata(record)

    if trusted_recruiter:
        return {
            POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
            "kind": "agency_or_recruiter",
            "source": "metadata_first",
            "trusted_metadata": trusted_metadata,
            "text_evidence": [],
            "needs_review": False,
        }

    llm_signal = llm_posting_channel if isinstance(llm_posting_channel, dict) else {}
    llm_kind = str(llm_signal.get("kind") or "unknown")
    llm_evidence = compact_whitespace(llm_signal.get("evidence") or "")

    if llm_kind in {"agency_or_recruiter", "direct_employer"}:
        return {
            POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
            "kind": llm_kind,
            "source": "llm_classifier",
            "trusted_metadata": trusted_metadata,
            "text_evidence": [llm_evidence] if llm_evidence else [],
            "needs_review": not bool(llm_signal.get("confident")),
        }

    return {
        POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
        "kind": "unknown",
        "source": "llm_classifier" if llm_signal else "insufficient_evidence",
        "trusted_metadata": trusted_metadata,
        "text_evidence": [llm_evidence] if llm_evidence else [],
        "needs_review": False,
    }
