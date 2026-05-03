from __future__ import annotations

import json
import re
from typing import Any

from job_hunter_agent.role_title_knowledge import load_role_title_knowledge
from job_hunter_agent.paths import DATA_DIR, OUTPUT_DIR


TITLE_NORMALIZATION_REVIEW_PATH = OUTPUT_DIR / "title_normalization_review.json"
TITLE_NORMALIZATION_RULES_PATH = DATA_DIR / "title_normalization_rules.json"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_payload() -> dict[str, Any]:
    if not TITLE_NORMALIZATION_RULES_PATH.exists():
        return {}
    try:
        payload = json.loads(TITLE_NORMALIZATION_RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_title_normalization_rules() -> dict[str, Any]:
    payload = _load_payload()
    if not payload:
        raise ValueError("title_normalization_rules.json must contain a rules object")
    return payload


def _save_rules_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("kind", "rules")
    normalized.setdefault("name", "title_normalization_rules")
    normalized.setdefault("version", 1)
    normalized.setdefault("updated_at", "")
    normalized.setdefault("seniority_modifiers", [])
    normalized.setdefault("abbreviation_expansions", {})
    normalized.setdefault("normalization", {})
    TITLE_NORMALIZATION_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TITLE_NORMALIZATION_RULES_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _strip_outer_punctuation(value: str) -> str:
    return re.sub(r"^[\s\W_]+|[\s\W_]+$", "", value).strip()


def _clean_rule_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _load_seniority_modifiers() -> frozenset[str]:
    try:
        payload = load_title_normalization_rules()
    except Exception:
        return frozenset()
    modifiers = payload.get("seniority_modifiers")
    if not isinstance(modifiers, list):
        return frozenset()
    return frozenset(
        _clean_rule_token(value)
        for value in modifiers
        if _clean_rule_token(value)
    )


def extract_seniority_modifiers(value: Any) -> list[str]:
    normalized = normalize_title_text(value)
    if not normalized:
        return []

    modifiers = _load_seniority_modifiers()
    if not modifiers:
        return []

    seen: set[str] = set()
    matched: list[str] = []
    for token in normalized.split():
        if token in modifiers and token not in seen:
            seen.add(token)
            matched.append(token)
    return matched


def _load_role_title_tokens() -> frozenset[str]:
    try:
        entries = load_role_title_knowledge()
    except Exception:
        return frozenset()

    tokens: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = _clean_rule_token(entry.get("value"))
        token = re.sub(r"[^a-z0-9+#/&-]", "", value.lower()).strip("-/")
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 4 and not token.endswith("ss") and not token.endswith("is"):
            token = token[:-1]
        if token:
            tokens.append(token)
    return frozenset(tokens)


def decompose_title_text(value: Any) -> dict[str, Any]:
    normalized = normalize_title_text(value)
    if not normalized:
        return {
            "normalized_title": "",
            "seniority_modifiers": [],
            "base_role": "",
            "variant_terms": "",
        }

    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return {
            "normalized_title": normalized,
            "seniority_modifiers": [],
            "base_role": "",
            "variant_terms": "",
        }

    seniority_modifiers = extract_seniority_modifiers(normalized)
    seniority_set = set(seniority_modifiers)
    family_tokens = [token for token in tokens if token not in seniority_set]
    if not family_tokens:
        return {
            "normalized_title": normalized,
            "seniority_modifiers": seniority_modifiers,
            "base_role": "",
            "variant_terms": "",
        }

    role_tokens = _load_role_title_tokens()
    base_role_tokens = list(family_tokens)
    variant_terms_tokens: list[str] = []
    if role_tokens:
        role_indices = [index for index, token in enumerate(family_tokens) if token in role_tokens]
        if role_indices:
            last_role_index = role_indices[-1] + 1
            base_role_tokens = family_tokens[:last_role_index]
            variant_terms_tokens = family_tokens[last_role_index:]

    base_role = " ".join(base_role_tokens).strip()
    variant_terms = " ".join(variant_terms_tokens).strip()
    return {
        "normalized_title": normalized,
        "seniority_modifiers": seniority_modifiers,
        "base_role": base_role,
        "variant_terms": variant_terms,
    }


def derive_base_title_from_seniority(value: Any) -> str:
    return str(decompose_title_text(value).get("base_role") or "").strip()


def _load_review_payload() -> dict[str, Any]:
    if not TITLE_NORMALIZATION_REVIEW_PATH.exists():
        return {"kind": "title_normalization_review", "name": "title_normalization_review", "version": 1, "entries": []}
    try:
        payload = json.loads(TITLE_NORMALIZATION_REVIEW_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("kind", "title_normalization_review")
    normalized.setdefault("name", "title_normalization_review")
    normalized.setdefault("version", 1)
    normalized.setdefault("updated_at", "")
    normalized.setdefault("entries", [])
    TITLE_NORMALIZATION_REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    TITLE_NORMALIZATION_REVIEW_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _normalize_review_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = _clean_rule_token(entry.get("value"))
    if not value:
        return None
    suggested_values = []
    seen: set[str] = {value}
    for item in entry.get("suggested_values") or []:
        suggested = _clean_rule_token(item)
        if not suggested or suggested in seen:
            continue
        seen.add(suggested)
        suggested_values.append(suggested)
    evidence = []
    seen_evidence: set[str] = set()
    for item in entry.get("evidence") or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        lowered = text.lower()
        if not text or lowered in seen_evidence:
            continue
        seen_evidence.add(lowered)
        evidence.append(text)
    sources = []
    seen_sources: set[str] = set()
    for item in entry.get("sources") or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        lowered = text.lower()
        if not text or lowered in seen_sources:
            continue
        seen_sources.add(lowered)
        sources.append(text)
    normalized: dict[str, Any] = {
        "value": value,
        "suggested_values": suggested_values,
        "evidence": evidence,
        "sources": sources,
        "confidence": _clean_rule_token(entry.get("confidence")) or "ambiguous",
        "needs_review": bool(entry.get("needs_review", True)),
    }
    note = re.sub(r"\s+", " ", str(entry.get("note") or "")).strip()
    if note:
        normalized["note"] = note
    return normalized


def load_title_normalization_review() -> list[dict[str, Any]]:
    payload = _load_review_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("title_normalization_review.json must contain an entries list")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = _normalize_review_entry(entry)
        if normalized is None:
            continue
        key = normalized["value"]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    if cleaned != entries:
        save_title_normalization_review(cleaned)
    return cleaned


def save_title_normalization_review(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_review_payload()
    payload.setdefault("kind", "title_normalization_review")
    payload.setdefault("name", "title_normalization_review")
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", "")
    payload["entries"] = [
        entry
        for entry in (
            _normalize_review_entry(item)
            for item in entries
        )
        if entry is not None
    ]
    return _save_review_payload(payload)


def record_title_normalization_review(
    value: str,
    *,
    suggested_values: list[str] | None = None,
    evidence: list[str] | None = None,
    sources: list[str] | None = None,
    confidence: str = "ambiguous",
    note: str = "",
) -> dict[str, Any]:
    cleaned_value = _clean_rule_token(value)
    if not cleaned_value:
        raise ValueError("value is required")

    entries = list(load_title_normalization_review())
    cleaned_suggestions = []
    seen: set[str] = {cleaned_value}
    for item in suggested_values or []:
        suggested = _clean_rule_token(item)
        if not suggested or suggested in seen:
            continue
        seen.add(suggested)
        cleaned_suggestions.append(suggested)

    cleaned_evidence: list[str] = []
    seen_evidence: set[str] = set()
    for item in evidence or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        lowered = text.lower()
        if not text or lowered in seen_evidence:
            continue
        seen_evidence.add(lowered)
        cleaned_evidence.append(text)

    cleaned_sources: list[str] = []
    seen_sources: set[str] = set()
    for item in sources or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        lowered = text.lower()
        if not text or lowered in seen_sources:
            continue
        seen_sources.add(lowered)
        cleaned_sources.append(text)

    for entry in entries:
        if entry["value"] != cleaned_value:
            continue
        merged_suggestions = list(dict.fromkeys([*entry.get("suggested_values", []), *cleaned_suggestions]))
        entry["suggested_values"] = merged_suggestions
        entry["evidence"] = list(dict.fromkeys([*entry.get("evidence", []), *cleaned_evidence]))
        entry["sources"] = list(dict.fromkeys([*entry.get("sources", []), *cleaned_sources]))
        entry["confidence"] = confidence or entry.get("confidence") or "ambiguous"
        if note:
            entry["note"] = note
        entry["needs_review"] = True
        return save_title_normalization_review(entries)

    entries.append({
        "value": cleaned_value,
        "suggested_values": cleaned_suggestions,
        "evidence": cleaned_evidence,
        "sources": cleaned_sources,
        "confidence": confidence or "ambiguous",
        "needs_review": True,
        **({"note": note} if note else {}),
    })
    return save_title_normalization_review(entries)


def upsert_title_normalization_expansion(abbreviation: str, expansion: str) -> dict[str, Any]:
    cleaned_abbreviation = _clean_rule_token(abbreviation)
    cleaned_expansion = _clean_rule_token(expansion)
    if not cleaned_abbreviation or not cleaned_expansion:
        raise ValueError("abbreviation and expansion are required")

    payload = load_title_normalization_rules()
    expansions = payload.get("abbreviation_expansions")
    if not isinstance(expansions, dict):
        expansions = {}
    existing = _clean_rule_token(expansions.get(cleaned_abbreviation))
    if existing and existing != cleaned_expansion:
        record_title_normalization_review(
            cleaned_abbreviation,
            suggested_values=[existing, cleaned_expansion],
            evidence=[f"{cleaned_abbreviation} -> {existing}", f"{cleaned_abbreviation} -> {cleaned_expansion}"],
            sources=["auto-promotion conflict"],
            confidence="ambiguous",
            note="conflicting approved expansion",
        )
        return payload

    if existing == cleaned_expansion:
        return payload

    expansions = dict(expansions)
    expansions[cleaned_abbreviation] = cleaned_expansion
    payload["abbreviation_expansions"] = expansions
    return _save_rules_payload(payload)


_MEDICAL_CONTEXT_TOKENS = {
    "medical",
    "doctor",
    "clinic",
    "patient",
    "health",
    "practice",
    "hospital",
    "general practitioner",
}


def _has_medical_context(*values: Any) -> bool:
    combined = " ".join(_clean_rule_token(value) for value in values if _clean_rule_token(value))
    if not combined:
        return False
    return any(token in combined for token in _MEDICAL_CONTEXT_TOKENS)


def _classify_title_normalization_candidate(title: Any, source_text: Any = "") -> dict[str, Any] | None:
    raw_title = _clean_text(title)
    if not raw_title:
        return None

    lowered = raw_title.lower()
    tokens = re.findall(r"[a-z0-9]+", lowered)
    if not tokens:
        return None

    source_context = _clean_text(source_text)
    for token in tokens:
        if token == "sr":
            return {
                "value": "sr",
                "expansion": "senior",
                "auto_promote": True,
                "confidence": "strong",
                "evidence": [raw_title],
            }
        if token == "jr":
            return {
                "value": "jr",
                "expansion": "junior",
                "auto_promote": True,
                "confidence": "strong",
                "evidence": [raw_title],
            }
        if token == "gp":
            if _has_medical_context(raw_title, source_context):
                return {
                    "value": "gp",
                    "expansion": "general practitioner",
                    "auto_promote": True,
                    "confidence": "likely",
                    "evidence": [raw_title, source_context],
                }
            return {
                "value": "gp",
                "suggested_values": ["general practitioner"],
                "auto_promote": False,
                "confidence": "ambiguous",
                "evidence": [raw_title],
            }
        if token == "pm":
            return {
                "value": "pm",
                "suggested_values": [
                    "project manager",
                    "product manager",
                    "program manager",
                ],
                "auto_promote": False,
                "confidence": "ambiguous",
                "evidence": [raw_title],
            }
    return None


def learn_title_normalization_candidates(
    titles: list[str] | tuple[str, ...] | set[str],
    *,
    source: str = "",
    source_text: str = "",
) -> dict[str, int]:
    summary = {"promoted": 0, "reviewed": 0}
    source_label = _clean_text(source)
    for title in titles or []:
        candidate = _classify_title_normalization_candidate(title, source_text)
        if candidate is None:
            continue
        if candidate.get("auto_promote") and candidate.get("expansion"):
            upsert_title_normalization_expansion(candidate["value"], candidate["expansion"])
            summary["promoted"] += 1
            continue
        record_title_normalization_review(
            candidate["value"],
            suggested_values=list(candidate.get("suggested_values") or []),
            evidence=list(candidate.get("evidence") or []),
            sources=[source_label] if source_label else [],
            confidence=str(candidate.get("confidence") or "ambiguous"),
        )
        summary["reviewed"] += 1
    return summary


def normalize_title_text(value: Any) -> str:
    payload = load_title_normalization_rules()
    normalization = payload.get("normalization") if isinstance(payload.get("normalization"), dict) else {}
    text = _clean_text(value)
    if not text:
        return ""

    if normalization.get("strip_outer_punctuation", True):
        text = _strip_outer_punctuation(text)

    if normalization.get("collapse_spaces", True):
        text = re.sub(r"\s+", " ", text).strip()

    if normalization.get("lowercase_for_matching", True):
        text = text.lower()

    expansions = payload.get("abbreviation_expansions")
    if not isinstance(expansions, dict) or not expansions:
        return text

    expanded_tokens: list[str] = []
    for token in re.split(r"\s+", text):
        cleaned_token = _strip_outer_punctuation(token)
        if not cleaned_token:
            continue
        expansion = _clean_text(expansions.get(cleaned_token))
        if expansion:
            expanded_tokens.extend(part for part in expansion.split() if part)
            continue
        expanded_tokens.append(cleaned_token)

    normalized = " ".join(expanded_tokens)
    if normalization.get("collapse_spaces", True):
        normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalization.get("lowercase_for_matching", True):
        normalized = normalized.lower()
    return normalized
