"""Helpers for fit scoring."""

import logging
from typing import Dict, List, Optional

from job_hunter_agent.capability_matching import (
    evidence_tier_alignment_score,
    find_profile_capability_matches,
)

logger = logging.getLogger(__name__)
from job_hunter_agent.description_trust import full_description_confidence
from job_hunter_agent.filters import analyze_title_filters
from job_hunter_agent.history import viewed_by_user
from job_hunter_agent.posting_utils import current_posted_age_days
from job_hunter_agent.preferences import (
    assess_contract_preference,
    assess_location_preference,
    assess_work_mode_preference,
    salary_fit_adjustment,
)
from job_hunter_agent.global_settings import KEY_FIT_HIGHLIGHTS, load_global_settings
from job_hunter_agent.profile_store import (
    KEY_CAPABILITY_CONTEXTUAL_LLM,
    KEY_CAPABILITY_EVIDENCE,
    KEY_CAPABILITY_LEVEL_WEIGHTS,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CONVERGENCE,
    KEY_LLM_GRADE_POINTS,
    CapabilityLevel,
    VALID_CAPABILITY_RULE_LEVELS,
    get_preference_weights,
    get_scoring_rules,
    load_profile,
)


from job_hunter_agent.role_analysis import (
    friendly_capability_label,
    role_text_bundle,
)
from job_hunter_agent.scoring_utils import weighted_points
from job_hunter_agent.signal_detection import (
    _capability_rule_strength,
    competitive_fit_highlights,
    competitive_signal_assessments,
    hard_block_reasons,
)
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.signal_schema import SIGNAL_LABEL_KEY, TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order

LLM_REVIEW_STATE_EVALUATED = "evaluated"
LLM_REVIEW_STATE_INVALID = "invalid"
LLM_REVIEW_INCOMPLETE_LABEL = "LLM review incomplete"


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
        else "Job has not been through LLM review — re-run the pipeline."
    )
    return {
        "state": LLM_REVIEW_STATE_INVALID,
        "label": LLM_REVIEW_INCOMPLETE_LABEL,
        "detail": detail,
    }


def llm_description_fit_entry(record: dict, profile: Optional[dict] = None) -> dict:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    if not grade:
        raise ValueError("llm_fit_grade is required for evaluated records")
    grade_points = scoring_rules[KEY_LLM_GRADE_POINTS]
    if grade not in grade_points:
        raise ValueError(f"Unsupported llm_fit_grade: {grade}")
    labels = load_ui_labels()["grade_labels"]
    if grade not in labels:
        raise ValueError(f"Missing grade label for llm_fit_grade: {grade}")
    label = labels[grade]
    value = int(grade_points[grade])
    return {"label": label, "value": value}


def capability_evidence_score(record: dict, profile: Optional[dict] = None) -> tuple[int, list[dict]]:
    """Score capability matches from LLM-confirmed contextual_capability_matches only.

    Each entry must name an exact capability group from the profile. Anything that slips
    past the LLM gate validation is logged as an error and skipped — it is never silently credited.
    """
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    level_weights = scoring_rules[KEY_CAPABILITY_LEVEL_WEIGHTS]
    max_score = int(scoring_rules[KEY_CAPABILITY_EVIDENCE]["max_score"])
    contextual_config = scoring_rules.get(KEY_CAPABILITY_CONTEXTUAL_LLM, {})
    levels_with_credit = set(contextual_config.get("confidence_levels_with_credit") or [])
    if not levels_with_credit:
        raise ValueError(
            f"scoring_rules[{KEY_CAPABILITY_CONTEXTUAL_LLM!r}]['confidence_levels_with_credit'] is empty — "
            "update scoring_rules.json before scoring"
        )

    profile_rules_by_name = {
        str(r.get("name") or "").strip().lower(): r
        for r in active_profile.get(KEY_CANDIDATE_CAPABILITIES, [])
        if isinstance(r, dict) and str(r.get("name") or "").strip()
    }

    scored: list[dict] = []
    credited_names: set[str] = set()

    for match in (record.get("contextual_capability_matches") or []):
        cap_name = str(match.get("capability_name") or "").strip().lower()
        confidence = str(match.get("confidence") or "").strip().lower()
        matched_text = str(match.get("matched_text") or "").strip()
        reason = str(match.get("reason") or "").strip()

        if cap_name in credited_names:
            continue

        rule = profile_rules_by_name.get(cap_name)
        if rule is None:
            logger.error(
                "[CAPABILITY_SCORING][GATE_BREACH] LLM returned a capability name not in the profile — "
                "valid_capability_names enforcement failed.\n"
                "  job        : %s (%s)\n"
                "  capability : %r\n"
                "  confidence : %s\n"
                "  matched_text: %s\n"
                "  known names: %s",
                record.get("job_key", "<unknown>"),
                str(record.get("title") or "").strip(),
                cap_name,
                confidence,
                matched_text or "(none)",
                ", ".join(sorted(profile_rules_by_name.keys())),
            )
            continue

        level = str(rule.get("level") or "").strip().lower()
        if level not in VALID_CAPABILITY_RULE_LEVELS:
            logger.error(
                "[CAPABILITY_SCORING][INVALID_LEVEL] capability=%r level=%r job=%s — fix the profile rule",
                cap_name, level, record.get("job_key", "<unknown>"),
            )
            continue

        if confidence not in levels_with_credit:
            logger.info(
                "[CAPABILITY_SCORING][BELOW_THRESHOLD] capability=%r confidence=%r matched_text=%r reason=%r job=%s",
                cap_name, confidence, matched_text, reason, record.get("job_key", "<unknown>"),
            )
            continue

        rule_strength = _capability_rule_strength(rule)
        profile_evidence = evidence_tier_alignment_score(active_profile, [cap_name])
        combined = max(rule_strength, profile_evidence)
        scored.append({
            "name": str(rule.get("name") or ""),
            "label": friendly_capability_label(str(rule.get("name") or "")),
            "level": level,
            "combined_strength": combined,
            "match_type": "llm_confirmed",
            "matched_text": matched_text,
        })
        credited_names.add(cap_name)

    scored.sort(key=lambda m: int(level_weights.get(m["level"], 0)), reverse=True)

    total = 0
    credited: list[dict] = []
    for m in scored:
        weight = int(level_weights.get(m["level"], 0))
        points = round(m["combined_strength"] * weight)
        remaining = max_score - total
        if remaining <= 0:
            break
        points = min(points, remaining)
        if points <= 0:
            continue
        total += points
        credited.append({**m, "points": points})

    return total, credited


def convergence_bonus_entry(record: dict, capability_matches: dict, profile: Optional[dict] = None) -> Optional[dict]:
    """Award a bonus when multiple strong independent signals simultaneously confirm fit.

    Conditions and bonus values come from scoring_rules.json so they stay managed
    rather than hidden in feature code.
    """
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    title_reason = str(record.get("title_reason") or "").strip().upper()
    content_reason = str(record.get("content_reason") or "").strip().upper()
    fit_confidence = full_description_confidence(record)
    missing_evidence = [item for item in (record.get("missing_evidence") or []) if compact_whitespace(item)]
    soft_risks = [item for item in (record.get("soft_risk_reasons") or []) if compact_whitespace(item)]
    active_profile = profile or load_profile()
    matches = capability_matches
    scoring_rules = get_scoring_rules(active_profile)
    convergence_rules = scoring_rules[KEY_CONVERGENCE]
    positive_count = (
        len(matches.get(CapabilityLevel.STRONG, []))
        + len(matches.get(CapabilityLevel.WORKING, []))
        + len(matches.get(CapabilityLevel.BASIC, []))
    )
    if (
        title_reason != convergence_rules["required_title_reason"]
        or content_reason != convergence_rules["required_content_reason"]
        or fit_confidence != convergence_rules["required_fit_confidence"]
    ):
        return None
    if missing_evidence or grade not in set(convergence_rules["eligible_grades"]):
        return None
    if positive_count < int(convergence_rules["min_positive_matches"]):
        return None
    bonus = int(convergence_rules["bonus_no_soft_risks"] if not soft_risks else convergence_rules["bonus_with_soft_risks"])
    return {"label": convergence_rules["label"], "value": bonus}


def build_fit_highlights(record: dict, details_text: str, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = []
    active_profile = profile or load_profile()
    highlight_labels = load_ui_labels()["fit_highlight_labels"]
    # Workspace card highlight counts are global optimiser settings.
    hl_config = load_global_settings()[KEY_FIT_HIGHLIGHTS]
    role_bundle = role_text_bundle(record, details_text)
    capability_matches = find_profile_capability_matches(role_bundle, active_profile)

    matched_profile_areas = (
        [(highlight_labels["strong_capability_match"], area) for area in capability_matches[CapabilityLevel.STRONG][:hl_config["strong_capability_count"]]]
        + [(highlight_labels["capability_match"], area) for area in capability_matches[CapabilityLevel.WORKING][:hl_config["working_capability_count"]]]
        + [(highlight_labels["capability_match"], area) for area in capability_matches[CapabilityLevel.BASIC][:hl_config["basic_capability_count"]]]
    )
    for prefix, area in matched_profile_areas:
        label = friendly_capability_label(area)
        entry = f"{prefix}: {label}" if label else ""
        if entry and entry not in highlights:
            highlights.append(entry)

    contract_signal = assess_contract_preference(record, active_profile)
    if contract_signal and int(contract_signal.get("value", 0) or 0) > 0:
        highlights.append(contract_signal["label"])

    location_signal = assess_location_preference(record, active_profile)
    if location_signal and int(location_signal.get("value", 0) or 0) > 0:
        label = location_signal["label"]
        if not label:
            raise ValueError(f"assess_location_preference returned signal with empty label: {location_signal!r}")
        highlights.append(label)

    highlights.extend(competitive_fit_highlights(record, active_profile))
    return dedupe_preserve_order(highlights)[:hl_config["max_highlights"]]


def competitive_signal_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    hl_labels = load_ui_labels()["fit_highlight_labels"]
    entries: List[dict] = []
    for signal in competitive_signal_assessments(record, profile):
        adjustment = int(signal.get("adjustment", 0) or 0)
        if adjustment == 0:
            continue
        prefix = hl_labels["competitive_signal_aligns"] if adjustment > 0 else hl_labels["competitive_signal_elsewhere"]
        entries.append({"label": f"{prefix}: {signal[SIGNAL_LABEL_KEY]}", "value": adjustment})
    entries.sort(key=lambda item: (abs(int(item.get("value", 0))), item.get("label", "")), reverse=True)
    return entries[:2]


def build_core_fit_breakdown(
    record: dict,
    scoring_rules: dict,
    weights: dict,
    scored_matches: list[dict],
    title_family: str,
    title_reason: str,
    content_reason: str,
    active_profile: dict,
) -> List[dict]:
    title_match_labels = load_ui_labels().get("title_match_labels", {})
    entries: List[dict] = []
    if title_family == "primary" or (not title_family and title_reason == "OK"):
        entries.append({
            "label": title_match_labels["primary_match"],
            "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_direct"]), weights["fit"]),
        })
    elif title_family == "secondary" or (not title_family and title_reason == TITLE_REASON_POTENTIAL_MATCH):
        entries.append({
            "label": title_match_labels["secondary_match"],
            "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_secondary"]), weights["fit"]),
        })
    llm_entry = llm_description_fit_entry(record, active_profile)
    entries.append({"label": llm_entry["label"], "value": weighted_points(int(llm_entry["value"]), weights["fit"])})
    if content_reason == "OK":
        entries.append({"label": "Passed content filters", "value": weighted_points(int(scoring_rules["fit_breakdown"]["content_ok"]), weights["fit"])})
    if full_description_confidence(record) == "LOW":
        entries.append({"label": "Description capture incomplete", "value": weighted_points(int(scoring_rules["fit_breakdown"]["description_capture_incomplete"]), weights["fit"])})
    for m in scored_matches:
        points = int(m.get("points") or 0)
        if not points:
            continue
        match_type = m.get("match_type") or "canonical"
        label_tag = f"[{match_type}]" if match_type != "alias" else f"[alias: {m.get('matched_text') or ''}]"
        entries.append({
            "label": f"{m['label']} {label_tag}",
            "value": weighted_points(points, weights["fit"]),
        })
    capability_matches = {}
    for m in scored_matches:
        capability_matches.setdefault(m["level"], [])
        capability_matches[m["level"]].append(m["name"])
    convergence_entry = convergence_bonus_entry(record, capability_matches, active_profile)
    if convergence_entry:
        entries.append({
            "label": convergence_entry["label"],
            "value": weighted_points(int(convergence_entry["value"]), weights["fit"]),
        })
    for item in competitive_signal_breakdown(record, active_profile):
        entries.append({"label": item["label"], "value": weighted_points(int(item["value"]), weights["fit"])})
    return entries


def build_preference_breakdown(record: dict, scoring_rules: dict, weights: dict, active_profile: dict) -> List[dict]:
    entries: List[dict] = []
    location_item = assess_location_preference(record, active_profile)
    if location_item:
        entries.append({
            "label": location_item["label"],
            "value": weighted_points(int(location_item["value"]), weights["location"]),
        })
    contract_item = assess_contract_preference(record, active_profile)
    if contract_item:
        entries.append({
            "label": contract_item["label"],
            "value": weighted_points(int(contract_item["value"]), weights["contract"]),
        })
    work_mode_item = assess_work_mode_preference(record, active_profile)
    if work_mode_item:
        entries.append({
            "label": work_mode_item["label"],
            "value": weighted_points(int(work_mode_item["value"]), weights["work_mode"]),
        })
    salary_score = weighted_points(salary_fit_adjustment(record, active_profile), weights["salary"])
    if salary_score > 0:
        entries.append({"label": "Salary/rate signal", "value": salary_score})
    elif salary_score < 0:
        entries.append({"label": "Salary/rate below target", "value": salary_score})
    return entries


def build_freshness_breakdown(scoring_rules: dict, weights: dict, posted_age_days: Optional[float]) -> List[dict]:
    entries: List[dict] = []
    if posted_age_days is None:
        return entries

    freshness_rules = scoring_rules["freshness"]
    buckets = freshness_rules["buckets"]
    bucket_order = freshness_rules["bucket_order"]
    if not isinstance(buckets, dict) or not buckets or not isinstance(bucket_order, list) or not bucket_order:
        raise ValueError("freshness buckets are required in scoring_rules")

    for bucket_key in bucket_order:
        lookup_key = bucket_key.lower()
        bucket = buckets.get(lookup_key)
        if not isinstance(bucket, dict):
            raise ValueError(f"Invalid freshness bucket: {bucket_key}")
        if posted_age_days <= float(bucket["max_days"]):
            entries.append({
                "label": str(bucket["label"]),
                "value": weighted_points(int(freshness_rules[lookup_key]), weights["freshness"]),
            })
            break
    return entries


def build_convenience_breakdown(record: dict, scoring_rules: dict, weights: dict, posted_age_days: Optional[float]) -> List[dict]:
    entries: List[dict] = []
    entries.extend(build_freshness_breakdown(scoring_rules, weights, posted_age_days))
    if viewed_by_user(record) and not record.get("applied"):
        entries.append({"label": "Already viewed by you", "value": int(scoring_rules["fit_breakdown"]["viewed_by_user"])})
    return entries


def build_risk_breakdown(scoring_rules: dict, hard_block_labels: List[str]) -> List[dict]:
    return [
        {"label": f"Hard blocker requirement mismatch: {label}", "value": int(scoring_rules["fit_breakdown"]["hard_block_penalty"])}
        for label in hard_block_labels
    ]


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
    title_reason = str(record.get("title_reason") or "")
    content_reason = str(record.get("content_reason") or "")
    title_metadata = record.get("title_match_metadata") if isinstance(record.get("title_match_metadata"), dict) else {}
    posted_age_days = current_posted_age_days(record)
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    _evidence_score, scored_matches = capability_evidence_score(record, active_profile)
    if not title_metadata and str(record.get("title") or "").strip():
        title_metadata = analyze_title_filters(str(record.get("title") or ""), active_profile)
    title_family = str(title_metadata.get("match_family") or "").strip().lower()

    return (
        build_core_fit_breakdown(record, scoring_rules, weights, scored_matches, title_family, title_reason, content_reason, active_profile)
        + build_preference_breakdown(record, scoring_rules, weights, active_profile)
        + build_convenience_breakdown(record, scoring_rules, weights, posted_age_days)
        + build_risk_breakdown(scoring_rules, hard_block_labels)
    )


def has_hard_blockers(record: dict, profile: Optional[dict] = None) -> bool:
    active_profile = profile or load_profile()
    return bool(hard_block_reasons(record, active_profile))


def fit_score(record: dict, profile: Optional[dict] = None) -> int:
    score = sum(item["value"] for item in fit_score_breakdown(record, profile))
    return max(min(score, 100), 0)
