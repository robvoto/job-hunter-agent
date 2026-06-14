"""Helpers for salary-related knowledge and parsing rules."""

import json

from job_hunter_agent.paths import KNOWLEDGE_DIR

_SALARY_PATH = KNOWLEDGE_DIR / "salary.json"

KEY_INTERVAL_SUFFIX = "interval_suffix"
KEY_INTERVAL_DIVISOR = "interval_divisor"
KEY_CURRENCIES_WITH_DOLLAR = "currencies_with_dollar"

_cached_rules: dict[str, object] | None = None

def load_salary() -> dict[str, object]:
    global _cached_rules
    if _cached_rules is None:
        try:
            with open(_SALARY_PATH, encoding="utf-8") as f:
                _cached_rules = json.load(f)
        except Exception as exc:
            print(f"[SALARY][ERROR] Failed to load salary rules from {_SALARY_PATH}: {exc}")
            _cached_rules = {}
    cached_rules = _cached_rules
    if cached_rules is None:
        return {}
    return cached_rules
