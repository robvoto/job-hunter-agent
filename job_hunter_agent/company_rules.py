from __future__ import annotations

"""Company suffix cleanup and weak matching helpers."""

import json
import re
from functools import lru_cache
from typing import Any

from job_hunter_agent.paths import COMPANY_RULES_PATH


def _load_payload() -> dict[str, Any]:
    if not COMPANY_RULES_PATH.exists():
        return {}
    try:
        payload = json.loads(COMPANY_RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    company_suffixes = normalized.get("company_suffixes")
    if not isinstance(company_suffixes, list):
        raise ValueError("company_rules.json must define company_suffixes as a list")
    cleaned_suffixes: list[str] = []
    seen_suffixes: set[str] = set()
    for value in company_suffixes:
        suffix = str(value or "").strip().lower()
        if not suffix or suffix in seen_suffixes:
            continue
        seen_suffixes.add(suffix)
        cleaned_suffixes.append(suffix)
    if not cleaned_suffixes:
        raise ValueError("company_rules.json must define at least one company_suffixes entry")
    normalized["company_suffixes"] = cleaned_suffixes
    return normalized


def load_company_rules() -> dict[str, Any]:
    payload = _load_payload()
    if not payload:
        raise ValueError("company_rules.json must contain a rules object")
    return _normalize_config(payload)


def save_company_rules(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_config(payload)
    normalized.setdefault("kind", "system_config")
    normalized.setdefault("name", "company_rules")
    normalized.setdefault("version", 1)
    COMPANY_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPANY_RULES_PATH.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return normalized


@lru_cache(maxsize=1)
def _company_suffix_pattern() -> re.Pattern[str]:
    suffixes = [
        re.escape(value)
        for value in load_company_rules().get("company_suffixes", [])
        if str(value).strip()
    ]
    if not suffixes:
        return re.compile(r"(?!x)x")
    return re.compile(rf"\b({'|'.join(suffixes)})\b", flags=re.IGNORECASE)


def normalize_company_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", str(value or "").lower())
    cleaned = _company_suffix_pattern().sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def company_names_weakly_match(a: str, b: str) -> bool:
    left = normalize_company_name(a)
    right = normalize_company_name(b)
    return bool(left and right and left == right)
