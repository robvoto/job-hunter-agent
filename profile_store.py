import copy
import json
from pathlib import Path
from typing import Any


PROFILE_PATH = Path("profile.json")

DEFAULT_PROFILE = {
    "search_settings": {
        "date_range_days": 3,
        "max_pages_cap": 10,
        "enforce_posted_age_limit": True,
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
    "llm_prompt_notes": [
        "Prefer roles centered on discovery, requirements, delivery, process improvement, and stakeholder engagement.",
        "Allow BA-adjacent roles like systems analyst or implementation consultant if the description still reads like a fit.",
        "Reject hands-on security or cyber roles.",
        "Reject specialist platform roles when they are mainly configuration, engineering, or admin rather than business analysis.",
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
    if PROFILE_PATH.exists():
        return
    save_profile(DEFAULT_PROFILE)


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return _deep_merge(copy.deepcopy(DEFAULT_PROFILE), data)
    except Exception:
        pass
    return copy.deepcopy(DEFAULT_PROFILE)


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return profile


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
