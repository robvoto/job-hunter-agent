import json
from pathlib import Path
from typing import Dict, Optional, Set
#Harcoded: We need LLM to learn / maintain and grow salary_rules
_BASE_DIR = Path(__file__).resolve().parent
_SALARY_PATH = _BASE_DIR / "data" / "salary.json"

_cached_rules: Optional[Dict] = None


def load_salary(force_reload: bool = False) -> dict:
    """
    Load salary formatting rules from persistent storage.

    Results are cached in memory to avoid repeated disk reads.
    """
    global _cached

    if _cached is not None and not force_reload:
        return _cached

    if _SALARY_PATH.exists():
        _cached = json.loads(_SALARY_PATH.read_text())
    else:
        _cached = {}

    return _cached
