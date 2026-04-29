"""CV analysis pipeline with deterministic extraction plus one label-only LLM pass.

Produces 3 profile fields from raw CV text:
  capability_profile_rules, dominant_signal_clusters, and must_not_require_skills.

Layers:
  A - parse_roles: extract structured role list
  B - extract_phrases: bigrams/trigrams from bullets
  C - cluster_phrases: Jaccard-based phrase grouping
  D - score_and_promote: score clusters into level/fit bands
  LLM - rename top cluster seeds only
"""

import re
from collections import defaultdict
from typing import Any

from job_hunter_agent.capability_matrix import choose_capability_name, derive_job_description_aliases
from job_hunter_agent.profile_learning import (
    _CURRENT_YEAR,
    _normalize_token,
    _normalize_phrase,
    _parse_role_entries,
    _resolve_extraction_lookback_years,
    repair_text,
)
from job_hunter_agent.profile_store import normalize_capability_rules

_STOPWORDS = {
    "a", "an", "and", "the", "to", "for", "of", "in", "on", "with", "by", "from", "into",
    "using", "use", "used", "within", "through", "under", "over", "per", "or", "as", "at",
    "is", "are", "was", "were", "be", "been", "being", "that", "this", "these", "those",
    "will", "would", "can", "could", "should", "may",
}
_GENERIC_ROLE_TOKENS = {
    "analyst", "manager", "coordinator", "consultant", "specialist", "developer", "engineer",
    "architect", "officer", "director", "administrator", "owner", "lead", "executive",
    "head", "staff", "master",
}
_TITLE_MODIFIER_TOKENS = {
    "senior", "lead", "principal", "technical", "functional", "digital", "delivery", "staff",
    "junior", "associate", "executive", "chief", "head", "contract", "consulting",
}
_PHRASE_BLOCKLIST = {
    "experience", "responsibility", "responsibilities", "project", "projects", "outcome",
    "outcomes", "profile", "professional experience", "tools", "technologies", "skills", "summary",
}


def _is_generic_title_phrase(text: str) -> bool:
    tokens = _normalize_phrase(text).split()
    return bool(tokens) and all(t in _TITLE_MODIFIER_TOKENS or t in _GENERIC_ROLE_TOKENS for t in tokens)


def _is_quality_phrase(text: str) -> bool:
    cleaned = _normalize_phrase(text)
    if not cleaned or cleaned in _PHRASE_BLOCKLIST:
        return False
    tokens = cleaned.split()
    if not tokens or len(tokens) > 4:
        return False
    if len(tokens) == 1 and len(tokens[0]) < 4:
        return False
    if all(t in _STOPWORDS for t in tokens):
        return False
    return True

_ACTION_VERBS = {
    "led", "lead", "managed", "manage", "delivered", "deliver",
    "designed", "design", "built", "build", "developed", "develop",
    "implemented", "implement", "established", "establish",
    "coordinated", "coordinate", "facilitated", "facilitate",
    "executed", "execute", "drove", "drive", "created", "create",
    "defined", "define", "analysed", "analyzed", "analyse", "analyze",
    "oversaw", "oversee", "maintained", "maintain", "launched", "launch",
    "improved", "improve", "streamlined", "streamline", "automated",
    "automate", "negotiated", "negotiate", "architected", "architect",
    "mentored", "mentor", "presented", "present", "deployed", "deploy",
}
_TOOL_LINE_RE = re.compile(
    r"^(?:tools?|tools\s+and\s+platforms?|tools\s+and\s+practices)(?:\s+included|\s+include)?\s*:?\s*(?P<body>.+)$",
    flags=re.IGNORECASE,
)
_WEAK_NAME_LEAD_TOKENS = _ACTION_VERBS | {
    "including",
    "multiple",
    "primary",
    "senior",
    "junior",
    "tool",
    "tools",
    "team",
    "teams",
    "external",
    "internal",
    "during",
    "through",
    "across",
    "compare",
    "check",
    "based",
}
_WEAK_NAME_TAIL_TOKENS = {
    "client",
    "clients",
    "environment",
    "external",
    "manager",
    "managers",
    "program",
    "programs",
    "service",
    "services",
    "technology",
    "vendor",
    "vendors",
}


def parse_roles(
    cv_text: str,
    onboarding_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    recent_cutoff = _CURRENT_YEAR - _resolve_extraction_lookback_years(onboarding_settings)
    for role in _parse_role_entries(cv_text):
        end_year = int(role.get("end_year") or 0)
        roles.append({
            "title": role.get("title", ""),
            "employer": role.get("employer", ""),
            "start_year": role.get("start_year"),
            "end_year": end_year,
            "is_recent": end_year >= recent_cutoff,
            "bullets": role.get("bullets", []),
        })
    return roles


def _has_action_verb(text: str) -> bool:
    tokens = {token.lower() for token in re.findall(r"[a-zA-Z]+", text)}
    return bool(tokens & _ACTION_VERBS)


def _tool_terms(text: str) -> list[str]:
    match = _TOOL_LINE_RE.match(str(text or "").strip())
    if not match:
        return []

    body = str(match.group("body") or "").strip().rstrip(".")
    if not body:
        return []

    raw_parts = [
        part.strip()
        for part in re.split(r",|;", body)
        if part.strip()
    ]
    terms: list[str] = []
    for raw_part in raw_parts:
        cleaned_part = re.sub(r"\([^)]*\)", "", raw_part).strip()
        if not cleaned_part:
            continue
        pieces = [
            piece.strip()
            for piece in re.split(r"\s*&\s*|\s+and\s+", cleaned_part)
            if piece.strip()
        ]
        for piece in pieces or [cleaned_part]:
            tokens = [_normalize_token(token) for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/-]*", piece)]
            tokens = [token for token in tokens if token and token not in _STOPWORDS]
            if not tokens:
                continue
            term = " ".join(tokens[:4]).strip()
            if term and _is_quality_phrase(term) and not _is_generic_title_phrase(term):
                terms.append(term)
    return list(dict.fromkeys(terms))


def _ngrams(text: str, excluded_tokens: set[str] | None = None) -> list[str]:
    blocked = excluded_tokens or set()
    tokens = [
        _normalize_token(token)
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/-]*", text)
        if _normalize_token(token) not in _STOPWORDS
        and _normalize_token(token) not in blocked
    ]
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(len(tokens) - size + 1):
            phrase = _normalize_phrase(" ".join(tokens[index:index + size]))
            if phrase and _is_quality_phrase(phrase) and not _is_generic_title_phrase(phrase):
                phrases.append(phrase)
    return list(dict.fromkeys(phrases))


def extract_phrases(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phrase_items: list[dict[str, Any]] = []
    for role in roles:
        title = role.get("title", "")
        is_recent = bool(role.get("is_recent"))
        employer_tokens = {
            _normalize_token(token)
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/-]*", str(role.get("employer", "")))
            if _normalize_token(token)
        }
        for bullet in role.get("bullets", []):
            has_action_verb = _has_action_verb(bullet)
            tool_terms = _tool_terms(bullet)
            for phrase in tool_terms:
                phrase_items.append({
                    "phrase": phrase,
                    "role_title": title,
                    "is_recent": is_recent,
                    "has_action_verb": False,
                })
            if tool_terms:
                continue
            for phrase in _ngrams(bullet, excluded_tokens=employer_tokens):
                phrase_items.append({
                    "phrase": phrase,
                    "role_title": title,
                    "is_recent": is_recent,
                    "has_action_verb": has_action_verb,
                })
    return phrase_items


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def cluster_phrases(phrase_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "occurrences": 0,
        "_internal_roles": set(),
        "_internal_recent_hits": 0,
        "_internal_action_hits": 0,
    })
    for item in phrase_items:
        phrase = item["phrase"]
        aggregate = aggregates[phrase]
        aggregate["occurrences"] += 1
        aggregate["_internal_roles"].add(item["role_title"])
        if item["is_recent"]:
            aggregate["_internal_recent_hits"] += 1
        if item["has_action_verb"]:
            aggregate["_internal_action_hits"] += 1

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
            cluster["_internal_recent_hits"] += int(stats["_internal_recent_hits"])
            cluster["_internal_action_hits"] += int(stats["_internal_action_hits"])
            token_sets[best_index].update(tokens)
            continue

        clusters.append({
            "seed": phrase,
            "aliases": [],
            "occurrences": int(stats["occurrences"]),
            "_internal_roles": set(stats["_internal_roles"]),
            "_internal_recent_hits": int(stats["_internal_recent_hits"]),
            "_internal_action_hits": int(stats["_internal_action_hits"]),
        })
        token_sets.append(tokens)

    for cluster in clusters:
        cluster["role_count"] = len(cluster["_internal_roles"])
        cluster["recent_role_count"] = int(cluster["_internal_recent_hits"])
        cluster["action_verb_count"] = int(cluster["_internal_action_hits"])

    clusters.sort(key=lambda item: (-int(item["occurrences"]), item["seed"]))
    return clusters


def _score(cluster: dict[str, Any]) -> float:
    occurrences = int(cluster["occurrences"])
    recurrence = min(occurrences / 10.0, 1.0)
    breadth = min(int(cluster["role_count"]) / 5.0, 1.0)
    recency = int(cluster["recent_role_count"]) / max(occurrences, 1)
    action_ratio = int(cluster["action_verb_count"]) / max(occurrences, 1)
    return recurrence * 0.35 + breadth * 0.30 + recency * 0.25 + action_ratio * 0.10


def score_and_promote(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for cluster in clusters:
        score = _score(cluster)
        occurrences = int(cluster["occurrences"])
        breadth = min(int(cluster["role_count"]) / 5.0, 1.0)
        recency_ratio = int(cluster["recent_role_count"]) / max(occurrences, 1)

        level = (
            "strong" if (score >= 0.65 or occurrences >= 8)
            else "working" if (score >= 0.45 or occurrences >= 4)
            else "basic"
        )
        fit = (
            "core" if (breadth >= 0.4 and recency_ratio >= 0.4)
            else "supporting" if (breadth >= 0.2 or recency_ratio >= 0.5)
            else "contextual"
        )

        scored.append({
            **cluster,
            "score": round(score, 3),
            "level": level,
            "fit": fit,
            "name": cluster["seed"],
            "fit_label": "",
            "watchout_label": "",
            "_internal_breadth": round(breadth, 3),
            "_internal_recency_ratio": round(recency_ratio, 3),
        })

    scored.sort(key=lambda item: (-float(item["score"]), item["seed"]))
    return scored


def _rename_top_clusters(candidates: list[dict[str, Any]], llm_client: Any = None) -> list[dict[str, Any]]:
    try:
        from job_hunter_agent.llm_gate import name_capability_clusters
    except ImportError:
        return candidates

    if not candidates:
        return candidates

    top = candidates[:20]
    try:
        labels = name_capability_clusters([
            {"name": item["seed"], "aliases": item["aliases"][:6]}
            for item in top
        ], llm_client=llm_client)
        if not labels:
            return candidates
    except Exception as exc:
        print(f"[CV_PIPELINE] LLM enrichment failed: {exc}")
        return candidates

    renamed_top: list[dict[str, Any]] = []
    for index, item in enumerate(top):
        renamed = dict(item)
        if index < len(labels):
            label = str(labels[index]).strip().lower()
            if label == "skip":
                continue
            # Basic length check; _is_quality_phrase would over-stem the label
            words = label.split()
            if label and 1 <= len(words) <= 5 and not _is_generic_title_phrase(_normalize_phrase(label)):
                renamed["name"] = label
        renamed_top.append(renamed)
    return renamed_top + candidates[len(top):]


def _build_output(candidates: list[dict[str, Any]], total_roles: int = 0) -> dict[str, Any]:
    capability_rules: list[dict[str, Any]] = []
    dominant_signal_clusters: list[dict[str, Any]] = []
    must_not_require_skills: list[str] = []

    for candidate in candidates:
        score = float(candidate["score"])
        role_count = int(candidate.get("role_count") or 0)
        if total_roles > 1 and role_count < 2 and (score < 0.65 or candidate.get("fit") != "core"):
            continue
        display_name = choose_capability_name(
            candidate["name"],
            [candidate["seed"], *candidate["aliases"]],
        )
        matching_aliases = derive_job_description_aliases(
            display_name,
            [candidate["seed"], *candidate["aliases"]],
            max_aliases=8,
        )
        if not display_name:
            continue
        name_tokens = display_name.split()
        if (
            not matching_aliases
            and len(name_tokens) <= 2
            and (
                name_tokens[0] in _WEAK_NAME_LEAD_TOKENS
                or name_tokens[-1] in _WEAK_NAME_TAIL_TOKENS
            )
        ):
            continue
        if name_tokens and name_tokens[0] in _WEAK_NAME_LEAD_TOKENS:
            continue

        if score >= 0.25:
            capability_rules.append({
                "name": display_name,
                "level": candidate["level"],
                "fit": candidate["fit"],
                "aliases": matching_aliases,
            })

        if score >= 0.20:
            signal_aliases = matching_aliases[:]
            if len(signal_aliases) < 2:
                signal_aliases = list(dict.fromkeys([display_name, *signal_aliases]))
            dominant_signal_clusters.append({
                "name": display_name,
                "aliases": signal_aliases[:8],
                "fit_label": candidate["fit_label"],
                "watchout_label": candidate["watchout_label"],
                "min_alias_hits": 2 if len(signal_aliases) >= 2 else 1,
                "min_snippet_hits": 2,
                "dense_snippet_alias_hits": max(len(signal_aliases) // 2 + 2, 4),
            })

    return {
        "capability_profile_rules": normalize_capability_rules(capability_rules[:20]),
        "dominant_signal_clusters": dominant_signal_clusters[:8],
        "must_not_require_skills": [],
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

    roles = parse_roles(text, onboarding_settings=onboarding_settings)
    phrase_items = extract_phrases(roles)
    clusters = cluster_phrases(phrase_items)
    candidates = score_and_promote(clusters)
    output = _build_output(candidates, total_roles=len(roles))

    print(
        f"[CV_PIPELINE] {len(roles)} roles -> {len(phrase_items)} phrases -> "
        f"{len(clusters)} clusters -> {len(candidates)} candidates -> "
        f"{len(output.get('capability_profile_rules', []))} cap rules, "
        f"{len(output.get('dominant_signal_clusters', []))} dominant clusters"
    )
    return _strip_internal_keys(output)
