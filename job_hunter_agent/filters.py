# filters.py

import json
import re
from typing import Tuple

from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.paths import OUTPUT_DIR
from job_hunter_agent.profile_store import load_profile




TITLE_BLOCK_SEGMENT_SPLIT_RE = re.compile(r"\s*\|\s*|\s[-\u2013\u2014/:]\s|[(),\[\]]")


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns if pattern)


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
    aliases = {
        "low": "low",
        "weak": "low",
        "basic": "basic",
        "limited": "basic",
        "working": "working",
        "intermediate": "working",
        "strong": "strong",
        "expert": "strong",
    }
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


def _matches_hard_requirement(text: str, alias: str) -> bool:
    alias_lower = (alias or "").strip().lower()
    if not alias_lower:
        return False

    escaped_alias = re.escape(alias_lower)
    patterns = [
        rf"(strong|solid|extensive|proven|demonstrated|hands[- ]on|deep|advanced|expert).{{0,45}}{escaped_alias}",
        rf"{escaped_alias}.{{0,45}}(required|essential|must have|mandatory|highly desirable)",
        rf"(required|essential|must have|mandatory|highly desirable).{{0,45}}{escaped_alias}",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _matches_soft_requirement(text: str, alias: str) -> bool:
    alias_lower = (alias or "").strip().lower()
    if not alias_lower:
        return False

    escaped_alias = re.escape(alias_lower)
    patterns = [
        rf"(experience in|experience with|knowledge of|understanding of|proficiency in).{{0,45}}{escaped_alias}",
        rf"{escaped_alias}.{{0,35}}(experience|knowledge|understanding|proficiency)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def matches_missing_requirement(description_text: str, required_term: str) -> bool:
    description_lower = (description_text or "").lower()
    skill_lower = (required_term or "").strip().lower()
    if not description_lower or not skill_lower:
        return False
    escaped_skill = re.escape(skill_lower)
    term_pattern = rf"(?<!\w){escaped_skill}(?!\w)"
    hard_requirement_re = re.compile(r"\b(required|requires|required to|essential|must have|mandatory|need to have|needs to have)\b")
    strength_re = re.compile(r"\b(strong|extensive|proven|solid|deep|hands[- ]on|expert)\b")
    desirable_re = re.compile(r"\b(desirable|preferred|highly regarded|nice to have|advantageous|beneficial|highly desirable)\b")

    def hard_requirement_matches(context: str) -> bool:
        for hard_match in hard_requirement_re.finditer(context):
            prefix = context[max(0, hard_match.start() - 5):hard_match.start()]
            if re.search(r"\bnot\s+$", prefix):
                continue
            return True
        return False

    for match in re.finditer(term_pattern, description_lower):
        start = max(match.start() - 45, 0)
        end = min(match.end() + 45, len(description_lower))
        context = description_lower[start:end]
        if hard_requirement_matches(context):
            return True
        if strength_re.search(context) and not desirable_re.search(context):
            return True
    return False


def _evaluate_capability_profile(description_lower: str, profile: dict) -> Tuple[bool, str]:
    capability_rules = profile.get("capability_profile_rules", [])
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

    for rule in profile.get("capability_profile_rules", []):
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
    section_score = sum(
        1
        for pattern in (
            r"\bresponsibilities\b",
            r"\brequirements\b",
            r"\byou will\b",
            r"\bkey duties\b",
            r"\babout the role\b",
            r"\bexperience with\b",
            r"\bmust have\b",
            r"\bessential\b",
        )
        if re.search(pattern, description_lower)
    )
    bullet_score = len(re.findall(r"(?m)^\s*[-*\u2022]", details_text))
    generic_score = sum(
        1
        for phrase in (
            "great opportunity",
            "fast-paced environment",
            "dynamic team",
            "leading organisation",
            "excellent communication skills",
            "must be based in",
            "full working rights",
        )
        if phrase in description_lower
    )
    coordination_score = sum(
        1
        for token in (
            "coordination",
            "coordinating",
            "reporting",
            "liaise",
            "liaison",
            "administration",
            "scheduling",
        )
        if token in description_lower
    )
    proof_hits, mention_hits = _count_capability_role_proof(description_lower, profile)
    has_capability_rules = any(
        str(rule.get("name") or "").strip()
        for rule in profile.get("capability_profile_rules", [])
    )
    structurally_thin = text_length < 500 and section_score < 2 and bullet_score < 3

    if title_reason == "TITLE_POTENTIAL_MATCH":
        if has_capability_rules and proof_hits == 0 and mention_hits == 0:
            return False, "DESC_ROLE_PROOF_MISSING"
        if proof_hits == 0 and mention_hits < 2 and (structurally_thin or generic_score >= 2 or coordination_score >= 3):
            return False, "DESC_ROLE_PROOF_MISSING"
        if proof_hits <= 1 and structurally_thin and mention_hits == 0:
            return False, "DESC_ROLE_PROOF_WEAK"

    if title_reason == "OK" and proof_hits == 0 and structurally_thin and generic_score >= 2:
        return False, "DESC_VAGUE_TARGET_ROLE"

    return True, "OK"


def passes_title_filters(title: str) -> Tuple[bool, str]:
    """
    Title-based gatekeeping.
    Returns (True, "OK") if title is acceptable, else (False, "REASON").
    """
    if not title:
        return False, "TITLE_EMPTY"

    profile = load_profile()
    title_lower = title.strip().lower()

    target_patterns = profile.get("primary_job_title_pattern", [])
    adjacent_patterns = profile.get("secondary_title_patterns", [])
    is_direct_match = _matches_any(title_lower, target_patterns)
    is_adjacent_match = _matches_any(title_lower, adjacent_patterns)

    if not is_direct_match and not is_adjacent_match:
        return False, "TITLE_NOT_TARGET"

    if is_direct_match and _has_numeric_title_level(title_lower):
        return True, "TITLE_POTENTIAL_MATCH"

    for rule in profile.get("reject_title_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"TITLE_REJECT:{pattern}")
        if pattern and re.search(pattern, title_lower):
            return False, reason

    if is_direct_match:
        return True, "OK"
    return True, "TITLE_POTENTIAL_MATCH"


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

    ok_capability, capability_reason = _evaluate_capability_profile(description_lower, profile)
    if not ok_capability:
        return False, capability_reason

    ok_confidence, confidence_reason = _evaluate_description_confidence(details_text, description_lower, title_reason, profile)
    if not ok_confidence:
        return False, confidence_reason

    for skill in profile.get("must_not_require_skills", []):
        skill_lower = (skill or "").strip().lower()
        if not skill_lower:
            continue
        if matches_missing_requirement(description_lower, skill_lower):
            return False, f"DESC_MANDATORY_SKILL:{_normalize_reason_token(skill_lower)}"

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
    title_lower = (title or "").strip().lower()
    teaser_lower = (teaser or "").strip().lower()
    combined = "\n".join(
        part for part in [
            title_lower,
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
    direct_target_title = _matches_any(title_lower, profile.get("primary_job_title_pattern", []))

    for rule in profile.get("cheap_reject_metadata_rules", []):
        pattern = rule.get("pattern", "")
        reason = rule.get("reason", f"CARD_SPECIALIST:{pattern}")
        scope = str(rule.get("scope") or "title_or_teaser").strip().lower()
        haystack = teaser_lower
        if scope == "title":
            haystack = title_lower
        elif scope == "teaser":
            haystack = teaser_lower
        else:
            haystack = "\n".join(part for part in [title_lower, teaser_lower] if part)

        if not pattern or not haystack or not re.search(pattern, haystack):
            continue

        title_has_specialist_signal = bool(re.search(pattern, title_lower)) 
        unusually_strong_counter = direct_target_title and counter_hits >= 4 and not title_has_specialist_signal
        if unusually_strong_counter:
            continue
        return False, reason

    return True, "OK"


# ---------------------------------------------------------------------------
# Rejection-learning: extraction helpers
# ---------------------------------------------------------------------------

_REJECTION_RULES_PATH = OUTPUT_DIR / "rejection_rules.json"


def _load_saved_rejection_rules() -> list:
    if not _REJECTION_RULES_PATH.exists():
        return []
    try:
        data = json.loads(_REJECTION_RULES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def passes_saved_rejection_rules(text: str) -> Tuple[bool, str]:
    """Apply user-saved rejection rules (output/rejection_rules.json) to description text.

    Returns (True, 'OK') if no active rule matches, else (False, reason).
    Called during scraping, NOT at render time.
    """
    rules = _load_saved_rejection_rules()
    if not rules:
        return True, "OK"
    lowered = (text or "").lower()
    for rule in rules:
        if not rule.get("active", True):
            continue
        value = str(rule.get("value") or "").strip().lower()
        if len(value) < 3:
            continue
        pattern = rf"(?<!\w){re.escape(value)}(?!\w)"
        if re.search(pattern, lowered):
            category = re.sub(r"[^a-z0-9_]", "_", str(rule.get("category") or "other"))
            token = re.sub(r"[^a-z0-9]+", "_", value).strip("_")[:30]
            return False, f"LEARNED_REJECT:{category}:{token}"
    return True, "OK"
