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
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from job_hunter_agent.capability_matrix import expand_capability_terms
from job_hunter_agent.config import MAX_PAGES_CAP, OUTPUT_HTML
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
from job_hunter_agent.profile_store import (
    get_evidence_tier_weights,
    get_evidence_tiers,
    get_preference_weights,
    get_search_settings,
    load_profile,
)
from job_hunter_agent.review_insights import build_review_data
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
from job_hunter_agent.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from job_hunter_agent.utils import (
    extract_salary,
    extract_work_mode,
    parse_seek_posted_age_days,
    safe_html,
    set_page_param,
)


ROOT_DIR = REPO_ROOT
MAX_LLM_CHARS = 3000
ARCHIVE_STALE_AFTER_DAYS = 15
HIDDEN_REVIEW_DAYS = 30
AUTO_REFRESH_SECONDS = 60
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
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
DEBUG_JSON_PATH = OUTPUT_DIR / "audit_records.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
RUN_STATS_PATH = OUTPUT_DIR / "run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "review_data.json"
MIN_TRUSTED_DESCRIPTION_LENGTH = 600
TRUSTED_DESCRIPTION_SOURCES = frozenset({"jobaddetails", "body", "linkedin_full_description"})
DESCRIPTION_CAPTURE_ISSUE = "Full job description not captured clearly"

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
    cleaned = re.sub(r"^[•\-–—]+\s*", "", cleaned).strip()
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
    combined = f"{company}\n{compact_whitespace(details_text).lower()}"
    recruiter_company_match = re.search(r"\b(recruitment|recruiter|staffing|talent)\b", company)
    recruiter_copy_match = re.search(r"\bour client\b", combined)
    if recruiter_company_match and recruiter_copy_match:
        return {"kind": "recruiter", "label": "Recruiter posting", "confidence": "high"}
    if recruiter_company_match:
        return {"kind": "recruiter", "label": "Recruiter posting", "confidence": "medium"}
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


_GOVERNMENT_CONTEXT_PATTERNS = (
    r"\bgovernment\b",
    r"\bpublic sector\b",
    r"\bfederal\b",
    r"\baps\d*\b",
    r"\bdepartment\b",
    r"\bdepartment of\b",
    r"\bministry\b",
    r"\bcouncil\b",
    r"\bstate government\b",
    r"\blocal government\b",
    r"\bgovernment agency\b",
)
_GOVERNMENT_CONTEXT_FALSE_POSITIVE_PATTERNS = (
    r"\bgovernment\s+id(?:entification)?\s+(?:number|numbers|document|documents)?\b",
    r"\bgovernment-issued\s+id(?:entification)?\b",
)


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


def find_profile_capability_matches(details_text: str, profile: dict) -> Dict[str, List[str]]:
    lowered = compact_whitespace(details_text).lower()
    matched_core: List[str] = []
    matched_supporting: List[str] = []
    matched_low_fit: List[str] = []
    matched_must_not: List[str] = []

    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        fit = str(rule.get("fit") or "").strip().lower()
        level = str(rule.get("level") or "").strip().lower()
        aliases = [str(alias).strip().lower() for alias in expand_capability_terms(rule) if str(alias).strip()]
        if not aliases:
            continue
        if not any(text_contains_term(lowered, alias) for alias in aliases):
            continue
        label = friendly_capability_label(name)
        if fit in {"core", "supporting"} and level in {"strong", "working", "basic"}:
            if fit == "core":
                matched_core.append(label)
            else:
                matched_supporting.append(label)
        elif fit == "avoid" or level in {"low", "none"}:
            matched_low_fit.append(label)

    for skill in profile.get("must_not_require_skills", []):
        cleaned_skill = str(skill).strip().lower()
        if cleaned_skill and matches_missing_requirement(lowered, cleaned_skill):
            matched_must_not.append(cleaned_skill.upper() if cleaned_skill.isupper() else cleaned_skill)

    return {
        "core": dedupe_preserve_order(matched_core),
        "supporting": dedupe_preserve_order(matched_supporting),
        "low_fit": dedupe_preserve_order(matched_low_fit),
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

    matched_profile_areas = capability_matches["core"][:3] + capability_matches["supporting"][:2]
    for area in matched_profile_areas:
        label = friendly_capability_label(area)
        if label and f"Strong capability match: {label}" not in highlights:
            highlights.append(f"Strong capability match: {label}")

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
    return compact_whitespace(value).startswith("Strong capability match:")


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
        risks.append("Adjacent title match rather than direct target role")

    if capability_matches["must_not"]:
        missing.append(f"{list_to_phrase(capability_matches['must_not'][:2]).capitalize()} explicitly required but not evidenced")

    if capability_matches["low_fit"]:
        risks.append(f"{list_to_phrase(capability_matches['low_fit'][:2]).capitalize()} looks niche for your background")

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
    fit = compact_whitespace(rule.get("fit") or "").lower()
    level_map = {
        "strong": 1.0,
        "working": 0.72,
        "basic": 0.55,
        "low": 0.22,
        "none": 0.0,
    }
    fit_bonus = {
        "core": 0.08,
        "supporting": 0.0,
        "contextual": -0.06,
        "avoid": -0.18,
    }
    return max(min(level_map.get(level, 0.45) + fit_bonus.get(fit, 0.0), 1.05), 0.0)


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
        aliases = _normalized_aliases(list(raw_cluster.get("aliases") or []))
        if len(aliases) < 2:
            continue

        matched_aliases = [alias for alias in aliases if text_contains_term(source_text, alias)]
        if len(matched_aliases) < int(raw_cluster.get("min_alias_hits", 2) or 2):
            continue

        snippet_hits = 0
        max_aliases_in_snippet = 0
        for snippet in snippets:
            alias_hits_in_snippet = sum(1 for alias in matched_aliases if text_contains_term(snippet, alias))
            max_aliases_in_snippet = max(max_aliases_in_snippet, alias_hits_in_snippet)
            if alias_hits_in_snippet > 0:
                snippet_hits += 1
        min_snippet_hits = int(raw_cluster.get("min_snippet_hits", 2) or 2)
        dense_snippet_alias_hits = int(
            raw_cluster.get("dense_snippet_alias_hits", max(int(raw_cluster.get("min_alias_hits", 2) or 2) + 2, 4))
            or max(int(raw_cluster.get("min_alias_hits", 2) or 2) + 2, 4)
        )
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
    aliases = _normalized_aliases(list(signal.get("aliases") or []))
    capability_best = 0.0

    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        rule_aliases = _normalized_aliases(expand_capability_terms(rule))
        if not rule_aliases:
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
    positive_bonus = int(signal.get("positive_bonus", min(1 + dominance_level, 3)) or min(1 + dominance_level, 3))
    partial_penalty = int(signal.get("partial_penalty", 4 + (dominance_level * 2)) or 4 + (dominance_level * 2))
    weak_penalty = int(signal.get("weak_penalty", 6 + (dominance_level * 2)) or 6 + (dominance_level * 2))
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


def score_to_tone_class(score: int) -> str:
    if score >= 85:
        return "tone-strong"
    if score >= 70:
        return "tone-good"
    if score >= 55:
        return "tone-borderline"
    return "tone-low"


def compact_score_label(label: str) -> str:
    direct_map = {
        "Direct target title match": "Title",
        "Adjacent title match": "Title",
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


def llm_description_fit_entry(record: dict) -> dict:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    decision = str(record.get("llm_decision") or "").strip().upper()
    if not grade:
        fallback_map = {
            "KEEP": "STRONG",
            "MAYBE": "SOLID",
            "REJECT": "MISMATCH",
        }
        grade = fallback_map.get(decision, "SOLID")

    grade_map = {
        "EXCELLENT": ("Description fit is excellent", 20),
        "STRONG": ("Description fit is strong", 16),
        "SOLID": ("Description fit is solid", 12),
        "WEAK": ("Description fit is mixed", 6),
        "POOR": ("Description fit is weak", 0),
        "MISMATCH": ("Description fit is a mismatch", -10),
    }
    label, value = grade_map.get(grade, grade_map["SOLID"])
    return {"label": label, "value": value}


def capability_match_summary(record: dict, profile: Optional[dict] = None) -> Dict[str, List[str]]:
    active_profile = profile or load_profile()
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    return find_profile_capability_matches(source_text, active_profile)


def capability_evidence_score(record: dict, profile: Optional[dict] = None) -> tuple[int, dict]:
    matches = capability_match_summary(record, profile)
    core_count = len(matches.get("core", []))
    supporting_count = len(matches.get("supporting", []))
    score = min((core_count * 4) + (supporting_count * 2), 18)
    return score, matches


def calibrated_fit_alignment_entry(record: dict, capability_matches: Optional[dict] = None) -> Optional[dict]:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    title_reason = str(record.get("title_reason") or "").strip().upper()
    content_reason = str(record.get("content_reason") or "").strip().upper()
    fit_confidence = full_description_confidence(record)
    missing_evidence = [item for item in (record.get("missing_evidence") or []) if compact_whitespace(item)]
    soft_risks = [item for item in (record.get("soft_risk_reasons") or []) if compact_whitespace(item)]
    matches = capability_matches or capability_match_summary(record)
    core_count = len(matches.get("core", []))

    if title_reason != "OK" or content_reason != "OK" or fit_confidence != "HIGH":
        return None
    if missing_evidence:
        return None
    if grade in {"EXCELLENT", "STRONG"} and core_count >= 2:
        bonus = 6 if not soft_risks else 4
        return {"label": "Core fit signals align", "value": bonus}
    return None


def clean_fit_bonus_entry(
    record: dict,
    breakdown: List[dict],
    capability_matches: Optional[dict] = None,
) -> Optional[dict]:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    title_reason = str(record.get("title_reason") or "").strip().upper()
    content_reason = str(record.get("content_reason") or "").strip().upper()
    fit_confidence = full_description_confidence(record)
    missing_evidence = [item for item in (record.get("missing_evidence") or []) if compact_whitespace(item)]
    soft_risks = [item for item in (record.get("soft_risk_reasons") or []) if compact_whitespace(item)]
    matches = capability_matches or capability_match_summary(record)
    capability_count = len(matches.get("core", [])) + len(matches.get("supporting", []))

    if title_reason != "OK" or content_reason != "OK" or fit_confidence != "HIGH":
        return None
    if grade not in {"EXCELLENT", "STRONG", "SOLID"}:
        return None
    if missing_evidence or soft_risks:
        return None
    if capability_count < 3:
        return None
    if any(int(item.get("value", 0) or 0) < 0 for item in breakdown):
        return None
    return {"label": "Clean fit with no clear penalties", "value": 2}


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
        return {"label": f"Location matches primary preference: {label_target}", "value": 4}

    if secondary_location and _matches_location(secondary_location):
        label_target = compact_whitespace(secondary_location)
        if work_mode == "remote" or "remote position" in source_text or "fully remote" in source_text:
            return {"label": f"Location matches secondary preference with remote setup: {label_target}", "value": 2}
        if re.search(r"\b(1 day a week|one day a week|1 day per week|fortnight|2 days a month|two days a month)\b", source_text):
            return {"label": f"Secondary location has limited onsite attendance: {label_target}", "value": 0}
        if re.search(r"\b(2 days a week|two days a week|3 days a week|three days a week|2-3 days|two to three days)\b", source_text):
            return {"label": f"Secondary location requires regular onsite attendance: {label_target}", "value": -3}

        secondary_terms = [re.escape(value) for value in _location_variants(secondary_location) if value]
        if secondary_terms and re.search(
            rf"\b(must be based in|must reside in|onsite in)\s+(?:{'|'.join(secondary_terms)})\b",
            source_text,
        ):
            return {"label": f"Secondary location requires local onsite attendance: {label_target}", "value": -6}
        return {"label": f"Location matches secondary preference: {label_target}", "value": -1}

    return None


def assess_contract_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
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
            return {"label": "Permanent role (preference is Contract)", "value": -4}
        return {"label": "Permanent role", "value": 7}

    if not is_contract:
        return None

    if eng_pref == "permanent":
        return {"label": "Contract role (preference is Permanent)", "value": -4}

    contract_months = extract_contract_months(source_text)
    if contract_months is None:
        return None
    if contract_months >= preferred_contract_months:
        if "extension" in source_text.lower():
            return {"label": "12+ month contract with extension potential", "value": 6}
        return {"label": "12+ month contract", "value": 5}
    if contract_months >= short_contract_months:
        return {"label": "6-12 month contract", "value": 2}
    return {"label": "Contract is shorter than preferred", "value": -4}


def assess_government_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    if not preferences.get("prefer_government", True):
        return None

    title = compact_whitespace(record.get("title") or "").lower()
    company = compact_whitespace(record.get("company") or "").lower()
    source_text = build_scoring_source_text(record).lower()
    combined = "\n".join([title, company, source_text])
    if has_government_context(combined) or text_contains_term(combined, "ministerial"):
        return {"label": "Government context", "value": 4}
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
        capability_count = len(capability_matches.get("core", [])) + len(capability_matches.get("supporting", []))
        gaps.append(f"Only {capability_count} capability evidence match{'es' if capability_count != 1 else ''} counted")

    if full_description_confidence(record) == "LOW":
        gaps.append("Scoring confidence is limited because the full description was not captured")

    return dedupe_preserve_order(gaps)[:max_items]


def score_to_match_label(score: int) -> str:
    if score >= 85:
        return "Strong match"
    if score >= 70:
        return "Good match"
    if score >= 55:
        return "Worth a look"
    return "Stretch"


def score_filter_option_label(threshold: int) -> str:
    label = score_to_match_label(threshold)
    if threshold >= 85:
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

    thresholds = [85, 70, 55]
    if show_borderline or any(score < 50 for score in scores):
        thresholds.append(35)
    return thresholds


def render_score_filter_options(
    records: List[dict],
    scoring_profile: Optional[dict] = None,
    default_min: int = DEFAULT_SCORE_FILTER_MIN,
    include_borderline: Optional[bool] = None,
) -> str:
    options = ['<option value="all">All match levels</option>']
    for threshold in score_filter_thresholds(records, scoring_profile, include_borderline=include_borderline):
        selected_attr = " selected" if int(default_min) == threshold else ""
        options.append(
            f'<option value="{threshold}"{selected_attr}>'
            f'{safe_html(score_filter_option_label(threshold))}</option>'
        )
    return "".join(options)


def posted_filter_option_label(threshold: int) -> str:
    labels = {
        1: "Posted today",
        3: "Recent roles",
        7: "This week",
        15: "Last two weeks",
        30: "This month",
    }
    return labels.get(threshold, f"Last {threshold} days")


def render_posted_filter_options(records: List[dict]) -> str:
    options = [f'<option value="all">Any posted date ({len(records)})</option>']
    previous_count = 0
    for threshold in [1, 3, 7, 15, 30]:
        count = sum(
            1
            for record in records
            if record.get("posted_age_days") is not None
            and float(record.get("posted_age_days") or 0) <= threshold
        )
        if count == previous_count:
            continue
        previous_count = count
        options.append(
            f'<option value="{threshold}">'
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
        return "Adjacent title match"
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

    active_profile = profile or load_profile()
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
            return 3
        ratio = parsed_value / minimum_daily_rate
        if ratio >= 0.80:
            return -2
        if ratio >= 0.60:
            return -4
        return -5

    if is_non_comparable_period:
        return 0

    if minimum_salary_yearly <= 0 or parsed_value <= 0:
        return 0
    if parsed_value >= minimum_salary_yearly:
        return 3
    ratio = parsed_value / minimum_salary_yearly
    if ratio >= 0.80:
        return -2
    if ratio >= 0.60:
        return -4
    return -5


def fit_score_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    breakdown: List[dict] = []
    title_reason = str(record.get("title_reason") or "")
    content_reason = str(record.get("content_reason") or "")
    posted_age_days = record.get("posted_age_days")
    work_mode = str(record.get("work_mode") or "").lower()
    fit_highlights = [item for item in record.get("fit_highlights", []) if str(item).strip()]
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    evidence_score, capability_matches = capability_evidence_score(record, active_profile)

    if hard_block_labels:
        return [{"label": f"Hard blocker requirement mismatch: {hard_block_labels[0]}", "value": -100}]

    if title_reason == "OK":
        breakdown.append({"label": "Direct target title match", "value": weighted_points(14, weights["fit"])})
    elif title_reason == "TITLE_POTENTIAL_MATCH":
        breakdown.append({"label": "Adjacent title match", "value": weighted_points(4, weights["fit"])})

    llm_entry = llm_description_fit_entry(record)
    breakdown.append({"label": llm_entry["label"], "value": weighted_points(int(llm_entry["value"]), weights["fit"])})

    if content_reason == "OK":
        breakdown.append({"label": "Passed content filters", "value": weighted_points(8, weights["fit"])})

    if full_description_confidence(record) == "LOW":
        breakdown.append({"label": "Description capture incomplete", "value": weighted_points(-10, weights["fit"])})

    if evidence_score:
        breakdown.append({"label": "Fit evidence bullets", "value": weighted_points(evidence_score, weights["fit"])})

    calibrated_fit_entry = calibrated_fit_alignment_entry(record, capability_matches)
    if calibrated_fit_entry:
        breakdown.append({
            "label": calibrated_fit_entry["label"],
            "value": weighted_points(int(calibrated_fit_entry["value"]), weights["fit"]),
        })

    for item in competitive_signal_breakdown(record, active_profile):
        breakdown.append({"label": item["label"], "value": weighted_points(int(item["value"]), weights["fit"])})

    if posted_age_days is not None:
        if posted_age_days <= (1 / 24):
            breakdown.append({"label": "Posted within the last hour", "value": weighted_points(12, weights["freshness"])})
        elif posted_age_days <= 1:
            breakdown.append({"label": "Posted within the last day", "value": weighted_points(9, weights["freshness"])})
        elif posted_age_days <= 3:
            breakdown.append({"label": "Posted within the last 3 days", "value": weighted_points(6, weights["freshness"])})
        elif posted_age_days <= 7:
            breakdown.append({"label": "Posted within the last week", "value": weighted_points(3, weights["freshness"])})
        elif posted_age_days <= 15:
            breakdown.append({"label": "Still relatively recent", "value": weighted_points(1, weights["freshness"])})

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
        breakdown.append({"label": "Hybrid work available", "value": weighted_points(1, weights["work_mode"])})
    elif work_mode == "remote":
        breakdown.append({"label": "Remote work available", "value": weighted_points(2, weights["work_mode"])})
    elif work_mode in {"on-site", "onsite", "on site"}:
        breakdown.append({"label": "On-site role", "value": weighted_points(-4, weights["work_mode"])})

    salary_score = weighted_points(salary_fit_adjustment(record, active_profile), weights["salary"])
    if salary_score > 0:
        breakdown.append({"label": "Salary/rate signal", "value": salary_score})
    elif salary_score < 0:
        breakdown.append({"label": "Salary/rate below target", "value": salary_score})

    if viewed_by_user(record) and not record.get("applied"):
        breakdown.append({"label": "Already viewed by you", "value": -3})

    clean_fit_bonus = clean_fit_bonus_entry(record, breakdown, capability_matches)
    if clean_fit_bonus:
        breakdown.append({"label": clean_fit_bonus["label"], "value": weighted_points(int(clean_fit_bonus["value"]), weights["fit"])})

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
        record["posted"] = snapshot.get("posted") or "N/A"
    if record.get("posted_age_days") is None and snapshot.get("posted_age_days") is not None:
        record["posted_age_days"] = snapshot.get("posted_age_days")
    if record.get("salary") in {None, "", "N/A"}:
        record["salary"] = snapshot.get("salary") or "N/A"
    if record.get("teaser") in {None, "", "N/A"}:
        record["teaser"] = snapshot.get("teaser") or "N/A"
    if record.get("location") in {None, "", "N/A"}:
        record["location"] = snapshot.get("location") or "N/A"
    if record.get("work_mode") in {None, "", "N/A"}:
        record["work_mode"] = snapshot.get("work_mode") or "N/A"
    if record.get("work_type") in {None, "", "N/A"}:
        record["work_type"] = snapshot.get("work_type") or "N/A"
    if record.get("role_snapshot") in {None, "", "N/A"}:
        record["role_snapshot"] = snapshot.get("role_snapshot") or "N/A"
    if not compact_whitespace(record.get("fit_source_text") or ""):
        record["fit_source_text"] = snapshot.get("fit_source_text") or ""
    if not compact_whitespace(record.get("full_description") or ""):
        record["full_description"] = snapshot.get("full_description") or ""
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
    if int(entry.get("times_kept", 0) or 0) <= 0:
        return None

    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    archived_age_days = days_since(entry.get("last_kept_at"), run_started_at)
    record = {
        "job_key": job_key,
        "source": "linkedin" if str(job_key).startswith("linkedin:") else "seek",
        "title": snapshot.get("title") or entry.get("title") or "Untitled",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "llm_fit_grade": snapshot.get("llm_fit_grade"),
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "fit_source_text": snapshot.get("fit_source_text") or "",
        "full_description": snapshot.get("full_description") or "",
        "fit_confidence": snapshot.get("fit_confidence") or "",
        "details_status": snapshot.get("details_status") or "",
        "description_source": snapshot.get("description_source") or "",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],
        "missing_evidence": snapshot.get("missing_evidence") or [],
        "competitive_signals": snapshot.get("competitive_signals") or [],
        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],
        "seen_before": True,
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "times_kept": int(entry.get("times_kept", 0) or 0),
        "first_kept_at": entry.get("first_kept_at"),
        "last_kept_at": entry.get("last_kept_at"),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "archived": True,
        "archived_age_days": archived_age_days,
        "is_stale": archived_age_days is not None and archived_age_days > ARCHIVE_STALE_AFTER_DAYS,
    }
    return record


def build_archive_records(
    history: Dict[str, dict],
    current_run_keys: Set[str],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_started_at: datetime,
) -> List[dict]:
    records: List[dict] = []
    blocked_keys = applied_job_keys | hidden_job_keys

    for job_key, entry in history.items():
        normalized_key = normalize_job_key(str(job_key))
        if not normalized_key or normalized_key in current_run_keys or normalized_key in blocked_keys:
            continue
        record = build_history_dashboard_record(normalized_key, entry, run_started_at)
        if record:
            records.append(record)

    records.sort(
        key=lambda item: parse_timestamp(item.get("last_kept_at")) or datetime.min,
        reverse=True,
    )
    return records


def build_hidden_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")
    hidden_age_days = days_since(hidden_at, run_started_at) if hidden_at else None
    return {
        "job_key": job_key,
        "source": "linkedin" if str(job_key).startswith("linkedin:") else "seek",
        "title": snapshot.get("title") or entry.get("title") or f"Hidden job {job_key}",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "llm_fit_grade": snapshot.get("llm_fit_grade"),
        "fit_source_text": snapshot.get("fit_source_text") or "",
        "full_description": snapshot.get("full_description") or "",
        "fit_confidence": snapshot.get("fit_confidence") or "",
        "details_status": snapshot.get("details_status") or "",
        "description_source": snapshot.get("description_source") or "",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],
        "missing_evidence": snapshot.get("missing_evidence") or [],
        "competitive_signals": snapshot.get("competitive_signals") or [],
        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "first_hidden_at": entry.get("first_hidden_at"),
        "last_hidden_at": entry.get("last_hidden_at"),
        "hidden_age_days": hidden_age_days,
        "hidden": True,
    }


def build_hidden_records(
    hidden_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    records: List[dict] = []
    for job_key in hidden_job_keys:
        entry = history.get(job_key, {})
        hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")
        hidden_age_days = days_since(hidden_at, run_started_at) if hidden_at else None
        if hidden_age_days is not None and hidden_age_days > HIDDEN_REVIEW_DAYS:
            continue
        records.append(build_hidden_dashboard_record(job_key, entry, run_started_at))

    records.sort(
        key=lambda item: (
            parse_timestamp(item.get("last_hidden_at")) or datetime.min,
            parse_timestamp(item.get("last_seen_at")) or datetime.min,
        ),
        reverse=True,
    )
    return records


def build_applied_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    applied_at = entry.get("last_applied_at") or entry.get("first_applied_at")
    applied_age_days = days_since(applied_at, run_started_at) if applied_at else None
    return {
        "job_key": job_key,
        "title": snapshot.get("title") or entry.get("title") or f"Applied job {job_key}",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "llm_fit_grade": snapshot.get("llm_fit_grade"),
        "fit_source_text": snapshot.get("fit_source_text") or "",
        "full_description": snapshot.get("full_description") or "",
        "fit_confidence": snapshot.get("fit_confidence") or "",
        "details_status": snapshot.get("details_status") or "",
        "description_source": snapshot.get("description_source") or "",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],
        "missing_evidence": snapshot.get("missing_evidence") or [],
        "competitive_signals": snapshot.get("competitive_signals") or [],
        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "first_applied_at": entry.get("first_applied_at"),
        "last_applied_at": entry.get("last_applied_at"),
        "applied_age_days": applied_age_days,
        "applied": True,
    }


def build_applied_records(
    applied_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    records: List[dict] = []
    for job_key in applied_job_keys:
        records.append(build_applied_dashboard_record(job_key, history.get(job_key, {}), run_started_at))

    records.sort(
        key=lambda item: (
            parse_timestamp(item.get("last_applied_at")) or datetime.min,
            parse_timestamp(item.get("last_seen_at")) or datetime.min,
        ),
        reverse=True,
    )
    return records


def build_dashboard_record_sets(
    kept_records: List[dict],
    job_history: Dict[str, dict],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    reference_time: datetime,
    scoring_profile: Optional[dict] = None,
) -> Dict[str, List[dict]]:
    profile = scoring_profile or load_profile()
    curated_kept_records = [record for record in kept_records if is_dashboard_eligible(record, profile)]

    def _rank_by_fit(record: dict) -> tuple:
        return (
            -fit_score(record, profile),
            -(1 if not viewed_by_user(record) else 0),
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
        )

    def _rank_archive_by_fit(record: dict) -> tuple:
        timestamp = parse_timestamp(record.get("last_kept_at"))
        return (
            -fit_score(record, profile),
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(timestamp or datetime.min).timestamp() if timestamp else float("-inf"),
        )

    current_records = sorted(
        curated_kept_records,
        key=_rank_by_fit,
    )
    current_run_keys = {
        normalize_job_key(str(record.get("job_key") or ""))
        for record in curated_kept_records
        if normalize_job_key(str(record.get("job_key") or ""))
    }
    archive_records = build_archive_records(
        job_history,
        current_run_keys,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )
    applied_records = build_applied_records(applied_job_keys, job_history, reference_time)
    hidden_records = build_hidden_records(hidden_job_keys, job_history, reference_time)
    recent_archive_records = sorted(
        [record for record in archive_records if not record.get("is_stale") and is_dashboard_eligible(record, profile)],
        key=_rank_archive_by_fit,
    )
    stale_archive_records = sorted(
        [record for record in archive_records if record.get("is_stale") and is_dashboard_eligible(record, profile)],
        key=_rank_archive_by_fit,
    )
    return {
        "current_records": current_records,
        "archive_records": archive_records,
        "recent_archive_records": recent_archive_records,
        "stale_archive_records": stale_archive_records,
        "applied_records": applied_records,
        "hidden_records": hidden_records,
    }


def render_job_card(record: dict, scoring_profile: Optional[dict] = None, applied_pool: Optional[List[dict]] = None) -> str:
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
    fit_label = score_to_match_label(fit_points)
    fit_tone_class = score_to_tone_class(fit_points)
    score_breakdown = fit_score_breakdown(display_record, scoring_profile)
    visible_reasons = visible_fit_reasons(fit_highlights, score_breakdown, include_values=SHOW_SCORING_DEBUG)
    description_issue = fit_confidence_level == "LOW"
    work_mode = str(display_record.get("work_mode") or "N/A")
    posted_age_days = record.get("posted_age_days")
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
        badges.append(render_badge("Previously Kept", "badge-archive", "This role was kept in an earlier run and carried forward into the dashboard."))
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
        context_bits.append(f"Kept from an earlier run {format_timestamp_label(record.get('last_kept_at'))}")
    context_html = f'<div class="job-context">{safe_html(" | ".join(context_bits))}</div>' if context_bits else ""

    summary_html = (
        f'<p class="job-summary">{safe_html(role_summary)}</p>'
        if role_summary and role_summary != "N/A"
        else ""
    )
    note_bits: List[str] = []
    if description_issue:
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
    insight_sections = []
    if visible_reasons:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Why it fits</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in visible_reasons)}</ul>'
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


def render_section(title: str, records: List[dict], empty_message: str, scoring_profile: Optional[dict] = None, applied_pool: Optional[List[dict]] = None) -> str:
    if not records:
        return (
            f'<section class="section"><h2>{safe_html(title)}</h2>'
            f'<p class="empty-state">{safe_html(empty_message)}</p></section>'
        )
    dom_id = section_dom_id(title)
    cards = "".join(render_job_card(record, scoring_profile, applied_pool=applied_pool) for record in records)
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
    audit_rows = load_json_list(DEBUG_JSON_PATH)
    if not audit_rows:
        return []

    latest_run_started_at = max(
        (str(row.get("run_started_at") or "") for row in audit_rows if row.get("run_started_at")),
        default="",
    )
    if not latest_run_started_at:
        return []

    records = [
        row
        for row in audit_rows
        if row.get("decision") == "KEEP" and str(row.get("run_started_at") or "") == latest_run_started_at
    ]
    return deduplicate_across_sources(records)


def build_run_stats(
    audit_rows: List[dict],
    kept_records: List[dict],
    run_started_at: datetime,
    run_finished_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    max_pages_cap: int,
) -> dict:
    search_targets: Dict[str, Set[int]] = {}
    reject_counts: Dict[str, int] = {}
    skip_counts: Dict[str, int] = {}

    for row in audit_rows:
        search_location = str(row.get("search_location") or "Unknown")
        page_num = row.get("page")
        if page_num is not None:
            search_targets.setdefault(search_location, set()).add(int(page_num))

        reason = row.get("reject_reason") or "UNKNOWN"
        decision = row.get("decision")
        if decision == "SKIP":
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
        elif decision != "KEEP":
            reject_counts[reason] = reject_counts.get(reason, 0) + 1

    top_reject_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(reject_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    detail_fetches = sum(1 for row in audit_rows if int(row.get("details_length") or 0) > 0)
    cards_seen = len(audit_rows)
    kept_count = len(kept_records)

    return {
        "run_started_at": run_started_at.isoformat(timespec="seconds"),
        "run_finished_at": run_finished_at.isoformat(timespec="seconds"),
        "search_window_days": date_range_days,
        "sort_newest_first": sort_newest_first,
        "max_pages_cap": max_pages_cap,
        "search_targets": {
            location: sorted(pages)
            for location, pages in sorted(search_targets.items())
        },
        "page_count": sum(len(pages) for pages in search_targets.values()),
        "cards_seen": cards_seen,
        "detail_fetches": detail_fetches,
        "kept_count": kept_count,
        "keep_rate": round((kept_count / cards_seen), 4) if cards_seen else 0.0,
        "top_reject_reasons": top_reject_reasons,
        "skip_counts": skip_counts,
    }


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
    current_records = dashboard_records["current_records"]
    recent_archive_records = dashboard_records["recent_archive_records"]
    stale_archive_records = dashboard_records["stale_archive_records"]
    applied_records = dashboard_records["applied_records"]
    hidden_records = dashboard_records["hidden_records"]
    potential_records = [*current_records, *recent_archive_records, *stale_archive_records]
    score_filter_options_html = render_score_filter_options(potential_records, scoring_profile)
    posted_filter_options_html = render_posted_filter_options(potential_records)
    shortlist_count = len(current_records) + len(recent_archive_records) + len(stale_archive_records)
    run_label = run_started_at.strftime("%d %b %Y %I:%M %p")
    dashboard_run_id = str(run_stats.get("run_started_at") or run_started_at.isoformat(timespec="seconds"))
    target_summaries = []
    for location, pages in (run_stats.get("search_targets") or {}).items():
        page_label = ", ".join(str(page) for page in pages) if pages else "none"
        target_summaries.append(f"{location}: pages {page_label}")
    testing_mode_notes = []
    if LOW_SCRAPE_MODE:
        testing_mode_notes.append(f"Scrape allow-low mode is on, keeping roles at {score_to_match_label(DASHBOARD_MIN_SCORE)} or better.")
    elif DASHBOARD_DEBUG_MODE:
        testing_mode_notes.append(f"Dashboard debug mode is on, showing scores and keeping roles at {score_to_match_label(DASHBOARD_MIN_SCORE)} or better without a fresh scrape.")
    elif EXPAND_DASHBOARD_MODE:
        testing_mode_notes.append(f"Expanded dashboard view is on, keeping roles at {score_to_match_label(DASHBOARD_MIN_SCORE)} or better without a fresh scrape.")
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
    snapshot_helper = f"Shortlist currently keeps roles at {score_to_match_label(DASHBOARD_MIN_SCORE)} or better and {view_history_text}."
    hero_summary = (
        f"Last run {run_label} - {run_stats.get('cards_seen', 0)} cards scanned, "
        f"{len(current_records)} matches found"
    )
    this_run_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (len(current_records), "Matches"),
            (sum(1 for record in current_records if not viewed_by_user(record)), "New to you"),
            (sum(1 for record in current_records if viewed_by_user(record)), "Opened by you"),
            (len(recent_archive_records), "Previously kept"),
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

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Role Match Dashboard</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf9;
      --card: #fffdfa;
      --ink: #182231;
      --muted: #667085;
      --line: #e9ddcf;
      --accent: #14532d;
      --accent-soft: #e7f7eb;
      --warm: #9a3412;
      --warm-soft: #fff0e6;
      --cool: #1d4ed8;
      --cool-soft: #edf3ff;
      --shadow: 0 16px 38px rgba(45, 34, 20, 0.08);
      --serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      --sans: Aptos, "Trebuchet MS", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--sans);
      background:
        radial-gradient(circle at top left, rgba(20, 83, 45, 0.07), transparent 28%),
        radial-gradient(circle at top right, rgba(154, 52, 18, 0.06), transparent 22%),
        var(--bg);
      color: var(--ink);
    }}
    .page {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 40px 22px 72px;
    }}
    .dashboard-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 330px;
      gap: 36px;
      align-items: start;
    }}
    .dashboard-main {{
      min-width: 0;
    }}
    .dashboard-sidebar {{
      position: sticky;
      top: 24px;
      display: grid;
      gap: 18px;
    }}
    .hero {{
      padding: 2px 2px 24px;
      margin-bottom: 18px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-family: var(--serif);
      font-size: clamp(2.5rem, 4.8vw, 4rem);
      font-weight: 500;
      line-height: 0.96;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
      max-width: 44rem;
      line-height: 1.5;
    }}
    .hero-note {{
      margin-top: 0;
    }}
    .snapshot-rail {{
      background: rgba(255, 253, 249, 0.94);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 22px;
    }}
    .snapshot-section + .snapshot-section {{
      border-top: 1px solid rgba(233, 221, 207, 0.9);
      margin-top: 18px;
      padding-top: 18px;
    }}
    .snapshot-heading {{
      margin: 0 0 14px;
      font-family: var(--serif);
      font-size: 0.98rem;
      font-weight: 500;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #7a5f46;
    }}
    .side-panel {{
      background: rgba(255, 253, 249, 0.9);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .side-panel summary {{
      list-style: none;
      cursor: pointer;
      padding: 14px 16px;
    }}
    .side-panel summary::-webkit-details-marker {{
      display: none;
    }}
    .side-panel[open] summary {{
      border-bottom: 1px solid var(--line);
    }}
    .side-panel-summary-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    .side-panel-title-wrap {{
      min-width: 0;
    }}
    .side-panel-title {{
      display: block;
      font-size: 1rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--ink);
    }}
    .side-panel-subtitle {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 500;
      line-height: 1.35;
    }}
    .side-panel-body {{
      padding: 14px 16px 16px;
    }}
    .side-panel-copy {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .side-panel-copy:last-child {{
      margin-bottom: 0;
    }}
    .side-panel-summary-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .side-toggle-hint {{
      color: var(--cool);
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid rgba(29, 78, 216, 0.12);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    .summary-grid,
    .side-panel-summary-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .summary-card {{
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid rgba(233, 221, 207, 0.8);
      border-radius: 16px;
      padding: 14px 14px 12px;
      min-height: 92px;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .summary-card strong {{
      display: block;
      font-family: var(--serif);
      font-size: 2rem;
      font-weight: 500;
      line-height: 1;
      margin-bottom: 6px;
      letter-spacing: -0.03em;
    }}
    .summary-card span {{
      color: var(--muted);
      font-size: 0.95rem;
      font-weight: 500;
      line-height: 1.25;
    }}
    .summary-card small {{
      display: block;
      margin-top: 3px;
      color: #7b8390;
      font-size: 0.72rem;
      line-height: 1.35;
    }}
    .snapshot-meta {{
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
    }}
    .snapshot-meta-row {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 5px;
      border-bottom: 1px solid rgba(230, 220, 205, 0.65);
    }}
    .snapshot-meta-row:last-child {{
      padding-bottom: 0;
      border-bottom: 0;
    }}
    .snapshot-subheading {{
      margin: 12px 0 8px;
      font-size: 0.8rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      border-bottom: 1px solid rgba(233, 221, 207, 0.5);
      padding-bottom: 4px;
    }}
    .snapshot-meta-label {{
      color: var(--muted);
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .snapshot-meta-value {{
      color: var(--ink);
      font-size: 0.9rem;
      font-weight: 700;
      text-align: right;
      line-height: 1.35;
    }}
    .snapshot-helper {{
      margin: 0 0 12px;
      color: #6b7280;
      font-size: 0.78rem;
      line-height: 1.4;
    }}
    .snapshot-section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .snapshot-section-head .snapshot-heading {{
      margin-bottom: 0;
    }}
    .search-status-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 82px;
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 0.76rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      border: 1px solid transparent;
    }}
    .search-status-pill.is-idle {{
      background: #f3f4f6;
      color: #4b5563;
      border-color: #d1d5db;
    }}
    .search-status-pill.is-running {{
      background: #dcfce7;
      color: #166534;
      border-color: #86efac;
    }}
    .search-settings-readonly .snapshot-meta-value {{
      max-width: 190px;
      text-align: right;
      white-space: normal;
      word-break: break-word;
    }}
    .search-settings-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
      align-items: center;
    }}
    .search-settings-edit {{
      display: grid;
      gap: 12px;
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid rgba(233, 221, 207, 0.9);
    }}
    .search-settings-edit[hidden] {{
      display: none;
    }}
    .search-settings-field {{
      display: grid;
      gap: 6px;
    }}
    .search-settings-field span {{
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .search-settings-field input,
    .search-settings-field textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 11px 12px;
      font: inherit;
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
    }}
    .search-settings-field textarea {{
      min-height: 84px;
      resize: vertical;
    }}
    .search-settings-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .search-settings-checkbox {{
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--ink);
      font-size: 0.9rem;
      font-weight: 600;
    }}
    .search-settings-checkbox input {{
      margin: 0;
      accent-color: var(--accent);
    }}
    .search-button {{
      border: 0;
      border-radius: 999px;
      padding: 10px 15px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .search-button:hover {{
      transform: translateY(-1px);
    }}
    .search-button:active {{
      transform: translateY(0) scale(0.98);
      opacity: 0.9;
    }}
    .search-button[disabled] {{
      opacity: 0.6;
      cursor: progress;
      transform: none;
    }}
    .search-button-secondary {{
      background: white;
      color: var(--cool);
      border: 1px solid rgba(29, 78, 216, 0.16);
    }}
    .search-button-primary {{
      background: var(--accent);
      color: white;
      box-shadow: 0 10px 18px rgba(20, 83, 45, 0.18);
    }}
    .search-settings-message {{
      min-height: 1.2rem;
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .search-settings-message.is-error {{
      color: #991b1b;
    }}
    .section {{
      margin-top: 30px;
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-family: var(--serif);
      font-size: 1.28rem;
      font-weight: 500;
      letter-spacing: 0.02em;
    }}
    .job-grid {{
      display: grid;
      gap: 18px;
    }}
    .job-card {{
      --card-accent: rgba(214, 198, 178, 0.85);
      --card-accent-bg: rgba(214, 198, 178, 0.06);
      background: rgba(255, 253, 250, 0.98);
      border: 1px solid var(--line);
      border-left: 5px solid var(--card-accent);
      border-radius: 24px;
      padding: 20px 22px 18px;
      box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.72);
      background-image: linear-gradient(90deg, var(--card-accent-bg), rgba(255, 253, 250, 0) 34%);
    }}
    .job-card.tone-strong {{
      --card-accent: #16a34a;
      --card-accent-bg: rgba(22, 163, 74, 0.08);
    }}
    .job-card.tone-good {{
      --card-accent: #0f766e;
      --card-accent-bg: rgba(15, 118, 110, 0.08);
    }}
    .job-card.tone-borderline {{
      --card-accent: #d89b00;
      --card-accent-bg: rgba(216, 155, 0, 0.1);
    }}
    .job-card.tone-low {{
      --card-accent: #9ca3af;
      --card-accent-bg: rgba(156, 163, 175, 0.08);
    }}
    .job-card.is-description-issue {{
      --card-accent: #dc2626;
      --card-accent-bg: rgba(220, 38, 38, 0.09);
    }}
    .job-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 11px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: help;
    }}
    .badge-new {{ background: var(--accent-soft); color: var(--accent); text-transform: none; }}
    .badge-potential {{ background: var(--warm-soft); color: var(--warm); }}
    .badge-archive {{ background: #f3e8ff; color: #6b21a8; }}
    .badge-hidden {{ background: #fee2e2; color: #991b1b; }}
    .badge-stale {{ background: #f3f4f6; color: #4b5563; }}
    .badge-viewed {{ background: #fef3c7; color: #92400e; }}
    .badge-source-seek {{ background: #e0f2fe; color: #0c4a6e; }}
    .badge-source-linkedin {{ background: #dbeafe; color: #1e3a5f; }}
    .badge-source-neutral {{ background: #ecfdf3; color: #166534; }}
    .badge-sector-government {{ background: #e0f2fe; color: #0c4a6e; }}
    .badge-channel-recruiter {{ background: #fff1e6; color: #b45309; }}
    .badge-fit-high {{ background: #dcfce7; color: #166534; }}
    .badge-fit-medium {{ background: #fef3c7; color: #92400e; }}
    .badge-fit-borderline {{ background: #e5e7eb; color: #374151; }}
    .badge-warning {{ background: #fee2e2; color: #991b1b; }}
    .filter-panel {{
      background: rgba(255, 253, 249, 0.96);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px 22px;
      box-shadow: var(--shadow);
    }}
    .results-helper {{
      margin-top: 18px;
      background: rgba(255, 252, 246, 0.96);
      border: 1px solid rgba(233, 221, 207, 0.95);
      border-radius: 20px;
      padding: 16px 18px;
      box-shadow: var(--shadow);
      display: flex;
      gap: 14px;
      align-items: flex-start;
      justify-content: space-between;
    }}
    .results-helper[hidden] {{
      display: none !important;
    }}
    .results-helper-copy {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.95rem;
    }}
    .results-helper-dismiss {{
      border: 1px solid rgba(29, 78, 216, 0.18);
      border-radius: 999px;
      background: white;
      color: var(--cool);
      font: inherit;
      font-weight: 700;
      padding: 8px 12px;
      cursor: pointer;
      white-space: nowrap;
    }}
    .filter-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr));
      gap: 12px;
    }}
    .scope-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 0;
    }}
    .scope-tab {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 11px 18px;
      font: inherit;
      font-weight: 700;
      background: rgba(255, 255, 255, 0.82);
      color: var(--ink);
      cursor: pointer;
      transition: transform 120ms ease, border-color 120ms ease, color 120ms ease, box-shadow 120ms ease;
    }}
    .scope-tab:hover {{
      transform: translateY(-1px);
    }}
    .scope-tab:active {{
      transform: translateY(0) scale(0.98);
      opacity: 0.9;
    }}
    .scope-tab.is-active {{
      color: var(--accent);
      border-color: rgba(20, 83, 45, 0.24);
      box-shadow: 0 10px 18px rgba(20, 83, 45, 0.12);
      background: linear-gradient(180deg, #fffefb, #f5fbf6);
    }}
    .workspace-panel[hidden] {{
      display: none !important;
    }}
    .filter-field {{
      display: block;
    }}
    .filter-field span {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 0.83rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .filter-field select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 11px 38px 11px 12px;
      font: inherit;
      line-height: 1.3;
      min-height: 48px;
      background: rgba(255, 255, 255, 0.82);
      color: var(--ink);
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .section-head h2 {{
      margin: 0;
    }}
    .section-tools {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pagination-label {{
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .pagination-button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: white;
      color: var(--cool);
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .pagination-button:hover:not(:disabled) {{
      transform: translateY(-1px);
    }}
    .pagination-button:active:not(:disabled) {{
      transform: translateY(0) scale(0.98);
    }}
    .pagination-button[disabled] {{
      opacity: 0.5;
      cursor: default;
    }}
    .section-copy {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .job-header-row {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 8px;
    }}
    .job-header-copy {{
      min-width: 0;
    }}
    .job-link {{
      display: inline-block;
      color: var(--ink);
      text-decoration: none;
      font-family: var(--serif);
      font-size: 1.6rem;
      font-weight: 500;
      line-height: 1.16;
      margin-bottom: 6px;
    }}
    .job-link:hover {{ text-decoration: underline; }}
    .job-company {{ 
      color: #374151;
      font-size: 1.12rem;
      font-weight: 500;
      margin-top: 4px;
    }}
    .match-tile {{
      min-width: 124px;
      align-self: flex-start;
      border-radius: 18px;
      padding: 12px 14px 11px;
      text-align: center;
      background: #eefbf3;
      display: grid;
      gap: 7px;
    }}
    .match-tile-number {{
      display: block;
      font-family: var(--serif);
      font-size: 2rem;
      line-height: 1;
    }}
    .match-tile-label {{
      display: block;
      font-size: 0.95rem;
      font-weight: 600;
      line-height: 1.2;
    }}
    .match-tile-bar {{
      display: block;
      width: 100%;
      height: 6px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.5);
    }}
    .match-tile-bar-fill {{
      display: block;
      width: var(--match-score, 0%);
      height: 100%;
      border-radius: inherit;
      background: currentColor;
      opacity: 0.72;
    }}
    .tone-strong.match-tile {{
      background: #dbf8e6;
      color: #166534;
    }}
    .tone-good.match-tile {{
      background: #ddf7e2;
      color: #15803d;
    }}
    .tone-borderline.match-tile {{
      background: #fff0bf;
      color: #9a6700;
    }}
    .tone-low.match-tile {{
      background: #f3f4f6;
      color: #7f1d1d;
    }}
    .job-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      margin-bottom: 14px;
    }}
    .job-meta-item {{
      position: relative;
      color: var(--muted);
      font-size: 0.98rem;
      line-height: 1.4;
    }}
    .job-meta-item:not(:last-child)::after {{
      content: "\\2022";
      margin-left: 18px;
      color: #b6a795;
    }}
    .job-meta-item strong {{
      color: #495463;
      font-weight: 600;
    }}
    .chip {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--panel);
      border: 1px solid var(--line);
      font-size: 0.92rem;
    }}
    .chip-score {{
      background: #eefbf3;
      border-color: #ccebd7;
    }}
    .job-summary {{
      margin: 0 0 14px;
      color: var(--ink);
      font-size: 1.02rem;
      line-height: 1.55;
    }}
    .job-note {{
      margin: 0 0 14px;
      border: 1px solid rgba(233, 221, 207, 0.9);
      border-radius: 16px;
      background: rgba(249, 244, 237, 0.72);
      padding: 14px 16px;
      color: #5f6775;
      line-height: 1.55;
    }}
    .job-insights {{
      margin: 0 0 12px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 250, 242, 0.7);
      padding: 0 16px 12px;
    }}
    .job-insights summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--cool);
      padding: 12px 0;
    }}
    .job-insight-group {{
      margin-top: 6px;
    }}
    .job-insight-group strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 0.92rem;
    }}
    .job-insight-group.is-secondary strong {{
      color: var(--muted);
    }}
    .job-insight-group.job-insight-warning strong {{
      color: #991b1b;
    }}
    .job-insight-group.job-insight-muted strong {{
      color: #6b7280;
    }}
    .job-insight-group ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .job-insight-group.is-secondary ul {{
      color: #6b7280;
      font-size: 0.92rem;
    }}
    .job-insight-group li {{
      margin: 4px 0;
    }}
    .job-insight-unavailable strong {{
      color: var(--muted);
    }}
    .insight-unavailable-note {{
      margin: 0;
      color: var(--muted);
      font-size: 0.85rem;
      font-style: italic;
    }}
    .job-context {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}
    .job-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin: 14px 0 10px;
    }}
    .review-button {{
      border: 0;
      border-radius: 999px;
      padding: 9px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .review-button:hover {{
      transform: translateY(-1px);
    }}
    .review-applied {{
      background: var(--accent);
      color: white;
      box-shadow: 0 10px 18px rgba(20, 83, 45, 0.18);
    }}
    .review-not-for-me {{
      background: white;
      color: var(--warm);
      border: 1px solid rgba(154, 52, 18, 0.22);
    }}
    .review-hide {{
      background: #f8fafc;
      color: #475569;
      border: 1px solid #d7dee8;
    }}
    /* Rejection-learning panel */
    .rejection-overlay {{
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.35);
      z-index: 900;
    }}
    .rejection-panel {{
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      z-index: 901;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 12px 36px rgba(0,0,0,0.18);
      width: min(640px, 96vw);
      max-height: 82vh;
      display: flex;
      flex-direction: column;
      font-size: 0.94rem;
    }}
    .rejection-panel[hidden],
    .rejection-overlay[hidden] {{
      display: none;
    }}
    .rejection-panel-header {{
      padding: 18px 22px 12px;
      border-bottom: 1px solid var(--line);
    }}
    .rejection-panel-header h3 {{
      margin: 0 0 4px;
      font-size: 1.08rem;
      color: var(--ink);
    }}
    .rejection-panel-header p {{
      margin: 0;
      font-size: 0.84rem;
      line-height: 1.45;
      color: var(--muted);
    }}
    .rejection-first-use {{
      margin: 12px 22px 0;
      border: 1px solid #dbe7f5;
      border-radius: 12px;
      background: #f8fbff;
      color: #516173;
      overflow: hidden;
    }}
    .rejection-first-use[hidden] {{
      display: none;
    }}
    .rejection-first-use summary {{
      cursor: pointer;
      list-style: none;
      padding: 10px 12px;
      font-size: 0.82rem;
      font-weight: 700;
      color: #35506b;
    }}
    .rejection-first-use summary::-webkit-details-marker {{
      display: none;
    }}
    .rejection-first-use-body {{
      padding: 0 12px 12px;
      font-size: 0.81rem;
      line-height: 1.5;
      color: #516173;
    }}
    .rejection-panel-body {{
      padding: 16px 22px;
      overflow-y: auto;
      flex: 1;
    }}
    .rejection-panel-body.is-loading {{
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      min-height: 80px;
    }}
    .rejection-group {{
      margin-bottom: 12px;
    }}
    .rejection-group-label {{
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 5px;
    }}
    .rejection-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .rejection-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: var(--bg);
      font-size: 0.86rem;
      cursor: pointer;
      user-select: none;
      transition: background 0.12s, border-color 0.12s;
    }}
    .rejection-chip input[type=checkbox] {{
      margin: 0;
      accent-color: var(--accent);
    }}
    .rejection-chip:has(input:checked) {{
      background: #dcfce7;
      border-color: var(--accent);
    }}
    .rejection-other {{
      padding: 12px 22px 14px;
      border-top: 1px solid var(--line);
    }}
    .rejection-other-label {{
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .rejection-other-row {{
      display: flex;
      gap: 6px;
      align-items: center;
    }}
    .rejection-other-row input[type=text] {{
      flex: 1;
      min-width: 0;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      font-size: 0.88rem;
      background: var(--bg);
    }}
    .rejection-other-row button {{
      padding: 8px 14px;
      background: var(--accent);
      color: white;
      border: none;
      border-radius: 7px;
      font-size: 0.84rem;
      font-weight: 700;
      cursor: pointer;
    }}
    .rejection-custom-list {{
      margin-top: 7px;
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }}
    .rejection-custom-chip {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 8px;
      border-radius: 20px;
      background: #dcfce7;
      border: 1px solid var(--accent);
      font-size: 0.8rem;
    }}
    .rejection-custom-chip button {{
      background: none;
      border: none;
      padding: 0;
      cursor: pointer;
      font-size: 0.85rem;
      line-height: 1;
      color: var(--muted);
    }}
    .rejection-panel-footer {{
      padding: 12px 22px 16px;
      border-top: 1px solid var(--line);
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .rejection-btn-save {{
      flex: 1;
      padding: 10px 16px;
      background: var(--accent);
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 0.88rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .rejection-btn-save:not(:disabled):hover {{
      transform: translateY(-1px);
    }}
    .rejection-btn-save:not(:disabled):active {{
      transform: translateY(0) scale(0.98);
    }}
    .rejection-btn-save:disabled {{
      opacity: 0.55;
      cursor: default;
    }}
    .rejection-btn-skip {{
      padding: 10px 16px;
      background: white;
      color: var(--muted);
      border: 1px solid var(--line);
      border-radius: 8px;
      font-size: 0.86rem;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .rejection-btn-skip:hover {{
      transform: translateY(-1px);
    }}
    .rejection-btn-skip:active {{
      transform: translateY(0) scale(0.98);
    }}
    .rejection-btn-cancel {{
      padding: 10px 12px;
      background: none;
      border: none;
      color: var(--muted);
      font-size: 0.86rem;
      cursor: pointer;
    }}
    .rejection-inline-tip {{
      width: 100%;
      margin: -2px 0 0;
      padding: 10px 12px;
      border-radius: 10px;
      background: #f8fafc;
      border: 1px solid #dbe7f5;
      color: #475569;
      font-size: 0.82rem;
      line-height: 1.45;
    }}
    .rejection-inline-tip[hidden] {{
      display: none;
    }}
    .title-block-btn {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      margin-left: 8px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid rgba(29, 78, 216, 0.2);
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 0.76rem;
      font-weight: 700;
      color: var(--cool);
      cursor: pointer;
      vertical-align: middle;
      white-space: nowrap;
      transition: color 0.15s, border-color 0.15s, background 0.15s;
    }}
    .title-block-btn:hover {{
      color: #1d4ed8;
      background: #eff6ff;
      border-color: rgba(29, 78, 216, 0.42);
    }}
    .review-undo,
    .review-unhide {{
      background: var(--cool);
      color: white;
      box-shadow: 0 10px 18px rgba(29, 78, 216, 0.16);
    }}
    .review-button[disabled] {{
      opacity: 0.6;
      cursor: progress;
      transform: none;
    }}
    .review-status {{
      color: var(--muted);
      font-size: 0.9rem;
      min-height: 1.2rem;
    }}
    .block-confirm {{
      margin-top: 8px;
      margin-bottom: 12px;
      border: 1px solid rgba(29, 78, 216, 0.14);
      border-radius: 16px;
      background: rgba(237, 243, 255, 0.75);
      padding: 12px 14px;
      display: grid;
      gap: 8px;
    }}
    .block-confirm[hidden] {{
      display: none;
    }}
    .block-confirm-copy {{
      color: #334155;
      font-size: 0.92rem;
      line-height: 1.45;
      margin: 0;
    }}
    .block-confirm-sub {{
      color: var(--muted);
      font-size: 0.85rem;
      margin: 0;
    }}
    .block-status {{
      display: block;
      font-size: 0.82rem;
      color: var(--muted);
      margin-top: 4px;
    }}
    .block-status:empty {{
      display: none;
    }}
    .block-confirm-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .mini-button {{
      border: 1px solid rgba(29, 78, 216, 0.18);
      border-radius: 999px;
      padding: 8px 12px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: white;
      color: var(--cool);
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .mini-button:hover:not(:disabled) {{
      transform: translateY(-1px);
    }}
    .mini-button:active:not(:disabled) {{
      transform: translateY(0) scale(0.98);
    }}
    .mini-button-primary {{
      background: var(--cool);
      color: white;
      border-color: transparent;
    }}
    .mini-button[disabled] {{
      opacity: 0.6;
      cursor: progress;
    }}
    .block-phrase-checks {{
      display: flex;
      flex-direction: column;
      gap: 5px;
    }}
    .block-phrase-check-row {{
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 0.86rem;
      color: #334155;
      cursor: pointer;
    }}
    .block-empty-suggestion {{
      color: var(--muted);
      font-size: 0.84rem;
    }}
    .block-phrase-checkbox {{
      accent-color: var(--cool);
      width: 15px;
      height: 15px;
      flex-shrink: 0;
    }}
    .block-manual-row {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .block-manual-row[hidden] {{
      display: none;
    }}
    .block-manual-label {{
      font-size: 0.8rem;
      color: var(--muted);
    }}
    .block-manual-help {{
      font-size: 0.78rem;
      color: #64748b;
      line-height: 1.4;
    }}
    .block-manual-input {{
      border: 1px solid rgba(29, 78, 216, 0.2);
      border-radius: 8px;
      padding: 5px 9px;
      font: inherit;
      font-size: 0.84rem;
      outline: none;
      width: 100%;
      box-sizing: border-box;
    }}
    .block-manual-input:focus {{
      border-color: var(--cool);
    }}
    .block-impact {{
      font-size: 0.82rem;
      color: var(--cool);
      margin: 0;
      min-height: 1.2em;
    }}
    .block-admin-tip {{
      font-size: 0.78rem;
      color: var(--muted);
      margin: 0;
    }}
    .block-admin-tip a {{
      color: var(--cool);
    }}
    .job-card.is-reviewed {{
      opacity: 0.55;
    }}
    .empty-state {{
      margin: 0;
      padding: 18px;
      background: var(--card);
      border: 1px dashed var(--line);
      border-radius: 18px;
      color: var(--muted);
    }}
    .toggle-button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 9px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: var(--card);
      color: var(--cool);
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .toggle-button:hover:not(:disabled) {{
      transform: translateY(-1px);
    }}
    .toggle-button:active:not(:disabled) {{
      transform: translateY(0) scale(0.98);
    }}
    .toggle-button[disabled] {{
      opacity: 0.55;
      cursor: default;
    }}
    @media (max-width: 700px) {{
      .page {{ padding: 20px 14px 40px; }}
      .hero {{ padding: 0 0 18px; }}
      .job-card {{ padding: 16px; }}
      .job-link {{ font-size: 1.2rem; }}
      .job-header-row {{ flex-direction: column; }}
      .match-tile {{ min-width: 0; width: 100%; }}
      .summary-grid, .side-panel-summary-grid {{ grid-template-columns: 1fr; }}
      .search-settings-grid {{ grid-template-columns: 1fr; }}
      .search-settings-actions {{ flex-direction: column; }}
    }}
    @media (max-width: 1080px) {{
      .dashboard-layout {{
        grid-template-columns: 1fr;
      }}
      .dashboard-sidebar {{
        position: static;
      }}
      .side-panel-summary-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <div class="dashboard-layout">
      <div class="dashboard-main">
        <section class="hero">
          <h1>Potential Jobs Found</h1>
          <p class="hero-note">Mode: {safe_html(mode_label)}</p>
          <p class="hero-note">{safe_html(hero_summary)}</p>
        </section>
        <section class="section filter-panel">
          <div class="scope-tabs" aria-label="Top-level dashboard views">
            <button class="scope-tab is-active" type="button" data-workspace-target="potential">Potential Jobs ({shortlist_count})</button>
            <button class="scope-tab" type="button" data-workspace-target="applied">Applied ({len(applied_records)})</button>
            <button class="scope-tab" type="button" data-workspace-target="hidden">Hidden ({len(hidden_records)})</button>
          </div>
        </section>
        <div class="workspace-panel" data-workspace-panel="potential">
          <section class="section filter-panel">
            <div class="section-head">
              <h2>Match Controls</h2>
              <button class="mini-button" type="button" id="reset_dashboard_filters">Reset All Filters</button>
            </div>
            <div class="filter-grid">
              <label class="filter-field">
                <span>Sort</span>
                <select id="sort_select">
                  <option value="fit">Best match first</option>
                  <option value="newest">Newest posted first</option>
                  <option value="salary">Highest salary first</option>
                </select>
              </label>
              <label class="filter-field">
                <span>Per page</span>
                <select id="page_size_select">
                  <option value="12">12</option>
                  <option value="24">24</option>
                  <option value="48">48</option>
                  <option value="96">96</option>
                </select>
              </label>
              <label class="filter-field">
                <span>Show</span>
                <select id="scope_filter">
                  <option value="all" selected>All potential jobs</option>
                  <option value="current">Matches this run</option>
                  <option value="saved">Kept from earlier runs</option>
                </select>
              </label>
              <label class="filter-field">
                <span>Posted</span>
                <select id="posted_filter">
                  {posted_filter_options_html}
                </select>
              </label>
              <label class="filter-field">
                <span>Work mode</span>
                <select id="work_mode_filter">
                  <option value="all">Any</option>
                  <option value="remote">Remote</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="on-site">On-site</option>
                </select>
              </label>
              <label class="filter-field">
                <span>Match level</span>
                <select id="score_filter">
                  {score_filter_options_html}
                </select>
              </label>
              <label class="filter-field">
                <span>Salary</span>
                <select id="salary_filter">
                  <option value="all">Any</option>
                  <option value="listed">Any salary shown</option>
                  <option value="meets">Meets my target</option>
                  <option value="below">Below my target</option>
                  <option value="missing">No salary shown</option>
                </select>
              </label>
            </div>
          </section>
          <div class="results-helper" id="results_helper" hidden>
            <p class="results-helper-copy">Job sites often return broad results even when the search is correct. If a title clearly doesn&#8217;t match what you want, you can block similar titles directly from the title. This helps remove repeated noise from future results.</p>
            <button class="results-helper-dismiss" id="dismiss_results_helper" type="button">Dismiss</button>
          </div>
          {render_section("Matches From This Run", current_records, "No kept roles from the latest run right now.", scoring_profile, applied_pool=applied_records)}
          {render_section("Kept From Earlier Runs", recent_archive_records, "No roles from earlier runs are being carried forward right now.", scoring_profile, applied_pool=applied_records)}
          <section class="section job-section" data-section-id="older-saved">
            <div class="section-head">
              <h2>Older Previously Kept Jobs</h2>
              <div class="section-tools">
                <span class="pagination-label"></span>
                <button class="pagination-button" type="button" data-page-direction="prev">Prev</button>
                <button class="pagination-button" type="button" data-page-direction="next">Next</button>
                <button class="toggle-button" type="button" data-toggle-target="older-archive" {'disabled' if not stale_archive_records else ''}>{'Show' if stale_archive_records else 'No'} Older Previously Kept Jobs ({len(stale_archive_records)})</button>
              </div>
            </div>
            <p class="section-copy">Roles kept from earlier runs are collapsed here once they are more than {ARCHIVE_STALE_AFTER_DAYS} days past their last keep, so the dashboard stays focused.</p>
            <div id="older-archive" hidden>
              <div class="job-grid">
                {''.join(render_job_card(record, scoring_profile, applied_pool=applied_records) for record in stale_archive_records)}
              </div>
            </div>
            {'' if stale_archive_records else '<p class="empty-state">No older previously kept roles right now.</p>'}
          </section>
        </div>
        <div class="workspace-panel" data-workspace-panel="applied" hidden>
          <section class="section filter-panel">
            <div class="section-head">
              <h2>Applied Jobs</h2>
            </div>
            <p class="section-copy">This area is for jobs where you have already sent your CV. They are tracked separately so they do not clutter the live shortlist.</p>
          </section>
          {render_section("Applied Jobs", applied_records, "No applied jobs saved yet.", scoring_profile)}
        </div>
        <div class="workspace-panel" data-workspace-panel="hidden" hidden>
          <section class="section filter-panel">
            <div class="section-head">
              <h2>Hidden Jobs</h2>
            </div>
            <p class="section-copy">This area keeps roles you have intentionally pushed out of sight for now.</p>
          </section>
          {render_section("Hidden Jobs", hidden_records, "No hidden jobs right now.", scoring_profile)}
        </div>
      </div>
      <aside class="dashboard-sidebar">
        <section class="snapshot-rail">
          <section class="snapshot-section">
            <h2 class="snapshot-heading">Search Configuration</h2>
            
            <div class="search-settings-group" style="margin-bottom: 16px;">
              <h3 class="snapshot-subheading">Common Settings</h3>
              <div class="snapshot-meta">
                <div class="snapshot-meta-row"><span class="snapshot-meta-label">Keywords</span><span class="snapshot-meta-value" id="search_keywords_current">{safe_html(search_keywords_label)}</span></div>
                <div class="snapshot-meta-row"><span class="snapshot-meta-label">Locations</span><span class="snapshot-meta-value" id="search_locations_current">{safe_html(search_locations_label)}</span></div>
              </div>
            </div>

            <div class="search-settings-group" style="margin-bottom: 16px;">
              <h3 class="snapshot-subheading">SEEK Settings</h3>
              <div class="snapshot-meta">
                <div class="snapshot-meta-row"><span class="snapshot-meta-label">Date window</span><span class="snapshot-meta-value" id="search_date_range_current">{safe_html(str(search_settings_payload["date_range_days"]))} day{"s" if int(search_settings_payload["date_range_days"]) != 1 else ""}</span></div>
                <div class="snapshot-meta-row"><span class="snapshot-meta-label">Pages cap</span><span class="snapshot-meta-value" id="search_max_pages_current">{safe_html(str(search_settings_payload["max_pages_cap"]))}</span></div>
              </div>
            </div>

            <div class="search-settings-group" style="margin-bottom: 16px;">
              <h3 class="snapshot-subheading">LinkedIn Settings</h3>
              <div class="snapshot-meta">
                <div class="snapshot-meta-row"><span class="snapshot-meta-label">Max age</span><span class="snapshot-meta-value" id="search_li_hours_current">{safe_html(str(li_hours))} hours</span></div>
                <div class="snapshot-meta-row"><span class="snapshot-meta-label">Results cap</span><span class="snapshot-meta-value" id="search_li_results_current">{safe_html(str(li_results))}</span></div>
              </div>
            </div>

            <div class="search-settings-actions" style="margin-top: 14px;">
              <button class="search-button search-button-secondary" type="button" id="search_settings_toggle">Edit Configuration</button>
            </div>

            <div class="search-settings-edit" id="search_settings_edit" hidden>
              <div class="search-settings-group" style="margin-top: 14px; border-top: 1px solid var(--line); padding-top: 14px;">
                <h3 class="snapshot-subheading">Common</h3>
                <label class="search-settings-field">
                  <span>Keywords</span>
                  <input type="text" id="search_keywords_input" value="{safe_html(search_settings_payload['keywords'])}" placeholder="Optional keywords">
                </label>
                <label class="search-settings-field">
                  <span>Locations</span>
                  <textarea id="search_locations_input" placeholder="One location per line">{safe_html(search_locations_text)}</textarea>
                </label>
              </div>

              <div class="search-settings-group">
                <h3 class="snapshot-subheading">SEEK</h3>
                <div class="search-settings-grid">
                  <label class="search-settings-field">
                    <span>Date window</span>
                    <input type="number" id="search_date_range_input" min="1" max="30" value="{safe_html(str(search_settings_payload['date_range_days']))}">
                  </label>
                  <label class="search-settings-field">
                    <span>Pages cap</span>
                    <input type="number" id="search_max_pages_input" min="1" max="25" value="{safe_html(str(search_settings_payload['max_pages_cap']))}">
                  </label>
                </div>
              </div>

              <div class="search-settings-group">
                <h3 class="snapshot-subheading">LinkedIn</h3>
                <div class="search-settings-grid">
                  <label class="search-settings-field">
                    <span>Hours old</span>
                    <input type="number" id="search_li_hours_input" min="1" max="168" value="{safe_html(str(li_hours))}">
                  </label>
                  <label class="search-settings-field">
                    <span>Results cap</span>
                    <input type="number" id="search_li_results_input" min="1" max="100" value="{safe_html(str(li_results))}">
                  </label>
                </div>
              </div>
            </div>
          </section>

          <section class="snapshot-section">
            <h2 class="snapshot-heading">Search Operations</h2>
            <div class="search-status-row" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
              <span class="snapshot-meta-label">Status</span>
              <span class="search-status-pill is-idle" id="run_status_pill" title="Background scraper status">Idle</span>
            </div>
            <button class="search-button search-button-primary" style="width: 100%;" type="button" id="run_now_button">Run Search Now</button>
            <div class="search-settings-message" id="search_settings_message" aria-live="polite"></div>
            <p class="snapshot-helper" style="margin-top: 10px;">Daily automation schedule and notification targets are configured in the <a href="/settings" target="_blank">Settings Console</a>.</p>
          </section>
          <section class="snapshot-section">
            <h2 class="snapshot-heading">This Run</h2>
            <div class="summary-grid">
              {this_run_cards_html}
            </div>
          </section>
          <section class="snapshot-section">
            <h2 class="snapshot-heading">Crawler Stats</h2>
            <div class="summary-grid">
              {crawler_cards_html}
            </div>
          </section>
          <section class="snapshot-section">
            <h2 class="snapshot-heading">Applications</h2>
            <div class="summary-grid">
              {application_cards_html}
            </div>
          </section>
        </section>
        <details class="side-panel">
          <summary>
            <span>Run Efficiency</span>
            <span class="side-toggle-hint">Show / hide</span>
          </summary>
          <div class="side-panel-body">
            <p class="side-panel-copy">Search targets this run: {safe_html(" | ".join(target_summaries) or "None")}. {safe_html(snapshot_helper)}{safe_html(testing_mode_note)}</p>
            <div class="job-meta">
              {''.join(f'<span class="chip" title="{safe_html(str(item.get("reason", "UNKNOWN")))}"><strong>{safe_html(humanize_reject_reason(str(item.get("reason", "UNKNOWN"))))}:</strong> {safe_html(str(item.get("count", 0)))}</span>' for item in run_stats.get("top_reject_reasons", []))}
            </div>
          </div>
        </details>
        <details class="side-panel">
          <summary>
            <span>How Match Levels Work</span>
            <span class="side-toggle-hint">Show / hide</span>
          </summary>
          <div class="side-panel-body">
            <p class="side-panel-copy">Match levels are a guide, not a final verdict. The raw score is kept internally for sorting and test mode, while normal mode uses human-friendly bands so the dashboard does not pretend to be more precise than it really is.</p>
            <div class="job-meta">
              <span class="chip"><strong>Strong match:</strong> strongest fit signals</span>
              <span class="chip"><strong>Good match:</strong> clear fit with fewer caveats</span>
              <span class="chip"><strong>Worth a look:</strong> plausible fit worth reviewing</span>
              <span class="chip"><strong>Stretch:</strong> lower-confidence or borderline fit</span>
              <span class="chip"><strong>Title match:</strong> direct titles are favored over adjacent titles</span>
              <span class="chip"><strong>Description review:</strong> stronger description fit lifts the match level</span>
              <span class="chip"><strong>Competitive signals:</strong> specialist bias can lift or lower the match level</span>
              <span class="chip"><strong>Freshness:</strong> newer roles are favored</span>
              <span class="chip"><strong>Decision weights:</strong> fit, pay, location, work mode, contract, government, and freshness can be dialed up or down</span>
              <span class="chip"><strong>Watchouts:</strong> essential gaps hit harder than desirable-only gaps</span>
              <span class="chip"><strong>Risks:</strong> essential gaps hit harder than desirable-only gaps</span>
            </div>
          </div>
        </details>
      </aside>
    </div>
  </main>

  <div class="rejection-overlay" id="rejection-overlay" hidden></div>
  <div class="rejection-panel" id="rejection-panel" hidden>
    <div class="rejection-panel-header">
      <h3 id="rejection-panel-title">Why isn&#39;t this a fit for you?</h3>
      <p>Choose required terms you do not want the app to accept again.</p>
    </div>
    <details class="rejection-first-use" id="rejection-first-use" hidden>
      <summary>How this works</summary>
      <div class="rejection-first-use-body" id="rejection-first-use-body">If you save a term here, future jobs are filtered only when it looks required. To block any mention, use advanced description blockers in Settings.</div>
    </details>
    <div class="rejection-panel-body is-loading" id="rejection-panel-body">Loading suggestions&#8230;</div>
    <div class="rejection-other">
      <div class="rejection-other-label">Add your own required term</div>
      <div class="rejection-other-row">
        <input type="text" id="rejection-other-input" placeholder="e.g. SAP, payroll, NV1 clearance" maxlength="80" />
        <button type="button" id="rejection-other-add">Add</button>
      </div>
      <div class="rejection-custom-list" id="rejection-custom-list"></div>
    </div>
    <div class="rejection-panel-footer">
      <button class="rejection-btn-save" id="rejection-btn-save" disabled type="button">Save &amp; Continue</button>
      <button class="rejection-btn-skip" id="rejection-btn-skip" type="button" hidden>Continue Without Extra Blocks</button>
      <button class="rejection-btn-cancel" id="rejection-btn-cancel" type="button">Cancel</button>
      <p class="block-admin-tip" style="width:100%;text-align:center;margin-top:2px;">View and edit saved rules in the <a href="/settings" target="_blank" rel="noopener">Settings panel</a>.</p>
    </div>
  </div>
    <script>
    const API_BASE_URL = window.location.protocol === 'file:' ? 'http://127.0.0.1:8765' : '';
    const REVIEW_API_URL = `${{API_BASE_URL}}/api/review`;
    const JOB_HISTORY_API_URL = `${{API_BASE_URL}}/api/job-history`;
    const RUN_API_URL = `${{API_BASE_URL}}/api/run`;
    const RUN_STATUS_API_URL = `${{API_BASE_URL}}/api/run-status`;
    const DASHBOARD_RUN_ID = {json.dumps(dashboard_run_id)};
    const LEGACY_DASHBOARD_FILTERS_KEY = 'jobHunter.dashboard.filters';
    const DASHBOARD_FILTERS_KEY = `jobHunter.dashboard.filters.${{DASHBOARD_RUN_ID}}`;
    const INITIAL_SEARCH_SETTINGS = {search_settings_json};
    const RESULTS_HELPER_DISMISSED_KEY = 'jobHunter.dashboard.resultsHelperDismissed';
    const REJECTION_FIRST_USE_KEY = 'jobHunter.dashboard.rejectionFirstUseSeen';
    const sortSelect = document.getElementById('sort_select');
    const pageSizeSelect = document.getElementById('page_size_select');
    const scopeFilter = document.getElementById('scope_filter');
    const postedFilter = document.getElementById('posted_filter');
    const workModeFilter = document.getElementById('work_mode_filter');
    const scoreFilter = document.getElementById('score_filter');
    const salaryFilter = document.getElementById('salary_filter');
    const DEFAULT_SCORE_FILTER_VALUE = {json.dumps(str(DEFAULT_SCORE_FILTER_MIN))};
    const resetFiltersButton = document.getElementById('reset_dashboard_filters');
    const resultsHelper = document.getElementById('results_helper');
    const dismissResultsHelperButton = document.getElementById('dismiss_results_helper');
    const workspaceTabs = Array.from(document.querySelectorAll('[data-workspace-target]'));
    const workspacePanels = Array.from(document.querySelectorAll('[data-workspace-panel]'));
    const searchSettingsToggleButton = document.getElementById('search_settings_toggle');
    const searchSettingsEdit = document.getElementById('search_settings_edit');
    const searchSettingsMessage = document.getElementById('search_settings_message');
    const runNowButton = document.getElementById('run_now_button');
    const runStatusPill = document.getElementById('run_status_pill');
    const searchKeywordsInput = document.getElementById('search_keywords_input');
    const searchLocationsInput = document.getElementById('search_locations_input');
    const searchDateRangeInput = document.getElementById('search_date_range_input');
    const searchMaxPagesInput = document.getElementById('search_max_pages_input');
    const searchKeywordsCurrent = document.getElementById('search_keywords_current');
    const searchLocationsCurrent = document.getElementById('search_locations_current');
    const searchDateRangeCurrent = document.getElementById('search_date_range_current');
    const searchMaxPagesCurrent = document.getElementById('search_max_pages_current');
    const paginationState = {{}};
    let runStatusPollHandle = null;
    let runStatusWasRunning = false;

    function normalizeSearchSettingsInput(settings) {{
      const source = settings && typeof settings === 'object' ? settings : {{}};
      const locations = Array.isArray(source.locations)
        ? source.locations.map(value => String(value || '').trim()).filter(Boolean)
        : [];
      return {{
        keywords: String(source.keywords || '').trim(),
        locations,
        date_range_days: Math.max(1, Math.min(30, Number(source.date_range_days || 3) || 3)),
        max_pages_cap: Math.max(1, Math.min(25, Number(source.max_pages_cap || 10) || 10)),
      }};
    }}

    function setSearchSettingsMessage(message, isError = false) {{
      if (!searchSettingsMessage) {{
        return;
      }}
      searchSettingsMessage.textContent = message || '';
      searchSettingsMessage.classList.toggle('is-error', Boolean(isError && message));
    }}

    function setRunStatusPill(status) {{
      if (!runStatusPill) {{
        return;
      }}
      const isRunning = status === 'running';
      runStatusPill.textContent = isRunning ? 'Running...' : 'Idle';
      runStatusPill.classList.toggle('is-running', isRunning);
      runStatusPill.classList.toggle('is-idle', !isRunning);
    }}

    function renderSearchSettingsReadonly(settings) {{
      const normalized = normalizeSearchSettingsInput(settings);
      if (searchKeywordsCurrent) {{
        searchKeywordsCurrent.textContent = normalized.keywords || 'Not set';
      }}
      if (searchLocationsCurrent) {{
        searchLocationsCurrent.textContent = normalized.locations.length ? normalized.locations.join(' | ') : 'Not set';
      }}
      if (searchDateRangeCurrent) {{
        searchDateRangeCurrent.textContent = `${{normalized.date_range_days}} day${{normalized.date_range_days === 1 ? '' : 's'}}`;
      }}
      if (searchMaxPagesCurrent) {{
        searchMaxPagesCurrent.textContent = String(normalized.max_pages_cap);
      }}
    }}

    function renderSearchSettingsForm(settings) {{
      const normalized = normalizeSearchSettingsInput(settings);
      if (searchKeywordsInput) {{
        searchKeywordsInput.value = normalized.keywords;
      }}
      if (searchLocationsInput) {{
        searchLocationsInput.value = normalized.locations.join('\\n');
      }}
      if (searchDateRangeInput) {{
        searchDateRangeInput.value = String(normalized.date_range_days);
      }}
      if (searchMaxPagesInput) {{
        searchMaxPagesInput.value = String(normalized.max_pages_cap);
      }}
    }}

    function collectSearchSettingsFromForm() {{
      return normalizeSearchSettingsInput({{
        keywords: searchKeywordsInput?.value || '',
        locations: String(searchLocationsInput?.value || '')
          .split(/[\\r\\n]+/)
          .map(value => value.trim())
          .filter(Boolean),
        date_range_days: Number(searchDateRangeInput?.value || 3),
        max_pages_cap: Number(searchMaxPagesInput?.value || 10),
      }});
    }}

    function stopRunStatusPolling() {{
      if (runStatusPollHandle) {{
        window.clearInterval(runStatusPollHandle);
        runStatusPollHandle = null;
      }}
    }}

    function startRunStatusPolling() {{
      if (runStatusPollHandle) {{
        return;
      }}
      runStatusPollHandle = window.setInterval(syncRunStatus, 10000);
    }}

    async function syncRunStatus() {{
      try {{
        const response = await fetch(RUN_STATUS_API_URL, {{ method: 'GET' }});
        if (!response.ok) {{
          throw new Error('Could not check run status.');
        }}
        const payload = await response.json().catch(() => ({{}}));
        const isRunning = payload?.status === 'running';
        setRunStatusPill(isRunning ? 'running' : 'idle');
        if (runNowButton) {{
          runNowButton.disabled = isRunning;
        }}
        if (isRunning) {{
          runStatusWasRunning = true;
          startRunStatusPolling();
          if (!searchSettingsMessage?.textContent) {{
            setSearchSettingsMessage('Scrape in progress. The dashboard will refresh when it finishes.');
          }}
          return;
        }}
        stopRunStatusPolling();
        if (runStatusWasRunning) {{
          runStatusWasRunning = false;
          setSearchSettingsMessage('Scrape finished. Reloading dashboard...');
          window.setTimeout(() => window.location.reload(), 700);
        }}
      }} catch (error) {{
      }}
    }}

    async function runSearchNow() {{
      const searchSettings = collectSearchSettingsFromForm();
      if (runNowButton) {{
        runNowButton.disabled = true;
      }}
      if (searchSettingsToggleButton) {{
        searchSettingsToggleButton.disabled = true;
      }}
      setSearchSettingsMessage('Saving search settings and starting scrape...');

      try {{
        const response = await fetch(RUN_API_URL, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(searchSettings),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.error || 'Could not start scrape.');
        }}

        renderSearchSettingsReadonly(searchSettings);
        setRunStatusPill('running');
        runStatusWasRunning = true;
        startRunStatusPolling();
        if (payload?.status === 'running') {{
          setSearchSettingsMessage('A scrape is already running. The dashboard will reload when it finishes.');
        }} else {{
          setSearchSettingsMessage('Scrape started. The dashboard will reload when it finishes.');
        }}
      }} catch (error) {{
        setRunStatusPill('idle');
        setSearchSettingsMessage(error.message || 'Could not start scrape.', true);
      }} finally {{
        if (searchSettingsToggleButton) {{
          searchSettingsToggleButton.disabled = false;
        }}
        if (runNowButton && !runStatusWasRunning) {{
          runNowButton.disabled = false;
        }}
      }}
    }}

    function showResultsHelperIfNeeded() {{
      if (!resultsHelper) {{
        return;
      }}
      try {{
        if (window.localStorage.getItem(RESULTS_HELPER_DISMISSED_KEY) === '1') {{
          return;
        }}
      }} catch (error) {{
      }}
      resultsHelper.hidden = false;
    }}

    function dismissResultsHelper() {{
      if (resultsHelper) {{
        resultsHelper.hidden = true;
      }}
      try {{
        window.localStorage.setItem(RESULTS_HELPER_DISMISSED_KEY, '1');
      }} catch (error) {{
      }}
    }}

    function updateRejectionFirstUseNote(exampleTerm = '') {{
      const note = document.getElementById('rejection-first-use');
      const body = document.getElementById('rejection-first-use-body');
      if (!note || !body) {{
        return;
      }}
      const example = String(exampleTerm || '').trim() || 'payroll';
      body.textContent = `Example: if you save "${{example}}", future jobs are filtered only when ${{example}} looks required, not when it is just preferred. To block any mention, use advanced description blockers in Settings.`;
      note.hidden = false;
      note.open = true;
      try {{
        if (window.localStorage.getItem(REJECTION_FIRST_USE_KEY) === '1') {{
          note.open = false;
          return;
        }}
        window.localStorage.setItem(REJECTION_FIRST_USE_KEY, '1');
      }} catch (error) {{
      }}
    }}

    function getActiveWorkspace() {{
      return workspaceTabs.find(tab => tab.classList.contains('is-active'))?.dataset.workspaceTarget || 'potential';
    }}

    function setActiveWorkspace(workspace, updateHash = true) {{
      const allowed = new Set(['potential', 'applied', 'hidden']);
      const nextWorkspace = allowed.has(workspace) ? workspace : 'potential';

      for (const tab of workspaceTabs) {{
        tab.classList.toggle('is-active', (tab.dataset.workspaceTarget || '') === nextWorkspace);
      }}
      for (const panel of workspacePanels) {{
        const panelWorkspace = panel.dataset.workspacePanel || 'potential';
        if (panelWorkspace === nextWorkspace) {{
          panel.removeAttribute('hidden');
        }} else {{
          panel.setAttribute('hidden', '');
        }}
      }}

      if (updateHash) {{
        const targetHash = nextWorkspace === 'potential' ? '#potential' : `#${{nextWorkspace}}`;
        if (window.location.hash !== targetHash) {{
          window.history.replaceState(null, '', targetHash);
        }}
      }}

      resetPagination();
      applyDashboardControls();
    }}

    function saveDashboardFilters() {{
      const filters = {{
        sort: sortSelect?.value,
        pageSize: pageSizeSelect?.value,
        scope: scopeFilter?.value,
        posted: postedFilter?.value,
        workMode: workModeFilter?.value,
        score: scoreFilter?.value,
        salary: salaryFilter?.value,
      }};
      try {{
        window.localStorage.setItem(DASHBOARD_FILTERS_KEY, JSON.stringify(filters));
      }} catch (e) {{}}
    }}

    function setSelectValueIfAvailable(select, value) {{
      if (!select || value === undefined || value === null || value === '') {{
        return;
      }}
      const normalized = String(value);
      if (Array.from(select.options).some(option => option.value === normalized)) {{
        select.value = normalized;
      }}
    }}

    function loadDashboardFilters() {{
      try {{
        window.localStorage.removeItem(LEGACY_DASHBOARD_FILTERS_KEY);
        const saved = window.localStorage.getItem(DASHBOARD_FILTERS_KEY);
        if (!saved) return;
        const filters = JSON.parse(saved);
        
        setSelectValueIfAvailable(sortSelect, filters.sort);
        setSelectValueIfAvailable(pageSizeSelect, filters.pageSize);
        setSelectValueIfAvailable(scopeFilter, filters.scope);
        setSelectValueIfAvailable(postedFilter, filters.posted);
        setSelectValueIfAvailable(workModeFilter, filters.workMode);
        setSelectValueIfAvailable(scoreFilter, filters.score);
        setSelectValueIfAvailable(salaryFilter, filters.salary);
      }} catch (e) {{}}
    }}

    function resetDashboardFiltersToDefaults() {{
      if (sortSelect) sortSelect.value = 'fit';
      if (pageSizeSelect) pageSizeSelect.value = '12';
      if (scopeFilter) scopeFilter.value = 'all';
      if (postedFilter) postedFilter.value = 'all';
      if (workModeFilter) workModeFilter.value = 'all';
      if (scoreFilter) {{
        setSelectValueIfAvailable(scoreFilter, DEFAULT_SCORE_FILTER_VALUE);
      }}
      if (salaryFilter) salaryFilter.value = 'all';
      try {{
        window.localStorage.removeItem(DASHBOARD_FILTERS_KEY);
        window.localStorage.removeItem(LEGACY_DASHBOARD_FILTERS_KEY);
      }} catch (e) {{}}
      resetPagination();
      applyDashboardControls();
    }}

    function getVisibleCards() {{
      return Array.from(document.querySelectorAll('.job-card'));
    }}

    function resetPagination() {{
      for (const key of Object.keys(paginationState)) {{
        paginationState[key] = 1;
      }}
    }}

    function applySectionPagination(section) {{
      const grid = section.querySelector('.job-grid');
      if (!grid) {{
        return;
      }}

      const sectionId = section.dataset.sectionId || 'matches';
      const cards = Array.from(grid.querySelectorAll('.job-card'));
      const matchingCards = cards.filter(card => card.dataset.matchesFilters !== '0');
      const pageSize = Number(pageSizeSelect?.value || 12);
      const totalPages = Math.max(Math.ceil(matchingCards.length / pageSize), 1);

      if (!paginationState[sectionId]) {{
        paginationState[sectionId] = 1;
      }}
      paginationState[sectionId] = Math.min(Math.max(paginationState[sectionId], 1), totalPages);

      const currentPage = paginationState[sectionId];
      const startIndex = (currentPage - 1) * pageSize;
      const endIndex = startIndex + pageSize;

      cards.forEach(card => {{
        card.hidden = true;
      }});
      matchingCards.slice(startIndex, endIndex).forEach(card => {{
        card.hidden = false;
      }});

      const label = section.querySelector('.pagination-label');
      if (label) {{
        label.textContent = matchingCards.length
          ? `${{matchingCards.length}} matches | Page ${{currentPage}} of ${{totalPages}}`
          : '0 matches';
      }}

      const prevButton = section.querySelector('[data-page-direction="prev"]');
      const nextButton = section.querySelector('[data-page-direction="next"]');
      if (prevButton) prevButton.disabled = currentPage <= 1 || matchingCards.length === 0;
      if (nextButton) nextButton.disabled = currentPage >= totalPages || matchingCards.length === 0;
    }}

    function applyDashboardControls() {{
      const sortMode = sortSelect?.value || 'fit';
      const scopeMode = scopeFilter?.value || 'all';
      const postedLimit = postedFilter?.value || 'all';
      const workMode = workModeFilter?.value || 'all';
      const scoreMode = scoreFilter?.value || 'all';
      const salaryMode = salaryFilter?.value || 'all';
      const activeWorkspace = getActiveWorkspace();

      for (const card of getVisibleCards()) {{
        const cardScope = card.dataset.recordKind || 'current';
        const viewed = card.dataset.viewed === '1';
        const cardWorkMode = (card.dataset.workMode || '').toLowerCase();
        const cardScore = Number(card.dataset.fitScore || 0);
        const postedAge = Number(card.dataset.postedAge || 9999);
        const salaryState = (card.dataset.salaryFit || 'missing').toLowerCase();

        let visible = true;
        if (card.dataset.reviewDismissed === '1') visible = false;
        if (activeWorkspace === 'potential') {{
          if (!['current', 'saved'].includes(cardScope)) visible = false;
          if (scopeMode === 'current' && cardScope !== 'current') visible = false;
          if (scopeMode === 'saved' && cardScope !== 'saved') visible = false;
          if (scopeMode === 'unseen' && viewed) visible = false;
          if (scopeMode === 'viewed' && !viewed) visible = false;
          if (postedLimit !== 'all' && postedAge > Number(postedLimit)) visible = false;
          if (workMode !== 'all' && cardWorkMode !== workMode) visible = false;
          if (scoreMode !== 'all' && cardScore < Number(scoreMode)) visible = false;
          if (salaryMode === 'listed' && salaryState === 'missing') visible = false;
          if (salaryMode === 'meets' && salaryState !== 'meets') visible = false;
          if (salaryMode === 'below' && salaryState !== 'below') visible = false;
          if (salaryMode === 'missing' && salaryState !== 'missing') visible = false;
        }} else if (activeWorkspace === 'applied') {{
          if (cardScope !== 'applied') visible = false;
        }} else if (activeWorkspace === 'hidden') {{
          if (cardScope !== 'hidden') visible = false;
        }}

        card.dataset.matchesFilters = visible ? '1' : '0';
      }}

      for (const grid of Array.from(document.querySelectorAll('.job-grid'))) {{
        const cards = Array.from(grid.querySelectorAll('.job-card'));
        const originalOrder = [...cards];
        cards.sort((a, b) => {{
          if (sortMode === 'newest') {{
            return Number(a.dataset.postedAge || 9999) - Number(b.dataset.postedAge || 9999);
          }}
          if (sortMode === 'salary') {{
            return Number(b.dataset.salarySort || 0) - Number(a.dataset.salarySort || 0);
          }}
          if (sortMode === 'unseen') {{
            const viewedDiff = Number(a.dataset.viewed || 0) - Number(b.dataset.viewed || 0);
            if (viewedDiff !== 0) return viewedDiff;
          }}
          const fitDiff = Number(b.dataset.fitScore || 0) - Number(a.dataset.fitScore || 0);
          if (fitDiff !== 0) return fitDiff;
          return Number(a.dataset.postedAge || 9999) - Number(b.dataset.postedAge || 9999);
        }});
        for (const card of cards) {{
          grid.appendChild(card);
        }}
        let orderChanged = false;
        for (let i = 0; i < cards.length; i++) {{
          if (cards[i] !== originalOrder[i]) {{
            orderChanged = true;
            break;
          }}
        }}
        if (orderChanged) {{
          for (const card of cards) {{
            grid.appendChild(card);
          }}
        }}
      }}

      for (const section of Array.from(document.querySelectorAll('.job-section'))) {{
        applySectionPagination(section);
      }}
    }}

    function markCardViewed(link) {{
      const card = link.closest('.job-card');
      if (!card) return;
      card.dataset.viewed = '1';
      const badges = card.querySelector('.job-badges');
      const newBadge = badges?.querySelector('.badge-new');
      if (newBadge) {{
        newBadge.remove();
      }}
      if (!card.querySelector('.badge-viewed')) {{
        if (badges) {{
          badges.insertAdjacentHTML('beforeend', {json.dumps(viewed_badge_html())});
        }}
      }}
      applyDashboardControls();
    }}

    async function hydrateViewedState() {{
      try {{
        const response = await fetch(JOB_HISTORY_API_URL, {{ method: 'GET' }});
        if (!response.ok) {{
          return;
        }}
        const payload = await response.json().catch(() => ({{}}));
        const jobs = payload?.jobs || {{}};
        for (const card of getVisibleCards()) {{
          const link = card.querySelector('.job-link');
          const jobKey = link?.dataset.jobKey || '';
          if (!jobKey || !jobs[jobKey] || Number(jobs[jobKey].times_viewed || 0) <= 0) {{
            continue;
          }}
          card.dataset.viewed = '1';
          const badges = card.querySelector('.job-badges');
          const newBadge = badges?.querySelector('.badge-new');
          if (newBadge) {{
            newBadge.remove();
          }}
          if (!card.querySelector('.badge-viewed') && badges) {{
            badges.insertAdjacentHTML('beforeend', {json.dumps(viewed_badge_html())});
          }}
        }}
        applyDashboardControls();
      }} catch (error) {{
      }}
    }}

    function sendViewedBeacon(link) {{
      const payload = JSON.stringify({{
        action: 'viewed',
        job_key: link.dataset.jobKey || '',
        url: link.dataset.jobUrl || '',
        title: link.dataset.jobTitle || '',
      }});

      try {{
        const blob = new Blob([payload], {{ type: 'application/json' }});
        navigator.sendBeacon(REVIEW_API_URL, blob);
      }} catch (error) {{
      }}
    }}

    function hideBlockConfirm(card) {{
      const confirm = card?.querySelector('[data-block-confirm]');
      if (confirm) confirm.hidden = true;
      const blockStatus = card?.querySelector('.block-status');
      if (blockStatus) blockStatus.textContent = '';
    }}

    function escapeRegExp(value) {{
      return String(value || '').replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
    }}

    function dismissCardsByTitlePhrase(phrase) {{
      const normalized = String(phrase || '').trim().toLowerCase();
      if (!normalized) {{
        return;
      }}
      const tokens = normalized.split(/\s+/).filter(Boolean);
      if (!tokens.length) {{
        return;
      }}
      const matcher = new RegExp(`\\\\b${{tokens.map(token => escapeRegExp(token)).join('\\\\s+')}}\\\\b`, 'i');
      for (const card of getVisibleCards()) {{
        const scope = card.dataset.recordKind || 'current';
        if (!['current', 'saved'].includes(scope)) {{
          continue;
        }}
        if (matcher.test(card.dataset.titleSearch || '')) {{
          card.dataset.reviewDismissed = '1';
          card.classList.add('is-reviewed');
        }}
      }}
      applyDashboardControls();
    }}

    function openBlockConfirm(button) {{
      const card = button.closest('.job-card');
      if (!card) return;
      const confirm = card.querySelector('[data-block-confirm]');
      const blockStatus = card.querySelector('.block-status');
      for (const panel of Array.from(document.querySelectorAll('[data-block-confirm]'))) {{
        if (panel !== confirm) panel.hidden = true;
      }}
      for (const s of Array.from(document.querySelectorAll('.block-status'))) {{
        if (s !== blockStatus) s.textContent = '';
      }}
      if (!confirm) return;

      let phrases = [];
      try {{ phrases = JSON.parse(button.dataset.blockPhrases || '[]'); }} catch(e) {{}}
      if (!phrases.length && button.dataset.blockPhrase) phrases = [button.dataset.blockPhrase.trim()].filter(Boolean);

      const checksContainer = confirm.querySelector('[data-block-phrase-checks]');
      const manualInput = confirm.querySelector('[data-block-manual-input]');
      const manualToggle = confirm.querySelector('[data-block-manual-toggle]');
      const manualRow = confirm.querySelector('.block-manual-row');
      const impactEl = confirm.querySelector('[data-block-impact]');
      const confirmButton = confirm.querySelector('[data-confirm-block]');

      if (confirmButton) {{
        confirmButton.dataset.jobKey = button.dataset.jobKey || '';
        confirmButton.dataset.jobUrl = button.dataset.jobUrl || '';
        confirmButton.dataset.jobTitle = button.dataset.jobTitle || '';
        confirmButton.dataset.jobCompany = button.dataset.jobCompany || '';
        confirmButton.dataset.jobTeaser = button.dataset.jobTeaser || '';
      }}

      if (checksContainer) {{
        checksContainer.innerHTML = phrases.length
          ? phrases.map(p =>
              `<label class="block-phrase-check-row"><input class="block-phrase-checkbox" type="checkbox" value="${{p}}" checked> ${{p}}</label>`
            ).join('')
          : '<span class="block-empty-suggestion">Add a phrase below.</span>';
      }}
      if (manualInput) manualInput.value = '';
      if (manualRow) manualRow.hidden = true;
      if (manualToggle) manualToggle.hidden = false;

      function getSelectedPhrases() {{
        const checked = Array.from(
          (checksContainer || document.createElement('div')).querySelectorAll('.block-phrase-checkbox:checked')
        ).map(cb => cb.value.trim()).filter(Boolean);
        const manual = (manualInput ? manualInput.value : '').split(',')
          .map(p => p.trim()).filter(Boolean);
        return [...new Set([...checked, ...manual])];
      }}

      async function updateImpact() {{
        const selected = getSelectedPhrases();
        if (confirmButton) confirmButton.disabled = !selected.length;
        if (!impactEl) return;
        if (!selected.length) {{ impactEl.textContent = ''; return; }}
        impactEl.textContent = 'Checking impact\u2026';
        try {{
          const resp = await fetch(`${{API_BASE_URL}}/api/title-block-preview`, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ phrases: selected }}),
          }});
          if (!resp.ok) {{ impactEl.textContent = ''; return; }}
          const data = await resp.json();
          const total = data.total || 0;
          impactEl.textContent = total > 0
            ? `Would hide ${{total}} visible job${{total === 1 ? '' : 's'}} matching these patterns.`
            : 'No current visible jobs match these patterns.';
        }} catch(e) {{ impactEl.textContent = ''; }}
      }}

      if (checksContainer) {{
        checksContainer.querySelectorAll('.block-phrase-checkbox').forEach(cb => {{
          cb.addEventListener('change', updateImpact);
        }});
      }}
      if (manualInput) manualInput.addEventListener('input', updateImpact);
      if (manualToggle) {{
        manualToggle.onclick = () => {{
          if (manualRow) manualRow.hidden = false;
          manualToggle.hidden = true;
          manualInput?.focus();
        }};
      }}

      updateImpact();
      if (blockStatus) blockStatus.textContent = '';
      confirm.hidden = false;
    }}

    function reviewSavingMessage(action) {{
      if (action === 'applied') return 'Saving as applied...';
      if (action === 'unapply') return 'Removing from applied jobs...';
      if (action === 'hidden') return 'Hiding this job...';
      if (action === 'unhide') return 'Removing from hidden jobs...';
      if (action === 'not_for_me') return 'Saving Not For Me feedback...';
      if (action === 'block_similar') return 'Saving title block...';
      return 'Saving review action...';
    }}

    function reviewSuccessMessage(action, payload) {{
      if (payload?.message) {{
        return payload.message;
      }}
      if (action === 'applied') return 'Saved to Applied jobs. It will be hidden in future runs.';
      if (action === 'unapply') return 'Removed from Applied jobs. It can appear again in future runs.';
      if (action === 'hidden') return 'Hidden. This role moved to Hidden jobs and can be unhidden later.';
      if (action === 'unhide') return 'Removed from Hidden jobs. It can appear again in future runs.';
      if (action === 'not_for_me') return 'Saved as Not For Me. We will learn from this without blocking similar titles yet.';
      if (action === 'block_similar') return 'Saved. Similar jobs will be blocked by title in future runs.';
      return 'Review action saved.';
    }}

    function confirmPossibleRepostBeforeApply(button) {{
      if (button.dataset.reviewAction !== 'applied' || button.dataset.similarAppliedWarning !== '1') {{
        return true;
      }}
      const priorTitle = button.dataset.similarAppliedTitle || button.dataset.jobTitle || 'this role';
      const priorCompany = button.dataset.similarAppliedCompany || button.dataset.jobCompany || '';
      const priorSource = button.dataset.similarAppliedSource || 'another source';
      const companyLabel = priorCompany ? ` at ${{priorCompany}}` : '';
      return window.confirm(
        `You already marked a very similar role as applied: "${{priorTitle}}"${{companyLabel}} from ${{priorSource}}.\n\nContinue marking this one as applied?`
      );
    }}

    async function saveReviewAction(button, extraPayload = {{}}, options = {{}}) {{
      const card = button.closest('.job-card');
      const status = card?.querySelector('.review-status');
      const action = button.dataset.reviewAction || extraPayload.action || '';
      const requestPayload = {{
        action,
        job_key: button.dataset.jobKey || '',
        url: button.dataset.jobUrl || '',
        title: button.dataset.jobTitle || '',
        company: button.dataset.jobCompany || '',
        teaser: button.dataset.jobTeaser || '',
        ...extraPayload,
      }};

      if (!status) {{
        return;
      }}

      const buttons = card.querySelectorAll('button');
      buttons.forEach(item => item.disabled = true);
      status.textContent = reviewSavingMessage(action);

      try {{
        const response = await fetch(REVIEW_API_URL, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(requestPayload)
        }});

        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.error || 'Could not save review action');
        }}

        hideBlockConfirm(card);
        card.classList.add('is-reviewed');
        status.textContent = options.successMessage || reviewSuccessMessage(action, payload);
        window.setTimeout(() => {{
          if (payload?.reload_dashboard || ['applied', 'unapply', 'hidden', 'unhide'].includes(action)) {{
            window.location.reload();
            return;
          }}
          card.dataset.reviewDismissed = '1';
          applyDashboardControls();
          if (action === 'block_similar') {{
            const phrasesToDismiss = payload.block_phrases || (requestPayload.block_phrases) ||
              [(payload.block_phrase || requestPayload.block_phrase || '')];
            phrasesToDismiss.filter(Boolean).forEach(p => dismissCardsByTitlePhrase(p));
          }}
        }}, 700);
      }} catch (error) {{
        buttons.forEach(item => item.disabled = false);
        status.textContent = error.message || 'Could not save review action.';
      }}
    }}

    document.addEventListener('click', async event => {{
      const resetFilters = event.target.closest('#reset_dashboard_filters');
      if (resetFilters) {{
        resetDashboardFiltersToDefaults();
        return;
      }}

      const searchToggle = event.target.closest('#search_settings_toggle');
      if (searchToggle) {{
        if (!searchSettingsEdit) {{
          return;
        }}
        const isHidden = searchSettingsEdit.hasAttribute('hidden');
        if (isHidden) {{
          searchSettingsEdit.removeAttribute('hidden');
          searchToggle.textContent = 'Close';
        }} else {{
          searchSettingsEdit.setAttribute('hidden', '');
          searchToggle.textContent = 'Edit';
        }}
        return;
      }}

      const runNowTrigger = event.target.closest('#run_now_button');
      if (runNowTrigger) {{
        await runSearchNow();
        return;
      }}

      const toggle = event.target.closest('[data-toggle-target]');
      if (toggle) {{
        const target = document.getElementById(toggle.dataset.toggleTarget || '');
        if (!target) {{
          return;
        }}
        const isHidden = target.hasAttribute('hidden');
        if (isHidden) {{
          target.removeAttribute('hidden');
          toggle.textContent = toggle.textContent.replace('Show', 'Hide');
        }} else {{
          target.setAttribute('hidden', '');
          toggle.textContent = toggle.textContent.replace('Hide', 'Show');
        }}
        return;
      }}

      const pageButton = event.target.closest('[data-page-direction]');
      if (pageButton) {{
        const section = pageButton.closest('.job-section');
        if (!section) {{
          return;
        }}
        const sectionId = section.dataset.sectionId || 'matches';
        const delta = pageButton.dataset.pageDirection === 'next' ? 1 : -1;
        paginationState[sectionId] = (paginationState[sectionId] || 1) + delta;
        applySectionPagination(section);
        return;
      }}

      const link = event.target.closest('.job-link');
      if (link) {{
        markCardViewed(link);
        sendViewedBeacon(link);
        return;
      }}

      const dismissHelper = event.target.closest('#dismiss_results_helper');
      if (dismissHelper) {{
        dismissResultsHelper();
        return;
      }}

      const cancelBlock = event.target.closest('[data-cancel-block]');
      if (cancelBlock) {{
        const card = cancelBlock.closest('.job-card');
        hideBlockConfirm(card);
        return;
      }}

      const confirmBlock = event.target.closest('[data-confirm-block]');
      if (confirmBlock) {{
        const blockCard = confirmBlock.closest('.job-card');
        const blockConfirmEl = blockCard?.querySelector('[data-block-confirm]');
        const checksContainer = blockConfirmEl?.querySelector('[data-block-phrase-checks]');
        const manualInput = blockConfirmEl?.querySelector('[data-block-manual-input]');
        const checked = Array.from(
          (checksContainer || document.createElement('div')).querySelectorAll('.block-phrase-checkbox:checked')
        ).map(cb => cb.value.trim()).filter(Boolean);
        const manual = (manualInput ? manualInput.value : '').split(',')
          .map(p => p.trim()).filter(Boolean);
        const blockPhrases = [...new Set([...checked, ...manual])].filter(Boolean);
        await saveReviewAction(confirmBlock, {{
          action: 'block_similar',
          block_phrases: blockPhrases,
          block_phrase: blockPhrases[0] || '',
        }});
        return;
      }}

      const titleBlockBtn = event.target.closest('.title-block-btn');
      if (titleBlockBtn) {{
        openBlockConfirm(titleBlockBtn);
        return;
      }}

      const button = event.target.closest('.review-button');
      if (!button) {{
        const workspaceTab = event.target.closest('[data-workspace-target]');
        if (!workspaceTab) {{
          return;
        }}
        setActiveWorkspace(workspaceTab.dataset.workspaceTarget || 'potential');
        return;
      }}
      hideBlockConfirm(button.closest('.job-card'));
      if (button.dataset.reviewAction === 'not_for_me') {{
        openRejectionPanel(button);
      }} else {{
        if (!confirmPossibleRepostBeforeApply(button)) {{
          const card = button.closest('.job-card');
          const status = card?.querySelector('.review-status');
          if (status) {{
            status.textContent = 'Apply cancelled. This role looks very similar to one already marked as applied.';
          }}
          return;
        }}
        saveReviewAction(button);
      }}
    }});

    for (const control of [sortSelect, pageSizeSelect, scopeFilter, postedFilter, workModeFilter, scoreFilter, salaryFilter]) {{
      control?.addEventListener('change', () => {{
        resetPagination();
        saveDashboardFilters();
        applyDashboardControls();
      }});
    }}

    renderSearchSettingsReadonly(INITIAL_SEARCH_SETTINGS);
    renderSearchSettingsForm(INITIAL_SEARCH_SETTINGS);
    setRunStatusPill('idle');
    loadDashboardFilters();
    syncRunStatus();
    setActiveWorkspace((window.location.hash || '#potential').replace('#', ''), false);
    showResultsHelperIfNeeded();
    hydrateViewedState();
    // Rejection-learning panel
    let _rejectionPendingButton = null;
    let _rejectionCustomTerms = [];
    let _rejectionStage = 'select';
    let _rejectionSavedBlockers = [];
    let _rejectionTitleSuggestions = [];
    let _rejectionDescriptionSuggestions = [];

    const _rejVisibleSuggestionCategories = new Set([
      'other',
    ]);

    function _rejEscapeHtml(value) {{
      return String(value || '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }}[ch]));
    }}

    function _rejResetPanelChrome() {{
      _rejectionStage = 'select';
      _rejectionSavedBlockers = [];
      _rejectionTitleSuggestions = [];
      _rejectionDescriptionSuggestions = [];
      document.getElementById('rejection-btn-save').textContent = 'Save & Continue';
      document.getElementById('rejection-btn-save').disabled = true;
      document.getElementById('rejection-btn-skip').textContent = 'Continue Without Extra Blocks';
      document.getElementById('rejection-btn-skip').setAttribute('hidden', '');
      document.getElementById('rejection-btn-cancel').removeAttribute('hidden');
      document.querySelector('.rejection-other')?.removeAttribute('hidden');
      const headerCopy = document.querySelector('#rejection-panel .rejection-panel-header p');
      if (headerCopy) {{
        headerCopy.textContent = 'Choose required terms you do not want the app to accept again.';
      }}
      const firstUseNote = document.getElementById('rejection-first-use');
      if (firstUseNote) {{
        firstUseNote.hidden = false;
        firstUseNote.open = false;
      }}
    }}

    function openRejectionPanel(button) {{
      _rejectionPendingButton = button;
      _rejectionCustomTerms = [];
      _rejResetPanelChrome();
      const jobTitle = button.dataset.jobTitle || 'this role';
      document.getElementById('rejection-panel-title').textContent =
        `Why isn\u2019t "${{jobTitle}}" a fit for you?`;
      const body = document.getElementById('rejection-panel-body');
      body.className = 'rejection-panel-body is-loading';
      body.textContent = 'Loading suggestions\u2026';
      document.getElementById('rejection-custom-list').innerHTML = '';
      document.getElementById('rejection-other-input').value = '';
      document.getElementById('rejection-panel').removeAttribute('hidden');
      document.getElementById('rejection-overlay').removeAttribute('hidden');
      const jobKey = button.dataset.jobKey || '';
      fetch(`${{API_BASE_URL}}/api/rejection-suggestions?job_id=${{encodeURIComponent(jobKey)}}`)
        .then(r => r.json())
        .catch(() => ({{}}))
        .then(data => _rejRenderSuggestions(data));
    }}

    function _rejSuggestionItems(groups) {{
      const items = [];
      const seen = new Set();
      for (const [cat, terms] of Object.entries(groups || {{}})) {{
        if (!_rejVisibleSuggestionCategories.has(cat)) continue;
        for (const raw of terms || []) {{
          const value = String(raw || '').trim();
          const key = value.toLowerCase();
          if (!value || seen.has(key)) continue;
          seen.add(key);
          items.push({{ value, category: cat }});
        }}
      }}
      return items.slice(0, 12);
    }}

    function _rejCollectSelectedBlockers() {{
      const selected = Array.from(
        document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-value]:checked')
      ).map(cb => String(cb.dataset.value || '').trim()).filter(Boolean);
      const custom = _rejectionCustomTerms.map(item => String(item.value || '').trim()).filter(Boolean);
      const pendingInput = String(document.getElementById('rejection-other-input')?.value || '').trim();
      return [...new Set([...selected, ...custom, ...(pendingInput ? [pendingInput] : [])])];
    }}

    function _rejRenderSuggestions(groups) {{
      const body = document.getElementById('rejection-panel-body');
      body.className = 'rejection-panel-body';
      const items = _rejSuggestionItems(groups);
      updateRejectionFirstUseNote(items[0]?.value || '');
      if (items.length === 0) {{
        body.innerHTML = '<p style="color:var(--muted);font-size:0.85rem;">No strong required terms found. Add one below if this role clearly depends on something you want to avoid.</p>';
        return;
      }}
      const chips = items.map(item => {{
        const escapedValue = _rejEscapeHtml(item.value);
        const escapedCat = _rejEscapeHtml(item.category);
        return `<div class="rejection-chip">` +
          `<label><input type="checkbox" data-value="${{escapedValue}}" data-cat="${{escapedCat}}" /> ${{escapedValue}}</label>` +
          `</div>`;
      }}).join('');
      body.innerHTML =
        `<div class="rejection-group">` +
        `<div class="rejection-group-label">Suggested required terms</div>` +
        `<div class="rejection-chips">${{chips}}</div>` +
        `</div>`;
      body.querySelectorAll('input[type=checkbox]').forEach(cb => {{
        cb.addEventListener('change', _rejUpdateSaveBtn);
      }});
    }}

    function _rejRenderBlockFollowup(payload) {{
      _rejectionStage = 'block_followup';
      _rejectionTitleSuggestions = Array.isArray(payload?.title_block_suggestions) ? payload.title_block_suggestions : [];
      _rejectionDescriptionSuggestions = Array.isArray(payload?.description_block_suggestions) ? payload.description_block_suggestions : [];
      document.querySelector('.rejection-other')?.setAttribute('hidden', '');
      document.getElementById('rejection-btn-save').textContent = 'Apply Extra Blocks';
      document.getElementById('rejection-btn-skip').textContent = 'Continue Without Extra Blocks';
      document.getElementById('rejection-btn-skip').removeAttribute('hidden');
      document.getElementById('rejection-btn-cancel').setAttribute('hidden', '');
      const headerCopy = document.querySelector('#rejection-panel .rejection-panel-header p');
      if (headerCopy) {{
        headerCopy.textContent = 'Optional next step. Only add extra blocks when they are safe to reject without more context.';
      }}
      const firstUseNote = document.getElementById('rejection-first-use');
      if (firstUseNote) {{
        firstUseNote.hidden = true;
      }}
      const body = document.getElementById('rejection-panel-body');
      body.className = 'rejection-panel-body';
      const selectedBlockers = Array.isArray(_rejectionSavedBlockers) ? _rejectionSavedBlockers : [];
      const selectedBlockerKeys = new Set(selectedBlockers.map(item => String(item || '').trim().toLowerCase()).filter(Boolean));
      const directDescriptionCards = selectedBlockers.map(blocker => {{
        const phrase = _rejEscapeHtml(String(blocker || '').trim());
        if (!phrase) return '';
        return `
          <div class="rejection-group">
            <div class="rejection-chip" style="display:flex;align-items:flex-start;width:100%;border-radius:14px;padding:10px 12px;">
              <label style="display:flex;gap:8px;align-items:flex-start;width:100%;cursor:pointer;">
                <input type="checkbox" data-direct-description-followup="1" data-phrase="${{phrase}}" />
                <span>
                  <strong>${{phrase}}</strong><br>
                  <span style="color:var(--muted);font-size:0.8rem;">Reject any future job that mentions this exact phrase anywhere in the description.</span>
                </span>
              </label>
            </div>
          </div>
        `;
      }}).join('');
      const filteredDescriptionSuggestions = _rejectionDescriptionSuggestions.filter(item => {{
        const key = String(item?.phrase || '').trim().toLowerCase();
        return key && !selectedBlockerKeys.has(key);
      }});
      const descriptionCards = _rejectionDescriptionSuggestions.map(item => {{
        const phrase = _rejEscapeHtml(item.phrase || '');
        const rejectedCount = Number(item.matched_rejected_count || 0);
        const rejectedExamples = Array.isArray(item.sample_rejected_titles) ? item.sample_rejected_titles : [];
        const examplesHtml = rejectedExamples.length
          ? `<ul>${{rejectedExamples.map(example => `<li>${{_rejEscapeHtml(example.title || 'Untitled role')}}${{example.company ? ` - ${{_rejEscapeHtml(example.company)}}` : ''}}</li>`).join('')}}</ul>`
          : '<p>No sample roles saved yet.</p>';
        return `
          <div class="rejection-group">
            <div class="rejection-chip" style="display:flex;align-items:flex-start;width:100%;border-radius:14px;padding:10px 12px;">
              <label style="display:flex;gap:8px;align-items:flex-start;width:100%;cursor:pointer;">
                <input type="checkbox" data-description-followup="1" data-phrase="${{phrase}}" />
                <span>
                  <strong>${{phrase}}</strong><br>
                  <span style="color:var(--muted);font-size:0.8rem;">Matched ${{rejectedCount}} rejected description${{rejectedCount === 1 ? '' : 's'}} and no kept roles.</span>
                </span>
              </label>
            </div>
            <div style="margin:6px 0 0 26px;color:var(--muted);font-size:0.82rem;">
              <strong style="color:var(--ink);font-size:0.82rem;">Examples</strong>
              ${{examplesHtml}}
            </div>
          </div>
        `;
      }}).join('');
      const titleCards = _rejectionTitleSuggestions.map(item => {{
        const phrase = _rejEscapeHtml(item.phrase || '');
        const rejectedCount = Number(item.matched_rejected_count || 0);
        const rejectedExamples = Array.isArray(item.sample_rejected_titles) ? item.sample_rejected_titles : [];
        const examplesHtml = rejectedExamples.length
          ? `<ul>${{rejectedExamples.map(example => `<li>${{_rejEscapeHtml(example.title || 'Untitled role')}}${{example.company ? ` - ${{_rejEscapeHtml(example.company)}}` : ''}}</li>`).join('')}}</ul>`
          : '<p>No sample titles saved yet.</p>';
        return `
          <div class="rejection-group">
            <div class="rejection-chip" style="display:flex;align-items:flex-start;width:100%;border-radius:14px;padding:10px 12px;">
              <label style="display:flex;gap:8px;align-items:flex-start;width:100%;cursor:pointer;">
                <input type="checkbox" data-title-followup="1" data-phrase="${{phrase}}" />
                <span>
                  <strong>${{phrase}}</strong><br>
                  <span style="color:var(--muted);font-size:0.8rem;">Matched ${{rejectedCount}} rejected title${{rejectedCount === 1 ? '' : 's'}} and no kept titles.</span>
                </span>
              </label>
            </div>
            <div style="margin:6px 0 0 26px;color:var(--muted);font-size:0.82rem;">
              <strong style="color:var(--ink);font-size:0.82rem;">Examples</strong>
              ${{examplesHtml}}
            </div>
          </div>
        `;
      }}).join('');
      const sections = [];
      if (directDescriptionCards) {{
        sections.push(
          `<div class="rejection-group">` +
          `<div class="rejection-group-label">Always reject exact phrase</div>` +
          `<p style="margin:0 0 10px;color:var(--muted);font-size:0.84rem;">Use this only when any mention should reject the job, even if the term is not framed as a requirement.</p>` +
          `${{directDescriptionCards}}` +
          `</div>`
        );
      }}
      if (descriptionCards) {{
        sections.push(
          `<div class="rejection-group">` +
          `<div class="rejection-group-label">Optional hard description blocks</div>` +
          `<p style="margin:0 0 10px;color:var(--muted);font-size:0.84rem;">These phrases only appeared in rejected descriptions, so they can be blocked anywhere in future job descriptions.</p>` +
          `${{descriptionCards}}` +
          `</div>`
        );
      }}
      if (titleCards) {{
        sections.push(
          `<div class="rejection-group">` +
          `<div class="rejection-group-label">Optional title blocks</div>` +
          `<p style="margin:0 0 10px;color:var(--muted);font-size:0.84rem;">These terms also look strong enough to block at the title level before the app reads the description.</p>` +
          `${{titleCards}}` +
          `</div>`
        );
      }}
      body.innerHTML = sections.join('');
      body.querySelectorAll('input[type=checkbox][data-title-followup], input[type=checkbox][data-description-followup], input[type=checkbox][data-direct-description-followup]').forEach(cb => {{
        cb.addEventListener('change', _rejUpdateSaveBtn);
      }});
      _rejUpdateSaveBtn();
    }}

    function _rejUpdateSaveBtn() {{
      if (_rejectionStage === 'block_followup') {{
        const anyChecked = document.querySelector('#rejection-panel-body input[type=checkbox][data-title-followup]:checked, #rejection-panel-body input[type=checkbox][data-description-followup]:checked, #rejection-panel-body input[type=checkbox][data-direct-description-followup]:checked');
        document.getElementById('rejection-btn-save').disabled = !anyChecked;
        return;
      }}
      const anyChecked = document.querySelector('#rejection-panel-body input[type=checkbox][data-value]:checked');
      document.getElementById('rejection-btn-save').disabled =
        !anyChecked && _rejectionCustomTerms.length === 0;
    }}

    function closeRejectionPanel() {{
      document.getElementById('rejection-panel').setAttribute('hidden', '');
      document.getElementById('rejection-overlay').setAttribute('hidden', '');
      _rejectionPendingButton = null;
      _rejectionCustomTerms = [];
      _rejResetPanelChrome();
    }}

    async function _rejPersistMandatoryBlockers(blockers, titleBlockPhrases = [], descriptionBlockPhrases = []) {{
      const button = _rejectionPendingButton;
      const response = await fetch(`${{API_BASE_URL}}/api/rejection-feedback/mandatory-blockers`, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          job_id: button?.dataset.jobKey || '',
          job_title: button?.dataset.jobTitle || '',
          url: button?.dataset.jobUrl || '',
          company: button?.dataset.jobCompany || '',
          teaser: button?.dataset.jobTeaser || '',
          blockers,
          title_block_phrases: titleBlockPhrases,
          description_block_phrases: descriptionBlockPhrases,
        }}),
      }});
      const payload = await response.json().catch(() => ({{}}));
      if (!response.ok) {{
        throw new Error(payload.error || 'Could not save blockers');
      }}
      return payload;
    }}

    async function _rejCompleteReview(result, titleBlockPhrases = [], descriptionBlockPhrases = []) {{
      const button = _rejectionPendingButton;
      const successMessage = result?.message || 'Saved blocker feedback.';
      closeRejectionPanel();
      titleBlockPhrases.filter(Boolean).forEach(phrase => dismissCardsByTitlePhrase(phrase));
      if (button) {{
        await saveReviewAction(button, {{}}, {{ successMessage }});
      }}
    }}

    async function _rejSaveAndContinue() {{
      const saveButton = document.getElementById('rejection-btn-save');
      const originalLabel = saveButton.textContent;
      saveButton.disabled = true;
      saveButton.textContent = _rejectionStage === 'block_followup' ? 'Saving…' : 'Saving blockers…';
      try {{
        if (_rejectionStage === 'block_followup') {{
          const selectedTitlePhrases = Array.from(
            document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-title-followup]:checked')
          ).map(cb => String(cb.dataset.phrase || '').trim()).filter(Boolean);
          const selectedDescriptionPhrases = Array.from(
            document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-direct-description-followup]:checked')
          ).map(cb => String(cb.dataset.phrase || '').trim()).filter(Boolean);
          const suggestedDescriptionPhrases = Array.from(
            document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-description-followup]:checked')
          ).map(cb => String(cb.dataset.phrase || '').trim()).filter(Boolean);
          const allDescriptionPhrases = [...new Set([...selectedDescriptionPhrases, ...suggestedDescriptionPhrases])];
          const result = await _rejPersistMandatoryBlockers(
            _rejectionSavedBlockers,
            selectedTitlePhrases,
            allDescriptionPhrases,
          );
          await _rejCompleteReview(
            result,
            result?.applied_title_block_phrases || selectedTitlePhrases,
            result?.applied_description_block_phrases || allDescriptionPhrases,
          );
          return;
        }}

        const blockers = _rejCollectSelectedBlockers();
        if (!blockers.length) {{
          return;
        }}
        _rejectionSavedBlockers = blockers;
        const result = await _rejPersistMandatoryBlockers(blockers);
        const hasFollowups =
          blockers.length > 0 ||
          (Array.isArray(result?.title_block_suggestions) && result.title_block_suggestions.length) ||
          (Array.isArray(result?.description_block_suggestions) && result.description_block_suggestions.length);
        if (hasFollowups) {{
          _rejRenderBlockFollowup(result);
          return;
        }}
        await _rejCompleteReview(result);
      }} catch (error) {{
        saveButton.disabled = false;
        saveButton.textContent = originalLabel;
        const body = document.getElementById('rejection-panel-body');
        if (body && !body.classList.contains('is-loading')) {{
          body.insertAdjacentHTML(
            'afterbegin',
            `<p style="margin:0 0 10px;color:#b91c1c;font-size:0.84rem;">${{_rejEscapeHtml(error.message || 'Could not save blockers.')}}</p>`
          );
        }}
        return;
      }}
      saveButton.textContent = originalLabel;
    }}

    function _rejRenderCustomChips() {{
      const list = document.getElementById('rejection-custom-list');
      list.innerHTML = _rejectionCustomTerms.map((t, i) => {{
        const value = _rejEscapeHtml(t.value);
        return `<span class="rejection-custom-chip">${{value}}` +
          `<button type="button" data-idx="${{i}}" aria-label="Remove">&times;</button></span>`;
      }}).join('');
      list.querySelectorAll('button').forEach(btn => {{
        btn.addEventListener('click', () => {{
          _rejectionCustomTerms.splice(+btn.dataset.idx, 1);
          _rejRenderCustomChips();
          _rejUpdateSaveBtn();
        }});
      }});
    }}

    document.getElementById('rejection-other-add').addEventListener('click', () => {{
      if (_rejectionStage !== 'select') return;
      const input = document.getElementById('rejection-other-input');
      const cat = 'other';
      const val = input.value.trim();
      if (!val || val.length < 2) return;
      _rejectionCustomTerms.push({{ value: val, category: cat }});
      input.value = '';
      _rejRenderCustomChips();
      _rejUpdateSaveBtn();
    }});

    document.getElementById('rejection-other-input').addEventListener('keydown', e => {{
      if (e.key === 'Enter') document.getElementById('rejection-other-add').click();
    }});

    document.getElementById('rejection-btn-save').addEventListener('click', _rejSaveAndContinue);

    document.getElementById('rejection-btn-skip').addEventListener('click', () => {{
      if (_rejectionStage === 'block_followup') {{
        _rejCompleteReview({{
          message: 'Saved blocker feedback without adding extra blocks.',
        }}).catch(() => {{}});
      }}
    }});

    document.getElementById('rejection-btn-cancel').addEventListener('click', () => {{
      const card = _rejectionPendingButton?.closest('.job-card');
      if (card) {{ card.querySelectorAll('button').forEach(b => b.disabled = false); }}
      closeRejectionPanel();
    }});

    document.getElementById('rejection-overlay').addEventListener('click', () => {{
      document.getElementById('rejection-btn-cancel').click();
    }});
    // end rejection-learning panel
  </script>
</body>
</html>
"""
    output_file = Path(output_path)
    if not output_file.is_absolute():
        output_file = ROOT_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")


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
                        title = ""
                        company = "N/A"
                        record = {
                            "run_started_at": run_iso,
                            "search_location": search_location,
                            "search_keywords": search_keywords,
                            "search_classifications": classification_ids,
                            "page": current_page_num,
                            "source": "seek",
                            "job_key": None,
                            "title": "",
                            "company": company,
                            "posted": "N/A",
                            "posted_age_days": None,
                            "url": None,
                            "salary": "N/A",
                            "location": "N/A",
                            "work_mode": "N/A",
                            "work_type": "N/A",
                            "teaser": "N/A",
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
                            "details_length": 0,
                        }

                        try:
                            title_el = card.query_selector(SELECTOR_TITLE)
                            company_el = card.query_selector(SELECTOR_COMPANY)
                            posted_el = card.query_selector(SELECTOR_POSTED)
                            card_meta = extract_card_metadata(card)
                            card_text = (card.inner_text() or "").strip()

                            title = title_el.inner_text().strip() if title_el else ""
                            company = company_el.inner_text().strip() if company_el else "N/A"
                            posted = posted_el.inner_text().strip() if posted_el else ""
                            if not posted:
                                posted = extract_posted_text_from_card(card_text)
                            posted = normalize_posted_text(posted)
                            posted_age_days = parse_seek_posted_age_days(posted)
                            record.update({
                                "title": title,
                                "company": company,
                                "posted": posted,
                                "posted_age_days": posted_age_days,
                                "location": card_meta["location"],
                                "work_mode": card_meta["work_mode"],
                                "work_type": card_meta["work_type"],
                                "teaser": card_meta["teaser"],
                            })

                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            ok_title, title_reason = passes_title_filters(title)
                            record["title_reason"] = title_reason
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                record["reject_reason"] = title_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            relative_url = title_el.get_attribute("href") if title_el else None
                            full_url = build_full_seek_url(relative_url)
                            record["url"] = full_url
                            record["job_key"] = stable_job_key(full_url)
                            if not full_url:
                                print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                                record["reject_reason"] = "NO_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["job_key"] in applied_job_keys:
                                print(f"SKIP (applied) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "ALREADY_APPLIED"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["job_key"] in hidden_job_keys:
                                print(f"SKIP (hidden) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "MANUALLY_HIDDEN"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if (
                                enforce_posted_age_limit
                                and posted_age_days is not None
                                and posted_age_days > configured_date_range
                            ):
                                print(
                                    f"REJECTED (posted) [POSTED_TOO_OLD:{configured_date_range}] "
                                    f"{title} @ {company} | {posted}"
                                )
                                record["reject_reason"] = f"POSTED_TOO_OLD:{configured_date_range}"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if full_url in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "DUPLICATE_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(full_url)

                            if not SKIP_QUICK_CARD_GATE_FOR_TESTING:
                                ok_card, card_reason = passes_quick_card_filters(
                                    title=title,
                                    teaser=card_meta["teaser"],
                                    company=company,
                                    location=record["location"],
                                    work_mode=record["work_mode"],
                                    work_type=record["work_type"],
                                    salary=card_meta["card_salary"],
                                )
                                if not ok_card:
                                    print(f"REJECTED (card gate) [{card_reason}] {title} @ {company}")
                                    record["reject_reason"] = card_reason
                                    finalize_record(job_history, audit_rows, record, run_iso)
                                    continue

                            history_entry = job_history.get(record["job_key"] or "", {})
                            if can_reuse_kept_job(history_entry, record, profile):
                                record = apply_kept_job_reuse(record, history_entry)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                kept_records.append(record)
                                print(
                                    f"KEPT (history reuse): {title} @ {company} | {posted} | "
                                    f"{record['location']} | {record['work_type']} | {record['salary']}"
                                )
                                continue

                            details_payload = fetch_job_details_payload(detail_page, full_url)
                            details_text = str(details_payload.get("text") or "")
                            details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))
                            record["details_status"] = details_status
                            record["details_length"] = len(details_text)
                            if details_status != "ok" or not details_text:
                                reject_reason = {
                                    "challenge_page": "DETAILS_CHALLENGE_PAGE",
                                    "blocked_page": "DETAILS_BLOCKED_PAGE",
                                    "navigation_error": "DETAILS_NAVIGATION_ERROR",
                                    "empty": "NO_DETAILS",
                                }.get(details_status, "NO_DETAILS")
                                print(f"REJECTED (details) [{reject_reason}] {title} @ {company} | {full_url}")
                                record["reject_reason"] = reject_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            record["fit_source_text"] = details_text
                            record["full_description"] = details_text
                            record["description_source"] = details_payload.get("source") or "jobAdDetails"
                            source = str(record.get("description_source") or "").strip().lower()
                            is_trusted = source in TRUSTED_DESCRIPTION_SOURCES and len(details_text) >= MIN_TRUSTED_DESCRIPTION_LENGTH
                            record["fit_confidence"] = "HIGH" if is_trusted else "LOW"

                            ok_desc, desc_reason = passes_content_filters(
                                details_text,
                                record["location"],
                                record.get("title_reason", ""),
                            )
                            record["content_reason"] = desc_reason
                            if not ok_desc:
                                print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
                                record["reject_reason"] = desc_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            ok_learned, learned_reason = passes_saved_rejection_rules(details_text)
                            if not ok_learned:
                                record["content_reason"] = learned_reason
                                record["reject_reason"] = learned_reason
                                print(f"REJECTED (learned rule) [{learned_reason}] {title} @ {company}")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            record["competitive_signals"] = [
                                evaluate_competitive_signal_alignment(signal, profile)
                                for signal in detect_competitive_signals(details_text, profile)
                            ]
                            hard_block_matches = hard_block_entries(
                                {
                                    "fit_source_text": details_text,
                                    "competitive_signals": record.get("competitive_signals"),
                                },
                                profile,
                            )
                            record["hard_block_reasons"] = [entry["text"] for entry in hard_block_matches]
                            if record["hard_block_reasons"]:
                                hard_block_category = hard_block_matches[0].get("category") or "hard_block"
                                record["content_reason"] = f"DESC_HARD_BLOCK:{hard_block_category}"
                                record["reject_reason"] = record["content_reason"]
                                print(
                                    f"REJECTED (hard block) [{record['content_reason']}] {title} @ {company} | "
                                    f"{'; '.join(record['hard_block_reasons'])}"
                                )
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            salary = extract_salary(details_text)
                            if salary == "N/A":
                                salary = card_meta["card_salary"]
                            record["salary"] = salary
                            detail_work_mode = extract_work_mode(details_text)
                            if detail_work_mode != "N/A":
                                record["work_mode"] = detail_work_mode
                            record["role_snapshot"] = build_role_summary(record, details_text, profile)
                            record["fit_highlights"] = build_fit_highlights(record, details_text, profile)
                            record["soft_risk_reasons"], record["missing_evidence"] = build_risk_and_missing_evidence(
                                details_text,
                                title_reason,
                                profile,
                                competitive_signals=record.get("competitive_signals") if isinstance(record.get("competitive_signals"), list) else None,
                            )

                            deterministic_review = deterministic_review_outcome(
                                record,
                                record["fit_highlights"],
                                record["missing_evidence"],
                                record["soft_risk_reasons"],
                            )
                            if deterministic_review is not None:
                                llm_review = deterministic_review
                                review_source = "rule"
                                print(f"[REVIEW][RULE] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                            else:
                                llm_input_text = details_text[:MAX_LLM_CHARS]
                                llm_fp = build_llm_cache_key(llm_input_text)

                                if NO_LLM_MODE:
                                    llm_review = normalize_llm_review(None)
                                    review_source = "no_llm_flag"
                                    print(f"[REVIEW][NO_LLM_FLAG] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                                elif not llm_is_enabled():
                                    llm_review = normalize_llm_review(None)
                                    review_source = "disabled"
                                    print(f"[REVIEW][DISABLED] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                                elif llm_fp in llm_cache:
                                    llm_review = normalize_llm_review(llm_cache[llm_fp])
                                    review_source = "cache"
                                    print(f"[REVIEW][CACHE] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                                else:
                                    llm_review = normalize_llm_review(llm_should_consider(llm_input_text))
                                    llm_cache[llm_fp] = llm_review
                                    review_source = "llm"
                                    print(f"[REVIEW][LLM] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")

                            record["llm_decision"] = llm_review["decision"]
                            record["llm_fit_grade"] = llm_review["grade"]
                            record["review_source"] = review_source
                            if SHOW_SCORES_MODE:
                                test_score_breakdown = fit_score_breakdown(record, profile)
                                print(
                                    f"[TEST][SCORE] {title} @ {company} | "
                                    f"{fit_score(record, profile)}/100 | "
                                    f"{format_score_breakdown_for_console(test_score_breakdown)}"
                                )
                            if review_source == "rule" and llm_review["decision"] == "REJECT":
                                print(f"REJECTED (deterministic) [DET_REJECT] {title} @ {company}")
                                record["reject_reason"] = "DET_REJECT"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            record["decision"] = "KEEP"

                            finalize_record(job_history, audit_rows, record, run_iso)
                            kept_records.append(record)
                            print(
                                f"KEPT: {title} @ {company} | {posted} | "
                                f"{record['location']} | {record['work_type']} | {salary} | "
                                f"{'SEEN_BEFORE' if record.get('seen_before') else 'NEW'}"
                            )
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
