"""Helpers for role analysis."""

import re
from typing import Any

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


def _collect_trusted_posting_channel_metadata(record: dict) -> tuple[list[str], bool, bool]:

    metadata = _source_metadata(record)

    raw_fields = _raw_source_fields(metadata)

    trusted_metadata: list[str] = []

    recruiter_keys = (
        "seekPostingSourceCode",
        "seekPartnerMetadata",
        "recruiter_badge",
        "recruiterBadge",
        "agency_specific_reference",
        "agencySpecificReferences",
    )

    employer_keys = (
        "seekHirerJobReference",
        "hirer",
        "hirer_relationship",
        "hirerRelationship",
        "company_url_direct",
        "job_url_direct",
    )

    for key in recruiter_keys:
        value = raw_fields.get(key)

        if value is not None and compact_whitespace(value):
            trusted_metadata.append(key)

    for key in employer_keys:
        value = raw_fields.get(key)

        if value is not None and compact_whitespace(value):
            trusted_metadata.append(key)

    apply_domain = compact_whitespace(metadata.get("apply_domain") or "")

    company_profile_url = compact_whitespace(metadata.get("company_profile_url") or "")

    if apply_domain:
        trusted_metadata.append(f"apply domain = {apply_domain}")

    if company_profile_url:
        trusted_metadata.append(f"company profile link = {company_profile_url}")

    trusted_metadata = _dedupe_strings(trusted_metadata)

    trusted_recruiter = any(
        key in raw_fields and compact_whitespace(raw_fields.get(key)) for key in recruiter_keys
    )

    trusted_employer = any(
        key in raw_fields and compact_whitespace(raw_fields.get(key)) for key in employer_keys
    )

    return trusted_metadata, trusted_recruiter, trusted_employer


def infer_posting_channel(record: dict, llm_posting_channel: dict[str, Any] | None) -> dict[str, Any]:
    """Decide who posted this ad: direct employer, agency/recruiter, or unknown.

    Structured publisher metadata (e.g. SEEK's own recruiter/hirer fields) is trusted first
    since it is factual, not inferred. Everything else — including the old company-name and
    ad-copy keyword matching — is delegated to the LLM fit review, which reads the actual ad
    text and isn't fooled by agencies with generic-sounding names (e.g. "Talenza").
    """
    trusted_metadata, trusted_recruiter, trusted_employer = (
        _collect_trusted_posting_channel_metadata(record)
    )

    if trusted_recruiter:
        return {
            "kind": "agency_or_recruiter",
            "source": "metadata_first",
            "trusted_metadata": trusted_metadata,
            "text_evidence": [],
            "needs_review": False,
        }

    if trusted_employer:
        return {
            "kind": "direct_employer",
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
            "kind": llm_kind,
            "source": "llm_classifier",
            "trusted_metadata": trusted_metadata,
            "text_evidence": [llm_evidence] if llm_evidence else [],
            "needs_review": not bool(llm_signal.get("confident")),
        }

    return {
        "kind": "unknown",
        "source": "llm_classifier" if llm_signal else "insufficient_evidence",
        "trusted_metadata": trusted_metadata,
        "text_evidence": [llm_evidence] if llm_evidence else [],
        "needs_review": False,
    }
