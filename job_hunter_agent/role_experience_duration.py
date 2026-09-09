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
policy, no user-facing text. ``segments`` is the only supported role-duration
contract; incomplete rows fail explicitly instead of using an older aggregate shape.
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

    ``as_of`` defaults to today. Every row must contain a non-empty ``segments``
    list. Every current segment must contain a valid ISO ``duration_as_of`` date.
    Invalid canonical data fails explicitly at runtime; there is no legacy fallback.
    """
    if not isinstance(row, dict):
        raise TypeError("role_experience row must be a dict")

    segments = row.get(_SEGMENTS_KEY)
    if not isinstance(segments, list) or not segments:
        raise ValueError("role_experience row requires a non-empty segments list")

    reference = as_of or date.today()
    total = 0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("role_experience segments must contain dict rows")
        months = max(int(segment.get("duration_months") or 0), 0)
        if segment.get("is_current"):
            extracted_on = _parse_iso_date(segment.get("duration_as_of"))
            if extracted_on is None:
                raise ValueError("current role_experience segment requires valid duration_as_of")
            months += whole_months_between(extracted_on, reference)
        total += months
    return total


def apply_effective_durations(
    role_experience: Any, *, as_of: date | None = None
) -> list[Any]:
    """Copy ``role_experience`` with each family's ``total_duration_months`` set to
    its effective (accrued) value.

    ``title_variants`` are left exactly as stored. This function accrues a
    still-current role forward only at the canonical family level, because only
    the family row carries the per-segment ``is_current`` / ``duration_as_of``
    timing needed to do so. A variant carries a flat ``total_duration_months``
    with no timing, so there is nothing here to accrue.

    Variant months are still consumed as scoring evidence elsewhere:
    ``experience_requirements._variant_entries`` credits a requirement tied to a
    specific sub-title with that variant's own stored months. That figure is an
    extraction-time snapshot and does not tick up between profile refreshes; for
    a variant of a still-current role it can lag the canonical family, which is
    accepted because it only ever understates (fails safe).
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
