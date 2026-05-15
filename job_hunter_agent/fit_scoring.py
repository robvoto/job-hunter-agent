from typing import Dict, List, Optional

from job_hunter_agent.capability_matching import (
    evidence_tier_alignment_score,
    find_profile_capability_matches,
    reviewed_signal_match_summary,
    reviewed_signal_matches_for_text,
)
from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.description_trust import full_description_confidence, get_trusted_full_description
from job_hunter_agent.filters import analyze_title_filters
from job_hunter_agent.history import viewed_by_user
from job_hunter_agent.posting_utils import current_posted_age_days
from job_hunter_agent.preferences import (
    assess_contract_preference,
    assess_government_preference,
    assess_location_preference,
    salary_fit_adjustment,
)
from job_hunter_agent.advance_settings import KEY_FIT_HIGHLIGHTS, load_advance_settings
from job_hunter_agent.profile_store import (
    KEY_CAPABILITY_EVIDENCE,
    KEY_CAPABILITY_LEVEL_WEIGHTS,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_CONVERGENCE,
    KEY_CONVERGENCE_BONUS_NO_SOFT_RISKS,
    KEY_CONVERGENCE_BONUS_WITH_SOFT_RISKS,
    KEY_CONVERGENCE_ELIGIBLE_GRADES,
    KEY_CONVERGENCE_LABEL,
    KEY_CONVERGENCE_MIN_POSITIVE_MATCHES,
    KEY_CONVERGENCE_REQUIRED_CONTENT_REASON,
    KEY_CONVERGENCE_REQUIRED_FIT_CONFIDENCE,
    KEY_CONVERGENCE_REQUIRED_TITLE_REASON,
    KEY_LLM_GRADE_POINTS,
    KEY_MAX_SCORE,
    LEVEL_BASIC,
    LEVEL_STRONG,
    LEVEL_WORKING,
    VALID_CAPABILITY_MATCH_LEVELS,
    get_preference_weights,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.role_analysis import (
    friendly_capability_label,
    role_text_bundle,
    text_contains_term,
)
from job_hunter_agent.scoring_utils import (
    build_scoring_source_text,
    weighted_points,
)
from job_hunter_agent.signal_detection import (
    _capability_rule_strength,
    competitive_fit_highlights,
    competitive_signal_assessments,
    hard_block_reasons,
)
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.signal_schema import SIGNAL_LABEL_KEY, TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order


def llm_description_fit_entry(record: dict, profile: Optional[dict] = None) -> dict:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    if not grade:
        raise ValueError("llm_fit_grade is required for score breakdown")
    grade_points = scoring_rules[KEY_LLM_GRADE_POINTS]
    if grade not in grade_points:
        raise ValueError(f"Unsupported llm_fit_grade: {grade}")
    labels = load_ui_labels()["grade_labels"]
    if grade not in labels:
        raise ValueError(f"Missing grade label for llm_fit_grade: {grade}")
    label = labels[grade]
    value = int(grade_points[grade])
    return {"label": label, "value": value}


def capability_match_summary(record: dict, profile: Optional[dict] = None) -> Dict[str, List[str]]:
    active_profile = profile or load_profile()
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    return find_profile_capability_matches(source_text, active_profile)


def capability_scored_matches(source_text: str, profile: dict) -> list[dict]:
    lowered = compact_whitespace(source_text).lower()
    results = []
    for rule in profile.get(KEY_CAPABILITY_PROFILE_RULES, []):
        if not isinstance(rule, dict):
            continue
        level = str(rule.get("level") or "").strip().lower()
        if level not in VALID_CAPABILITY_MATCH_LEVELS:
            continue
        canonical = canonical_capability_term(rule)
        if not canonical or not text_contains_term(lowered, canonical):
            continue
        rule_strength = _capability_rule_strength(rule)
        profile_evidence = evidence_tier_alignment_score(profile, [canonical])
        combined = max(rule_strength, profile_evidence)
        results.append({
            "label": friendly_capability_label(str(rule.get("name") or "")),
            "level": level,
            "combined_strength": combined,
        })
    return results


def capability_evidence_score(record: dict, profile: Optional[dict] = None) -> tuple[int, dict]:
    active_profile = profile or load_profile()
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    scoring_rules = get_scoring_rules(active_profile)
    level_weights = scoring_rules[KEY_CAPABILITY_LEVEL_WEIGHTS]
    max_score = int(scoring_rules[KEY_CAPABILITY_EVIDENCE][KEY_MAX_SCORE])
    scored = capability_scored_matches(source_text, active_profile)
    total = sum(
        m["combined_strength"] * int(level_weights[str(m.get("level") or "")])
        for m in scored
    )
    score = min(round(total), max_score)
    matches = capability_match_summary(record, active_profile)
    return score, matches


def convergence_bonus_entry(record: dict, capability_matches: Optional[dict] = None, profile: Optional[dict] = None) -> Optional[dict]:
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
    matches = capability_matches or capability_match_summary(record, active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    convergence_rules = scoring_rules[KEY_CONVERGENCE]
    positive_count = (
        len(matches.get(LEVEL_STRONG, []))
        + len(matches.get(LEVEL_WORKING, []))
        + len(matches.get(LEVEL_BASIC, []))
    )
    if (
        title_reason != convergence_rules[KEY_CONVERGENCE_REQUIRED_TITLE_REASON]
        or content_reason != convergence_rules[KEY_CONVERGENCE_REQUIRED_CONTENT_REASON]
        or fit_confidence != convergence_rules[KEY_CONVERGENCE_REQUIRED_FIT_CONFIDENCE]
    ):
        return None
    if missing_evidence or grade not in set(convergence_rules[KEY_CONVERGENCE_ELIGIBLE_GRADES]):
        return None
    if positive_count < int(convergence_rules[KEY_CONVERGENCE_MIN_POSITIVE_MATCHES]):
        return None
    bonus = int(convergence_rules[KEY_CONVERGENCE_BONUS_NO_SOFT_RISKS] if not soft_risks else convergence_rules[KEY_CONVERGENCE_BONUS_WITH_SOFT_RISKS])
    return {"label": convergence_rules[KEY_CONVERGENCE_LABEL], "value": bonus}


def build_fit_highlights(record: dict, details_text: str, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = []
    active_profile = profile or load_profile()
    highlight_labels = load_ui_labels()["fit_highlight_labels"]
    # Workspace card highlight counts are global optimiser settings.
    hl_config = load_advance_settings()[KEY_FIT_HIGHLIGHTS]
    role_bundle = role_text_bundle(record, details_text)
    capability_matches = find_profile_capability_matches(role_bundle, active_profile)

    matched_profile_areas = (
        [(highlight_labels["strong_capability_match"], area) for area in capability_matches[LEVEL_STRONG][:hl_config["strong_capability_count"]]]
        + [(highlight_labels["capability_match"], area) for area in capability_matches[LEVEL_WORKING][:hl_config["working_capability_count"]]]
        + [(highlight_labels["capability_match"], area) for area in capability_matches[LEVEL_BASIC][:hl_config["basic_capability_count"]]]
    )
    for prefix, area in matched_profile_areas:
        label = friendly_capability_label(area)
        entry = f"{prefix}: {label}" if label else ""
        if entry and entry not in highlights:
            highlights.append(entry)

    reviewed = reviewed_signal_match_summary(
        {**record, "reviewed_signal_matches": record.get("reviewed_signal_matches") or reviewed_signal_matches_for_text(role_bundle)}
    )
    for signal in reviewed["matched"][:hl_config["reviewed_signal_count"]]:
        label = friendly_capability_label(signal)
        entry = f"{highlight_labels['matched_signal']}: {label}" if label else ""
        if entry and entry not in highlights:
            highlights.append(entry)

    govt_signal = assess_government_preference(record, active_profile)
    if govt_signal and int(govt_signal.get("value", 0) or 0) > 0:
        highlights.append(govt_signal["label"])

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
    evidence_score: int,
    capability_matches: dict,
    title_family: str,
    title_seniority_adjustment: int,
    title_reason: str,
    content_reason: str,
    active_profile: dict,
) -> List[dict]:
    entries: List[dict] = []
    if title_family == "primary" or (not title_family and title_reason == "OK"):
        entries.append({
            "label": "Primary role-family match",
            "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_direct"]), weights["fit"]),
        })
        if title_seniority_adjustment:
            entries.append({
                "label": "Primary seniority adjustment",
                "value": weighted_points(int(title_seniority_adjustment), weights["fit"]),
            })
    elif title_family == "secondary" or (not title_family and title_reason == TITLE_REASON_POTENTIAL_MATCH):
        entries.append({
            "label": "Secondary role-family match",
            "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_secondary"]), weights["fit"]),
        })
    llm_entry = llm_description_fit_entry(record, active_profile)
    entries.append({"label": llm_entry["label"], "value": weighted_points(int(llm_entry["value"]), weights["fit"])})
    if content_reason == "OK":
        entries.append({"label": "Passed content filters", "value": weighted_points(int(scoring_rules["fit_breakdown"]["content_ok"]), weights["fit"])})
    if full_description_confidence(record) == "LOW":
        entries.append({"label": "Description capture incomplete", "value": weighted_points(int(scoring_rules["fit_breakdown"]["description_capture_incomplete"]), weights["fit"])})
    if evidence_score:
        entries.append({"label": "Fit evidence bullets", "value": weighted_points(evidence_score, weights["fit"])})
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
    government_item = assess_government_preference(record, active_profile)
    if government_item:
        entries.append({
            "label": government_item["label"],
            "value": weighted_points(int(government_item["value"]), weights["government"]),
        })
    work_mode = str(record.get("work_mode") or "").lower()
    if work_mode == "hybrid":
        entries.append({"label": "Hybrid work available", "value": weighted_points(int(scoring_rules["work_mode"]["hybrid"]), weights["work_mode"])})
    elif work_mode == "remote":
        entries.append({"label": "Remote work available", "value": weighted_points(int(scoring_rules["work_mode"]["remote"]), weights["work_mode"])})
    elif work_mode in {"on-site", "onsite", "on site"}:
        entries.append({"label": "On-site role", "value": weighted_points(int(scoring_rules["work_mode"]["on_site"]), weights["work_mode"])})
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
        bucket = buckets.get(bucket_key)
        if not isinstance(bucket, dict):
            raise ValueError(f"Invalid freshness bucket: {bucket_key}")
        if posted_age_days <= float(bucket["max_days"]):
            entries.append({
                "label": str(bucket["label"]),
                "value": weighted_points(int(freshness_rules[bucket_key]), weights["freshness"]),
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
    title_reason = str(record.get("title_reason") or "")
    content_reason = str(record.get("content_reason") or "")
    title_metadata = record.get("title_match_metadata") if isinstance(record.get("title_match_metadata"), dict) else {}
    posted_age_days = current_posted_age_days(record)
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    evidence_score, capability_matches = capability_evidence_score(record, active_profile)
    if not title_metadata and str(record.get("title") or "").strip():
        title_metadata = analyze_title_filters(str(record.get("title") or ""), active_profile)
    title_family = str(title_metadata.get("match_family") or "").strip().lower()
    title_seniority_adjustment = int(title_metadata.get("seniority_adjustment") or 0)

    return (
        build_core_fit_breakdown(record, scoring_rules, weights, evidence_score, capability_matches, title_family, title_seniority_adjustment, title_reason, content_reason, active_profile)
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
