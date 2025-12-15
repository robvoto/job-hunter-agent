# filters.py

import re
from typing import Tuple


def passes_title_filters(title: str) -> Tuple[bool, str]:
    """
    Title-based gatekeeping.
    Returns (True, "OK") if title is acceptable, else (False, "REASON").
    """
    if not title:
        return False, "TITLE_EMPTY"

    title_lower = title.strip().lower()

    # Step 1: Must look like a BA role (tight)
    allowed_ba_title_patterns = [
        r"\bbusiness analyst\b",
        r"\btechnical business analyst\b",
        r"\bsenior business analyst\b",
        r"\blead business analyst\b",
        r"\bprincipal business analyst\b",
        r"\bdigital business analyst\b",
        r"\bpayments business analyst\b",
        r"\bgovernment business analyst\b",
    ]
    if not any(re.search(pattern, title_lower) for pattern in allowed_ba_title_patterns):
        return False, "TITLE_NOT_BA"

    # Step 2: Reject roles that aren't BA even if they contain BA-ish wording
    bad_role_patterns = [
        r"\bproject manager\b",
        r"\bprogram manager\b",
        r"\bproduct manager\b",
        r"\bproduct owner\b",
        r"\bscrum master\b",
        r"\bchange analyst\b",
        r"\bservice transition\b",
        r"\bapplication support\b",
        r"\bsupport analyst\b",
        r"\bdata governance\b",
        r"\bdeveloper\b",
        r"\bengineer\b",
        r"\btester\b|\btest analyst\b|\bqa\b",
        r"\bconsultant\b",
        r"\bintern\b",
        r"\bofficer\b",
        r"\bcoordinator\b",
    ]
    for pattern in bad_role_patterns:
        if re.search(pattern, title_lower):
            return False, f"TITLE_BAD_ROLE:{pattern}"

    # Step 3: Reject titles that are basically tool/platform specialists (not you)
    bad_title_patterns = [
        r"\bservicenow\b",
        r"\bdynamics\s*365\b",
        r"\bms\s*dynamics\b",
        r"\bzoho\b",
        r"\bsalesforce\b",
        r"\bworkday\b",
        r"\bsap\b",
        r"\boracle\b",
        r"\bnetsuite\b",
        r"\bunderwriting\b",
    ]
    for pattern in bad_title_patterns:
        if re.search(pattern, title_lower):
            return False, f"TITLE_BAD_KEYWORD:{pattern}"

    return True, "OK"


def passes_content_filters(details_text: str) -> Tuple[bool, str]:
    """
    Description-based filtering.
    Returns (True, "OK") if description fits, else (False, "REASON").
    """
    if not details_text:
        return False, "DESC_EMPTY"

    description_lower = details_text.lower()

    # --- Wealth / banking style roles (not you)
    finance_bad_phrases = [
        "wealth management",
        "private banking",
        "private wealth",
        "funds management",
        "portfolio management",
    ]
    for phrase in finance_bad_phrases:
        if phrase in description_lower:
            return False, f"DESC_FINANCE:{phrase}"

    # --- Treasury / loan systems (not you)
    treasury_bad_phrases = [
        "treasury",
        "loan systems",
        "loan system",
        "core banking",
        "derivatives",
        "market data feed",
        "debt instruments",
        "amortization",
    ]
    for phrase in treasury_bad_phrases:
        if phrase in description_lower:
            return False, f"DESC_TREASURY:{phrase}"

    '''
    # --- Underwriting domain (not you)
    underwriting_patterns = [
        r"\bunderwriting\b",
        r"\bunderwriter\b",
    ]
    for pattern in underwriting_patterns:
        if re.search(pattern, description_lower):
            return False, f"DESC_UNDERWRITING:{pattern}"
    '''

    # --- ERP / Finance Systems / GL / AP AR roles (not you)
    # IMPORTANT: we do NOT reject "superannuation" because it may just be pay text.
    erp_finance_systems_patterns = [ 
        r"\bfinance systems?\b",
        r"\bfinancial systems?\b",
        r"\bfinance function\b",
        r"\bgeneral ledger\b|\bgl\b",
        r"\baccounts payable\b|\baccounts receivable\b",
        r"\bpayable\b|\breceivable\b",
        r"\bmonth[- ]end\b|\byear[- ]end\b",
        r"\breconciliation\b",
        r"\bchart of accounts\b",
    ]
    for pattern in erp_finance_systems_patterns:
        if re.search(pattern, description_lower):
            return False, f"DESC_ERP_FIN:{pattern}"

    return True, "OK"
