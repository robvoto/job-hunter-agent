"""Deterministic filter helpers.

Purpose: apply the early title and capability filters without guessing around
bad rule data.
"""

import re
from typing import Any, Tuple

from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.profile_store import KEY_CANDIDATE_CAPABILITIES, load_profile
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.title_normalization_rules import normalize_title_text

def _normalize_title_pattern_text(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace(r"\b", " ").replace(r"\B", " ").replace(r"\A", " ").replace(r"\Z", " ")
    raw = raw.replace("\\", " ")
    return normalize_title_text(raw).strip()


def _get_synonym_group(role: str) -> set[str]:
    """Return all roles in the same synonym group as role, including role itself."""
    groups = load_parsing_rules().get("title_role_synonyms", [])
    for group in groups:
        normalized = [normalize_title_text(r) for r in group]
        if role in normalized:
            return set(normalized)
    return {role}


def _find_matching_title_pattern(text: str, patterns: list[str]) -> str:
    normalized_text = normalize_title_text(text)
    if not normalized_text:
        return ""
    text_synonyms = _get_synonym_group(normalized_text)
    for pattern in patterns:
        cleaned = _normalize_title_pattern_text(pattern)
        if not cleaned:
            continue
        pattern_synonyms = _get_synonym_group(cleaned)
        # Match if any synonym of the text equals any synonym of the pattern
        if text_synonyms & pattern_synonyms:
            return cleaned
        if any(re.search(rf"\b{re.escape(s)}\b", normalized_text) for s in pattern_synonyms):
            return cleaned
        if any(re.search(rf"\b{re.escape(normalized_text)}\b", s) for s in pattern_synonyms):
            return cleaned
    return ""


def _matches_normalized_title(text: str, patterns: list[str]) -> bool:
    return bool(_find_matching_title_pattern(text, patterns))


def analyze_title_filters(title: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "reason": "TITLE_EMPTY",
        "normalized_title": "",
        "match_family": "",
        "matched_pattern": "",
        "warning_reason": "",
    }
    if not title:
        return result

    profile = profile if isinstance(profile, dict) else load_profile()
    normalized_title = normalize_title_text(title)
    target_patterns = profile.get("target_roles", [])
    adjacent_patterns = profile.get("also_consider_roles", [])
    matched_primary_pattern = _find_matching_title_pattern(normalized_title, target_patterns)
    matched_secondary_pattern = _find_matching_title_pattern(normalized_title, adjacent_patterns)
    is_direct_match = bool(matched_primary_pattern)
    is_adjacent_match = bool(matched_secondary_pattern)

    result["normalized_title"] = normalized_title
    result["matched_pattern"] = matched_primary_pattern or matched_secondary_pattern

    for rule in profile.get("reject_title_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"TITLE_REJECT:{pattern}")
        if pattern and re.search(pattern, normalized_title):
            result["reason"] = reason
            return result

    if is_direct_match:
        if _has_numeric_title_level(normalized_title):
            result.update(
                {"ok": True, "reason": TITLE_REASON_POTENTIAL_MATCH, "match_family": "primary"}
            )
            return result
        result.update({"ok": True, "reason": "OK", "match_family": "primary"})
        return result

    if is_adjacent_match:
        result.update(
            {"ok": True, "reason": TITLE_REASON_POTENTIAL_MATCH, "match_family": "secondary"}
        )
        return result

    result.update({"ok": False, "reason": "TITLE_NOT_TARGET", "match_family": "none"})
    return result


def normalize_title_block_phrase(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()
    if not cleaned:
        return ""
    tokens = [token for token in cleaned.split() if token]
    if not tokens:
        return ""
    return " ".join(tokens[:3])


_TITLE_QUALIFIER_NOISE = frozenset(
    {
        "senior", "sr", "junior", "jr", "lead", "principal", "head",
        "digital", "technology", "tech", "contract", "permanent",
        "full", "time", "part", "remote", "hybrid",
    }
)


def suggest_title_block_phrase(
    title: str, profile: dict[str, Any] | None = None
) -> str:
    """Suggest a conservative distinguishing qualifier for manual title blocking."""

    raw_title = str(title or "").strip()
    if not raw_title:
        return ""

    analysis = analyze_title_filters(raw_title, profile)
    matched_pattern = normalize_title_block_phrase(str(analysis.get("matched_pattern") or ""))

    def usable(candidate: str) -> str:
        normalized = normalize_title_block_phrase(candidate)
        if not normalized or normalized == matched_pattern:
            return ""
        tokens = [token for token in normalized.split() if token not in _TITLE_QUALIFIER_NOISE]
        if not tokens:
            return ""
        result = " ".join(tokens[:3])
        if matched_pattern and result == matched_pattern:
            return ""
        return result

    for candidate in reversed(re.findall(r"\(([^()]*)\)", raw_title)):
        suggestion = usable(candidate)
        if suggestion:
            return suggestion

    segments = [
        part.strip()
        for part in re.split(r"\s*(?:\||:|–|—)\s*", raw_title)
        if part.strip()
    ]
    if len(segments) > 1:
        for candidate in reversed(segments):
            normalized_candidate = normalize_title_block_phrase(candidate)
            if matched_pattern and matched_pattern in normalized_candidate:
                continue
            suggestion = usable(candidate)
            if suggestion:
                return suggestion

    normalized_title = normalize_title_block_phrase(raw_title)
    if matched_pattern:
        residual = re.sub(
            rf"(?<!\w){re.escape(matched_pattern)}(?!\w)", " ", normalized_title
        )
        residual_tokens = [
            token for token in residual.split() if token not in _TITLE_QUALIFIER_NOISE
        ]
        if 1 <= len(residual_tokens) <= 3:
            return " ".join(residual_tokens)

    return ""


def build_title_block_rule(phrase: str) -> dict[str, str]:
    normalized = normalize_title_block_phrase(phrase)
    if not normalized:
        raise ValueError("Title block phrase is required")

    tokens = [token for token in normalized.split() if token]
    if not tokens:
        raise ValueError("Title block phrase is required")

    pattern = r"\b" + r"\s+".join(re.escape(token) for token in tokens) + r"\b"
    return {
        "pattern": pattern,
        "reason": f"TITLE_BAD_KEYWORD:{normalized}",
    }


def _has_numeric_title_level(text: str) -> bool:
    if not re.search(r"\b(?:\d+|ii|iii|iv|v)\b", text):
        return False

    numeric_suffix = r"[\W_]{0,5}(?:\b(?:level|grade|tier|band|class)\b[\W_]{0,5})?(?:\d+(?:st|nd|rd|th)?|ii|iii|iv|v)\b"
    return bool(re.search(numeric_suffix, text))


def _normalize_reason_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return cleaned.strip("_") or "unknown"


_KNOWN_CAPABILITY_LEVELS = {"strong", "working", "basic", "low"}


def _normalize_level(value: str) -> str | None:
    level = (value or "").strip().lower()
    if not level:
        return None
    aliases = load_parsing_rules().get("level_aliases", {})
    resolved = aliases.get(level, level)
    if resolved not in _KNOWN_CAPABILITY_LEVELS:
        return None
    return resolved


def _record_capability_level_warning(name: str, raw_level: str, reason: str) -> None:
    normalized_name = _normalize_reason_token(name)
    fingerprint = make_system_warning_fingerprint("filters", normalized_name, raw_level, reason)
    record_system_warning(
        severity="warning",
        category="profile_capability_level",
        source="filters",
        message=(
            f"Capability rule {name!r} has {reason.replace('_', ' ')} level {raw_level!r}; "
            "it will not be treated as basic."
        ),
        fingerprint=fingerprint,
        context={
            "capability_name": name,
            "raw_level": raw_level,
            "reason": reason,
        },
    )


def _count_alias_hits(text: str, aliases: list[str]) -> tuple[int, int]:
    total_hits = 0
    distinct_hits = 0
    for alias in aliases:
        alias_lower = (alias or "").strip().lower()
        if not alias_lower:
            continue
        pattern = rf"(?<!\w){re.escape(alias_lower)}(?!\w)"
        matches = re.findall(pattern, text)
        if matches:
            total_hits += len(matches)
            distinct_hits += 1
    return total_hits, distinct_hits


def _load_required_parsing_rule_terms(rule_key: str) -> list[str]:
    rules = load_parsing_rules()
    values = rules.get(rule_key)
    if not isinstance(values, list):
        raise ValueError(f"parsing_rules.json must define {rule_key}")

    terms = [str(value).strip().lower() for value in values if str(value).strip()]
    if not terms:
        raise ValueError(f"parsing_rules.json must define at least one {rule_key}")
    return terms


def _evaluate_capability_profile(description_lower: str, profile: dict) -> Tuple[bool, str]:
    capability_rules = profile.get(KEY_CANDIDATE_CAPABILITIES, [])
    positive_hits = 0
    warning_reason = "OK"

    for rule in capability_rules:
        name = str(rule.get("name") or "").strip()
        raw_level = str(rule.get("level") or "").strip()
        level = _normalize_level(raw_level)
        canonical = canonical_capability_term(rule)
        if not name or not canonical:
            continue

        if level is None:
            if warning_reason == "OK":
                warning_reason = f"DESC_CAPABILITY_LEVEL_UNREVIEWED:{_normalize_reason_token(name)}"
            _record_capability_level_warning(
                name,
                raw_level or "<missing>",
                "missing" if not raw_level else "unrecognized",
            )
            continue

        _, distinct_hits = _count_alias_hits(description_lower, [canonical])
        if level in {"strong", "working"}:
            positive_hits += distinct_hits

        reason_token = _normalize_reason_token(name)

        if level == "low" and distinct_hits >= 3:
            if warning_reason == "OK":
                warning_reason = f"DESC_CAPABILITY_LOW:{reason_token}"
        if level == "basic" and distinct_hits >= 2:
            if warning_reason == "OK":
                warning_reason = f"DESC_CAPABILITY_BASIC:{reason_token}"
        if level in {"low", "basic"} and distinct_hits >= 4 and positive_hits <= 2:
            if warning_reason == "OK":
                warning_reason = f"DESC_PRIMARY_FOCUS:{reason_token}"

    return True, warning_reason


def passes_title_filters(title: str) -> Tuple[bool, str]:
    """
    Title-based gatekeeping.
    Returns (True, "OK") if title is acceptable, else (False, "REASON").
    """
    analysis = analyze_title_filters(title)
    return bool(analysis["ok"]), str(analysis["reason"])


def passes_content_filters(
    details_text: str,
    card_location: str = "",
    title_reason: str = "",
    profile: dict | None = None,
) -> Tuple[bool, str]:
    """
    Description-based filtering.
    Returns (True, "OK") if description fits, else (False, "REASON").
    """
    if not details_text:
        return False, "DESC_EMPTY"

    profile = profile or load_profile()
    description_lower = details_text.lower()
    for rule in profile.get("reject_description_phrase_rules", []):
        phrase = (rule.get("phrase") or "").strip().lower()
        reason = rule.get("reason", f"DESC_REJECT:{phrase}")
        if phrase and phrase in description_lower:
            return False, reason

    hard_block_matches = find_hard_block_matches(
        details_text, profile.get("must_not_require_skills", [])
    )
    for match in hard_block_matches:
        token = _normalize_reason_token(match.get("matched_term") or "")
        if token:
            return False, f"DESC_HARD_BLOCK_RULE:{token}"

    ok_capability, capability_reason = _evaluate_capability_profile(description_lower, profile)
    if not ok_capability:
        return False, capability_reason

    if hard_block_matches:
        return (
            False,
            f"DESC_HARD_BLOCK_RULE:{_normalize_reason_token(hard_block_matches[0].get('matched_term') or '')}",
        )

    if capability_reason != "OK":
        return True, capability_reason

    return True, "OK"


def passes_quick_card_filters(
    title: str,
    teaser: str = "",
    company: str = "",
    location: str = "",
    work_mode: str = "",
    work_type: str = "",
    salary: str = "",
    profile: dict | None = None,
) -> Tuple[bool, str]:
    profile = profile or load_profile()
    teaser_lower = (teaser or "").strip().lower()
    title_context = "\n".join(
        part
        for part in [
            (title or "").strip(),
            teaser_lower,
            (company or "").strip().lower(),
            (location or "").strip().lower(),
            (work_mode or "").strip().lower(),
            (work_type or "").strip().lower(),
            (salary or "").strip().lower(),
        ]
        if part
    )
    normalized_title = normalize_title_text(title, title_context)
    combined = "\n".join(
        part
        for part in [
            normalized_title,
            teaser_lower,
            (company or "").strip().lower(),
            (location or "").strip().lower(),
            (work_mode or "").strip().lower(),
            (work_type or "").strip().lower(),
            (salary or "").strip().lower(),
        ]
        if part
    )
    counter_patterns = profile.get("cheap_keep_counter_patterns", [])
    counter_hits = sum(
        1 for pattern in counter_patterns if pattern and re.search(pattern, combined)
    )
    direct_target_title = _matches_normalized_title(
        normalized_title, profile.get("target_roles", [])
    )

    for rule in profile.get("cheap_reject_metadata_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"CARD_SPECIALIST:{pattern}")
        scope = str(rule.get("scope") or "title_or_teaser").strip().lower()
        haystack = teaser_lower
        if scope == "title":
            haystack = normalized_title
        elif scope == "teaser":
            haystack = teaser_lower
        else:
            haystack = "\n".join(part for part in [normalized_title, teaser_lower] if part)

        if not pattern or not haystack or not re.search(pattern, haystack):
            continue

        title_has_specialist_signal = bool(re.search(pattern, normalized_title))
        unusually_strong_counter = (
            direct_target_title and counter_hits >= 4 and not title_has_specialist_signal
        )
        if unusually_strong_counter:
            continue
        return False, reason

    return True, "OK"
