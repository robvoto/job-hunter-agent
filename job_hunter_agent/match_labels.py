from typing import Final


MATCH_LEVELS: Final[list[dict[str, object]]] = [
    {
        "minimum_score": 85,
        "label": "Strong match",
        "description": "strongest fit signals",
    },
    {
        "minimum_score": 70,
        "label": "Good match",
        "description": "clear fit with fewer caveats",
    },
    {
        "minimum_score": 55,
        "label": "Worth a look",
        "description": "plausible fit worth reviewing",
    },
    {
        "minimum_score": 0,
        "label": "Stretch",
        "description": "lower-confidence or borderline fit",
    },
]


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
