"""Human-readable note for an explicit years/months-of-experience requirement.

Shared by the workspace card (`workspace_renderer`) and the scoring audit
(`fit_scoring`) so both describe a duration requirement's outcome with identical
wording. The copy templates live in
``data/knowledge/ui_labels.json`` under ``experience_requirement_labels`` — this
module only selects the right template and fills it.
"""

from __future__ import annotations

from job_hunter_agent.io_utils import load_ui_labels

_LABEL_GROUP = "experience_requirement_labels"


def _label(key: str) -> str:
    labels = load_ui_labels().get(_LABEL_GROUP, {})
    value = labels.get(key) if isinstance(labels, dict) else None
    if value is None or not str(value).strip():
        raise ValueError(f"ui_labels.json is missing {_LABEL_GROUP}.{key}")
    return str(value)


def experience_requirement_note(
    *,
    required_experience_months: int,
    matched_role_family: str,
    matched_role_family_months: int,
    matched_role_family_end_year: int,
    experience_requirement_met: bool,
    experience_requirement_review_needed: bool,
) -> str:
    """Return one sentence describing how role history covers a duration requirement.

    - role family resolved + duration met -> proven
    - role family resolved + duration short -> explicit gap
    - role family not resolved -> unresolved, flagged for review
    - otherwise -> just restate the stated threshold
    """
    if required_experience_months <= 0:
        return ""
    required_years = f"{required_experience_months / 12.0:g}"
    if matched_role_family:
        key = "duration_proven" if experience_requirement_met else "duration_gap"
        note = _label(key).format(
            months=matched_role_family_months,
            family=matched_role_family,
            required=required_experience_months,
        )
        if matched_role_family_end_year > 0:
            note += _label("end_year_suffix").format(end_year=matched_role_family_end_year)
        return note
    if experience_requirement_review_needed:
        return _label("role_unresolved").format(years=required_years)
    return _label("duration_only").format(years=required_years)
