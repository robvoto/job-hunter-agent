"""Fit scoring helpers.

Purpose: score covered requirements and render explainable fit breakdowns.
"""

import json
import logging
from typing import Any, List, Optional

from job_hunter_agent.capability_matching import (
    find_profile_capability_matches,
)

logger = logging.getLogger(__name__)
from job_hunter_agent.global_settings import KEY_FIT_HIGHLIGHTS, load_global_settings
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.paths import UNCERTAINTY_LOG_PATH
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
    LLM_ALLOWED_OCCUPATION_ALIGNMENTS,
)
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    KEY_CAPABILITY_LEVEL_WEIGHTS,
    KEY_OCCUPATION_ALIGNMENT,
    KEY_REQUIREMENT_IMPORTANCE_WEIGHTS,
    KEY_REQUIREMENT_STATUS_WEIGHTS,
    CapabilityLevel,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.record_schema import (
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
    RECORD_OCCUPATION_ALIGNMENT_KEY,
    RECORD_OCCUPATION_ALIGNMENT_REASON_KEY,
    RECORD_RUN_STARTED_AT_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)
from job_hunter_agent.role_analysis import (
    friendly_capability_label,
    role_text_bundle,
)
from job_hunter_agent.runtime_helpers import append_uncertainty_log, build_uncertainty_entry
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.signal_detection import (
    competitive_fit_highlights,
    hard_block_reasons,
)
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order, list_to_phrase

LLM_REVIEW_STATE_EVALUATED = "evaluated"
LLM_REVIEW_STATE_INVALID = "invalid"
LLM_REVIEW_INCOMPLETE_LABEL = "LLM review incomplete"

# Debug audit rows must read the same words as the job card UI (Mandatory/Expected/
# Preferred/Bonus, In profile/Partial match/etc, Strong/Working/...) instead of
# title-casing the raw enum values — otherwise the same status shows up as two
# different phrases depending on which view you're looking at.
_AUDIT_IMPORTANCE_LABEL_KEYS = {
    "mandatory": "importance_mandatory",
    "strongly_preferred": "importance_strongly_preferred",
    "preferred": "importance_preferred",
    "nice_to_have": "importance_nice_to_have",
}
_AUDIT_STATUS_LABEL_KEYS = {
    "supported": "coverage_status_supported",
    "partially_supported": "coverage_status_partially_supported",
    "mismatch": "coverage_status_mismatch",
    "invalid": "coverage_status_invalid",
    # "not_shown" has no badge text in the main UI (redundant there with the
    # "Needs attention" group heading), but the audit table needs a non-blank
    # status for every row, so reuse the mandatory-gap wording — it's accurate
    # regardless of importance.
    "not_shown": "coverage_status_mandatory_not_shown",
}


def _audit_card_label(key: str) -> str:
    labels = load_ui_labels().get("workspace_card_labels", {})
    value = labels.get(key) if isinstance(labels, dict) else None
    if not value:
        raise ValueError(f"ui_labels.json is missing workspace_card_labels.{key}")
    return str(value)


def _audit_level_label(candidate_level: str) -> str:
    if not candidate_level:
        return "Unresolved"
    labels = load_ui_labels().get("level_labels", {})
    value = labels.get(candidate_level) if isinstance(labels, dict) else None
    if value:
        return str(value)
    # Eligibility rows use "confirmed" rather than a graded capability level —
    # that's not in level_labels, but it's already plain English.
    return candidate_level.replace("_", " ").title()


REQUIREMENT_MAPPING_UNCERTAIN_REASON = "requirement_capability_mapping_uncertain"
ELIGIBILITY_GATE_NOT_APPLICABLE = "not_applicable"
ELIGIBILITY_GATE_PASS = "pass"
ELIGIBILITY_GATE_FAIL = "fail"
ELIGIBILITY_GATE_UNRESOLVED = "unresolved"


def _requirement_importance_weights(scoring_rules: dict) -> dict[str, float]:
    weights = scoring_rules.get(KEY_REQUIREMENT_IMPORTANCE_WEIGHTS)
    if not isinstance(weights, dict) or not weights:
        raise ValueError("requirement_importance_weights are required in scoring_rules")
    return weights


def _capability_level_credits(scoring_rules: dict) -> dict[str, float]:
    credits = scoring_rules.get(KEY_CAPABILITY_LEVEL_WEIGHTS)
    if not isinstance(credits, dict) or not credits:
        raise ValueError("capability_level_weights are required in scoring_rules")
    return credits


def _requirement_status_weights(scoring_rules: dict) -> dict[str, float]:
    weights = scoring_rules.get(KEY_REQUIREMENT_STATUS_WEIGHTS)
    if not isinstance(weights, dict) or not weights:
        raise ValueError("requirement_status_weights are required in scoring_rules")
    for key in ("supported", "partially_supported"):
        if key not in weights:
            raise ValueError(f"{KEY_REQUIREMENT_STATUS_WEIGHTS} must define {key!r}")
    return weights


def _occupation_alignment_adjustments(scoring_rules: dict) -> dict[str, int]:
    adjustments = scoring_rules.get(KEY_OCCUPATION_ALIGNMENT)
    if not isinstance(adjustments, dict) or not adjustments:
        raise ValueError("occupation_alignment adjustments are required in scoring_rules")
    for key in LLM_ALLOWED_OCCUPATION_ALIGNMENTS:
        if key not in adjustments:
            raise ValueError(f"{KEY_OCCUPATION_ALIGNMENT} must define {key!r}")
    return adjustments


def _normalise_lookup_text(value: str) -> str:
    return compact_whitespace(str(value or "")).strip().lower().replace("_", " ")


def _candidate_capability_level_lookup(profile: dict, capability_credits: dict) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for rule in profile.get("candidate_capabilities", []) or []:
        if not isinstance(rule, dict):
            continue
        level = str(rule.get("level") or "").strip().lower()
        if level not in capability_credits:
            continue
        names = [rule.get("name"), friendly_capability_label(str(rule.get("name") or ""))]
        aliases = rule.get("aliases") or []
        if isinstance(aliases, str):
            names.append(aliases)
        else:
            names.extend(aliases)
        for name in names:
            key = _normalise_lookup_text(str(name or ""))
            if key:
                lookup[key] = level
    return lookup


def _candidate_eligibility_lookup(profile: dict) -> dict[str, bool]:
    lookup: dict[str, bool] = {}
    for item in [
        *(profile.get(KEY_CANDIDATE_ELIGIBILITY, []) or []),
        *(profile.get(KEY_CANDIDATE_ELIGIBILITY_FACTS, []) or []),
    ]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        key = _normalise_lookup_text(name)
        if key:
            lookup[key] = bool(item.get("value", True))
    return lookup


def _append_requirement_mapping_uncertainty(record: dict, item: dict, detail: str) -> None:
    raw_value = {
        "requirement": item.get("requirement"),
        "proposed_capability": item.get("capability_name"),
        "proposed_eligibility": item.get("eligibility_name"),
        "requirement_type": item.get("requirement_type"),
        "status": item.get("status"),
        "matched_job_text": item.get("matched_job_text"),
    }
    entry = build_uncertainty_entry(
        reason_code=REQUIREMENT_MAPPING_UNCERTAIN_REASON,
        stage="fit_scoring",
        field="requirement_coverage.capability_name",
        raw_value=json.dumps(raw_value, ensure_ascii=False),
        normalized_value="",
        detail=detail,
        source=str(record.get("source") or record.get("platform") or ""),
        job_key=str(record.get("job_key") or ""),
        severity="warning",
    )
    append_uncertainty_log(UNCERTAINTY_LOG_PATH, entry)
    fingerprint = make_system_warning_fingerprint(
        "fit_scoring",
        REQUIREMENT_MAPPING_UNCERTAIN_REASON,
        record.get("source") or record.get("platform") or "",
        record.get("job_key") or "",
        record.get(RECORD_RUN_STARTED_AT_KEY) or "",
        item.get("requirement") or "",
        item.get("status") or "",
        item.get("requirement_type") or "",
        item.get("capability_name") or item.get("eligibility_name") or "",
        detail,
    )
    record_system_warning(
        severity="warning",
        category="requirement_coverage_uncertainty",
        source=str(record.get("source") or record.get("platform") or "fit_scoring"),
        message=str(detail),
        fingerprint=fingerprint,
        job_key=str(record.get("job_key") or ""),
        run_id=str(record.get(RECORD_RUN_STARTED_AT_KEY) or ""),
        context={
            "reason_code": REQUIREMENT_MAPPING_UNCERTAIN_REASON,
            "field": "requirement_coverage.capability_name",
            "raw_value": raw_value,
            "normalized_value": "",
            "detail": detail,
            "stage": "fit_scoring",
        },
    )


def eligibility_gate_diagnostics(record: dict, profile: Optional[dict] = None) -> dict[str, Any]:
    """Return shared eligibility-gate status from requirement_coverage.

    Eligibility is a gate, not a score contributor. This helper is shared by logs
    and debug UI so the explanation stays aligned with the same review payload.
    """

    active_profile = profile or load_profile()
    eligibility_levels = _candidate_eligibility_lookup(active_profile)
    coverage = record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []
    if not isinstance(coverage, list):
        coverage = []

    relevant_rows: list[dict[str, Any]] = []
    for item in coverage:
        if not isinstance(item, dict):
            continue
        if str(item.get("requirement_type") or "").strip().lower() != "eligibility":
            continue
        relevant_rows.append(item)

    if not relevant_rows:
        return {
            "status": ELIGIBILITY_GATE_NOT_APPLICABLE,
            "label": "Not applicable",
            "reason": "No eligibility requirements were returned.",
        }

    unresolved = 0
    for item in relevant_rows:
        status = str(item.get("status") or "").strip().lower()
        matched_candidate_fact = compact_whitespace(
            str(
                item.get("matched_candidate_fact")
                or item.get("profile_name")
                or item.get("eligibility_name")
                or ""
            )
        )
        eligibility_key = _normalise_lookup_text(matched_candidate_fact)
        if status == "mismatch":
            return {
                "status": ELIGIBILITY_GATE_FAIL,
                "label": "Fail",
                "reason": compact_whitespace(str(item.get("requirement") or "Eligibility mismatch")),
            }
        if status in {"supported", "partially_supported"}:
            if not matched_candidate_fact or eligibility_key not in eligibility_levels:
                unresolved += 1
                continue
            if not eligibility_levels.get(eligibility_key, False):
                return {
                    "status": ELIGIBILITY_GATE_FAIL,
                    "label": "Fail",
                    "reason": compact_whitespace(
                        str(item.get("requirement") or matched_candidate_fact or "Eligibility mismatch")
                    ),
                }
            continue
        if status == "not_shown":
            unresolved += 1
            continue
        unresolved += 1

    if unresolved:
        return {
            "status": ELIGIBILITY_GATE_UNRESOLVED,
            "label": "Unresolved",
            "reason": f"{unresolved} eligibility requirement(s) were unresolved.",
        }

    return {
        "status": ELIGIBILITY_GATE_PASS,
        "label": "Pass",
        "reason": f"{len(relevant_rows)} eligibility requirement(s) passed.",
    }


def requirement_fit_audit_rows(record: dict, profile: Optional[dict] = None) -> List[dict]:
    """Return the exact per-requirement inputs and credit used by fit scoring."""

    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    importance_weights = _requirement_importance_weights(scoring_rules)
    capability_credits = _capability_level_credits(scoring_rules)
    status_weights = _requirement_status_weights(scoring_rules)
    capability_levels = _candidate_capability_level_lookup(active_profile, capability_credits)
    eligibility_levels = _candidate_eligibility_lookup(active_profile)
    coverage = record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []
    if not isinstance(coverage, list):
        return []

    rows: List[dict] = []
    for item in coverage:
        if not isinstance(item, dict):
            continue
        requirement = compact_whitespace(str(item.get("requirement") or ""))
        if not requirement:
            continue
        importance = str(item.get("importance") or "").strip().lower()
        if importance not in importance_weights:
            raise ValueError(f"Unknown requirement importance in coverage: {importance!r}")
        requirement_type = str(item.get("requirement_type") or "").strip().lower()
        status = str(item.get("status") or "").strip().lower()
        matched_candidate_fact = str(
            item.get("matched_candidate_fact") or item.get("profile_name") or ""
        ).strip()
        weight = importance_weights[importance]
        is_eligibility_gate = requirement_type == "eligibility"
        scoring_weight = 0.0 if is_eligibility_gate else weight
        candidate_level = ""
        level_credit = 0.0
        status_credit = 0.0
        credit_fraction = 0.0

        if status in {"supported", "partially_supported"}:
            status_credit = float(status_weights[status])
            if requirement_type == "eligibility":
                eligibility_key = _normalise_lookup_text(matched_candidate_fact)
                if eligibility_key in eligibility_levels and eligibility_levels[eligibility_key]:
                    candidate_level = "confirmed"
                    level_credit = 0.0
                    credit_fraction = 0.0
            elif requirement_type in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
                capability_key = _normalise_lookup_text(matched_candidate_fact)
                candidate_level = capability_levels.get(capability_key, "")
                if candidate_level:
                    level_credit = capability_credits[candidate_level]
                    credit_fraction = level_credit * status_credit

        raw_support = item.get("profile_support") or []
        if isinstance(raw_support, str):
            raw_support = [raw_support]
        profile_support = [
            compact_whitespace(str(value))
            for value in raw_support
            if compact_whitespace(str(value))
        ] if isinstance(raw_support, list) else []

        rows.append(
            {
                "requirement": requirement,
                "importance": importance,
                "requirement_type": requirement_type,
                "status": status,
                "matched_candidate_fact": matched_candidate_fact,
                "candidate_level": candidate_level,
                "matched_job_text": compact_whitespace(str(item.get("matched_job_text") or "")),
                "match_source": compact_whitespace(str(item.get("match_source") or "")).lower(),
                "matched_profile_term": compact_whitespace(
                    str(item.get("matched_profile_term") or "")
                ),
                "profile_support": profile_support,
                "requirement_weight": scoring_weight,
                "raw_requirement_weight": weight,
                "is_eligibility_gate": is_eligibility_gate,
                "level_credit": level_credit,
                "status_credit": status_credit,
                "credit_fraction": credit_fraction,
                "weighted_credit": scoring_weight * credit_fraction,
                "required_experience_months": int(item.get("required_experience_months") or 0),
                "matched_role_experience_title": compact_whitespace(
                    str(item.get("matched_role_experience_title") or "")
                ),
                "matched_role_experience_months": int(
                    item.get("matched_role_experience_months") or 0
                ),
                "matched_role_experience_end_year": int(
                    item.get("matched_role_experience_end_year") or 0
                ),
                "experience_requirement_met": bool(item.get("experience_requirement_met")),
                "experience_requirement_review_needed": bool(
                    item.get("experience_requirement_review_needed")
                ),
            }
        )
        if item.get("role_defining"):
            rows[-1]["role_defining"] = True
        role_defining_group = compact_whitespace(
            str(item.get("role_defining_group") or "")
        ).lower()
        if role_defining_group:
            rows[-1]["role_defining_group"] = role_defining_group
    return rows


def requirement_fit_diagnostics(record: dict, profile: Optional[dict] = None) -> dict[str, Any]:
    """Return shared requirement-fit diagnostics for logs and debug UI.

    Uses requirement_fit_audit_rows() as the scoring source of truth so the UI and
    logs cannot drift from the actual calculation.
    """

    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    rows = requirement_fit_audit_rows(record, active_profile)
    earned_weighted_credit = sum(float(row["weighted_credit"]) for row in rows)
    total_requirement_weight = sum(float(row["requirement_weight"]) for row in rows)
    final_requirement_fit = (
        round((earned_weighted_credit / total_requirement_weight) * 100)
        if total_requirement_weight > 0
        else 0
    )

    role_gap_rules = scoring_rules.get("role_defining_gap_control", {})
    if not isinstance(role_gap_rules, dict):
        role_gap_rules = {}
    min_group_requirements = int(role_gap_rules.get("min_group_requirements") or 0)
    uncovered_ratio_threshold = float(role_gap_rules.get("uncovered_ratio_threshold") or 1.0)
    max_score_when_uncovered = int(role_gap_rules.get("max_score_when_uncovered") or 100)
    role_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = compact_whitespace(str(row.get("role_defining_group") or "")).lower()
        if row.get("role_defining") and group:
            role_groups.setdefault(group, []).append(row)
    role_defining_caps: list[dict[str, Any]] = []
    for group, group_rows in role_groups.items():
        if len(group_rows) < min_group_requirements:
            continue
        uncovered = [
            row for row in group_rows
            if str(row.get("status") or "").lower() not in {"supported", "partially_supported"}
        ]
        uncovered_ratio = len(uncovered) / len(group_rows)
        if uncovered_ratio >= uncovered_ratio_threshold:
            final_requirement_fit = min(final_requirement_fit, max_score_when_uncovered)
            role_defining_caps.append({
                "group": group,
                "requirements": len(group_rows),
                "uncovered": len(uncovered),
                "uncovered_ratio": uncovered_ratio,
                "score_cap": max_score_when_uncovered,
            })

    detailed_rows: list[dict[str, Any]] = []
    for row in rows:
        requirement_type = str(row["requirement_type"] or "").strip().lower() or "capability"
        candidate_level = str(row["candidate_level"] or "").strip()
        matched_candidate_fact = compact_whitespace(str(row["matched_candidate_fact"] or ""))
        mapping_label = matched_candidate_fact or "Unresolved mapping"
        if candidate_level:
            mapping_label = f"{mapping_label} ({candidate_level})"
        level_credit = float(row.get("level_credit") or 0.0)
        status_credit = float(row.get("status_credit") or 0.0)
        match_source = compact_whitespace(str(row.get("match_source") or "")).lower()
        matched_profile_term = compact_whitespace(str(row.get("matched_profile_term") or ""))
        required_experience_months = int(row.get("required_experience_months") or 0)
        matched_role_experience_title = compact_whitespace(
            str(row.get("matched_role_experience_title") or "")
        )
        matched_role_experience_months = int(row.get("matched_role_experience_months") or 0)
        matched_role_experience_end_year = int(row.get("matched_role_experience_end_year") or 0)
        experience_requirement_review_needed = bool(
            row.get("experience_requirement_review_needed")
        )
        if required_experience_months > 0:
            required_years = required_experience_months / 12.0
            if matched_role_experience_title:
                experience_evidence_label = (
                    f"Role history: {matched_role_experience_title} "
                    f"{matched_role_experience_months} months matched against "
                    f"required {required_experience_months} months"
                )
                if matched_role_experience_end_year > 0:
                    experience_evidence_label += (
                        f" (most recent end year {matched_role_experience_end_year})"
                    )
            elif experience_requirement_review_needed:
                experience_evidence_label = (
                    f"Role history: requirement asks for {required_years:g} years, "
                    "but the saved role titles did not prove a matching role family."
                )
            else:
                experience_evidence_label = (
                    f"Role history: requirement asks for {required_years:g} years."
                )
        else:
            experience_evidence_label = ""
        importance_key = str(row["importance"]).strip().lower()
        status_key = str(row["status"]).strip().lower()
        detailed_rows.append(
            {
                **row,
                "importance_label": _audit_card_label(
                    _AUDIT_IMPORTANCE_LABEL_KEYS.get(importance_key, "importance_preferred")
                ),
                "requirement_type_label": requirement_type.replace("_", " ").title(),
                "status_label": _audit_card_label(
                    _AUDIT_STATUS_LABEL_KEYS.get(status_key, "coverage_status_mismatch")
                ),
                "mapping_label": mapping_label,
                "candidate_level_label": _audit_level_label(candidate_level),
                "match_source_label": (
                    match_source.replace("_", " ").title() if match_source else "Unresolved"
                ),
                "matched_profile_term_label": matched_profile_term or "Unresolved",
                "profile_support_label": "; ".join(row["profile_support"])
                or "No profile evidence returned",
                "experience_evidence_label": experience_evidence_label,
                "calculation_label": (
                    "Eligibility gate only — no points added"
                    if row.get("is_eligibility_gate")
                    else (
                        f"{float(row['requirement_weight']):g} × "
                        f"{level_credit:g} × "
                        f"{status_credit:g} = "
                        f"{float(row['weighted_credit']):g} / {float(row['requirement_weight']):g}"
                    )
                ),
            }
        )

    return {
        "rows": detailed_rows,
        "earned_weighted_credit": earned_weighted_credit,
        "total_requirement_weight": total_requirement_weight,
        "final_requirement_fit": final_requirement_fit,
        "role_defining_caps": role_defining_caps,
        "final_calculation_label": (
            f"{earned_weighted_credit:g} ÷ {total_requirement_weight:g} × 100"
            if total_requirement_weight > 0
            else "0 ÷ 0 × 100"
        ),
    }


def format_requirement_fit_diagnostics_lines(record: dict, profile: Optional[dict] = None) -> list[str]:
    """Format transparent per-requirement scoring diagnostics for logs/debug views."""

    diagnostics = requirement_fit_diagnostics(record, profile)
    eligibility_gate = eligibility_gate_diagnostics(record, profile)
    lines: list[str] = []
    for row in diagnostics["rows"]:
        lines.extend(
            [
                f"Requirement: {row['requirement']}",
                f"Importance: {row['importance_label']}",
                f"Requirement type: {row['requirement_type_label']}",
                f"Coverage: {row['status_label']}",
                f"Mapped to: {row['mapping_label']}",
                f"Matched via: {row['match_source_label']}",
                f"Matched term: {row['matched_profile_term_label']}",
                f"Candidate level: {row['candidate_level_label']}",
                (
                    f"Calculation: {row['calculation_label']}"
                    if row.get("is_eligibility_gate")
                    else (
                        f"Calculation: {row['calculation_label']}"
                        f" ({float(row['credit_fraction']) * 100:.0f}%)"
                    )
                ),
                f"Profile evidence used: {row['profile_support_label']}",
            ]
        )
    lines.extend(
        [
            f"Eligibility gate: {eligibility_gate['label']}",
            f"Earned weighted credit: {diagnostics['earned_weighted_credit']:g}",
            f"Total requirement weight: {diagnostics['total_requirement_weight']:g}",
            f"Calculation: {diagnostics['final_calculation_label']}",
            f"Final Requirement Fit: {diagnostics['final_requirement_fit']}%",
        ]
    )
    return lines


def format_requirement_fit_diagnostics_block(
    record: dict,
    profile: Optional[dict] = None,
    *,
    decision: str = "",
    grade: str = "",
    debug_reason: str = "",
) -> str:
    """Format one compact per-job diagnostics block for logs."""

    diagnostics = requirement_fit_diagnostics(record, profile)
    eligibility_gate = eligibility_gate_diagnostics(record, profile)
    summary_lines = [
        "  Requirement scoring",
        (
            "  Outcome: "
            f"{compact_whitespace(decision) or 'Unavailable'}"
            + (
                f" | Grade: {compact_whitespace(grade)}"
                if compact_whitespace(grade)
                else ""
            )
            + f" | Requirement Fit: {diagnostics['final_requirement_fit']}%"
        ),
        (
            "  Earned: "
            f"{diagnostics['earned_weighted_credit']:g} / {diagnostics['total_requirement_weight']:g}"
        ),
        f"  Eligibility gate: {eligibility_gate['label']} | {compact_whitespace(eligibility_gate['reason'])}",
        f"  Why: {compact_whitespace(debug_reason) or 'No debug reason provided'}",
    ]
    detail_lines = [
        (
            "  - "
            f"{row['requirement']} | {row['importance_label']} | {row['requirement_type_label']} | "
            f"{row['status_label']} | {row['mapping_label']} | Via: {row['match_source_label']} | "
            f"Term: {row['matched_profile_term_label']} | {row['calculation_label']} | "
            f"Evidence: {row['profile_support_label']}"
            + (
                f" | {row['experience_evidence_label']}"
                if compact_whitespace(str(row.get("experience_evidence_label") or ""))
                else ""
            )
        )
        for row in diagnostics["rows"]
    ]
    footer_lines = [
        (
            "  Final calculation: "
            f"{diagnostics['earned_weighted_credit']:g} ÷ "
            f"{diagnostics['total_requirement_weight']:g} × 100 = "
            f"{diagnostics['final_requirement_fit']}%"
        )
    ]
    return "\n".join(summary_lines + detail_lines + footer_lines)


def _requirement_fit_entries(record: dict, profile: dict, scoring_rules: dict) -> List[dict]:
    coverage = record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []
    if not isinstance(coverage, list) or not coverage:
        if record.get("review_source") == "llm" and record.get(RECORD_JOB_REQUIREMENTS_KEY):
            return [
                {
                    "label": "Requirement Fit: requirement coverage not returned",
                    "value": 0,
                    "section": "requirement_fit",
                }
            ]
        return [{"label": "Requirement Fit: no requirements to score", "value": 0, "section": "requirement_fit"}]

    importance_weights = _requirement_importance_weights(scoring_rules)
    capability_credits = _capability_level_credits(scoring_rules)
    status_weights = _requirement_status_weights(scoring_rules)
    capability_levels = _candidate_capability_level_lookup(profile, capability_credits)
    eligibility_levels = _candidate_eligibility_lookup(profile)
    total_weight = 0.0
    earned_weight = 0.0
    counts = {
        "strong": 0,
        "working": 0,
        "basic": 0,
        "low": 0,
        "eligibility": 0,
        "partial": 0,
        "not_shown": 0,
        "mismatch": 0,
        "unknown": 0,
    }
    mandatory_gaps: list[str] = []
    weak_mandatory: list[str] = []
    uncertain_count = 0

    for item in coverage:
        if not isinstance(item, dict):
            continue
        requirement = compact_whitespace(str(item.get("requirement") or ""))
        if not requirement:
            continue
        importance = str(item.get("importance") or "preferred").strip().lower()
        weight = importance_weights.get(importance, importance_weights["preferred"])
        status = str(item.get("status") or "").strip().lower()
        requirement_type = str(item.get("requirement_type") or "capability").strip().lower()
        scoring_weight = 0.0 if requirement_type == "eligibility" else weight
        total_weight += scoring_weight
        matched_candidate_fact = str(
            item.get("matched_candidate_fact")
            or item.get("profile_name")
            or item.get("capability_name")
            or item.get("eligibility_name")
            or ""
        ).strip()

        if status in {"not_shown", "not shown"}:
            counts["not_shown"] += 1
            if importance == "mandatory":
                mandatory_gaps.append(requirement)
            continue
        if status == "mismatch":
            counts["mismatch"] += 1
            if importance == "mandatory":
                mandatory_gaps.append(requirement)
            continue
        if status not in {"supported", "partially_supported"}:
            counts["unknown"] += 1
            uncertain_count += 1
            _append_requirement_mapping_uncertainty(
                record,
                item,
                "Requirement was not marked as supported or partially_supported, so scoring treated it as not covered and needs review.",
            )
            if importance == "mandatory":
                mandatory_gaps.append(requirement)
            continue
        if requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            counts["unknown"] += 1
            uncertain_count += 1
            _append_requirement_mapping_uncertainty(
                record,
                item,
                "Requirement was marked with an invalid requirement type and needs review before scoring can treat it as covered.",
            )
            if importance == "mandatory":
                mandatory_gaps.append(requirement)
            continue

        if requirement_type == "eligibility":
            eligibility_key = _normalise_lookup_text(matched_candidate_fact)
            if not matched_candidate_fact or eligibility_key not in eligibility_levels:
                counts["unknown"] += 1
                uncertain_count += 1
                _append_requirement_mapping_uncertainty(
                    record,
                    item,
                    "Requirement was marked as covered but the mapped candidate eligibility fact is missing or cannot be resolved.",
                )
                if importance == "mandatory":
                    mandatory_gaps.append(requirement)
                continue
            if not eligibility_levels.get(eligibility_key, False):
                counts["mismatch"] += 1
                if importance == "mandatory":
                    mandatory_gaps.append(requirement)
                continue
            counts["eligibility"] += 1
            continue

        capability_key = _normalise_lookup_text(matched_candidate_fact)
        level = capability_levels.get(capability_key)
        if not matched_candidate_fact or not level:
            counts["unknown"] += 1
            uncertain_count += 1
            _append_requirement_mapping_uncertainty(
                record,
                item,
                "Requirement was marked as covered but the mapped candidate capability is missing or cannot be resolved.",
            )
            if importance == "mandatory":
                mandatory_gaps.append(requirement)
            continue

        credit = capability_credits[level] * float(status_weights[status])
        earned_weight += weight * credit
        bucket = "low" if level in {"low", "limited_depth"} else level
        counts[bucket] += 1
        if status == "partially_supported":
            counts["partial"] += 1
        if importance == "mandatory" and level in {"basic", "low", "limited_depth"}:
            weak_mandatory.append(requirement)

    percent = round((earned_weight / total_weight) * 100) if total_weight > 0 else 0
    label_parts = [
        f"Requirement Fit: {percent}%",
        f"strong {counts['strong']}",
        f"working {counts['working']}",
        f"basic {counts['basic']}",
        f"low {counts['low']}",
        f"eligibility {counts['eligibility']}",
        f"partial {counts['partial']}",
        f"not shown {counts['not_shown']}",
        f"mismatch {counts['mismatch']}",
    ]
    if counts["unknown"]:
        label_parts.append(f"needs review {counts['unknown']}")

    entries = [{"label": " | ".join(label_parts), "value": int(percent), "section": "requirement_fit"}]
    for requirement in mandatory_gaps[:3]:
        entries.append(
            {
                "label": f"Mandatory gap: {requirement}",
                "value": 0,
                "section": "requirement_fit_warning",
            }
        )
    for requirement in weak_mandatory[:3]:
        entries.append(
            {
                "label": f"Mandatory weak coverage: {requirement}",
                "value": 0,
                "section": "requirement_fit_warning",
            }
        )
    if uncertain_count:
        entries.append(
            {
                "label": f"Requirement mapping needs review: {uncertain_count}",
                "value": 0,
                "section": "requirement_fit_warning",
            }
        )
    return entries


def llm_review_state(record: dict) -> dict:
    """Classify the LLM review state for a record.

    - evaluated: a grade is present
    - invalid: decision or grade is missing — scoring must not proceed
    """
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    decision = str(record.get("llm_decision") or "").strip().upper()
    if grade:
        return {"state": LLM_REVIEW_STATE_EVALUATED, "label": "", "detail": ""}
    detail = (
        "llm_decision is present but llm_fit_grade is missing."
        if decision
        else "Job has not been through LLM review, so scoring is blocked until the pipeline runs successfully."
    )
    return {
        "state": LLM_REVIEW_STATE_INVALID,
        "label": LLM_REVIEW_INCOMPLETE_LABEL,
        "detail": detail,
    }


def build_fit_highlights(
    record: dict, details_text: str, profile: Optional[dict] = None
) -> List[str]:
    highlights: List[str] = []
    active_profile = profile or load_profile()
    highlight_labels = load_ui_labels()["fit_highlight_labels"]
    # Workspace card highlight counts are global optimiser settings.
    hl_config = load_global_settings()[KEY_FIT_HIGHLIGHTS]
    role_bundle = role_text_bundle(record, details_text)
    capability_matches = find_profile_capability_matches(role_bundle, active_profile)

    matched_profile_areas = (
        [
            (True, area)
            for area in capability_matches[CapabilityLevel.STRONG][
                : hl_config["strong_capability_count"]
            ]
        ]
        + [
            (False, area)
            for area in capability_matches[CapabilityLevel.WORKING][
                : hl_config["working_capability_count"]
            ]
        ]
        + [
            (False, area)
            for area in capability_matches[CapabilityLevel.BASIC][
                : hl_config["basic_capability_count"]
            ]
        ]
    )
    cap_template = str(highlight_labels["capability_match_sentence"])
    capability_labels = dedupe_preserve_order(
        [
            label
            for label in (
                friendly_capability_label(area) for _strong, area in matched_profile_areas
            )
            if label
        ]
    )
    if capability_labels:
        entry = cap_template.format(capability=list_to_phrase(capability_labels))
        if entry:
            highlights.append(entry)

    highlights.extend(
        item
        for item in competitive_fit_highlights(record, active_profile)
        if not _is_location_fit_highlight(item)
    )
    return dedupe_preserve_order(highlights)[: hl_config["max_highlights"]]


def _is_location_fit_highlight(text: str) -> bool:
    cleaned = compact_whitespace(text).lower()
    return bool(
        cleaned
        and (
            "location" in cleaned
            or "onsite" in cleaned
            or "on-site" in cleaned
            or "travel" in cleaned
        )
    )


def occupation_alignment_diagnostics(record: dict, scoring_rules: dict) -> dict[str, Any]:
    """Shared occupation alignment diagnostics for logs and debug UI.

    occupation_alignment never blocks scoring: an unclassified or invalid value
    (missing, or outside LLM_ALLOWED_OCCUPATION_ALIGNMENTS) shows as "needs review"
    with a zero adjustment rather than raising, per the "do not reject on occupation
    alignment" rule.
    """
    adjustments = _occupation_alignment_adjustments(scoring_rules)
    alignment = str(record.get(RECORD_OCCUPATION_ALIGNMENT_KEY) or "").strip().lower()
    reason = compact_whitespace(record.get(RECORD_OCCUPATION_ALIGNMENT_REASON_KEY) or "")
    is_classified = alignment in LLM_ALLOWED_OCCUPATION_ALIGNMENTS
    return {
        "alignment": alignment if is_classified else "",
        "alignment_label": alignment.title() if is_classified else "Needs review (not classified)",
        "reason": reason or "No reason provided",
        "adjustment": int(adjustments[alignment]) if is_classified else 0,
        "is_classified": is_classified,
    }


def build_occupation_alignment_breakdown(record: dict, scoring_rules: dict) -> List[dict]:
    occupation = occupation_alignment_diagnostics(record, scoring_rules)
    return [
        {
            "label": f"Occupation alignment: {occupation['alignment_label']}",
            "value": occupation["adjustment"],
            "section": "occupation_alignment",
        }
    ]


def format_occupation_alignment_diagnostics_block(
    record: dict, final_score: int, profile: Optional[dict] = None
) -> str:
    """Format the occupation alignment classification, reason, adjustment, and final
    score calculation for logs and debug views."""

    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    occupation = occupation_alignment_diagnostics(record, scoring_rules)
    requirement_fit = requirement_fit_diagnostics(record, active_profile)["final_requirement_fit"]
    hard_block_penalty = int(scoring_rules["fit_breakdown"]["hard_block_penalty"]) * len(
        hard_block_reasons(record, active_profile)
    )
    calculation = f"{requirement_fit} + ({occupation['adjustment']:+d})"
    if hard_block_penalty:
        calculation += f" + ({hard_block_penalty:+d} hard blocker)"
    calculation += f" = {final_score} (clamped 0-100)"
    return "\n".join(
        [
            "  Occupation alignment",
            f"  Alignment: {occupation['alignment_label']}",
            f"  Reason: {occupation['reason']}",
            f"  Adjustment: {occupation['adjustment']:+d}",
            f"  Final calculation: {calculation}",
        ]
    )


def build_risk_breakdown(scoring_rules: dict, hard_block_labels: List[str]) -> List[dict]:
    return [
        {
            "label": f"Hard blocker requirement mismatch: {label}",
            "value": int(scoring_rules["fit_breakdown"]["hard_block_penalty"]),
            "section": "risk",
        }
        for label in hard_block_labels
    ]


def _clamp_score(score: int) -> int:
    return max(min(int(score), 100), 0)


def fit_score_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    review_state = llm_review_state(record)
    if review_state["state"] != LLM_REVIEW_STATE_EVALUATED:
        job_key = str(record.get("job_key") or "<unknown>")
        title = str(record.get("title") or "").strip() or "<untitled>"
        raise RuntimeError(
            f"[FIT_SCORE] Cannot score job without LLM review — {review_state['detail']}\n"
            f"  job: {job_key} ({title})\n"
            "  Re-run the pipeline to generate a review before scoring."
        )
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    entries = _requirement_fit_entries(record, active_profile, scoring_rules)
    hard_block_labels = hard_block_reasons(record, active_profile)
    return (
        entries
        + build_occupation_alignment_breakdown(record, scoring_rules)
        + build_risk_breakdown(scoring_rules, hard_block_labels)
    )


def has_hard_blockers(record: dict, profile: Optional[dict] = None) -> bool:
    active_profile = profile or load_profile()
    return bool(hard_block_reasons(record, active_profile))


def fit_score(record: dict, profile: Optional[dict] = None) -> int:
    score = sum(item["value"] for item in fit_score_breakdown(record, profile))
    return _clamp_score(score)


def fit_score_breakdown_frozen(record: dict, profile: Optional[dict] = None) -> List[dict]:
    """Frozen Requirement Fit % breakdown computed once at scrape time."""
    return fit_score_breakdown(record, profile)


def fit_score_and_breakdown_frozen(
    record: dict, profile: Optional[dict] = None
) -> tuple[int, List[dict]]:
    """Frozen score + breakdown computed together so callers storing both fields

    (score, breakdown) don't recompute — and re-log — the breakdown twice.
    """
    active_profile = profile or load_profile()
    breakdown = fit_score_breakdown_frozen(record, active_profile)
    return _clamp_score(sum(item["value"] for item in breakdown)), breakdown


def fit_score_frozen(record: dict, profile: Optional[dict] = None) -> int:
    """Frozen score — excludes freshness and viewed status. Stored on the record at scrape time."""
    score, _ = fit_score_and_breakdown_frozen(record, profile)
    return score


def fit_score_and_breakdown_displayed(
    record: dict, profile: Optional[dict] = None
) -> tuple[int, List[dict]]:
    """Displayed score and full breakdown: frozen base.

    Falls back to full live scoring for records that predate score freezing.
    """
    if RECORD_FIT_SCORE_KEY not in record:
        breakdown = fit_score_breakdown(record, profile)
        return _clamp_score(sum(e["value"] for e in breakdown)), breakdown
    frozen_score = int(record[RECORD_FIT_SCORE_KEY])
    frozen_breakdown = list(record.get(RECORD_FIT_SCORE_BREAKDOWN_KEY) or [])
    return _clamp_score(frozen_score), frozen_breakdown

def fit_score_displayed(record: dict, profile: Optional[dict] = None) -> int:
    """Displayed score for filtering and sorting: frozen base only."""
    return fit_score_and_breakdown_displayed(record, profile)[0]
