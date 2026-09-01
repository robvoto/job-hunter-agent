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
"""

from __future__ import annotations

import re
from typing import Any

from job_hunter_agent.llm_protocol import (
    LLM_EXPERIENCE_COMPONENT_DURATION,
    LLM_EXPERIENCE_COMPONENT_ROLE_ACTIVITY,
)
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


def _role_experience_family_lookup(
    role_experience: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Index saved role families by every name they are known under (casefolded).

    Both the family's own ``normalized_title`` and each ``title_variants`` entry
    resolve to the same family row, so an LLM that names a sub-title (e.g.
    "Senior Business Analyst") still lands on the accumulated family total — and
    ``family`` carries the canonical ``normalized_title`` so the caller reports
    and credits the whole family, never the sub-title it was asked about.
    """
    lookup: dict[str, dict[str, Any]] = {}
    for row in role_experience or []:
        if not isinstance(row, dict):
            continue
        title = compact_whitespace(row.get("normalized_title"))
        if not title:
            continue
        entry = {
            "family": title,
            "total_duration_months": max(int(row.get("total_duration_months") or 0), 0),
            "most_recent_end_year": max(int(row.get("most_recent_end_year") or 0), 0),
        }
        names = {title.casefold()}
        variants = row.get("title_variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_title = compact_whitespace(variant.get("normalized_title"))
                if variant_title:
                    names.add(variant_title.casefold())
        for name in names:
            lookup.setdefault(name, entry)
    return lookup


def resolve_role_experience_requirement(
    experience_components: list[dict[str, Any]] | None,
    required_months: int | None,
    role_experience: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Compare a stated experience threshold against the LLM-identified family.

    Returns None when the requirement states no duration. Otherwise:
    - ``matched_role_family`` present + found in role history -> reports the
      canonical family name, its accumulated months, and whether they meet
      ``required_months``.
    - ``matched_role_family`` present but absent from role history, or empty ->
      ``role_family_resolved`` is False so the caller keeps the row unresolved
      for human review rather than asserting a pass or a fail.

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

    saved = _role_experience_family_lookup(role_experience).get(family.casefold())
    if saved is None:
        # The LLM named a family the profile does not actually hold; do not
        # invent a pass or a fail from that. Keep the LLM's label so the review
        # note can say which family was looked for.
        result["matched_role_family"] = family
        result["role_family_resolved"] = False
        return result

    # Report and credit the canonical family, never the sub-title the LLM was
    # asked about: labelling the whole Business Analyst family total as "Senior
    # Business Analyst" would overstate seniority.
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
