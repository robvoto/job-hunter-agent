"""Current direct-page job-source connector and dashboard builder.

Main goals:
- fetch current job listings from the active source implementation
- apply deterministic filtering and optional LLM fit review
- persist audit data, run stats, review insights, and dashboard HTML

Notes:
- this filename is historical; in product and documentation language we prefer
  "source connector" over "scraper"
- the current implementation is SEEK-specific, but the normalized record shape
  is intended to be reusable for additional sources later
"""

import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from config import MAX_PAGES_CAP, OUTPUT_HTML, SEEK_URL
from filters import passes_content_filters, passes_quick_card_filters, passes_title_filters
from llm_gate import build_llm_cache_key, llm_is_enabled, llm_should_consider, normalize_llm_review
from profile_store import (
    get_evidence_tier_weights,
    get_evidence_tiers,
    get_preference_weights,
    get_search_settings,
    load_profile,
)
from review_insights import build_review_data, extract_detected_skills
from scraper_seek import (
    SELECTOR_CARDS,
    SELECTOR_COMPANY,
    SELECTOR_POSTED,
    SELECTOR_TITLE,
    build_seek_search_targets,
    extract_card_metadata,
    extract_posted_text_from_card,
    fetch_job_details_payload,
    stable_job_key,
)
from utils import (
    extract_salary,
    extract_work_mode,
    parse_seek_posted_age_days,
    safe_html,
    set_page_param,
)


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
MAX_LLM_CHARS = 3000
ARCHIVE_STALE_AFTER_DAYS = 15
HIDDEN_REVIEW_DAYS = 30
AUTO_REFRESH_SECONDS = 60
CLI_FLAGS = set(sys.argv[1:])
TEST_DASHBOARD_MODE = "--test-dashboard-mode" in CLI_FLAGS
TEST_SCRAPE_MODE = "--test-scrape-mode" in CLI_FLAGS
TEST_ANY_MODE = TEST_DASHBOARD_MODE or TEST_SCRAPE_MODE
TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING = (
    "--reset-new-to-you" in CLI_FLAGS or TEST_ANY_MODE
)
SKIP_QUICK_CARD_GATE_FOR_TESTING = TEST_SCRAPE_MODE
TEST_SCRAPE_DATE_RANGE_DAYS = 7
TEST_SCRAPE_MAX_PAGES_CAP = 6
SHOW_SCORING_DEBUG = TEST_ANY_MODE
SHOW_BORDERLINE_BY_DEFAULT = TEST_ANY_MODE
DASHBOARD_MIN_SCORE = 35 if TEST_ANY_MODE else 50
DEFAULT_SCORE_FILTER_MIN = 35 if TEST_ANY_MODE else (50 if SHOW_BORDERLINE_BY_DEFAULT else 65)
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
DEBUG_JSON_PATH = OUTPUT_DIR / "seek_results.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
RUN_STATS_PATH = OUTPUT_DIR / "seek_run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "seek_review_data.json"
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
    "details_status",
    "role_snapshot",
    "fit_highlights",
    "fit_watchouts",
    "fit_watchout_meta",
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

    For '$450 - $700 per day' returns 700; for '$130k–$145k p.a.' returns 145000.
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


def build_full_url(relative_or_full_url: Optional[str]) -> Optional[str]:
    if not relative_or_full_url:
        return None
    return urljoin("https://www.seek.com.au", relative_or_full_url)


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
        cleaned = compact_whitespace(raw_line.strip(" -•\t"))
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
        "must be based in australia",
        "full working rights",
    )
    return any(phrase in lowered for phrase in generic_phrases)


def score_summary_snippet(snippet: str) -> int:
    lowered = snippet.lower()
    score = 0
    summary_keywords = (
        "looking for",
        "seeking",
        "you will",
        "responsible for",
        "lead",
        "deliver",
        "support",
        "requirements",
        "stakeholder",
        "workshop",
        "process",
        "integration",
        "data",
        "implementation",
    )
    score += sum(2 for keyword in summary_keywords if keyword in lowered)
    if len(snippet) < 60:
        score -= 1
    if _is_generic_summary_text(snippet):
        score -= 3
    if re.search(r"\$\d", lowered):
        score -= 2
    return score


def synthesize_role_snapshot(record: dict) -> str:
    title = compact_whitespace(record.get("title") or "")
    location = compact_whitespace(record.get("location") or "")
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


def build_role_snapshot(details_text: str, teaser: Optional[str]) -> str:
    teaser_text = compact_whitespace(teaser)
    detail_snippets = split_text_snippets(details_text)
    if teaser_text and teaser_text.lower() != "n/a" and not _is_generic_summary_text(teaser_text):
        if len(teaser_text) <= 240:
            return teaser_text
    if detail_snippets:
        ranked = sorted(
            detail_snippets,
            key=lambda item: (-score_summary_snippet(item), len(item)),
        )
        best = ranked[0]
        if len(best) <= 260:
            return best
        return best[:257].rstrip() + "..."
    return teaser_text or "Role summary not available."


def summarize_snippet(snippet: str, max_length: int = 180) -> str:
    cleaned = compact_whitespace(snippet)
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def infer_employer_type(record: dict, details_text: str) -> str:
    company = compact_whitespace(record.get("company") or "").lower()
    combined = f"{company}\n{compact_whitespace(details_text).lower()}"

    if any(term in combined for term in ("government", "department", "agency", "aps", "public sector", "ministry", "council")):
        return "Government agency"
    if any(term in company for term in ("recruitment", "sourcing", "talent", "peoplebank", "randstad", "hays", "ignite")):
        return "Recruitment-led role"
    if any(term in company for term in ("consulting", "consult", "advisory", "services")):
        return "Consulting firm"
    return "Private sector employer"


def infer_ba_style(record: dict, details_text: str) -> str:
    title = compact_whitespace(record.get("title") or "").lower()
    lowered = compact_whitespace(details_text).lower()

    if "technical business analyst" in title:
        return "technical BA"
    if "systems analyst" in title:
        return "systems-focused BA"
    if "process analyst" in title or "process business analyst" in title:
        return "process-focused BA"
    if "delivery" in title and "business analyst" in title:
        return "delivery BA"

    process_score = sum(
        1 for term in ("bpmn", "process mapping", "process modelling", "workflow", "as-is", "to-be")
        if text_contains_term(lowered, term)
    )
    technical_score = sum(
        1 for term in ("api", "apis", "integration", "data mapping", "sql", "technical", "system", "platform")
        if text_contains_term(lowered, term) or text_contains_term(title, term)
    )
    delivery_score = sum(
        1 for term in ("agile", "user stories", "acceptance criteria", "backlog", "sprint", "delivery", "implementation")
        if text_contains_term(lowered, term) or text_contains_term(title, term)
    )

    if technical_score >= 2 and delivery_score >= 2:
        return "technical delivery BA"
    if process_score >= 2:
        return "process-focused BA"
    if technical_score >= 2:
        return "technical BA"
    if delivery_score >= 2:
        return "delivery BA"
    return "generalist BA"


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


def infer_role_themes(record: dict, details_text: str) -> List[str]:
    lowered = role_text_bundle(record, details_text).lower()
    themes: List[str] = []
    theme_rules = [
        ("digital delivery", ("digital", "delivery", "implementation", "transformation", "ict")),
        ("process analysis", ("bpmn", "process mapping", "process modelling", "workflow", "as-is", "to-be")),
        ("requirements shaping", ("requirements", "business rules", "elicitation", "functional specification", "functional specs")),
        ("stakeholder workshops", ("stakeholder", "stakeholders", "workshop", "workshops", "facilitate")),
        ("agile documentation", ("agile", "scrum", "user stories", "acceptance criteria", "backlog", "gherkin")),
        ("data / integration analysis", ("sql", "data mapping", "integration", "api", "apis", "validation", "system interactions")),
        ("systems improvement", ("system", "platform", "solution", "improvement", "modernisation", "uplift")),
    ]
    for label, terms in theme_rules:
        if any(text_contains_term(lowered, term) for term in terms):
            themes.append(label)
    return dedupe_preserve_order(themes)[:4]


def infer_role_context_clause(record: dict, details_text: str) -> str:
    lowered = role_text_bundle(record, details_text).lower()

    context_rules = [
        ("in an energy trading environment", ("energy trading", "nem", "wholesale energy")),
        ("on a government ICT delivery program", ("aps", "government", "department", "agency", "cio", "ict")),
        ("for a finance or treasury change program", ("treasury", "core banking", "loan systems", "financial management")),
        ("for an ERP or operating-model change program", ("erp", "vendor evaluation", "vendor selection", "supply chain", "commercial functions")),
        ("on a health or public-service program", ("health", "ehealth", "aged care", "ambulance")),
        ("on a systems and integration program", ("integration", "integrations", "api", "apis", "data mapping", "system interactions")),
    ]
    for clause, terms in context_rules:
        if any(text_contains_term(lowered, term) for term in terms):
            return clause
    return ""


def build_role_summary(record: dict, details_text: str, profile: Optional[dict] = None) -> str:
    employer_type = infer_employer_type(record, details_text)
    ba_style = infer_ba_style(record, details_text)
    themes = infer_role_themes(record, details_text)
    context_clause = infer_role_context_clause(record, details_text)

    if employer_type == "Government agency":
        intro = f"Government agency looking for a {ba_style}"
    elif employer_type == "Consulting firm":
        intro = f"Consulting firm looking for a {ba_style}"
    elif employer_type == "Recruitment-led role":
        intro = f"Recruitment-led role for a {ba_style}"
    else:
        intro = f"Private sector role for a {ba_style}"

    if themes:
        if context_clause and "government ict" in context_clause and employer_type == "Government agency":
            summary = f"{intro} to support {list_to_phrase(themes[:3])}."
        elif context_clause:
            summary = f"{intro} {context_clause} to support {list_to_phrase(themes[:3])}."
        else:
            summary = f"{intro} to support {list_to_phrase(themes[:3])}."
    elif context_clause:
        summary = f"{intro} {context_clause}."
    else:
        summary = f"{intro}."
    return summarize_snippet(summary, max_length=180)


def friendly_capability_label(name: str) -> str:
    labels = {
        "business analysis delivery": "requirements shaping and BA delivery",
        "api and integration": "APIs and integrations",
        "data analysis and validation": "data analysis and validation",
        "stakeholder management": "stakeholder management",
        "bpmn and process modelling": "process mapping and BPMN",
        "agile delivery": "Agile delivery",
        "system and technical analysis": "technical analysis",
        "cloud and infrastructure": "cloud or infrastructure context",
        "ai innovation and automation": "automation and AI experimentation",
        "advanced data analytics and bi": "heavy BI or analytics work",
        "hr and workforce management": "HR or workforce systems",
        "crm platform administration": "CRM platform administration",
        "cyber and security": "cyber or security work",
    }
    normalized = compact_whitespace(name).lower()
    return labels.get(normalized, compact_whitespace(name))


def text_contains_term(text: str, term: str) -> bool:
    cleaned_text = compact_whitespace(text).lower()
    cleaned_term = compact_whitespace(term).lower()
    if not cleaned_text or not cleaned_term:
        return False
    pattern = rf"(?<!\w){re.escape(cleaned_term)}(?!\w)"
    return re.search(pattern, cleaned_text) is not None


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
        aliases = [
            str(alias).strip().lower()
            for alias in [rule.get("name"), *(rule.get("aliases") or [])]
            if str(alias).strip()
        ]
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
        if cleaned_skill and text_contains_term(lowered, cleaned_skill):
            matched_must_not.append(cleaned_skill.upper() if cleaned_skill.isupper() else cleaned_skill)

    return {
        "core": dedupe_preserve_order(matched_core),
        "supporting": dedupe_preserve_order(matched_supporting),
        "low_fit": dedupe_preserve_order(matched_low_fit),
        "must_not": dedupe_preserve_order(matched_must_not),
    }


def find_matching_evidence_snippets(details_text: str, profile: dict) -> List[str]:
    snippets = split_text_snippets(details_text)
    if not snippets:
        return []

    target_terms: Set[str] = set()
    for strength in profile.get("strengths", []):
        cleaned = str(strength).strip().lower()
        if cleaned:
            target_terms.add(cleaned)
    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        fit = str(rule.get("fit") or "").strip().lower()
        level = str(rule.get("level") or "").strip().lower()
        if fit in {"core", "supporting"} and level in {"strong", "working", "basic"}:
            name = str(rule.get("name") or "").strip().lower()
            if name:
                target_terms.add(name)
            for alias in rule.get("aliases", []):
                cleaned_alias = str(alias).strip().lower()
                if cleaned_alias:
                    target_terms.add(cleaned_alias)

    generic_positive_terms = {
        "business analysis",
        "requirements",
        "requirement",
        "stakeholder",
        "stakeholders",
        "workshop",
        "workshops",
        "discovery",
        "process",
        "workflow",
        "delivery",
        "backlog",
        "user stories",
        "agile",
        "implementation",
        "transformation",
        "change",
        "mapping",
        "analysis",
        "analyst",
    }

    scored: List[tuple[int, str]] = []
    for snippet in snippets:
        lowered = snippet.lower()
        target_matches = sum(1 for term in target_terms if text_contains_term(lowered, term))
        positive_matches = sum(1 for term in generic_positive_terms if text_contains_term(lowered, term))
        if target_matches > 0 or positive_matches > 0:
            score = (target_matches * 3) + positive_matches
            if any(token in lowered for token in ("experience in", "responsible for", "working with", "will")):
                score += 1
            scored.append((score, summarize_snippet(snippet)))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return dedupe_preserve_order([snippet for _, snippet in scored[:3]])


def fit_highlight_for_profile_area(area: str) -> Optional[str]:
    mapping = {
        "requirements shaping and BA delivery": "Requirements elicitation and BA delivery",
        "stakeholder management": "Workshops and stakeholder facilitation",
        "process mapping and BPMN": "BPMN and process modelling",
        "Agile delivery": "User stories and acceptance criteria",
        "data analysis and validation": "Data mapping and validation",
        "technical analysis": "Technical and systems analysis",
        "APIs and integrations": "APIs and integration context",
        "cloud or infrastructure context": "Infrastructure and platform context",
        "automation and AI experimentation": "Automation and AI experimentation",
    }
    return mapping.get(area)


def build_fit_highlights(record: dict, details_text: str, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = [
        compact_whitespace(item)
        for item in (record.get("fit_highlights") or [])
        if compact_whitespace(item)
    ]
    active_profile = profile or load_profile()
    role_bundle = role_text_bundle(record, details_text)
    lowered = role_bundle.lower()
    capability_matches = find_profile_capability_matches(role_bundle, active_profile)
    title_lower = compact_whitespace(record.get("title") or "").lower()

    matched_profile_areas = capability_matches["core"][:3] + capability_matches["supporting"][:2]
    for area in matched_profile_areas:
        label = fit_highlight_for_profile_area(area)
        if label:
            highlights.append(label)

    if (
        not highlights
        and sum(text_contains_term(lowered, term) for term in ("requirements", "workshop", "stakeholder", "business rules", "elicitation")) >= 2
    ):
        highlights.append("Requirements elicitation and BA delivery")

    if "technical business analyst" in title_lower and not any("Technical and systems analysis" in item for item in highlights):
        highlights.append("Technical and systems analysis")
    elif "business analyst" in title_lower and not any("BA delivery" in item or "Business Analyst scope" in item for item in highlights):
        highlights.append("Core Business Analyst scope")

    if any(text_contains_term(lowered, term) for term in ("government", "department", "agency", "aps", "public sector", "federal", "state")):
        highlights.append("Government context")

    contract_months = extract_contract_months(details_text)
    if contract_months and contract_months >= 12:
        highlights.append("12+ month contract")
    elif compact_whitespace(record.get("work_type") or "").lower() in {"full time", "full-time", "permanent"}:
        highlights.append("Permanent role")

    if compact_whitespace(record.get("work_mode") or "").lower() == "remote" and "canberra" in compact_whitespace(record.get("location") or "").lower():
        highlights.append("Canberra role with remote setup")
    elif "sydney" in compact_whitespace(record.get("location") or "").lower():
        highlights.append("Sydney-based role")

    highlights.extend(competitive_fit_highlights(record, active_profile))
    return dedupe_preserve_order(highlights)[:4]


def build_watchout_entries(
    details_text: str,
    title_reason: Optional[str],
    profile: dict,
    existing_entries: Optional[List[dict]] = None,
    competitive_signals: Optional[List[dict]] = None,
) -> List[dict]:
    entries: List[dict] = []
    lowered = compact_whitespace(details_text).lower()
    capability_matches = find_profile_capability_matches(details_text, profile)

    def add_entry(
        text: str,
        severity: str = "medium",
        kind: str = "watchout",
        category: str = "",
    ) -> None:
        cleaned = compact_whitespace(text)
        if not cleaned:
            return
        entries.append({"text": cleaned, "severity": severity, "kind": kind, "category": category})

    if title_reason == "TITLE_POTENTIAL_MATCH":
        add_entry("Systems Analyst title rather than direct BA title", "medium", category="adjacent_title")

    handled_must_not: Set[str] = set()
    d365_aliases = ["d365", "dynamics 365", "power platform", "power apps", "power automate"]
    d365_strength = find_requirement_strength(details_text, d365_aliases)
    if d365_strength:
        add_entry(
            "Dynamics 365 / Power Platform not evidenced",
            severity_from_requirement_strength(d365_strength, "medium"),
            category="d365_power_platform",
        )
        handled_must_not.update({"d365", "dynamics 365"})

    erp_aliases = ["erp", "vendor evaluation", "vendor selection", "supply chain", "commercial functions"]
    erp_strength = find_requirement_strength(details_text, erp_aliases)
    if any(text_contains_term(lowered, alias) for alias in erp_aliases):
        erp_severity = recency_adjusted_severity(
            profile,
            ["erp", "vendor evaluation", "vendor selection", "supply chain", "commercial functions", "salesforce"],
            severity_from_requirement_strength(erp_strength or "mentioned", "high"),
        )
        add_entry("ERP strategy / vendor selection depth may be limited", erp_severity, category="erp_platform")

    data_ml_aliases = ["data science", "machine learning", "predictive modelling", "advanced analytics", "ml"]
    data_ml_strength = find_requirement_strength(details_text, data_ml_aliases)
    if any(text_contains_term(lowered, alias) for alias in data_ml_aliases):
        add_entry(
            "Data / ML depth is not strongly evidenced",
            severity_from_requirement_strength(data_ml_strength or "desirable", "light"),
            category="data_ml",
        )

    filtered = [item for item in capability_matches["must_not"] if item.lower() not in handled_must_not] if capability_matches["must_not"] else []
    if filtered:
        add_entry(f"{list_to_phrase(filtered[:2])} not evidenced", "high", category="must_not_platform")

    if capability_matches["low_fit"]:
        add_entry(
            f"{list_to_phrase(capability_matches['low_fit'][:2])} looks niche for your background",
            "medium",
            category="low_fit_specialist",
        )

    if "energy trading" in lowered or "knowledge of the nem" in lowered:
        add_entry("Energy trading domain experience not evidenced", "medium", category="energy_trading")
    if "treasury" in lowered or "core banking" in lowered or "loan systems" in lowered:
        treasury_severity = recency_adjusted_severity(
            profile,
            ["treasury", "banking", "core banking", "loan systems", "financial management"],
            "medium",
        )
        add_entry("Treasury / banking domain depth may be limited", treasury_severity, category="finance_treasury")
    if "banking" in lowered or "transaction banking" in lowered:
        banking_severity = recency_adjusted_severity(
            profile,
            ["banking", "transaction banking", "payments", "savings", "investments"],
            "medium",
        )
        add_entry("Banking domain depth may be limited", banking_severity, category="banking_domain")
    if text_contains_term(lowered, "guidewire"):
        old_year = find_profile_experience_year(profile, ["guidewire"])
        if old_year:
            add_entry(f"Guidewire exposure is older from {old_year}", "light", category="insurance_platform")
    if text_contains_term(lowered, "sap") or text_contains_term(lowered, "edi"):
        old_year = find_profile_experience_year(profile, ["sap", "edi"])
        if old_year:
            add_entry(f"SAP / EDI exposure is older from {old_year}", "light", category="erp_platform")
    if re.search(r"\bmust be based in canberra\b|\bmust reside in canberra\b|\bonsite in canberra\b", lowered):
        add_entry("Canberra onsite requirement needs checking", "high", category="canberra_travel")
    elif re.search(r"\b(2 days a week|two days a week|3 days a week|three days a week|2-3 days|two to three days)\b", lowered):
        add_entry("Canberra onsite pattern looks heavier than preferred", "medium", category="canberra_travel")

    for existing in existing_entries or []:
        if not isinstance(existing, dict):
            continue
        add_entry(
            str(existing.get("text") or ""),
            str(existing.get("severity") or "medium"),
            str(existing.get("kind") or "watchout"),
            str(existing.get("category") or ""),
        )

    signal_record = {"fit_source_text": details_text, "competitive_signals": competitive_signals or []}
    for competitive_entry in competitive_gap_watchouts(signal_record, profile):
        add_entry(
            competitive_entry["text"],
            competitive_entry["severity"],
            str(competitive_entry.get("kind") or "competitive_signal"),
            str(competitive_entry.get("category") or ""),
        )

    severity_rank = {"light": 1, "medium": 2, "high": 3}
    best_by_key: Dict[str, dict] = {}
    ordered_keys: List[str] = []
    for entry in entries:
        text_key = str(entry.get("text") or "").strip().lower()
        category_key = normalize_watchout_category(
            str(entry.get("category") or ""),
            str(entry.get("text") or ""),
        )
        dedupe_key = category_key or text_key
        if not dedupe_key:
            continue
        existing = best_by_key.get(dedupe_key)
        if existing is None:
            best_by_key[dedupe_key] = entry
            ordered_keys.append(dedupe_key)
            continue
        existing_rank = severity_rank.get(str(existing.get("severity") or "medium").lower(), 2)
        current_rank = severity_rank.get(str(entry.get("severity") or "medium").lower(), 2)
        if current_rank > existing_rank or (
            current_rank == existing_rank
            and len(str(entry.get("text") or "")) < len(str(existing.get("text") or ""))
        ):
            best_by_key[dedupe_key] = entry

    deduped = [best_by_key[key] for key in ordered_keys if key in best_by_key]
    return deduped[:4]


def build_watchout_lines(details_text: str, title_reason: Optional[str], profile: dict) -> List[str]:
    return [entry["text"] for entry in build_watchout_entries(details_text, title_reason, profile)]


def normalize_watchout_category(category: str, text: str) -> str:
    lowered = f"{compact_whitespace(category).lower()} {compact_whitespace(text).lower()}".strip()
    if any(token in lowered for token in ("erp", "vendor selection", "vendor evaluation", "sap", "edi", "platform implementation", "netsuite", "oracle")):
        return "erp_platform"
    if any(token in lowered for token in ("finance", "treasury", "banking", "accounting", "general ledger", "accounts payable", "accounts receivable", "reconciliation")):
        return "finance_treasury"
    if any(token in lowered for token in ("data / ml", "data ml", "analytics", "machine learning", "predictive", "bi", "business intelligence", "reporting")):
        return "data_analytics"
    if any(token in lowered for token in ("dynamics 365", "d365", "power platform", "power apps", "power automate")):
        return "d365_power_platform"
    if any(token in lowered for token in ("salesforce", "crm")):
        return "crm_platform"
    if any(token in lowered for token in ("insurance", "guidewire", "policycenter", "claimcenter", "underwriting", "claims")):
        return "insurance_platform"
    if any(token in lowered for token in ("canberra", "travel", "onsite")):
        return "canberra_travel"
    if any(token in lowered for token in ("energy trading", "nem")):
        return "energy_trading"
    return compact_whitespace(category).lower() or compact_whitespace(text).lower()


def _normalized_aliases(values: List[str]) -> List[str]:
    return dedupe_preserve_order(
        [compact_whitespace(str(value)).lower() for value in values if compact_whitespace(str(value))]
    )


def _profile_text_blob(profile: dict) -> str:
    parts = [
        " ".join(str(item).strip() for item in profile.get("strengths", []) if str(item).strip()),
        profile.get("llm_profile_brief"),
        profile.get("star_evidence_text"),
        profile.get("cv_text"),
    ]
    return "\n".join(compact_whitespace(part).lower() for part in parts if compact_whitespace(part))


def _profile_auxiliary_text(profile: dict) -> str:
    parts = [
        " ".join(str(item).strip() for item in profile.get("strengths", []) if str(item).strip()),
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
        rule_aliases = _normalized_aliases(
            [str(rule.get("name") or "")] + list(rule.get("aliases") or [])
        )
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
                    "aliases": _normalized_aliases(list(item.get("aliases") or [])),
                    "dominance_level": int(item.get("dominance_level", 1) or 1),
                    "alignment": compact_whitespace(item.get("alignment") or "partial").lower(),
                    "adjustment": int(item.get("adjustment", 0) or 0),
                }
            )
        if sanitized:
            return sanitized

    active_profile = profile or load_profile()
    details_text = build_fit_source_text(record, include_watchouts=False)
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


def competitive_gap_watchouts(record: dict, profile: Optional[dict] = None) -> List[dict]:
    watchouts: List[dict] = []
    for signal in competitive_signal_assessments(record, profile):
        if int(signal.get("adjustment", 0)) >= 0:
            continue
        alignment = compact_whitespace(signal.get("alignment") or "").lower()
        severity = "medium" if alignment == "partial" else "high"
        label = compact_whitespace(signal.get("watchout_label") or signal.get("name") or "")
        category = (
            compact_whitespace(signal.get("name") or "")
            .lower()
            .replace(" and ", "_")
            .replace(" ", "_")
        )
        if label:
            watchouts.append({
                "text": label,
                "severity": severity,
                "kind": "competitive_signal",
                "category": category,
            })
    return watchouts[:2]


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
    if salary_adjustment >= 4:
        return "meets"
    if salary_adjustment < 0:
        return "below"
    return "listed"


def score_to_tone_class(score: int) -> str:
    if score >= 80:
        return "tone-strong"
    if score >= 65:
        return "tone-good"
    if score >= 50:
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
        "Watchouts or specialist gaps": "Watchouts",
        "Already viewed by you": "Viewed",
    }
    if label in direct_map:
        return direct_map[label]
    if label.startswith("Posted within") or label == "Still relatively recent":
        return "Freshness"
    if label.startswith("Sydney location") or label.startswith("Canberra role") or label.startswith("Location"):
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


def format_posted_date_label(posted_text: Optional[str], posted_age_days: Optional[float], reference_time: Optional[datetime]) -> str:
    normalized_posted = normalize_posted_text(posted_text)
    if normalized_posted.lower() == "today":
        return "Today"
    if posted_age_days is None or reference_time is None:
        return "Unknown"
    try:
        posted_at = reference_time - timedelta(days=float(posted_age_days))
        return posted_at.strftime("%d %b %Y")
    except Exception:
        return "Unknown"


def get_match_preferences(profile: Optional[dict] = None) -> dict:
    active_profile = profile or load_profile()
    defaults = {
        "home_location": "Sydney NSW",
        "secondary_location": "Canberra ACT",
        "prefer_government": True,
        "prefer_permanent": True,
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


def build_fit_source_text(record: dict, include_watchouts: bool = True) -> str:
    explicit_source = compact_whitespace(record.get("fit_source_text") or "")
    if explicit_source:
        return explicit_source
    source_parts: List[str] = []
    values = [
        record.get("title"),
        record.get("role_snapshot"),
        record.get("teaser"),
        *(record.get("fit_highlights", []) or []),
    ]
    if include_watchouts:
        values.extend(record.get("fit_watchouts", []) or [])
    for value in values:
        cleaned = compact_whitespace(value)
        if cleaned and cleaned != "N/A":
            source_parts.append(cleaned)
    return "\n".join(dedupe_preserve_order(source_parts))


def find_requirement_strength(details_text: str, aliases: List[str]) -> str:
    lowered = compact_whitespace(details_text).lower()
    if not lowered:
        return ""

    essential_terms = r"(required|essential|must have|mandatory|strong experience|proven experience)"
    desirable_terms = r"(desirable|nice to have|preferred|bonus)"

    for alias in aliases:
        cleaned = str(alias).strip().lower()
        if not cleaned:
            continue
        escaped = re.escape(cleaned)
        if re.search(rf"{essential_terms}.{{0,60}}{escaped}|{escaped}.{{0,60}}{essential_terms}", lowered):
            return "essential"
    for alias in aliases:
        cleaned = str(alias).strip().lower()
        if not cleaned:
            continue
        escaped = re.escape(cleaned)
        if re.search(rf"{desirable_terms}.{{0,60}}{escaped}|{escaped}.{{0,60}}{desirable_terms}", lowered):
            return "desirable"
    if any(str(alias).strip().lower() in lowered for alias in aliases if str(alias).strip()):
        return "mentioned"
    return ""


def extract_contract_months(details_text: str) -> Optional[int]:
    lowered = compact_whitespace(details_text).lower()
    matches = [int(value) for value in re.findall(r"\b(\d{1,2})\s*[-‑– ]?(?:month|months|mth)\b", lowered)]
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
        r"(20\d{2})\s*[-–]\s*(present|current|ongoing|20\d{2})",
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


def lower_severity(severity: str) -> str:
    order = ["light", "medium", "high"]
    if severity not in order:
        return severity
    index = max(order.index(severity) - 1, 0)
    return order[index]


def raise_severity(severity: str) -> str:
    order = ["light", "medium", "high"]
    if severity not in order:
        return severity
    index = min(order.index(severity) + 1, len(order) - 1)
    return order[index]


def severity_from_requirement_strength(strength: str, default: str = "medium") -> str:
    normalized = compact_whitespace(strength).lower()
    if normalized == "essential":
        return "high"
    if normalized == "desirable":
        return "light"
    if normalized == "mentioned":
        return default
    return default


def recency_adjusted_severity(profile: dict, aliases: List[str], base_severity: str) -> str:
    multiplier = profile_recency_multiplier(profile, aliases)
    if multiplier >= 1.0:
        return lower_severity(base_severity)
    if 0.0 < multiplier < 0.6:
        return base_severity
    if multiplier == 0.0 and base_severity == "medium":
        return raise_severity(base_severity)
    return base_severity


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


def deterministic_review_outcome(record: dict, fit_highlights: List[str], fit_watchout_meta: List[dict]) -> Optional[dict]:
    title_reason = str(record.get("title_reason") or "")
    high_watchouts = sum(1 for item in fit_watchout_meta if str(item.get("severity") or "").lower() == "high")
    medium_watchouts = sum(1 for item in fit_watchout_meta if str(item.get("severity") or "").lower() == "medium")
    strong_signal_count = len(fit_highlights)

    if high_watchouts >= 2 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "MISMATCH"}
    if title_reason == "TITLE_POTENTIAL_MATCH" and high_watchouts >= 1 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "POOR"}
    if title_reason == "OK" and strong_signal_count >= 4 and high_watchouts == 0:
        return {"decision": "KEEP", "grade": "STRONG"}
    if title_reason == "OK" and strong_signal_count >= 3 and high_watchouts == 0 and medium_watchouts <= 1:
        return {"decision": "KEEP", "grade": "SOLID"}
    return None


def assess_location_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    source_text = build_fit_source_text(record).lower()
    location = compact_whitespace(record.get("location") or "").lower()
    work_mode = compact_whitespace(record.get("work_mode") or "").lower()

    if not location or location == "n/a":
        return None

    home_location = str(preferences.get("home_location") or "").lower()
    secondary_location = str(preferences.get("secondary_location") or "").lower()

    if "sydney" in location and "sydney" in home_location:
        return {"label": "Sydney-based role", "value": 4}

    if "canberra" in location and "canberra" in secondary_location:
        if work_mode == "remote" or "remote position" in source_text or "fully remote" in source_text:
            return {"label": "Canberra role with remote setup", "value": 2}
        if re.search(r"\b(1 day a week|one day a week|1 day per week|fortnight|2 days a month|two days a month)\b", source_text):
            return {"label": "Canberra role with lighter travel", "value": 0}
        if re.search(r"\b(2 days a week|two days a week|3 days a week|three days a week|2-3 days|two to three days)\b", source_text):
            return {"label": "Canberra onsite pattern is heavier", "value": -3}
        if re.search(r"\bmust be based in canberra\b|\bmust reside in canberra\b|\bonsite in canberra\b", source_text):
            return {"label": "Canberra onsite attendance is required", "value": -6}
        return {"label": "Canberra role may involve travel", "value": -1}

    return None


def assess_contract_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    source_text = build_fit_source_text(record)
    work_type = compact_whitespace(record.get("work_type") or "").lower()
    preferred_contract_months = int(preferences.get("preferred_contract_months", 12) or 12)
    short_contract_months = int(preferences.get("short_contract_months", 6) or 6)

    if "full time" in work_type or "permanent" in work_type:
        return {"label": "Permanent role", "value": 7}

    if "contract" not in work_type:
        return None

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
    source_text = build_fit_source_text(record).lower()
    government_terms = (
        "government",
        "department",
        "agency",
        "public sector",
        "aps",
        "ministerial",
        "federal",
        "state",
    )
    combined = "\n".join([title, company, source_text])
    if any(term in combined for term in government_terms):
        return {"label": "Government context", "value": 4}
    return None


def score_to_match_label(score: int) -> str:
    if score >= 80:
        return "Strong match"
    if score >= 65:
        return "Good match"
    if score >= 50:
        return "Worth a look"
    return "Stretch"


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
    if prefix == "DESC_FINANCE" and cleaned_detail:
        return f"Finance-domain mismatch: {cleaned_detail}"
    if prefix == "DESC_TREASURY" and cleaned_detail:
        return f"Treasury or banking-specialist role: {cleaned_detail}"
    if prefix == "DESC_ERP_FIN" and cleaned_detail:
        return f"ERP or finance-specialist workflow: {cleaned_detail}"
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
    if prefix == "TITLE_POTENTIAL_MATCH":
        return "Adjacent title match"
    if prefix == "CARD_SPECIALIST" and cleaned_detail:
        return f"Rejected early from card metadata: {cleaned_detail}"

    fallback = raw.replace("_", " ").lower()
    return fallback[:1].upper() + fallback[1:]


def watchout_penalty(record: dict, profile: Optional[dict] = None) -> int:
    watchout_meta = record.get("fit_watchout_meta") or []
    if isinstance(watchout_meta, list) and watchout_meta:
        severity_points = {"light": 2, "medium": 5, "high": 8}
        penalty = 0
        for entry in watchout_meta[:4]:
            if str((entry or {}).get("kind") or "").strip().lower() == "competitive_signal":
                continue
            severity = str((entry or {}).get("severity") or "medium").strip().lower()
            penalty += severity_points.get(severity, 5)
        return min(penalty, 14)

    watchouts = [
        str(item).strip().lower()
        for item in record.get("fit_watchouts", [])
        if str(item).strip()
    ]
    if not watchouts:
        return 0

    active_profile = profile or load_profile()
    strong_keywords = {
        "energy trading",
        "trading experience",
        "treasury",
        "erp",
        "vendor evaluation",
        "vendor selection",
        "supply chain",
        "commercial functions",
        "machine learning",
        "data science",
    }
    low_fit_aliases: Set[str] = set()
    for rule in active_profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        level = str(rule.get("level") or "").strip().lower()
        fit = str(rule.get("fit") or "").strip().lower()
        if fit == "avoid" or level in {"low", "none"}:
            name = str(rule.get("name") or "").strip().lower()
            if name:
                low_fit_aliases.add(name)
            for alias in rule.get("aliases", []):
                alias_text = str(alias).strip().lower()
                if alias_text:
                    low_fit_aliases.add(alias_text)

    penalty = 0
    for item in watchouts[:4]:
        penalty += 4
        matched_keywords = [keyword for keyword in strong_keywords if keyword in item]
        if matched_keywords:
            penalty += 2 + min(len(matched_keywords), 3)
        if any(alias in item for alias in low_fit_aliases):
            penalty += 3
        if "desirable" in item or "preferred" in item or "bonus" in item:
            penalty = max(penalty - 1, 1)
    return min(penalty, 14)


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
    is_daily = "per day" in lowered or "daily rate" in lowered or "/day" in lowered

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

    evidence_score = min(len(fit_highlights) * 3, 12)
    if evidence_score:
        breakdown.append({"label": "Fit evidence bullets", "value": weighted_points(evidence_score, weights["fit"])})

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

    salary_score = weighted_points(salary_fit_adjustment(record, active_profile), weights["salary"])
    if salary_score > 0:
        breakdown.append({"label": "Salary/rate signal", "value": salary_score})
    elif salary_score < 0:
        breakdown.append({"label": "Salary/rate below target", "value": salary_score})

    watchout_score = weighted_points(watchout_penalty(record, active_profile), weights["fit"])
    if watchout_score > 0:
        breakdown.append({"label": "Watchouts or specialist gaps", "value": -watchout_score})

    if viewed_by_user(record) and not record.get("applied"):
        breakdown.append({"label": "Already viewed by you", "value": -3})

    return breakdown


def fit_score(record: dict, profile: Optional[dict] = None) -> int:
    score = sum(item["value"] for item in fit_score_breakdown(record, profile))
    return max(min(score, 100), 0)


def is_dashboard_eligible(record: dict, profile: Optional[dict] = None) -> bool:
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
    if not record.get("fit_highlights"):
        record["fit_highlights"] = snapshot.get("fit_highlights") or []
    if not record.get("fit_watchouts"):
        record["fit_watchouts"] = snapshot.get("fit_watchouts") or []
    if not record.get("fit_watchout_meta"):
        record["fit_watchout_meta"] = snapshot.get("fit_watchout_meta") or []
    if not record.get("competitive_signals"):
        record["competitive_signals"] = snapshot.get("competitive_signals") or []
    if not record.get("hard_block_reasons"):
        record["hard_block_reasons"] = snapshot.get("hard_block_reasons") or []
    if not compact_whitespace(record.get("details_status") or ""):
        record["details_status"] = snapshot.get("details_status") or ""

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
        "details_status": snapshot.get("details_status") or "",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "fit_watchouts": snapshot.get("fit_watchouts") or [],
        "fit_watchout_meta": snapshot.get("fit_watchout_meta") or [],
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
        "details_status": snapshot.get("details_status") or "",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "fit_watchouts": snapshot.get("fit_watchouts") or [],
        "fit_watchout_meta": snapshot.get("fit_watchout_meta") or [],
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
        "details_status": snapshot.get("details_status") or "",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "fit_watchouts": snapshot.get("fit_watchouts") or [],
        "fit_watchout_meta": snapshot.get("fit_watchout_meta") or [],
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
    current_records = sorted(
        curated_kept_records,
        key=lambda record: (
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -fit_score(record, profile),
            -(1 if not viewed_by_user(record) else 0),
        ),
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
        key=lambda record: (
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(fit_score(record, profile)),
            -(parse_timestamp(record.get("last_kept_at")) or datetime.min).timestamp()
            if parse_timestamp(record.get("last_kept_at"))
            else float("-inf"),
        ),
    )
    stale_archive_records = sorted(
        [record for record in archive_records if record.get("is_stale") and is_dashboard_eligible(record, profile)],
        key=lambda record: (
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(fit_score(record, profile)),
            -(parse_timestamp(record.get("last_kept_at")) or datetime.min).timestamp()
            if parse_timestamp(record.get("last_kept_at"))
            else float("-inf"),
        ),
    )
    return {
        "current_records": current_records,
        "archive_records": archive_records,
        "recent_archive_records": recent_archive_records,
        "stale_archive_records": stale_archive_records,
        "applied_records": applied_records,
        "hidden_records": hidden_records,
    }


def render_job_card(record: dict, scoring_profile: Optional[dict] = None) -> str:
    active_profile = scoring_profile or load_profile()
    display_record = dict(record)
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
    fit_source_text = build_fit_source_text(display_record, include_watchouts=False) or stored_snapshot
    watchout_source_text = build_fit_source_text(display_record, include_watchouts=True) or fit_source_text
    display_record["fit_source_text"] = watchout_source_text
    role_summary = build_role_summary(record, fit_source_text, active_profile)
    display_record["role_snapshot"] = role_summary
    display_record["competitive_signals"] = competitive_signal_assessments(record, active_profile)
    fit_highlights = build_fit_highlights(record, fit_source_text, active_profile)
    fit_watchout_meta = build_watchout_entries(
        watchout_source_text,
        title_reason,
        active_profile,
        existing_entries=record.get("fit_watchout_meta") if isinstance(record.get("fit_watchout_meta"), list) else None,
        competitive_signals=display_record.get("competitive_signals") if isinstance(display_record.get("competitive_signals"), list) else None,
    )
    fit_watchouts = [entry["text"] for entry in fit_watchout_meta]
    blocking_reasons = hard_block_reasons(display_record, active_profile)
    if blocking_reasons:
        fit_watchouts = dedupe_preserve_order([*blocking_reasons, *fit_watchouts])
    display_record["hard_block_reasons"] = blocking_reasons
    display_record["fit_highlights"] = fit_highlights
    display_record["fit_watchouts"] = fit_watchouts
    display_record["fit_watchout_meta"] = fit_watchout_meta
    fit_points = fit_score(display_record, scoring_profile)
    fit_label = score_to_match_label(fit_points)
    fit_tone_class = score_to_tone_class(fit_points)
    score_breakdown = fit_score_breakdown(display_record, scoring_profile)
    posted_text = normalize_posted_text(record.get("posted"))
    posted_date_label = format_posted_date_label(
        posted_text,
        record.get("posted_age_days"),
        parse_timestamp(record.get("last_seen_at")) or parse_timestamp(record.get("first_seen_at")),
    )
    work_mode = str(record.get("work_mode") or "N/A")
    posted_age_days = record.get("posted_age_days")
    salary_value = salary_sort_value(str(record.get("salary") or ""))
    salary_fit_state = salary_fit_label(record, scoring_profile)
    record_kind = "applied" if applied_record else ("hidden" if hidden_record else ("saved" if archived else "current"))

    source = str(record.get("source") or "seek").lower().strip()
    source_label = {"linkedin": "LinkedIn", "seek": "SEEK"}.get(source, source.upper())

    badges = []
    if applied_record:
        badges.append(render_badge("Applied", "badge-viewed", "You already applied for this role."))
    elif hidden_record:
        badges.append(render_badge("Hidden", "badge-hidden", "You hid this role for now."))
    elif archived:
        badges.append(render_badge("Previously Kept", "badge-archive", "This role was kept in an earlier run and carried forward into the dashboard."))
    if not applied_record and not seen_by_you:
        badges.append(render_badge("New To You", "badge-new", "You have not opened this role from the dashboard yet."))
    if is_stale:
        badges.append(render_badge("15+ Days Old", "badge-stale", "This role is older, but still saved for reference."))
    elif seen_by_you:
        badges.append(viewed_badge_html())
    badges.append(render_badge(source_label, f"badge-source-{source}", f"Sourced from {source_label}."))

    score_html = (
        f'<div class="match-tile {fit_tone_class}">'
        + (
            f'<span class="match-tile-number">{fit_points}</span>'
            if TEST_ANY_MODE
            else ""
        )
        + f'<span class="match-tile-label">{safe_html(fit_label)}</span>'
        + "</div>"
    )

    posted_display = posted_text
    if posted_age_days is not None and posted_age_days >= 1 and posted_text not in ("N/A", ""):
        if posted_date_label != "Unknown" and posted_date_label != posted_text:
            posted_display = f"{posted_text} ({posted_date_label})"
    elif posted_display in ("N/A", "") and posted_date_label != "Unknown":
        posted_display = posted_date_label

    meta_items = []
    for label, value in [
        ("Posted", posted_display),
        ("Location", record.get("location")),
        ("Work mode", record.get("work_mode")),
        ("Type", record.get("work_type")),
        ("Salary", record.get("salary")),
    ]:
        if value and value != "N/A" and value != "Unknown":
            meta_items.append(
                f'<span class="job-meta-item"><strong>{safe_html(label)}</strong> {safe_html(str(value))}</span>'
            )
    context_bits = []
    if salary_fit_state == "below":
        fit_watchouts = dedupe_preserve_order([
            *fit_watchouts,
            "Salary is below target range",
        ])
    contract_item = assess_contract_preference(record, scoring_profile)
    if contract_item and int(contract_item.get("value", 0)) < 0:
        fit_watchouts = dedupe_preserve_order([
            *fit_watchouts,
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
    if fit_highlights:
        note_bits.append(f"Strongest fit: {fit_highlights[0]}.")
    if fit_watchouts:
        note_bits.append(f"Watchout: {fit_watchouts[0]}.")
    note_html = (
        f'<div class="job-note">{safe_html(" ".join(note_bits))}</div>'
        if note_bits
        else ""
    )
    insight_sections = []
    if fit_highlights:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Why it fits</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in fit_highlights)}</ul>'
            '</div>'
        )
    if fit_watchouts:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Possible gaps</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in fit_watchouts)}</ul>'
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

    if hidden_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-unhide" type="button" data-review-action="unhide" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">Unhide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif not applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-applied" type="button" data-review-action="applied" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">Applied</button>'
            f'<button class="review-button review-hide" type="button" data-review-action="hidden" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}" title="Hides this role and teaches the engine to filter similar ones">Not for me</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    else:
        actions_html = ""

    return (
        f'<article class="job-card" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html((record.get("company") or "").lower())}" data-source="{safe_html(source)}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        f'<div class="job-company">{company}</div>'
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


def render_section(title: str, records: List[dict], empty_message: str, scoring_profile: Optional[dict] = None) -> str:
    if not records:
        return (
            f'<section class="section"><h2>{safe_html(title)}</h2>'
            f'<p class="empty-state">{safe_html(empty_message)}</p></section>'
        )
    dom_id = section_dom_id(title)
    cards = "".join(render_job_card(record, scoring_profile) for record in records)
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

    return [
        row
        for row in audit_rows
        if row.get("decision") == "KEEP" and str(row.get("run_started_at") or "") == latest_run_started_at
    ]


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
    shortlist_count = len(current_records) + len(recent_archive_records) + len(stale_archive_records)
    run_label = run_started_at.strftime("%d %b %Y %I:%M %p")
    target_summaries = []
    for location, pages in (run_stats.get("search_targets") or {}).items():
        page_label = ", ".join(str(page) for page in pages) if pages else "none"
        target_summaries.append(f"{location}: pages {page_label}")
    testing_mode_note = ""
    if TEST_SCRAPE_MODE:
        testing_mode_note = (
            f" Scrape test mode is on, so the dashboard keeps roles scoring {DASHBOARD_MIN_SCORE}+,"
            f" widens the live search to at least {TEST_SCRAPE_DATE_RANGE_DAYS} days and"
            f" {TEST_SCRAPE_MAX_PAGES_CAP} pages, skips the quick card gate, and treats"
            f" every role as New To You."
        )
    elif TEST_DASHBOARD_MODE:
        testing_mode_note = (
            f" Dashboard test mode is on, so the shortlist keeps roles scoring {DASHBOARD_MIN_SCORE}+"
            f" and treats every role as New To You without running a fresh scrape."
        )
    elif "--reset-new-to-you" in CLI_FLAGS:
        testing_mode_note = " Viewed history has been reset for this dashboard rebuild, so all roles are shown as unseen."
    search_window_label = f"Last {date_range_days} day" + ("" if date_range_days == 1 else "s")
    sort_order_label = "Newest first" if sort_newest_first else "Source relevance"
    mode_label = "Test mode ON" if TEST_ANY_MODE else "Normal mode"
    snapshot_helper = (
        f"Shortlist currently keeps roles scoring {DASHBOARD_MIN_SCORE}+ and treats all roles as New To You."
        if TEST_ANY_MODE
        else f"Shortlist currently keeps roles scoring {DASHBOARD_MIN_SCORE}+ and preserves your viewed history."
    )
    hero_summary = (
        f"Last run {run_label} — {run_stats.get('cards_seen', 0)} cards scanned, "
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
      background: rgba(255, 253, 250, 0.98);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px 22px 18px;
      box-shadow: var(--shadow);
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
    .badge-new {{ background: var(--accent-soft); color: var(--accent); }}
    .badge-potential {{ background: var(--warm-soft); color: var(--warm); }}
    .badge-archive {{ background: #f3e8ff; color: #6b21a8; }}
    .badge-hidden {{ background: #fee2e2; color: #991b1b; }}
    .badge-stale {{ background: #f3f4f6; color: #4b5563; }}
    .badge-viewed {{ background: #fef3c7; color: #92400e; }}
    .badge-source-seek {{ background: #e0f2fe; color: #0c4a6e; }}
    .badge-source-linkedin {{ background: #dbeafe; color: #1e3a5f; }}
    .badge-fit-high {{ background: #dcfce7; color: #166534; }}
    .badge-fit-medium {{ background: #fef3c7; color: #92400e; }}
    .badge-fit-borderline {{ background: #e5e7eb; color: #374151; }}
    .filter-panel {{
      background: rgba(255, 253, 249, 0.96);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px 22px;
      box-shadow: var(--shadow);
    }}
    .filter-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
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
      margin-bottom: 12px;
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
      color: var(--muted);
      font-size: 1.02rem;
    }}
    .match-tile {{
      min-width: 108px;
      align-self: flex-start;
      border-radius: 18px;
      padding: 12px 14px 10px;
      text-align: center;
      background: #eefbf3;
    }}
    .match-tile-number {{
      display: block;
      font-family: var(--serif);
      font-size: 2rem;
      line-height: 1;
      margin-bottom: 4px;
    }}
    .match-tile-label {{
      display: block;
      font-size: 0.95rem;
      font-weight: 600;
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
      content: "•";
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
    .review-hide {{
      background: white;
      color: var(--warm);
      border: 1px solid rgba(154, 52, 18, 0.22);
    }}
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
          <h1>Potential Jobs</h1>
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
            </div>
            <div class="filter-grid">
              <label class="filter-field">
                <span>Sort</span>
                <select id="sort_select">
                  <option value="newest">Newest posted first</option>
                  <option value="fit">Best match first</option>
                  <option value="salary">Highest salary first</option>
                  <option value="unseen">Not opened by me first</option>
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
                  <option value="unseen">Not opened by me</option>
                  <option value="viewed">Opened by me</option>
                </select>
              </label>
              <label class="filter-field">
                <span>Posted</span>
                <select id="posted_filter">
                  <option value="all">Any time</option>
                  <option value="1">Today</option>
                  <option value="3">Last 3 days</option>
                  <option value="7">Last 7 days</option>
                  <option value="15">Last 15 days</option>
                  <option value="30">Last 30 days</option>
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
                <span>Match score</span>
                <select id="score_filter">
                  <option value="all">Any</option>
                  <option value="80" {"selected" if DEFAULT_SCORE_FILTER_MIN == 80 else ""}>80+ only</option>
                  <option value="65" {"selected" if DEFAULT_SCORE_FILTER_MIN == 65 else ""}>65+ only</option>
                  <option value="35" {"selected" if DEFAULT_SCORE_FILTER_MIN == 35 else ""}>35+ only</option>
                  <option value="50" {"selected" if DEFAULT_SCORE_FILTER_MIN == 50 else ""}>50+ only</option>
                </select>
              </label>
              <label class="filter-field">
                <span>Salary</span>
                <select id="salary_filter">
                  <option value="all">Any</option>
                  <option value="listed">Salary listed</option>
                  <option value="meets">Meets my target</option>
                  <option value="below">Below my target</option>
                  <option value="missing">No salary shown</option>
                </select>
              </label>
            </div>
          </section>
          {render_section("Matches From This Run", current_records, "No kept roles from the latest run right now.", scoring_profile)}
          {render_section("Kept From Earlier Runs", recent_archive_records, "No roles from earlier runs are being carried forward right now.", scoring_profile)}
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
                {''.join(render_job_card(record, scoring_profile) for record in stale_archive_records)}
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
            <h2 class="snapshot-heading">Run Snapshot</h2>
            <div class="snapshot-meta">
              <div class="snapshot-meta-row"><span class="snapshot-meta-label">Last run</span><span class="snapshot-meta-value">{safe_html(run_label)}</span></div>
              <div class="snapshot-meta-row"><span class="snapshot-meta-label">Window</span><span class="snapshot-meta-value">{safe_html(search_window_label)}</span></div>
              <div class="snapshot-meta-row"><span class="snapshot-meta-label">Sort</span><span class="snapshot-meta-value">{safe_html(sort_order_label)}</span></div>
              <div class="snapshot-meta-row"><span class="snapshot-meta-label">Mode</span><span class="snapshot-meta-value">{safe_html(mode_label)}</span></div>
            </div>
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
            <span>How Match Score Works</span>
            <span class="side-toggle-hint">Show / hide</span>
          </summary>
          <div class="side-panel-body">
            <p class="side-panel-copy">The score is a guide, not a final verdict. The raw number is kept internally for ranking and is shown on cards only in test mode. Normal mode shows four human-friendly bands instead so the dashboard does not pretend to be more precise than it really is.</p>
            <div class="job-meta">
              <span class="chip"><strong>Strong match:</strong> 80-100</span>
              <span class="chip"><strong>Good match:</strong> 65-79</span>
              <span class="chip"><strong>Worth a look:</strong> 50-64</span>
              <span class="chip"><strong>Stretch:</strong> 0-49</span>
              <span class="chip"><strong>Title match:</strong> +14 direct, +4 adjacent</span>
              <span class="chip"><strong>Description review:</strong> +20 excellent, +16 strong, +12 solid, +6 weak, 0 poor, -10 mismatch</span>
              <span class="chip"><strong>Competitive signals:</strong> specialist bias can add a small boost or a moderate penalty</span>
              <span class="chip"><strong>Freshness:</strong> newer roles score higher</span>
              <span class="chip"><strong>Decision weights:</strong> fit, pay, location, work mode, contract, government, and freshness can now be dialed up or down</span>
              <span class="chip"><strong>Watchouts:</strong> essential gaps hit harder than desirable-only gaps</span>
            </div>
          </div>
        </details>
      </aside>
    </div>
  </main>
  <script>
    const REVIEW_API_URL = 'http://127.0.0.1:8765/api/review';
    const JOB_HISTORY_API_URL = 'http://127.0.0.1:8765/api/job-history';
    const sortSelect = document.getElementById('sort_select');
    const pageSizeSelect = document.getElementById('page_size_select');
    const scopeFilter = document.getElementById('scope_filter');
    const postedFilter = document.getElementById('posted_filter');
    const workModeFilter = document.getElementById('work_mode_filter');
    const scoreFilter = document.getElementById('score_filter');
    const salaryFilter = document.getElementById('salary_filter');
    const workspaceTabs = Array.from(document.querySelectorAll('[data-workspace-target]'));
    const workspacePanels = Array.from(document.querySelectorAll('[data-workspace-panel]'));
    const paginationState = {{}};

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
      const sortMode = sortSelect?.value || 'newest';
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

    async function saveReviewAction(button) {{
      const card = button.closest('.job-card');
      const status = card?.querySelector('.review-status');
      const action = button.dataset.reviewAction;
      const jobKey = button.dataset.jobKey || '';
      const jobUrl = button.dataset.jobUrl || '';

      if (!status) {{
        return;
      }}

      const buttons = card.querySelectorAll('.review-button');
      buttons.forEach(item => item.disabled = true);
      status.textContent = action === 'applied'
        ? 'Saving as applied...'
        : action === 'unhide'
          ? 'Removing from hidden jobs...'
          : 'Saving hidden job...';

      try {{
        const response = await fetch(REVIEW_API_URL, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            action,
            job_key: jobKey,
            url: jobUrl
          }})
        }});

        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.error || 'Could not save review action');
        }}

        card.classList.add('is-reviewed');
        status.textContent = action === 'applied'
          ? 'Saved to Applied jobs. It will be hidden in future runs.'
          : action === 'unhide'
            ? 'Removed from Hidden jobs. It can appear again in future runs.'
            : 'Saved to Hidden jobs. It will stay out of future runs.';
        window.setTimeout(() => {{
          card.style.display = 'none';
        }}, 900);
      }} catch (error) {{
        buttons.forEach(item => item.disabled = false);
        status.textContent = error.message || 'Could not save review action.';
      }}
    }}

    document.addEventListener('click', event => {{
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

      const button = event.target.closest('.review-button');
      if (!button) {{
        const workspaceTab = event.target.closest('[data-workspace-target]');
        if (!workspaceTab) {{
          return;
        }}
        setActiveWorkspace(workspaceTab.dataset.workspaceTarget || 'potential');
        return;
      }}
      saveReviewAction(button);
    }});

    for (const control of [sortSelect, pageSizeSelect, scopeFilter, postedFilter, workModeFilter, scoreFilter, salaryFilter]) {{
      control?.addEventListener('change', () => {{
        resetPagination();
        applyDashboardControls();
      }});
    }}

    setActiveWorkspace((window.location.hash || '#potential').replace('#', ''), false);
    hydrateViewedState();
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
                            "fit_watchouts": [],
                            "fit_watchout_meta": [],
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
                            full_url = build_full_url(relative_url)
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

                            for skill in extract_detected_skills(details_text):
                                skill_observations.append(
                                    {
                                        "skill": skill,
                                        "title": title,
                                        "company": company,
                                        "url": full_url,
                                        "search_location": search_location,
                                    }
                                )

                            ok_desc, desc_reason = passes_content_filters(details_text, record["location"])
                            record["content_reason"] = desc_reason
                            if not ok_desc:
                                print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
                                record["reject_reason"] = desc_reason
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
                            record["fit_watchout_meta"] = build_watchout_entries(
                                details_text,
                                title_reason,
                                profile,
                                competitive_signals=record.get("competitive_signals") if isinstance(record.get("competitive_signals"), list) else None,
                            )
                            record["fit_watchouts"] = [entry["text"] for entry in record["fit_watchout_meta"]]

                            deterministic_review = deterministic_review_outcome(
                                record,
                                record["fit_highlights"],
                                record["fit_watchout_meta"],
                            )
                            if deterministic_review is not None:
                                llm_review = deterministic_review
                                print(f"[LLM][SKIP] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                            else:
                                llm_input_text = details_text[:MAX_LLM_CHARS]
                                llm_fp = build_llm_cache_key(llm_input_text)

                                if not llm_is_enabled():
                                    llm_review = normalize_llm_review(None)
                                    print(f"[LLM][DISABLED] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                                elif llm_fp in llm_cache:
                                    llm_review = normalize_llm_review(llm_cache[llm_fp])
                                    print(f"[LLM][CACHE] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                                else:
                                    llm_review = normalize_llm_review(llm_should_consider(llm_input_text))
                                    llm_cache[llm_fp] = llm_review
                                    print(f"[LLM] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")

                            record["llm_decision"] = llm_review["decision"]
                            record["llm_fit_grade"] = llm_review["grade"]
                            if TEST_SCRAPE_MODE:
                                test_score_breakdown = fit_score_breakdown(record, profile)
                                print(
                                    f"[TEST][SCORE] {title} @ {company} | "
                                    f"{fit_score(record, profile)}/100 | "
                                    f"{format_score_breakdown_for_console(test_score_breakdown)}"
                                )
                            if llm_review["decision"] == "REJECT":
                                print(f"REJECTED (llm) [LLM_REJECT] {title} @ {company}")
                                record["reject_reason"] = "LLM_REJECT"
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


def _deduplicate_across_sources(records: List[dict]) -> List[dict]:
    """Remove cross-source duplicates. SEEK record wins over LinkedIn."""

    def _norm(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").lower()).strip()

    def _are_same_job(a: dict, b: dict) -> bool:
        co_a = _norm(a.get("company", ""))
        co_b = _norm(b.get("company", ""))
        if not co_a or co_a != co_b:
            return False
        words_a = set(_norm(a.get("title", "")).split())
        words_b = set(_norm(b.get("title", "")).split())
        if not words_a or not words_b:
            return False
        return len(words_a & words_b) / len(words_a | words_b) >= 0.8

    seen: List[dict] = []
    for record in records:
        if not any(_are_same_job(record, kept) for kept in seen):
            seen.append(record)
    return seen


def scrape_seek_jobs_direct(max_pages_cap: int = MAX_PAGES_CAP, headless: bool = False) -> str:
    configure_console_output()
    if TEST_SCRAPE_MODE:
        print("Mode: test scrape run")
    else:
        print("Mode: real scrape run (default)")

    profile = load_profile()
    previous_audit_rows = load_json_list(DEBUG_JSON_PATH)
    previous_run_stats = load_json_dict(RUN_STATS_PATH)
    search_settings = get_search_settings(profile)
    configured_max_pages = int(search_settings.get("max_pages_cap", max_pages_cap) or max_pages_cap)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    if TEST_SCRAPE_MODE:
        configured_max_pages = max(configured_max_pages, TEST_SCRAPE_MAX_PAGES_CAP)
        configured_date_range = max(configured_date_range, TEST_SCRAPE_DATE_RANGE_DAYS)
    enforce_posted_age_limit = bool(search_settings.get("enforce_posted_age_limit", True))
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
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
        from scraper_linkedin import LinkedInScraper  # noqa: PLC0415
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
            kept_records = _deduplicate_across_sources(kept_records + li_kept)
            audit_rows.extend(li_audit)
            skill_observations.extend(li_skills)
        except Exception as exc:
            print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {exc}")

    # --- Finalize ---
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


def rebuild_html_dashboard() -> str:
    configure_console_output()
    if TEST_DASHBOARD_MODE:
        print("Mode: test dashboard rebuild")
    elif TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        print("Mode: real dashboard rebuild with viewed-state reset")
    else:
        print("Mode: real dashboard rebuild")
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
    if TEST_ANY_MODE:
        print("New To You has been reset for testing.")
    elif "--reset-new-to-you" in CLI_FLAGS:
        print("Viewed history has been reset for this dashboard rebuild.")
    return OUTPUT_HTML


if __name__ == "__main__":
    if "--rebuild-dashboard" in sys.argv:
        rebuild_html_dashboard()
    else:
        scrape_seek_jobs_direct()
