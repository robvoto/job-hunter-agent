"""Helpers for capability matching."""

import re
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from job_hunter_agent.capability_matrix import expand_capability_terms
from job_hunter_agent.description_trust import get_trusted_full_description
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_CAPABILITIES,
    KEY_MUST_NOT_REQUIRED_SKILLS,
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
    CapabilityLevel,
    get_candidate_profile_tier_weights,
    get_candidate_profile_tiers,
)
from job_hunter_agent.role_analysis import friendly_capability_label, text_contains_term
from job_hunter_agent.scoring_utils import (
    build_scoring_source_text,
    find_profile_experience_year_in_text,
)
from job_hunter_agent.signal_registry import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    load_approved_signal_catalog,
    load_registry,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_HARD_BLOCKER_PATTERN,
    LEARNING_CATEGORY_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    SIGNAL_ADJUSTMENT_KEY,
    SIGNAL_ALIGNMENT_KEY,
    SIGNAL_LABEL_KEY,
    SIGNAL_RISK_LABEL_KEY,
    TITLE_REASON_POTENTIAL_MATCH,
)
from job_hunter_agent.text_processing import (
    compact_whitespace,
    dedupe_preserve_order,
    list_to_phrase,
)

_REVIEW_SIGNAL_EXCLUDED_CATEGORIES = frozenset({
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
})
_REVIEW_SIGNAL_EXCLUDED_CATEGORIES_WITH_HARD_BLOCKERS = _REVIEW_SIGNAL_EXCLUDED_CATEGORIES | {
    CATEGORY_HARD_BLOCKER_PATTERN
}


@lru_cache(maxsize=1)
def _capability_ui_labels() -> dict:
    labels = load_ui_labels().get("workspace_card_labels", {})
    return labels if isinstance(labels, dict) else {}


def reviewed_signal_matches_for_text(details_text: str) -> dict[str, list[str]]:
    lowered = compact_whitespace(details_text).lower()
    buckets = {
        "matched": [],
        "evidence_only": [],
        "ignored": [],
        "unresolved": [],
    }
    if not lowered:
        return buckets

    registry = load_registry()
    for record in registry.values():
        if not isinstance(record, dict):
            continue
        category = compact_whitespace(record.get(LEARNING_CATEGORY_KEY) or "").lower()
        if category in _REVIEW_SIGNAL_EXCLUDED_CATEGORIES_WITH_HARD_BLOCKERS:
            continue
        label = compact_whitespace(record.get(LEARNING_SIGNAL_KEY) or "")
        terms = [label, *(record.get(LEARNING_ORIGINAL_TEXTS_KEY) or [])]
        if not label:
            continue
        if not any(text_contains_term(lowered, term) for term in terms if str(term).strip()):
            continue
        decision = compact_whitespace(
            record.get("decision") or record.get("learning_status") or record.get("status")
        ).lower()
        display_label = _display_review_signal_label(label)
        if not display_label:
            continue
        if decision in {"use", "approved", "keep", "accept"}:
            buckets["matched"].append(display_label)
        elif decision in {"evidence_only", "evidence only"}:
            buckets["evidence_only"].append(display_label)
        elif decision in {"ignore", "ignored"}:
            buckets["ignored"].append(display_label)
        else:
            buckets["unresolved"].append(display_label)

    for item in load_approved_signal_catalog():
        label = compact_whitespace(item.get("label") or "")
        terms = item.get("terms") if isinstance(item, dict) else []
        category = compact_whitespace(item.get(LEARNING_CATEGORY_KEY) or "").lower()
        if (
            not label
            or not isinstance(terms, list)
            or category != CATEGORY_CAPABILITY_CONCEPT
        ):
            continue
        if not any(text_contains_term(lowered, term) for term in terms):
            continue
        display_label = _display_review_signal_label(label)
        if display_label:
            buckets["matched"].append(display_label)

    return {key: dedupe_preserve_order(values) for key, values in buckets.items()}


def _display_review_signal_label(value: str) -> str:
    cleaned = compact_whitespace(value).lower()
    if not cleaned:
        return ""
    return friendly_capability_label(cleaned)


_WORK_TYPE_REVIEW_LABELS = (
    "contract",
    "permanent",
    "ftc",
    "full time contract",
    "full-time contract",
    "contract/temp",
    "temporary",
)


def _is_work_type_review_label(label: str) -> bool:
    cleaned = compact_whitespace(label).lower()
    if not cleaned:
        return False
    return any(token == cleaned or token in cleaned for token in _WORK_TYPE_REVIEW_LABELS)


def _review_signal_evidence_phrase(label: str, profile: Optional[dict]) -> str:
    if not isinstance(profile, dict):
        return "related experience"

    matches = find_profile_capability_matches(label, profile)
    evidence: list[str] = []
    for bucket in ("core", "supporting", "strong", "working", "basic"):
        for item in matches.get(bucket) or []:
            cleaned = compact_whitespace(item)
            if cleaned:
                evidence.append(cleaned)

    evidence = dedupe_preserve_order(evidence)
    if not evidence:
        return "related experience"
    if len(evidence) == 1:
        return evidence[0]
    return list_to_phrase(evidence[:2])


def humanize_reviewed_signal_match(label: str, profile: Optional[dict] = None) -> str:
    cleaned = _display_review_signal_label(label)
    if not cleaned:
        return ""

    if _is_work_type_review_label(cleaned):
        return ""

    evidence_phrase = _review_signal_evidence_phrase(cleaned, profile)
    if evidence_phrase == "related experience":
        return f"The ad mentions {cleaned}, and your profile shows related experience."
    return f"The ad mentions {cleaned}, and your profile shows {evidence_phrase}."


def reviewed_signal_match_summary(
    record: dict, profile: Optional[dict] = None
) -> dict[str, list[str]]:
    existing = record.get("reviewed_signal_matches")
    if isinstance(existing, dict):
        active_profile = profile or {}

        def _humanized(bucket: str) -> list[str]:
            items: list[str] = []
            for item in existing.get(bucket) or []:
                if _is_work_type_review_label(item):
                    continue
                sentence = humanize_reviewed_signal_match(item, active_profile)
                if sentence:
                    items.append(sentence)
            return dedupe_preserve_order(items)

        return {
            "matched": _humanized("matched"),
            "evidence_only": _humanized("evidence_only"),
            "ignored": _humanized("ignored"),
            "unresolved": _humanized("unresolved"),
        }
    source_text = get_trusted_full_description(record) or build_scoring_source_text(record)
    summary = reviewed_signal_matches_for_text(source_text)
    active_profile = profile or {}
    return {
        key: [
            sentence
            for sentence in (
                (
                    ""
                    if _is_work_type_review_label(item)
                    else humanize_reviewed_signal_match(item, active_profile)
                )
                for item in values
            )
            if sentence
        ]
        for key, values in summary.items()
    }


def find_profile_capability_matches(details_text: str, profile: dict) -> Dict[str, List[str]]:
    lowered = compact_whitespace(details_text).lower()
    matched_core: List[str] = []
    matched_supporting: List[str] = []
    matched_strong: List[str] = []
    matched_working: List[str] = []
    matched_basic: List[str] = []
    matched_limited_depth: List[str] = []
    matched_must_not: List[str] = []

    for rule in profile.get(KEY_CANDIDATE_CAPABILITIES, []):
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "").strip()
        level = str(rule.get("level") or "").strip().lower()
        fit = str(rule.get("fit") or "").strip().lower()
        terms = expand_capability_terms(rule)
        if not terms:
            continue
        if not any(text_contains_term(lowered, term) for term in terms):
            continue
        label = friendly_capability_label(name)
        if fit == "core":
            matched_core.append(label)
        elif fit == "supporting":
            matched_supporting.append(label)
        if level == CapabilityLevel.STRONG:
            matched_strong.append(label)
        elif level == CapabilityLevel.WORKING:
            matched_working.append(label)
        elif level == CapabilityLevel.BASIC:
            matched_basic.append(label)
        elif level == CapabilityLevel.LOW:
            matched_limited_depth.append(label)

    for skill in profile.get(KEY_MUST_NOT_REQUIRED_SKILLS, []):
        cleaned_skill = str(skill).strip().lower()
        if not cleaned_skill or not text_contains_term(lowered, cleaned_skill):
            continue
        pos = lowered.find(cleaned_skill)
        context_window = lowered[max(0, pos - 90) : pos + 90] if pos >= 0 else lowered
        if re.search(
            r"\b(desirable|preferred|highly regarded|nice to have|advantageous|beneficial)\b",
            context_window,
        ):
            continue
        matched_must_not.append(cleaned_skill.upper() if cleaned_skill.isupper() else cleaned_skill)

    return {
        "core": dedupe_preserve_order(matched_core),
        "supporting": dedupe_preserve_order(matched_supporting),
        "strong": dedupe_preserve_order(matched_strong),
        "working": dedupe_preserve_order(matched_working),
        "basic": dedupe_preserve_order(matched_basic),
        "limited_depth": dedupe_preserve_order(matched_limited_depth),
        "must_not": dedupe_preserve_order(matched_must_not),
    }


def description_watchout_reasons(details_text: str, profile: dict) -> List[str]:
    lowered = compact_whitespace(details_text).lower()
    if not lowered:
        return []

    watchouts: List[str] = []
    profile_blockers = {
        compact_whitespace(str(skill)).lower()
        for skill in profile.get(KEY_MUST_NOT_REQUIRED_SKILLS, [])
        if compact_whitespace(str(skill)).lower()
    }
    seen_terms: set[str] = set(profile_blockers)

    for skill in profile.get(KEY_MUST_NOT_REQUIRED_SKILLS, []):
        cleaned_skill = compact_whitespace(str(skill)).lower()
        if not cleaned_skill or not text_contains_term(lowered, cleaned_skill):
            continue
        label = cleaned_skill.upper() if cleaned_skill.isupper() else cleaned_skill
        pos = lowered.find(cleaned_skill)
        context_window = lowered[max(0, pos - 90) : pos + 90] if pos >= 0 else lowered
        if re.search(
            r"\b(desirable|preferred|highly regarded|nice to have|advantageous|beneficial)\b",
            context_window,
        ):
            watchouts.append(f"{label} appears desirable")
        else:
            watchouts.append(f"{label} appears required")

    for match in find_hard_block_matches(
        details_text, profile.get(KEY_MUST_NOT_REQUIRED_SKILLS, [])
    ):
        canonical = compact_whitespace(match.get("value") or "")
        matched_term = compact_whitespace(match.get("matched_term") or "")
        term_key = canonical.lower() or matched_term.lower()
        if not term_key or term_key in seen_terms:
            continue
        label_text = matched_term or canonical
        label = label_text.upper() if label_text.isupper() else label_text.lower()
        watchouts.append(f"{label} appears required")
        seen_terms.add(term_key)

    for rule in profile.get("reject_description_phrase_rules", []):
        phrase = compact_whitespace(str(rule.get("phrase") or "")).lower()
        if phrase and phrase in lowered:
            watchouts.append(f"Blocked description phrase appears: {phrase}")

    return dedupe_preserve_order(watchouts)[:4]


def is_capability_fit_highlight(value: str) -> bool:
    normalized = compact_whitespace(value)
    return normalized.startswith("Capability match:") or normalized.startswith(
        "Strong capability match:"
    )


def capability_fit_highlights(fit_highlights: List[str]) -> List[str]:
    return [
        compact_whitespace(item)
        for item in fit_highlights
        if is_capability_fit_highlight(str(item))
    ]


def build_risk_and_missing_profile_support(
    details_text: str,
    title_reason: Optional[str],
    profile: dict,
    competitive_signals: Optional[List[dict]] = None,
) -> Tuple[List[str], List[str]]:
    risks: List[str] = []
    missing: List[str] = []
    capability_matches = find_profile_capability_matches(details_text, profile)

    if title_reason == TITLE_REASON_POTENTIAL_MATCH:
        risks.append("Secondary role-family match rather than direct target role")

    if capability_matches["must_not"]:
        missing.append(
            f"{list_to_phrase(capability_matches['must_not'][:2]).capitalize()} explicitly required but not shown"
        )

    if capability_matches["limited_depth"]:
        risks.append(
            f"{list_to_phrase(capability_matches['limited_depth'][:2]).capitalize()} appears in the role, but your profile marks it as beginner-level"
        )

    risks.extend(description_watchout_reasons(details_text, profile))

    for signal in competitive_signals or []:
        if int(signal.get(SIGNAL_ADJUSTMENT_KEY, 0)) < 0:
            alignment = compact_whitespace(signal.get(SIGNAL_ALIGNMENT_KEY) or "").lower()
            fit_label = compact_whitespace(signal.get(SIGNAL_LABEL_KEY) or "")
            risk_label = compact_whitespace(signal.get(SIGNAL_RISK_LABEL_KEY) or "") or fit_label
            if risk_label:
                if alignment == "weak":
                    missing.append(f"{risk_label} required but weakly shown")
                else:
                    partial_suffix = str(
                        _capability_ui_labels().get("partial_support_risk_suffix")
                        or "is only partially supported by your profile"
                    )
                    risks.append(f"{risk_label} {partial_suffix}")

    return dedupe_preserve_order(risks)[:4], dedupe_preserve_order(missing)[:4]


def _normalized_aliases(values: List[str]) -> List[str]:
    return dedupe_preserve_order(
        [
            compact_whitespace(str(value)).lower()
            for value in values
            if compact_whitespace(str(value))
        ]
    )


def _profile_auxiliary_text(profile: dict) -> str:
    parts = [
        profile.get("llm_profile_brief"),
        profile.get("star_evidence_text"),
    ]
    return "\n".join(compact_whitespace(part).lower() for part in parts if compact_whitespace(part))


def evidence_tier_alignment_score(profile: dict, aliases: List[str]) -> float:
    evidence_tiers = get_candidate_profile_tiers(profile)
    evidence_weights = get_candidate_profile_tier_weights(profile)
    tier_order = (
        KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
    )
    best_score = 0.0

    for tier_name in tier_order:
        tier_text = compact_whitespace(evidence_tiers.get(tier_name) or "").lower()
        if not tier_text:
            continue
        alias_hits = [alias for alias in aliases if text_contains_term(tier_text, alias)]
        if not alias_hits:
            continue
        hit_count = len(alias_hits)
        base_strength = min(0.42 + (0.18 * min(hit_count - 1, 3)), 1.0)
        tier_weight = float(evidence_weights.get(tier_name, 0.0) or 0.0)
        recent_year = find_profile_experience_year_in_text(tier_text, aliases)
        if recent_year:
            years_ago = max(datetime.now().year - int(recent_year), 0)
            if years_ago <= 5:
                recency_multiplier = 1.0
            elif years_ago <= 10:
                recency_multiplier = 0.6
            else:
                recency_multiplier = 0.3
        elif tier_name == KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT:
            recency_multiplier = 1.0
        elif tier_name == KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT:
            recency_multiplier = 0.6
        else:
            recency_multiplier = 0.35

        best_score = max(best_score, base_strength * tier_weight * recency_multiplier)

    auxiliary_text = _profile_auxiliary_text(profile)
    auxiliary_hits = sum(1 for alias in aliases if text_contains_term(auxiliary_text, alias))
    if auxiliary_hits:
        best_score = max(best_score, min(0.12 + (0.05 * min(auxiliary_hits - 1, 2)), 0.22))

    return min(best_score, 1.0)
