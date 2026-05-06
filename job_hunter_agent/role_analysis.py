import re
from typing import Optional

from job_hunter_agent.io_utils import load_json_dict, load_parsing_rules
from job_hunter_agent.paths import (
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    GOVERNMENT_CONTEXT_RULES_PATH,
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
        return {"kind": "government", "label": "Government", "confidence": "high"}
    return {"kind": "unknown", "label": "", "confidence": "unknown"}


def infer_posting_channel(record: dict, details_text: str) -> dict[str, str]:
    company = compact_whitespace(record.get("company") or "").lower()
    title = compact_whitespace(record.get("title") or "").lower()
    teaser = compact_whitespace(record.get("teaser") or "").lower()
    description = compact_whitespace(details_text).lower()
    combined = "\n".join(part for part in [title, company, teaser, description] if part)

    rules = load_parsing_rules().get("posting_channel_indicators", {})
    recruiter_keywords = rules.get("recruiter_keywords", [])
    recruiter_copy_patterns = [rf"\b{p}\b" for p in rules.get("recruiter_copy_patterns", [])]
    direct_copy_patterns = [rf"\b{p}\b" for p in rules.get("direct_copy_patterns", [])]

    recruiter_keyword_pattern = rf"\b({'|'.join(recruiter_keywords)})\b"
    recruiter_company_match = re.search(recruiter_keyword_pattern, company, re.IGNORECASE)

    recruiter_score = 0
    direct_score = 0

    if recruiter_company_match:
        recruiter_score += 2
    recruiter_score += sum(1 for pattern in recruiter_copy_patterns if re.search(pattern, combined))
    direct_score += sum(1 for pattern in direct_copy_patterns if re.search(pattern, combined))

    if company and description:
        company_pattern = re.escape(company)
        if re.search(rf"\b(?:at|join|with)\s+{company_pattern}\b", description):
            direct_score += 1
        if re.search(rf"\b{company_pattern}\s+is\b", description):
            direct_score += 1
    #HARCODED
    if recruiter_score >= 3 and recruiter_score > direct_score:
        return {"kind": "recruiter", "label": "Recruiter posting", "confidence": "high"}
    if recruiter_score >= 1 and recruiter_score > direct_score:
        return {"kind": "recruiter", "label": "Recruiter posting", "confidence": "medium"}
    if direct_score >= 3 and recruiter_score == 0:
        return {"kind": "direct_employer", "label": "Direct employer", "confidence": "high"}
    if direct_score >= 1 and recruiter_score == 0:
        return {"kind": "direct_employer", "label": "Direct employer", "confidence": "medium"}
    return {"kind": "unknown", "label": "", "confidence": "unknown"}
