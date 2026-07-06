"""Helpers for review insights."""

import re
from typing import Any

from job_hunter_agent.global_settings import (
    KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT,
    KEY_REVIEW_MAX_EXAMPLES_PER_SKILL,
    KEY_REVIEW_MAX_SAMPLES_PER_REJECTION,
    KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT,
    get_review_settings,
)
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.occupation_taxonomy import RESULT_UNCERTAIN
from job_hunter_agent.profile_store import (
    CAPABILITY_ICON_GENERIC,
    KEY_ALIASES,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_ICON_KEY,
    KEY_LEVEL,
    KEY_MUST_NOT_REQUIRED_SKILLS,
    KEY_NAME,
    VALID_CAPABILITY_ICON_KEYS,
)
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order


def _normalize_term(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _collect_known_terms(profile: dict[str, Any]) -> set[str]:
    known_terms = set()
    for skill in profile.get(KEY_MUST_NOT_REQUIRED_SKILLS, []):
        normalized = _normalize_term(str(skill))
        if normalized:
            known_terms.add(normalized)

    for rule in profile.get(KEY_CANDIDATE_CAPABILITIES, []):
        normalized_name = _normalize_term(str(rule.get(KEY_NAME) or ""))
        if normalized_name:
            known_terms.add(normalized_name)
        for alias in rule.get(KEY_ALIASES, []):
            normalized_alias = _normalize_term(str(alias))
            if normalized_alias:
                known_terms.add(normalized_alias)
    return known_terms


def build_unknown_skill_review(
    skill_observations: list[dict], profile: dict[str, Any]
) -> list[dict]:
    settings = get_review_settings()
    max_examples = settings[KEY_REVIEW_MAX_EXAMPLES_PER_SKILL]
    known_terms = _collect_known_terms(profile)
    grouped: dict[str, dict[str, Any]] = {}

    for observation in skill_observations:
        term = str(observation.get("skill") or "").strip()
        normalized = _normalize_term(term)
        if not term or not normalized or normalized in known_terms:
            continue
        entry = grouped.setdefault(
            normalized,
            {
                "skill": term,
                "count": 0,
                "examples": [],
            },
        )
        entry["count"] += 1
        if len(entry["examples"]) < max_examples:
            entry["examples"].append(
                {
                    "title": observation.get("title"),
                    "company": observation.get("company"),
                    "url": observation.get("url"),
                    "search_location": observation.get("search_location"),
                }
            )

    return sorted(grouped.values(), key=lambda item: (-item["count"], item["skill"].lower()))


def build_rejection_review(audit_rows: list[dict]) -> list[dict]:
    settings = get_review_settings()
    max_samples = settings[KEY_REVIEW_MAX_SAMPLES_PER_REJECTION]
    grouped: dict[str, dict[str, Any]] = {}
    for row in audit_rows:
        decision = row.get("decision")
        reason = row.get("reject_reason")
        if decision == "KEEP" or not reason:
            continue
        entry = grouped.setdefault(
            reason,
            {
                "reason": reason,
                "count": 0,
                "samples": [],
                "onet_results": [],
                "onet_result_counts": {},
            },
        )
        entry["count"] += 1
        onet = row.get("onet_classification")
        if isinstance(onet, dict):
            onet_result = str(onet.get("result") or "").strip().lower()
            if onet_result and onet_result not in entry["onet_results"]:
                entry["onet_results"].append(onet_result)
            if onet_result:
                entry["onet_result_counts"][onet_result] = (
                    int(entry["onet_result_counts"].get(onet_result, 0)) + 1
                )
        if len(entry["samples"]) < max_samples:
            entry["samples"].append(
                {
                    "title": row.get("title"),
                    "company": row.get("company"),
                    "url": row.get("url"),
                    "search_location": row.get("search_location"),
                    "location": row.get("location"),
                }
            )

    return sorted(grouped.values(), key=lambda item: (-item["count"], item["reason"]))


def _friendly_reason_suffix(value: str) -> str:
    cleaned = str(value or "").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _capability_rule_lookup(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for rule in profile.get(KEY_CANDIDATE_CAPABILITIES, []):
        if not isinstance(rule, dict):
            continue
        aliases = [rule.get(KEY_NAME), *(rule.get(KEY_ALIASES) or [])]
        for alias in aliases:
            normalized = _normalize_term(str(alias))
            if normalized:
                lookup[normalized] = rule
    return lookup


def _capability_rule_index_lookup(capability_rules: list[dict[str, Any]]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx, rule in enumerate(capability_rules):
        if not isinstance(rule, dict):
            continue
        aliases = [rule.get(KEY_NAME), *(rule.get(KEY_ALIASES) or [])]
        for alias in aliases:
            normalized = _normalize_term(str(alias))
            if normalized:
                lookup[normalized] = idx
    return lookup


def _choice_label(choice: str) -> str:
    rules = load_ui_labels()
    labels = rules.get("level_labels", {})
    return labels.get(choice, choice.replace("_", " ").strip().title())


def _current_rule_label(rule: dict[str, Any] | None) -> str:
    if not isinstance(rule, dict):
        return _choice_label("unclassified")
    level = str(rule.get(KEY_LEVEL) or "").strip().lower()
    if not level:
        return _choice_label("unclassified")
    return _choice_label(level)


_CAPABILITY_HIGHLIGHT_PREFIXES = (
    "strong capability match:",
    "capability match:",
)


def _skill_label_from_highlight(text: Any) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s*\u2713\s*$", "", cleaned).strip()
    lowered = cleaned.lower()
    for prefix in _CAPABILITY_HIGHLIGHT_PREFIXES:
        if lowered.startswith(prefix):
            return str(cleaned[len(prefix) :]).strip()
    return ""


def _collect_positive_skill_labels(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        label = str(value or "").strip()
        normalized = _normalize_term(label)
        if not label or not normalized or normalized in seen:
            return
        seen.add(normalized)
        labels.append(label)

    reviewed_matches = row.get("reviewed_signal_matches")
    if isinstance(reviewed_matches, dict):
        for bucket_name in ("matched", "evidence_only"):
            for item in reviewed_matches.get(bucket_name) or []:
                add(item)

    for signal in row.get("competitive_signals") or []:
        if not isinstance(signal, dict):
            continue
        if int(signal.get("adjustment", 0) or 0) <= 0:
            continue
        add(signal.get("fit_label") or signal.get("label"))

    for highlight in row.get("fit_highlights") or []:
        add(_skill_label_from_highlight(highlight))

    role_snapshot = row.get("role_snapshot")
    if isinstance(role_snapshot, str):
        add(_skill_label_from_highlight(role_snapshot))
    elif isinstance(role_snapshot, (list, tuple, set)):
        for item in role_snapshot:
            add(_skill_label_from_highlight(item))
    elif isinstance(role_snapshot, dict):
        for value in role_snapshot.values():
            add(_skill_label_from_highlight(value))

    return labels


def _observations_from_kept_row(row: dict[str, Any]) -> list[dict]:
    observations: list[dict] = []
    for skill in _collect_positive_skill_labels(row):
        observations.append(
            {
                "skill": skill,
                "title": row.get(RECORD_TITLE_KEY),
                "company": row.get(RECORD_COMPANY_KEY),
                "url": row.get(RECORD_URL_KEY),
                "search_location": row.get(RECORD_SEARCH_LOCATION_KEY),
            }
        )
    return observations


_REQUIREMENT_LABEL_PREFIXES = (
    "native or near-native level ",
    "native-level ",
    "minimum ",
    "at least ",
    "proven ",
    "strong ",
    "excellent ",
    "demonstrated ",
    "solid ",
    "practical ",
    "hands-on ",
    "working knowledge of ",
)

_REQUIREMENT_LABEL_SUFFIXES = (
    " required",
    " preferred",
    " preferred but not essential",
    " mandatory",
    " essential",
    " desired",
)


def _canonical_requirement_label(value: Any) -> str:
    cleaned = compact_whitespace(value)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for suffix in _REQUIREMENT_LABEL_SUFFIXES:
        if lowered.endswith(suffix):
            cleaned = compact_whitespace(cleaned[: -len(suffix)])
            lowered = cleaned.lower()
            break
    for prefix in _REQUIREMENT_LABEL_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = compact_whitespace(cleaned[len(prefix) :])
            lowered = cleaned.lower()
            break

    language_match = re.search(r"(?i)\b([a-z0-9&/+\- ]+? language proficiency)\b", cleaned)
    if language_match:
        cleaned = compact_whitespace(language_match.group(1))

    cleaned = re.sub(r"(?i)^\d+(?:-\d+)?\s+years?\s+of\s+", "", cleaned)
    cleaned = re.sub(r"(?i)^\d+(?:\.\d+)?\s+years?\s+of\s+", "", cleaned)
    cleaned = re.sub(r"(?i)^\d+(?:-\d+)?\s+years?\s+", "", cleaned)
    cleaned = compact_whitespace(cleaned.strip(" ,.;:-"))
    return cleaned


def _requirement_entry_from_label(label: str, source_requirement: str) -> tuple[str, str]:
    canonical = _canonical_requirement_label(label)
    if not canonical:
        return "", ""
    alias = compact_whitespace(source_requirement)
    return canonical, alias


def build_requirement_tuning_suggestions(
    audit_rows: list[dict], profile: dict[str, Any]
) -> list[dict]:
    settings = get_review_settings()
    min_count = settings[KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT]
    working_min_count = settings[KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT]
    max_examples = settings[KEY_REVIEW_MAX_EXAMPLES_PER_SKILL]
    known_terms = _collect_known_terms(profile)

    grouped: dict[str, dict[str, Any]] = {}
    for row in audit_rows:
        if not isinstance(row, dict) or row.get("decision") != "KEEP":
            continue
        row_seen: set[str] = set()
        for requirement in row.get("job_requirements") or []:
            label, alias = _requirement_entry_from_label(requirement, requirement)
            normalized = _normalize_term(label)
            if not label or not normalized or normalized in known_terms or normalized in row_seen:
                continue
            row_seen.add(normalized)
            entry = grouped.setdefault(
                normalized,
                {
                    "skill": label,
                    "count": 0,
                    "aliases": [],
                    "examples": [],
                },
            )
            entry["count"] += 1
            if alias:
                entry["aliases"].append(alias)
            if len(entry["examples"]) < max_examples:
                entry["examples"].append(
                    {
                        "title": row.get("title"),
                        "company": row.get("company"),
                        "url": row.get("url"),
                        "search_location": row.get("search_location"),
                    }
                )

    suggestions: list[dict[str, Any]] = []
    for normalized, entry in grouped.items():
        count = int(entry["count"] or 0)
        if count < min_count:
            continue
        skill = str(entry["skill"] or normalized).strip()
        recommended_choice = "working" if count >= working_min_count else "basic"
        suggestions.append(
            {
                "kind": "requirement",
                "skill": skill,
                "count": count,
                "headline": f"{skill} appears repeatedly in kept roles",
                "detail": f"Seen in {count} kept role(s) as an explicit requirement.",
                "target": "Capability matrix",
                "recommended_choice": recommended_choice,
                "recommended_label": _choice_label(recommended_choice),
                "prompt": f"{skill} is required in several kept roles. Do you have this capability?",
                "aliases": dedupe_preserve_order(entry["aliases"]),
                "examples": entry["examples"],
            }
        )

    return sorted(
        suggestions,
        key=lambda item: (-int(item["count"]), str(item["skill"]).lower()),
    )


def build_capability_tuning_suggestions(
    skill_observations: list[dict],
    audit_rows: list[dict],
    profile: dict[str, Any],
) -> list[dict]:
    settings = get_review_settings()
    min_count = settings[KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT]
    working_min_count = settings[KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT]
    max_examples = settings[KEY_REVIEW_MAX_EXAMPLES_PER_SKILL]

    row_by_url = {
        str(row.get("url") or "").strip(): row
        for row in audit_rows
        if str(row.get("url") or "").strip()
    }
    rule_lookup = _capability_rule_lookup(profile)
    grouped: dict[str, dict[str, Any]] = {}

    for observation in skill_observations:
        url = str(observation.get("url") or "").strip()
        row = row_by_url.get(url)
        if not isinstance(row, dict) or row.get("decision") != "KEEP":
            continue

        skill = str(observation.get("skill") or "").strip()
        normalized = _normalize_term(skill)
        if not normalized:
            continue
        entry = grouped.setdefault(
            normalized,
            {
                "skill": skill,
                "count": 0,
                "examples": [],
            },
        )
        entry["count"] += 1
        if len(entry["examples"]) < max_examples:
            entry["examples"].append(
                {
                    "title": observation.get("title"),
                    "company": observation.get("company"),
                    "url": observation.get("url"),
                    "search_location": observation.get("search_location"),
                }
            )

    suggestions: list[dict[str, Any]] = []
    for normalized, entry in grouped.items():
        count = int(entry["count"] or 0)
        if count < min_count:
            continue

        current_rule = rule_lookup.get(normalized)
        skill = str(entry["skill"] or normalized).strip()

        if current_rule:
            # Already classified - skip regardless of stored strength.
            # Once a user confirms a skill, don't keep nudging them to upgrade it.
            continue
        recommended_choice = "working" if count >= working_min_count else "basic"
        headline = f"Classify {skill} as a known capability signal"
        detail = f"Seen in {count} kept role(s) and still unclassified."

        suggestions.append(
            {
                "kind": "capability",
                "skill": skill,
                "count": count,
                "headline": headline,
                "detail": detail,
                "target": "Capability matrix",
                "recommended_choice": recommended_choice,
                "recommended_label": _choice_label(recommended_choice),
                "current_treatment": _current_rule_label(current_rule),
                "examples": entry["examples"],
            }
        )

    return sorted(
        suggestions,
        key=lambda item: (-int(item["count"]), str(item["skill"]).lower()),
    )


def _build_rule_tuning_suggestions_from_reviews(review_items: list[dict[str, Any]]) -> list[dict]:
    settings = get_review_settings()
    title_not_target_min = settings[KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT]
    rule_min = settings[KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT]

    suggestions: list[dict[str, Any]] = []
    for item in review_items:
        reason = str(item.get("reason") or "").strip()
        count = int(item.get("count") or 0)
        samples = item.get("samples") or []
        if reason == "ONET_FAR_OCCUPATION":
            if count < title_not_target_min:
                continue
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": "Broad capture is producing a lot of non-primary job titles",
                    "detail": f"{count} role(s) were filtered by title before deeper review.",
                    "target": "Search keywords and title matching",
                    "recommendation": "Keep search broad unless deeper review volume rises. Tighten title rules before tightening search keywords.",
                    "samples": samples,
                }
            )
            continue

        prefix, _, suffix = reason.partition(":")
        if prefix == "CARD_SPECIALIST" and count >= rule_min:
            domain = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Specialist {domain.lower()} roles are being filtered early",
                    "detail": f"{count} role(s) looked specialist-heavy enough to stop at the card gate.",
                    "target": "Specialist reject signals",
                    "recommendation": "Keep or refine this specialist-domain block if these remain off-target.",
                    "samples": samples,
                }
            )
        elif prefix == "DESC_CAPABILITY_LOW" and count >= rule_min:
            area = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Beginner-level capability repeated: {area}",
                    "detail": f"{count} role(s) leaned heavily into this capability track.",
                    "target": "Capability matrix or Requirement Exclusions",
                    "recommendation": "Keep this area in the background unless you want to exclude it explicitly in Requirement Exclusions.",
                    "samples": samples,
                }
            )
        elif prefix == "TITLE_BAD_KEYWORD" and count >= rule_min:
            keyword = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Title keyword filter is doing useful work: {keyword}",
                    "detail": f"{count} role(s) were blocked by this title keyword.",
                    "target": "Reject title rules",
                    "recommendation": "Keep this exclusion. Only widen it if close variants keep leaking through.",
                    "samples": samples,
                }
            )
        elif prefix == "DESC_MANDATORY_SKILL" and count >= rule_min:
            skill = _friendly_reason_suffix(suffix)
            suggestions.append(
                {
                    "kind": "rule",
                    "reason": reason,
                    "count": count,
                    "headline": f"Mandatory skill signal repeated: {skill}",
                    "detail": f"{count} role(s) required {skill} strongly enough to reject.",
                    "target": "Mandatory skills you do not have",
                    "recommendation": "Add this only if it becomes a recurring blocker for otherwise relevant roles.",
                    "samples": samples,
                }
            )

    return suggestions


def build_rule_tuning_suggestions(audit_rows: list[dict]) -> list[dict]:
    return _build_rule_tuning_suggestions_from_reviews(build_rejection_review(audit_rows))


def build_title_optimization_suggestions(audit_rows: list[dict]) -> list[dict]:
    settings = get_review_settings()
    min_count = settings[KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT]
    max_samples = settings[KEY_REVIEW_MAX_SAMPLES_PER_REJECTION]

    grouped: dict[str, dict[str, Any]] = {}
    for row in audit_rows:
        if not isinstance(row, dict) or row.get("decision") != "REJECT":
            continue
        onet = row.get("onet_classification") or {}
        if (
            not isinstance(onet, dict)
            or str(onet.get("result") or "").strip().lower() != RESULT_UNCERTAIN
        ):
            continue
        title = compact_whitespace(str(row.get(RECORD_TITLE_KEY) or ""))
        normalized = _normalize_term(title)
        if not title or not normalized:
            continue
        entry = grouped.setdefault(
            normalized,
            {
                "title": title,
                "count": 0,
                "samples": [],
            },
        )
        entry["count"] += 1
        if len(entry["samples"]) < max_samples:
            entry["samples"].append(
                {
                    "title": row.get("title"),
                    "company": row.get("company"),
                    "url": row.get("url"),
                    "search_location": row.get("search_location"),
                }
            )

    suggestions: list[dict[str, Any]] = []
    for normalized, entry in grouped.items():
        count = int(entry["count"] or 0)
        if count < min_count:
            continue
        title = str(entry["title"] or normalized).strip()
        suggestions.append(
            {
                "kind": "optimization",
                "reason": "ONET_UNCERTAIN_TITLE",
                "count": count,
                "headline": f"Repeated uncertain title: {title}",
                "detail": f"O*NET could not classify this title in {count} rejected role(s). Keep it as a softer optimise suggestion before hard blocking.",
                "target": "Optimisation rules",
                "recommendation": "Filter similar roles only if they keep coming back as poor fits.",
                "samples": entry["samples"],
            }
        )

    return sorted(
        suggestions,
        key=lambda item: (-int(item["count"]), str(item["headline"]).lower()),
    )


def build_suggested_tuning(
    audit_rows: list[dict],
    skill_observations: list[dict],
    profile: dict[str, Any],
) -> dict[str, Any]:
    capability_suggestions = build_capability_tuning_suggestions(
        skill_observations, audit_rows, profile
    )
    requirement_suggestions = build_requirement_tuning_suggestions(audit_rows, profile)
    optimization_suggestions = build_title_optimization_suggestions(audit_rows)
    rule_suggestions = build_rule_tuning_suggestions(audit_rows)
    return {
        "summary": {
            "capability_count": len(capability_suggestions),
            "requirement_count": len(requirement_suggestions),
            "optimization_count": len(optimization_suggestions),
            "rule_count": len(rule_suggestions),
        },
        "capability_suggestions": capability_suggestions,
        "requirement_suggestions": requirement_suggestions,
        "optimization_suggestions": optimization_suggestions,
        "rule_suggestions": rule_suggestions,
    }


def _kept_skill_observations_from_audit_rows(
    audit_rows: list[dict], _profile: dict[str, Any]
) -> list[dict]:
    observations: list[dict] = []
    for row in audit_rows:
        if not isinstance(row, dict) or row.get("decision") != "KEEP":
            continue
        observations.extend(_observations_from_kept_row(row))
    return observations


def build_review_data(
    audit_rows: list[dict], skill_observations: list[dict], profile: dict[str, Any]
) -> dict:
    kept_skill_observations = _kept_skill_observations_from_audit_rows(audit_rows, profile)
    kept_job_urls = sorted(
        {
            str(row.get("url") or "").strip()
            for row in audit_rows
            if row.get("decision") == "KEEP" and str(row.get("url") or "").strip()
        }
    )
    return {
        "suggested_tuning": build_suggested_tuning(audit_rows, kept_skill_observations, profile),
        "kept_job_urls": kept_job_urls,
        "skill_observations": kept_skill_observations,
        "unknown_skills": build_unknown_skill_review(kept_skill_observations, profile),
        "rejections_by_reason": build_rejection_review(audit_rows),
    }


def apply_capability_tuning_decisions(
    profile: dict[str, Any], decisions: list[dict[str, str]]
) -> dict[str, Any]:
    capability_rules = list(profile.get(KEY_CANDIDATE_CAPABILITIES, []))
    existing_index = _capability_rule_index_lookup(capability_rules)

    for item in decisions:
        skill = str(item.get("skill") or "").strip()
        choice = str(item.get("choice") or "").strip().lower()
        incoming_aliases = [
            str(alias).strip() for alias in (item.get(KEY_ALIASES) or []) if str(alias).strip()
        ]
        normalized = _normalize_term(skill)
        if not normalized or not choice:
            continue

        if choice not in {"strong", "working", "basic"}:
            continue
        level = choice

        rule = {
            KEY_NAME: skill,
            KEY_LEVEL: level,
            KEY_ALIASES: incoming_aliases,
        }

        if normalized in existing_index:
            existing_rule = capability_rules[existing_index[normalized]]
            merged_aliases: list[str] = []
            canonical_name = str(existing_rule.get(KEY_NAME) or skill).strip() or skill
            canonical_name_norm = _normalize_term(canonical_name)

            alias_candidates = [
                *incoming_aliases,
                *(existing_rule.get(KEY_ALIASES) or []),
            ]

            for alias in alias_candidates:
                cleaned_alias = str(alias or "").strip()
                if not cleaned_alias:
                    continue
                if _normalize_term(cleaned_alias) == canonical_name_norm:
                    continue
                if cleaned_alias not in merged_aliases:
                    merged_aliases.append(cleaned_alias)

            capability_rules[existing_index[normalized]] = {
                KEY_NAME: canonical_name,
                KEY_LEVEL: level,
                KEY_ALIASES: merged_aliases,
            }
            icon_key = str(existing_rule.get(KEY_ICON_KEY) or "").strip().lower()
            if icon_key not in VALID_CAPABILITY_ICON_KEYS:
                raise ValueError(
                    f"Capability {canonical_name!r} has missing or invalid icon_key: {icon_key!r}"
                )
            capability_rules[existing_index[normalized]][KEY_ICON_KEY] = icon_key
        else:
            rule[KEY_ICON_KEY] = CAPABILITY_ICON_GENERIC
            capability_rules.append(rule)
            existing_index[normalized] = len(capability_rules) - 1

    profile[KEY_CANDIDATE_CAPABILITIES] = capability_rules
    return profile
