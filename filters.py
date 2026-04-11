# filters.py

import re
from typing import Tuple

from profile_store import load_profile


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns if pattern)


def passes_title_filters(title: str) -> Tuple[bool, str]:
    """
    Title-based gatekeeping.
    Returns (True, "OK") if title is acceptable, else (False, "REASON").
    """
    if not title:
        return False, "TITLE_EMPTY"

    profile = load_profile()
    title_lower = title.strip().lower()

    target_patterns = profile.get("target_title_patterns", [])
    adjacent_patterns = profile.get("adjacent_title_patterns", [])
    is_direct_match = _matches_any(title_lower, target_patterns)
    is_adjacent_match = _matches_any(title_lower, adjacent_patterns)

    if not is_direct_match and not is_adjacent_match:
        return False, "TITLE_NOT_TARGET"

    for rule in profile.get("reject_title_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"TITLE_REJECT:{pattern}")
        if pattern and re.search(pattern, title_lower):
            return False, reason

    if is_direct_match:
        return True, "OK"
    return True, "TITLE_POTENTIAL_MATCH"


def passes_content_filters(details_text: str) -> Tuple[bool, str]:
    """
    Description-based filtering.
    Returns (True, "OK") if description fits, else (False, "REASON").
    """
    if not details_text:
        return False, "DESC_EMPTY"

    profile = load_profile()
    description_lower = details_text.lower()

    for rule in profile.get("reject_description_phrase_rules", []):
        phrase = (rule.get("phrase") or "").strip().lower()
        reason = rule.get("reason", f"DESC_REJECT:{phrase}")
        if phrase and phrase in description_lower:
            return False, reason

    for rule in profile.get("reject_description_regex_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"DESC_REJECT:{pattern}")
        if pattern and re.search(pattern, description_lower):
            return False, reason

    return True, "OK"
