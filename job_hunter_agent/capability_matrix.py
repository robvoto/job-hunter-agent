import re
from collections import Counter
from typing import Any

from job_hunter_agent.profile_learning import (
    _GENERIC_PHRASE_STOPWORDS,
    _is_generic_title_phrase,
    _is_quality_phrase,
    _normalize_phrase,
    _normalize_token,
)

_ALIAS_NOISE_TOKENS = _GENERIC_PHRASE_STOPWORDS | {
    "ability",
    "acted",
    "activity",
    "activities",
    "area",
    "based",
    "covering",
    "definition",
    "definitions",
    "delivery",
    "detailed",
    "end",
    "extensive",
    "including",
    "initiative",
    "initiatives",
    "lead",
    "major",
    "management",
    "multiple",
    "operational",
    "practice",
    "practices",
    "primary",
    "process",
    "processes",
    "produced",
    "program",
    "programs",
    "project",
    "projects",
    "reporting",
    "support",
    "supporting",
    "system",
    "systems",
    "team",
    "teams",
    "technical",
    "tool",
    "tools",
    "used",
    "using",
    "workflow",
    "workflows",
}
_GENERIC_SINGLE_WORD_ALIASES = {
    "analysis",
    "analyst",
    "background",
    "business",
    "capability",
    "client",
    "clients",
    "configuration",
    "context",
    "coordination",
    "criteria",
    "data",
    "definition",
    "delivery",
    "design",
    "discovery",
    "engagement",
    "handling",
    "improvement",
    "management",
    "methodologies",
    "methodology",
    "modelling",
    "modeling",
    "operations",
    "primary",
    "process",
    "programme",
    "program",
    "project",
    "reporting",
    "requirement",
    "requirements",
    "risk",
    "scenario",
    "stakeholder",
    "support",
    "test",
    "testing",
    "validation",
}
_TOKEN_REPAIRS = {
    "devop": "devops",
    "processe": "process",
}


def _clean_phrase(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _repair_term_text(value: str) -> str:
    return " ".join(_TOKEN_REPAIRS.get(token, token) for token in str(value or "").split()).strip()


def _tokenize(value: str) -> list[str]:
    tokens = [_TOKEN_REPAIRS.get(_normalize_token(token), _normalize_token(token)) for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/&-]*", value)]
    return [token for token in tokens if token]


def _collect_short_terms(value: str) -> list[str]:
    tokens = [token for token in _tokenize(value) if token not in _ALIAS_NOISE_TOKENS]
    terms: list[str] = []
    for size in (2, 1):
        if len(tokens) < size:
            continue
        for index in range(len(tokens) - size + 1):
            term = " ".join(tokens[index:index + size]).strip()
            if not term:
                continue
            if size == 1 and term in _GENERIC_SINGLE_WORD_ALIASES:
                continue
            if not _is_quality_phrase(term):
                continue
            if _is_generic_title_phrase(term):
                continue
            if size == 2 and any(token in _GENERIC_SINGLE_WORD_ALIASES for token in term.split()):
                continue
            terms.append(term)
    return list(dict.fromkeys(terms))


def derive_job_description_aliases(
    name: str,
    raw_aliases: list[str] | None,
    max_aliases: int = 8,
) -> list[str]:
    cleaned_name = _repair_term_text(_normalize_phrase(name))
    if not cleaned_name:
        return []

    sources = [
        _repair_term_text(_normalize_phrase(_clean_phrase(raw_value)))
        for raw_value in [name, *(raw_aliases or [])]
    ]
    sources = [value for value in sources if value]
    if not sources:
        return []

    filtered_sources = [
        [token for token in _tokenize(value) if token not in _ALIAS_NOISE_TOKENS]
        for value in sources
    ]
    token_counts = Counter(
        token
        for tokens in filtered_sources
        for token in dict.fromkeys(tokens)
    )
    name_tokens = {
        token
        for token in _tokenize(cleaned_name)
        if token and token not in _ALIAS_NOISE_TOKENS
    }
    ordered_name_tokens = [
        token
        for token in _tokenize(cleaned_name)
        if token and token not in _ALIAS_NOISE_TOKENS
    ]

    full_phrase_scores: Counter[str] = Counter()
    short_term_scores: Counter[str] = Counter()

    collapsed_name_tokens = " ".join(ordered_name_tokens).strip()
    if len(ordered_name_tokens) >= 2 and collapsed_name_tokens and collapsed_name_tokens != cleaned_name:
        short_term_scores[collapsed_name_tokens] += 10
    if len(ordered_name_tokens) > 2:
        for index in range(len(ordered_name_tokens) - 1):
            phrase = " ".join(ordered_name_tokens[index:index + 2]).strip()
            if phrase and phrase != cleaned_name and _is_quality_phrase(phrase) and not _is_generic_title_phrase(phrase):
                short_term_scores[phrase] += 8

    for index, cleaned in enumerate(sources):
        source_bonus = 5 if index == 0 else 3
        phrase_tokens = _tokenize(cleaned)
        if (
            cleaned != cleaned_name
            and len(cleaned.split()) <= 2
            and _is_quality_phrase(cleaned)
            and not _is_generic_title_phrase(cleaned)
            and phrase_tokens
            and all(token not in _ALIAS_NOISE_TOKENS for token in phrase_tokens)
        ):
            full_phrase_scores[cleaned] += source_bonus + 4

        for term in _collect_short_terms(cleaned):
            if term == cleaned_name:
                continue
            term_tokens = term.split()
            if len(term_tokens) == 1:
                token = term_tokens[0]
                if token in _GENERIC_SINGLE_WORD_ALIASES:
                    continue
                if token_counts.get(token, 0) < 2 and token not in name_tokens:
                    continue
                score = source_bonus + (3 if token in name_tokens else 1)
            else:
                if not all(token_counts.get(token, 0) >= 2 or token in name_tokens for token in term_tokens):
                    continue
                score = source_bonus + 4
            if term in cleaned_name:
                score += 2
            short_term_scores[term] += score

    ordered_terms = [
        term
        for term, _ in sorted(
            {**short_term_scores, **full_phrase_scores}.items(),
            key=lambda item: (-int(short_term_scores.get(item[0], 0) + full_phrase_scores.get(item[0], 0)), -len(item[0].split()), item[0]),
        )
    ]

    aliases: list[str] = []
    seen: set[str] = {cleaned_name}
    for term in ordered_terms:
        normalized = _repair_term_text(_normalize_phrase(term))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(normalized)
        if len(aliases) >= max_aliases:
            break
    return aliases


def expand_capability_terms(rule: dict[str, Any], max_terms: int = 10) -> list[str]:
    name = _clean_phrase(rule.get("name"))
    raw_aliases = [str(alias).strip() for alias in rule.get("aliases", []) if str(alias).strip()]
    derived_aliases = derive_job_description_aliases(name, raw_aliases, max_aliases=max_terms)

    expanded: list[str] = []
    seen: set[str] = set()
    for value in [name, *raw_aliases, *derived_aliases]:
        raw_cleaned = _clean_phrase(value).lower()
        normalized = _repair_term_text(_normalize_phrase(value))
        for candidate in [raw_cleaned, normalized]:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
            if len(expanded) >= max_terms:
                return expanded
    return expanded
