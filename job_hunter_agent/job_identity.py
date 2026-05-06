import re
from functools import lru_cache
from typing import Any, Iterable, List, Optional

from job_hunter_agent.identity_rules import load_identity_rules


@lru_cache(maxsize=1)
def _get_identity_config() -> dict[str, Any]:
    """Load identity matching rules from managed knowledge."""
    return load_identity_rules()


@lru_cache(maxsize=1)
def _get_company_suffix_pattern() -> re.Pattern:
    suffixes = [
        re.escape(str(value).strip())
        for value in _get_identity_config().get("company_suffixes", [])
        if str(value).strip()
    ]
    if not suffixes:
        return re.compile(r"(?!x)x")
    return re.compile(rf"\b({'|'.join(suffixes)})\b", flags=re.IGNORECASE)


def _normalize_identity_text(text: str) -> str:
    # Remove punctuation and common company suffixes to improve matching across sources.
    t = str(text or "").lower()
    t = re.sub(r"[^\w\s]", "", t)
    # Strip common corporate legal entities and region suffixes.
    t = _get_company_suffix_pattern().sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def _title_words(record: dict) -> set[str]:
    return set(_normalize_identity_text(str(record.get("title") or "")).split())


def _source_priority(record: dict) -> int:
    source_map = _get_identity_config().get("source_priority", {})
    source = _normalize_identity_text(str(record.get("source") or ""))
    fallback_priority = (max(source_map.values()) + 1) if source_map else 1
    return source_map.get(source, fallback_priority)


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
    threshold = float(_get_identity_config()["title_similarity_threshold"])
    return (len(overlap) / len(combined)) >= threshold


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
