
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
        if value in lowered:
            category = re.sub(r"[^a-z0-9_]", "_", str(rule.get("category") or "other"))
            token = re.sub(r"[^a-z0-9]+", "_", value).strip("_")[:30]
            return False, f"LEARNED_REJECT:{category}:{token}"
    return True, "OK"
