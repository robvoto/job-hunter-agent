"""CV analysis pipeline for capability candidate diagnostics plus one label-only LLM pass.

This module orchestrates the processing of raw CV text through a multi-stage pipeline
to extract structured information. It performs deterministic extraction of roles,
phrases, and clusters, followed by an optional LLM pass for renaming top clusters.

Key functionalities include:
- Parsing roles and extracting structured role lists from CV text.
- Extracting n-gram phrases from bullet points.
- Clustering similar phrases using Jaccard similarity.
- Scoring and promoting clusters into strength bands.
- Renaming top clusters using an LLM for improved readability and consistency.

Produces the deterministic review fields from raw CV text:
  dominant_signal_clusters and must_not_require_skills.

Layers:
  A - extract source groups from raw CV text
  B - extract_phrases: bigrams/trigrams from bullets
  C - cluster_phrases: Jaccard-based phrase grouping
  D - score_and_promote: score clusters into strength bands
  LLM - rename top cluster seeds only
"""

import logging
import re
from collections import defaultdict
from typing import Any

from job_hunter_agent.capability_matrix import (
    derive_job_description_aliases,
)
from job_hunter_agent.global_settings import (
    KEY_CAPABILITY_ALIAS_LIMIT,
    KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS,
    KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS,
    KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS,
    get_llm_capability_naming_aliases_max_items,
)
from job_hunter_agent.profile_learning import (
    _CURRENT_YEAR,
    _cap_log,
    _clean_line,
    _is_bullet_line,
    _is_heading_line,
    _normalize_phrase,
    _normalize_token,
    get_parsing_rule_set,
    repair_text,
)
from job_hunter_agent.profile_store import (
    KEY_MUST_NOT_REQUIRED_SKILLS,
    KEY_SIGNAL_CLUSTERS,
    normalize_onboarding_settings,
)

logger = logging.getLogger(__name__)


def _stopwords() -> set[str]:
    return get_parsing_rule_set("stopwords")


def _is_quality_phrase(text: str) -> bool:
    cleaned = _normalize_phrase(text)
    if not cleaned:
        return False
    tokens = cleaned.split()
    if not tokens:
        return False
    if all(t in _stopwords() for t in tokens):
        return False
    return True


def _format_cv_pipeline_summary(
    source_groups: int,
    phrases: int,
    clusters: int,
    candidates: int,
    dominant: int,
) -> str:
    lines = [
        "[CV_PIPELINE]",
        f"  source groups: {source_groups}",
        f"  phrases: {phrases}",
        f"  clusters: {clusters}",
        f"  candidates: {candidates}",
        f"  capability candidates: {dominant} (evidence/review only)",
    ]
    return "\n".join(lines)


_TOOL_LINE_RE = re.compile(
    r"^(?:tools?|tools\s+and\s+platforms?|tools\s+and\s+practices)(?:\s+included|\s+include)?\s*:?\s*(?P<body>.+)$",
    flags=re.IGNORECASE,
)


def _strip_bullet_prefix(text: str) -> str:
    return re.sub(r"^[\-\*\u2022\u2013\u2014]+\s*", "", str(text or "").lstrip()).strip()


def _source_groups_from_cv_text(cv_text: str) -> list[dict[str, Any]]:
    source_groups: list[dict[str, Any]] = []
    current_label = "source"
    current_bullets: list[str] = []

    def flush_group() -> None:
        if current_bullets:
            source_groups.append(
                {
                    "label": current_label,
                    "bullets": list(current_bullets),
                }
            )

    for line in cv_text.splitlines():
        raw_line = line.strip()
        cleaned = _clean_line(raw_line)
        if not cleaned:
            continue
        if _is_heading_line(raw_line):
            flush_group()
            current_bullets.clear()
            current_label = cleaned.lower() or "source"
            continue
        if _is_bullet_line(raw_line):
            current_bullets.append(_strip_bullet_prefix(raw_line))
            continue
        if _TOOL_LINE_RE.match(cleaned):
            current_bullets.append(cleaned)

    flush_group()
    return source_groups


def _tool_terms(text: str) -> list[str]:
    match = _TOOL_LINE_RE.match(str(text or "").strip())
    if not match:
        return []

    body = str(match.group("body") or "").strip().rstrip(".")
    if not body:
        return []

    raw_parts = [part.strip() for part in re.split(r",|;", body) if part.strip()]
    terms: list[str] = []
    for raw_part in raw_parts:
        cleaned_part = re.sub(r"\([^)]*\)", "", raw_part).strip()
        if not cleaned_part:
            continue
        pieces = [
            piece.strip()
            for piece in re.split(r"\s*[&/]\s*|\s+and\s+", cleaned_part)
            if piece.strip()
        ]
        for piece in pieces or [cleaned_part]:
            tokens = [
                t
                for t in (
                    _normalize_token(token)
                    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/-]*", piece)
                )
                if t and len(t) > 1 and t not in _stopwords()
            ]
            if not tokens:
                continue
            term = " ".join(tokens[:4]).strip()
            if term and _is_quality_phrase(term):
                terms.append(term)
    return list(dict.fromkeys(terms))


def _ngrams(text: str, excluded_tokens: set[str] | None = None) -> list[str]:
    blocked = excluded_tokens or set()
    sw = _stopwords()
    tokens = [
        t
        for t in (
            _normalize_token(token) for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/-]*", text)
        )
        if t and len(t) > 1 and t not in sw and t not in blocked
    ]
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(len(tokens) - size + 1):
            phrase = _normalize_phrase(" ".join(tokens[index : index + size]))
            if phrase and _is_quality_phrase(phrase):
                phrases.append(phrase)
    return list(dict.fromkeys(phrases))


def extract_phrases(source_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phrase_items: list[dict[str, Any]] = []
    for index, group in enumerate(source_groups):
        source_label = str(group.get("label") or "source").strip().lower() or "source"
        role_key = f"{source_label}|{index}"
        for bullet in group.get("bullets", []):
            tool_terms = _tool_terms(bullet)
            for phrase in tool_terms:
                phrase_items.append(
                    {
                        "phrase": phrase,
                        "role_title": source_label,
                        "role_key": role_key,
                        "end_year": 0,
                        "duration_months": 0,
                        "is_recent": False,
                        "is_current": False,
                    }
                )
            for phrase in _ngrams(bullet):
                phrase_items.append(
                    {
                        "phrase": phrase,
                        "role_title": source_label,
                        "role_key": role_key,
                        "end_year": 0,
                        "duration_months": 0,
                        "is_recent": False,
                        "is_current": False,
                    }
                )
    return phrase_items


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def cluster_phrases(phrase_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "occurrences": 0,
            "_internal_roles": set(),
            "_internal_role_meta": {},
            "_internal_recent_hits": 0,
            "_internal_current_hits": 0,
        }
    )
    for item in phrase_items:
        phrase = item["phrase"]
        aggregate = aggregates[phrase]
        aggregate["occurrences"] += 1
        aggregate["_internal_roles"].add(item["role_title"])
        role_key = str(item.get("role_key") or item["role_title"])
        role_meta = aggregate["_internal_role_meta"].setdefault(
            role_key,
            {
                "end_year": int(item.get("end_year") or 0),
                "duration_months": max(int(item.get("duration_months") or 0), 0),
                "is_recent": bool(item.get("is_recent")),
                "is_current": bool(item.get("is_current")),
            },
        )
        role_meta["end_year"] = max(
            int(role_meta.get("end_year") or 0), int(item.get("end_year") or 0)
        )
        role_meta["duration_months"] = max(
            int(role_meta.get("duration_months") or 0),
            max(int(item.get("duration_months") or 0), 0),
        )
        role_meta["is_recent"] = bool(role_meta.get("is_recent")) or bool(item.get("is_recent"))
        role_meta["is_current"] = bool(role_meta.get("is_current")) or bool(item.get("is_current"))
        if item["is_recent"]:
            aggregate["_internal_recent_hits"] += 1
        if item.get("is_current"):
            aggregate["_internal_current_hits"] += 1

    sorted_phrases = sorted(
        aggregates.items(),
        key=lambda item: (-int(item[1]["occurrences"]), item[0]),
    )

    clusters: list[dict[str, Any]] = []
    token_sets: list[set[str]] = []

    for phrase, stats in sorted_phrases:
        tokens = set(phrase.split())
        best_index = -1
        best_score = 0.0
        for index, token_set in enumerate(token_sets):
            score = _jaccard(tokens, token_set)
            if score >= 0.40 and score > best_score:
                best_index = index
                best_score = score

        if best_index >= 0:
            cluster = clusters[best_index]
            cluster["aliases"].append(phrase)
            cluster["occurrences"] += int(stats["occurrences"])
            cluster["_internal_roles"].update(stats["_internal_roles"])
            for role_key, role_meta in stats["_internal_role_meta"].items():
                existing_meta = cluster["_internal_role_meta"].setdefault(
                    role_key,
                    {
                        "end_year": 0,
                        "duration_months": 0,
                        "is_recent": False,
                        "is_current": False,
                    },
                )
                existing_meta["end_year"] = max(
                    int(existing_meta.get("end_year") or 0),
                    int(role_meta.get("end_year") or 0),
                )
                existing_meta["duration_months"] = max(
                    int(existing_meta.get("duration_months") or 0),
                    int(role_meta.get("duration_months") or 0),
                )
                existing_meta["is_recent"] = bool(existing_meta.get("is_recent")) or bool(
                    role_meta.get("is_recent")
                )
                existing_meta["is_current"] = bool(existing_meta.get("is_current")) or bool(
                    role_meta.get("is_current")
                )
            cluster["_internal_recent_hits"] += int(stats["_internal_recent_hits"])
            cluster["_internal_current_hits"] += int(stats["_internal_current_hits"])
            token_sets[best_index].update(tokens)
            continue

        clusters.append(
            {
                "seed": phrase,
                "aliases": [],
                "occurrences": int(stats["occurrences"]),
                "_internal_roles": set(stats["_internal_roles"]),
                "_internal_role_meta": dict(stats["_internal_role_meta"]),
                "_internal_recent_hits": int(stats["_internal_recent_hits"]),
                "_internal_current_hits": int(stats["_internal_current_hits"]),
            }
        )
        token_sets.append(tokens)

    for cluster in clusters:
        role_meta = list(cluster["_internal_role_meta"].values())
        cluster["role_count"] = len(cluster["_internal_roles"])
        cluster["recent_role_count"] = int(cluster["_internal_recent_hits"])
        cluster["most_recent_year"] = max(
            (int(item.get("end_year") or 0) for item in role_meta), default=0
        )
        cluster["total_duration_months"] = sum(
            max(int(item.get("duration_months") or 0), 0) for item in role_meta
        )

    clusters.sort(key=lambda item: (-int(item["occurrences"]), item["seed"]))
    return clusters


def _score(cluster: dict[str, Any]) -> float:
    occurrences = int(cluster["occurrences"])
    recurrence = min(occurrences / 10.0, 1.0)
    breadth = min(int(cluster["role_count"]) / 5.0, 1.0)
    recency = int(cluster["recent_role_count"]) / max(occurrences, 1)
    current_depth = min(int(cluster.get("total_duration_months") or 0) / 72.0, 1.0)
    return recurrence * 0.30 + breadth * 0.25 + recency * 0.25 + current_depth * 0.20


def _classify_cluster_level(
    cluster: dict[str, Any], onboarding_settings: dict[str, Any] | None = None
) -> str:
    settings = normalize_onboarding_settings(onboarding_settings)
    total_duration_months = max(int(cluster.get("total_duration_months") or 0), 0)
    most_recent_year = int(cluster.get("most_recent_year") or 0)
    years_since_last_use = max(_CURRENT_YEAR - most_recent_year, 0) if most_recent_year else 99
    is_recent = years_since_last_use <= int(settings["capability_recent_years"])

    if (
        is_recent
        and years_since_last_use <= int(settings["capability_strong_max_years_since_use"])
        and total_duration_months >= int(settings["capability_strong_min_months"])
    ):
        return "strong"
    if years_since_last_use <= int(
        settings["capability_working_max_years_since_use"]
    ) and total_duration_months >= int(settings["capability_working_min_months"]):
        return "working"
    if total_duration_months >= int(
        settings["capability_working_long_history_min_months"]
    ) and years_since_last_use <= int(
        settings["capability_working_long_history_max_years_since_use"]
    ):
        return "working"
    return "basic"


def score_and_promote(
    clusters: list[dict[str, Any]],
    onboarding_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for cluster in clusters:
        score = _score(cluster)
        occurrences = int(cluster["occurrences"])
        breadth = min(int(cluster["role_count"]) / 5.0, 1.0)
        recency_ratio = int(cluster["recent_role_count"]) / max(occurrences, 1)
        total_duration_months = max(int(cluster.get("total_duration_months") or 0), 0)
        most_recent_year = int(cluster.get("most_recent_year") or 0)
        years_since_last_use = max(_CURRENT_YEAR - most_recent_year, 0) if most_recent_year else 99

        scored.append(
            {
                **cluster,
                "score": round(score, 3),
                "level": _classify_cluster_level(cluster, onboarding_settings),
                "name": cluster["seed"],
                "fit_label": "",
                "watchout_label": "",
                "_internal_breadth": round(breadth, 3),
                "_internal_recency_ratio": round(recency_ratio, 3),
                "_internal_years_since_last_use": years_since_last_use,
                "_internal_total_duration_months": total_duration_months,
            }
        )

    scored.sort(key=lambda item: (-float(item["score"]), item["seed"]))
    return scored


def _rename_top_clusters(
    candidates: list[dict[str, Any]], llm_client: Any = None
) -> list[dict[str, Any]]:
    try:
        from job_hunter_agent.llm_gate import name_capability_clusters
    except ImportError:
        return candidates

    if not candidates:
        return candidates

    top = candidates[:20]
    try:
        labels = name_capability_clusters(
            [
                {
                    "name": item["seed"],
                    "aliases": item["aliases"][: get_llm_capability_naming_aliases_max_items()],
                }
                for item in top
            ],
            llm_client=llm_client,
        )
        if not labels:
            return candidates
    except Exception as exc:
        logger.warning("CV pipeline LLM enrichment failed: %s", exc)
        return candidates

    renamed_top: list[dict[str, Any]] = []
    for index, item in enumerate(top):
        renamed = dict(item)
        if index < len(labels):
            label = str(labels[index]).strip().lower()
            if label:
                renamed["name"] = label
        renamed_top.append(renamed)
    return renamed_top + candidates[len(top) :]


def _build_output(
    candidates: list[dict[str, Any]],
    total_roles: int = 0,
    onboarding_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn extracted capability candidates into persisted profile learning output."""
    settings = normalize_onboarding_settings(onboarding_settings)
    dominant_signal_clusters: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for candidate in candidates:
        display_name = str(candidate["name"] or "").strip()
        if not display_name:
            continue
        display_name = re.sub(r"\s+", " ", display_name).strip()
        if len(display_name) > 120:
            continue
        matching_aliases = derive_job_description_aliases(
            display_name,
            [candidate["seed"], *candidate["aliases"]],
            max_aliases=int(settings[KEY_CAPABILITY_ALIAS_LIMIT]),
        )
        if not isinstance(matching_aliases, list):
            matching_aliases = []
        clean_aliases: list[str] = []
        seen_aliases: set[str] = set()
        display_name_norm = display_name.lower()
        for alias in matching_aliases:
            cleaned_alias = re.sub(r"\s+", " ", str(alias or "")).strip()
            if not cleaned_alias or len(cleaned_alias) > 120:
                continue
            alias_norm = cleaned_alias.lower()
            if alias_norm == display_name_norm or alias_norm in seen_aliases:
                continue
            seen_aliases.add(alias_norm)
            clean_aliases.append(cleaned_alias)

        if not display_name_norm or display_name_norm in seen_names:
            continue
        seen_names.add(display_name_norm)

        signal_aliases = clean_aliases[:]
        if len(signal_aliases) < 2:
            signal_aliases = list(dict.fromkeys([display_name, *signal_aliases]))
        dominant_signal_clusters.append(
            {
                "name": display_name,
                "aliases": signal_aliases[: int(settings[KEY_CAPABILITY_ALIAS_LIMIT])],
                "level": candidate["level"],
                "fit_label": candidate["fit_label"],
                "watchout_label": candidate["watchout_label"],
                "min_alias_hits": int(settings[KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS]),
                "min_snippet_hits": int(settings[KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS]),
                "dense_snippet_alias_hits": int(
                    settings[KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS]
                ),
                "needs_review": True,
            }
        )

    return {
        KEY_SIGNAL_CLUSTERS: dominant_signal_clusters,
        KEY_MUST_NOT_REQUIRED_SKILLS: [],
    }


def _strip_internal_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_internal_keys(item)
            for key, item in value.items()
            if not str(key).startswith("_internal")
        }
    if isinstance(value, list):
        return [_strip_internal_keys(item) for item in value]
    return value


def run_cv_pipeline(
    cv_text: str,
    llm_client: Any = None,
    onboarding_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = repair_text(cv_text)
    if not text:
        return {}

    source_groups = _source_groups_from_cv_text(text)
    phrase_items = extract_phrases(source_groups)
    clusters = cluster_phrases(phrase_items)
    candidates = score_and_promote(clusters, onboarding_settings=onboarding_settings)
    candidates = _rename_top_clusters(candidates, llm_client=llm_client)
    output = _build_output(
        candidates, total_roles=len(source_groups), onboarding_settings=onboarding_settings
    )

    capability_candidates = output.get("dominant_signal_clusters", [])
    _cap_log(
        _format_cv_pipeline_summary(
            len(source_groups),
            len(phrase_items),
            len(clusters),
            len(candidates),
            len(capability_candidates),
        )
    )
    if capability_candidates:
        _cap_log(
            f"[CV_PIPELINE] capability candidate names: {[r['name'] for r in capability_candidates]}"
        )
    return _strip_internal_keys(output)
