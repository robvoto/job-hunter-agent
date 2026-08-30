"""Shared search-term planning from the candidate profile."""

from __future__ import annotations

from job_hunter_agent.profile_store import (
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
)


def ordered_profile_search_terms(search_settings: dict, profile: dict | None = None) -> list[str]:
    """Return configured role search terms in stable, case-insensitive deduplicated order."""
    candidates: list[str] = []
    if isinstance(profile, dict):
        for key in (
            KEY_PRIMARY_PATTERNS,
            KEY_SECONDARY_PATTERNS,
        ):
            values = profile.get(key) or []
            if not isinstance(values, list):
                continue
            candidates.extend(str(value).strip() for value in values)

    if not any(str(value).strip() for value in candidates):
        candidates.append(str(search_settings.get("keywords") or "").strip())

    ordered_terms: list[str] = []
    seen_terms: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split()).strip()
        if not normalized:
            continue
        dedupe_key = normalized.casefold()
        if dedupe_key in seen_terms:
            continue
        seen_terms.add(dedupe_key)
        ordered_terms.append(normalized)
    return ordered_terms


def direct_profile_title_match_job_keys(records: list[dict], profile: dict) -> set[str]:
    """Return job keys whose visible titles directly match configured role tiers.

    Search planning uses the existing deterministic title contract only to decide
    whether a query deserves deeper pagination. It does not replace the normal
    review pipeline and does not classify unfamiliar titles as rejected.
    """
    from job_hunter_agent.filters import analyze_title_filters

    matched_job_keys: set[str] = set()
    for record in records:
        job_key = str(record.get("job_key") or "").strip()
        title = str(record.get("title") or "").strip()
        if not job_key or not title:
            continue
        if analyze_title_filters(title, profile).get("ok"):
            matched_job_keys.add(job_key)
    return matched_job_keys
