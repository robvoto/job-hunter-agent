import json
from pathlib import Path
from typing import Dict, Optional
#Harcoded: We need LLM to learn / maintain and grow job_type_store

_BASE_DIR = Path(__file__).resolve().parent
_JOB_TYPE_STORE_PATH = _BASE_DIR / "data" / "job_type.json" 

_cached_mapping: Optional[Dict[str, str]] = None


def load_job_type(force_reload: bool = False) -> dict:
    """
    Load the job type normalization mapping from persistent storage.

    The mapping is cached in memory to avoid repeated file reads.
    Set force_reload=True to refresh the cache from disk.
    """
    global _cached_mapping

    if _cached_mapping is not None and not force_reload:
        return _cached_mapping

    if _JOB_TYPE_STORE_PATH.exists():
        _cached_mapping = json.loads(_JOB_TYPE_STORE_PATH.read_text())
    else:
        _cached_mapping = {}

    return _cached_mapping