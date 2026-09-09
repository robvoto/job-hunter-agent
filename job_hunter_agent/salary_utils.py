"""Helpers for salary utils."""

import re

from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.salary import load_salary
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


def salary_period_classification(value: str) -> tuple[str, str]:
    """Return ``(period, confidence)`` for a salary/rate string.

    Explicit source wording always wins. When the source omits the period,
    use conservative Australian amount bands from ``salary.json``. Amounts
    outside those clear bands deliberately remain uncertain rather than being
    forced into an hourly/daily/annual interpretation.
    """

    text = compact_whitespace(value)
    if not text or text == "N/A":
        return "", "unknown"

    explicit_period = _salary_explicit_period(text)
    if explicit_period:
        return explicit_period, "explicit"

    amount = salary_max_value(text)
    if amount <= 0:
        return "", "unknown"

    rules = load_salary().get("period_inference", {})
    if not isinstance(rules, dict):
        return "", "uncertain"

    try:
        annual_min = float(rules["annual_min"])
        hourly_max = float(rules["hourly_max"])
        daily_min = float(rules["daily_min"])
        daily_max = float(rules["daily_max"])
    except (KeyError, TypeError, ValueError):
        return "", "uncertain"

    if amount >= annual_min:
        return "annual", "inferred"
    if amount <= hourly_max:
        return "hourly", "inferred"
    if daily_min <= amount <= daily_max:
        return "daily", "inferred"
    return "", "uncertain"


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


def salary_is_total_package(value: str) -> bool:
    """Return True when the stated amount is a total/inclusive package.

    ``$120k + super`` is a base salary plus super and remains comparable to
    a base-salary preference. ``$120k package`` or ``$120k incl super`` is a
    different compensation basis, so callers should not hard-compare it to a
    base-salary floor.
    """

    text = compact_whitespace(value).lower()
    if not text or text == "n/a":
        return False
    if re.search(r"\+\s*super(?:annuation)?\b", text):
        return False
    return bool(
        re.search(
            r"\b(?:incl\.?\s*super|including\s+super|package|salary\s+packaging|superannuation)\b",
            text,
        )
    )


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
    """Return salary text with transparent inferred/uncertain period hints."""

    text = compact_whitespace(value)
    if not text or text == "N/A":
        return text or "N/A"

    period, confidence = salary_period_classification(text)
    if confidence == "explicit":
        return text
    if confidence == "inferred":
        label = {
            "annual": "likely p.a.",
            "daily": "likely daily",
            "hourly": "likely hourly",
        }.get(period, "")
        if label:
            return f"{text} ({label})"
    if confidence == "uncertain":
        return f"{text} (period unclear)"
    return text
