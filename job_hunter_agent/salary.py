"""Helpers for salary."""



import json

from typing import Dict, Optional



"""Manages salary-related knowledge and parsing rules.



This module loads and caches salary parsing rules, including interval suffixes,

divisors, and currency symbols, from a JSON knowledge file."""



from job_hunter_agent.paths import KNOWLEDGE_DIR



_SALARY_PATH = KNOWLEDGE_DIR / "salary.json"



KEY_INTERVAL_SUFFIX = "interval_suffix"

KEY_INTERVAL_DIVISOR = "interval_divisor"

KEY_CURRENCIES_WITH_DOLLAR = "currencies_with_dollar"



_cached_rules: Optional[Dict] = None





def load_salary() -> Dict:

    global _cached_rules

    if _cached_rules is None:

        try:

            with open(_SALARY_PATH, encoding="utf-8") as f:

                _cached_rules = json.load(f)

        except Exception as exc:

            print(f"[SALARY][ERROR] Failed to load salary rules from {_SALARY_PATH}: {exc}")

            _cached_rules = {} # Fallback to empty dict on error

    return _cached_rules

