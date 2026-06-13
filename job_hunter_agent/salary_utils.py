"""Helpers for salary utils."""

import re

from job_hunter_agent.io_utils import load_parsing_rules


def salary_sort_value(value: str) -> float:
    """Return a single numeric value for sorting (uses the lower bound of ranges)."""

    if not value or value == "N/A":
        return 0.0

    text = value.lower().replace(",", "").strip()

    match = re.search(r"(\d+(?:\.\d+)?)\s*k", text)

    if match:
        return float(match.group(1)) * 1000

    match = re.search(r"\$(\d+(?:\.\d+)?)", text)

    if match:
        return float(match.group(1))

    return 0.0


def salary_max_value(value: str) -> float:
    """Return the upper bound of a salary range for minimum-target comparisons.



    For '$450 - $700 per day' returns 700; for '$130k-$145k p.a.' returns 145000.

    Falls back to salary_sort_value when only one figure is present.

    """

    if not value or value == "N/A":
        return 0.0

    text = value.lower().replace(",", "").strip()

    k_vals = [float(m) * 1000 for m in re.findall(r"(\d+(?:\.\d+)?)\s*k", text)]

    if k_vals:
        return max(k_vals)

    dollar_vals = [float(m) for m in re.findall(r"\$(\d+(?:\.\d+)?)", text)]

    if dollar_vals:
        return max(dollar_vals)

    return 0.0


def salary_display_score(value: str) -> tuple[int, int]:

    text = str(value or "").strip()

    if not text or text == "N/A":
        return (0, 0)

    normalized = text.lower().replace(",", "")

    amount_count = len(re.findall(r"\$?\d+(?:\.\d+)?\s*k?", normalized))

    return amount_count, len(text)


def preferred_salary_display(*values: str) -> str:

    best_value = ""

    best_score = (-1, -1)

    for value in values:
        text = str(value or "").strip()

        if not text or text == "N/A":
            continue

        score = salary_display_score(text)

        if score > best_score:
            best_score = score

            best_value = text

    return best_value


def salary_includes_super_or_package(value: str) -> bool:

    text = str(value or "").strip().lower()

    if not text or text == "n/a":
        return False

    rules = load_parsing_rules()

    indicators = rules.get("salary_package_indicators", [])

    if not indicators:
        return False

    pattern = rf"(?:\b{'|'.join(indicators)}\b)"

    return bool(re.search(pattern, text, re.IGNORECASE))
