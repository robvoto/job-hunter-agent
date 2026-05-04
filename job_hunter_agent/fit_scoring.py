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
from job_hunter_agent.profile_store import (
    get_preference_weights,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.role_analysis import (
    friendly_capability_label,
    has_government_context,
    role_text_bundle,
    text_contains_term,
)
from job_hunter_agent.scoring_utils import (
    build_scoring_source_text,
    extract_contract_months,
    weighted_points,
)
from job_hunter_agent.signal_detection import (
    _capability_rule_strength,
    competitive_fit_highlights,
    competitive_signal_assessments,
    hard_block_reasons,
)
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order


def llm_description_fit_entry(record: dict, profile: Optional[dict] = None) -> dict:
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    decision = str(record.get("llm_decision") or "").strip().upper()
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    if not grade:
        fallback_map = {
            "KEEP": "STRONG",
            "MAYBE": "SOLID",
            "REJECT": "MISMATCH",
        }
        grade = fallback_map.get(decision, "SOLID")

    grade_map = {
        "EXCELLENT": ("Description fit is excellent", int(scoring_rules["llm_grade_points"]["EXCELLENT"])),
        "STRONG": ("Description fit is strong", int(scoring_rules["llm_grade_points"]["STRONG"])),
        "SOLID": ("Description fit is solid", int(scoring_rules["llm_grade_points"]["SOLID"])),
        "WEAK": ("Description fit is mixed", int(scoring_rules["llm_grade_points"]["WEAK"])),
        "POOR": ("Description fit is weak", int(scoring_rules["llm_grade_points"]["POOR"])),
        "MISMATCH": ("Description fit is a mismatch", int(scoring_rules["llm_grade_points"]["MISMATCH"])),
    }
    label, value = grade_map.get(grade, grade_map["SOLID"])
    return {"label": label, "value": value}


def capability_match_summary(record: dict, profile: Optional[dict] = None) -> Dict[str, List[str]]:
    active_profile = profile or load_profile()
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    return find_profile_capability_matches(source_text, active_profile)


def capability_scored_matches(source_text: str, profile: dict) -> list[dict]:
    lowered = compact_whitespace(source_text).lower()
    results = []
    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        level = str(rule.get("level") or "").strip().lower()
        if level not in {"strong", "working", "basic"}:
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
    scored = capability_scored_matches(source_text, active_profile)
    total = sum(
        m["combined_strength"] * {"strong": 4, "working": 3, "basic": 2}.get(str(m.get("level") or ""), 0)
        for m in scored
    )
    score = min(round(total), 20)
    matches = capability_match_summary(record, active_profile)
    return score, matches


def convergence_bonus_entry(record: dict, capability_matches: Optional[dict] = None, profile: Optional[dict] = None) -> Optional[dict]:
    """Award a bonus when multiple strong independent signals simultaneously confirm fit.

    Conditions: title OK, content OK, HIGH description confidence, LLM grade
    EXCELLENT or STRONG, 2+ positive capability matches, no missing evidence.
    Soft risks reduce the bonus from 5 to 3 but do not eliminate it.
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
    convergence_rules = scoring_rules["convergence"]
    positive_count = (
        len(matches.get("strong", []))
        + len(matches.get("working", []))
        + len(matches.get("basic", []))
    )

    if title_reason != "OK" or content_reason != "OK" or fit_confidence != "HIGH":
        return None
    if missing_evidence or grade not in set(convergence_rules.get("eligible_grades", [])):
        return None
    if positive_count < int(convergence_rules.get("min_positive_matches", 2) or 2):
        return None
    bonus = (
        int(convergence_rules.get("bonus_no_soft_risks", 5) or 5)
        if not soft_risks
        else int(convergence_rules.get("bonus_with_soft_risks", 3) or 3)
    )
    return {"label": "Multiple strong signals align", "value": bonus}


def build_fit_highlights(record: dict, details_text: str, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = []
    active_profile = profile or load_profile()
    role_bundle = role_text_bundle(record, details_text)
    lowered = role_bundle.lower()
    capability_matches = find_profile_capability_matches(role_bundle, active_profile)

    matched_profile_areas = (
        [("Strong capability match", area) for area in capability_matches["strong"][:3]]
        + [("Capability match", area) for area in capability_matches["working"][:2]]
        + [("Capability match", area) for area in capability_matches["basic"][:1]]
    )
    for prefix, area in matched_profile_areas:
        label = friendly_capability_label(area)
        entry = f"{prefix}: {label}" if label else ""
        if entry and entry not in highlights:
            highlights.append(entry)

    reviewed = reviewed_signal_match_summary(
        {**record, "reviewed_signal_matches": record.get("reviewed_signal_matches") or reviewed_signal_matches_for_text(role_bundle)}
    )
    for signal in reviewed["matched"][:3]:
        label = friendly_capability_label(signal)
        if label and f"Matched signal: {label}" not in highlights:
            highlights.append(f"Matched signal: {label}")

    if has_government_context(lowered):
        highlights.append("Government context")

    contract_months = extract_contract_months(details_text)
    if contract_months and contract_months >= 12:
        highlights.append("12+ month contract")
    elif compact_whitespace(record.get("work_type") or "").lower() in {"full time", "full-time", "permanent"}:
        highlights.append("Permanent role")

    location_signal = assess_location_preference(record, active_profile)
    if location_signal and int(location_signal.get("value", 0) or 0) > 0:
        highlights.append(str(location_signal.get("label") or "Location preference match"))

    highlights.extend(competitive_fit_highlights(record, active_profile))
    return dedupe_preserve_order(highlights)[:4]


def competitive_signal_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    entries: List[dict] = []
    for signal in competitive_signal_assessments(record, profile):
        adjustment = int(signal.get("adjustment", 0) or 0)
        label_base = compact_whitespace(signal.get("fit_label") or signal.get("name") or "competitive signal")
        if not label_base or adjustment == 0:
            continue
        if adjustment > 0:
            label = f"Competitive signal aligns: {label_base}"
        else:
            label = f"Competitive signal leans elsewhere: {label_base}"
        entries.append({"label": label, "value": adjustment})
    entries.sort(key=lambda item: (abs(int(item.get("value", 0))), item.get("label", "")), reverse=True)
    return entries[:2]


def fit_score_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    breakdown: List[dict] = []
    title_reason = str(record.get("title_reason") or "")
    content_reason = str(record.get("content_reason") or "")
    title_metadata = record.get("title_match_metadata") if isinstance(record.get("title_match_metadata"), dict) else {}
    posted_age_days = current_posted_age_days(record)
    work_mode = str(record.get("work_mode") or "").lower()
    fit_highlights = [item for item in record.get("fit_highlights", []) if str(item).strip()]
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    evidence_score, capability_matches = capability_evidence_score(record, active_profile)
    reviewed_signal_matches = reviewed_signal_match_summary(record, active_profile)
    if not title_metadata and str(record.get("title") or "").strip():
        title_metadata = analyze_title_filters(str(record.get("title") or ""), active_profile)
    title_family = str(title_metadata.get("match_family") or "").strip().lower()
    title_seniority_adjustment = int(title_metadata.get("seniority_adjustment") or 0)

    if hard_block_labels:
        return [{"label": f"Hard blocker requirement mismatch: {hard_block_labels[0]}", "value": int(scoring_rules["fit_breakdown"]["hard_block_penalty"])}]

    if title_family == "primary" or (not title_family and title_reason == "OK"):
        breakdown.append({
            "label": "Primary role-family match",
            "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_direct"]), weights["fit"]),
        })
        if title_seniority_adjustment:
            breakdown.append({
                "label": "Primary seniority adjustment",
                "value": weighted_points(int(title_seniority_adjustment), weights["fit"]),
            })
    elif title_family == "secondary" or (not title_family and title_reason == "TITLE_POTENTIAL_MATCH"):
        breakdown.append({
            "label": "Secondary role-family match",
            "value": weighted_points(int(scoring_rules["fit_breakdown"]["title_secondary"]), weights["fit"]),
        })

    llm_entry = llm_description_fit_entry(record, active_profile)
    breakdown.append({"label": llm_entry["label"], "value": weighted_points(int(llm_entry["value"]), weights["fit"])})

    if content_reason == "OK":
        breakdown.append({"label": "Passed content filters", "value": weighted_points(int(scoring_rules["fit_breakdown"]["content_ok"]), weights["fit"])})

    if full_description_confidence(record) == "LOW":
        breakdown.append({"label": "Description capture incomplete", "value": weighted_points(int(scoring_rules["fit_breakdown"]["description_capture_incomplete"]), weights["fit"])})

    if evidence_score:
        breakdown.append({"label": "Fit evidence bullets", "value": weighted_points(evidence_score, weights["fit"])})

    convergence_entry = convergence_bonus_entry(record, capability_matches, active_profile)
    if convergence_entry:
        breakdown.append({
            "label": convergence_entry["label"],
            "value": weighted_points(int(convergence_entry["value"]), weights["fit"]),
        })

    for item in competitive_signal_breakdown(record, active_profile):
        breakdown.append({"label": item["label"], "value": weighted_points(int(item["value"]), weights["fit"])})

    if posted_age_days is not None:
        if posted_age_days <= (1 / 24):
            breakdown.append({"label": "Posted within the last hour", "value": weighted_points(int(scoring_rules["freshness"]["last_hour"]), weights["freshness"])})
        elif posted_age_days <= 1:
            breakdown.append({"label": "Posted within the last day", "value": weighted_points(int(scoring_rules["freshness"]["last_day"]), weights["freshness"])})
        elif posted_age_days <= 3:
            breakdown.append({"label": "Posted within the last 3 days", "value": weighted_points(int(scoring_rules["freshness"]["last_3_days"]), weights["freshness"])})
        elif posted_age_days <= 7:
            breakdown.append({"label": "Posted within the last week", "value": weighted_points(int(scoring_rules["freshness"]["last_week"]), weights["freshness"])})
        elif posted_age_days <= 15:
            breakdown.append({"label": "Still relatively recent", "value": weighted_points(int(scoring_rules["freshness"]["last_15_days"]), weights["freshness"])})

    location_item = assess_location_preference(record, active_profile)
    if location_item:
        breakdown.append({
            "label": location_item["label"],
            "value": weighted_points(int(location_item["value"]), weights["location"]),
        })

    contract_item = assess_contract_preference(record, active_profile)
    if contract_item:
        breakdown.append({
            "label": contract_item["label"],
            "value": weighted_points(int(contract_item["value"]), weights["contract"]),
        })

    government_item = assess_government_preference(record, active_profile)
    if government_item:
        breakdown.append({
            "label": government_item["label"],
            "value": weighted_points(int(government_item["value"]), weights["government"]),
        })

    if work_mode == "hybrid":
        breakdown.append({"label": "Hybrid work available", "value": weighted_points(int(scoring_rules["work_mode"]["hybrid"]), weights["work_mode"])})
    elif work_mode == "remote":
        breakdown.append({"label": "Remote work available", "value": weighted_points(int(scoring_rules["work_mode"]["remote"]), weights["work_mode"])})
    elif work_mode in {"on-site", "onsite", "on site"}:
        breakdown.append({"label": "On-site role", "value": weighted_points(int(scoring_rules["work_mode"]["on_site"]), weights["work_mode"])})

    salary_score = weighted_points(salary_fit_adjustment(record, active_profile), weights["salary"])
    if salary_score > 0:
        breakdown.append({"label": "Salary/rate signal", "value": salary_score})
    elif salary_score < 0:
        breakdown.append({"label": "Salary/rate below target", "value": salary_score})

    if viewed_by_user(record) and not record.get("applied"):
        breakdown.append({"label": "Already viewed by you", "value": int(scoring_rules["fit_breakdown"]["viewed_by_user"])})

    return breakdown


def fit_score(record: dict, profile: Optional[dict] = None) -> int:
    score = sum(item["value"] for item in fit_score_breakdown(record, profile))
    return max(min(score, 100), 0)
