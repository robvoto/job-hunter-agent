# filters.py

import re
from typing import Any, Tuple

from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.profile_store import KEY_CAPABILITY_PROFILE_RULES, load_profile
from job_hunter_agent.parsing_schema import (
    KEY_P_CONF_MIN_BULLETS,
    KEY_P_CONF_MIN_COORDINATION,
    KEY_P_CONF_MIN_GENERIC,
    KEY_P_CONF_MIN_SECTIONS,
    KEY_P_CONF_MIN_LENGTH,
    KEY_P_CTX_HARD_PREFIX,
    KEY_P_CTX_HARD_SUFFIX,
    KEY_P_CTX_HARD_WINDOW,
    KEY_P_MATCHING_CONTEXT,
    KEY_P_CTX_NEGATION_WINDOW,
    KEY_P_CTX_SOFT_PREFIX,
    KEY_P_CTX_SOFT_SUFFIX,
    KEY_P_CTX_SOFT_WINDOW,
)
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.title_normalization_rules import decompose_title_text, normalize_title_text




TITLE_BLOCK_SEGMENT_SPLIT_RE = re.compile(r"\s*\|\s*|\s[-\u2013\u2014/:]\s|[(),\[\]]")


def _normalize_title_pattern_text(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace(r"\b", " ").replace(r"\B", " ").replace(r"\A", " ").replace(r"\Z", " ")
    raw = raw.replace("\\", " ")
    decomposition = decompose_title_text(raw)
    return str(decomposition.get("base_role") or decomposition.get("normalized_title") or normalize_title_text(raw)).strip()


def _get_synonym_group(role: str) -> set[str]:
    """Return all roles in the same synonym group as role, including role itself."""
    groups = load_parsing_rules().get("title_role_synonyms", [])
    for group in groups:
        normalized = [normalize_title_text(r) for r in group]
        if role in normalized:
            return set(normalized)
    return {role}


def _find_matching_title_pattern(text: str, patterns: list[str]) -> str:
    normalized_text = decompose_title_text(text).get("base_role") or normalize_title_text(text)
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


def _title_match_family_text(text: str) -> str:
    decomposition = decompose_title_text(text)
    return str(decomposition.get("base_role") or decomposition.get("normalized_title") or "").strip()


def analyze_title_filters(title: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "reason": "TITLE_EMPTY",
        "normalized_title": "",
        "base_role": "",
        "seniority_modifiers": [],
        "variant_terms": "",
        "match_family": "",
        "matched_pattern": "",
        "title_seniority": "plain",
        "primary_pattern_has_seniority": False,
        "seniority_adjustment": 0,
        "warning_reason": "",
    }
    if not title:
        return result

    profile = profile if isinstance(profile, dict) else load_profile()
    decomposition = decompose_title_text(title)
    normalized_title = str(decomposition.get("normalized_title") or "").strip()
    base_role = _title_match_family_text(title)
    target_patterns = profile.get("target_roles", [])
    adjacent_patterns = profile.get("also_consider_roles", [])
    matched_primary_pattern = ""
    primary_pattern_has_seniority = False
    for pattern in target_patterns:
        cleaned_pattern = _normalize_title_pattern_text(pattern)
        if not cleaned_pattern:
            continue
        if not matched_primary_pattern and _find_matching_title_pattern(base_role, [pattern]):
            matched_primary_pattern = cleaned_pattern
        if decompose_title_text(pattern).get("seniority_modifiers"):
            if _find_matching_title_pattern(base_role, [pattern]):
                primary_pattern_has_seniority = True
    matched_secondary_pattern = _find_matching_title_pattern(base_role, adjacent_patterns)
    is_direct_match = bool(matched_primary_pattern)
    is_adjacent_match = bool(matched_secondary_pattern)
    rules = load_parsing_rules()
    lower_sen_tokens = set(rules.get("title_seniority_groups", {}).get("lower", []))
    title_seniority = "plain"
    if any(token in lower_sen_tokens for token in decomposition.get("seniority_modifiers") or []):
        title_seniority = "lower"
    elif decomposition.get("seniority_modifiers"):
        title_seniority = "preferred"

    result.update(
        {
            "normalized_title": normalized_title,
            "base_role": base_role,
            "seniority_modifiers": list(decomposition.get("seniority_modifiers") or []),
            "variant_terms": str(decomposition.get("variant_terms") or "").strip(),
            "matched_pattern": matched_primary_pattern or matched_secondary_pattern,
            "title_seniority": title_seniority,
            "primary_pattern_has_seniority": primary_pattern_has_seniority,
            "warning_reason": "TITLE_SENIORITY_VARIANT" if decomposition.get("seniority_modifiers") else "",
            "seniority_adjustment": 0,
        }
    )
    if result["primary_pattern_has_seniority"]:
        adjustments = rules.get("seniority_score_adjustments", {})
        if title_seniority == "lower":
            result["seniority_adjustment"] = adjustments.get("lower", -5)
        elif title_seniority == "preferred":
            result["seniority_adjustment"] = adjustments.get("preferred", 3)

    for rule in profile.get("reject_title_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"TITLE_REJECT:{pattern}")
        if pattern and re.search(pattern, normalized_title):
            result["reason"] = reason
            return result

    if is_direct_match:
        if _has_numeric_title_level(normalized_title):
            result.update({"ok": True, "reason": TITLE_REASON_POTENTIAL_MATCH, "match_family": "primary"})
            return result
        result.update({"ok": True, "reason": "OK", "match_family": "primary"})
        return result

    if is_adjacent_match:
        result.update({"ok": True, "reason": TITLE_REASON_POTENTIAL_MATCH, "match_family": "secondary"})
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


def _phrase_from_segment(segment: str) -> str:
    cleaned = normalize_title_block_phrase(segment)
    if not cleaned:
        return ""

    tokens = [
        token
        for token in cleaned.split()
        if len(token) >= 2 and not token.isdigit()
    ]
    if not tokens:
        return ""
    return " ".join(tokens[:3])


def suggest_title_block_phrases(title: str) -> list[str]:
    """Return ranked non-empty block-phrase candidates from explicit title qualifiers."""
    raw_title = (title or "").strip()
    if not raw_title:
        return []
    normalized = re.sub(r"\s+", " ", raw_title)
    segments = [segment.strip() for segment in TITLE_BLOCK_SEGMENT_SPLIT_RE.split(normalized) if segment and segment.strip()]
    if len(segments) <= 1:
        return []
    ranked_groups: list[list[str]] = [[], []]
    seen: set[str] = set()
    for index, seg in enumerate(segments):
        if index == 0:
            continue
        phrase = _phrase_from_segment(seg)
        if phrase and phrase not in seen:
            seen.add(phrase)
            ranked_groups[0].append(phrase)
    return ranked_groups[0] + ranked_groups[1]


def suggest_title_block_phrase(title: str) -> str:
    """Return the single best block phrase."""
    candidates = suggest_title_block_phrases(title)
    return candidates[0] if candidates else ""


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


def _normalize_level(value: str) -> str:
    level = (value or "").strip().lower()
    aliases = load_parsing_rules().get("level_aliases", {})
    if not aliases:
        return level or "basic"
    return aliases.get(level, level or "basic")


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


def _load_matching_context_patterns() -> dict[str, Any]:
    rules = load_parsing_rules()
    patterns = rules.get(KEY_P_MATCHING_CONTEXT)
    if not isinstance(patterns, dict):
        raise ValueError("parsing_rules.json must define matching_context_patterns")
    return patterns


def _matches_hard_requirement(text: str, alias: str) -> bool:
    alias_lower = (alias or "").strip().lower()
    if not alias_lower:
        return False

    context_pats = _load_matching_context_patterns()
    escaped_alias = re.escape(alias_lower)
    prefix = str(context_pats.get(KEY_P_CTX_HARD_PREFIX) or "").strip()
    suffix = str(context_pats.get(KEY_P_CTX_HARD_SUFFIX) or "").strip()
    if not prefix or not suffix:
        raise ValueError("parsing_rules.json must define hard_requirement_prefix and hard_requirement_suffix")
    try:
        window_chars = int(context_pats.get(KEY_P_CTX_HARD_WINDOW))
        negation_window = int(context_pats.get(KEY_P_CTX_NEGATION_WINDOW))
    except Exception as exc:
        raise ValueError("parsing_rules.json must define hard_requirement_window_chars and negation_prefix_window_chars") from exc
    if window_chars <= 0 or negation_window <= 0:
        raise ValueError("parsing_rules.json must define hard_requirement_window_chars and negation_prefix_window_chars")

    patterns = [
        rf"{prefix}.{{0,{window_chars}}}{escaped_alias}",
        rf"{escaped_alias}.{{0,{window_chars}}}{suffix}",
        rf"{suffix}.{{0,{window_chars}}}{escaped_alias}",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _matches_soft_requirement(text: str, alias: str) -> bool:
    alias_lower = (alias or "").strip().lower()
    if not alias_lower:
        return False

    context_pats = _load_matching_context_patterns()
    escaped_alias = re.escape(alias_lower)
    prefix = str(context_pats.get(KEY_P_CTX_SOFT_PREFIX) or "").strip()
    suffix = str(context_pats.get(KEY_P_CTX_SOFT_SUFFIX) or "").strip()
    if not prefix or not suffix:
        raise ValueError("parsing_rules.json must define soft_requirement_prefix and soft_requirement_suffix")
    try:
        window_chars = int(context_pats.get(KEY_P_CTX_SOFT_WINDOW))
    except Exception as exc:
        raise ValueError("parsing_rules.json must define soft_requirement_window_chars") from exc
    if window_chars <= 0:
        raise ValueError("parsing_rules.json must define soft_requirement_window_chars")

    patterns = [
        rf"{prefix}.{{0,{window_chars}}}{escaped_alias}",
        rf"{escaped_alias}.{{0,{window_chars}}}{suffix}",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _evaluate_capability_profile(description_lower: str, profile: dict) -> Tuple[bool, str]:
    capability_rules = profile.get(KEY_CAPABILITY_PROFILE_RULES, [])
    positive_hits = 0
    warning_reason = "OK"

    for rule in capability_rules:
        name = str(rule.get("name") or "").strip()
        level = _normalize_level(str(rule.get("level") or "basic"))
        canonical = canonical_capability_term(rule)
        if not name or not canonical:
            continue

        _, distinct_hits = _count_alias_hits(description_lower, [canonical])
        if level in {"strong", "working"}:
            positive_hits += distinct_hits

        hard_requirement_match = _matches_hard_requirement(description_lower, canonical)
        soft_requirement_match = _matches_soft_requirement(description_lower, canonical)
        reason_token = _normalize_reason_token(name)

        if level == "low" and (hard_requirement_match or soft_requirement_match or distinct_hits >= 3):
            if warning_reason == "OK":
                warning_reason = f"DESC_CAPABILITY_LOW:{reason_token}"
        if level == "basic" and hard_requirement_match and distinct_hits >= 2:
            if warning_reason == "OK":
                warning_reason = f"DESC_CAPABILITY_BASIC:{reason_token}"
        if level in {"low", "basic"} and distinct_hits >= 4 and positive_hits <= 2:
            if warning_reason == "OK":
                warning_reason = f"DESC_PRIMARY_FOCUS:{reason_token}"

    return True, warning_reason


def _count_capability_role_proof(description_lower: str, profile: dict) -> tuple[int, int]:
    proof_hits = 0
    mention_hits = 0

    for rule in profile.get(KEY_CAPABILITY_PROFILE_RULES, []):
        name = str(rule.get("name") or "").strip()
        if not name:
            continue

        canonical = canonical_capability_term(rule)
        if not canonical:
            continue

        _, distinct_hits = _count_alias_hits(description_lower, [canonical])
        hard_requirement_match = _matches_hard_requirement(description_lower, canonical)
        soft_requirement_match = _matches_soft_requirement(description_lower, canonical)

        if distinct_hits > 0:
            mention_hits += 1
        if hard_requirement_match or soft_requirement_match or distinct_hits >= 2:
            proof_hits += 1

    return proof_hits, mention_hits


def _evaluate_description_confidence(details_text: str, description_lower: str, title_reason: str, profile: dict) -> Tuple[bool, str]:
    normalized_text = re.sub(r"\s+", " ", details_text).strip()
    text_length = len(normalized_text)
    rules = load_parsing_rules()
    conf_rules = rules.get("description_confidence_rules", {})
    if not isinstance(conf_rules, dict):
        raise ValueError("parsing_rules.json must define description_confidence_rules")

    try:
        min_text_length = int(conf_rules.get(KEY_P_CONF_MIN_LENGTH))
        min_section_hits = int(conf_rules.get(KEY_P_CONF_MIN_SECTIONS))
        min_bullet_points = int(conf_rules.get(KEY_P_CONF_MIN_BULLETS))
        min_generic_phrases = int(conf_rules.get(KEY_P_CONF_MIN_GENERIC))
        min_coordination_tokens = int(conf_rules.get(KEY_P_CONF_MIN_COORDINATION))
    except Exception as exc:
        raise ValueError("parsing_rules.json must define description confidence thresholds") from exc

    if min_text_length <= 0 or min_section_hits < 0 or min_bullet_points < 0 or min_generic_phrases < 0 or min_coordination_tokens < 0:
        raise ValueError("parsing_rules.json must define description confidence thresholds")

    section_score = sum(
        1
        for pattern in [rf"\b{re.escape(i)}\b" for i in conf_rules.get("section_indicators", [])]
        if re.search(pattern, description_lower)
    )
    bullet_score = len(re.findall(r"(?m)^\s*[-*\u2022]", details_text))
    generic_score = sum(
        1
        for phrase in rules.get("generic_summary_phrases", [])
        if phrase.lower() in description_lower
    )
    coordination_score = sum(
        1
        for token in conf_rules.get("coordination_tokens", [])
        if token.lower() in description_lower
    )
    proof_hits, mention_hits = _count_capability_role_proof(description_lower, profile)
    has_capability_rules = any(
        str(rule.get("name") or "").strip()
        for rule in profile.get(KEY_CAPABILITY_PROFILE_RULES, [])
    )
    structurally_thin = text_length < min_text_length and section_score < min_section_hits and bullet_score < min_bullet_points

    if title_reason == TITLE_REASON_POTENTIAL_MATCH:
        if has_capability_rules and proof_hits == 0 and mention_hits == 0:
            return False, "DESC_ROLE_PROOF_MISSING"
        if proof_hits == 0 and mention_hits < 2 and (structurally_thin or generic_score >= min_generic_phrases or coordination_score >= min_coordination_tokens):
            return False, "DESC_ROLE_PROOF_MISSING"
        if proof_hits <= 1 and structurally_thin and mention_hits == 0:
            return False, "DESC_ROLE_PROOF_WEAK"

    if title_reason == "OK" and proof_hits == 0 and structurally_thin and generic_score >= min_generic_phrases:
        return False, "DESC_VAGUE_TARGET_ROLE"

    return True, "OK"


def passes_title_filters(title: str) -> Tuple[bool, str]:
    """
    Title-based gatekeeping.
    Returns (True, "OK") if title is acceptable, else (False, "REASON").
    """
    analysis = analyze_title_filters(title)
    return bool(analysis["ok"]), str(analysis["reason"])


def passes_content_filters(details_text: str, card_location: str = "", title_reason: str = "") -> Tuple[bool, str]:
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

    hard_block_matches = find_hard_block_matches(details_text, profile.get("must_not_require_skills", []))
    for match in hard_block_matches:
        token = _normalize_reason_token(match.get("matched_term") or "")
        if token:
            return False, f"DESC_HARD_BLOCK_RULE:{token}"

    ok_capability, capability_reason = _evaluate_capability_profile(description_lower, profile)
    if not ok_capability:
        return False, capability_reason

    ok_confidence, confidence_reason = _evaluate_description_confidence(details_text, description_lower, title_reason, profile)
    if not ok_confidence:
        return False, confidence_reason

    if hard_block_matches:
        return False, f"DESC_HARD_BLOCK_RULE:{_normalize_reason_token(hard_block_matches[0].get('matched_term') or '')}"

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
    ) -> Tuple[bool, str]:
    profile = load_profile()
    normalized_title = normalize_title_text(title)
    teaser_lower = (teaser or "").strip().lower()
    combined = "\n".join(
        part for part in [
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
    counter_hits = sum(1 for pattern in counter_patterns if pattern and re.search(pattern, combined))
    direct_target_title = _matches_normalized_title(normalized_title, profile.get("target_roles", []))

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
        unusually_strong_counter = direct_target_title and counter_hits >= 4 and not title_has_specialist_signal
        if unusually_strong_counter:
            continue
        return False, reason

    return True, "OK"
