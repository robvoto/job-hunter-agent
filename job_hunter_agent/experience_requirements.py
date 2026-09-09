"""Deterministic helpers for explicit experience-duration requirements.

Purpose: pull the numeric threshold out of wording like "5+ years experience as
a Business Analyst" and compare it against the saved role_experience family the
fit-review LLM has already identified.

Ownership boundary: this module does arithmetic only. Deciding which job wording
counts as the same role family (e.g. Business Analyst vs Senior Business Analyst)
is a semantic judgement that stays with the fit-review LLM, which receives the
role experience matrix and returns ``matched_role_family`` on the experience
component. There is deliberately no regex subject extraction, stemming, or
synonym table here.

Whichever name the LLM returns decides how much history is credited: a saved
family's own canonical title credits that family's whole accrued duration; a
title variant credits only that variant's own stored months, never the parent
family total; anything the profile does not hold that way is left unresolved.
"""

from __future__ import annotations

import re
from typing import Any

from job_hunter_agent.llm_protocol import (
    LLM_EXPERIENCE_COMPONENT_DURATION,
    LLM_EXPERIENCE_COMPONENT_ROLE_ACTIVITY,
)
from job_hunter_agent.role_experience_duration import effective_family_months
from job_hunter_agent.text_processing import compact_whitespace

# Range patterns are searched before the single-value patterns on purpose: the
# single-value pattern happily matches the upper bound inside a range ("5 years"
# within "3-5 years"), which would overstate the requirement. A stated range is
# lower-bounded ("3-5 years" -> 36 months, "18-24 months" -> 18).
_EXPERIENCE_MONTHS_RANGE = re.compile(
    r"(?i)\b(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*months?\b"
)
_EXPERIENCE_MONTHS_SINGLE = re.compile(
    r"(?i)\b(?:minimum of\s+|minimum\s+|at least\s+)?(\d+)\s*(?:\+)?\s*months?\b"
)
_EXPERIENCE_YEARS_RANGE = re.compile(
    r"(?i)\b(\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(\d+(?:\.\d+)?)\s*(?:years|yrs)\b"
)
_EXPERIENCE_YEARS_SINGLE = re.compile(
    r"(?i)\b(?:minimum of\s+|minimum\s+|at least\s+)?(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years|yrs)\b"
)


def extract_required_experience_months(*texts: Any) -> int | None:
    """Return the stated experience threshold in whole months, or None.

    Pure numeric parsing: it recognises "N years"/"N months" and lower-bounds a
    stated range ("3-5 years" -> 36). It never inspects the role or activity
    named alongside the duration.
    """
    for raw_text in texts:
        text = compact_whitespace(str(raw_text or ""))
        if not text:
            continue

        months_range = _EXPERIENCE_MONTHS_RANGE.search(text)
        if months_range:
            return min(int(months_range.group(1)), int(months_range.group(2)))

        months_single = _EXPERIENCE_MONTHS_SINGLE.search(text)
        if months_single:
            return int(months_single.group(1))

        years_range = _EXPERIENCE_YEARS_RANGE.search(text)
        if years_range:
            lower_years = min(float(years_range.group(1)), float(years_range.group(2)))
            return int(lower_years * 12)

        years_single = _EXPERIENCE_YEARS_SINGLE.search(text)
        if years_single:
            return int(float(years_single.group(1)) * 12)

    return None


def _llm_matched_role_family(experience_components: list[dict[str, Any]] | None) -> str:
    """Return the role family the fit-review LLM tied this requirement to.

    The LLM sets ``matched_role_family`` on the role_or_activity (or duration)
    component to the exact role experience matrix family whose accumulated
    history it judges to cover the stated role/activity. Empty means the LLM
    could not safely tie the requirement to any saved family.
    """
    if not isinstance(experience_components, list):
        return ""
    for kind in (LLM_EXPERIENCE_COMPONENT_ROLE_ACTIVITY, LLM_EXPERIENCE_COMPONENT_DURATION):
        for component in experience_components:
            if not isinstance(component, dict) or component.get("kind") != kind:
                continue
            family = compact_whitespace(component.get("matched_role_family"))
            if family:
                return family
    return ""


def _canonical_family_entry(row: dict[str, Any]) -> dict[str, Any]:
    """Family-level credit: the whole accrued role-family duration.

    ``effective_family_months`` accrues whole elapsed months onto a still-current
    canonical role segment (see role_experience_duration). Persisted role rows
    without segments are invalid and fail at that owner boundary.
    """
    title = compact_whitespace(row.get("normalized_title"))
    return {
        "family": title,
        "total_duration_months": effective_family_months(row),
        "most_recent_end_year": max(int(row.get("most_recent_end_year") or 0), 0),
    }


def _variant_entries(row: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    """Map each ``title_variants`` name to *that variant's own* stored duration.

    A sub-title never inherits the parent family total: a requirement the LLM
    ties to "Senior Business Analyst" is credited with the Senior Business
    Analyst variant's own months, not the whole Business Analyst family. A
    variant that carries no usable own duration maps to ``None`` so the caller
    keeps the row unresolved instead of falling back to the family total.

    A variant's ``total_duration_months`` is a conservative extraction-time
    snapshot. Unlike the canonical family row it carries no ``segments`` /
    ``duration_as_of`` timing, so no runtime accrual is applied here: the figure
    does not tick up between profile refreshes. For a variant of a still-current
    role it can therefore lag the canonical family total, which is accepted
    because it only ever understates the candidate (fails safe) and the row
    stays visible as a duration gap for review.
    """
    entries: dict[str, dict[str, Any] | None] = {}
    variants = row.get("title_variants")
    if not isinstance(variants, list):
        return entries
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        name = compact_whitespace(variant.get("normalized_title"))
        if not name:
            continue
        key = name.casefold()
        try:
            months = int(variant.get("total_duration_months"))
        except (TypeError, ValueError):
            months = 0
        if months <= 0:
            entries.setdefault(key, None)
            continue
        entry = {
            "family": name,
            "total_duration_months": months,
            "most_recent_end_year": max(int(variant.get("most_recent_end_year") or 0), 0),
        }
        if key in entries:
            prior = entries[key]
            if prior is None or prior["total_duration_months"] != months:
                entries[key] = None
        else:
            entries[key] = entry
    return entries


def _resolve_saved_family(
    name: str,
    role_experience: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Resolve the LLM-named role/family to a saved duration to credit.

    Precedence:
    - name equals a saved family's canonical ``normalized_title`` -> that
      family's whole accrued total.
    - otherwise name equals exactly one title variant that carries its own
      stored duration -> that variant's own months (never the family total).
    - name found only as a variant with no trustworthy own duration, or a
      variant name whose duration is inconsistent across families, or a name
      absent from the profile -> ``None``: the caller keeps the row unresolved
      for human review rather than guessing.
    """
    key = name.casefold()
    canonical: dict[str, dict[str, Any]] = {}
    variant_map: dict[str, dict[str, Any] | None] = {}
    for row in role_experience or []:
        if not isinstance(row, dict):
            continue
        title = compact_whitespace(row.get("normalized_title"))
        if title:
            canonical.setdefault(title.casefold(), _canonical_family_entry(row))
        for vkey, ventry in _variant_entries(row).items():
            if vkey not in variant_map:
                variant_map[vkey] = ventry
                continue
            prior = variant_map[vkey]
            if (
                ventry is None
                or prior is None
                or prior["total_duration_months"] != ventry["total_duration_months"]
            ):
                variant_map[vkey] = None
    if key in canonical:
        return canonical[key]
    return variant_map.get(key)


def resolve_role_experience_requirement(
    experience_components: list[dict[str, Any]] | None,
    required_months: int | None,
    role_experience: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Compare a stated experience threshold against the LLM-identified role.

    Returns None when the requirement states no duration. Otherwise:
    - the LLM's ``matched_role_family`` names a saved canonical family -> credit
      that family's whole accrued months.
    - it names a title variant with its own stored duration -> credit that
      variant's own months, not the family total.
    - it names nothing, a role the profile does not hold, or a variant with no
      trustworthy own duration -> ``role_family_resolved`` is False so the
      caller keeps the row unresolved for human review rather than asserting a
      pass or a fail.

    The months come from ``role_experience`` captured at the last CV/profile
    refresh; they are a snapshot, not a figure that ticks up on its own.
    """
    if required_months is None:
        return None

    result: dict[str, Any] = {"required_experience_months": int(required_months)}
    family = _llm_matched_role_family(experience_components)
    if not family:
        result["role_family_resolved"] = False
        return result

    saved = _resolve_saved_family(family, role_experience)
    if saved is None:
        # The LLM named a role the profile does not hold, or only a sub-title
        # with no duration of its own. Do not invent a pass or a fail, and do
        # not fall back to a parent family total. Keep the LLM's label so the
        # review note can say which role was looked for.
        result["matched_role_family"] = family
        result["role_family_resolved"] = False
        return result

    # Credit and report whatever _resolve_saved_family matched: the canonical
    # family total for a family-level tie, or the sub-title's own (smaller)
    # months for a variant tie — a sub-title never inherits the family total.
    total_months = int(saved["total_duration_months"])
    result.update(
        {
            "matched_role_family": saved["family"],
            "role_family_resolved": True,
            "matched_role_family_months": total_months,
            "matched_role_family_end_year": int(saved["most_recent_end_year"]),
            "experience_requirement_met": total_months >= int(required_months),
        }
    )
    return result
