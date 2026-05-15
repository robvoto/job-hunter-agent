import json
from typing import Dict, Optional

from job_hunter_agent.paths import KNOWLEDGE_DIR

_SALARY_PATH = KNOWLEDGE_DIR / "salary.json"

KEY_INTERVAL_SUFFIX = "interval_suffix"
KEY_INTERVAL_DIVISOR = "interval_divisor"
KEY_CURRENCIES_WITH_DOLLAR = "currencies_with_dollar"

_cached_rules: Optional[Dict] = None


def load_salary(force_reload: bool = False) -> dict:
    """
    Load salary formatting rules from persistent storage.

    Results are cached in memory to avoid repeated disk reads.
    """
    global _cached_rules

    if _cached_rules is not None and not force_reload:
        return _cached_rules

    if _SALARY_PATH.exists():
        _cached_rules = json.loads(_SALARY_PATH.read_text())
    else:
        _cached_rules = {}

    return _cached_rules
