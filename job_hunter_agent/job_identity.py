import re
from functools import lru_cache
from typing import Any, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

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


def _normalized_url(record: dict) -> str:
    raw_url = str(record.get("url") or "").strip()
    if not raw_url:
        return ""
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return raw_url.split("#", 1)[0].split("?", 1)[0].strip().lower()
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, "", ""))


def _normalized_job_key(record: dict) -> str:
    return str(record.get("job_key") or "").strip().lower()


def _confirmed_duplicate_key(record: dict) -> Optional[tuple[str, str]]:
    job_key = _normalized_job_key(record)
    if job_key:
        return ("job_key", job_key)
    url = _normalized_url(record)
    if url:
        return ("url", url)
    return None


def _possible_duplicate_signature(record: dict) -> Optional[tuple[str, str]]:
    company = _normalize_identity_text(str(record.get("company") or ""))
    title = _normalize_identity_text(str(record.get("title") or ""))
    if not company or not title:
        return None
    return (company, title)


def _mark_possible_duplicate(record: dict, candidate: dict) -> None:
    review_items = record.setdefault("identity_review", [])
    review_items.append(
        {
            "kind": "possible_duplicate",
            "needs_review": True,
            "source": "normalized_company_and_title",
            "matched_record": {
                "job_key": candidate.get("job_key"),
                "source": candidate.get("source"),
                "title": candidate.get("title"),
                "company": candidate.get("company"),
                "url": candidate.get("url"),
            },
        }
    )


def _source_priority(record: dict) -> int:
    source_map = _get_identity_config().get("source_priority", {})
    source = _normalize_identity_text(str(record.get("source") or ""))
    fallback_priority = (max(source_map.values()) + 1) if source_map else 1
    return source_map.get(source, fallback_priority)


def are_jobs_confirmed_duplicates(a: dict, b: dict) -> bool:
    """Return True only when two records share a deterministic identity."""
    key_a = _confirmed_duplicate_key(a)
    key_b = _confirmed_duplicate_key(b)
    return bool(key_a and key_a == key_b)


def are_jobs_semantically_similar(a: dict, b: dict) -> bool:
    """Deprecated compatibility wrapper: only confirmed duplicates are actionable."""
    return are_jobs_confirmed_duplicates(a, b)


def find_similar_job(record: dict, pool: Iterable[dict]) -> Optional[dict]:
    """Return only a confirmed duplicate from the supplied pool."""
    for candidate in pool:
        if are_jobs_confirmed_duplicates(record, candidate):
            return candidate
    return None


def deduplicate_across_sources(records: List[dict]) -> List[dict]:
    """Collapse only confirmed duplicates; annotate possible duplicates for review."""
    deduped: List[dict] = []
    possible_duplicate_index: dict[tuple[str, str], dict] = {}

    for record in records:
        duplicate_index = next(
            (index for index, kept in enumerate(deduped) if are_jobs_confirmed_duplicates(record, kept)),
            None,
        )
        if duplicate_index is not None:
            if _source_priority(record) < _source_priority(deduped[duplicate_index]):
                deduped[duplicate_index] = record
            continue

        possible_signature = _possible_duplicate_signature(record)
        if possible_signature and possible_signature in possible_duplicate_index:
            _mark_possible_duplicate(record, possible_duplicate_index[possible_signature])
            _mark_possible_duplicate(possible_duplicate_index[possible_signature], record)
        elif possible_signature:
            possible_duplicate_index[possible_signature] = record

        deduped.append(record)

    return deduped
