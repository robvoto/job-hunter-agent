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


def _salary_explicit_period(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(per\s+hour|hourly|p/h|ph|/hr|/hour)\b", lowered):
        return "hourly"
    if re.search(r"\b(per\s+day|daily|p\.d\.|day\s+rate)\b|/day", lowered):
        return "daily"
    if re.search(r"\b(p\.a\.|per\s+annum|annually)\b|/yr\b|/year\b", lowered):
        return "annual"
    if re.search(r"\b(per\s+month|monthly)\b|/mo\b|/month\b", lowered):
        return "monthly"
    if re.search(r"\b(per\s+week|weekly)\b|/wk\b|/week\b", lowered):
        return "weekly"
    return ""


def _salary_implied_period(text: str, work_type: str = "") -> str:
    salary_text = compact_whitespace(text)
    if not salary_text or salary_text == "N/A":
        return ""

    explicit = _salary_explicit_period(salary_text)
    if explicit:
        return explicit

    normalized_work_type = compact_whitespace(work_type).lower()
    is_contract = bool(re.search(r"\bcontract\b|\bftc\b", normalized_work_type))
    is_permanent = bool(re.search(r"\bpermanent\b|\bfull\s*time\b", normalized_work_type))

    amount_match = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*k?\b", salary_text.replace(",", ""))
    if not amount_match:
        amount_match = re.search(r"(\d+(?:\.\d+)?)", salary_text.replace(",", ""))
    amount = float(amount_match.group(1)) if amount_match else 0.0

    if is_contract and amount > 0:
        return "hourly" if amount < 250 else "daily"

    if is_permanent and amount >= 1000:
        return "annual"

    return ""


def format_salary_display(value: str, *, work_type: str = "") -> str:
    """Return a salary string with a visible period hint when possible."""

    text = compact_whitespace(value)
    if not text or text == "N/A":
        return text or "N/A"

    explicit_period = _salary_explicit_period(text)
    if explicit_period:
        return text

    implied_period = _salary_implied_period(text, work_type)
    if implied_period:
        suffix = load_salary().get("interval_suffix", {}).get(implied_period, "")
        if suffix:
            separator = "" if suffix.startswith("/") else " "
            return f"{text}{separator}{suffix}".strip()

    return text
