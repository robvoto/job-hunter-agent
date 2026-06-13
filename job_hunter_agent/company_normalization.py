"""Helpers for company normalization."""

from __future__ import annotations

"""Company name normalization and weak matching helpers."""


import re
from functools import lru_cache
from typing import Any


def _load_payload() -> dict[str, Any]:

    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("company_name_normalization") or {}


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:

    normalized = dict(payload)

    normalization_suffixes = normalized.get("company_name_suffixes")

    if not isinstance(normalization_suffixes, list):
        raise ValueError(
            "company_name_normalization.json must define company_name_suffixes as a list"
        )

    cleaned_suffixes: list[str] = []

    seen_suffixes: set[str] = set()

    for value in normalization_suffixes:
        suffix = str(value or "").strip().lower()

        if not suffix or suffix in seen_suffixes:
            continue

        seen_suffixes.add(suffix)

        cleaned_suffixes.append(suffix)

    if not cleaned_suffixes:
        raise ValueError(
            "company_name_normalization.json must define at least one company_name_suffixes entry"
        )

    normalized["company_name_suffixes"] = cleaned_suffixes

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
        for value in load_company_name_normalization().get("company_name_suffixes", [])
        if str(value).strip()
    ]

    if not normalization_terms:
        return re.compile(r"(?!x)x")

    return re.compile(rf"\b({'|'.join(normalization_terms)})\b", flags=re.IGNORECASE)


def normalize_company_name(value: str) -> str:

    cleaned = re.sub(r"[^\w\s]", " ", str(value or "").lower())

    cleaned = _company_name_normalization_pattern().sub(" ", cleaned)

    return re.sub(r"\s+", " ", cleaned).strip()


def company_names_weakly_match(a: str, b: str) -> bool:

    left = normalize_company_name(a)

    right = normalize_company_name(b)

    return bool(left and right and left == right)
