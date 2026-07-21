"""Helpers for signal detection."""

import re
from typing import Any, List, Optional, Set

from job_hunter_agent.capability_matching import (
    _normalized_aliases,
    evidence_tier_alignment_score,
)
from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.io_utils import load_parsing_rules, load_signal_defaults
from job_hunter_agent.job_quality import detect_cv_farming_signals, load_dodgy_job_rules
from job_hunter_agent.parsing_schema import (
    PARSING_DEFAULT_KEY,
    PARSING_JUNK_KEYWORDS_KEY,
    PARSING_MAX_DISCOVERY_TERMS_KEY,
    PARSING_MIN_TERM_LENGTH_KEY,
    PARSING_SKILL_DISCOVERY_CONFIG_KEY,
    PARSING_STOPWORDS_KEY,
    PARSING_STRENGTH_COEFFICIENTS_KEY,
)
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_CAPABILITIES,
    KEY_COMPETITIVE_SIGNAL_ALIGNMENT,
    KEY_LEVEL,
    KEY_SIGNAL_CLUSTERS,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.role_analysis import text_contains_term
from job_hunter_agent.scoring_utils import build_scoring_source_text, profile_recency_multiplier
from job_hunter_agent.signal_registry import signal_in_approved_knowledge
from job_hunter_agent.signal_schema import (
    ALIGNMENT_PARTIAL,
    ALIGNMENT_STRONG,
    ALIGNMENT_WEAK,
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_HARD_BLOCKER_PATTERN,
    COMPETITIVE_SIGNALS_KEY,
    HARD_BLOCK_REASONS_KEY,
    HARD_BLOCK_TEXT_KEY,
    LEARNING_CATEGORY_KEY,
    LEARNING_CONTEXT_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_KNOWLEDGE_MATCH_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    OBSERVATION_SKILL_KEY,
    SIGNAL_ADJUSTMENT_KEY,
    SIGNAL_ALIAS_HITS_KEY,
    SIGNAL_ALIASES_KEY,
    SIGNAL_ALIGNMENT_KEY,
    SIGNAL_DOMINANCE_LEVEL_KEY,
    SIGNAL_FIT_LABEL_KEY,
    SIGNAL_LABEL_KEY,
    SIGNAL_NAME_KEY,
    SIGNAL_RISK_LABEL_KEY,
    SIGNAL_SNIPPET_HITS_KEY,
    SIGNAL_WATCHOUT_LABEL_KEY,
    SOURCE_JOB_PARSING,
)
from job_hunter_agent.text_processing import (
    compact_whitespace,
    dedupe_preserve_order,
    split_text_snippets,
)

CLUSTER_MIN_SNIPPET_HITS_KEY = "min_snippet_hits"
CLUSTER_DENSE_SNIPPET_ALIAS_HITS_KEY = "dense_snippet_alias_hits"
CLUSTER_HARD_BLOCK_ON_MISMATCH_KEY = "hard_block_on_mismatch"
CLUSTER_HARD_BLOCK_ALIGNMENT_LEVELS_KEY = "hard_block_alignment_levels"
CLUSTER_HARD_BLOCK_LABEL_KEY = "hard_block_label"
CLUSTER_POSITIVE_BONUS_KEY = "positive_bonus"
CLUSTER_PARTIAL_PENALTY_KEY = "partial_penalty"
CLUSTER_WEAK_PENALTY_KEY = "weak_penalty"

ALIGNMENT_STRONG_THRESHOLD_KEY = "strong_threshold"
ALIGNMENT_PARTIAL_THRESHOLD_KEY = "partial_threshold"
ALIGNMENT_RECENCY_FALLBACK_MIN_CAPABILITY_BEST_KEY = "recency_fallback_min_capability_best"
ALIGNMENT_RECENCY_FALLBACK_MULTIPLIER_KEY = "recency_fallback_multiplier"
ALIGNMENT_OVERLAP_BONUS_PER_EXTRA_ALIAS_KEY = "overlap_bonus_per_extra_alias"
ALIGNMENT_OVERLAP_BONUS_MAX_EXTRA_ALIASES_KEY = "overlap_bonus_max_extra_aliases"
ALIGNMENT_MAX_CAPABILITY_BEST_KEY = "max_capability_best"
ALIGNMENT_POSITIVE_BONUS_BY_DOMINANCE_KEY = "positive_bonus_by_dominance"
ALIGNMENT_PARTIAL_PENALTY_BY_DOMINANCE_KEY = "partial_penalty_by_dominance"
ALIGNMENT_WEAK_PENALTY_BY_DOMINANCE_KEY = "weak_penalty_by_dominance"


def _dedupe_key(value: Any) -> str:
    return compact_whitespace(str(value or "")).lower()


def _signal_defaults() -> dict[str, str]:
    defaults = load_signal_defaults()
    return {
        key: compact_whitespace(value)
        for key, value in defaults.items()
        if isinstance(value, str) and compact_whitespace(value)
    }


def _resolved_signal_text(source: dict[str, Any], key: str, defaults: dict[str, str]) -> str:
    value = compact_whitespace(source.get(key) or "")
    if value:
        return value
    return compact_whitespace(defaults.get(key) or "")


def _resolved_signal_int(source: dict[str, Any], key: str, fallback: Any) -> int:
    raw = source.get(key)
    if raw is None:
        return int(fallback)
    if isinstance(raw, str) and not raw.strip():
        return int(fallback)
    return int(raw)


def _capability_rule_strength(rule: dict) -> float:
    level = compact_whitespace(rule.get(KEY_LEVEL) or "").lower()
    rules = load_parsing_rules()
    level_map = rules.get(PARSING_STRENGTH_COEFFICIENTS_KEY, {})
    default = level_map.get(PARSING_DEFAULT_KEY, 0.45)
    return max(min(level_map.get(level, default), 1.0), 0.0)


def _competitive_signal_alignment_rules(profile: dict) -> dict[str, Any]:
    scoring_rules = get_scoring_rules(profile)
    rules = scoring_rules.get(KEY_COMPETITIVE_SIGNAL_ALIGNMENT, {})
    if not isinstance(rules, dict) or not rules:
        raise ValueError("competitive_signal_alignment rules are required in scoring_rules")
    return rules


def detect_competitive_signals(details_text: str, profile: Optional[dict] = None) -> List[dict]:
    active_profile = profile or load_profile()
    defaults = _signal_defaults()
    source_text = _dedupe_key(details_text)
    snippets = [_dedupe_key(snippet) for snippet in split_text_snippets(details_text)]
    if not source_text:
        return []

    detected: List[dict] = []
    for raw_cluster in active_profile.get(KEY_SIGNAL_CLUSTERS, []):
        if not isinstance(raw_cluster, dict):
            continue
        canonical = _dedupe_key(raw_cluster.get(SIGNAL_NAME_KEY) or "")
        aliases = [canonical] if canonical else []
        if not aliases:
            continue

        matched_aliases = [alias for alias in aliases if text_contains_term(source_text, alias)]
        if len(matched_aliases) < 1:
            continue

        snippet_hits = 0
        max_aliases_in_snippet = 0
        for snippet in snippets:
            alias_hits_in_snippet = sum(
                1 for alias in matched_aliases if text_contains_term(snippet, alias)
            )
            max_aliases_in_snippet = max(max_aliases_in_snippet, alias_hits_in_snippet)
            if alias_hits_in_snippet > 0:
                snippet_hits += 1
        min_snippet_hits = int(raw_cluster.get(CLUSTER_MIN_SNIPPET_HITS_KEY, 2))
        dense_snippet_alias_hits = int(
            raw_cluster.get(CLUSTER_DENSE_SNIPPET_ALIAS_HITS_KEY, 4)
        )
        if snippet_hits < min_snippet_hits and max_aliases_in_snippet >= dense_snippet_alias_hits:
            snippet_hits = min_snippet_hits
        if snippet_hits < min_snippet_hits:
            continue

        dominance_level = 1
        if len(matched_aliases) >= 3:
            dominance_level += 1
        if snippet_hits >= 3:
            dominance_level += 1

        detected.append(
            {
                SIGNAL_NAME_KEY: _resolved_signal_text(raw_cluster, SIGNAL_NAME_KEY, defaults),
                SIGNAL_FIT_LABEL_KEY: _resolved_signal_text(
                    raw_cluster, SIGNAL_FIT_LABEL_KEY, defaults
                ),
                SIGNAL_WATCHOUT_LABEL_KEY: _resolved_signal_text(
                    raw_cluster, SIGNAL_WATCHOUT_LABEL_KEY, defaults
                ),
                SIGNAL_RISK_LABEL_KEY: _resolved_signal_text(
                    raw_cluster, SIGNAL_RISK_LABEL_KEY, defaults
                ),
                SIGNAL_ALIASES_KEY: matched_aliases,
                SIGNAL_ALIAS_HITS_KEY: len(matched_aliases),
                SIGNAL_SNIPPET_HITS_KEY: snippet_hits,
                SIGNAL_DOMINANCE_LEVEL_KEY: min(dominance_level, 3),
            }
        )

    detected.sort(
        key=lambda item: (
            -int(item.get(SIGNAL_DOMINANCE_LEVEL_KEY, 0)),
            -int(item.get(SIGNAL_ALIAS_HITS_KEY, 0)),
            item.get(SIGNAL_NAME_KEY, ""),
        )
    )
    return detected[:3]


def evaluate_competitive_signal_alignment(signal: dict, profile: dict) -> dict:
    defaults = _signal_defaults()
    alignment_rules = _competitive_signal_alignment_rules(profile)
    signal_name = _resolved_signal_text(signal, SIGNAL_NAME_KEY, defaults)
    aliases = _normalized_aliases([signal_name])
    capability_best = 0.0

    for rule in profile.get(KEY_CANDIDATE_CAPABILITIES, []):
        if not isinstance(rule, dict):
            continue
        canonical = canonical_capability_term(rule)
        rule_aliases = _normalized_aliases([canonical])
        if not canonical:
            continue
        overlap = sum(
            1
            for alias in aliases
            if alias in rule_aliases
            or any(alias in rule_alias or rule_alias in alias for rule_alias in rule_aliases)
        )
        if overlap <= 0:
            continue
        rule_strength = _capability_rule_strength(rule)
        overlap_bonus = float(alignment_rules[ALIGNMENT_OVERLAP_BONUS_PER_EXTRA_ALIAS_KEY])
        max_overlap_bonus_steps = int(
            alignment_rules[ALIGNMENT_OVERLAP_BONUS_MAX_EXTRA_ALIASES_KEY]
        )
        max_capability_best = float(alignment_rules[ALIGNMENT_MAX_CAPABILITY_BEST_KEY])
        capability_best = max(
            capability_best,
            min(
                rule_strength + (overlap_bonus * min(overlap - 1, max_overlap_bonus_steps)),
                max_capability_best,
            ),
        )

    tiered_evidence_score = evidence_tier_alignment_score(profile, aliases)
    recency_multiplier = profile_recency_multiplier(profile, aliases)
    if recency_multiplier == 0.0 and capability_best >= float(
        alignment_rules[ALIGNMENT_RECENCY_FALLBACK_MIN_CAPABILITY_BEST_KEY]
    ):
        recency_multiplier = float(alignment_rules[ALIGNMENT_RECENCY_FALLBACK_MULTIPLIER_KEY])

    dominant_alignment_score = max(
        capability_best * (recency_multiplier or 1.0),
        tiered_evidence_score,
    )

    dominance_level = int(signal.get(SIGNAL_DOMINANCE_LEVEL_KEY, 1))
    positive_bonus = _resolved_signal_int(
        signal,
        CLUSTER_POSITIVE_BONUS_KEY,
        alignment_rules[ALIGNMENT_POSITIVE_BONUS_BY_DOMINANCE_KEY][str(dominance_level)],
    )
    partial_penalty = _resolved_signal_int(
        signal,
        CLUSTER_PARTIAL_PENALTY_KEY,
        alignment_rules[ALIGNMENT_PARTIAL_PENALTY_BY_DOMINANCE_KEY][str(dominance_level)],
    )
    weak_penalty = _resolved_signal_int(
        signal,
        CLUSTER_WEAK_PENALTY_KEY,
        alignment_rules[ALIGNMENT_WEAK_PENALTY_BY_DOMINANCE_KEY][str(dominance_level)],
    )
    if dominant_alignment_score >= float(alignment_rules[ALIGNMENT_STRONG_THRESHOLD_KEY]):
        adjustment = positive_bonus
        alignment = ALIGNMENT_STRONG
    elif dominant_alignment_score >= float(alignment_rules[ALIGNMENT_PARTIAL_THRESHOLD_KEY]):
        adjustment = -partial_penalty
        alignment = ALIGNMENT_PARTIAL
    else:
        adjustment = -weak_penalty
        alignment = ALIGNMENT_WEAK

    label = _resolved_signal_text(signal, SIGNAL_FIT_LABEL_KEY, defaults)
    if not label:
        raise ValueError(
            f"competitive signal missing fit_label and no default available: {signal!r}"
        )
    return {
        SIGNAL_LABEL_KEY: label,
        SIGNAL_NAME_KEY: signal_name,
        SIGNAL_FIT_LABEL_KEY: _resolved_signal_text(signal, SIGNAL_FIT_LABEL_KEY, defaults),
        SIGNAL_WATCHOUT_LABEL_KEY: _resolved_signal_text(
            signal, SIGNAL_WATCHOUT_LABEL_KEY, defaults
        ),
        SIGNAL_RISK_LABEL_KEY: _resolved_signal_text(signal, SIGNAL_RISK_LABEL_KEY, defaults),
        SIGNAL_ALIASES_KEY: aliases,
        SIGNAL_DOMINANCE_LEVEL_KEY: dominance_level,
        SIGNAL_ALIGNMENT_KEY: alignment,
        SIGNAL_ADJUSTMENT_KEY: adjustment,
    }


def competitive_signal_assessments(record: dict, profile: Optional[dict] = None) -> List[dict]:
    existing = record.get(COMPETITIVE_SIGNALS_KEY)
    if isinstance(existing, list) and existing:
        defaults = _signal_defaults()
        sanitized: List[dict] = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            label = _resolved_signal_text(item, SIGNAL_FIT_LABEL_KEY, defaults)
            if not label:
                continue
            sanitized.append(
                {
                    SIGNAL_LABEL_KEY: label,
                    SIGNAL_NAME_KEY: _resolved_signal_text(item, SIGNAL_NAME_KEY, defaults),
                    SIGNAL_FIT_LABEL_KEY: _resolved_signal_text(
                        item, SIGNAL_FIT_LABEL_KEY, defaults
                    ),
                    SIGNAL_WATCHOUT_LABEL_KEY: _resolved_signal_text(
                        item, SIGNAL_WATCHOUT_LABEL_KEY, defaults
                    ),
                    SIGNAL_RISK_LABEL_KEY: _resolved_signal_text(
                        item, SIGNAL_RISK_LABEL_KEY, defaults
                    ),
                    SIGNAL_ALIASES_KEY: _normalized_aliases(
                        list(item.get(SIGNAL_ALIASES_KEY) or [])
                    ),
                    SIGNAL_DOMINANCE_LEVEL_KEY: int(item.get(SIGNAL_DOMINANCE_LEVEL_KEY, 1)),
                    SIGNAL_ALIGNMENT_KEY: _dedupe_key(
                        item.get(SIGNAL_ALIGNMENT_KEY) or ALIGNMENT_PARTIAL
                    ),
                    SIGNAL_ADJUSTMENT_KEY: int(item.get(SIGNAL_ADJUSTMENT_KEY, 0) or 0),
                }
            )
        if sanitized:
            return sanitized

    active_profile = profile or load_profile()
    details_text = build_scoring_source_text(record)
    signals = detect_competitive_signals(details_text, active_profile)
    return [evaluate_competitive_signal_alignment(signal, active_profile) for signal in signals]


def competitive_fit_highlights(record: dict, profile: Optional[dict] = None) -> List[str]:
    highlights: List[str] = []
    for signal in competitive_signal_assessments(record, profile):
        if int(signal.get(SIGNAL_ADJUSTMENT_KEY, 0)) > 0:
            highlights.append(f"{signal[SIGNAL_LABEL_KEY]} ✓")
    return dedupe_preserve_order(highlights)[:2]


def extract_skill_observations(record: dict, profile: Optional[dict] = None) -> List[dict]:
    """Return repeated capability-like signals from a kept role for review insights.

    These observations are intentionally conservative: we only emit positively aligned
    competitive signals from roles we already kept, so Suggested Tuning learns from
    viable roles rather than from noisy broad matches.
    """
    active_profile = profile or load_profile()
    observations: List[dict] = []
    seen: Set[str] = set()
    for signal in competitive_signal_assessments(record, active_profile):
        if int(signal.get(SIGNAL_ADJUSTMENT_KEY, 0) or 0) <= 0:
            continue
        skill = signal[SIGNAL_LABEL_KEY]
        key = _dedupe_key(skill)
        if not key or key in seen:
            continue
        seen.add(key)
        observations.append(
            {
                OBSERVATION_SKILL_KEY: skill,
                RECORD_TITLE_KEY: record.get(RECORD_TITLE_KEY),
                RECORD_COMPANY_KEY: record.get(RECORD_COMPANY_KEY),
                RECORD_URL_KEY: record.get(RECORD_URL_KEY),
                RECORD_SEARCH_LOCATION_KEY: record.get(RECORD_SEARCH_LOCATION_KEY),
            }
        )
    return observations


def build_job_learning_signals(
    record: dict,
    skill_observations: List[dict],
    profile: Optional[dict] = None,
) -> List[dict[str, Any]]:
    pending: List[dict[str, Any]] = []
    seen: Set[str] = set()

    # 1. Process explicit observations (from existing clusters)
    for observation in skill_observations:
        _add_to_pending(
            observation.get(OBSERVATION_SKILL_KEY),
            CATEGORY_CAPABILITY_CONCEPT,
            record,
            pending,
            seen,
        )

    # 2. Discovery: scan for UNKNOWN skills in the description
    details_text = (
        record.get(RECORD_FULL_DESCRIPTION_KEY) or record.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""
    )
    if details_text:
        new_skills = _extract_capability_learning_signals(details_text, profile or load_profile())
        for skill in new_skills:
            _add_to_pending(skill, CATEGORY_CAPABILITY_CONCEPT, record, pending, seen)

    if details_text:
        for item in detect_cv_farming_signals(details_text, load_dodgy_job_rules()):
            sig = compact_whitespace(item.get(LEARNING_SIGNAL_KEY) or "")
            if not sig:
                continue
            sig_key = _dedupe_key(sig)
            if sig_key in seen:
                continue
            seen.add(sig_key)
            pending.append(
                {
                    LEARNING_SIGNAL_KEY: sig,
                    LEARNING_CATEGORY_KEY: item.get("suggested_category")
                    or CATEGORY_CV_FARMING_PATTERN,
                    LEARNING_SOURCE_KEY: SOURCE_JOB_PARSING,
                    LEARNING_CONTEXT_KEY: [
                        compact_whitespace(record.get(RECORD_TITLE_KEY) or ""),
                        compact_whitespace(record.get(RECORD_COMPANY_KEY) or ""),
                    ],
                    LEARNING_EVIDENCE_KEY: [compact_whitespace(item.get("evidence") or sig)],
                    LEARNING_NEEDS_REVIEW_KEY: True,
                    LEARNING_ORIGINAL_TEXTS_KEY: [
                        compact_whitespace(text)
                        for text in (item.get("original_texts") or [sig])
                        if compact_whitespace(text)
                    ],
                }
            )

    return pending


def _add_to_pending(
    value: str, category: str, record: dict, pending: list, seen: set, context: list = None
) -> None:
    val = compact_whitespace(value or "")
    key = _dedupe_key(val)
    if not val or key in seen:
        return
    seen.add(key)

    known_signal, knowledge_match = signal_in_approved_knowledge(category, val)
    if not known_signal:
        item = {
            LEARNING_SIGNAL_KEY: val,
            LEARNING_CATEGORY_KEY: category,
            LEARNING_SOURCE_KEY: SOURCE_JOB_PARSING,
            LEARNING_CONTEXT_KEY: context
            or [
                compact_whitespace(record.get(RECORD_TITLE_KEY) or ""),
                compact_whitespace(record.get(RECORD_COMPANY_KEY) or ""),
            ],
            LEARNING_EVIDENCE_KEY: [val],
            LEARNING_NEEDS_REVIEW_KEY: True,
        }
        if knowledge_match:
            item[LEARNING_KNOWLEDGE_MATCH_KEY] = knowledge_match
        pending.append(item)


def _extract_capability_learning_signals(text: str, profile: dict) -> List[str]:
    rules = load_parsing_rules()
    config = rules.get(PARSING_SKILL_DISCOVERY_CONFIG_KEY, {})
    junk = {
        _dedupe_key(item) for item in config.get(PARSING_JUNK_KEYWORDS_KEY, []) if _dedupe_key(item)
    }
    sw = set(rules.get(PARSING_STOPWORDS_KEY, []))

    tokens = [t for t in re.findall(r"[a-z]{3,}", text.lower()) if t not in sw and t not in junk]
    # Basic n-gram extraction (discovery only)
    max_discovery_terms = int(config.get(PARSING_MAX_DISCOVERY_TERMS_KEY, 10))
    return list(set(t for t in tokens if len(t) >= config.get(PARSING_MIN_TERM_LENGTH_KEY, 3)))[
        :max_discovery_terms
    ]


def hard_block_entries(record: dict, profile: Optional[dict] = None) -> List[dict]:
    existing = [
        compact_whitespace(item)
        for item in (record.get(HARD_BLOCK_REASONS_KEY) or [])
        if compact_whitespace(item)
    ]
    if existing:
        return [
            {HARD_BLOCK_TEXT_KEY: item, LEARNING_CATEGORY_KEY: CATEGORY_HARD_BLOCKER_PATTERN}
            for item in dedupe_preserve_order(existing)[:3]
        ]

    active_profile = profile or load_profile()
    cluster_by_name = {
        _dedupe_key(cluster.get(SIGNAL_NAME_KEY) or ""): cluster
        for cluster in active_profile.get(KEY_SIGNAL_CLUSTERS, [])
        if isinstance(cluster, dict) and _dedupe_key(cluster.get(SIGNAL_NAME_KEY) or "")
    }

    entries: List[dict] = []
    for assessment in competitive_signal_assessments(record, active_profile):
        cluster = cluster_by_name.get(_dedupe_key(assessment.get(SIGNAL_NAME_KEY) or ""))
        if not isinstance(cluster, dict) or not bool(
            cluster.get(CLUSTER_HARD_BLOCK_ON_MISMATCH_KEY)
        ):
            continue

        allowed_alignments = {
            compact_whitespace(str(value)).lower()
            for value in (
                cluster.get(CLUSTER_HARD_BLOCK_ALIGNMENT_LEVELS_KEY) or ["partial", "weak"]
            )
            if compact_whitespace(str(value))
        } or {"partial", "weak"}
        alignment = compact_whitespace(str(assessment.get(SIGNAL_ALIGNMENT_KEY) or "")).lower()
        if alignment not in allowed_alignments:
            continue

        text = compact_whitespace(
            cluster.get(CLUSTER_HARD_BLOCK_LABEL_KEY)
            or assessment.get(SIGNAL_WATCHOUT_LABEL_KEY)
            or assessment.get(SIGNAL_RISK_LABEL_KEY)
            or ""
        )
        if not text:
            continue
        entries.append(
            {HARD_BLOCK_TEXT_KEY: text, LEARNING_CATEGORY_KEY: CATEGORY_HARD_BLOCKER_PATTERN}
        )

    deduped: List[dict] = []
    seen_keys: Set[str] = set()
    for entry in entries:
        key = _dedupe_key(entry.get(LEARNING_CATEGORY_KEY) or entry.get(HARD_BLOCK_TEXT_KEY) or "")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(entry)
    return deduped[:3]


def hard_block_reasons(record: dict, profile: Optional[dict] = None) -> List[str]:
    return [entry[HARD_BLOCK_TEXT_KEY] for entry in hard_block_entries(record, profile)]
