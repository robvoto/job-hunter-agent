"""
Main job-source connector and dashboard builder.

Main goals:
- fetch current job listings from all enabled source implementations
- apply deterministic filtering and optional LLM fit review
- persist audit data, run stats, review insights, and dashboard HTML

Notes:
- this file orchestrates individual source connectors (e.g. SEEK, LinkedIn)
- the normalized record shape is intended to be reusable for additional sources
"""

import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from job_hunter_agent.capability_matrix import expand_capability_terms
from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.config import MAX_PAGES_CAP, OUTPUT_HTML
from job_hunter_agent import dashboard_data
from job_hunter_agent.filters import (
    matches_missing_requirement,
    passes_content_filters,
    passes_quick_card_filters,
    passes_saved_rejection_rules,
    passes_title_filters,
    suggest_title_block_phrase,
    suggest_title_block_phrases,
)
from job_hunter_agent.job_identity import (
    deduplicate_across_sources,
    find_similar_job,
)
from job_hunter_agent.llm_gate import build_llm_cache_key, llm_is_enabled, llm_should_consider, normalize_llm_review
from job_hunter_agent.match_labels import score_to_match_level, score_to_match_label
from job_hunter_agent.profile_store import (
    get_match_levels,
    get_evidence_tier_weights,
    get_evidence_tiers,
    get_preference_weights,
    get_scoring_rules,
    get_search_settings,
    load_profile,
)
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.signal_registry import load_registry
from job_hunter_agent.scrapers.seek import (
    SELECTOR_CARDS,
    SELECTOR_COMPANY,
    SELECTOR_POSTED,
    SELECTOR_TITLE,
    build_seek_search_targets,
    extract_card_metadata,
    extract_posted_text_from_card,
    fetch_job_details_payload,
    stable_job_key,
    build_full_seek_url,
)
from job_hunter_agent.paths import (
    AUDIT_RECORDS_PATH as DEBUG_JSON_PATH,
    DATA_DIR,
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH as _GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    JOB_HISTORY_PATH,
    LLM_CACHE_PATH,
    OUTPUT_DIR,
    REPO_ROOT as ROOT_DIR,
    RESULTS_TEMPLATE_PATH,
    REVIEW_DATA_PATH,
    RUN_STATS_PATH,
    TEMPLATES_DIR,
)
from job_hunter_agent.utils import (
    extract_salary,
    extract_work_mode,
    parse_seek_posted_age_days,
    safe_html,
    repair_text,
    set_page_param,
)


MAX_LLM_CHARS = 3000
ARCHIVE_STALE_AFTER_DAYS = 15
HIDDEN_REVIEW_DAYS = 30
CLI_FLAGS = set(sys.argv[1:])
_max_pages_arg = next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--max-pages"), None)
CLI_MAX_PAGES_CAP = int(_max_pages_arg) if _max_pages_arg and _max_pages_arg.isdigit() else None
NO_LLM_MODE = "--no-llm" in CLI_FLAGS
CHEAP_LLM_MODE = "--cheap-llm" in CLI_FLAGS
DASHBOARD_DEBUG_MODE = "--debug-dashboard" in CLI_FLAGS
EXPAND_DASHBOARD_MODE = "--expand-dashboard" in CLI_FLAGS or DASHBOARD_DEBUG_MODE
LOW_SCRAPE_MODE = "--scrape-allow-low" in CLI_FLAGS
EXPANDED_POOL_MODE = EXPAND_DASHBOARD_MODE or LOW_SCRAPE_MODE
TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING = "--reset-new-to-you" in CLI_FLAGS
SKIP_QUICK_CARD_GATE_FOR_TESTING = False
SHOW_SCORES_MODE = "--show-scores" in CLI_FLAGS or DASHBOARD_DEBUG_MODE
SHOW_SCORING_DEBUG = SHOW_SCORES_MODE
DASHBOARD_MIN_SCORE = 35 if EXPANDED_POOL_MODE else 50
DEFAULT_SCORE_FILTER_MIN = DASHBOARD_MIN_SCORE
MIN_TRUSTED_DESCRIPTION_LENGTH = 600
TRUSTED_DESCRIPTION_SOURCES = frozenset({"jobaddetails", "body", "linkedin_full_description"})
DESCRIPTION_CAPTURE_ISSUE = "Full job description not captured clearly"
ARCHIVE_LABEL = "Saved From Earlier Searches"
ARCHIVE_BADGE_TOOLTIP = "This role was saved from an earlier search and kept on your dashboard."
ARCHIVE_CONTEXT_PREFIX = "Saved From Earlier Searches"
MAX_HISTORY_SIGHTINGS = 24
REPEATED_LISTING_MIN_TIMES_SEEN = 4
REPEATED_LISTING_MIN_SPAN_DAYS = 21
MULTI_LISTING_RED_FLAG_MIN_LISTINGS = 3
MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS = 30

KEEP_SNAPSHOT_FIELDS = (
    "title",
    "company",
    "url",
    "posted",
    "posted_age_days",
    "salary",
    "work_mode",
    "location",
    "work_type",
    "teaser",
    "title_reason",
    "content_reason",
    "llm_decision",
    "llm_fit_grade",
    "search_location",
    "search_keywords",
    "fit_source_text",
    "full_description",
    "fit_confidence",
    "details_status",
    "description_source",
    "role_snapshot",
    "fit_highlights",
    "soft_risk_reasons",
    "missing_evidence",
    "competitive_signals",
    "hard_block_reasons",
    "reviewed_signal_matches",
)


def salary_sort_value(value: str) -> float:
    """Return a single numeric value for sorting (uses the lower bound of ranges)."""
    if not value or value == "N/A":
        return 0.0
    text = value.lower().replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*k", text)
    if match:
        return float(match.group(1)) * 1000
    match = re.search(r"\$(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return 0.0


def _salary_max_value(value: str) -> float:
    """Return the upper bound of a salary range for minimum-target comparisons.

    For '$450 - $700 per day' returns 700; for '$130k-$145k p.a.' returns 145000.
    Falls back to salary_sort_value when only one figure is present.
    """
    if not value or value == "N/A":
        return 0.0
    text = value.lower().replace(",", "").strip()
    k_vals = [float(m) * 1000 for m in re.findall(r"(\d+(?:\.\d+)?)\s*k", text)]
    if k_vals:
        return max(k_vals)
    dollar_vals = [float(m) for m in re.findall(r"\$(\d+(?:\.\d+)?)", text)]
    if dollar_vals:
        return max(dollar_vals)
    return 0.0


def _salary_includes_super_or_package(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text or text == "n/a":
        return False
    return bool(re.search(r"(?:\bincl\.?\s*super\b|\bincluding\s+super\b|\+\s*super\b|\bsuperannuation\b|\bpackage\b|\bsalary packaging\b)", text))


def normalize_posted_text(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    return re.sub(r"^\s*posted\s+", "", text, flags=re.IGNORECASE).strip()


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json_dict(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_json_list(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_llm_cache() -> Dict[str, Any]:
    raw = load_json_dict(LLM_CACHE_PATH)
    return {str(k): v for k, v in raw.items()}


def save_llm_cache(cache: Dict[str, Any]) -> None:
    save_json(LLM_CACHE_PATH, cache)


def load_job_history() -> Dict[str, dict]:
    return load_json_dict(JOB_HISTORY_PATH)


def save_job_history(history: Dict[str, dict]) -> None:
    save_json(JOB_HISTORY_PATH, history)


def write_debug_json(records: List[dict]) -> None:
    save_json(DEBUG_JSON_PATH, records)


def write_run_stats(payload: dict) -> None:
    save_json(RUN_STATS_PATH, payload)


def write_review_data(payload: dict) -> None:
    save_json(REVIEW_DATA_PATH, payload)


def dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def compact_whitespace(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_text_snippets(text: str) -> List[str]:
    snippets: List[str] = []
    for raw_line in re.split(r"[\r\n]+", text or ""):
        cleaned = compact_whitespace(raw_line.strip(" -\u2022\t"))
        if len(cleaned) >= 24:
            snippets.append(cleaned)
    if snippets:
        return dedupe_preserve_order(snippets)

    compact = compact_whitespace(text)
    if not compact:
        return []
    sentence_like = [
        compact_whitespace(part)
        for part in re.split(r"(?<=[.!?])\s+", compact)
        if len(compact_whitespace(part)) >= 24
    ]
    return dedupe_preserve_order(sentence_like)


def list_to_phrase(items: List[str]) -> str:
    cleaned = [compact_whitespace(item) for item in items if compact_whitespace(item)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _is_generic_summary_text(text: str) -> bool:
    lowered = compact_whitespace(text).lower()
    generic_phrases = (
        "opportunity to join",
        "fast-paced environment",
        "leading company",
        "great opportunity",
        "asap",
        "urgent",
        "must be based in",
        "full working rights",
    )
    return any(phrase in lowered for phrase in generic_phrases)


def synthesize_role_snapshot(record: dict) -> str:
    title = compact_whitespace(record.get("title") or "")
    location = compact_whitespace(record.get("location") or "")
    if location.endswith(", Australia"):
        location = location[:-11].strip()
    work_type = compact_whitespace(record.get("work_type") or "")
    teaser = compact_whitespace(record.get("teaser") or "")

    domain_focus = ""
    if " - " in title:
        domain_focus = compact_whitespace(title.split(" - ", 1)[1])
    elif "(" in title and ")" in title:
        domain_focus = compact_whitespace(re.sub(r"^[^(]*\((.*?)\).*$", r"\1", title))

    summary = ""
    if title and domain_focus and work_type and location and work_type != "N/A" and location != "N/A":
        summary = f"{title} role focused on {domain_focus.lower()} work in {location} on a {work_type.lower()} basis."
    elif title and location and location != "N/A":
        summary = f"{title} role based in {location}."
    elif title:
        summary = f"{title} role."

    if teaser and teaser != "N/A" and not _is_generic_summary_text(teaser):
        summary = f"{summary} {teaser}".strip()

    return summarize_snippet(summary, max_length=220) if summary else "Role summary not available."


def summarize_snippet(snippet: str, max_length: int = 180) -> str:
    cleaned = compact_whitespace(snippet)
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def _clean_summary_candidate(text: str) -> str:
    cleaned = compact_whitespace(text)
    if not cleaned:
        return ""
    if ":" in cleaned[:40]:
        prefix, _, remainder = cleaned.partition(":")
        if 0 < len(prefix.split()) <= 4 and remainder.strip():
            cleaned = compact_whitespace(remainder)
    cleaned = re.sub(r"^[\u2022\-\u2013\u2014]+\s*", "", cleaned).strip()
    return cleaned


def _is_summary_heading(text: str) -> bool:
    cleaned = compact_whitespace(text)
    if not cleaned:
        return True
    if len(cleaned) <= 24 and cleaned.endswith(":"):
        return True
    tokens = cleaned.split()
    if len(tokens) <= 5 and cleaned == cleaned.upper():
        return True
    return False


def _looks_like_generic_job_summary(text: str, title: str, company: str) -> bool:
    cleaned = compact_whitespace(text)
    lowered = cleaned.lower()
    title_lower = compact_whitespace(title).lower()
    company_lower = compact_whitespace(company).lower()
    if not cleaned or len(cleaned) < 45:
        return True
    if cleaned.endswith(":"):
        return True
    if title_lower and lowered == title_lower:
        return True
    if company_lower and lowered == company_lower:
        return True
    if lowered.startswith("about the role") and len(cleaned.split()) <= 4:
        return True
    return False


def description_summary_snippet(record: dict, details_text: str) -> str:
    title = compact_whitespace(record.get("title") or "")
    company = compact_whitespace(record.get("company") or "")
    snippets = [
        _clean_summary_candidate(snippet)
        for snippet in split_text_snippets(details_text)
    ]
    for snippet in snippets:
        if _is_summary_heading(snippet):
            continue
        if _looks_like_generic_job_summary(snippet, title, company):
            continue
        return summarize_snippet(snippet, max_length=220)
    return ""


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

    recruiter_company_match = re.search(
        r"\b(recruitment|recruiter|staffing|resourcing|labour hire|labor hire|executive search|search firm)\b",
        company,
    )
    recruiter_copy_patterns = [
        r"\bour client\b",
        r"\bfor our client\b",
        r"\bon behalf of\b",
        r"\bclient is seeking\b",
        r"\bsubmit (?:your )?(?:cv|resume|application)\b",
        r"\bcontact (?:our )?(?:consultant|recruiter|recruitment team)\b",
        r"\breference number\b",
        r"\bshortlisted candidates\b",
        r"\bimmediate interviews?\b",
    ]
    direct_copy_patterns = [
        r"\babout us\b",
        r"\babout the company\b",
        r"\bwho we are\b",
        r"\bour company\b",
        r"\bour organisation\b",
        r"\bour organization\b",
        r"\bjoin our team\b",
        r"\bjoin us\b",
        r"\bwe are looking for\b",
        r"\bwe are seeking\b",
    ]

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

    if recruiter_score >= 3 and recruiter_score > direct_score:
        return {"kind": "recruiter", "label": "Recruiter posting", "confidence": "high"}
    if recruiter_score >= 1 and recruiter_score > direct_score:
        return {"kind": "recruiter", "label": "Recruiter posting", "confidence": "medium"}
    if direct_score >= 3 and recruiter_score == 0:
        return {"kind": "direct_employer", "label": "Direct employer", "confidence": "high"}
    if direct_score >= 1 and recruiter_score == 0:
        return {"kind": "direct_employer", "label": "Direct employer", "confidence": "medium"}
    return {"kind": "unknown", "label": "", "confidence": "unknown"}


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


def build_role_summary(record: dict, details_text: str, profile: Optional[dict] = None) -> str:
    teaser = compact_whitespace(record.get("teaser") or "")
    title = compact_whitespace(record.get("title") or "")
    location = compact_whitespace(record.get("location") or "")
    work_type = compact_whitespace(record.get("work_type") or "")

    detail_summary = description_summary_snippet(record, details_text)
    if detail_summary:
        return detail_summary

    if teaser and teaser != "N/A" and not _is_generic_summary_text(teaser):
        return summarize_snippet(teaser, max_length=220)

    domain_focus = ""
    if " - " in title:
        domain_focus = compact_whitespace(title.split(" - ", 1)[1])
    elif "(" in title and ")" in title:
        domain_focus = compact_whitespace(re.sub(r"^[^(]*\((.*?)\).*$", r"\1", title))

    base_role = title.split(" - ")[0].split("(")[0].strip() if domain_focus else title

    if title and location and location != "N/A" and work_type and work_type != "N/A":
        intro = f"{base_role} role in {location} ({work_type.lower()})"
    elif title and location and location != "N/A":
        intro = f"{base_role} role in {location}"
    else:
        intro = f"{base_role} role" if base_role else "Role"

    if domain_focus:
        summary = f"{intro} focused on {domain_focus}."
    else:
        summary = f"{intro}."

    return summarize_snippet(summary, max_length=180)


def friendly_capability_label(name: str) -> str:
    normalized = compact_whitespace(name).lower()
    return normalized[:1].upper() + normalized[1:] if normalized else ""

def _load_government_context_knowledge() -> tuple[tuple[str, ...], tuple[str, ...]]:
    payload = load_json_dict(_GOVERNMENT_CONTEXT_KNOWLEDGE_PATH)
    positive_entries = payload.get("positive_patterns")
    false_positive_entries = payload.get("false_positive_patterns")
    if not isinstance(positive_entries, list) or not isinstance(false_positive_entries, list):
        raise ValueError("government_context_knowledge.json must define pattern lists")

    positive_patterns = tuple(
        str(pattern).strip()
        for pattern in positive_entries
        if str(pattern).strip()
    )
    false_positive_patterns = tuple(
        str(pattern).strip()
        for pattern in false_positive_entries
        if str(pattern).strip()
    )
    if not positive_patterns:
        raise ValueError("government_context_knowledge.json must define at least one positive pattern")
    return positive_patterns, false_positive_patterns


_GOVERNMENT_CONTEXT_PATTERNS, _GOVERNMENT_CONTEXT_FALSE_POSITIVE_PATTERNS = _load_government_context_knowledge()


def text_contains_term(text: str, term: str) -> bool:
    cleaned_text = compact_whitespace(text).lower()
    cleaned_term = compact_whitespace(term).lower()
    if not cleaned_text or not cleaned_term:
        return False
    pattern = rf"(?<!\w){re.escape(cleaned_term)}(?!\w)"
    return re.search(pattern, cleaned_text) is not None


def has_government_context(text: str) -> bool:
    lowered = compact_whitespace(text).lower()
    if not lowered:
        return False
    for pattern in _GOVERNMENT_CONTEXT_FALSE_POSITIVE_PATTERNS:
        lowered = re.sub(pattern, " ", lowered)
    return any(re.search(pattern, lowered) for pattern in _GOVERNMENT_CONTEXT_PATTERNS)


def _reviewed_signal_terms(record: dict[str, Any]) -> list[str]:
    values = [record.get("signal"), *(record.get("original_texts") or [])]
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = compact_whitespace(value or "")
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(cleaned)
    return terms


def reviewed_signal_matches_for_text(details_text: str) -> dict[str, list[str]]:
    lowered = compact_whitespace(details_text).lower()
    buckets = {
        "matched": [],
        "evidence_only": [],
        "ignored": [],
        "unresolved": [],
    }
    if not lowered:
        return buckets

    for record in load_registry().values():
        if not isinstance(record, dict):
            continue
        signal = compact_whitespace(record.get("signal") or "")
        decision = compact_whitespace(record.get("decision") or "review").lower()
        if not signal or decision not in {"use", "evidence_only", "ignore", "review"}:
            continue
        terms = _reviewed_signal_terms(record)
        if not terms or not any(text_contains_term(lowered, term) for term in terms):
            continue
        label = compact_whitespace(signal).lower()
        if decision == "use":
            buckets["matched"].append(label)
        elif decision == "evidence_only":
            buckets["evidence_only"].append(label)
        elif decision == "ignore":
            buckets["ignored"].append(label)
        else:
            buckets["unresolved"].append(label)

    return {
        key: dedupe_preserve_order(values)
        for key, values in buckets.items()
    }


def reviewed_signal_match_summary(record: dict, profile: Optional[dict] = None) -> dict[str, list[str]]:
    existing = record.get("reviewed_signal_matches")
    if isinstance(existing, dict):
        return {
            "matched": dedupe_preserve_order(existing.get("matched") or []),
            "evidence_only": dedupe_preserve_order(existing.get("evidence_only") or []),
            "ignored": dedupe_preserve_order(existing.get("ignored") or []),
            "unresolved": dedupe_preserve_order(existing.get("unresolved") or []),
        }
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    return reviewed_signal_matches_for_text(source_text)


def find_profile_capability_matches(details_text: str, profile: dict) -> Dict[str, List[str]]:
    lowered = compact_whitespace(details_text).lower()
    matched_core: List[str] = []
    matched_supporting: List[str] = []
    matched_strong: List[str] = []
    matched_working: List[str] = []
    matched_basic: List[str] = []
    matched_limited_depth: List[str] = []
    matched_must_not: List[str] = []

    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        level = str(rule.get("level") or "").strip().lower()
        fit = str(rule.get("fit") or "").strip().lower()
        terms = expand_capability_terms(rule)
        if not terms:
            continue
        if not any(text_contains_term(lowered, term) for term in terms):
            continue
        label = friendly_capability_label(name)
        if fit == "core":
            matched_core.append(label)
        elif fit == "supporting":
            matched_supporting.append(label)
        if level == "strong":
            matched_strong.append(label)
        elif level == "working":
            matched_working.append(label)
        elif level == "basic":
            matched_basic.append(label)
        elif level == "low":
            matched_limited_depth.append(label)

    for skill in profile.get("must_not_require_skills", []):
        cleaned_skill = str(skill).strip().lower()
        if cleaned_skill and matches_missing_requirement(lowered, cleaned_skill):
            matched_must_not.append(cleaned_skill.upper() if cleaned_skill.isupper() else cleaned_skill)

    return {
        "core": dedupe_preserve_order(matched_core),
        "supporting": dedupe_preserve_order(matched_supporting),
        "strong": dedupe_preserve_order(matched_strong),
        "working": dedupe_preserve_order(matched_working),
        "basic": dedupe_preserve_order(matched_basic),
        "limited_depth": dedupe_preserve_order(matched_limited_depth),
        "must_not": dedupe_preserve_order(matched_must_not),
    }


def _near_desirable_language(text: str, term: str, window: int = 90) -> bool:
    cleaned_text = compact_whitespace(text).lower()
    cleaned_term = compact_whitespace(term).lower()
    if not cleaned_text or not cleaned_term:
        return False
    for match in re.finditer(rf"(?<!\w){re.escape(cleaned_term)}(?!\w)", cleaned_text):
        start = max(match.start() - window, 0)
        end = min(match.end() + window, len(cleaned_text))
        context = cleaned_text[start:end]
        if re.search(
            r"\b(desirable|preferred|highly regarded|nice to have|advantageous|beneficial)\b",
            context,
        ):
            return True
    return False


def description_watchout_reasons(details_text: str, profile: dict) -> List[str]:
    lowered = compact_whitespace(details_text).lower()
    if not lowered:
        return []

    watchouts: List[str] = []

    for skill in profile.get("must_not_require_skills", []):
        cleaned_skill = compact_whitespace(str(skill)).lower()
        if not cleaned_skill or not text_contains_term(lowered, cleaned_skill):
            continue
        label = cleaned_skill.upper() if cleaned_skill.isupper() else cleaned_skill
        if matches_missing_requirement(lowered, cleaned_skill):
            watchouts.append(f"{label} appears required")
        elif _near_desirable_language(lowered, cleaned_skill):
            watchouts.append(f"{label} appears desirable")
        else:
            watchouts.append(f"{label} appears in the description")

    for rule in profile.get("reject_description_phrase_rules", []):
        phrase = compact_whitespace(str(rule.get("phrase") or "")).lower()
        if phrase and phrase in lowered:
            watchouts.append(f"Blocked description phrase appears: {phrase}")

    return dedupe_preserve_order(watchouts)[:4]


def build_fit_highlights(record: dict, details_text: str, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = []
    active_profile = profile or load_profile()
    role_bundle = role_text_bundle(record, details_text)
    lowered = role_bundle.lower()
    capability_matches = find_profile_capability_matches(role_bundle, active_profile)
    title_lower = compact_whitespace(record.get("title") or "").lower()

    matched_profile_areas = (
        [("Strong capability match", area) for area in capability_matches["strong"][:3]]
        + [("Capability match", area) for area in capability_matches["working"][:2]]
        + [("Capability match", area) for area in capability_matches["basic"][:1]]
    )
    for prefix, area in matched_profile_areas:
        label = friendly_capability_label(area)
        entry = f"{prefix}: {label}" if label else ""
        if entry and entry not in highlights:
            highlights.append(entry)

    reviewed_signal_matches = reviewed_signal_match_summary(
        {**record, "reviewed_signal_matches": record.get("reviewed_signal_matches") or reviewed_signal_matches_for_text(role_bundle)}
    )
    for signal in reviewed_signal_matches["matched"][:3]:
        label = friendly_capability_label(signal)
        if label and f"Matched signal: {label}" not in highlights:
            highlights.append(f"Matched signal: {label}")

    if has_government_context(lowered):
        highlights.append("Government context")

    contract_months = extract_contract_months(details_text)
    if contract_months and contract_months >= 12:
        highlights.append("12+ month contract")
    elif compact_whitespace(record.get("work_type") or "").lower() in {"full time", "full-time", "permanent"}:
        highlights.append("Permanent role")

    location_signal = assess_location_preference(record, active_profile)
    if location_signal and int(location_signal.get("value", 0) or 0) > 0:
        highlights.append(str(location_signal.get("label") or "Location preference match"))

    highlights.extend(competitive_fit_highlights(record, active_profile))
    return dedupe_preserve_order(highlights)[:4]


def is_capability_fit_highlight(value: str) -> bool:
    normalized = compact_whitespace(value)
    return normalized.startswith("Capability match:") or normalized.startswith("Strong capability match:")


def capability_fit_highlights(fit_highlights: List[str]) -> List[str]:
    return [
        compact_whitespace(item)
        for item in fit_highlights
        if is_capability_fit_highlight(str(item))
    ]


def build_risk_and_missing_evidence(
    details_text: str,
    title_reason: Optional[str],
    profile: dict,
    competitive_signals: Optional[List[dict]] = None,
) -> Tuple[List[str], List[str]]:
    risks: List[str] = []
    missing: List[str] = []
    lowered = compact_whitespace(details_text).lower()
    capability_matches = find_profile_capability_matches(details_text, profile)

    if title_reason == "TITLE_POTENTIAL_MATCH":
        risks.append("Secondary title match rather than direct target role")

    if capability_matches["must_not"]:
        missing.append(f"{list_to_phrase(capability_matches['must_not'][:2]).capitalize()} explicitly required but not evidenced")

    if capability_matches["limited_depth"]:
        risks.append(
            f"{list_to_phrase(capability_matches['limited_depth'][:2]).capitalize()} appears in the role, but your profile marks it as beginner-level"
        )

    risks.extend(description_watchout_reasons(details_text, profile))

    for signal in (competitive_signals or []):
        if int(signal.get("adjustment", 0)) < 0:
            alignment = compact_whitespace(signal.get("alignment") or "").lower()
            label = compact_whitespace(signal.get("risk_label") or signal.get("name") or "")
            if label:
                if alignment == "weak":
                    missing.append(f"{label} required but weakly evidenced")
                else:
                    risks.append(f"{label} required but only partially evidenced")

    return dedupe_preserve_order(risks)[:4], dedupe_preserve_order(missing)[:4]


def _normalized_aliases(values: List[str]) -> List[str]:
    return dedupe_preserve_order(
        [compact_whitespace(str(value)).lower() for value in values if compact_whitespace(str(value))]
    )


def _profile_auxiliary_text(profile: dict) -> str:
    parts = [
        profile.get("llm_profile_brief"),
        profile.get("star_evidence_text"),
    ]
    return "\n".join(compact_whitespace(part).lower() for part in parts if compact_whitespace(part))


def find_profile_experience_year_in_text(source_text: str, aliases: List[str]) -> Optional[int]:
    text = str(source_text or "")
    if not text.strip():
        return None

    current_year = datetime.now().year
    most_recent_year: Optional[int] = None
    section_year: Optional[int] = None

    for raw_line in text.splitlines():
        line = compact_whitespace(raw_line)
        if not line:
            continue
        updated_year = _line_year_context(line, current_year)
        if updated_year:
            section_year = updated_year
        lowered_line = line.lower()
        if any(text_contains_term(lowered_line, alias) for alias in aliases if str(alias).strip()):
            candidate_year = updated_year or section_year
            if candidate_year and (most_recent_year is None or candidate_year > most_recent_year):
                most_recent_year = candidate_year
    return most_recent_year


def evidence_tier_alignment_score(profile: dict, aliases: List[str]) -> float:
    evidence_tiers = get_evidence_tiers(profile)
    evidence_weights = get_evidence_tier_weights(profile)
    tier_order = (
        "primary_current_evidence",
        "secondary_older_evidence",
        "background_optional_evidence",
    )
    best_score = 0.0

    for tier_name in tier_order:
        tier_text = compact_whitespace(evidence_tiers.get(tier_name) or "").lower()
        if not tier_text:
            continue
        alias_hits = [alias for alias in aliases if text_contains_term(tier_text, alias)]
        if not alias_hits:
            continue
        hit_count = len(alias_hits)
        base_strength = min(0.42 + (0.18 * min(hit_count - 1, 3)), 1.0)
        tier_weight = float(evidence_weights.get(tier_name, 0.0) or 0.0)
        recent_year = find_profile_experience_year_in_text(tier_text, aliases)
        if recent_year:
            years_ago = max(datetime.now().year - int(recent_year), 0)
            if years_ago <= 5:
                recency_multiplier = 1.0
            elif years_ago <= 10:
                recency_multiplier = 0.6
            else:
                recency_multiplier = 0.3
        elif tier_name == "primary_current_evidence":
            recency_multiplier = 1.0
        elif tier_name == "secondary_older_evidence":
            recency_multiplier = 0.6
        else:
            recency_multiplier = 0.35

        best_score = max(best_score, base_strength * tier_weight * recency_multiplier)

    auxiliary_text = _profile_auxiliary_text(profile)
    auxiliary_hits = sum(1 for alias in aliases if text_contains_term(auxiliary_text, alias))
    if auxiliary_hits:
        best_score = max(best_score, min(0.12 + (0.05 * min(auxiliary_hits - 1, 2)), 0.22))

    return min(best_score, 1.0)


def _capability_rule_strength(rule: dict) -> float:
    level = compact_whitespace(rule.get("level") or "").lower()
    level_map = {
        "strong": 1.0,
        "working": 0.72,
        "basic": 0.55,
        "low": 0.22,
    }
    return max(min(level_map.get(level, 0.45), 1.0), 0.0)


def detect_competitive_signals(details_text: str, profile: Optional[dict] = None) -> List[dict]:
    active_profile = profile or load_profile()
    source_text = compact_whitespace(details_text).lower()
    snippets = [snippet.lower() for snippet in split_text_snippets(details_text)]
    if not source_text:
        return []

    detected: List[dict] = []
    for raw_cluster in active_profile.get("dominant_signal_clusters", []):
        if not isinstance(raw_cluster, dict):
            continue
        canonical = compact_whitespace(raw_cluster.get("name") or "").lower()
        aliases = [canonical] if canonical else []
        if not aliases:
            continue

        matched_aliases = [alias for alias in aliases if text_contains_term(source_text, alias)]
        if len(matched_aliases) < 1:
            continue

        snippet_hits = 0
        max_aliases_in_snippet = 0
        for snippet in snippets:
            alias_hits_in_snippet = sum(1 for alias in matched_aliases if text_contains_term(snippet, alias))
            max_aliases_in_snippet = max(max_aliases_in_snippet, alias_hits_in_snippet)
            if alias_hits_in_snippet > 0:
                snippet_hits += 1
        min_snippet_hits = int(raw_cluster.get("min_snippet_hits", 2) or 2)
        dense_snippet_alias_hits = int(raw_cluster.get("dense_snippet_alias_hits", 4) or 4)
        if snippet_hits < min_snippet_hits and max_aliases_in_snippet >= dense_snippet_alias_hits:
            snippet_hits = min_snippet_hits
        if snippet_hits < min_snippet_hits:
            continue

        dominance_level = 1
        if len(matched_aliases) >= 3:
            dominance_level += 1
        if snippet_hits >= 3:
            dominance_level += 1

        detected.append(
            {
                "name": compact_whitespace(raw_cluster.get("name") or "domain specialist track"),
                "fit_label": compact_whitespace(raw_cluster.get("fit_label") or ""),
                "watchout_label": compact_whitespace(raw_cluster.get("watchout_label") or ""),
                "risk_label": compact_whitespace(raw_cluster.get("risk_label") or raw_cluster.get("watchout_label") or ""),
                "aliases": matched_aliases,
                "alias_hits": len(matched_aliases),
                "snippet_hits": snippet_hits,
                "dominance_level": min(dominance_level, 3),
            }
        )

    detected.sort(key=lambda item: (-int(item.get("dominance_level", 0)), -int(item.get("alias_hits", 0)), item.get("name", "")))
    return detected[:3]


def evaluate_competitive_signal_alignment(signal: dict, profile: dict) -> dict:
    aliases = _normalized_aliases([signal.get("name") or ""])
    capability_best = 0.0

    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        canonical = canonical_capability_term(rule)
        rule_aliases = _normalized_aliases([canonical])
        if not canonical:
            continue
        overlap = sum(1 for alias in aliases if alias in rule_aliases or any(alias in rule_alias or rule_alias in alias for rule_alias in rule_aliases))
        if overlap <= 0:
            continue
        rule_strength = _capability_rule_strength(rule)
        capability_best = max(capability_best, min(rule_strength + (0.05 * min(overlap - 1, 2)), 1.05))

    tiered_evidence_score = evidence_tier_alignment_score(profile, aliases)
    recency_multiplier = profile_recency_multiplier(profile, aliases)
    if recency_multiplier == 0.0 and capability_best >= 0.9:
        recency_multiplier = 0.75

    dominant_alignment_score = max(
        capability_best * (recency_multiplier or 1.0),
        tiered_evidence_score,
    )

    dominance_level = int(signal.get("dominance_level", 1) or 1)
    positive_bonus = int(signal.get("positive_bonus", min(1 + dominance_level, 2)) or min(1 + dominance_level, 2))
    partial_penalty = int(signal.get("partial_penalty", 3 + (dominance_level * 2)) or 3 + (dominance_level * 2))
    weak_penalty = int(signal.get("weak_penalty", 4 + (dominance_level * 2)) or 4 + (dominance_level * 2))
    if dominant_alignment_score >= 0.78:
        adjustment = positive_bonus
        alignment = "strong"
    elif dominant_alignment_score >= 0.42:
        adjustment = -partial_penalty
        alignment = "partial"
    else:
        adjustment = -weak_penalty
        alignment = "weak"

    return {
        "name": signal.get("name") or "domain specialist track",
        "fit_label": signal.get("fit_label") or signal.get("name") or "specialist context",
        "watchout_label": signal.get("watchout_label") or f"Role leans toward {signal.get('name') or 'specialist depth'}",
        "risk_label": signal.get("risk_label") or f"Role leans toward {signal.get('name') or 'specialist depth'}",
        "aliases": aliases,
        "dominance_level": dominance_level,
        "alignment": alignment,
        "adjustment": adjustment,
    }


def competitive_signal_assessments(record: dict, profile: Optional[dict] = None) -> List[dict]:
    existing = record.get("competitive_signals")
    if isinstance(existing, list) and existing:
        sanitized: List[dict] = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            sanitized.append(
                {
                    "name": compact_whitespace(item.get("name") or "domain specialist track"),
                    "fit_label": compact_whitespace(item.get("fit_label") or item.get("name") or ""),
                    "watchout_label": compact_whitespace(item.get("watchout_label") or ""),
                    "risk_label": compact_whitespace(item.get("risk_label") or item.get("watchout_label") or ""),
                    "aliases": _normalized_aliases(list(item.get("aliases") or [])),
                    "dominance_level": int(item.get("dominance_level", 1) or 1),
                    "alignment": compact_whitespace(item.get("alignment") or "partial").lower(),
                    "adjustment": int(item.get("adjustment", 0) or 0),
                }
            )
        if sanitized:
            return sanitized

    active_profile = profile or load_profile()
    details_text = build_scoring_source_text(record)
    signals = detect_competitive_signals(details_text, active_profile)
    return [evaluate_competitive_signal_alignment(signal, active_profile) for signal in signals]


def competitive_fit_highlights(record: dict, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = []
    for signal in competitive_signal_assessments(record, profile):
        if int(signal.get("adjustment", 0)) > 0:
            fit_label = compact_whitespace(signal.get("fit_label") or signal.get("name") or "")
            if fit_label:
                highlights.append(f"{fit_label} \u2713")
    return dedupe_preserve_order(highlights)[:2]


def extract_skill_observations(record: dict, details_text: str, profile: Optional[dict] = None) -> List[dict]:
    """Return repeated capability-like signals from a kept role for review insights.

    These observations are intentionally conservative: we only emit positively aligned
    competitive signals from roles we already kept, so Suggested Tuning learns from
    viable roles rather than from noisy broad matches.
    """
    active_profile = profile or load_profile()
    observations: List[dict] = []
    seen: Set[str] = set()
    for signal in competitive_signal_assessments(record, active_profile):
        if int(signal.get("adjustment", 0) or 0) <= 0:
            continue
        skill = compact_whitespace(signal.get("fit_label") or signal.get("name") or "")
        key = skill.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        observations.append(
            {
                "skill": skill,
                "title": record.get("title"),
                "company": record.get("company"),
                "url": record.get("url"),
                "search_location": record.get("search_location"),
            }
        )
    return observations


def hard_block_entries(record: dict, profile: Optional[dict] = None) -> List[dict]:
    existing = [
        compact_whitespace(item)
        for item in (record.get("hard_block_reasons") or [])
        if compact_whitespace(item)
    ]
    if existing:
        return [{"text": item, "category": ""} for item in dedupe_preserve_order(existing)[:3]]

    active_profile = profile or load_profile()
    cluster_by_name = {
        compact_whitespace(str(cluster.get("name") or "")).lower(): cluster
        for cluster in active_profile.get("dominant_signal_clusters", [])
        if isinstance(cluster, dict) and compact_whitespace(str(cluster.get("name") or ""))
    }

    entries: List[dict] = []
    for assessment in competitive_signal_assessments(record, active_profile):
        cluster = cluster_by_name.get(compact_whitespace(str(assessment.get("name") or "")).lower())
        if not isinstance(cluster, dict) or not bool(cluster.get("hard_block_on_mismatch")):
            continue

        allowed_alignments = {
            compact_whitespace(str(value)).lower()
            for value in (cluster.get("hard_block_alignment_levels") or ["partial", "weak"])
            if compact_whitespace(str(value))
        } or {"partial", "weak"}
        alignment = compact_whitespace(str(assessment.get("alignment") or "")).lower()
        if alignment not in allowed_alignments:
            continue

        text = compact_whitespace(
            cluster.get("hard_block_label")
            or assessment.get("watchout_label")
            or assessment.get("risk_label")
            or assessment.get("name")
            or ""
        )
        if not text:
            continue
        category = (
            compact_whitespace(str(cluster.get("name") or ""))
            .lower()
            .replace(" and ", "_")
            .replace(" ", "_")
        )
        entries.append({"text": text, "category": category})

    deduped: List[dict] = []
    seen_keys: Set[str] = set()
    for entry in entries:
        key = compact_whitespace(str(entry.get("category") or entry.get("text") or "")).lower()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(entry)
    return deduped[:3]


def hard_block_reasons(record: dict, profile: Optional[dict] = None) -> List[str]:
    return [entry["text"] for entry in hard_block_entries(record, profile)]


def salary_fit_label(record: dict, profile: Optional[dict] = None) -> str:
    salary_text = str(record.get("salary") or "").strip()
    if not salary_text or salary_text == "N/A":
        return "missing"

    salary_adjustment = salary_fit_adjustment(record, profile)
    if salary_adjustment > 0:
        return "meets"
    if salary_adjustment < 0:
        return "below"
    return "listed"


def score_to_tone_class(score: int, profile: Optional[dict] = None) -> str:
    match_levels = get_match_levels(profile or load_profile())
    match_level = score_to_match_level(score, match_levels)
    if match_levels and match_level == match_levels[0]:
        return "tone-strong"
    if len(match_levels) > 1 and match_level == match_levels[1]:
        return "tone-good"
    if len(match_levels) > 2 and match_level == match_levels[2]:
        return "tone-borderline"
    return "tone-low"


def compact_score_label(label: str) -> str:
    direct_map = {
        "Direct target title match": "Title",
        "Secondary title match": "Title",
        "Description fit is excellent": "Description",
        "Description fit is strong": "Description",
        "Description fit is solid": "Description",
        "Description fit is mixed": "Description",
        "Description fit is weak": "Description",
        "Description fit is a mismatch": "Description",
        "Passed content filters": "Filters",
        "Fit evidence bullets": "Evidence",
        "Salary/rate signal": "Salary",
        "Salary/rate below target": "Salary",
        "Already viewed by you": "Viewed",
        "Description capture incomplete": "Description",
        "On-site role": "Work mode",
    }
    if label in direct_map:
        return direct_map[label]
    if label.startswith("Posted within") or label == "Still relatively recent":
        return "Freshness"
    if "location" in label.lower() or "onsite" in label.lower() or "travel" in label.lower():
        return "Location"
    if label.startswith("Competitive signal"):
        return "Competitive"
    if "contract" in label.lower() or "permanent" in label.lower():
        return "Engagement"
    if "government" in label.lower():
        return "Government"
    if "remote" in label.lower() or "hybrid" in label.lower() or label == "On-site role":
        return "Work mode"
    return label


def format_score_breakdown_for_console(breakdown: List[dict]) -> str:
    return " | ".join(
        f"{compact_score_label(str(item.get('label', '')))} {int(item.get('value', 0)):+d}"
        for item in breakdown
    )


def render_badge(label: str, class_name: str, explanation: str) -> str:
    return (
        f'<span class="badge {safe_html(class_name)}" title="{safe_html(explanation)}" '
        f'aria-label="{safe_html(explanation)}">{safe_html(label)}</span>'
    )


def viewed_badge_html() -> str:
    return render_badge("Viewed", "badge-viewed", "You have already opened this role from the dashboard.")


def normalize_job_key(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    match = re.search(r"/job/(\d+)", value)
    if match:
        return match.group(1)
    id_match = re.fullmatch(r"\d+", value)
    if id_match:
        return value
    return value.split("#", 1)[0]


def get_manual_skip_sets(profile: dict) -> tuple[Set[str], Set[str]]:
    review_controls = profile.get("review_controls", {})
    applied = {
        normalize_job_key(value)
        for value in review_controls.get("applied_job_keys", [])
        if normalize_job_key(value)
    }
    hidden = {
        normalize_job_key(value)
        for value in review_controls.get("hidden_job_keys", [])
        if normalize_job_key(value)
    }
    return applied, hidden


def format_timestamp_label(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y %I:%M %p")
    except Exception:
        return value


def posted_datetime_from_age(posted_age_days: Optional[float], reference_time: Optional[datetime]) -> Optional[datetime]:
    if posted_age_days is None or reference_time is None:
        return None
    try:
        return reference_time - timedelta(days=float(posted_age_days))
    except Exception:
        return None


def format_posted_date_label(posted_text: Optional[str], posted_age_days: Optional[float], reference_time: Optional[datetime]) -> str:
    normalized_posted = normalize_posted_text(posted_text)
    if normalized_posted.lower() == "today" and reference_time is None:
        return "Today"
    posted_at = posted_datetime_from_age(posted_age_days, reference_time)
    if posted_at is None:
        return "Unknown"
    try:
        return posted_at.strftime("%d %b %Y")
    except Exception:
        return "Unknown"


def relative_posted_age_label(posted_at: Optional[datetime], now: Optional[datetime] = None) -> str:
    if posted_at is None:
        return ""
    current = now or datetime.now().astimezone()
    try:
        local_posted = posted_at.astimezone(current.tzinfo) if posted_at.tzinfo and current.tzinfo else posted_at
        days_old = max((current.date() - local_posted.date()).days, 0)
    except Exception:
        return ""
    if days_old == 0:
        return "today"
    if days_old == 1:
        return "yesterday"
    return f"{days_old} days ago"


def posted_reference_time(record: dict) -> Optional[datetime]:
    for key in ("run_started_at", "last_seen_at", "last_kept_at", "first_seen_at"):
        timestamp = parse_timestamp(record.get(key))
        if timestamp:
            return timestamp
    return None


def is_relative_posted_text(value: Optional[str]) -> bool:
    text = normalize_posted_text(value).lower()
    if text in {"today", "yesterday"}:
        return True
    return re.fullmatch(r"\d+\s*[mhdy](?:\s*ago)?", text) is not None


def posted_display_label(record: dict, now: Optional[datetime] = None) -> str:
    posted_text = normalize_posted_text(record.get("posted"))
    posted_age_days = record.get("posted_age_days")
    reference_time = posted_reference_time(record)
    posted_at = posted_datetime_from_age(posted_age_days, reference_time)
    relative_label = relative_posted_age_label(posted_at, now) if posted_at else ""
    posted_date_label = format_posted_date_label(
        posted_text,
        posted_age_days,
        reference_time,
    )

    if posted_date_label != "Unknown" and posted_age_days is not None and is_relative_posted_text(posted_text):
        return f"{posted_date_label} ({relative_label})" if relative_label else posted_date_label
    if posted_age_days is not None and posted_age_days >= 1 and posted_text not in ("N/A", ""):
        if posted_date_label != "Unknown" and posted_date_label != posted_text:
            if relative_label:
                return f"{posted_date_label} ({relative_label})"
            return posted_date_label
    if posted_text in ("N/A", "") and posted_date_label != "Unknown":
        return f"{posted_date_label} ({relative_label})" if relative_label else posted_date_label
    return posted_text


def current_posted_age_days(record: dict, now: Optional[datetime] = None) -> Optional[float]:
    posted_age_days = record.get("posted_age_days")
    if posted_age_days is None:
        return None
    try:
        raw_age_days = float(posted_age_days)
    except Exception:
        return None

    reference_time = posted_reference_time(record)
    if reference_time is None:
        return max(raw_age_days, 0.0)

    posted_at = posted_datetime_from_age(raw_age_days, reference_time)
    if posted_at is None:
        return max(raw_age_days, 0.0)

    current = now or datetime.now().astimezone()
    try:
        age_seconds = (current - posted_at).total_seconds()
    except Exception:
        return max(raw_age_days, 0.0)
    return max(age_seconds / 86400, 0.0)


def get_match_preferences(profile: Optional[dict] = None) -> dict:
    active_profile = profile or load_profile()
    defaults = {
        "home_location": "",
        "secondary_location": "",
        "prefer_government": False,
        "prefer_permanent": False,
        "preferred_contract_months": 12,
        "short_contract_months": 6,
    }
    preferences = active_profile.get("match_preferences", {})
    if isinstance(preferences, dict):
        defaults.update(preferences)
    return defaults


def weighted_points(value: int, weight: float) -> int:
    scaled = float(value) * float(weight)
    if scaled >= 0:
        return int(math.floor(scaled + 0.5))
    return -int(math.floor(abs(scaled) + 0.5))


def build_scoring_source_text(record: dict) -> str:
    source_parts: List[str] = []
    for value in [
        record.get("fit_source_text"),
        record.get("full_description"),
        record.get("title"),
        record.get("company"),
        record.get("role_snapshot"),
        record.get("teaser"),
    ]:
        cleaned = compact_whitespace(value)
        if cleaned and cleaned != "N/A":
            source_parts.append(cleaned)
    return "\n".join(dedupe_preserve_order(source_parts))


def extract_contract_months(details_text: str) -> Optional[int]:
    lowered = compact_whitespace(details_text).lower()
    matches = [int(value) for value in re.findall(r"\b(\d{1,2})\s*[-\u2011\u2013 ]?(?:month|months|mth)\b", lowered)]
    if not matches:
        return None
    return max(matches)


def find_old_experience_year(profile: dict, aliases: List[str]) -> Optional[int]:
    cv_text = compact_whitespace(profile.get("cv_text") or "").lower()
    if not cv_text:
        return None
    for alias in aliases:
        cleaned = str(alias).strip().lower()
        if not cleaned:
            continue
        match = re.search(rf"{re.escape(cleaned)}.{{0,90}}old from (\d{{4}})", cv_text)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _line_year_context(line: str, current_year: int) -> Optional[int]:
    lowered = compact_whitespace(line).lower()
    if not lowered:
        return None

    patterns = [
        r"(20\d{2})\s*[-\u2013]\s*(present|current|ongoing|20\d{2})",
        r"from\s+(20\d{2})\s+to\s+(20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        end_value = match.group(2)
        if end_value in {"present", "current", "ongoing"}:
            return current_year
        try:
            return int(end_value)
        except Exception:
            continue
    return None


def find_profile_experience_year(profile: dict, aliases: List[str]) -> Optional[int]:
    explicit_old_year = find_old_experience_year(profile, aliases)
    if explicit_old_year:
        return explicit_old_year

    evidence_tiers = get_evidence_tiers(profile)
    candidate_years = [
        find_profile_experience_year_in_text(evidence_tiers.get("primary_current_evidence", ""), aliases),
        find_profile_experience_year_in_text(evidence_tiers.get("secondary_older_evidence", ""), aliases),
        find_profile_experience_year_in_text(evidence_tiers.get("background_optional_evidence", ""), aliases),
        find_profile_experience_year_in_text(str(profile.get("cv_text") or ""), aliases),
    ]
    candidate_years = [year for year in candidate_years if year]
    if not candidate_years:
        return None
    return max(candidate_years)


def profile_recency_multiplier(profile: dict, aliases: List[str]) -> float:
    most_recent_year = find_profile_experience_year(profile, aliases)
    if not most_recent_year:
        return 0.0
    years_ago = max(datetime.now().year - int(most_recent_year), 0)
    if years_ago <= 5:
        return 1.0
    if years_ago <= 10:
        return 0.6
    return 0.3


def llm_description_fit_entry(record: dict, profile: Optional[dict] = None) -> dict:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    decision = str(record.get("llm_decision") or "").strip().upper()
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    if not grade:
        fallback_map = {
            "KEEP": "STRONG",
            "MAYBE": "SOLID",
            "REJECT": "MISMATCH",
        }
        grade = fallback_map.get(decision, "SOLID")

    grade_map = {
        "EXCELLENT": ("Description fit is excellent", int(scoring_rules["llm_grade_points"]["EXCELLENT"])),
        "STRONG": ("Description fit is strong", int(scoring_rules["llm_grade_points"]["STRONG"])),
        "SOLID": ("Description fit is solid", int(scoring_rules["llm_grade_points"]["SOLID"])),
        "WEAK": ("Description fit is mixed", int(scoring_rules["llm_grade_points"]["WEAK"])),
        "POOR": ("Description fit is weak", int(scoring_rules["llm_grade_points"]["POOR"])),
        "MISMATCH": ("Description fit is a mismatch", int(scoring_rules["llm_grade_points"]["MISMATCH"])),
    }
    label, value = grade_map.get(grade, grade_map["SOLID"])
    return {"label": label, "value": value}


def capability_match_summary(record: dict, profile: Optional[dict] = None) -> Dict[str, List[str]]:
    active_profile = profile or load_profile()
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    return find_profile_capability_matches(source_text, active_profile)


def capability_scored_matches(source_text: str, profile: dict) -> list[dict]:
    lowered = compact_whitespace(source_text).lower()
    results = []
    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        level = str(rule.get("level") or "").strip().lower()
        if level not in {"strong", "working", "basic"}:
            continue
        canonical = canonical_capability_term(rule)
        if not canonical or not text_contains_term(lowered, canonical):
            continue
        rule_strength = _capability_rule_strength(rule)
        profile_evidence = evidence_tier_alignment_score(profile, [canonical])
        combined = max(rule_strength, profile_evidence)
        results.append({
            "label": friendly_capability_label(str(rule.get("name") or "")),
            "level": level,
            "combined_strength": combined,
        })
    return results


def capability_evidence_score(record: dict, profile: Optional[dict] = None) -> tuple[int, dict]:
    active_profile = profile or load_profile()
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    scored = capability_scored_matches(source_text, active_profile)
    total = sum(
        m["combined_strength"] * {"strong": 4, "working": 3, "basic": 2}.get(str(m.get("level") or ""), 0)
        for m in scored
    )
    score = min(round(total), 20)
    matches = capability_match_summary(record, active_profile)
    return score, matches


def convergence_bonus_entry(record: dict, capability_matches: Optional[dict] = None, profile: Optional[dict] = None) -> Optional[dict]:
    """Award a bonus when multiple strong independent signals simultaneously confirm fit.

    Conditions: title OK, content OK, HIGH description confidence, LLM grade
    EXCELLENT or STRONG, 2+ positive capability matches, no missing evidence.
    Soft risks reduce the bonus from 5 to 3 but do not eliminate it.
    """
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    title_reason = str(record.get("title_reason") or "").strip().upper()
    content_reason = str(record.get("content_reason") or "").strip().upper()
    fit_confidence = full_description_confidence(record)
    missing_evidence = [item for item in (record.get("missing_evidence") or []) if compact_whitespace(item)]
    soft_risks = [item for item in (record.get("soft_risk_reasons") or []) if compact_whitespace(item)]
    active_profile = profile or load_profile()
    matches = capability_matches or capability_match_summary(record, active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    convergence_rules = scoring_rules["convergence"]
    positive_count = (
        len(matches.get("strong", []))
        + len(matches.get("working", []))
        + len(matches.get("basic", []))
    )

    if title_reason != "OK" or content_reason != "OK" or fit_confidence != "HIGH":
        return None
    if missing_evidence or grade not in set(convergence_rules.get("eligible_grades", [])):
        return None
    if positive_count < int(convergence_rules.get("min_positive_matches", 2) or 2):
        return None
    bonus = (
        int(convergence_rules.get("bonus_no_soft_risks", 5) or 5)
        if not soft_risks
        else int(convergence_rules.get("bonus_with_soft_risks", 3) or 3)
    )
    return {"label": "Multiple strong signals align", "value": bonus}


def deterministic_review_outcome(record: dict, fit_highlights: List[str], missing_evidence: List[str], soft_risk_reasons: List[str]) -> Optional[dict]:
    title_reason = str(record.get("title_reason") or "")
    strong_signal_count = len(capability_fit_highlights(fit_highlights))
    high_risks = len(missing_evidence)
    medium_risks = len(soft_risk_reasons)

    if high_risks >= 2 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "MISMATCH"}
    if title_reason == "TITLE_POTENTIAL_MATCH" and high_risks >= 1 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "POOR"}
    if title_reason == "OK" and strong_signal_count >= 4 and high_risks == 0:
        return {"decision": "KEEP", "grade": "STRONG"}
    if title_reason == "OK" and strong_signal_count >= 3 and high_risks == 0 and medium_risks <= 1:
        return {"decision": "KEEP", "grade": "SOLID"}
    return None


def assess_location_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    location_rules = scoring_rules["location"]
    source_text = build_scoring_source_text(record).lower()
    location = compact_whitespace(record.get("location") or "").lower()
    work_mode = compact_whitespace(record.get("work_mode") or "").lower()

    if not location or location == "n/a":
        return None

    def _location_variants(value: str) -> list[str]:
        cleaned = compact_whitespace(value).lower()
        if not cleaned:
            return []
        variants = [cleaned]
        no_prefix = re.sub(r"^all\s+", "", cleaned).strip()
        if no_prefix and no_prefix not in variants:
            variants.append(no_prefix)
        no_region = re.sub(r"\s+[a-z]{2,3}$", "", no_prefix).strip()
        if no_region and no_region not in variants:
            variants.append(no_region)
        return variants

    def _matches_location(preference: str) -> bool:
        return any(variant and variant in location for variant in _location_variants(preference))

    home_location = str(preferences.get("home_location") or "")
    secondary_location = str(preferences.get("secondary_location") or "")

    if home_location and _matches_location(home_location):
        label_target = compact_whitespace(home_location)
        return {"label": f"Location matches primary preference: {label_target}", "value": int(location_rules["primary_match"])}

    if secondary_location and _matches_location(secondary_location):
        label_target = compact_whitespace(secondary_location)
        if work_mode == "remote" or "remote position" in source_text or "fully remote" in source_text:
            return {"label": f"Location matches secondary preference with remote setup: {label_target}", "value": int(location_rules["secondary_remote"])}
        if re.search(r"\b(1 day a week|one day a week|1 day per week|fortnight|2 days a month|two days a month)\b", source_text):
            return {"label": f"Secondary location has limited onsite attendance: {label_target}", "value": int(location_rules["secondary_limited_onsite"])}
        if re.search(r"\b(2 days a week|two days a week|3 days a week|three days a week|2-3 days|two to three days)\b", source_text):
            return {"label": f"Secondary location requires regular onsite attendance: {label_target}", "value": int(location_rules["secondary_regular_onsite"])}

        secondary_terms = [re.escape(value) for value in _location_variants(secondary_location) if value]
        if secondary_terms and re.search(
            rf"\b(must be based in|must reside in|onsite in)\s+(?:{'|'.join(secondary_terms)})\b",
            source_text,
        ):
            return {"label": f"Secondary location requires local onsite attendance: {label_target}", "value": int(location_rules["secondary_local_onsite"])}
        return {"label": f"Location matches secondary preference: {label_target}", "value": int(location_rules["secondary_match"])}

    return None


def assess_contract_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    contract_rules = scoring_rules["contract"]
    source_text = build_scoring_source_text(record)
    work_type = compact_whitespace(record.get("work_type") or "").lower()
    preferred_contract_months = int(preferences.get("preferred_contract_months", 12) or 12)
    short_contract_months = int(preferences.get("short_contract_months", 6) or 6)
    eng_pref = preferences.get("engagement_type", "both")

    normalized_work_type = re.sub(r"[\s_-]+", " ", work_type).strip()
    is_perm = "full time" in normalized_work_type or "permanent" in normalized_work_type
    is_contract = "contract" in normalized_work_type

    if is_perm:
        if eng_pref == "contract":
            return {"label": "Permanent role (preference is Contract)", "value": int(contract_rules["permanent_when_contract_preferred"])}
        return {"label": "Permanent role", "value": int(contract_rules["permanent_match"])}

    if not is_contract:
        return None

    if eng_pref == "permanent":
        return {"label": "Contract role (preference is Permanent)", "value": int(contract_rules["contract_when_permanent_preferred"])}

    contract_months = extract_contract_months(source_text)
    if contract_months is None:
        return None
    if contract_months >= preferred_contract_months:
        if "extension" in source_text.lower():
            return {"label": "12+ month contract with extension potential", "value": int(contract_rules["long_with_extension"])}
        return {"label": "12+ month contract", "value": int(contract_rules["long_contract"])}
    if contract_months >= short_contract_months:
        return {"label": "6-12 month contract", "value": int(contract_rules["medium_contract"])}
    return {"label": "Contract is shorter than preferred", "value": int(contract_rules["short_contract"])}


def assess_government_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    if not preferences.get("prefer_government", True):
        return None

    title = compact_whitespace(record.get("title") or "").lower()
    company = compact_whitespace(record.get("company") or "").lower()
    source_text = build_scoring_source_text(record).lower()
    combined = "\n".join([title, company, source_text])
    if has_government_context(combined) or text_contains_term(combined, "ministerial"):
        return {"label": "Government context", "value": int(scoring_rules["government"]["match_bonus"])}
    return None



def visible_fit_reasons(
    fit_highlights: List[str],
    score_breakdown: List[dict],
    max_items: int = 4,
    include_values: bool = False,
) -> List[str]:
    reasons = dedupe_preserve_order([
        compact_whitespace(item)
        for item in fit_highlights
        if compact_whitespace(item)
    ])
    excluded = {
        "Fit evidence bullets",
        "Passed content filters",
    }

    for item in score_breakdown:
        label = compact_whitespace(item.get("label") or "")
        value = int(item.get("value", 0) or 0)
        if not label or value <= 0 or label in excluded:
            continue
        if label not in reasons:
            reasons.append(label)
        if len(reasons) >= max_items:
            break

    reasons = reasons[:max_items]

    if include_values:
        formatted_reasons = []
        for reason in reasons:
            val = next((int(i.get("value", 0) or 0) for i in score_breakdown if compact_whitespace(i.get("label") or "") == reason), None)
            if val is not None:
                formatted_reasons.append(f"{reason}: {val:+d}")
            else:
                formatted_reasons.append(reason)
        return formatted_reasons

    return reasons


def negative_score_reasons(
    score_breakdown: List[dict],
    max_items: int = 4,
    include_values: bool = True,
) -> List[str]:
    friendly_labels = {
        "Salary/rate below target": "Salary is below target range",
        "Description capture incomplete": DESCRIPTION_CAPTURE_ISSUE,
        "Already viewed by you": "Already opened by you",
        "Contract is shorter than preferred": "Contract length is shorter than preferred",
    }
    reasons = [
        (
            f"{compact_whitespace(item.get('label') or '')}: {int(item.get('value', 0) or 0):+d}"
            if include_values
            else friendly_labels.get(
                compact_whitespace(item.get("label") or ""),
                compact_whitespace(item.get("label") or ""),
            )
        )
        for item in score_breakdown
        if compact_whitespace(item.get("label") or "") and int(item.get("value", 0) or 0) < 0
    ]
    return dedupe_preserve_order(reasons)[:max_items]


def score_gap_reasons(record: dict, score_breakdown: List[dict], max_items: int = 4) -> List[str]:
    labels = [compact_whitespace(item.get("label") or "") for item in score_breakdown]
    evidence_points = next(
        (int(item.get("value", 0) or 0) for item in score_breakdown if item.get("label") == "Fit evidence bullets"),
        0,
    )
    gaps: List[str] = []

    if not any(label.startswith("Posted within") or label == "Still relatively recent" for label in labels):
        gaps.append("No reliable recent-posted signal")

    if not any(label in {"Salary/rate signal", "Salary/rate below target"} for label in labels):
        salary = compact_whitespace(record.get("salary") or "")
        if not salary or salary == "N/A":
            gaps.append("No comparable salary/rate found")

    if evidence_points < 12:
        capability_matches = capability_match_summary(record)
        capability_count = (
            len(capability_matches.get("strong", []))
            + len(capability_matches.get("working", []))
            + len(capability_matches.get("basic", []))
        )
        gaps.append(f"Only {capability_count} capability evidence match{'es' if capability_count != 1 else ''} counted")

    if full_description_confidence(record) == "LOW":
        gaps.append("Scoring confidence is limited because the full description was not captured")

    return dedupe_preserve_order(gaps)[:max_items]


def score_filter_option_label(threshold: int, scoring_profile: Optional[dict] = None) -> str:
    active_profile = scoring_profile or load_profile()
    match_levels = get_match_levels(active_profile)
    label = score_to_match_label(threshold, match_levels)
    highest_threshold = max(int(level.get("minimum_score", 0) or 0) for level in match_levels)
    if threshold >= highest_threshold:
        return f"{label} only"
    return f"{label} or better"


def score_filter_thresholds(
    records: List[dict],
    scoring_profile: Optional[dict] = None,
    include_borderline: Optional[bool] = None,
) -> List[int]:
    active_profile = scoring_profile or load_profile()
    show_borderline = EXPANDED_POOL_MODE if include_borderline is None else bool(include_borderline)
    scores = [fit_score(record, active_profile) for record in records]
    match_levels = get_match_levels(active_profile)
    thresholds = [int(level.get("minimum_score", 0) or 0) for level in match_levels if int(level.get("minimum_score", 0) or 0) > 0]
    lowest_band_threshold = int(match_levels[-1].get("minimum_score", 0) or 0) if match_levels else 0
    if (show_borderline or any(score < (thresholds[-1] if thresholds else 0) for score in scores)) and lowest_band_threshold not in thresholds:
        thresholds.append(lowest_band_threshold)
    return thresholds


def render_score_filter_options(
    records: List[dict],
    scoring_profile: Optional[dict] = None,
    default_min: int = DEFAULT_SCORE_FILTER_MIN,
    include_borderline: Optional[bool] = None,
) -> str:
    active_profile = scoring_profile or load_profile()
    options = ['<option value="all">All match levels</option>']
    for threshold in score_filter_thresholds(records, active_profile, include_borderline=include_borderline):
        selected_attr = " selected" if int(default_min) == threshold else ""
        options.append(
            f'<option value="{threshold}"{selected_attr}>'
            f'{safe_html(score_filter_option_label(threshold, active_profile))}</option>'
        )
    return "".join(options)


def posted_filter_option_label(threshold: int) -> str:
    labels = {
        1: "Posted today",
        3: "Last 3 days",
        7: "Last 7 days",
        14: "Last 14 days",
        30: "Last 30 days",
    }
    return labels.get(threshold, f"Last {threshold} days")


def render_posted_filter_options(records: List[dict], now: Optional[datetime] = None) -> str:
    options = [f'<option value="all">Any posted date ({len(records)})</option>']
    for threshold in [1, 3, 7, 14, 30]:
        count = sum(
            1
            for record in records
            if (age_days := current_posted_age_days(record, now)) is not None
            and age_days <= threshold
        )
        options.append(
            f'<option {"selected" if threshold == 1 else ""} value="{threshold}">'
            f'{safe_html(posted_filter_option_label(threshold))} ({count})</option>'
        )
    return "".join(options)


def humanize_reject_reason(reason: Optional[str]) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "Other filtered-out roles"

    direct_map = {
        "TITLE_NOT_TARGET": "Title outside target role family",
        "NO_DETAILS": "Could not read full job details",
        "DETAILS_CHALLENGE_PAGE": "Blocked by SEEK challenge page",
        "DETAILS_BLOCKED_PAGE": "Blocked from reading job details",
        "DETAILS_NAVIGATION_ERROR": "Could not open the job ad page",
        "DET_REJECT": "Deterministic fit gate rejected",
        "LLM_REJECT": "AI fit review rejected",
        "DUPLICATE_URL": "Duplicate listing removed",
        "ALREADY_APPLIED": "Already marked as applied",
        "MANUALLY_HIDDEN": "Already hidden by you",
        "UNKNOWN": "Other filtered-out roles",
    }
    if raw in direct_map:
        return direct_map[raw]

    prefix, _, detail = raw.partition(":")
    cleaned_detail = detail.replace("_", " ").strip()
    if prefix == "TITLE_BAD_KEYWORD" and cleaned_detail:
        return f"Excluded title keyword: {cleaned_detail}"
    if prefix == "TITLE_BAD_ROLE" and cleaned_detail:
        return f"Excluded role family: {cleaned_detail}"
    if prefix == "POSTED_TOO_OLD" and cleaned_detail:
        return f"Older than the search window ({cleaned_detail} days)"
    if prefix == "DESC_LOCATION" and cleaned_detail:
        return f"Location mismatch: {cleaned_detail}"
    if prefix == "DESC_CAPABILITY_LOW" and cleaned_detail:
        return f"Low-fit specialist area: {cleaned_detail}"
    if prefix == "DESC_HARD_BLOCK" and cleaned_detail:
        return f"Hard blocker mismatch: {cleaned_detail}"
    if prefix == "CARD_EXCEPTION" and cleaned_detail:
        return f"Collection error: {cleaned_detail}"
    if prefix == "DESC_BAD_PHRASE" and cleaned_detail:
        return f"Excluded description phrase: {cleaned_detail}"
    if prefix == "DESC_BAD_REGEX" and cleaned_detail:
        return f"Excluded description pattern: {cleaned_detail}"
    if prefix == "LEARNED_REJECT" and cleaned_detail:
        return f"Learned blocker: {cleaned_detail.split(':')[-1].strip()}"
    if prefix == "TITLE_POTENTIAL_MATCH":
        return "Secondary title match"
    if prefix == "CARD_SPECIALIST" and cleaned_detail:
        return f"Rejected early from card metadata: {cleaned_detail}"

    fallback = raw.replace("_", " ").lower()
    return fallback[:1].upper() + fallback[1:]


def competitive_signal_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    entries: List[dict] = []
    for signal in competitive_signal_assessments(record, profile):
        adjustment = int(signal.get("adjustment", 0) or 0)
        label_base = compact_whitespace(signal.get("fit_label") or signal.get("name") or "competitive signal")
        if not label_base or adjustment == 0:
            continue
        if adjustment > 0:
            label = f"Competitive signal aligns: {label_base}"
        else:
            label = f"Competitive signal leans elsewhere: {label_base}"
        entries.append({"label": label, "value": adjustment})
    entries.sort(key=lambda item: (abs(int(item.get("value", 0))), item.get("label", "")), reverse=True)
    return entries[:2]


def salary_fit_adjustment(record: dict, profile: Optional[dict] = None) -> int:
    salary_text = str(record.get("salary") or "").strip()
    if not salary_text or salary_text == "N/A":
        return 0
    if _salary_includes_super_or_package(salary_text):
        return 0

    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    salary_rules = scoring_rules["salary"]
    salary_preferences = active_profile.get("salary_preferences", {})
    minimum_salary_yearly = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    minimum_daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    parsed_value = _salary_max_value(salary_text)
    lowered = salary_text.lower()
    is_daily = bool(re.search(r"\b(per\s+day|daily\s+rate|day\s+rate|p/d|pd)\b|/day", lowered))
    is_non_comparable_period = bool(
        re.search(
            r"\b(per\s+hour|hourly|p/h|ph|per\s+week|weekly|per\s+month|monthly)\b"
            r"|/(?:hr|hour|wk|week|mo|month)",
            lowered,
        )
    )

    if is_daily:
        if minimum_daily_rate <= 0 or parsed_value <= 0:
            return 0
        if parsed_value >= minimum_daily_rate:
            return int(salary_rules["meeting_target"])
        ratio = parsed_value / minimum_daily_rate
        if ratio >= float(salary_rules["below_target_near_min_ratio"]):
            return int(salary_rules["below_target_near_adjustment"])
        if ratio >= float(salary_rules["below_target_mid_min_ratio"]):
            return int(salary_rules["below_target_mid_adjustment"])
        return int(salary_rules["below_target_far_adjustment"])

    if is_non_comparable_period:
        return 0

    if minimum_salary_yearly <= 0 or parsed_value <= 0:
        return 0
    if parsed_value >= minimum_salary_yearly:
        return int(salary_rules["meeting_target"])
    ratio = parsed_value / minimum_salary_yearly
    if ratio >= float(salary_rules["below_target_near_min_ratio"]):
        return int(salary_rules["below_target_near_adjustment"])
    if ratio >= float(salary_rules["below_target_mid_min_ratio"]):
        return int(salary_rules["below_target_mid_adjustment"])
    return int(salary_rules["below_target_far_adjustment"])


def fit_score_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    breakdown: List[dict] = []
    title_reason = str(record.get("title_reason") or "")
    content_reason = str(record.get("content_reason") or "")
    posted_age_days = current_posted_age_days(record)
    work_mode = str(record.get("work_mode") or "").lower()
    fit_highlights = [item for item in record.get("fit_highlights", []) if str(item).strip()]
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    evidence_score, capability_matches = capability_evidence_score(record, active_profile)
    reviewed_signal_matches = reviewed_signal_match_summary(record, active_profile)

    if hard_block_labels:
        return [{"label": f"Hard blocker requirement mismatch: {hard_block_labels[0]}", "value": int(scoring_rules["fit_breakdown"]["hard_block_penalty"])}]

    if title_reason == "OK":
        breakdown.append({"label": "Direct target title match", "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_direct"]), weights["fit"])})
    elif title_reason == "TITLE_POTENTIAL_MATCH":
        breakdown.append({"label": "Secondary title match", "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_secondary"]), weights["fit"])})

    llm_entry = llm_description_fit_entry(record, active_profile)
    breakdown.append({"label": llm_entry["label"], "value": weighted_points(int(llm_entry["value"]), weights["fit"])})

    if content_reason == "OK":
        breakdown.append({"label": "Passed content filters", "value": weighted_points(int(scoring_rules["fit_breakdown"]["content_ok"]), weights["fit"])})

    if full_description_confidence(record) == "LOW":
        breakdown.append({"label": "Description capture incomplete", "value": weighted_points(int(scoring_rules["fit_breakdown"]["description_capture_incomplete"]), weights["fit"])})

    if evidence_score:
        breakdown.append({"label": "Fit evidence bullets", "value": weighted_points(evidence_score, weights["fit"])})

    convergence_entry = convergence_bonus_entry(record, capability_matches, active_profile)
    if convergence_entry:
        breakdown.append({
            "label": convergence_entry["label"],
            "value": weighted_points(int(convergence_entry["value"]), weights["fit"]),
        })

    for item in competitive_signal_breakdown(record, active_profile):
        breakdown.append({"label": item["label"], "value": weighted_points(int(item["value"]), weights["fit"])})

    if posted_age_days is not None:
        if posted_age_days <= (1 / 24):
            breakdown.append({"label": "Posted within the last hour", "value": weighted_points(int(scoring_rules["freshness"]["last_hour"]), weights["freshness"])})
        elif posted_age_days <= 1:
            breakdown.append({"label": "Posted within the last day", "value": weighted_points(int(scoring_rules["freshness"]["last_day"]), weights["freshness"])})
        elif posted_age_days <= 3:
            breakdown.append({"label": "Posted within the last 3 days", "value": weighted_points(int(scoring_rules["freshness"]["last_3_days"]), weights["freshness"])})
        elif posted_age_days <= 7:
            breakdown.append({"label": "Posted within the last week", "value": weighted_points(int(scoring_rules["freshness"]["last_week"]), weights["freshness"])})
        elif posted_age_days <= 15:
            breakdown.append({"label": "Still relatively recent", "value": weighted_points(int(scoring_rules["freshness"]["last_15_days"]), weights["freshness"])})

    location_item = assess_location_preference(record, active_profile)
    if location_item:
        breakdown.append({
            "label": location_item["label"],
            "value": weighted_points(int(location_item["value"]), weights["location"]),
        })

    contract_item = assess_contract_preference(record, active_profile)
    if contract_item:
        breakdown.append({
            "label": contract_item["label"],
            "value": weighted_points(int(contract_item["value"]), weights["contract"]),
        })

    government_item = assess_government_preference(record, active_profile)
    if government_item:
        breakdown.append({
            "label": government_item["label"],
            "value": weighted_points(int(government_item["value"]), weights["government"]),
        })

    if work_mode == "hybrid":
        breakdown.append({"label": "Hybrid work available", "value": weighted_points(int(scoring_rules["work_mode"]["hybrid"]), weights["work_mode"])})
    elif work_mode == "remote":
        breakdown.append({"label": "Remote work available", "value": weighted_points(int(scoring_rules["work_mode"]["remote"]), weights["work_mode"])})
    elif work_mode in {"on-site", "onsite", "on site"}:
        breakdown.append({"label": "On-site role", "value": weighted_points(int(scoring_rules["work_mode"]["on_site"]), weights["work_mode"])})

    salary_score = weighted_points(salary_fit_adjustment(record, active_profile), weights["salary"])
    if salary_score > 0:
        breakdown.append({"label": "Salary/rate signal", "value": salary_score})
    elif salary_score < 0:
        breakdown.append({"label": "Salary/rate below target", "value": salary_score})

    if viewed_by_user(record) and not record.get("applied"):
        breakdown.append({"label": "Already viewed by you", "value": int(scoring_rules["fit_breakdown"]["viewed_by_user"])})

    return breakdown


def fit_score(record: dict, profile: Optional[dict] = None) -> int:
    score = sum(item["value"] for item in fit_score_breakdown(record, profile))
    return max(min(score, 100), 0)


def is_dashboard_eligible(record: dict, profile: Optional[dict] = None) -> bool:
    ok_title, _ = passes_title_filters(str(record.get("title") or ""))
    if not ok_title:
        return False
    return fit_score(record, profile) >= DASHBOARD_MIN_SCORE


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def days_since(value: Optional[str], reference: datetime) -> Optional[int]:
    timestamp = parse_timestamp(value)
    if not timestamp:
        return None
    try:
        return max((reference - timestamp).days, 0)
    except Exception:
        return None


def build_keep_snapshot(record: dict) -> dict:
    snapshot = {}
    for field in KEEP_SNAPSHOT_FIELDS:
        if field in record:
            snapshot[field] = record.get(field)
    return snapshot


def can_reuse_kept_job(history_entry: dict, record: dict, profile: Optional[dict] = None) -> bool:
    if not isinstance(history_entry, dict):
        return False
    if int(history_entry.get("times_kept", 0) or 0) <= 0:
        return False
    snapshot = history_entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        return False
    if not record.get("job_key"):
        return False
    previous_url = str(snapshot.get("url") or history_entry.get("url") or "").strip()
    current_url = str(record.get("url") or "").strip()
    if previous_url and current_url and previous_url != current_url:
        return False
    if hard_block_reasons(snapshot if isinstance(snapshot, dict) else {}, profile):
        return False
    return True


def apply_kept_job_reuse(record: dict, history_entry: dict) -> dict:
    snapshot = history_entry.get("last_kept_snapshot") if isinstance(history_entry, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    if record.get("posted") in {None, "", "N/A"}:
        record["posted"] = repair_text(snapshot.get("posted") or "N/A")
    if record.get("posted_age_days") is None and snapshot.get("posted_age_days") is not None:
        record["posted_age_days"] = snapshot.get("posted_age_days")
    if record.get("salary") in {None, "", "N/A"}:
        record["salary"] = repair_text(snapshot.get("salary") or "N/A")
    if record.get("teaser") in {None, "", "N/A"}:
        record["teaser"] = repair_text(snapshot.get("teaser") or "N/A")
    if record.get("location") in {None, "", "N/A"}:
        record["location"] = repair_text(snapshot.get("location") or "N/A")
    if record.get("work_mode") in {None, "", "N/A"}:
        record["work_mode"] = repair_text(snapshot.get("work_mode") or "N/A")
    if record.get("work_type") in {None, "", "N/A"}:
        record["work_type"] = repair_text(snapshot.get("work_type") or "N/A")
    if record.get("role_snapshot") in {None, "", "N/A"}:
        record["role_snapshot"] = repair_text(snapshot.get("role_snapshot") or "N/A")
    if not compact_whitespace(record.get("fit_source_text") or ""):
        record["fit_source_text"] = repair_text(snapshot.get("fit_source_text") or "")
    if not compact_whitespace(record.get("full_description") or ""):
        record["full_description"] = repair_text(snapshot.get("full_description") or "")
    if not record.get("fit_confidence"):
        record["fit_confidence"] = snapshot.get("fit_confidence") or ""
    if not record.get("fit_highlights"):
        record["fit_highlights"] = snapshot.get("fit_highlights") or []
    if not record.get("soft_risk_reasons"):
        record["soft_risk_reasons"] = snapshot.get("soft_risk_reasons") or []
    if not record.get("missing_evidence"):
        record["missing_evidence"] = snapshot.get("missing_evidence") or []
    if not record.get("competitive_signals"):
        record["competitive_signals"] = snapshot.get("competitive_signals") or []
    if not record.get("hard_block_reasons"):
        record["hard_block_reasons"] = snapshot.get("hard_block_reasons") or []
    if not compact_whitespace(record.get("details_status") or ""):
        record["details_status"] = snapshot.get("details_status") or ""
    if not record.get("description_source"):
        record["description_source"] = snapshot.get("description_source") or ""

    record["content_reason"] = snapshot.get("content_reason")
    record["llm_decision"] = snapshot.get("llm_decision")
    record["llm_fit_grade"] = snapshot.get("llm_fit_grade")
    record["decision"] = "KEEP"
    record["details_length"] = 0
    record["reused_history"] = True
    return record


def viewed_by_user(record: dict) -> bool:
    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        return False
    return int(record.get("times_viewed", 0) or 0) > 0


def get_trusted_full_description(record: dict) -> str:
    """Return the trusted full description text, or empty string if not available.

    Prefers the canonical ``full_description`` field. Falls back to
    ``fit_source_text`` when the source is trusted. Older saved LinkedIn
    snapshots did not always persist ``description_source``; if the detail
    status was OK and the fallback text is long enough, treat that as trusted
    legacy detail text so dashboard rebuilds do not lose evidence.
    """
    full = compact_whitespace(record.get("full_description") or "")
    if full:
        return full
    source = str(record.get("description_source") or "").strip().lower()
    fallback_text = compact_whitespace(record.get("fit_source_text") or "")
    if len(fallback_text) < MIN_TRUSTED_DESCRIPTION_LENGTH:
        return ""
    if source in TRUSTED_DESCRIPTION_SOURCES:
        return fallback_text
    details_status = str(record.get("details_status") or "").strip().lower()
    if details_status == "ok" and not source:
        return fallback_text
    return ""


def full_description_confidence(record: dict) -> str:
    """Return 'HIGH' if a trusted full description is available, else 'LOW'.

    Recomputes HIGH from trusted text first so legacy records with recovered
    detail text are not stuck with an old LOW confidence marker.
    """
    if get_trusted_full_description(record):
        return "HIGH"
    stored = str(record.get("fit_confidence") or "").strip().upper()
    if stored in {"HIGH", "LOW"}:
        return stored
    return "LOW"


def is_description_trusted(record: dict) -> bool:
    """Return True when a trusted full description is available for this record."""
    return full_description_confidence(record) == "HIGH"


def history_cluster_key_from_parts(source: Optional[str], company: Optional[str], title: Optional[str]) -> str:
    source_key = compact_whitespace(source or "").lower()
    company_key = re.sub(r"[^a-z0-9]+", " ", compact_whitespace(company or "").lower()).strip()
    title_key = re.sub(r"[^a-z0-9]+", " ", compact_whitespace(title or "").lower()).strip()
    if not source_key or not company_key or not title_key:
        return ""
    return f"{source_key}|{company_key}|{title_key}"


def history_cluster_key(record: dict) -> str:
    source = str(record.get("source") or "").strip().lower()
    if not source:
        job_key = str(record.get("job_key") or "")
        source = "linkedin" if job_key.startswith("linkedin:") else "seek"
    return history_cluster_key_from_parts(source, record.get("company"), record.get("title"))


def build_history_sighting(record: dict, run_iso: str) -> dict:
    details_text = get_trusted_full_description(record) or compact_whitespace(record.get("teaser") or "")
    posting_channel = infer_posting_channel(record, details_text).get("kind") or "unknown"
    return {
        "seen_at": run_iso,
        "url": str(record.get("url") or "").strip(),
        "posted": normalize_posted_text(record.get("posted")),
        "posted_age_days": record.get("posted_age_days"),
        "company": str(record.get("company") or "").strip(),
        "title": str(record.get("title") or "").strip(),
        "source": str(record.get("source") or "").strip().lower(),
        "posting_channel": posting_channel,
    }


def build_history_cluster_index(history: Dict[str, dict]) -> Dict[str, dict]:
    clusters: Dict[str, dict] = {}
    for job_key, entry in history.items():
        if not isinstance(entry, dict):
            continue
        snapshot = entry.get("last_kept_snapshot") if isinstance(entry.get("last_kept_snapshot"), dict) else {}
        source = snapshot.get("source") or ("linkedin" if str(job_key).startswith("linkedin:") else "seek")
        company = snapshot.get("company") or entry.get("company")
        title = snapshot.get("title") or entry.get("title")
        cluster_key = history_cluster_key_from_parts(source, company, title)
        if not cluster_key:
            continue
        stats = clusters.setdefault(
            cluster_key,
            {
                "job_keys": set(),
                "times_seen": 0,
                "first_seen_at": None,
                "last_seen_at": None,
            },
        )
        stats["job_keys"].add(str(job_key))
        stats["times_seen"] += int(entry.get("times_seen", 0) or 0)
        first_seen = parse_timestamp(entry.get("first_seen_at"))
        last_seen = parse_timestamp(entry.get("last_seen_at"))
        if first_seen and (stats["first_seen_at"] is None or first_seen < stats["first_seen_at"]):
            stats["first_seen_at"] = first_seen
        if last_seen and (stats["last_seen_at"] is None or last_seen > stats["last_seen_at"]):
            stats["last_seen_at"] = last_seen
    return clusters


def assess_history_warning_signals(record: dict, history_clusters: Optional[Dict[str, dict]] = None) -> List[str]:
    warnings: List[str] = []
    times_seen = int(record.get("times_seen", 0) or 0)
    first_seen = parse_timestamp(record.get("first_seen_at"))
    last_seen = parse_timestamp(record.get("last_seen_at"))
    if first_seen and last_seen:
        span_days = max((last_seen.date() - first_seen.date()).days, 0)
        if times_seen >= REPEATED_LISTING_MIN_TIMES_SEEN and span_days >= REPEATED_LISTING_MIN_SPAN_DAYS:
            warnings.append(
                f"Potential red flag: this same listing has been seen {times_seen} times over {span_days} days"
            )

    cluster_key = history_cluster_key(record)
    cluster_stats = history_clusters.get(cluster_key) if history_clusters and cluster_key else None
    if cluster_stats:
        listing_count = len(cluster_stats.get("job_keys", set()))
        cluster_first_seen = cluster_stats.get("first_seen_at")
        cluster_last_seen = cluster_stats.get("last_seen_at")
        if cluster_first_seen and cluster_last_seen:
            cluster_span_days = max((cluster_last_seen.date() - cluster_first_seen.date()).days, 0)
            if listing_count >= MULTI_LISTING_RED_FLAG_MIN_LISTINGS and cluster_span_days >= MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS:
                warnings.append(
                    f"Potential red flag: the same title from the same poster has appeared across {listing_count} separate listings over {cluster_span_days} days"
                )
    return dedupe_preserve_order(warnings)


def update_job_history(history: Dict[str, dict], record: dict, run_iso: str) -> None:
    job_key = record.get("job_key")
    if not job_key:
        record["seen_before"] = False
        record["times_kept"] = 0
        record["first_kept_at"] = None
        return

    entry = history.get(job_key, {})
    prior_kept_count = int(entry.get("times_kept", 0) or 0)

    entry["job_key"] = job_key
    entry["title"] = record.get("title")
    entry["company"] = record.get("company")
    entry["url"] = record.get("url")
    entry["last_seen_at"] = run_iso
    entry["times_seen"] = int(entry.get("times_seen", 0) or 0) + 1
    if not entry.get("first_seen_at"):
        entry["first_seen_at"] = run_iso

    record["seen_before"] = prior_kept_count > 0
    record["times_seen"] = entry["times_seen"]
    record["times_kept"] = prior_kept_count
    record["times_viewed"] = int(entry.get("times_viewed", 0) or 0)
    record["first_kept_at"] = entry.get("first_kept_at")
    record["first_seen_at"] = entry.get("first_seen_at")
    record["last_seen_at"] = entry.get("last_seen_at")
    record["first_viewed_at"] = entry.get("first_viewed_at")
    record["last_viewed_at"] = entry.get("last_viewed_at")
    sightings = entry.get("sightings") if isinstance(entry.get("sightings"), list) else []
    current_sighting = build_history_sighting(record, run_iso)
    if not sightings or sightings[-1] != current_sighting:
        sightings = [*sightings, current_sighting][-MAX_HISTORY_SIGHTINGS:]
    entry["sightings"] = sightings
    record["history_sightings"] = sightings

    if record.get("decision") == "KEEP":
        if not entry.get("first_kept_at"):
            entry["first_kept_at"] = run_iso
        entry["last_kept_at"] = run_iso
        entry["times_kept"] = prior_kept_count + 1
        entry["last_kept_snapshot"] = build_keep_snapshot(record)
        record["times_kept"] = entry["times_kept"]
        record["first_kept_at"] = entry["first_kept_at"]
        record["last_kept_at"] = entry["last_kept_at"]

    history[job_key] = entry


def finalize_record(history: Dict[str, dict], audit_rows: List[dict], record: dict, run_iso: str) -> None:
    update_job_history(history, record, run_iso)
    audit_rows.append(record)


def build_history_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> Optional[dict]:
    return dashboard_data.build_history_dashboard_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
        archive_stale_after_days=ARCHIVE_STALE_AFTER_DAYS,
    )


def build_archive_records(
    history: Dict[str, dict],
    current_run_keys: Set[str],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_started_at: datetime,
) -> List[dict]:
    return dashboard_data.build_archive_records(
        history,
        current_run_keys,
        applied_job_keys,
        hidden_job_keys,
        run_started_at,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_history_dashboard_record_fn=build_history_dashboard_record,
    )


def build_hidden_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    return dashboard_data.build_hidden_dashboard_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
    )


def build_hidden_records(
    hidden_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    return dashboard_data.build_hidden_records(
        hidden_job_keys,
        history,
        run_started_at,
        parse_timestamp_fn=parse_timestamp,
        days_since_fn=days_since,
        hidden_review_days=HIDDEN_REVIEW_DAYS,
        build_hidden_dashboard_record_fn=build_hidden_dashboard_record,
    )


def build_applied_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    return dashboard_data.build_applied_dashboard_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
    )


def build_applied_records(
    applied_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    return dashboard_data.build_applied_records(
        applied_job_keys,
        history,
        run_started_at,
        parse_timestamp_fn=parse_timestamp,
        build_applied_dashboard_record_fn=build_applied_dashboard_record,
    )


def build_dashboard_record_sets(
    kept_records: List[dict],
    job_history: Dict[str, dict],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    reference_time: datetime,
    scoring_profile: Optional[dict] = None,
) -> Dict[str, List[dict]]:
    profile = scoring_profile or load_profile()
    return dashboard_data.build_dashboard_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        profile=profile,
        is_dashboard_eligible_fn=is_dashboard_eligible,
        fit_score_fn=fit_score,
        viewed_by_user_fn=viewed_by_user,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_archive_records_fn=build_archive_records,
        build_applied_records_fn=build_applied_records,
        build_hidden_records_fn=build_hidden_records,
    )


def render_job_card(
    record: dict,
    scoring_profile: Optional[dict] = None,
    applied_pool: Optional[List[dict]] = None,
    history_clusters: Optional[Dict[str, dict]] = None,
) -> str:
    active_profile = scoring_profile or load_profile()
    display_record = dict(record)
    
    loc = str(display_record.get("location") or "").strip()
    if loc.endswith(", Australia"):
        display_record["location"] = loc[:-11].strip()
        
    title = safe_html(record.get("title", "Untitled"))
    company = safe_html(record.get("company", "N/A"))
    url = safe_html(record.get("url", "#"))
    job_key = safe_html(str(record.get("job_key") or ""))
    title_reason = record.get("title_reason")
    applied_record = bool(record.get("applied"))
    archived = bool(record.get("archived"))
    hidden_record = bool(record.get("hidden"))
    is_stale = bool(record.get("is_stale"))
    seen_by_you = viewed_by_user(record)
    stored_snapshot = compact_whitespace(record.get("role_snapshot") or record.get("teaser") or "N/A")
    if stored_snapshot in {"", "N/A"}:
        stored_snapshot = synthesize_role_snapshot(record)
    fit_confidence_level = full_description_confidence(record)
    trusted_desc = get_trusted_full_description(record)

    if fit_confidence_level == "HIGH" and trusted_desc:
        display_record["fit_source_text"] = trusted_desc
        display_record["fit_confidence"] = "HIGH"
        detail_work_mode = extract_work_mode(trusted_desc)
        if detail_work_mode != "N/A":
            display_record["work_mode"] = detail_work_mode
        role_summary = build_role_summary(record, trusted_desc, active_profile)
        display_record["competitive_signals"] = competitive_signal_assessments(record, active_profile)
        fit_highlights = build_fit_highlights(record, trusted_desc, active_profile)
        soft_risk_reasons, missing_evidence = build_risk_and_missing_evidence(
            trusted_desc,
            title_reason,
            active_profile,
            competitive_signals=display_record.get("competitive_signals") if isinstance(display_record.get("competitive_signals"), list) else None,
        )
        blocking_reasons = hard_block_reasons(display_record, active_profile)
        if blocking_reasons:
            missing_evidence = dedupe_preserve_order([*blocking_reasons, *missing_evidence])
    else:
        role_summary = stored_snapshot
        display_record["fit_confidence"] = "LOW"
        display_record["competitive_signals"] = []
        fit_highlights = []
        soft_risk_reasons = []
        missing_evidence = [DESCRIPTION_CAPTURE_ISSUE]
        blocking_reasons = []

    similar_applied_record = None
    is_possible_repost = False
    if not applied_record and applied_pool:
        similar_applied_record = find_similar_job(record, applied_pool)
        is_possible_repost = similar_applied_record is not None

    display_record["hard_block_reasons"] = blocking_reasons
    display_record["role_snapshot"] = role_summary
    display_record["fit_highlights"] = fit_highlights
    display_record["soft_risk_reasons"] = soft_risk_reasons
    display_record["missing_evidence"] = missing_evidence
    fit_points = fit_score(display_record, scoring_profile)
    match_levels = get_match_levels(scoring_profile or load_profile())
    fit_label = score_to_match_label(fit_points, match_levels)
    fit_tone_class = score_to_tone_class(fit_points, scoring_profile)
    score_breakdown = fit_score_breakdown(display_record, scoring_profile)
    visible_reasons = visible_fit_reasons(fit_highlights, score_breakdown, include_values=SHOW_SCORING_DEBUG)
    description_issue = fit_confidence_level == "LOW"
    work_mode = str(display_record.get("work_mode") or "N/A")
    posted_age_days = current_posted_age_days(record)
    salary_value = salary_sort_value(str(display_record.get("salary") or ""))
    salary_fit_state = salary_fit_label(display_record, scoring_profile)
    record_kind = "applied" if applied_record else ("hidden" if hidden_record else ("saved" if archived else "current"))
    company_attr = safe_html(compact_whitespace(str(record.get("company") or "")))
    teaser_attr = safe_html(compact_whitespace(str(record.get("teaser") or "")))
    sector_signal = infer_role_sector(display_record, trusted_desc if trusted_desc else stored_snapshot)
    channel_signal = infer_posting_channel(display_record, trusted_desc if trusted_desc else stored_snapshot)
    _block_phrases_list = suggest_title_block_phrases(str(record.get("title") or ""))
    block_phrase = safe_html(_block_phrases_list[0]) if _block_phrases_list else ""
    block_phrases_json = safe_html(json.dumps(_block_phrases_list))
    similar_applied_title = safe_html(str((similar_applied_record or {}).get("title") or ""))
    similar_applied_company = safe_html(str((similar_applied_record or {}).get("company") or ""))
    similar_applied_source = str((similar_applied_record or {}).get("source") or "").lower().strip()
    similar_applied_source_label = safe_html(
        {"linkedin": "LinkedIn", "seek": "SEEK"}.get(similar_applied_source, similar_applied_source.upper())
        if similar_applied_source
        else ""
    )
    similar_applied_job_key = safe_html(str((similar_applied_record or {}).get("job_key") or ""))
    button_data_attrs = (
        f'data-job-key="{job_key}" '
        f'data-job-url="{url}" '
        f'data-job-title="{title}" '
        f'data-job-company="{company_attr}" '
        f'data-job-teaser="{teaser_attr}" '
        f'data-role-sector="{safe_html(sector_signal.get("kind") or "unknown")}" '
        f'data-posting-channel="{safe_html(channel_signal.get("kind") or "unknown")}" '
        f'data-similar-applied-warning="{"1" if is_possible_repost else "0"}" '
        f'data-similar-applied-job-key="{similar_applied_job_key}" '
        f'data-similar-applied-title="{similar_applied_title}" '
        f'data-similar-applied-company="{similar_applied_company}" '
        f'data-similar-applied-source="{similar_applied_source_label}"'
    )

    source = str(record.get("source") or "unknown").lower().strip()
    source_label = {"linkedin": "LinkedIn", "seek": "SEEK"}.get(source, source.upper())

    badges = []
    if applied_record:
        badges.append(render_badge("Applied", "badge-viewed", "You already applied for this role."))
    elif hidden_record:
        badges.append(render_badge("Hidden", "badge-hidden", "You hid this role for now."))
    elif is_possible_repost:
        badges.append(render_badge("Possible Repost", "badge-warning", "This role looks very similar to one you have already applied to."))
    elif archived:
        badges.append(render_badge(ARCHIVE_LABEL, "badge-archive", ARCHIVE_BADGE_TOOLTIP))
    if not applied_record and not seen_by_you:
        badges.append(render_badge("New To You", "badge-new", "You have not opened this role from the dashboard yet."))
    if is_stale:
        badges.append(render_badge("15+ Days Old", "badge-stale", "This role is older, but still saved for reference."))
    elif seen_by_you:
        badges.append(viewed_badge_html())
    if description_issue:
        badges.append(render_badge("Description Issue", "badge-warning", "The full job description was not captured clearly, so this match needs manual checking."))
    badges.append(render_badge(source_label, f"badge-source-{source}", f"Sourced from {source_label}."))
    if sector_signal.get("kind") == "government":
        badges.append(render_badge("Government", "badge-sector-government", "Government/public-sector context detected from the captured job text."))
    if channel_signal.get("kind") == "recruiter":
        confidence_text = channel_signal.get("confidence") or "inferred"
        badges.append(render_badge("Recruiter", "badge-channel-recruiter", f"Recruiter/intermediary posting inferred with {confidence_text} confidence from the captured job text."))
    elif channel_signal.get("kind") == "direct_employer":
        confidence_text = channel_signal.get("confidence") or "inferred"
        badges.append(render_badge("Direct Employer", "badge-new", f"Direct employer posting inferred with {confidence_text} confidence from the captured job text."))
    history_warning_signals = assess_history_warning_signals(record, history_clusters)
    if history_warning_signals:
        badges.append(render_badge("Potential Red Flag", "badge-warning", history_warning_signals[0]))

    score_percent = max(min(int(fit_points), 100), 0)
    score_html = (
        f'<div class="match-tile {fit_tone_class}" style="--match-score: {score_percent}%;">'
        + (
            f'<span class="match-tile-number">{fit_points}</span>'
            if SHOW_SCORES_MODE
            else ""
        )
        + f'<span class="match-tile-label">{safe_html(fit_label)}</span>'
        + '<span class="match-tile-bar" aria-hidden="true"><span class="match-tile-bar-fill"></span></span>'
        + "</div>"
    )

    posted_display = posted_display_label(record)

    meta_items = []
    for label, value in [
        ("Posted", posted_display),
        ("Location", display_record.get("location")),
        ("Work mode", display_record.get("work_mode")),
        ("Type", display_record.get("work_type")),
        ("Salary", display_record.get("salary")),
    ]:
        if value and value != "N/A" and value != "Unknown":
            meta_items.append(
                f'<span class="job-meta-item"><strong>{safe_html(label)}</strong> {safe_html(str(value))}</span>'
            )
    context_bits = []
    if salary_fit_state == "below":
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            "Salary is below target range",
        ])
    contract_item = assess_contract_preference(display_record, scoring_profile)
    if contract_item and int(contract_item.get("value", 0)) < 0:
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            "Contract length is shorter than preferred",
        ])
    if seen_by_you and record.get("last_viewed_at"):
        context_bits.append(f"Opened by you {format_timestamp_label(record.get('last_viewed_at'))}")
    if applied_record and record.get("last_applied_at"):
        context_bits.append(f"Applied {format_timestamp_label(record.get('last_applied_at'))}")
    if hidden_record and record.get("last_hidden_at"):
        context_bits.append(f"Hidden {format_timestamp_label(record.get('last_hidden_at'))}")
    elif archived and record.get("last_kept_at"):
        context_bits.append(f"{ARCHIVE_CONTEXT_PREFIX} {format_timestamp_label(record.get('last_kept_at'))}")
    context_html = f'<div class="job-context">{safe_html(" | ".join(context_bits))}</div>' if context_bits else ""

    summary_html = (
        f'<p class="job-summary">{safe_html(role_summary)}</p>'
        if role_summary and role_summary != "N/A"
        else ""
    )
    note_bits: List[str] = []
    if history_warning_signals:
        note_bits.append(f"Potential red flag: {history_warning_signals[0].removeprefix('Potential red flag: ').strip()}.")
    elif description_issue:
        note_bits.append("Description issue: full job description was not captured clearly.")
    elif is_possible_repost:
        note_bits.append("Alert: This looks like a role you already marked as applied at this company.")
    elif missing_evidence:
        note_bits.append(f"Missing evidence: {missing_evidence[0]}.")
    elif soft_risk_reasons:
        note_bits.append(f"Risk: {soft_risk_reasons[0]}.")
    note_html = (
        f'<div class="job-note">{safe_html(" ".join(note_bits))}</div>'
        if note_bits
        else ""
    )
    reviewed_signal_matches = reviewed_signal_match_summary(display_record, scoring_profile)
    insight_sections = []
    if visible_reasons:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Why it fits</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in visible_reasons)}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["matched"]:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Matched signals</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["matched"])}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["unresolved"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Unresolved signals</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["unresolved"])}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["evidence_only"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Evidence only</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["evidence_only"])}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["ignored"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Ignored</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["ignored"])}</ul>'
            '</div>'
        )
    visible_penalties = negative_score_reasons(score_breakdown, include_values=SHOW_SCORING_DEBUG)
    if description_issue:
        visible_penalties = [
            item for item in visible_penalties
            if not item.startswith("Description capture incomplete")
        ]
    negative_items = dedupe_preserve_order([
        *([] if description_issue else missing_evidence),
        *soft_risk_reasons,
        *visible_penalties,
    ])[:6]
    if description_issue:
        description_issue_items = [DESCRIPTION_CAPTURE_ISSUE]
        if SHOW_SCORING_DEBUG:
            capture_facts = []
            status = compact_whitespace(record.get("details_status") or "")
            source_name = compact_whitespace(record.get("description_source") or "")
            details_length = record.get("details_length")
            if status:
                capture_facts.append(f"details status: {status}")
            if source_name:
                capture_facts.append(f"description source: {source_name}")
            if details_length not in {None, ""}:
                capture_facts.append(f"details length: {details_length}")
            if capture_facts:
                description_issue_items.append("; ".join(capture_facts))
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>Description issue</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in description_issue_items)}</ul>'
            '</div>'
        )
    if history_warning_signals:
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>Potential red flags</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in history_warning_signals)}</ul>'
            '</div>'
        )
    if negative_items:
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>What lowers it</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in negative_items)}</ul>'
            '</div>'
        )
    elif SHOW_SCORING_DEBUG:
        insight_sections.append(
            '<div class="job-insight-group job-insight-muted">'
            '<strong>Watchouts</strong>'
            '<p class="insight-unavailable-note">No explicit risks detected from the captured description.</p>'
            '</div>'
        )
    if SHOW_SCORING_DEBUG:
        negative_reasons = negative_score_reasons(score_breakdown)
        if negative_reasons:
            insight_sections.append(
                '<div class="job-insight-group job-insight-warning">'
                '<strong>Score penalties</strong>'
                f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in negative_reasons)}</ul>'
                '</div>'
            )
        gap_reasons = score_gap_reasons(display_record, score_breakdown)
        if gap_reasons:
            insight_sections.append(
                '<div class="job-insight-group is-secondary">'
                '<strong>Score gaps</strong>'
                f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in gap_reasons)}</ul>'
                '</div>'
            )
    if SHOW_SCORING_DEBUG and score_breakdown:
        score_breakdown_html = "".join(
            f"<li>{safe_html(str(item['label']))}: {int(item['value']):+d}</li>"
            for item in score_breakdown
        )
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Score details</strong>'
            f'<ul>{score_breakdown_html}</ul>'
            '</div>'
        )
    insight_html = (
        '<details class="job-insights">'
        '<summary>Fit breakdown</summary>'
        f'{"".join(insight_sections)}'
        '</details>'
        if insight_sections
        else ""
    )

    if applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo" type="button" data-review-action="unapply" {button_data_attrs}>Undo Applied</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif hidden_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo" type="button" data-review-action="unhide" {button_data_attrs}>Unhide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif not applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-applied" type="button" data-review-action="applied" {button_data_attrs}>Applied</button>'
            f'<button class="review-button review-not-for-me" type="button" data-review-action="not_for_me" {button_data_attrs} title="Marks this role as not a fit and stores it as learning feedback">Not For Me</button>'
            f'<button class="review-button review-hide" type="button" data-review-action="hidden" {button_data_attrs} title="Hide this one job only. You can unhide it later from Hidden jobs.">Hide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    else:
        actions_html = ""

    card_classes = f'job-card {fit_tone_class}' + (" is-description-issue" if description_issue else "")

    return (
        f'<article class="{safe_html(card_classes)}" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html((record.get("company") or "").lower())}" data-source="{safe_html(source)}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        + (
            f'<button class="title-block-btn" type="button" data-review-action="block_similar" data-block-phrase="{block_phrase}" data-block-phrases="{block_phrases_json}" {button_data_attrs} title="Hide future roles whose titles contain the selected words, before description review.">Hide title words</button>'
            '<div class="block-confirm" data-block-confirm hidden>'
            '<p class="block-confirm-copy">Hide future titles with:</p>'
            '<div class="block-phrase-checks" data-block-phrase-checks></div>'
            '<button class="mini-button block-manual-toggle" type="button" data-block-manual-toggle>Add other title words</button>'
            '<div class="block-manual-row">'
            '<span class="block-manual-label">Add title words</span>'
            '<input class="block-manual-input" type="text" data-block-manual-input placeholder="e.g. project manager, payroll">'
            '<span class="block-manual-help">Adds to the checked words above. Use commas to add more than one.</span>'
            '</div>'
            '<p class="block-impact" data-block-impact></p>'
            '<p class="block-confirm-sub">This is a strong filter. Matching titles will be hidden before description review.</p>'
            '<div class="block-confirm-actions">'
            '<button class="mini-button mini-button-primary" type="button" data-confirm-block disabled>Block Selected Titles</button>'
            '<button class="mini-button" type="button" data-cancel-block>Cancel</button>'
            '</div>'
            '</div>'
            '<span class="block-status" aria-live="polite"></span>'
            if (not applied_record and not hidden_record and _block_phrases_list) else "" 
        )
        + f'<div class="job-company">{company}</div>'
        '</div>'
        f"{score_html}"
        '</div>'
        f"{summary_html}"
        f'<div class="job-meta">{"".join(meta_items)}</div>'
        f"{note_html}"
        f"{insight_html}"
        f"{context_html}"
        f"{actions_html}"
        "</article>"
    )


def section_dom_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "matches"


def render_section(
    title: str,
    records: List[dict],
    empty_message: str,
    scoring_profile: Optional[dict] = None,
    applied_pool: Optional[List[dict]] = None,
    history_clusters: Optional[Dict[str, dict]] = None,
) -> str:
    if not records:
        return (
            f'<section class="section"><h2>{safe_html(title)}</h2>'
            f'<p class="empty-state">{safe_html(empty_message)}</p></section>'
        )
    dom_id = section_dom_id(title)
    cards = "".join(
        render_job_card(record, scoring_profile, applied_pool=applied_pool, history_clusters=history_clusters)
        for record in records
    )
    return (
        f'<section class="section job-section" data-section-id="{safe_html(dom_id)}">'
        '<div class="section-head">'
        f'<h2>{safe_html(title)}</h2>'
        '<div class="section-tools">'
        '<span class="pagination-label"></span>'
        '<button class="pagination-button" type="button" data-page-direction="prev">Prev</button>'
        '<button class="pagination-button" type="button" data-page-direction="next">Next</button>'
        "</div>"
        "</div>"
        f'<div class="job-grid">{cards}</div>'
        "</section>"
    )


def load_last_kept_records() -> List[dict]:
    return dashboard_data.load_last_kept_records(
        load_json_list(DEBUG_JSON_PATH),
        deduplicate_across_sources_fn=deduplicate_across_sources,
    )


def build_run_stats(
    audit_rows: List[dict],
    kept_records: List[dict],
    run_started_at: datetime,
    run_finished_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    max_pages_cap: int,
) -> dict:
    return dashboard_data.build_run_stats(
        audit_rows,
        kept_records,
        run_started_at,
        run_finished_at,
        date_range_days,
        sort_newest_first,
        max_pages_cap,
    )


def _render_results_fragment(context: dict[str, str]) -> str:
    if not RESULTS_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing template: {RESULTS_TEMPLATE_PATH}")
    template = Template(RESULTS_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.safe_substitute(context)


def _render_match_level_guide_html(profile: Optional[dict] = None) -> str:
    active_profile = profile or load_profile()
    match_levels = get_match_levels(active_profile)
    guide_bits = [
        f'<span class="chip"><strong>{safe_html(str(level["label"]))}:</strong> {safe_html(str(level["description"]))}</span>'
        for level in match_levels
    ]
    guide_bits.extend([
        '<span class="chip"><strong>Title match:</strong> direct titles are favored over secondary titles</span>',
        '<span class="chip"><strong>Description review:</strong> stronger description fit lifts the match level</span>',
        '<span class="chip"><strong>Competitive signals:</strong> specialist bias can lift or lower the match level</span>',
        '<span class="chip"><strong>Freshness:</strong> newer roles are favored</span>',
        '<span class="chip"><strong>Decision weights:</strong> fit, pay, location, work mode, contract, government, and freshness can be dialed up or down</span>',
        '<span class="chip"><strong>Watchouts:</strong> essential gaps hit harder than desirable-only gaps</span>',
        '<span class="chip"><strong>Risks:</strong> essential gaps hit harder than desirable-only gaps</span>',
    ])
    return "".join(guide_bits)


def render_html(
    output_path: str,
    kept_records: List[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    run_stats: dict,
    job_history: Dict[str, dict],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    dashboard_reference_at: Optional[datetime] = None,
) -> None:
    reference_time = dashboard_reference_at or run_started_at
    scoring_profile = load_profile()
    dashboard_records = build_dashboard_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        scoring_profile,
    )
    history_clusters = build_history_cluster_index(job_history)
    shortlist_records = dashboard_records["shortlist_records"]
    current_records = dashboard_records["current_records"]
    recent_archive_records = dashboard_records["recent_archive_records"]
    stale_archive_records = dashboard_records["stale_archive_records"]
    applied_records = dashboard_records["applied_records"]
    hidden_records = dashboard_records["hidden_records"]
    potential_records = shortlist_records
    score_filter_options_html = render_score_filter_options(potential_records, scoring_profile)
    posted_filter_options_html = render_posted_filter_options(potential_records, reference_time)
    shortlist_count = len(shortlist_records)
    run_label = run_started_at.strftime("%d %b %Y %I:%M %p")
    dashboard_run_id = str(run_stats.get("run_started_at") or run_started_at.isoformat(timespec="seconds"))
    target_summaries = []
    for location, pages in (run_stats.get("search_targets") or {}).items():
        page_label = ", ".join(str(page) for page in pages) if pages else "none"
        target_summaries.append(f"{location}: pages {page_label}")
    testing_mode_notes = []
    if LOW_SCRAPE_MODE:
        testing_mode_notes.append(f"Scrape allow-low mode is on, keeping roles at {score_to_match_label(DASHBOARD_MIN_SCORE, get_match_levels(scoring_profile))} or better.")
    elif DASHBOARD_DEBUG_MODE:
        testing_mode_notes.append(f"Dashboard debug mode is on, showing scores and keeping roles at {score_to_match_label(DASHBOARD_MIN_SCORE, get_match_levels(scoring_profile))} or better without a fresh scrape.")
    elif EXPAND_DASHBOARD_MODE:
        testing_mode_notes.append(f"Expanded dashboard view is on, keeping roles at {score_to_match_label(DASHBOARD_MIN_SCORE, get_match_levels(scoring_profile))} or better without a fresh scrape.")
    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        testing_mode_notes.append("Viewed history has been reset, so all roles are shown as unseen.")
        
    testing_mode_note = " " + " ".join(testing_mode_notes) if testing_mode_notes else ""
    search_window_label = f"Last {date_range_days} day" + ("" if date_range_days == 1 else "s")
    sort_order_label = "Newest first" if sort_newest_first else "Source relevance"
    mode_label = "Debug view ON" if EXPANDED_POOL_MODE or TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else "Normal mode"
    current_search_settings = get_search_settings(scoring_profile)
    search_settings_payload = {
        "keywords": str(current_search_settings.get("keywords") or "").strip(),
        "locations": [str(value).strip() for value in current_search_settings.get("locations", []) if str(value).strip()],
        "date_range_days": int(current_search_settings.get("date_range_days", date_range_days) or date_range_days),
        "max_pages_cap": int(
            current_search_settings.get("max_pages_cap", run_stats.get("max_pages_cap", MAX_PAGES_CAP))
            or run_stats.get("max_pages_cap", MAX_PAGES_CAP)
        ),
    }
    search_keywords_label = search_settings_payload["keywords"] or "Not set"
    search_locations_label = " | ".join(search_settings_payload["locations"]) or "Not set"
    search_locations_text = "\n".join(search_settings_payload["locations"])
    search_settings_json = json.dumps(search_settings_payload, ensure_ascii=False).replace("</", "<\\/")
    
    li_hours = scoring_profile.get("search_settings", {}).get("linkedin_hours_old", 24)
    li_results = scoring_profile.get("search_settings", {}).get("linkedin_results_per_search", 25)
    
    view_history_text = "treats all roles as New To You" if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else "preserves your viewed history"
    snapshot_helper = f"Shortlist currently keeps roles at {score_to_match_label(DASHBOARD_MIN_SCORE, get_match_levels(scoring_profile))} or better and {view_history_text}."
    hero_summary = (
        f"Last run {run_label} - {run_stats.get('cards_seen', 0)} cards scanned, "
        f"{len(shortlist_records)} shortlist matches shown"
    )
    this_run_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (len(shortlist_records), "Matches"),
            (sum(1 for record in shortlist_records if not viewed_by_user(record)), "New to you"),
            (sum(1 for record in shortlist_records if viewed_by_user(record)), "Opened by you"),
            (len(recent_archive_records), ARCHIVE_LABEL),
        ]
    )
    crawler_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (run_stats.get("cards_seen", 0), "Cards seen"),
            (run_stats.get("detail_fetches", 0), "Ads reviewed"),
            (run_stats.get("page_count", 0), "Pages crawled"),
            (f"{round(float(run_stats.get('keep_rate', 0.0)) * 100, 1)}%", "Keep rate"),
        ]
    )
    application_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (len(applied_records), "Applied"),
            (len(hidden_records), "Hidden"),
        ]
    )

    top_reject_reasons_html = "".join(
        f'<span class="chip" title="{safe_html(str(item.get("reason", "UNKNOWN")))}"><strong>{safe_html(humanize_reject_reason(str(item.get("reason", "UNKNOWN"))))}:</strong> {safe_html(str(item.get("count", 0)))}</span>'
        for item in run_stats.get("top_reject_reasons", [])
    )
    html = _render_results_fragment(
        {
            "MODE_LABEL": safe_html(mode_label),
            "HERO_SUMMARY": safe_html(hero_summary),
            "SHORTLIST_COUNT": str(shortlist_count),
            "APPLIED_COUNT": str(len(applied_records)),
            "HIDDEN_COUNT": str(len(hidden_records)),
            "POSTED_FILTER_OPTIONS_HTML": posted_filter_options_html,
            "SCORE_FILTER_OPTIONS_HTML": score_filter_options_html,
            "CURRENT_SECTION_HTML": render_section(
                "Best Matches",
                shortlist_records,
                "No shortlist matches are available right now.",
                scoring_profile,
                applied_pool=applied_records,
                history_clusters=history_clusters,
            ),
            "RECENT_SECTION_HTML": "",
            "ARCHIVE_LABEL": safe_html(ARCHIVE_LABEL),
            "APPLIED_SECTION_HTML": render_section(
                "Applied Jobs",
                applied_records,
                "No applied jobs saved yet.",
                scoring_profile,
                history_clusters=history_clusters,
            ),
            "HIDDEN_SECTION_HTML": render_section(
                "Hidden Jobs",
                hidden_records,
                "No hidden jobs right now.",
                scoring_profile,
                history_clusters=history_clusters,
            ),
            "SEARCH_KEYWORDS_LABEL": safe_html(search_keywords_label),
            "SEARCH_LOCATIONS_LABEL": safe_html(search_locations_label),
            "SEARCH_DATE_RANGE_DAYS": safe_html(str(search_settings_payload["date_range_days"])),
            "SEARCH_DATE_RANGE_SUFFIX": "s" if int(search_settings_payload["date_range_days"]) != 1 else "",
            "SEARCH_MAX_PAGES_CAP": safe_html(str(search_settings_payload["max_pages_cap"])),
            "LINKEDIN_HOURS": safe_html(str(li_hours)),
            "LINKEDIN_RESULTS": safe_html(str(li_results)),
            "SEARCH_KEYWORDS_INPUT": safe_html(search_settings_payload["keywords"]),
            "SEARCH_LOCATIONS_TEXT": safe_html(search_locations_text),
            "THIS_RUN_CARDS_HTML": this_run_cards_html,
            "CRAWLER_CARDS_HTML": crawler_cards_html,
            "APPLICATION_CARDS_HTML": application_cards_html,
            "TARGET_SUMMARIES": safe_html(" | ".join(target_summaries) or "None"),
            "SNAPSHOT_HELPER": safe_html(snapshot_helper),
            "TESTING_MODE_NOTE": safe_html(testing_mode_note),
            "TOP_REJECT_REASONS_HTML": top_reject_reasons_html,
            "MATCH_LEVEL_GUIDE_HTML": _render_match_level_guide_html(scoring_profile),
            "DASHBOARD_RUN_ID_JSON": json.dumps(dashboard_run_id),
            "SEARCH_SETTINGS_JSON": search_settings_json,
            "DEFAULT_SCORE_FILTER_MIN_JSON": json.dumps(str(DEFAULT_SCORE_FILTER_MIN)),
            "VIEWED_BADGE_HTML_JSON": json.dumps(viewed_badge_html()),
        }
    )
    output_file = Path(output_path)
    if not output_file.is_absolute():
        output_file = ROOT_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")


def _extract_seek_card_data(card, search_target: dict, run_iso: str) -> dict:
    """Extracts basic information from a SEEK job card and returns a normalized record."""
    title_el = card.query_selector(SELECTOR_TITLE)
    company_el = card.query_selector(SELECTOR_COMPANY)
    posted_el = card.query_selector(SELECTOR_POSTED)
    card_meta = extract_card_metadata(card)
    card_text = (card.inner_text() or "").strip()

    title = repair_text(title_el.inner_text().strip()) if title_el else ""
    company = repair_text(company_el.inner_text().strip()) if company_el else "N/A"
    posted = posted_el.inner_text().strip() if posted_el else ""
    if not posted:
        posted = extract_posted_text_from_card(card_text)
    posted = normalize_posted_text(posted)
    posted_age_days = parse_seek_posted_age_days(posted)
    
    relative_url = title_el.get_attribute("href") if title_el else None
    full_url = build_full_seek_url(relative_url)

    return {
        "run_started_at": run_iso,
        "search_location": search_target["location"],
        "search_keywords": search_target["keywords"],
        "search_classifications": ",".join(search_target.get("classification_ids", [])),
        "source": "seek",
        "job_key": stable_job_key(full_url) if full_url else None,
        "title": title,
        "company": company,
        "posted": posted,
        "posted_age_days": posted_age_days,
        "url": full_url,
        "location": card_meta["location"],
        "work_mode": card_meta["work_mode"],
        "work_type": card_meta["work_type"],
        "teaser": repair_text(card_meta["teaser"]),
        "card_salary": card_meta["card_salary"],
        "decision": "REJECT",
        "reject_reason": None,
        "title_reason": None,
        "content_reason": None,
        "llm_decision": None,
        "llm_fit_grade": None,
        "role_snapshot": "N/A",
        "fit_highlights": [],
        "soft_risk_reasons": [],
        "missing_evidence": [],
        "competitive_signals": [],
        "reviewed_signal_matches": {"matched": [], "evidence_only": [], "ignored": [], "unresolved": []},
        "details_length": 0,
    }


def _process_seek_job_details(
    record: dict, 
    detail_page, 
    profile: dict, 
    title_reason: str
) -> tuple[bool, str]:
    """Fetches full job details and performs initial content filtering and metadata enrichment."""
    details_payload = fetch_job_details_payload(detail_page, record["url"])
    details_text = str(details_payload.get("text") or "")
    details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))
    details_text = repair_text(details_text)
    
    record["details_status"] = details_status
    record["details_length"] = len(details_text)
    
    if details_status != "ok" or not details_text:
        reject_reason = {
            "challenge_page": "DETAILS_CHALLENGE_PAGE",
            "blocked_page": "DETAILS_BLOCKED_PAGE",
            "navigation_error": "DETAILS_NAVIGATION_ERROR",
            "empty": "NO_DETAILS",
        }.get(details_status, "NO_DETAILS")
        return False, reject_reason

    record["fit_source_text"] = details_text
    record["full_description"] = details_text
    record["description_source"] = details_payload.get("source") or "jobAdDetails"
    source = str(record.get("description_source") or "").strip().lower()
    is_trusted = source in TRUSTED_DESCRIPTION_SOURCES and len(details_text) >= MIN_TRUSTED_DESCRIPTION_LENGTH
    record["fit_confidence"] = "HIGH" if is_trusted else "LOW"

    ok_desc, desc_reason = passes_content_filters(details_text, record["location"], title_reason)
    if not ok_desc:
        return False, desc_reason

    ok_learned, learned_reason = passes_saved_rejection_rules(details_text)
    if not ok_learned:
        return False, learned_reason

    record["competitive_signals"] = [
        evaluate_competitive_signal_alignment(signal, profile)
        for signal in detect_competitive_signals(details_text, profile)
    ]
    record["reviewed_signal_matches"] = reviewed_signal_matches_for_text(details_text)
    
    hard_block_matches = hard_block_entries(record, profile)
    record["hard_block_reasons"] = [entry["text"] for entry in hard_block_matches]
    if record["hard_block_reasons"]:
        return False, f"DESC_HARD_BLOCK:{hard_block_matches[0].get('category') or 'hard_block'}"

    record["salary"] = extract_salary(details_text) or record.get("card_salary", "N/A")
    detail_work_mode = extract_work_mode(details_text)
    if detail_work_mode != "N/A":
        record["work_mode"] = detail_work_mode

    record["role_snapshot"] = build_role_summary(record, details_text, profile)
    record["fit_highlights"] = build_fit_highlights(record, details_text, profile)
    record["soft_risk_reasons"], record["missing_evidence"] = build_risk_and_missing_evidence(
        details_text, title_reason, profile, competitive_signals=record["competitive_signals"]
    )
    
    return True, "OK"


def _evaluate_job_fit(record: dict, profile: dict, llm_cache: dict) -> dict:
    """Determines the final fit decision based on rules or LLM review."""
    deterministic_review = deterministic_review_outcome(
        record, record["fit_highlights"], record["missing_evidence"], record["soft_risk_reasons"]
    )
    
    if deterministic_review is not None:
        review = deterministic_review
        source = "rule"
    else:
        llm_input_text = record["full_description"][:MAX_LLM_CHARS]
        llm_fp = build_llm_cache_key(llm_input_text)
        if NO_LLM_MODE or not llm_is_enabled():
            review = normalize_llm_review(None)
            source = "disabled"
        elif llm_fp in llm_cache:
            review = normalize_llm_review(llm_cache[llm_fp])
            source = "cache"
        else:
            review = normalize_llm_review(llm_should_consider(llm_input_text))
            llm_cache[llm_fp] = review
            source = "llm"

    return {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        "review_source": source,
        "decision": "KEEP" if review["decision"] != "REJECT" else "REJECT"
    }


def _seek_scrape_to_records(
    profile: dict,
    search_targets: List[dict],
    job_history: Dict[str, dict],
    llm_cache: Dict[str, Any],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_iso: str,
    configured_date_range: int,
    enforce_posted_age_limit: bool,
    configured_max_pages: int,
    headless: bool,
) -> tuple:
    """Run the SEEK Playwright scraping loop.

    Returns (kept_records, audit_rows, skill_observations).
    Shared state objects (job_history, llm_cache) are mutated in-place.
    """
    audit_rows: List[dict] = []
    kept_records: List[dict] = []
    skill_observations: List[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        list_page = browser.new_page(viewport={"width": 1400, "height": 900})
        detail_page = browser.new_page(viewport={"width": 1400, "height": 900})

        try:
            seen_urls: Set[str] = set()
            for search_target in search_targets:
                base_search_url = search_target["url"]
                search_location = search_target["location"]
                search_keywords = search_target["keywords"]
                classification_ids = ",".join(search_target.get("classification_ids", []))
                current_page_num = 1

                print(f"Location: {search_location}")
                print(f"Keywords: {search_keywords}")
                print(f"classification_ids: {classification_ids}")
                
                while current_page_num <= configured_max_pages:
                    page_url = set_page_param(base_search_url, current_page_num) if current_page_num > 1 else base_search_url

                    print(f"\n=== {search_location} | Page {current_page_num} ===")
                    print("URL:", page_url)

                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        list_page.wait_for_selector(SELECTOR_CARDS, timeout=8000)
                    except Exception as exc:
                        print(
                            f"No visible job cards for {search_location} on page {current_page_num}. "
                            f"Stopping this target. [{type(exc).__name__}]"
                        )
                        break

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    print(f"Found {len(job_cards)} job cards")

                    if len(job_cards) == 0:
                        print("No cards found. Stopping this target.")
                        break

                    page_has_fresh_card = False
                    
                    for card in job_cards:
                        try:
                            record = _extract_seek_card_data(card, search_target, run_iso)
                            record["page"] = current_page_num
                            title, company = record["title"], record["company"]
                            posted_age_days = record["posted_age_days"]

                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            ok_title, title_reason = passes_title_filters(title)
                            record["title_reason"] = title_reason
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                record["reject_reason"] = title_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if not record["url"]:
                                print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                                record["reject_reason"] = "NO_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            job_key = record["job_key"]
                            if job_key in applied_job_keys:
                                print(f"SKIP (applied) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "ALREADY_APPLIED"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if job_key in hidden_job_keys:
                                print(f"SKIP (hidden) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "MANUALLY_HIDDEN"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if enforce_posted_age_limit and posted_age_days is not None and posted_age_days > configured_date_range:
                                print(f"REJECTED (posted) [POSTED_TOO_OLD:{configured_date_range}] {title} @ {company}")
                                record["reject_reason"] = f"POSTED_TOO_OLD:{configured_date_range}"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["url"] in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "DUPLICATE_URL"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(record["url"])

                            if not SKIP_QUICK_CARD_GATE_FOR_TESTING:
                                ok_card, card_reason = passes_quick_card_filters(title=title, teaser=record["teaser"], company=company, location=record["location"], work_mode=record["work_mode"], work_type=record["work_type"], salary=record.get("card_salary", "N/A"))
                                if not ok_card:
                                    print(f"REJECTED (card gate) [{card_reason}] {title} @ {company}")
                                    record["reject_reason"] = card_reason
                                    finalize_record(job_history, audit_rows, record, run_iso)
                                    continue

                            history_entry = job_history.get(job_key or "", {})
                            if can_reuse_kept_job(history_entry, record, profile):
                                record = apply_kept_job_reuse(record, history_entry)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                kept_records.append(record)
                                print(f"KEPT (history reuse): {title} @ {company}")
                                continue

                            ok_details, reject_reason = _process_seek_job_details(record, detail_page, profile, title_reason)
                            if not ok_details:
                                print(f"REJECTED (details/content) [{reject_reason}] {title} @ {company}")
                                record["reject_reason"] = reject_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            fit_eval = _evaluate_job_fit(record, profile, llm_cache)
                            record.update(fit_eval)
                            
                            if record["decision"] == "REJECT":
                                print(f"REJECTED ({record['review_source']}) {title} @ {company}")
                                record["reject_reason"] = "LLM_REJECT" if record["review_source"] == "llm" else "DET_REJECT"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            
                            skill_observations.extend(extract_skill_observations(record, record["full_description"], profile))
                            finalize_record(job_history, audit_rows, record, run_iso)
                            kept_records.append(record)
                            print(f"KEPT: {title} @ {company} | {'SEEN_BEFORE' if record.get('seen_before') else 'NEW'}")

                        except Exception as exc:
                            record["reject_reason"] = f"CARD_EXCEPTION:{type(exc).__name__}"
                            print(f"REJECTED (card) [CARD_EXCEPTION:{type(exc).__name__}] {title} @ {company}")
                            finalize_record(job_history, audit_rows, record, run_iso)

                    if enforce_posted_age_limit and not page_has_fresh_card:
                        print(
                            f"All cards for {search_location} on page {current_page_num} "
                            f"were older than {configured_date_range} day(s). Stopping this target."
                        )
                        break

                    current_page_num += 1

        finally:
            browser.close()

    return kept_records, audit_rows, skill_observations


def scrape_jobs_direct(max_pages_cap: int = MAX_PAGES_CAP, headless: bool = False) -> str:
    configure_console_output()
    from job_hunter_agent.llm_gate import _get_llm_model
    print("=" * 60)
    print("  JOB HUNTER AGENT - SCRAPE RUN")
    print("=" * 60)
    print("  Trigger            : manual scrape command")
    print("  Action             : scrape fresh jobs, review them, rebuild dashboard")
    print("  Fresh scrape       : YES")
    print(f"  Dashboard debug    : {'ON (--debug-dashboard)' if DASHBOARD_DEBUG_MODE else 'OFF'}")
    print(f"  Scrape allow low   : {'ON (--scrape-allow-low)' if LOW_SCRAPE_MODE else 'OFF'}")
    print(f"  Cheap LLM          : {'ON (--cheap-llm)' if CHEAP_LLM_MODE else 'OFF'}")
    if DASHBOARD_DEBUG_MODE:
        expanded_label = "ON (--debug-dashboard)"
    elif LOW_SCRAPE_MODE:
        expanded_label = "ON (--scrape-allow-low)"
    elif EXPAND_DASHBOARD_MODE:
        expanded_label = "ON (--expand-dashboard)"
    else:
        expanded_label = "OFF"
    score_debug_label = "ON (--debug-dashboard)" if DASHBOARD_DEBUG_MODE else ("ON (--show-scores)" if SHOW_SCORES_MODE else "OFF")
    print(f"  Expanded view      : {expanded_label}")
    print(f"  Score debug        : {score_debug_label}")
    print(f"  LLM Disabled       : {'YES (--no-llm flag)' if NO_LLM_MODE else 'NO'}")
    print(f"  LLM Model          : {_get_llm_model()}")
    print(f"  Score Floor        : {DASHBOARD_MIN_SCORE}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}")
    if CLI_MAX_PAGES_CAP is not None:
        print(f"  Max pages override : {CLI_MAX_PAGES_CAP} (--max-pages)")
    print("=" * 60)

    profile = load_profile()
    previous_audit_rows = load_json_list(DEBUG_JSON_PATH)
    previous_run_stats = load_json_dict(RUN_STATS_PATH)
    search_settings = get_search_settings(profile)
    configured_max_pages = int(search_settings.get("max_pages_cap", max_pages_cap) or max_pages_cap)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    if CLI_MAX_PAGES_CAP is not None:
        configured_max_pages = CLI_MAX_PAGES_CAP
    enforce_posted_age_limit = bool(search_settings.get("enforce_posted_age_limit", True))
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()
    run_iso = run_started_at.isoformat(timespec="seconds")
    llm_cache: Dict[str, Any] = load_llm_cache()
    job_history = load_job_history()

    enabled_sources = [s.lower().strip() for s in (profile.get("enabled_sources") or ["seek"])]

    kept_records: List[dict] = []
    audit_rows: List[dict] = []
    skill_observations: List[dict] = []

    # --- SEEK ---
    if "seek" in enabled_sources:
        search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
        s_kept, s_audit, s_skills = _seek_scrape_to_records(
            profile=profile,
            search_targets=search_targets,
            job_history=job_history,
            llm_cache=llm_cache,
            applied_job_keys=applied_job_keys,
            hidden_job_keys=hidden_job_keys,
            run_iso=run_iso,
            configured_date_range=configured_date_range,
            enforce_posted_age_limit=enforce_posted_age_limit,
            configured_max_pages=configured_max_pages,
            headless=headless,
        )
        kept_records.extend(s_kept)
        audit_rows.extend(s_audit)
        skill_observations.extend(s_skills)

    # --- LinkedIn ---
    if "linkedin" in enabled_sources:
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
    # Final semantic deduplication pass to collapse reposts and cross-source duplicates
    kept_records = deduplicate_across_sources(kept_records)

    if not audit_rows and previous_audit_rows:
        render_html(
            OUTPUT_HTML,
            load_last_kept_records(),
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
        print("\nNo fresh cards were captured in this run, so the previous dashboard state was preserved.")
        print(f"Dashboard preserved at {OUTPUT_HTML}")
        return OUTPUT_HTML

    run_finished_at = datetime.now().astimezone()
    run_stats = build_run_stats(
        audit_rows,
        kept_records,
        run_started_at,
        run_finished_at,
        configured_date_range,
        sort_newest_first,
        configured_max_pages,
    )

    render_html(
        OUTPUT_HTML,
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
    print(f"\nSaved {len(kept_records)} jobs to {OUTPUT_HTML}")
    print(f"Saved {len(audit_rows)} audit rows to {DEBUG_JSON_PATH}")
    print(f"Saved run stats to {RUN_STATS_PATH}")
    print(f"Saved review data to {REVIEW_DATA_PATH}")
    print(f"Saved history for {len(job_history)} jobs to {JOB_HISTORY_PATH}")
    return OUTPUT_HTML


def rebuild_html_dashboard(reason: str = "Manual --rebuild-dashboard command") -> str:
    configure_console_output()
    print("=" * 60)
    print("  JOB HUNTER AGENT - DASHBOARD REBUILD")
    print("=" * 60)
    print(f"  Trigger            : {reason}")
    print("  Action             : re-render saved dashboard only")
    print("  Fresh scrape       : NO")
    print("  AI review          : NO")
    print(f"  Dashboard debug    : {'ON (--debug-dashboard)' if DASHBOARD_DEBUG_MODE else 'OFF'}")
    expanded_label = "ON (--debug-dashboard)" if DASHBOARD_DEBUG_MODE else ("ON (--expand-dashboard)" if EXPAND_DASHBOARD_MODE else "OFF")
    score_debug_label = "ON (--debug-dashboard)" if DASHBOARD_DEBUG_MODE else ("ON (--show-scores)" if SHOW_SCORES_MODE else "OFF")
    print(f"  Expanded view      : {expanded_label}")
    print(f"  Score debug        : {score_debug_label}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}")
    print("=" * 60)
    profile = load_profile()
    search_settings = get_search_settings(profile)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    run_stats = load_json_dict(RUN_STATS_PATH)
    run_started_at = parse_timestamp(run_stats.get("run_started_at")) or datetime.now().astimezone()
    reference_time = datetime.now().astimezone()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    job_history = load_job_history()
    kept_records = load_last_kept_records()
    print(f"  Saved kept records : {len(kept_records)}")
    print(f"  Job history records: {len(job_history)}")
    print(f"  Applied keys       : {len(applied_job_keys)}")
    print(f"  Hidden keys        : {len(hidden_job_keys)}")
    print("=" * 60)

    render_html(
        OUTPUT_HTML,
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
    print(f"Dashboard rebuilt at {OUTPUT_HTML}")
    return OUTPUT_HTML


if __name__ == "__main__":
    if "--rebuild-dashboard" in sys.argv:
        rebuild_html_dashboard()
    else:
        scrape_jobs_direct()
