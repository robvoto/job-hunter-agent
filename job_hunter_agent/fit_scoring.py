"""Helpers for fit scoring."""

import logging
from typing import Dict, List, Optional

from job_hunter_agent.capability_matching import (
    find_profile_capability_matches,
)

logger = logging.getLogger(__name__)
from job_hunter_agent.description_trust import full_description_confidence
from job_hunter_agent.filters import analyze_title_filters
from job_hunter_agent.global_settings import KEY_FIT_HIGHLIGHTS, load_global_settings
from job_hunter_agent.history import viewed_by_user
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.posting_utils import current_posted_age_days
from job_hunter_agent.preferences import (
    assess_location_preference,
    salary_fit_adjustment,
)
from job_hunter_agent.profile_store import (
    KEY_CONVERGENCE,
    KEY_LLM_GRADE_BANDS,
    KEY_LLM_GRADE_POINTS,
    CapabilityLevel,
    get_preference_weights,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.record_schema import (
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)
from job_hunter_agent.role_analysis import (
    friendly_capability_label,
    role_text_bundle,
)
from job_hunter_agent.scoring_utils import weighted_points
from job_hunter_agent.signal_detection import (
    competitive_fit_highlights,
    competitive_signal_assessments,
    hard_block_reasons,
)
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
        else "Job has not been through LLM review, so scoring is blocked until the pipeline runs successfully."
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


def convergence_bonus_entry(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    """Award a bonus when multiple strong independent signals simultaneously confirm fit.

    Convergence requires title match, description quality, grade, and LLM-supported capabilities
    (high-confidence contextual matches). Conditions and bonus values come from scoring_rules.json.
    """
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    title_reason = str(record.get("title_reason") or "").strip().upper()
    content_reason = str(record.get("content_reason") or "").strip().upper()
    fit_confidence = full_description_confidence(record)
    missing_profile_support = [
        item for item in (record.get("missing_profile_support") or []) if compact_whitespace(item)
    ]
    soft_risks = [
        item for item in (record.get("soft_risk_reasons") or []) if compact_whitespace(item)
    ]
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    convergence_rules = scoring_rules[KEY_CONVERGENCE]
    positive_count = sum(
        1
        for item in (record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "supported"
    )
    if (
        title_reason != convergence_rules["required_title_reason"]
        or content_reason != convergence_rules["required_content_reason"]
        or fit_confidence != convergence_rules["required_fit_confidence"]
    ):
        return None
    if missing_profile_support or grade not in set(convergence_rules["eligible_grades"]):
        return None
    if positive_count < int(convergence_rules["min_positive_matches"]):
        return None
    bonus = int(
        convergence_rules["bonus_no_soft_risks"]
        if not soft_risks
        else convergence_rules["bonus_with_soft_risks"]
    )
    return {"label": convergence_rules["label"], "value": bonus}


def requirement_coverage_entries(record: dict) -> List[dict]:
    entries: List[dict] = []
    coverage = record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []
    if not isinstance(coverage, list) or not coverage:
        if record.get("review_source") == "llm" and record.get(RECORD_JOB_REQUIREMENTS_KEY):
            entries.append(
                {"label": "Requirement coverage not returned", "value": 0, "section": "llm_fit"}
            )
        return entries

    for item in coverage:
        if not isinstance(item, dict):
            continue
        requirement = str(item.get("requirement") or "").strip()
        importance = str(item.get("importance") or "preferred").strip().lower()
        status = str(item.get("status") or "").strip().lower().replace("_", " ")
        capability_name = str(item.get("capability_name") or "").strip()
        matched_job_text = str(item.get("matched_job_text") or "").strip()
        profile_support = [
            compact_whitespace(text)
            for text in (item.get("profile_support") or [])
            if compact_whitespace(text)
        ]
        if not requirement:
            continue
        label = f"[{importance}] Requirement {status}: {requirement}"
        details: list[str] = []
        if capability_name:
            details.append(f"capability: {friendly_capability_label(capability_name)}")
        if matched_job_text:
            details.append(f"job text: {matched_job_text}")
        if profile_support:
            details.append(f"profile support: {', '.join(profile_support[:2])}")
        if details:
            label = f"{label} | " + " | ".join(details)
        entries.append({"label": label, "value": 0, "section": "llm_fit"})
    return entries


def capability_support_log(record: dict) -> None:
    """Log requirement-coverage capability support for debugging.

    Replaces the old contextual_capability_matches transparency log.
    Source of truth is requirement_coverage — the single capability-matching mechanism.
    """
    supported: list[str] = []
    low_confidence: list[str] = []
    for item in record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []:
        if not isinstance(item, dict):
            continue
        cap_name = str(item.get("capability_name") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if not cap_name:
            continue
        label = friendly_capability_label(cap_name)
        if status == "supported":
            supported.append(label)
        elif status == "partially_supported":
            low_confidence.append(label)

    logger.info(
        "[CAPABILITY_SUPPORT] job=%s supported=%s low_confidence=%s",
        record.get("job_key", "<unknown>"),
        ", ".join(dedupe_preserve_order(supported)) or "(none)",
        ", ".join(dedupe_preserve_order(low_confidence)) or "(none)",
    )


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
            (highlight_labels["strong_capability_match"], area)
            for area in capability_matches[CapabilityLevel.STRONG][
                : hl_config["strong_capability_count"]
            ]
        ]
        + [
            (highlight_labels["capability_match"], area)
            for area in capability_matches[CapabilityLevel.WORKING][
                : hl_config["working_capability_count"]
            ]
        ]
        + [
            (highlight_labels["capability_match"], area)
            for area in capability_matches[CapabilityLevel.BASIC][
                : hl_config["basic_capability_count"]
            ]
        ]
    )
    for prefix, area in matched_profile_areas:
        label = friendly_capability_label(area)
        entry = f"{prefix}: {label}" if label else ""
        if entry and entry not in highlights:
            highlights.append(entry)

    location_signal = assess_location_preference(record, active_profile)
    if location_signal and int(location_signal.get("value", 0) or 0) > 0:
        label = location_signal["label"]
        if not label:
            raise ValueError(
                f"assess_location_preference returned signal with empty label: {location_signal!r}"
            )
        highlights.append(label)

    highlights.extend(competitive_fit_highlights(record, active_profile))
    return dedupe_preserve_order(highlights)[: hl_config["max_highlights"]]


def competitive_signal_breakdown(record: dict, profile: Optional[dict] = None) -> List[dict]:
    hl_labels = load_ui_labels()["fit_highlight_labels"]
    entries: List[dict] = []
    for signal in competitive_signal_assessments(record, profile):
        adjustment = int(signal.get("adjustment", 0) or 0)
        if adjustment == 0:
            continue
        prefix = (
            hl_labels["competitive_signal_aligns"]
            if adjustment > 0
            else hl_labels["competitive_signal_elsewhere"]
        )
        entries.append({"label": f"{prefix}: {signal[SIGNAL_LABEL_KEY]}", "value": adjustment})
    entries.sort(
        key=lambda item: (abs(int(item.get("value", 0))), item.get("label", "")), reverse=True
    )
    return entries[:2]


def build_core_fit_breakdown(
    record: dict,
    scoring_rules: dict,
    weights: dict,
    title_family: str,
    title_reason: str,
    content_reason: str,
    active_profile: dict,
) -> List[dict]:
    title_match_labels = load_ui_labels().get("title_match_labels", {})
    entries: List[dict] = []
    if title_family == "primary" or (not title_family and title_reason == "OK"):
        entries.append(
            {
                "label": title_match_labels["primary_match"],
                "value": weighted_points(
                    int(scoring_rules["fit_breakdown"]["title_direct"]), weights["fit"]
                ),
                "section": "title",
            }
        )
    elif title_family == "secondary" or (
        not title_family and title_reason == TITLE_REASON_POTENTIAL_MATCH
    ):
        entries.append(
            {
                "label": title_match_labels["secondary_match"],
                "value": weighted_points(
                    int(scoring_rules["fit_breakdown"]["title_secondary"]), weights["fit"]
                ),
                "section": "title",
            }
        )
    llm_entry = llm_description_fit_entry(record, active_profile)
    entries.append(
        {
            "label": llm_entry["label"],
            "value": weighted_points(int(llm_entry["value"]), weights["fit"]),
            "section": "llm_fit",
        }
    )
    entries.extend(requirement_coverage_entries(record))
    if content_reason == "OK":
        entries.append(
            {
                "label": "Passed content filters",
                "value": weighted_points(
                    int(scoring_rules["fit_breakdown"]["content_ok"]), weights["fit"]
                ),
                "section": "content",
            }
        )
    if full_description_confidence(record) == "LOW":
        entries.append(
            {
                "label": "Description capture incomplete",
                "value": weighted_points(
                    int(scoring_rules["fit_breakdown"]["description_capture_incomplete"]),
                    weights["fit"],
                ),
                "section": "content",
            }
        )
    capability_support_log(record)
    convergence_entry = convergence_bonus_entry(record, active_profile)
    if convergence_entry:
        entries.append(
            {
                "label": convergence_entry["label"],
                "value": weighted_points(int(convergence_entry["value"]), weights["fit"]),
                "section": "capability",
            }
        )
    for item in competitive_signal_breakdown(record, active_profile):
        entries.append(
            {
                "label": item["label"],
                "value": weighted_points(int(item["value"]), weights["fit"]),
                "section": "other",
            }
        )
    return entries


def build_preference_breakdown(
    record: dict, scoring_rules: dict, weights: dict, active_profile: dict
) -> List[dict]:
    entries: List[dict] = []
    location_item = assess_location_preference(record, active_profile)
    if location_item:
        entries.append(
            {
                "label": location_item["label"],
                "value": weighted_points(int(location_item["value"]), weights["location"]),
                "section": "location",
            }
        )
    else:
        entries.append({"label": "Location: no preference set", "value": 0, "section": "location"})
    salary_score = weighted_points(salary_fit_adjustment(record, active_profile), weights["salary"])
    if salary_score > 0:
        entries.append({"label": "Salary/rate signal", "value": salary_score, "section": "salary"})
    elif salary_score < 0:
        entries.append(
            {"label": "Salary/rate below target", "value": salary_score, "section": "salary"}
        )
    else:
        no_salary_label = (
            load_ui_labels()
            .get("score_gap_labels", {})
            .get("no_comparable_salary_rate", "No salary info found")
        )
        entries.append({"label": no_salary_label, "value": 0, "section": "salary"})
    return entries


def build_freshness_breakdown(
    scoring_rules: dict, weights: dict, posted_age_days: Optional[float]
) -> List[dict]:
    entries: List[dict] = []
    if posted_age_days is None:
        return entries

    freshness_rules = scoring_rules["freshness"]
    buckets = freshness_rules["buckets"]
    bucket_order = freshness_rules["bucket_order"]
    if (
        not isinstance(buckets, dict)
        or not buckets
        or not isinstance(bucket_order, list)
        or not bucket_order
    ):
        raise ValueError("freshness buckets are required in scoring_rules")

    for bucket_key in bucket_order:
        lookup_key = bucket_key.lower()
        bucket = buckets.get(lookup_key)
        if not isinstance(bucket, dict):
            raise ValueError(f"Invalid freshness bucket: {bucket_key}")
        if posted_age_days <= float(bucket["max_days"]):
            entries.append(
                {
                    "label": str(bucket["label"]),
                    "value": weighted_points(
                        int(freshness_rules[lookup_key]), weights["freshness"]
                    ),
                    "section": "freshness",
                }
            )
            break
    return entries


def build_convenience_breakdown(
    record: dict, scoring_rules: dict, weights: dict, posted_age_days: Optional[float]
) -> List[dict]:
    entries: List[dict] = []
    entries.extend(build_freshness_breakdown(scoring_rules, weights, posted_age_days))
    if viewed_by_user(record) and not record.get("applied"):
        entries.append(
            {
                "label": "Already viewed by you",
                "value": int(scoring_rules["fit_breakdown"]["viewed_by_user"]),
            }
        )
    return entries


def build_risk_breakdown(scoring_rules: dict, hard_block_labels: List[str]) -> List[dict]:
    return [
        {
            "label": f"Hard blocker requirement mismatch: {label}",
            "value": int(scoring_rules["fit_breakdown"]["hard_block_penalty"]),
            "section": "risk",
        }
        for label in hard_block_labels
    ]


def _score_bounds(scoring_rules: dict) -> tuple[int, int]:
    bands = scoring_rules.get(KEY_LLM_GRADE_BANDS, {})
    if not isinstance(bands, dict) or not bands:
        raise ValueError("llm_grade_bands are required in scoring_rules")

    floors: list[int] = []
    ceilings: list[int] = []
    for grade, band in bands.items():
        if not isinstance(band, dict) or "floor" not in band or "ceiling" not in band:
            continue
        try:
            floor = int(band["floor"])
            ceiling = int(band["ceiling"])
        except Exception as exc:
            raise ValueError(f"Invalid grade band bounds for {grade}") from exc
        if floor < 0 or ceiling < floor:
            raise ValueError(
                f"Invalid grade band range for {grade}: floor={floor}, ceiling={ceiling}"
            )
        floors.append(floor)
        ceilings.append(ceiling)

    if not floors or not ceilings:
        raise ValueError("llm_grade_bands must define grade entries with floor and ceiling values")

    return min(floors), max(ceilings)


def _clamp_score(score: int, scoring_rules: dict) -> int:
    minimum_score, maximum_score = _score_bounds(scoring_rules)
    return max(min(score, maximum_score), minimum_score)


def _grade_band_adjustment(grade: str, raw: int, bands: dict) -> Optional[dict]:
    """Return a transparent breakdown entry when band clamping applies, or None.

    Ceiling cap: score exceeds the grade's maximum — entry value is negative.
    Floor lift:  score falls below the grade's minimum — entry value is positive.
    Hard block entries are excluded from `raw` so they cannot trigger the floor.
    """
    band = bands.get(grade)
    if not isinstance(band, dict):
        return None
    try:
        floor = int(band["floor"])
        ceiling = int(band["ceiling"])
    except Exception as exc:
        raise ValueError(f"Invalid grade band bounds for {grade}") from exc
    if raw > ceiling:
        return {"label": f"Grade band ceiling ({grade} ≤ {ceiling})", "value": ceiling - raw}
    if raw < floor:
        return {"label": f"Grade band floor ({grade} ≥ {floor})", "value": floor - raw}
    return None


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
    title_metadata = (
        record.get("title_match_metadata")
        if isinstance(record.get("title_match_metadata"), dict)
        else {}
    )
    posted_age_days = current_posted_age_days(record)
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    if not title_metadata and str(record.get("title") or "").strip():
        title_metadata = analyze_title_filters(str(record.get("title") or ""), active_profile)
    title_family = str(title_metadata.get("match_family") or "").strip().lower()

    # Build non-hard-block entries first so the band clamp does not interact with hard block penalties.
    non_hard_block = (
        build_core_fit_breakdown(
            record,
            scoring_rules,
            weights,
            title_family,
            title_reason,
            content_reason,
            active_profile,
        )
        + build_preference_breakdown(record, scoring_rules, weights, active_profile)
        + build_convenience_breakdown(record, scoring_rules, weights, posted_age_days)
    )

    # Apply grade band clamping: enforce floor and ceiling per LLM grade.
    # Hard block penalties are applied after this step and can override the floor.
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    grade_bands = scoring_rules.get(KEY_LLM_GRADE_BANDS, {})
    raw_non_hard_block = sum(e["value"] for e in non_hard_block)
    band_entry = _grade_band_adjustment(grade, raw_non_hard_block, grade_bands)
    if band_entry is not None:
        non_hard_block = non_hard_block + [band_entry]

    return non_hard_block + build_risk_breakdown(scoring_rules, hard_block_labels)


def has_hard_blockers(record: dict, profile: Optional[dict] = None) -> bool:
    active_profile = profile or load_profile()
    return bool(hard_block_reasons(record, active_profile))


def fit_score(record: dict, profile: Optional[dict] = None) -> int:
    score = sum(item["value"] for item in fit_score_breakdown(record, profile))
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    return _clamp_score(score, scoring_rules)


def fit_score_breakdown_frozen(record: dict, profile: Optional[dict] = None) -> List[dict]:
    """Frozen breakdown computed once at scrape time — excludes freshness and viewed status.

    Grade band is applied to core + preference only. Freshness and viewed are added at
    display time by fit_score_and_breakdown_displayed.
    """
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
    title_metadata = (
        record.get("title_match_metadata")
        if isinstance(record.get("title_match_metadata"), dict)
        else {}
    )
    active_profile = profile or load_profile()
    weights = get_preference_weights(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    hard_block_labels = hard_block_reasons(record, active_profile)
    if not title_metadata and str(record.get("title") or "").strip():
        title_metadata = analyze_title_filters(str(record.get("title") or ""), active_profile)
    title_family = str(title_metadata.get("match_family") or "").strip().lower()

    non_hard_block = build_core_fit_breakdown(
        record, scoring_rules, weights, title_family, title_reason, content_reason, active_profile
    ) + build_preference_breakdown(record, scoring_rules, weights, active_profile)
    grade = str(record.get("llm_fit_grade") or "").strip().upper()
    grade_bands = scoring_rules.get(KEY_LLM_GRADE_BANDS, {})
    raw_non_hard_block = sum(e["value"] for e in non_hard_block)
    band_entry = _grade_band_adjustment(grade, raw_non_hard_block, grade_bands)
    if band_entry is not None:
        non_hard_block = non_hard_block + [band_entry]
    return non_hard_block + build_risk_breakdown(scoring_rules, hard_block_labels)


def fit_score_frozen(record: dict, profile: Optional[dict] = None) -> int:
    """Frozen score — excludes freshness and viewed status. Stored on the record at scrape time."""
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    return _clamp_score(
        sum(item["value"] for item in fit_score_breakdown_frozen(record, profile)), scoring_rules
    )


def fit_score_and_breakdown_displayed(
    record: dict, profile: Optional[dict] = None
) -> tuple[int, List[dict]]:
    """Displayed score and full breakdown: frozen base + current freshness + viewed status.

    Falls back to full live scoring for records that predate score freezing.
    """
    if RECORD_FIT_SCORE_KEY not in record:
        breakdown = fit_score_breakdown(record, profile)
        active_profile = profile or load_profile()
        scoring_rules = get_scoring_rules(active_profile)
        return _clamp_score(sum(e["value"] for e in breakdown), scoring_rules), breakdown
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    weights = get_preference_weights(active_profile)
    posted_age_days = current_posted_age_days(record)
    live_entries: List[dict] = list(
        build_freshness_breakdown(scoring_rules, weights, posted_age_days)
    )
    if viewed_by_user(record) and not record.get("applied"):
        live_entries.append(
            {
                "label": "Already viewed by you",
                "value": int(scoring_rules["fit_breakdown"]["viewed_by_user"]),
            }
        )
    frozen_score = int(record[RECORD_FIT_SCORE_KEY])
    frozen_breakdown = list(record.get(RECORD_FIT_SCORE_BREAKDOWN_KEY) or [])
    total = _clamp_score(frozen_score + sum(e["value"] for e in live_entries), scoring_rules)
    return total, frozen_breakdown + live_entries


def fit_score_displayed(record: dict, profile: Optional[dict] = None) -> int:
    """Displayed score for filtering and sorting: frozen base + current freshness + viewed status."""
    return fit_score_and_breakdown_displayed(record, profile)[0]
