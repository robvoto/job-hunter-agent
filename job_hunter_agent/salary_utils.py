"""Helpers for salary utils."""

import re

from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.text_processing import compact_whitespace


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
    explicit_flag = 1 if _salary_explicit_period(text) else 0

    amount_count = len(re.findall(r"\$?\d+(?:\.\d+)?\s*k?", normalized))

    return explicit_flag, amount_count * 1000 + len(text)


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


def _salary_explicit_period(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:\bper\s+hour\b|\bhourly\b|\bp/h\b|\bph\b|/hr\b|/hour\b)", lowered):
        return "hourly"
    if re.search(r"(?:\bper\s+day\b|\bdaily\b|\bp\.?/?d\.?\b|\bday\s+rate\b|/day\b|/d\b)", lowered):
        return "daily"
    if re.search(r"(?:\bp\.a\.|\bper\s+annum\b|\bannually\b|/yr\b|/year\b)", lowered):
        return "annual"
    if re.search(r"(?:\bper\s+month\b|\bmonthly\b|/mo\b|/month\b)", lowered):
        return "monthly"
    if re.search(r"(?:\bper\s+week\b|\bweekly\b|/wk\b|/week\b)", lowered):
        return "weekly"
    return ""


def format_salary_display(value: str, *, work_type: str = "") -> str:
    """Return a salary string with a visible period hint when possible."""

    text = compact_whitespace(value)
    if not text or text == "N/A":
        return text or "N/A"

    explicit_period = _salary_explicit_period(text)
    if explicit_period:
        return text
    return text
