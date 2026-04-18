"""CV analysis pipeline — deterministic extraction followed by one focused LLM call.

Produces 5 profile fields from raw CV text:
  capability_profile_rules, dominant_signal_clusters, evidence_signals,
  must_not_require_skills, and search_settings.keywords (via caller).

Layers:
  A — parse_roles: extract structured role list
  B — extract_phrases: bigrams/trigrams from bullets
  C — cluster_phrases: Jaccard-based phrase grouping
  D — score_and_promote: threshold scoring into level/fit
  LLM — label only (no invention, ~400 in / 350 out tokens)
"""

import json
import re
from collections import defaultdict
from typing import Any

from profile_learning import (
    _CURRENT_YEAR,
    _GENERIC_PHRASE_STOPWORDS,
    _is_generic_title_phrase,
    _is_quality_phrase,
    _normalize_phrase,
    _parse_role_entries,
    repair_text,
)
from profile_store import normalize_capability_rules

_RECENT_CUTOFF = _CURRENT_YEAR - 5

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


# ─── Layer A ────────────────────────────────────────────────────

def parse_roles(cv_text: str) -> list[dict[str, Any]]:
    result = []
    for role in _parse_role_entries(cv_text):
        end_year = int(role.get("end_year") or 0)
        result.append({
            "title": role.get("title", ""),
            "start_year": role.get("start_year"),
            "end_year": end_year,
            "is_recent": end_year >= _RECENT_CUTOFF,
            "bullets": role.get("bullets", []),
        })
    return result


# ─── Layer B ────────────────────────────────────────────────────

def _has_action_verb(text: str) -> bool:
    tokens = {t.lower() for t in re.findall(r"[a-zA-Z]+", text)}
    return bool(tokens & _ACTION_VERBS)


def _ngrams(text: str) -> list[str]:
    tokens = [
        t.lower()
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/-]*", text)
        if t.lower() not in _GENERIC_PHRASE_STOPWORDS
    ]
    phrases = []
    for size in (3, 2):
        for i in range(len(tokens) - size + 1):
            norm = _normalize_phrase(" ".join(tokens[i : i + size]))
            if norm and _is_quality_phrase(norm) and not _is_generic_title_phrase(norm):
                phrases.append(norm)
    return list(dict.fromkeys(phrases))


def extract_phrases(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for role in roles:
        title = role.get("title", "")
        is_recent = bool(role.get("is_recent"))
        for bullet in role.get("bullets", []):
            has_av = _has_action_verb(bullet)
            for phrase in _ngrams(bullet):
                items.append({
                    "phrase": phrase,
                    "role_title": title,
                    "is_recent": is_recent,
                    "has_action_verb": has_av,
                })
    return items


# ─── Layer C ────────────────────────────────────────────────────

def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def cluster_phrases(phrase_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict] = defaultdict(lambda: {
        "occ": 0, "roles": set(), "recent": 0, "av": 0,
    })
    for item in phrase_items:
        d = agg[item["phrase"]]
        d["occ"] += 1
        d["roles"].add(item["role_title"])
        if item["is_recent"]:
            d["recent"] += 1
        if item["has_action_verb"]:
            d["av"] += 1

    sorted_phrases = sorted(agg.items(), key=lambda x: -x[1]["occ"])

    seeds: list[str] = []
    token_sets: list[set[str]] = []
    internals: list[dict] = []

    for phrase, stats in sorted_phrases:
        tokens = set(phrase.split())
        best_idx, best_j = -1, 0.0
        for i, tset in enumerate(token_sets):
            j = _jaccard(tokens, tset)
            if j >= 0.40 and j > best_j:
                best_idx, best_j = i, j

        if best_idx >= 0:
            c = internals[best_idx]
            c["aliases"].append(phrase)
            c["_roles"].update(stats["roles"])
            c["occ"] += stats["occ"]
            c["recent"] += stats["recent"]
            c["av"] += stats["av"]
        else:
            seeds.append(phrase)
            token_sets.append(tokens)
            internals.append({
                "aliases": [],
                "_roles": set(stats["roles"]),
                "occ": stats["occ"],
                "recent": stats["recent"],
                "av": stats["av"],
            })

    result = []
    for seed, c in zip(seeds, internals):
        result.append({
            "seed": seed,
            "aliases": c["aliases"],
            "occurrences": c["occ"],
            "role_count": len(c["_roles"]),
            "recent_role_count": c["recent"],
            "action_verb_count": c["av"],
        })
    result.sort(key=lambda x: -x["occurrences"])
    return result


# ─── Layer D ────────────────────────────────────────────────────

def _score(c: dict) -> float:
    occ = c["occurrences"]
    recurrence = min(occ / 10.0, 1.0)
    breadth = min(c["role_count"] / 5.0, 1.0)
    recency = c["recent_role_count"] / max(occ, 1)
    av = c["action_verb_count"] / max(occ, 1)
    return recurrence * 0.35 + breadth * 0.30 + recency * 0.25 + av * 0.10


def score_and_promote(clusters: list[dict]) -> list[dict]:
    candidates = []
    for c in clusters:
        s = _score(c)
        if s < 0.15:
            continue
        occ = c["occurrences"]
        breadth = min(c["role_count"] / 5.0, 1.0)
        recency_r = c["recent_role_count"] / max(occ, 1)

        level = (
            "strong" if (s >= 0.65 or occ >= 8)
            else "working" if (s >= 0.45 or occ >= 4)
            else "basic"
        )
        fit = (
            "core" if (breadth >= 0.4 and recency_r >= 0.4)
            else "supporting" if (breadth >= 0.2 or recency_r >= 0.5)
            else "contextual"
        )
        candidates.append({
            **c,
            "score": round(s, 3),
            "level": level,
            "fit": fit,
            "name": c["seed"],
            "fit_label": "",
            "watchout_label": "",
        })

    candidates.sort(key=lambda x: -x["score"])
    return candidates


# ─── LLM enrichment ─────────────────────────────────────────────

def _enrich_with_llm(candidates: list[dict]) -> list[dict]:
    try:
        from llm_gate import client, _get_llm_model
    except ImportError:
        return candidates
    if not client or not candidates:
        return candidates

    top = candidates[:15]
    payload = [
        {"seed": c["seed"], "aliases": c["aliases"][:4], "level": c["level"]}
        for c in top
    ]
    prompt = (
        "Label pre-detected CV capability clusters. Do not invent or remove clusters.\n"
        "Rules: same order as input; 1-4 word lowercase label; "
        "fit_label = 3-6 word role type that benefits; "
        "watchout_label = 4-8 word risk or caveat.\n"
        'Return JSON array only: [{"seed":"...","label":"...","fit_label":"...","watchout_label":"..."}]\n\n'
        "Clusters:\n" + json.dumps(payload, ensure_ascii=False)
    )

    try:
        resp = client.responses.create(
            model=_get_llm_model(),
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=350,
        )
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        enriched = json.loads(raw)
        if not isinstance(enriched, list):
            return candidates

        seed_map = {item.get("seed", ""): item for item in enriched if isinstance(item, dict)}
        result = []
        for c in top:
            llm = seed_map.get(c["seed"], {})
            c = dict(c)
            if llm.get("label"):
                c["name"] = str(llm["label"]).strip().lower()
            c["fit_label"] = str(llm.get("fit_label") or "").strip()
            c["watchout_label"] = str(llm.get("watchout_label") or "").strip()
            result.append(c)
        return result + candidates[15:]
    except Exception as exc:
        print(f"[CV_PIPELINE] LLM enrichment failed: {exc}")
        return candidates


# ─── Output assembly ─────────────────────────────────────────────

def _build_output(candidates: list[dict]) -> dict[str, Any]:
    cap_rules = []
    dom_clusters = []
    evidence: list[str] = []
    must_not: list[str] = []

    for c in candidates:
        s = c["score"]

        if s >= 0.25:
            cap_rules.append({
                "name": c["name"],
                "level": c["level"],
                "fit": c["fit"],
                "aliases": c["aliases"][:6],
            })

        if s >= 0.20:
            dom_clusters.append({
                "name": c["name"],
                "aliases": [c["seed"]] + c["aliases"][:8],
                "fit_label": c["fit_label"],
                "watchout_label": c["watchout_label"],
                "min_alias_hits": 2,
                "min_snippet_hits": 2,
                "dense_snippet_alias_hits": max(len(c["aliases"]) // 2 + 2, 4),
            })
            evidence.append(c["name"])
            evidence.extend(c["aliases"][:2])

        if (
            s < 0.10
            and c["recent_role_count"] == 0
            and c["action_verb_count"] == 0
            and c["occurrences"] <= 2
        ):
            must_not.append(c["seed"])

    return {
        "capability_profile_rules": normalize_capability_rules(cap_rules[:15]),
        "dominant_signal_clusters": dom_clusters[:8],
        "evidence_signals": list(dict.fromkeys(evidence))[:20],
        "must_not_require_skills": must_not[:8],
    }


# ─── Public entry point ──────────────────────────────────────────

def run_cv_pipeline(cv_text: str) -> dict[str, Any]:
    text = repair_text(cv_text)
    if not text:
        return {}

    roles = parse_roles(text)
    phrase_items = extract_phrases(roles)
    clusters = cluster_phrases(phrase_items)
    candidates = score_and_promote(clusters)
    enriched = _enrich_with_llm(candidates)
    output = _build_output(enriched)

    print(
        f"[CV_PIPELINE] {len(roles)} roles → {len(phrase_items)} phrases → "
        f"{len(clusters)} clusters → {len(candidates)} candidates → "
        f"{len(output.get('capability_profile_rules', []))} cap rules, "
        f"{len(output.get('dominant_signal_clusters', []))} dominant clusters"
    )
    return output
