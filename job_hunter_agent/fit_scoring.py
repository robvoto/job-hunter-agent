"""Fit scoring helpers.

Purpose: score covered requirements and render explainable fit breakdowns.
"""

import json
import logging
from typing import List, Optional

from job_hunter_agent.capability_matching import (
    find_profile_capability_matches,
)

logger = logging.getLogger(__name__)
from job_hunter_agent.global_settings import KEY_FIT_HIGHLIGHTS, load_global_settings
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.paths import UNCERTAINTY_LOG_PATH
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
)
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CAPABILITY_LEVEL_WEIGHTS,
    KEY_REQUIREMENT_IMPORTANCE_WEIGHTS,
    CapabilityLevel,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.record_schema import (
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
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
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order

LLM_REVIEW_STATE_EVALUATED = "evaluated"
LLM_REVIEW_STATE_INVALID = "invalid"
LLM_REVIEW_INCOMPLETE_LABEL = "LLM review incomplete"


REQUIREMENT_MAPPING_UNCERTAIN_REASON = "requirement_capability_mapping_uncertain"


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
    for item in profile.get(KEY_CANDIDATE_ELIGIBILITY, []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        key = _normalise_lookup_text(name)
        if not key:
            continue
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


def requirement_fit_audit_rows(record: dict, profile: Optional[dict] = None) -> List[dict]:
    """Return the exact per-requirement inputs and credit used by fit scoring."""

    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    importance_weights = _requirement_importance_weights(scoring_rules)
    capability_credits = _capability_level_credits(scoring_rules)
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
        profile_name = str(item.get("profile_name") or "").strip()
        weight = importance_weights[importance]
        candidate_level = ""
        credit_fraction = 0.0

        if status in {"supported", "partially_supported"}:
            if requirement_type == "eligibility":
                eligibility_key = _normalise_lookup_text(profile_name)
                if eligibility_key in eligibility_levels and eligibility_levels[eligibility_key]:
                    candidate_level = "confirmed"
                    credit_fraction = 1.0
            elif requirement_type in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
                capability_key = _normalise_lookup_text(profile_name)
                candidate_level = capability_levels.get(capability_key, "")
                if candidate_level:
                    credit_fraction = capability_credits[candidate_level]

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
                "profile_name": profile_name,
                "candidate_level": candidate_level,
                "matched_job_text": compact_whitespace(str(item.get("matched_job_text") or "")),
                "profile_support": profile_support,
                "requirement_weight": weight,
                "credit_fraction": credit_fraction,
                "weighted_credit": weight * credit_fraction,
            }
        )
    return rows


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
        total_weight += weight
        status = str(item.get("status") or "").strip().lower()
        requirement_type = str(item.get("requirement_type") or "capability").strip().lower()
        profile_name = str(
            item.get("profile_name") or item.get("capability_name") or item.get("eligibility_name") or ""
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
            eligibility_key = _normalise_lookup_text(profile_name)
            if not profile_name or eligibility_key not in eligibility_levels:
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
            earned_weight += weight
            counts["eligibility"] += 1
            continue

        capability_key = _normalise_lookup_text(profile_name)
        level = capability_levels.get(capability_key)
        if not profile_name or not level:
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

        credit = capability_credits[level]
        earned_weight += weight * credit
        bucket = "low" if level in {"low", "limited_depth"} else level
        counts[bucket] += 1
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
    cap_template = str(highlight_labels.get("capability_match_sentence") or "").strip()
    if "{capability}" not in cap_template or "show" not in cap_template.lower():
        cap_template = "The ad asks for {capability}, and your profile shows this experience."
    for _strong, area in matched_profile_areas:
        label = friendly_capability_label(area)
        if not label:
            continue
        entry = cap_template.format(capability=label)
        if entry and entry not in highlights:
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
    return entries + build_risk_breakdown(scoring_rules, hard_block_labels)


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
