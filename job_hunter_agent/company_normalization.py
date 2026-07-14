"""Helpers for company normalization and weak matching."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_COMPANY_NAME_SUFFIXES_KEY = "company_name_suffixes"
_COMPANY_NAME_MATCH_STOPWORDS_KEY = "company_name_match_stopwords"


def _load_payload() -> dict[str, Any]:

    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("company_name_normalization") or {}


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)

    normalization_suffixes = normalized.get(_COMPANY_NAME_SUFFIXES_KEY)
    normalization_stopwords = normalized.get(_COMPANY_NAME_MATCH_STOPWORDS_KEY)

    if not isinstance(normalization_suffixes, list):
        raise ValueError(
            "company_name_normalization.json must define company_name_suffixes as a list"
        )

    if not isinstance(normalization_stopwords, list):
        raise ValueError(
            "company_name_normalization.json must define company_name_match_stopwords as a list"
        )

    def _clean(values: list[Any]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            token = str(value or "").strip().lower()
            if not token or token in seen:
                continue
            seen.add(token)
            cleaned.append(token)
        return cleaned

    cleaned_suffixes = _clean(normalization_suffixes)
    cleaned_stopwords = _clean(normalization_stopwords)

    if not cleaned_suffixes:
        raise ValueError(
            "company_name_normalization.json must define at least one company_name_suffixes entry"
        )

    if not cleaned_stopwords:
        raise ValueError(
            "company_name_normalization.json must define at least one company_name_match_stopwords entry"
        )

    normalized[_COMPANY_NAME_SUFFIXES_KEY] = cleaned_suffixes
    normalized[_COMPANY_NAME_MATCH_STOPWORDS_KEY] = cleaned_stopwords

    return normalized


def load_company_name_normalization() -> dict[str, Any]:
    payload = _load_payload()

    if not payload:
        raise ValueError("company_name_normalization.json must contain a config object")

    return _normalize_config(payload)


def save_company_name_normalization(payload: dict[str, Any]) -> dict[str, Any]:
    config = _normalize_config(payload)

    config.setdefault("kind", "system_config")

    config.setdefault("name", "company_name_normalization")

    config.setdefault("version", 1)

    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge("company_name_normalization", config)

    return config


@lru_cache(maxsize=1)
def _company_name_normalization_pattern() -> re.Pattern[str]:
    normalization_terms = [
        re.escape(value)
        for value in load_company_name_normalization().get(_COMPANY_NAME_SUFFIXES_KEY, [])
        if str(value).strip()
    ]

    if not normalization_terms:
        return re.compile(r"(?!x)x")

    return re.compile(rf"\b({'|'.join(normalization_terms)})\b", flags=re.IGNORECASE)


@lru_cache(maxsize=1)
def _company_name_match_stopwords() -> frozenset[str]:
    return frozenset(
        str(value).strip().lower()
        for value in load_company_name_normalization().get(_COMPANY_NAME_MATCH_STOPWORDS_KEY, [])
        if str(value).strip()
    )


def normalize_company_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", str(value or "").lower())

    cleaned = _company_name_normalization_pattern().sub(" ", cleaned)

    return re.sub(r"\s+", " ", cleaned).strip()


def company_name_match_tokens(value: str) -> set[str]:
    normalized = normalize_company_name(value)
    if not normalized:
        return set()
    return set(normalized.split()) - _company_name_match_stopwords()


def company_name_token_overlap_match(a: str, b: str) -> bool:
    left = company_name_match_tokens(a)
    right = company_name_match_tokens(b)

    if not left or not right:
        return False

    overlap = len(left & right)
    return overlap >= max(1, min(len(left), len(right)) // 2)


def company_names_weakly_match(a: str, b: str) -> bool:
    left = normalize_company_name(a)
    right = normalize_company_name(b)
    return bool(left and right and left == right)


def normalize_match_text(value: str) -> str:
    """Normalize weak matching text for job titles, company names, and similar labels."""
    cleaned = re.sub(r"[^\w\s]", " ", str(value or "").lower())
    cleaned = re.sub(r"\b(pty|ltd|limited|inc|co|corp|group|australia|au)\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
