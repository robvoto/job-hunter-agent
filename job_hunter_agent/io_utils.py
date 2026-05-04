import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_hunter_agent.paths import (
    AUDIT_RECORDS_PATH as DEBUG_JSON_PATH,
    JOB_HISTORY_PATH,
    LLM_CACHE_PATH,
    REVIEW_DATA_PATH,
    RUN_STATS_PATH,
)


def normalize_posted_text(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    return re.sub(r"^\s*posted\s+", "", text, flags=re.IGNORECASE).strip()


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json_dict(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_json_list(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_llm_cache() -> Dict[str, Any]:
    raw = load_json_dict(LLM_CACHE_PATH)
    return {str(k): v for k, v in raw.items()}


def save_llm_cache(cache: Dict[str, Any]) -> None:
    save_json(LLM_CACHE_PATH, cache)


def load_job_history() -> Dict[str, dict]:
    return load_json_dict(JOB_HISTORY_PATH)


def save_job_history(history: Dict[str, dict]) -> None:
    save_json(JOB_HISTORY_PATH, history)


def write_debug_json(records: List[dict]) -> None:
    save_json(DEBUG_JSON_PATH, records)


def write_run_stats(payload: dict) -> None:
    save_json(RUN_STATS_PATH, payload)


def write_run_attempt(run_started_at: datetime) -> None:
    run_stats = load_json_dict(RUN_STATS_PATH)
    run_stats["last_run_attempt_at"] = run_started_at.isoformat(timespec="seconds")
    save_json(RUN_STATS_PATH, run_stats)


def write_review_data(payload: dict) -> None:
    save_json(REVIEW_DATA_PATH, payload)
