import re
from typing import Any, List, Optional, Set

from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.capability_matching import (
    _normalized_aliases,
    evidence_tier_alignment_score,
)
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.profile_learning import _role_title_review_token
from job_hunter_agent.profile_store import load_profile
from job_hunter_agent.role_analysis import text_contains_term
from job_hunter_agent.role_analysis import _load_government_context_rules
from job_hunter_agent.scoring_utils import build_scoring_source_text, profile_recency_multiplier
from job_hunter_agent.signal_registry import load_approved_signal_catalog, signal_in_approved_knowledge
from job_hunter_agent.text_processing import (
    compact_whitespace,
    dedupe_preserve_order,
    split_text_snippets,
)


def _capability_rule_strength(rule: dict) -> float:
    level = compact_whitespace(rule.get("level") or "").lower()
    level_map = {
        "strong": 1.0,
        "working": 0.72,
        "basic": 0.55,
        "low": 0.22,
    }
    return max(min(level_map.get(level, 0.45), 1.0), 0.0)


def detect_competitive_signals(details_text: str, profile: Optional[dict] = None) -> List[dict]:
    active_profile = profile or load_profile()
    source_text = compact_whitespace(details_text).lower()
    snippets = [snippet.lower() for snippet in split_text_snippets(details_text)]
    if not source_text:
        return []

    detected: List[dict] = []
    for raw_cluster in active_profile.get("dominant_signal_clusters", []):
        if not isinstance(raw_cluster, dict):
            continue
        canonical = compact_whitespace(raw_cluster.get("name") or "").lower()
        aliases = [canonical] if canonical else []
        if not aliases:
            continue

        matched_aliases = [alias for alias in aliases if text_contains_term(source_text, alias)]
        if len(matched_aliases) < 1:
            continue

        snippet_hits = 0
        max_aliases_in_snippet = 0
        for snippet in snippets:
            alias_hits_in_snippet = sum(1 for alias in matched_aliases if text_contains_term(snippet, alias))
            max_aliases_in_snippet = max(max_aliases_in_snippet, alias_hits_in_snippet)
            if alias_hits_in_snippet > 0:
                snippet_hits += 1
        min_snippet_hits = int(raw_cluster.get("min_snippet_hits", 2) or 2)
        dense_snippet_alias_hits = int(raw_cluster.get("dense_snippet_alias_hits", 4) or 4)
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
                "name": compact_whitespace(raw_cluster.get("name") or "domain specialist track"),
                "fit_label": compact_whitespace(raw_cluster.get("fit_label") or ""),
                "watchout_label": compact_whitespace(raw_cluster.get("watchout_label") or ""),
                "risk_label": compact_whitespace(raw_cluster.get("risk_label") or raw_cluster.get("watchout_label") or ""),
                "aliases": matched_aliases,
                "alias_hits": len(matched_aliases),
                "snippet_hits": snippet_hits,
                "dominance_level": min(dominance_level, 3),
            }
        )

    detected.sort(key=lambda item: (-int(item.get("dominance_level", 0)), -int(item.get("alias_hits", 0)), item.get("name", "")))
    return detected[:3]


def evaluate_competitive_signal_alignment(signal: dict, profile: dict) -> dict:
    aliases = _normalized_aliases([signal.get("name") or ""])
    capability_best = 0.0

    for rule in profile.get("capability_profile_rules", []):
        if not isinstance(rule, dict):
            continue
        canonical = canonical_capability_term(rule)
        rule_aliases = _normalized_aliases([canonical])
        if not canonical:
            continue
        overlap = sum(1 for alias in aliases if alias in rule_aliases or any(alias in rule_alias or rule_alias in alias for rule_alias in rule_aliases))
        if overlap <= 0:
            continue
        rule_strength = _capability_rule_strength(rule)
        capability_best = max(capability_best, min(rule_strength + (0.05 * min(overlap - 1, 2)), 1.05))

    tiered_evidence_score = evidence_tier_alignment_score(profile, aliases)
    recency_multiplier = profile_recency_multiplier(profile, aliases)
    if recency_multiplier == 0.0 and capability_best >= 0.9:
        recency_multiplier = 0.75

    dominant_alignment_score = max(
        capability_best * (recency_multiplier or 1.0),
        tiered_evidence_score,
    )

    dominance_level = int(signal.get("dominance_level", 1) or 1)
    positive_bonus = int(signal.get("positive_bonus", min(1 + dominance_level, 2)) or min(1 + dominance_level, 2))
    partial_penalty = int(signal.get("partial_penalty", 3 + (dominance_level * 2)) or 3 + (dominance_level * 2))
    weak_penalty = int(signal.get("weak_penalty", 4 + (dominance_level * 2)) or 4 + (dominance_level * 2))
    if dominant_alignment_score >= 0.78:
        adjustment = positive_bonus
        alignment = "strong"
    elif dominant_alignment_score >= 0.42:
        adjustment = -partial_penalty
        alignment = "partial"
    else:
        adjustment = -weak_penalty
        alignment = "weak"

    return {
        "name": signal.get("name") or "domain specialist track",
        "fit_label": signal.get("fit_label") or signal.get("name") or "specialist context",
        "watchout_label": signal.get("watchout_label") or f"Role leans toward {signal.get('name') or 'specialist depth'}",
        "risk_label": signal.get("risk_label") or f"Role leans toward {signal.get('name') or 'specialist depth'}",
        "aliases": aliases,
        "dominance_level": dominance_level,
        "alignment": alignment,
        "adjustment": adjustment,
    }


def competitive_signal_assessments(record: dict, profile: Optional[dict] = None) -> List[dict]:
    existing = record.get("competitive_signals")
    if isinstance(existing, list) and existing:
        sanitized: List[dict] = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            sanitized.append(
                {
                    "name": compact_whitespace(item.get("name") or "domain specialist track"),
                    "fit_label": compact_whitespace(item.get("fit_label") or item.get("name") or ""),
                    "watchout_label": compact_whitespace(item.get("watchout_label") or ""),
                    "risk_label": compact_whitespace(item.get("risk_label") or item.get("watchout_label") or ""),
                    "aliases": _normalized_aliases(list(item.get("aliases") or [])),
                    "dominance_level": int(item.get("dominance_level", 1) or 1),
                    "alignment": compact_whitespace(item.get("alignment") or "partial").lower(),
                    "adjustment": int(item.get("adjustment", 0) or 0),
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
        if int(signal.get("adjustment", 0)) > 0:
            fit_label = compact_whitespace(signal.get("fit_label") or signal.get("name") or "")
            if fit_label:
                highlights.append(f"{fit_label} ✓")
    return dedupe_preserve_order(highlights)[:2]


def extract_skill_observations(record: dict, details_text: str, profile: Optional[dict] = None) -> List[dict]:
    """Return repeated capability-like signals from a kept role for review insights.

    These observations are intentionally conservative: we only emit positively aligned
    competitive signals from roles we already kept, so Suggested Tuning learns from
    viable roles rather than from noisy broad matches.
    """
    active_profile = profile or load_profile()
    observations: List[dict] = []
    seen: Set[str] = set()
    for signal in competitive_signal_assessments(record, active_profile):
        if int(signal.get("adjustment", 0) or 0) <= 0:
            continue
        skill = compact_whitespace(signal.get("fit_label") or signal.get("name") or "")
        key = skill.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        observations.append(
            {
                "skill": skill,
                "title": record.get("title"),
                "company": record.get("company"),
                "url": record.get("url"),
                "search_location": record.get("search_location"),
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

    for observation in skill_observations:
        skill = compact_whitespace(observation.get("skill") or "")
        normalized_skill = skill.lower()
        if not skill or not normalized_skill or normalized_skill in seen:
            continue
        seen.add(normalized_skill)
        known_signal, knowledge_match = signal_in_approved_knowledge("capability_concept", skill)
        if known_signal:
            continue
        item: dict[str, Any] = {
            "signal": skill,
            "category": "capability_concept",
            "source": "job parsing",
            "context": [
                compact_whitespace(record.get("title") or ""),
                compact_whitespace(record.get("company") or ""),
            ],
            "evidence": [skill],
            "needs_review": True,
        }
        if knowledge_match:
            item["knowledge_match"] = knowledge_match
        pending.append(item)

    government_signals = _extract_government_context_learning_signals(record)
    for item in government_signals:
        key = compact_whitespace(item.get("signal") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        pending.append(item)

    title_reason = compact_whitespace(record.get("title_reason") or "").upper()
    if title_reason == "TITLE_POTENTIAL_MATCH":
        title = compact_whitespace(record.get("title") or "")
        review_token = _role_title_review_token(title)
        if review_token:
            known_signal, knowledge_match = signal_in_approved_knowledge("role_title_token", review_token)
            if not known_signal:
                item = {
                    "signal": review_token,
                    "category": "role_title_token",
                    "source": "job parsing",
                    "context": [title],
                    "evidence": [title],
                    "needs_review": True,
                }
                if knowledge_match:
                    item["knowledge_match"] = knowledge_match
                pending.append(item)

    return pending


def _extract_government_context_learning_signals(record: dict) -> List[dict[str, Any]]:
    sources = [
        compact_whitespace(record.get("company") or ""),
        compact_whitespace(record.get("title") or ""),
        compact_whitespace(record.get("full_description") or record.get("fit_source_text") or ""),
    ]
    combined = "\n".join(item for item in sources if item)
    lowered = combined.lower()
    if not lowered:
        return []

    try:
        _, false_positive_patterns = _load_government_context_rules()
    except Exception:
        false_positive_patterns = ()
    for pattern in false_positive_patterns:
        lowered = re.sub(pattern, " ", lowered)

    signals: List[dict[str, Any]] = []
    seen: Set[str] = set()

    def add_signal(value: str, original_text: str | None = None) -> None:
        cleaned = compact_whitespace(value).lower()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        known_signal, knowledge_match = signal_in_approved_knowledge("government_context", cleaned, [original_text] if original_text else None)
        if known_signal:
            return
        signal: dict[str, Any] = {
            "signal": cleaned,
            "original_texts": [original_text or cleaned],
            "suggested_category": "government_context",
            "source": "job parsing",
            "needs_review": True,
        }
        if knowledge_match:
            signal["knowledge_match"] = knowledge_match
        signals.append(signal)

    if re.search(r"\bgovernment\b", lowered):
        add_signal("government", "government")

    for match in re.finditer(r"\baps\s*([1-6])\b", lowered):
        level = match.group(1)
        add_signal(f"aps{level}", match.group(0))

    for match in re.finditer(r"\bel\s*([12])\b", lowered):
        level = match.group(1)
        add_signal(f"el{level}", match.group(0))

    for match in re.finditer(r"\b(?:baseline|nv\s*1|nv1|nv\s*2|nv2|negative vetting\s*1|negative vetting\s*2)\b", lowered):
        raw = compact_whitespace(match.group(0)).lower()
        if raw.startswith("negative vetting 1") or raw in {"nv1", "nv 1"}:
            add_signal("nv1", match.group(0))
        elif raw.startswith("negative vetting 2") or raw in {"nv2", "nv 2"}:
            add_signal("nv2", match.group(0))
        else:
            add_signal("baseline", match.group(0))

    department_pattern = re.compile(
        r"\bdepartment(?:\s+of)?\s+[a-z][a-z0-9&/-]*(?:\s+[a-z][a-z0-9&/-]*){1,7}\b",
        flags=re.IGNORECASE,
    )
    for line in lowered.splitlines():
        line = compact_whitespace(line)
        if not line or "department" not in line:
            continue
        for match in department_pattern.finditer(line):
            phrase = compact_whitespace(match.group(0))
            if len(phrase.split()) < 2 or len(phrase) > 80:
                continue
            add_signal(phrase, phrase)

    return signals


def hard_block_entries(record: dict, profile: Optional[dict] = None) -> List[dict]:
    existing = [
        compact_whitespace(item)
        for item in (record.get("hard_block_reasons") or [])
        if compact_whitespace(item)
    ]
    if existing:
        return [{"text": item, "category": ""} for item in dedupe_preserve_order(existing)[:3]]

    active_profile = profile or load_profile()
    cluster_by_name = {
        compact_whitespace(str(cluster.get("name") or "")).lower(): cluster
        for cluster in active_profile.get("dominant_signal_clusters", [])
        if isinstance(cluster, dict) and compact_whitespace(str(cluster.get("name") or ""))
    }

    entries: List[dict] = []
    for assessment in competitive_signal_assessments(record, active_profile):
        cluster = cluster_by_name.get(compact_whitespace(str(assessment.get("name") or "")).lower())
        if not isinstance(cluster, dict) or not bool(cluster.get("hard_block_on_mismatch")):
            continue

        allowed_alignments = {
            compact_whitespace(str(value)).lower()
            for value in (cluster.get("hard_block_alignment_levels") or ["partial", "weak"])
            if compact_whitespace(str(value))
        } or {"partial", "weak"}
        alignment = compact_whitespace(str(assessment.get("alignment") or "")).lower()
        if alignment not in allowed_alignments:
            continue

        text = compact_whitespace(
            cluster.get("hard_block_label")
            or assessment.get("watchout_label")
            or assessment.get("risk_label")
            or assessment.get("name")
            or ""
        )
        if not text:
            continue
        category = (
            compact_whitespace(str(cluster.get("name") or ""))
            .lower()
            .replace(" and ", "_")
            .replace(" ", "_")
        )
        entries.append({"text": text, "category": category})

    details_text = compact_whitespace(
        record.get("fit_source_text")
        or record.get("full_description")
        or ""
    )
    if details_text:
        profile_blockers = {
            compact_whitespace(str(skill)).lower()
            for skill in active_profile.get("must_not_require_skills", [])
            if compact_whitespace(str(skill)).lower()
        }
        seen_terms = {
            compact_whitespace(str(entry.get("text") or "")).lower()
            for entry in entries
            if compact_whitespace(str(entry.get("text") or "")).lower()
        }
        for match in find_hard_block_matches(details_text, active_profile.get("must_not_require_skills", [])):
            canonical = compact_whitespace(match.get("value") or "")
            matched_term = compact_whitespace(match.get("matched_term") or "")
            term_key = canonical.lower() or matched_term.lower()
            if not term_key or term_key in seen_terms or term_key in profile_blockers:
                continue
            entries.append({"text": canonical or matched_term, "category": "hard_blocker_pattern"})
            seen_terms.add(term_key)

    deduped: List[dict] = []
    seen_keys: Set[str] = set()
    for entry in entries:
        key = compact_whitespace(str(entry.get("category") or entry.get("text") or "")).lower()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(entry)
    return deduped[:3]


def hard_block_reasons(record: dict, profile: Optional[dict] = None) -> List[str]:
    return [entry["text"] for entry in hard_block_entries(record, profile)]
