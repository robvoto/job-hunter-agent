"""Profile persistence and defaults.

Main goals:
- define the runtime profile structure used by matching and review flows
- create a safe default profile for first run
- load, merge, patch, and save profile.json consistently

Notes:
- profile.json is the runtime source of truth
- onboarding and imports may generate it, and admin refines it over time
"""

import copy
import json
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
PROFILE_PATH = DATA_DIR / "profile.json"
MIN_DATE_RANGE_DAYS = 1
MAX_DATE_RANGE_DAYS = 30
MIN_PAGES_CAP = 1
MAX_PAGES_CAP_HARD_LIMIT = 25
DEFAULT_EVIDENCE_TIERS = {
    "primary_current_evidence": "",
    "secondary_older_evidence": "",
    "background_optional_evidence": "",
}
DEFAULT_EVIDENCE_TIER_WEIGHTS = {
    "primary_current_evidence": 1.0,
    "secondary_older_evidence": 0.55,
    "background_optional_evidence": 0.25,
}
DEFAULT_LLM_PROFILE_BRIEF_MODE = "auto"

DEFAULT_SEARCH_SETTINGS = {
    "keywords": "business analyst",
    "locations": [
        "All Sydney NSW",
        "All Canberra ACT",
    ],
    "classification_ids": [
        "6076",
        "1209",
        "6123",
        "6281",
        "1223",
    ],
    "date_range_days": 3,
    "max_pages_cap": 10,
    "enforce_posted_age_limit": True,
    "sort_newest_first": True,
}

DEFAULT_PROFILE = {
    "search_settings": {
        **DEFAULT_SEARCH_SETTINGS,
    },
    "review_controls": {
        "applied_job_keys": [],
        "hidden_job_keys": [],
    },
    "candidate_summary": (
        "I'm a Senior Business Analyst focused on digital delivery, discovery, "
        "process improvement, requirements shaping, and stakeholder alignment."
    ),
    "strengths": [
        "business analysis",
        "digital delivery",
        "discovery",
        "requirements elicitation",
        "process mapping",
        "stakeholder engagement",
        "workshops",
        "backlog refinement",
        "change delivery",
    ],
    "salary_preferences": {
        "minimum_salary_yearly": 0,
        "minimum_daily_rate": 0,
    },
    "match_preferences": {
        "home_location": "Sydney NSW",
        "secondary_location": "Canberra ACT",
        "prefer_government": True,
        "prefer_permanent": True,
        "preferred_contract_months": 12,
        "short_contract_months": 6,
    },
    "llm_profile_brief_mode": DEFAULT_LLM_PROFILE_BRIEF_MODE,
    "llm_profile_brief": "",
    "star_evidence_text": "",
    "cv_text": "",
    "evidence_tiers": {
        **DEFAULT_EVIDENCE_TIERS,
    },
    "evidence_tier_weights": {
        **DEFAULT_EVIDENCE_TIER_WEIGHTS,
    },
    "capability_profile_rules": [
        {
            "name": "business analysis delivery",
            "level": "strong",
            "fit": "core",
            "aliases": [
                "requirements elicitation",
                "requirements gathering",
                "process mapping",
                "stakeholder engagement",
                "workshops",
                "backlog refinement",
                "user stories",
                "discovery",
                "business process improvement",
                "uat",
            ],
        },
        {
            "name": "api and integration",
            "level": "working",
            "fit": "supporting",
            "aliases": [
                "api",
                "apis",
                "integration",
                "integrations",
                "rest api",
                "interface",
            ],
        },
        {
            "name": "data analysis and validation",
            "level": "working",
            "fit": "supporting",
            "aliases": [
                "sql",
                "excel",
                "data mapping",
                "data validation",
                "data migration",
                "query databases",
                "database queries",
            ],
        },
        {
            "name": "advanced data analytics and bi",
            "level": "low",
            "fit": "contextual",
            "aliases": [
                "data analytics",
                "analytics",
                "data warehousing",
                "etl",
                "data modelling",
                "sql",
                "power bi",
                "tableau",
                "snowflake",
                "azure data factory",
                "data governance",
                "data quality",
                "data lineage",
                "data visualisation",
            ],
        },
        {
            "name": "hr and workforce management",
            "level": "low",
            "fit": "contextual",
            "aliases": [
                "human resources",
                "hr",
                "workforce management",
                "workforce planning",
                "hcm",
                "people systems",
                "talent management",
                "rostering",
                "payroll",
            ],
        },
        {
            "name": "crm platform administration",
            "level": "low",
            "fit": "contextual",
            "aliases": [
                "hubspot",
                "hubspot crm",
                "salesforce",
                "crm workflows",
                "crm dashboard",
                "marketing automation",
            ],
        },
        {
            "name": "cyber and security",
            "level": "none",
            "fit": "avoid",
            "aliases": [
                "cyber security",
                "cybersecurity",
                "information security",
                "security operations",
                "threat detection",
                "identity and access management",
            ],
        },
    ],
    "llm_prompt_notes": [
        "Prefer roles centered on discovery, requirements, delivery, process improvement, and stakeholder engagement.",
        "Allow BA-adjacent roles like systems analyst or implementation consultant if the description still reads like a fit.",
        "Reject hands-on security or cyber roles.",
        "Reject specialist platform roles when they are mainly configuration, engineering, or admin rather than business analysis.",
    ],
    "cheap_keep_counter_patterns": [
        r"\bbusiness analyst\b",
        r"\brequirements?\b",
        r"\bstakeholder\b",
        r"\bworkshops?\b",
        r"\buser stories?\b",
        r"\bacceptance criteria\b",
        r"\bbpmn\b",
        r"\bprocess mapping\b",
        r"\bagile\b",
        r"\bdigital delivery\b",
        r"\bgovernment\b",
    ],
    "cheap_reject_metadata_rules": [
        {"pattern": r"\berp\b|\bvendor selection\b|\bvendor evaluation\b", "reason": "CARD_SPECIALIST:erp", "scope": "title_or_teaser"},
        {"pattern": r"\btreasury\b|\bcore banking\b|\bloan systems?\b|\bmarket data\b", "reason": "CARD_SPECIALIST:treasury", "scope": "title_or_teaser"},
        {"pattern": r"\binsurance\b|\bguidewire\b|\bund(er)?writing\b|\bclaims?\b|\bpolicycenter\b|\bclaimcenter\b", "reason": "CARD_SPECIALIST:insurance", "scope": "title_or_teaser"},
        {"pattern": r"\bfinancial systems?\b|\bfinance systems?\b|\bfinance transformation\b|\bfinance function\b", "reason": "CARD_SPECIALIST:finance", "scope": "title_or_teaser"},
        {"pattern": r"\bsalesforce\b|\bsfmc\b|\bcrm platform\b", "reason": "CARD_SPECIALIST:salesforce", "scope": "title_or_teaser"},
        {"pattern": r"\bmachine learning\b|\bdata science\b|\bpredictive analytics\b|\badvanced analytics\b", "reason": "CARD_SPECIALIST:data_ml", "scope": "title_or_teaser"},
        {"pattern": r"\bsupply chain\b|\bprocurement\b|\bwarehouse management\b", "reason": "CARD_SPECIALIST:supply_chain", "scope": "title_or_teaser"},
    ],
    "dominant_signal_clusters": [
        {
            "name": "telecommunications and oss/bss context",
            "aliases": [
                "telecommunications",
                "telecom",
                "wholesale telecommunications",
                "enterprise telecommunications",
                "oss",
                "bss",
                "provisioning",
                "network operations",
                "service assurance",
                "carrier",
            ],
            "fit_label": "Telecommunications context",
            "watchout_label": "Role leans toward telecommunications or OSS/BSS delivery depth",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 3,
            "partial_penalty": 8,
            "weak_penalty": 11,
        },
        {
            "name": "finance systems and accounting context",
            "aliases": [
                "finance systems",
                "financial systems",
                "treasury",
                "accounting",
                "general ledger",
                "accounts payable",
                "accounts receivable",
                "reconciliation",
                "month end",
                "year end",
            ],
            "fit_label": "Finance systems context",
            "watchout_label": "Role leans toward finance systems or accounting background",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 3,
            "partial_penalty": 8,
            "weak_penalty": 11,
        },
        {
            "name": "data reporting and analytics track",
            "aliases": [
                "reporting",
                "power bi",
                "tableau",
                "data analytics",
                "analytics",
                "data visualisation",
                "bi",
                "business intelligence",
                "dashboarding",
                "data modelling",
            ],
            "fit_label": "Data and reporting context",
            "watchout_label": "Role leans toward a data, BI, or analytics-heavy profile",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 2,
            "partial_penalty": 7,
            "weak_penalty": 10,
        },
        {
            "name": "erp or platform-heavy implementation",
            "aliases": [
                "erp",
                "platform implementation",
                "vendor selection",
                "vendor evaluation",
                "oracle",
                "sap",
                "dynamics 365",
                "netsuite",
                "salesforce",
                "platform migration",
            ],
            "fit_label": "Platform implementation context",
            "watchout_label": "Role leans toward ERP or platform implementation depth",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 3,
            "partial_penalty": 8,
            "weak_penalty": 11,
        },
        {
            "name": "structured change management track",
            "aliases": [
                "adkar",
                "change management",
                "change impact",
                "change readiness",
                "communications plan",
                "training plan",
                "stakeholder change",
                "change framework",
            ],
            "fit_label": "Structured change delivery context",
            "watchout_label": "Role leans toward structured change management depth",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 2,
            "partial_penalty": 6,
            "weak_penalty": 9,
        },
        {
            "name": "higher education domain",
            "aliases": [
                "higher education",
                "university",
                "student systems",
                "student lifecycle",
                "curriculum",
                "enrolment",
                "tertiary",
            ],
            "fit_label": "Higher education context",
            "watchout_label": "Role leans toward higher education domain experience",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 2,
            "partial_penalty": 6,
            "weak_penalty": 9,
        },
        {
            "name": "healthcare and care services domain",
            "aliases": [
                "healthcare",
                "hospital",
                "clinical",
                "patient",
                "aged care",
                "health service",
                "ehealth",
                "care pathway",
            ],
            "fit_label": "Healthcare context",
            "watchout_label": "Role leans toward healthcare or care-services experience",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 2,
            "partial_penalty": 6,
            "weak_penalty": 9,
        },
        {
            "name": "insurance domain and platforms",
            "aliases": [
                "insurance",
                "claims",
                "underwriting",
                "policy",
                "guidewire",
                "policycenter",
                "claimcenter",
                "broker",
            ],
            "fit_label": "Insurance context",
            "watchout_label": "Role leans toward insurance domain or platform experience",
            "min_alias_hits": 2,
            "min_snippet_hits": 2,
            "positive_bonus": 2,
            "partial_penalty": 7,
            "weak_penalty": 10,
        },
    ],
    "target_title_patterns": [
        r"\bbusiness analyst\b",
        r"\btechnical business analyst\b",
        r"\bsenior business analyst\b",
        r"\blead business analyst\b",
        r"\bprincipal business analyst\b",
        r"\bdigital business analyst\b",
        r"\bpayments business analyst\b",
        r"\bgovernment business analyst\b",
        r"\bbusiness systems analyst\b",
        r"\bbusiness process analyst\b",
        r"\bsenior ba\b",
        r"\blead ba\b",
        r"\btech(?:nical)?\s+ba\b",
    ],
    "adjacent_title_patterns": [
        r"\bsystems analyst\b",
        r"\bit systems analyst\b",
        r"\bfunctional analyst\b",
        r"\bfunctional consultant\b",
        r"\bimplementation consultant\b",
        r"\bimplementation specialist\b",
        r"\bconsultant\b.*\bimplementation\b",
        r"\bimplementation\b.*\bconsultant\b",
    ],
    "must_not_require_skills": [
        "hubspot",
        "hubspot crm",
        "salesforce",
        "servicenow",
        "workday",
        "sap",
        "oracle",
        "pega",
        "d365",
        "dynamics 365",
    ],
    "canberra_only_description_patterns": [
        r"\bmust be based in canberra\b",
        r"\bmust reside in canberra\b",
        r"\bcanberra[- ]based\b",
        r"\blocated in canberra\b.{0,40}\b(required|mandatory|essential)\b",
        r"\bcanberra office\b.{0,50}\b(required|mandatory|essential|5 days|full[- ]time)\b",
        r"\bonsite in canberra\b",
        r"\bwork from canberra\b",
    ],
    "reject_title_rules": [
        {"pattern": r"\bproject manager\b", "reason": "TITLE_BAD_ROLE:project manager"},
        {"pattern": r"\bprogram manager\b", "reason": "TITLE_BAD_ROLE:program manager"},
        {"pattern": r"\bproduct manager\b", "reason": "TITLE_BAD_ROLE:product manager"},
        {"pattern": r"\bproduct owner\b", "reason": "TITLE_BAD_ROLE:product owner"},
        {"pattern": r"\bscrum master\b", "reason": "TITLE_BAD_ROLE:scrum master"},
        {"pattern": r"\bchange analyst\b", "reason": "TITLE_BAD_ROLE:change analyst"},
        {"pattern": r"\bservice transition\b", "reason": "TITLE_BAD_ROLE:service transition"},
        {"pattern": r"\bapplication support\b", "reason": "TITLE_BAD_ROLE:application support"},
        {"pattern": r"\bsupport analyst\b", "reason": "TITLE_BAD_ROLE:support analyst"},
        {"pattern": r"\bdata governance\b", "reason": "TITLE_BAD_ROLE:data governance"},
        {"pattern": r"\bdeveloper\b", "reason": "TITLE_BAD_ROLE:developer"},
        {"pattern": r"\bengineer\b", "reason": "TITLE_BAD_ROLE:engineer"},
        {"pattern": r"\btester\b|\btest analyst\b|\bqa\b", "reason": "TITLE_BAD_ROLE:testing"},
        {"pattern": r"\bintern\b", "reason": "TITLE_BAD_ROLE:intern"},
        {"pattern": r"\bofficer\b", "reason": "TITLE_BAD_ROLE:officer"},
        {"pattern": r"\bcoordinator\b", "reason": "TITLE_BAD_ROLE:coordinator"},
        {"pattern": r"\bservicenow\b", "reason": "TITLE_BAD_KEYWORD:servicenow"},
        {"pattern": r"\bdynamics\s*365\b|\bd365\b", "reason": "TITLE_BAD_KEYWORD:d365"},
        {"pattern": r"\bms\s*dynamics\b", "reason": "TITLE_BAD_KEYWORD:ms dynamics"},
        {"pattern": r"\bzoho\b", "reason": "TITLE_BAD_KEYWORD:zoho"},
        {"pattern": r"\bsalesforce\b", "reason": "TITLE_BAD_KEYWORD:salesforce"},
        {"pattern": r"\bworkday\b", "reason": "TITLE_BAD_KEYWORD:workday"},
        {"pattern": r"\bsap\b", "reason": "TITLE_BAD_KEYWORD:sap"},
        {"pattern": r"\boracle\b", "reason": "TITLE_BAD_KEYWORD:oracle"},
        {"pattern": r"\bnetsuite\b", "reason": "TITLE_BAD_KEYWORD:netsuite"},
        {"pattern": r"\bunderwriting\b", "reason": "TITLE_BAD_KEYWORD:underwriting"},
        {"pattern": r"\bcyber\b", "reason": "TITLE_BAD_KEYWORD:cyber"},
        {"pattern": r"\bsecurity\b", "reason": "TITLE_BAD_KEYWORD:security"},
    ],
    "reject_description_phrase_rules": [
        {"phrase": "wealth management", "reason": "DESC_FINANCE:wealth management"},
        {"phrase": "private banking", "reason": "DESC_FINANCE:private banking"},
        {"phrase": "private wealth", "reason": "DESC_FINANCE:private wealth"},
        {"phrase": "funds management", "reason": "DESC_FINANCE:funds management"},
        {"phrase": "portfolio management", "reason": "DESC_FINANCE:portfolio management"},
        {"phrase": "treasury", "reason": "DESC_TREASURY:treasury"},
        {"phrase": "loan systems", "reason": "DESC_TREASURY:loan systems"},
        {"phrase": "loan system", "reason": "DESC_TREASURY:loan system"},
        {"phrase": "core banking", "reason": "DESC_TREASURY:core banking"},
        {"phrase": "derivatives", "reason": "DESC_TREASURY:derivatives"},
        {"phrase": "market data feed", "reason": "DESC_TREASURY:market data feed"},
        {"phrase": "debt instruments", "reason": "DESC_TREASURY:debt instruments"},
        {"phrase": "amortization", "reason": "DESC_TREASURY:amortization"},
        {"phrase": "cyber security", "reason": "DESC_NOT_MY_DOMAIN:cyber security"},
        {"phrase": "cybersecurity", "reason": "DESC_NOT_MY_DOMAIN:cybersecurity"},
        {"phrase": "information security", "reason": "DESC_NOT_MY_DOMAIN:information security"},
        {"phrase": "security operations", "reason": "DESC_NOT_MY_DOMAIN:security operations"},
        {"phrase": "threat detection", "reason": "DESC_NOT_MY_DOMAIN:threat detection"},
        {"phrase": "threat hunting", "reason": "DESC_NOT_MY_DOMAIN:threat hunting"},
        {"phrase": "identity and access management", "reason": "DESC_NOT_MY_DOMAIN:identity and access management"},
        {"phrase": "zero trust", "reason": "DESC_NOT_MY_DOMAIN:zero trust"},
    ],
    "reject_description_regex_rules": [
        {"pattern": r"\bfinance systems?\b", "reason": "DESC_ERP_FIN:finance systems"},
        {"pattern": r"\bfinancial systems?\b", "reason": "DESC_ERP_FIN:financial systems"},
        {"pattern": r"\bfinance function\b", "reason": "DESC_ERP_FIN:finance function"},
        {"pattern": r"\bgeneral ledger\b|\bgl\b", "reason": "DESC_ERP_FIN:general ledger"},
        {"pattern": r"\baccounts payable\b|\baccounts receivable\b", "reason": "DESC_ERP_FIN:ap ar"},
        {"pattern": r"\bpayable\b|\breceivable\b", "reason": "DESC_ERP_FIN:payable receivable"},
        {"pattern": r"\bmonth[- ]end\b|\byear[- ]end\b", "reason": "DESC_ERP_FIN:month end"},
        {"pattern": r"\breconciliation\b", "reason": "DESC_ERP_FIN:reconciliation"},
        {"pattern": r"\bchart of accounts\b", "reason": "DESC_ERP_FIN:chart of accounts"},
    ],
}


def ensure_profile_exists() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PROFILE_PATH.exists():
        return
    save_profile(DEFAULT_PROFILE)


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = _deep_merge(copy.deepcopy(DEFAULT_PROFILE), data)
            merged["search_settings"] = normalize_search_settings(merged.get("search_settings", {}))
            merged["salary_preferences"] = normalize_salary_preferences(merged.get("salary_preferences", {}))
            merged["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
                merged.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
            )
            merged["evidence_tiers"] = normalize_evidence_tiers(
                merged.get("evidence_tiers", {}),
                merged.get("cv_text", ""),
            )
            merged["evidence_tier_weights"] = normalize_evidence_tier_weights(
                merged.get("evidence_tier_weights", {})
            )
            return merged
    except Exception:
        pass
    fallback = copy.deepcopy(DEFAULT_PROFILE)
    fallback["search_settings"] = normalize_search_settings(fallback.get("search_settings", {}))
    fallback["salary_preferences"] = normalize_salary_preferences(fallback.get("salary_preferences", {}))
    fallback["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
        fallback.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
    )
    fallback["evidence_tiers"] = normalize_evidence_tiers(
        fallback.get("evidence_tiers", {}),
        fallback.get("cv_text", ""),
    )
    fallback["evidence_tier_weights"] = normalize_evidence_tier_weights(
        fallback.get("evidence_tier_weights", {})
    )
    return fallback


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(profile)
    normalized["search_settings"] = normalize_search_settings(normalized.get("search_settings", {}))
    normalized["salary_preferences"] = normalize_salary_preferences(normalized.get("salary_preferences", {}))
    normalized["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
        normalized.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
    )
    normalized["evidence_tiers"] = normalize_evidence_tiers(
        normalized.get("evidence_tiers", {}),
        normalized.get("cv_text", ""),
    )
    normalized["evidence_tier_weights"] = normalize_evidence_tier_weights(
        normalized.get("evidence_tier_weights", {})
    )
    PROFILE_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(patch)


def patch_profile(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_profile()
    merged = _deep_merge(current, patch)
    return save_profile(merged)


def normalize_search_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(copy.deepcopy(DEFAULT_SEARCH_SETTINGS), settings or {})

    try:
        merged["date_range_days"] = max(
            MIN_DATE_RANGE_DAYS,
            min(int(merged.get("date_range_days", DEFAULT_SEARCH_SETTINGS["date_range_days"])), MAX_DATE_RANGE_DAYS),
        )
    except Exception:
        merged["date_range_days"] = DEFAULT_SEARCH_SETTINGS["date_range_days"]

    try:
        merged["max_pages_cap"] = max(
            MIN_PAGES_CAP,
            min(int(merged.get("max_pages_cap", DEFAULT_SEARCH_SETTINGS["max_pages_cap"])), MAX_PAGES_CAP_HARD_LIMIT),
        )
    except Exception:
        merged["max_pages_cap"] = DEFAULT_SEARCH_SETTINGS["max_pages_cap"]

    merged["enforce_posted_age_limit"] = bool(merged.get("enforce_posted_age_limit", True))
    merged["sort_newest_first"] = bool(merged.get("sort_newest_first", True))
    merged["keywords"] = str(merged.get("keywords") or "").strip()
    merged["locations"] = [str(value).strip() for value in merged.get("locations", []) if str(value).strip()]
    merged["classification_ids"] = [
        str(value).strip() for value in merged.get("classification_ids", []) if str(value).strip()
    ]
    return merged


def normalize_salary_preferences(payload: dict[str, Any] | None) -> dict[str, int]:
    source = payload if isinstance(payload, dict) else {}
    try:
        minimum_salary_yearly = max(0, int(source.get("minimum_salary_yearly", 0) or 0))
    except Exception:
        minimum_salary_yearly = 0
    try:
        minimum_daily_rate = max(0, int(source.get("minimum_daily_rate", 0) or 0))
    except Exception:
        minimum_daily_rate = 0
    return {
        "minimum_salary_yearly": minimum_salary_yearly,
        "minimum_daily_rate": minimum_daily_rate,
    }


def normalize_llm_profile_brief_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "manual":
        return "manual"
    return DEFAULT_LLM_PROFILE_BRIEF_MODE


def classify_evidence_section_label(label: str) -> str:
    lowered = str(label or "").strip().lower()
    if not lowered:
        return "primary_current_evidence"
    if any(token in lowered for token in ("primary", "detailed", "current", "recent", "main", "core")):
        return "primary_current_evidence"
    if any(token in lowered for token in ("supporting", "older", "secondary", "legacy", "earlier", "previous")):
        return "secondary_older_evidence"
    if any(token in lowered for token in ("background", "optional", "extra", "additional", "note", "notes", "cert", "education")):
        return "background_optional_evidence"
    return "primary_current_evidence"


def _combine_unique_sections(parts: list[str]) -> str:
    seen: set[str] = set()
    cleaned_parts: list[str] = []
    for item in parts:
        text = str(item or "").strip()
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned_parts.append(text)
    return "\n\n".join(cleaned_parts).strip()


def build_evidence_tiers_from_sections(sections: list[dict[str, str]] | None) -> dict[str, str]:
    buckets = {key: [] for key in DEFAULT_EVIDENCE_TIERS}
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "").strip()
        text = str(section.get("text") or "").strip()
        if not text:
            continue
        bucket = classify_evidence_section_label(label)
        buckets[bucket].append(text)
    return {
        bucket: _combine_unique_sections(parts)
        for bucket, parts in buckets.items()
    }


def infer_evidence_tiers_from_cv_text(cv_text: str) -> dict[str, str]:
    text = str(cv_text or "").strip()
    if not text:
        return dict(DEFAULT_EVIDENCE_TIERS)

    heading_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if heading_matches:
        sections: list[dict[str, str]] = []
        for index, match in enumerate(heading_matches):
            label = match.group(1).strip()
            start = match.end()
            end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
            body = text[start:end].strip()
            if body:
                sections.append({"label": label, "text": body})
        tiers = build_evidence_tiers_from_sections(sections)
        if any(tiers.values()):
            return tiers

    if "supporting background" in text.lower():
        parts = re.split(r"(?im)^##\s+supporting background\s*$", text, maxsplit=1)
        primary = parts[0].strip()
        secondary = parts[1].strip() if len(parts) > 1 else ""
        return {
            "primary_current_evidence": primary,
            "secondary_older_evidence": secondary,
            "background_optional_evidence": "",
        }

    return {
        "primary_current_evidence": text,
        "secondary_older_evidence": "",
        "background_optional_evidence": "",
    }


def normalize_evidence_tiers(payload: dict[str, Any] | None, cv_text: str = "") -> dict[str, str]:
    normalized = dict(DEFAULT_EVIDENCE_TIERS)
    source = payload if isinstance(payload, dict) else {}
    inferred = infer_evidence_tiers_from_cv_text(cv_text)
    for key in normalized:
        value = str(source.get(key) or "").strip()
        normalized[key] = value or inferred.get(key, "")
    return normalized


def normalize_evidence_tier_weights(payload: dict[str, Any] | None) -> dict[str, float]:
    source = payload if isinstance(payload, dict) else {}
    normalized = dict(DEFAULT_EVIDENCE_TIER_WEIGHTS)
    for key, default in DEFAULT_EVIDENCE_TIER_WEIGHTS.items():
        try:
            value = float(source.get(key, default) or default)
        except Exception:
            value = default
        normalized[key] = max(min(value, 1.0), 0.0)
    return normalized


def get_evidence_tiers(profile: dict[str, Any]) -> dict[str, str]:
    return normalize_evidence_tiers(
        profile.get("evidence_tiers", {}),
        str(profile.get("cv_text") or ""),
    )


def get_evidence_tier_weights(profile: dict[str, Any]) -> dict[str, float]:
    return normalize_evidence_tier_weights(profile.get("evidence_tier_weights", {}))


def get_search_settings(profile: dict[str, Any]) -> dict[str, Any]:
    return normalize_search_settings(profile.get("search_settings", {}))
