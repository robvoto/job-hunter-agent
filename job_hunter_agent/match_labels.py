"""Helpers for match labels."""

from typing import Any, Final


def _load_default_levels() -> list[dict[str, Any]]:

    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge("match_level_defaults")

    if payload is None:
        raise RuntimeError("match_level_defaults not found in knowledge table — seed the DB first")

    entries = payload.get("entries")

    if not isinstance(entries, list) or not entries:
        raise ValueError("match_level_defaults must contain a non-empty entries list")

    return entries


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

        normalized.append(
            {
                "minimum_score": minimum_score,
                "label": label,
                "description": description,
                "_index": index,
            }
        )

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
        cleaned_levels.append(
            {
                "minimum_score": int(level["minimum_score"]),
                "label": str(level["label"]),
                "description": str(level["description"]),
            }
        )

    return cleaned_levels


def score_to_match_level(score: int, match_levels: object = None) -> dict[str, object]:

    numeric_score = int(score)

    for level in normalize_match_levels(match_levels if match_levels is not None else MATCH_LEVELS):
        if numeric_score >= int(level["minimum_score"]):
            return level

    return normalize_match_levels(match_levels if match_levels is not None else MATCH_LEVELS)[-1]


def score_to_match_label(score: int, match_levels: object = None) -> str:

    return str(score_to_match_level(score, match_levels).get("label") or "")
