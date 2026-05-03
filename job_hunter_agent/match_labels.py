import json
from typing import Final, Any
from job_hunter_agent.paths import MATCH_LEVEL_DEFAULTS_PATH


def _load_default_levels() -> list[dict[str, Any]]:
    """Load default match levels from JSON."""
    if not MATCH_LEVEL_DEFAULTS_PATH.exists():
        raise FileNotFoundError(f"Missing required knowledge file: {MATCH_LEVEL_DEFAULTS_PATH}")

    try:
        payload = json.loads(MATCH_LEVEL_DEFAULTS_PATH.read_text(encoding="utf-8"))
        entries = payload.get("entries")
        if isinstance(entries, list) and entries:
            return entries
    except Exception as exc:
        raise ValueError(
            f"Failed to load match levels from {MATCH_LEVEL_DEFAULTS_PATH}: {exc}"
        ) from exc

    raise ValueError(f"Knowledge file {MATCH_LEVEL_DEFAULTS_PATH} must contain a non-empty entries list")


MATCH_LEVELS: Final[list[dict[str, Any]]] = _load_default_levels()


def normalize_match_levels(levels: object) -> list[dict[str, object]]:
    if not isinstance(levels, list):
        levels = []

    normalized: list[dict[str, object]] = []
    seen_scores: set[int] = set()
    for index, raw_level in enumerate(levels):
        if not isinstance(raw_level, dict):
            continue
        try:
            minimum_score = int(raw_level.get("minimum_score", 0) or 0)
        except Exception:
            continue
        minimum_score = max(minimum_score, 0)
        label = str(raw_level.get("label") or "").strip()
        description = str(raw_level.get("description") or "").strip()
        if not label or not description or minimum_score in seen_scores:
            continue
        normalized.append({
            "minimum_score": minimum_score,
            "label": label,
            "description": description,
            "_index": index,
        })
        seen_scores.add(minimum_score)

    if not normalized:
        normalized = [
            {
                "minimum_score": int(level["minimum_score"]),
                "label": str(level["label"]),
                "description": str(level["description"]),
                "_index": index,
            }
            for index, level in enumerate(MATCH_LEVELS)
        ]

    normalized.sort(key=lambda level: (-int(level["minimum_score"]), int(level["_index"])))
    cleaned_levels: list[dict[str, object]] = []
    for level in normalized:
        cleaned_levels.append({
            "minimum_score": int(level["minimum_score"]),
            "label": str(level["label"]),
            "description": str(level["description"]),
        })
    return cleaned_levels


def score_to_match_level(score: int, match_levels: object = None) -> dict[str, object]:
    numeric_score = int(score)
    for level in normalize_match_levels(match_levels if match_levels is not None else MATCH_LEVELS):
        if numeric_score >= int(level["minimum_score"]):
            return level
    return normalize_match_levels(match_levels if match_levels is not None else MATCH_LEVELS)[-1]


def score_to_match_label(score: int, match_levels: object = None) -> str:
    return str(score_to_match_level(score, match_levels).get("label") or "")
