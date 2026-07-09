"""Helpers for role analysis."""

import re
import string
from functools import lru_cache
from typing import Any, Optional
from urllib.parse import urlparse

from job_hunter_agent.knowledge_store import get_knowledge
from job_hunter_agent.text_processing import compact_whitespace


def friendly_capability_label(name: str) -> str:

    normalized = compact_whitespace(name).lower()

    return normalized[:1].upper() + normalized[1:] if normalized else ""


# HARCODED


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


@lru_cache(maxsize=1)
def _posting_channel_rules() -> dict[str, Any]:
    payload = get_knowledge("posting_channel_indicators") or {}
    rules = payload.get("posting_channel_indicators", {}) if isinstance(payload, dict) else {}
    return rules if isinstance(rules, dict) else {}


_POSTING_CHANNEL_TRANSLATION = str.maketrans(
    {ch: " " for ch in string.punctuation + "“”‘’–—…"}
)


def _posting_channel_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        compact_whitespace(str(value or ""))
        for value in values
        if compact_whitespace(str(value or ""))
    ]


def _posting_channel_plural_map() -> dict[str, str]:
    rules = _posting_channel_rules()
    payload = rules.get("text_classifier", {}) if isinstance(rules, dict) else {}
    plural_map = payload.get("plural_normalisations", {}) if isinstance(payload, dict) else {}
    if not isinstance(plural_map, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in plural_map.items():
        cleaned_key = compact_whitespace(str(key or "")).lower()
        cleaned_value = compact_whitespace(str(value or "")).lower()
        if cleaned_key and cleaned_value:
            result[cleaned_key] = cleaned_value
    return result


def _posting_channel_tokens(text: str, plural_map: Optional[dict[str, str]] = None) -> list[str]:
    cleaned = compact_whitespace(text).lower()
    if not cleaned:
        return []
    mapped = plural_map or {}
    return [
        mapped.get(token, token)
        for token in cleaned.translate(_POSTING_CHANNEL_TRANSLATION).split()
        if token
    ]


def _posting_channel_phrase_entries(values: Any) -> list[tuple[str, list[str]]]:
    plural_map = _posting_channel_plural_map()
    entries: list[tuple[str, list[str]]] = []
    for value in _posting_channel_string_list(values):
        tokens = _posting_channel_tokens(value, plural_map)
        if tokens:
            entries.append((value.lower(), tokens))
    return entries


def _contains_token_sequence(tokens: list[str], phrase: list[str]) -> bool:
    if not tokens or not phrase or len(phrase) > len(tokens):
        return False
    limit = len(tokens) - len(phrase) + 1
    for start in range(limit):
        if tokens[start : start + len(phrase)] == phrase:
            return True
    return False


def _token_positions(tokens: list[str], terms: list[str]) -> list[tuple[int, str]]:
    positions: list[tuple[int, str]] = []
    terms_set = {term for term in terms if term}
    for index, token in enumerate(tokens):
        if token in terms_set:
            positions.append((index, token))
    return positions


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


def _build_weak_text_matches(details_text: str) -> list[str]:
    rules = _posting_channel_rules()
    text_rules = rules.get("text_classifier", {}) if isinstance(rules, dict) else {}
    if not isinstance(text_rules, dict):
        return []

    plural_map = _posting_channel_plural_map()
    tokens = _posting_channel_tokens(details_text, plural_map)
    if not tokens:
        return []

    matches: list[str] = []

    intermediary_phrases = _posting_channel_phrase_entries(
        text_rules.get("intermediary_phrases", [])
    )
    for phrase_label, phrase_tokens in intermediary_phrases:
        if _contains_token_sequence(tokens, phrase_tokens):
            matches.append(phrase_label)

    if matches:
        return _dedupe_strings(matches)

    first_person_terms = _posting_channel_string_list(text_rules.get("first_person_terms", []))
    client_terms = _posting_channel_string_list(text_rules.get("client_terms", []))
    hiring_terms = _posting_channel_string_list(text_rules.get("hiring_terms", []))

    def _normalised_terms(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            term_tokens = _posting_channel_tokens(value, plural_map)
            if term_tokens:
                result.append(term_tokens[0])
        return result

    first_positions = _token_positions(tokens, _normalised_terms(first_person_terms))
    client_positions = _token_positions(tokens, _normalised_terms(client_terms))
    hiring_positions = _token_positions(tokens, _normalised_terms(hiring_terms))

    for client_index, client_token in client_positions:
        nearest_first = next(
            (
                (first_index, first_token)
                for first_index, first_token in reversed(first_positions)
                if 0 < client_index - first_index <= 2
            ),
            None,
        )
        if not nearest_first:
            continue
        nearest_hiring = next(
            (
                (hiring_index, hiring_token)
                for hiring_index, hiring_token in hiring_positions
                if 0 < abs(hiring_index - client_index) <= 4
            ),
            None,
        )
        if not nearest_hiring:
            continue

        _, first_token = nearest_first
        hiring_index, _ = nearest_hiring
        matches.append(f"{first_token} {client_token}")
        span_start = min(client_index, hiring_index)
        span_end = max(client_index, hiring_index)
        matches.append(" ".join(tokens[span_start : span_end + 1]))

    return _dedupe_strings(matches)


def _posting_channel_company_evidence(record: dict) -> tuple[list[str], bool]:
    rules = _posting_channel_rules()
    company_rules = rules.get("company_indicators", {}) if isinstance(rules, dict) else {}
    if not isinstance(company_rules, dict):
        return [], False

    exact_names = {
        compact_whitespace(str(value or "")).lower()
        for value in company_rules.get("strong_names", [])
        if compact_whitespace(str(value or ""))
    }
    exact_domains = {
        compact_whitespace(str(value or "")).lower().removeprefix("www.")
        for value in company_rules.get("strong_domains", [])
        if compact_whitespace(str(value or ""))
    }
    strong_terms = _posting_channel_phrase_entries(company_rules.get("strong_terms", []))
    weak_terms = _posting_channel_phrase_entries(company_rules.get("weak_terms", []))

    metadata = _source_metadata(record)
    candidate_names = _dedupe_strings(
        [
            str(record.get("company") or ""),
            str(metadata.get("company_profile_name") or ""),
            str(metadata.get("poster_company") or ""),
            str(metadata.get("hiring_company") or ""),
        ]
    )
    candidate_domains = _dedupe_strings(
        [
            str(metadata.get("apply_domain") or ""),
            str(metadata.get("company_profile_url") or ""),
            str(metadata.get("apply_url") or ""),
        ]
    )

    def _normalize_domain(value: str) -> str:
        cleaned = compact_whitespace(value).lower()
        if not cleaned:
            return ""
        if "://" in cleaned:
            parsed = urlparse(cleaned)
            cleaned = parsed.netloc or parsed.path
        cleaned = cleaned.lstrip("www.")
        return cleaned

    for name in candidate_names:
        normalized_name = compact_whitespace(name).lower()
        if normalized_name in exact_names:
            return [f"company name = {name}"], False
        name_tokens = _posting_channel_tokens(name, _posting_channel_plural_map())
        if any(_contains_token_sequence(name_tokens, phrase_tokens) for _, phrase_tokens in strong_terms):
            return [f"company name = {name}"], False
        if any(_contains_token_sequence(name_tokens, phrase_tokens) for _, phrase_tokens in weak_terms):
            return [f"company name = {name}"], True

    for domain in candidate_domains:
        normalized_domain = _normalize_domain(domain)
        if not normalized_domain:
            continue
        if normalized_domain in exact_domains:
            return [f"apply domain = {normalized_domain}"], False
        domain_tokens = _posting_channel_tokens(normalized_domain, _posting_channel_plural_map())
        if any(_contains_token_sequence(domain_tokens, phrase_tokens) for _, phrase_tokens in strong_terms):
            return [f"apply domain = {normalized_domain}"], False
        if any(_contains_token_sequence(domain_tokens, phrase_tokens) for _, phrase_tokens in weak_terms):
            return [f"apply domain = {normalized_domain}"], True

    return [], False


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


def infer_posting_channel(record: dict, details_text: str) -> dict[str, Any]:
    metadata_context = _source_metadata(record)
    trusted_metadata, trusted_recruiter, trusted_employer = (
        _collect_trusted_posting_channel_metadata(record)
    )

    text_evidence = _build_weak_text_matches(details_text)
    company_evidence, company_needs_review = _posting_channel_company_evidence(record)
    company_source = "company_or_domain_indicator" if company_evidence else ""
    weak_text_matches = text_evidence or company_evidence

    if trusted_recruiter:
        return {
            "kind": "agency_or_recruiter",
            "source": "metadata_first",
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "text_evidence": weak_text_matches,
            "needs_review": False,
        }

    if trusted_employer:
        return {
            "kind": "direct_employer",
            "source": "metadata_first",
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "text_evidence": weak_text_matches,
            "needs_review": False,
        }

    if company_evidence:
        return {
            "kind": "agency_or_recruiter",
            "source": company_source,
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "text_evidence": weak_text_matches,
            "needs_review": company_needs_review,
        }

    if text_evidence:
        return {
            "kind": "agency_or_recruiter",
            "source": "text_window_classifier",
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "text_evidence": weak_text_matches,
            "needs_review": True,
        }

    return {
        "kind": "unknown",
        "source": "metadata_first" if metadata_context else "insufficient_evidence",
        "trusted_metadata": trusted_metadata,
        "weak_text_matches": [],
        "text_evidence": [],
        "needs_review": False,
    }
