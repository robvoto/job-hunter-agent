"""Canonical sector values used by job records and preference filtering."""

SECTOR_GOVERNMENT = "government"
SECTOR_PRIVATE = "private"
SECTOR_UNKNOWN = "unknown"

_SECTOR_ALIASES = {
    "government": SECTOR_GOVERNMENT,
    "government sector": SECTOR_GOVERNMENT,
    "public": SECTOR_GOVERNMENT,
    "public sector": SECTOR_GOVERNMENT,
    "private": SECTOR_PRIVATE,
    "private sector": SECTOR_PRIVATE,
    "unknown": SECTOR_UNKNOWN,
}


def normalize_sector_value(value: object) -> str:
    """Normalize a source-provided sector without inferring missing evidence."""

    normalized = " ".join(str(value or "").strip().casefold().split())
    return _SECTOR_ALIASES.get(normalized, SECTOR_UNKNOWN)


def classify_market_sector(item: dict, government_terms: list[str]) -> str:
    """Classify a market item from explicit or source-backed facts only.

    Government terms provide positive public-sector evidence. Generic industry
    categories do not establish that an employer is private, so ambiguous items
    stay unknown rather than being guessed into either sector.
    """

    explicit = normalize_sector_value(item.get("sector"))
    if explicit != SECTOR_UNKNOWN:
        return explicit

    evidence_parts = [
        item.get("classification_text"),
        item.get("subclassification_text"),
        item.get("title"),
        item.get("employer"),
        item.get("teaser_text"),
        item.get("full_description"),
    ]
    evidence = " ".join(str(value or "").casefold() for value in evidence_parts)
    normalized_terms = [
        " ".join(str(term or "").casefold().split())
        for term in government_terms
        if str(term or "").strip()
    ]
    if any(term in evidence for term in normalized_terms):
        return SECTOR_GOVERNMENT

    return SECTOR_UNKNOWN
