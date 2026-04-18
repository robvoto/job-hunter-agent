# filters.py

import json
import re
from pathlib import Path
from typing import Tuple

from profile_store import load_profile




GENERIC_TITLE_BLOCK_WORDS = {
    "a",
    "an",
    "and",
    "analyst",
    "analytics",
    "apps",
    "associate",
    "architect",
    "assistant",
    "business",
    "change",
    "consultant",
    "contract",
    "delivery",
    "digital",
    "enterprise",
    "functional",
    "government",
    "graduate",
    "implementation",
    "intermediate",
    "intern",
    "junior",
    "lead",
    "manager",
    "mid",
    "midlevel",
    "multiple",
    "owner",
    "permanent",
    "principal",
    "product",
    "program",
    "project",
    "role",
    "roles",
    "senior",
    "solution",
    "specialist",
    "support",
    "system",
    "systems",
    "technical",
    "temp",
    "temporary",
    "transformation",
}


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
        if token not in GENERIC_TITLE_BLOCK_WORDS and len(token) >= 2 and not token.isdigit()
    ]
    if not tokens:
        return ""
    return " ".join(tokens[:3])


def suggest_title_block_phrases(title: str) -> list[str]:
    """Return all non-empty block-phrase candidates from every title segment."""
    raw_title = (title or "").strip()
    if not raw_title:
        return []
    normalized = re.sub(r"\s+", " ", raw_title)
    # | handled with or without surrounding spaces; - / : only when space-bounded
    segments = [
        s.strip()
        for s in re.split(r"\s*\|\s*|\s[-–—/:]\s|[(),\[\]]", normalized)
        if s and s.strip()
    ]
    seen: set[str] = set()
    candidates: list[str] = []
    for seg in segments:
        phrase = _phrase_from_segment(seg)
        if phrase and phrase not in seen:
            seen.add(phrase)
            candidates.append(phrase)
    return candidates


def suggest_title_block_phrase(title: str) -> str:
    """Return the single best block phrase (first non-generic segment, backward compat)."""
    candidates = suggest_title_block_phrases(title)
    if candidates:
        return candidates[0]
    return _phrase_from_segment(re.sub(r"\s+", " ", (title or "").strip()))


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
        "none": "none",
        "no": "none",
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


def _normalize_fit(value: str, level: str) -> str:
    fit = (value or "").strip().lower()
    aliases = {
        "core": "core",
        "primary": "core",
        "supporting": "supporting",
        "secondary": "supporting",
        "contextual": "contextual",
        "adjacent": "contextual",
        "avoid": "avoid",
        "reject": "avoid",
    }
    if fit in aliases:
        return aliases[fit]
    if level == "strong":
        return "core"
    if level == "working":
        return "supporting"
    return "contextual"


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


def _matches_missing_skill_requirement(description_lower: str, skill_lower: str) -> bool:
    escaped_skill = re.escape(skill_lower)
    mandatory_patterns = [
        rf"\b(strong|extensive|proven|solid|deep|hands[- ]on|expert)\b.{{0,25}}\b{escaped_skill}\b",
        rf"\b{escaped_skill}\b.{{0,35}}\b(required|essential|must have|mandatory)\b",
        rf"\b(required|essential|must have|mandatory)\b.{{0,35}}\b{escaped_skill}\b",
    ]
    return any(re.search(pattern, description_lower) for pattern in mandatory_patterns)


def _evaluate_capability_profile(description_lower: str, profile: dict) -> Tuple[bool, str]:
    capability_rules = profile.get("capability_profile_rules", [])
    positive_hits = 0

    for rule in capability_rules:
        name = str(rule.get("name") or "").strip()
        level = _normalize_level(str(rule.get("level") or "basic"))
        fit = _normalize_fit(str(rule.get("fit") or ""), level)
        aliases = [str(alias).strip() for alias in rule.get("aliases", []) if str(alias).strip()]
        if not name or not aliases:
            continue

        total_hits, distinct_hits = _count_alias_hits(description_lower, aliases)
        if level in {"strong", "working"}:
            positive_hits += distinct_hits

        hard_requirement_match = any(_matches_hard_requirement(description_lower, alias) for alias in aliases)
        soft_requirement_match = any(_matches_soft_requirement(description_lower, alias) for alias in aliases)
        reason_token = _normalize_reason_token(name)

        if (fit == "avoid" or level == "none") and (hard_requirement_match or soft_requirement_match or distinct_hits >= 2):
            return False, f"DESC_CAPABILITY_NONE:{reason_token}"
        if level == "low" and (hard_requirement_match or soft_requirement_match or distinct_hits >= 3):
            return False, f"DESC_CAPABILITY_LOW:{reason_token}"
        if level == "basic" and hard_requirement_match and distinct_hits >= 2:
            return False, f"DESC_CAPABILITY_BASIC:{reason_token}"
        if fit == "contextual" and hard_requirement_match and distinct_hits >= 2:
            return False, f"DESC_CAPABILITY_CONTEXT:{reason_token}"
        if fit == "contextual" and distinct_hits >= 4 and positive_hits <= 2:
            return False, f"DESC_PRIMARY_FOCUS:{reason_token}"
        if level in {"low", "basic"} and distinct_hits >= 4 and positive_hits <= 2:
            return False, f"DESC_PRIMARY_FOCUS:{reason_token}"

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

    target_patterns = profile.get("target_title_patterns", [])
    adjacent_patterns = profile.get("adjacent_title_patterns", [])
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


def passes_content_filters(details_text: str, card_location: str = "") -> Tuple[bool, str]:
    """
    Description-based filtering.
    Returns (True, "OK") if description fits, else (False, "REASON").
    """
    if not details_text:
        return False, "DESC_EMPTY"

    profile = load_profile()
    description_lower = details_text.lower()
    card_location_lower = (card_location or "").lower()

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

    ok_capability, capability_reason = _evaluate_capability_profile(description_lower, profile)
    if not ok_capability:
        return False, capability_reason

    for skill in profile.get("must_not_require_skills", []):
        skill_lower = (skill or "").strip().lower()
        if not skill_lower:
            continue
        if _matches_missing_skill_requirement(description_lower, skill_lower):
            return False, f"DESC_MANDATORY_SKILL:{_normalize_reason_token(skill_lower)}"

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
    direct_ba_title = bool(re.search(r"\bbusiness analyst\b|\btechnical business analyst\b|\bsenior ba\b|\btech(?:nical)?\s+ba\b", title_lower))

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
        unusually_strong_counter = direct_ba_title and counter_hits >= 4 and not title_has_specialist_signal
        if unusually_strong_counter:
            continue
        return False, reason

    return True, "OK"


# ---------------------------------------------------------------------------
# Rejection-learning: extraction helpers
# ---------------------------------------------------------------------------

_REJECTION_RULES_PATH = Path(__file__).resolve().parent / "output" / "rejection_rules.json"

# (pattern, category) — each pattern matches a trigger phrase in a job description.
# Structural-label patterns (sector, domain, etc.) require a colon so we don't
# accidentally capture mid-sentence uses like "the insurance sector required...".
_EXTRACTION_TRIGGERS: list[tuple[str, str]] = [
    (r"experience (?:in|with)\s+", "mandatory_experience"),
    (r"must[- ]have\s+", "mandatory_skill"),
    (r"(?:required|essential):\s+", "mandatory_skill"),
    (r"background in\s+", "domain"),
    (r"knowledge of\s+", "mandatory_skill"),
    (r"exposure to\s+", "mandatory_experience"),
    (r"worked (?:in|with)\s+", "domain"),
    (r"working (?:in|with)\s+", "domain"),
    (r"\bdomain:\s+", "domain"),
    (r"\bsector:\s+", "domain"),
    (r"\bindustry:\s+", "domain"),
    (r"\bplatform:\s+", "industry_platform"),
    (r"proficien(?:t|cy) (?:in|with)\s+", "mandatory_skill"),
    (r"understanding of\s+", "mandatory_skill"),
    (r"familiarity with\s+", "mandatory_skill"),
    (r"clearance[:\s]+", "clearance_or_regulation"),
    (r"compliance with\s+", "clearance_or_regulation"),
]

# Stops candidate extraction at punctuation or a low-information connective word.
# Newlines are pre-collapsed via re.sub so we only need to handle single spaces.
_STOP_AFTER_RE = re.compile(
    r"[,;.()]|\s+(?:and|or|to|for|as|is|are|has|the|a|an|by|of|essential|required|needed|necessary|preferred)\b",
    re.IGNORECASE,
)
_STRIP_LEAD_RE = re.compile(
    r"^(?:a|an|the|strong|extensive|proven|solid|excellent|good|relevant|significant|deep)\s+",
    re.IGNORECASE,
)
# Single-word extractions that are part of the trigger vocabulary itself — skip them
_SKIP_SINGLE_WORDS = frozenset({
    "required", "essential", "necessary", "important", "knowledge",
    "experience", "skills", "ability", "exposure", "understanding",
    "management", "background", "expertise", "proficiency", "familiarity",
})
_GENERIC_PHRASES = frozenset({
    "the role", "this role", "our team", "the team", "the business",
    "the company", "our company", "your experience", "your background",
})


def _extract_phrase_after(text: str, start: int) -> str:
    """Pull the first meaningful noun phrase from text starting at start."""
    segment = text[start:start + 55]
    m = _STOP_AFTER_RE.search(segment)
    phrase = segment[:m.start()].strip() if m else segment.strip()
    phrase = _STRIP_LEAD_RE.sub("", phrase).strip()
    words = [w.rstrip(".,;:)") for w in phrase.split()[:3] if len(w) >= 2]
    return " ".join(words)


def extract_rejection_suggestions(text: str) -> dict[str, list[str]]:
    """Extract candidate rejection terms from a job description.

    Pure heuristic, no AI, no predefined vocabulary.
    Returns dict of category -> list of candidate phrases (capped at 6 per category).
    """
    lowered = re.sub(r"\s+", " ", (text or "").lower())
    results: dict[str, list[str]] = {}
    seen: set[str] = set()

    for pattern, category in _EXTRACTION_TRIGGERS:
        for m in re.finditer(pattern, lowered):
            phrase = _extract_phrase_after(lowered, m.end())
            if not phrase or len(phrase) < 3 or phrase in seen:
                continue
            if phrase in _GENERIC_PHRASES:
                continue
            # Skip single words that are part of the trigger vocabulary
            if phrase in _SKIP_SINGLE_WORDS:
                continue
            seen.add(phrase)
            results.setdefault(category, []).append(phrase)

    return {cat: terms[:6] for cat, terms in results.items()}


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
