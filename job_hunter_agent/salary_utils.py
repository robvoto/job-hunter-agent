import re


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


def _salary_max_value(value: str) -> float:
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


def _salary_includes_super_or_package(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text or text == "n/a":
        return False
    return bool(re.search(r"(?:\bincl\.?\s*super\b|\bincluding\s+super\b|\+\s*super\b|\bsuperannuation\b|\bpackage\b|\bsalary packaging\b)", text))
