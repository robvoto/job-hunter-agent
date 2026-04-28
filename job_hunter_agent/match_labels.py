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


def score_to_match_label(score: int) -> str:
    numeric_score = int(score)
    for level in MATCH_LEVELS:
        if numeric_score >= int(level["minimum_score"]):
            return str(level["label"])
    return str(MATCH_LEVELS[-1]["label"])
