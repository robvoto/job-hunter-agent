import re
from typing import Optional

from job_hunter_agent.io_utils import load_json_dict
from job_hunter_agent.paths import (
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    GOVERNMENT_CONTEXT_RULES_PATH,
    POSTING_CHANNEL_INDICATORS_PATH,
)
from job_hunter_agent.text_processing import compact_whitespace


def friendly_capability_label(name: str) -> str:
    normalized = compact_whitespace(name).lower()
    return normalized[:1].upper() + normalized[1:] if normalized else ""

#HARCODED
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


def _load_government_context_rules() -> tuple[tuple[str, ...], tuple[str, ...]]:
    payload = load_json_dict(GOVERNMENT_CONTEXT_RULES_PATH)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("government_context_rules.json must define an entries list")

    positive_patterns: list[str] = []
    false_positive_patterns: list[str] = []

    def add_pattern(target: list[str], raw_value: str) -> None:
        cleaned = compact_whitespace(raw_value).lower()
        if not cleaned:
            return
        if raw_value.startswith("\\b") or raw_value.endswith("\\b") or any(token in raw_value for token in ("\\d", "[", "(", ")", "^", "$")):
            target.append(raw_value)
        else:
            target.append(rf"\b{re.escape(cleaned)}\b")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        kind = str(entry.get("kind") or "positive").strip().lower()
        value = str(entry.get("value") or "").strip()
        pattern = str(entry.get("pattern") or "").strip()
        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), list) else []
        patterns = [pattern, value, *(str(alias or "").strip() for alias in aliases)]
        for item in patterns:
            if not item:
                continue
            if kind in {"false_positive", "negative", "ignore"}:
                add_pattern(false_positive_patterns, item)
            else:
                add_pattern(positive_patterns, item)

    if not positive_patterns:
        raise ValueError("government_context_rules.json must define at least one enabled positive entry")

    return tuple(positive_patterns), tuple(false_positive_patterns)


def _load_government_context_knowledge_patterns() -> tuple[str, ...]:
    knowledge_payload = load_json_dict(GOVERNMENT_CONTEXT_KNOWLEDGE_PATH)
    knowledge_entries = knowledge_payload.get("entries") if isinstance(knowledge_payload, dict) else []
    if not isinstance(knowledge_entries, list):
        return tuple()

    patterns: list[str] = []
    seen: set[str] = set()
    for entry in knowledge_entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        value = str(entry.get("value") or "").strip()
        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), list) else []
        for item in [value, *(str(alias or "").strip() for alias in aliases)]:
            cleaned = compact_whitespace(item).lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            patterns.append(rf"(?<!\w){re.escape(cleaned)}(?!\w)")
    return tuple(patterns)


def has_government_context(text: str) -> bool:
    lowered = compact_whitespace(text).lower()
    if not lowered:
        return False
    government_patterns, false_positive_patterns = _load_government_context_rules()
    for pattern in false_positive_patterns:
        lowered = re.sub(pattern, " ", lowered)
    if any(re.search(pattern, lowered) for pattern in government_patterns):
        return True
    return any(re.search(pattern, lowered) for pattern in _load_government_context_knowledge_patterns())


def infer_role_sector(record: dict, details_text: str) -> dict[str, str]:
    company = compact_whitespace(record.get("company") or "").lower()
    combined = f"{company}\n{compact_whitespace(details_text).lower()}"

    if has_government_context(combined):
        return {"kind": "government", "label": "Public sector", "confidence": "high"}
    return {"kind": "unknown", "label": "", "confidence": "unknown"}


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
    rules = load_json_dict(POSTING_CHANNEL_INDICATORS_PATH).get("posting_channel_indicators", {})
    recruiter_keywords = [str(value or "").strip() for value in rules.get("recruiter_keywords", []) if str(value or "").strip()]
    recruiter_copy_patterns = [str(value or "").strip() for value in rules.get("recruiter_copy_patterns", []) if str(value or "").strip()]
    description = compact_whitespace(details_text).lower()
    matches: list[str] = []

    for keyword in recruiter_keywords:
        pattern = rf"(?<!\w){re.escape(keyword.lower())}(?!\w)"
        if re.search(pattern, description, re.IGNORECASE):
            matches.append(keyword)

    for pattern_text in recruiter_copy_patterns:
        if re.search(pattern_text, description, re.IGNORECASE):
            matches.append(pattern_text)

    return _dedupe_strings(matches)


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
        "company_url",
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
    trusted_recruiter = any(key in raw_fields and compact_whitespace(raw_fields.get(key)) for key in recruiter_keys)
    trusted_employer = any(key in raw_fields and compact_whitespace(raw_fields.get(key)) for key in employer_keys)
    return trusted_metadata, trusted_recruiter, trusted_employer


def infer_posting_channel(record: dict, details_text: str) -> dict[str, object]:
    trusted_metadata, trusted_recruiter, trusted_employer = _collect_trusted_posting_channel_metadata(record)
    weak_text_matches = _build_weak_text_matches(details_text)

    if trusted_recruiter:
        return {
            "kind": "agency_or_recruiter",
            "source": "metadata_first",
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "needs_review": False,
        }

    if trusted_employer:
        return {
            "kind": "direct_employer",
            "source": "metadata_first",
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "needs_review": False,
        }

    if weak_text_matches:
        return {
            "kind": "unknown",
            "source": "fallback_text_evidence",
            "trusted_metadata": trusted_metadata,
            "weak_text_matches": weak_text_matches,
            "needs_review": True,
        }

    return {
        "kind": "unknown",
        "source": "metadata_first",
        "trusted_metadata": trusted_metadata,
        "weak_text_matches": [],
        "needs_review": False,
    }
