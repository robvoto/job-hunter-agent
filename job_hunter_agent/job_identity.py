import re
from typing import Iterable, List, Optional

# Business rule: how similar job titles must be to be considered the same

#HARCODED Seek job ads are preferred to linkedin once if both are the same
_SOURCE_PRIORITY = {
    "seek": 0,
    "linkedin": 1,
} 

# the percentage of similarity when comparing job ads, word by word should be > 80%
TITLE_SIMILARITY_THRESHOLD = 0.8

#HARDCODED
# Domain data: common company suffixes to ignore when matching
COMPANY_SUFFIXES = [
    "pty",
    "ltd",
    "inc",
    "corp",
    "corporation",
    "limited",
    "llc",
    "holdings",
    "group",
    "australia",
]

_COMPANY_SUFFIX_PATTERN = rf"\b({'|'.join(COMPANY_SUFFIXES)})\b"

def _normalize_identity_text(text: str) -> str:
    # Remove punctuation and common company suffixes to improve matching across sources
    t = str(text or "").lower()
    t = re.sub(r"[^\w\s]", "", t)
    # Strip common corporate legal entities and region suffixes
    t = re.sub(_COMPANY_SUFFIX_PATTERN, "", t)
    return re.sub(r"\s+", " ", t).strip()


def _title_words(record: dict) -> set[str]:
    return set(_normalize_identity_text(str(record.get("title") or "")).split())


def _source_priority(record: dict) -> int:
    source = _normalize_identity_text(str(record.get("source") or ""))
    return _SOURCE_PRIORITY.get(source, 99)


def are_jobs_semantically_similar(a: dict, b: dict) -> bool:
    """Return True when two records look like the same role at the same company."""
    company_a = _normalize_identity_text(str(a.get("company") or ""))
    company_b = _normalize_identity_text(str(b.get("company") or ""))
    if not company_a or company_a != company_b:
        return False

    words_a = _title_words(a)
    words_b = _title_words(b)
    if not words_a or not words_b:
        return False

    overlap = words_a & words_b
    combined = words_a | words_b
    return (len(overlap) / len(combined)) >= TITLE_SIMILARITY_THRESHOLD  



def find_similar_job(record: dict, pool: Iterable[dict]) -> Optional[dict]:
    for candidate in pool:
        if are_jobs_semantically_similar(record, candidate):
            return candidate
    return None


def deduplicate_across_sources(records: List[dict]) -> List[dict]:
    """Collapse cross-source duplicates, preferring SEEK over LinkedIn."""
    deduped: List[dict] = []
    for record in records:
        duplicate_index = next(
            (index for index, kept in enumerate(deduped) if are_jobs_semantically_similar(record, kept)),
            None,
        )
        if duplicate_index is None:
            deduped.append(record)
            continue
        if _source_priority(record) < _source_priority(deduped[duplicate_index]):
            deduped[duplicate_index] = record
    return deduped
