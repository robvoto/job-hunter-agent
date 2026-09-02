"""Effective duration of a saved role family, accrued forward to a given date.

``role_experience`` rows persist ``total_duration_months`` as a snapshot taken at
the last CV/profile extraction. For a role the candidate still holds, that number
does not grow on its own. Each family row also carries ``segments`` — one entry
per extracted role segment with ``duration_months`` and ``is_current``, and, for
current segments, ``duration_as_of`` (the date the duration was extracted).

This module turns those segments into an *effective* family total: completed
segments contribute their stored months; a current segment contributes its stored
months plus the whole calendar months elapsed since ``duration_as_of``.

Ownership boundary: pure date arithmetic. No role-family semantics, no threshold
policy, no user-facing text. Legacy rows without ``segments`` pass through with
their stored ``total_duration_months`` untouched.
"""

from __future__ import annotations

from datetime import date
from typing import Any

_SEGMENTS_KEY = "segments"
_TOTAL_MONTHS_KEY = "total_duration_months"


def whole_months_between(start: date, end: date) -> int:
    """Whole calendar months from ``start`` to ``end``, floored at 0.

    A partial final month does not count: 2024-01-10 -> 2024-03-05 is one whole
    month, 2024-01-10 -> 2024-03-10 is two.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _parse_iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def effective_family_months(row: dict[str, Any], *, as_of: date | None = None) -> int:
    """Return the family's accrued duration in whole months as of ``as_of``.

    ``as_of`` defaults to today. A row with no ``segments`` list is a legacy row
    and returns its stored ``total_duration_months`` unchanged. A current segment
    with a missing or unparseable ``duration_as_of`` contributes its stored
    months only — an honest floor, never a fabricated accrual.
    """
    if not isinstance(row, dict):
        return 0

    segments = row.get(_SEGMENTS_KEY)
    if not isinstance(segments, list) or not segments:
        return max(int(row.get(_TOTAL_MONTHS_KEY) or 0), 0)

    reference = as_of or date.today()
    total = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        months = max(int(segment.get("duration_months") or 0), 0)
        if segment.get("is_current"):
            extracted_on = _parse_iso_date(segment.get("duration_as_of"))
            if extracted_on is not None:
                months += whole_months_between(extracted_on, reference)
        total += months
    return total


def apply_effective_durations(
    role_experience: Any, *, as_of: date | None = None
) -> list[Any]:
    """Copy ``role_experience`` with each family's ``total_duration_months`` set to
    its effective (accrued) value. ``title_variants`` are left as stored — they
    are prompt-informational only and never drive the duration comparison.
    """
    if not isinstance(role_experience, list):
        return []
    result: list[Any] = []
    for row in role_experience:
        if not isinstance(row, dict):
            result.append(row)
            continue
        updated = dict(row)
        updated[_TOTAL_MONTHS_KEY] = effective_family_months(row, as_of=as_of)
        result.append(updated)
    return result
