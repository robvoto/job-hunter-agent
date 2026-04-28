import re
from collections import Counter
from typing import Any

from job_hunter_agent.profile_learning import (
    _GENERIC_PHRASE_STOPWORDS,
    _GENERIC_ROLE_NOUNS,
    _TITLE_MODIFIERS,
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
_TITLE_LIKE_TOKENS = _GENERIC_ROLE_NOUNS | _TITLE_MODIFIERS
_ACTIONISH_ALIAS_TOKENS = {
    "acted",
    "automated",
    "build",
    "built",
    "coordinate",
    "coordinated",
    "create",
    "created",
    "deliver",
    "delivered",
    "design",
    "designed",
    "develop",
    "developed",
    "drive",
    "drove",
    "execute",
    "executed",
    "facilitate",
    "facilitated",
    "implement",
    "implemented",
    "lead",
    "led",
    "manage",
    "managed",
    "run",
    "running",
    "support",
    "supported",
}
_WEAK_CAPABILITY_NAME_TOKENS = {
    "across",
    "based",
    "check",
    "during",
    "environment",
    "external",
    "including",
    "internal",
    "manager",
    "managers",
    "multiple",
    "primary",
    "secondary",
    "service",
    "services",
    "technology",
    "through",
    "tool",
    "tools",
    "vendor",
    "vendors",
}


def _clean_phrase(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _repair_term_text(value: str) -> str:
    return " ".join(_TOKEN_REPAIRS.get(token, token) for token in str(value or "").split()).strip()


def _tokenize(value: str) -> list[str]:
    tokens = [_TOKEN_REPAIRS.get(_normalize_token(token), _normalize_token(token)) for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#/&-]*", value)]
    return [token for token in tokens if token]


def _is_low_value_alias_term(term: str) -> bool:
    cleaned = _repair_term_text(_normalize_phrase(term))
    tokens = _tokenize(cleaned)
    if not cleaned or not tokens:
        return True
    if _is_generic_title_phrase(cleaned):
        return True
    if len(tokens) == 1:
        return tokens[0] in _GENERIC_SINGLE_WORD_ALIASES or tokens[0] in _TITLE_LIKE_TOKENS

    title_like_count = sum(1 for token in tokens if token in _TITLE_LIKE_TOKENS)
    if title_like_count >= max(len(tokens) - 1, 1):
        return True
    return False


def _informative_token_count(tokens: list[str]) -> int:
    return sum(1 for token in tokens if token not in _ALIAS_NOISE_TOKENS and token not in _TITLE_LIKE_TOKENS)


def _alias_quality_bonus(
    term: str,
    *,
    name_tokens: set[str],
    token_counts: Counter[str],
    from_full_phrase: bool,
) -> int:
    tokens = _tokenize(term)
    if not tokens:
        return -100

    bonus = 0
    informative_tokens = _informative_token_count(tokens)
    overlap_count = sum(1 for token in tokens if token in name_tokens)

    if len(tokens) >= 2:
        bonus += 10
    else:
        token = tokens[0]
        if token in name_tokens and token_counts.get(token, 0) < 4:
            bonus -= 8
        if token.endswith(("tion", "ment", "ing")):
            bonus -= 4
        bonus -= 3

    if from_full_phrase:
        bonus += 5

    if informative_tokens >= 2:
        bonus += 4
    elif informative_tokens == 0:
        bonus -= 6

    if overlap_count:
        bonus += overlap_count * 3

    if overlap_count == 0 and any("-" in token for token in tokens):
        bonus -= 6

    if tokens[0] in _ACTIONISH_ALIAS_TOKENS:
        bonus -= 12 if overlap_count == 0 else 7

    if len(tokens) == 2 and tokens[0] in name_tokens and tokens[1] in name_tokens:
        bonus += 2

    return bonus


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
            if not _is_quality_phrase(term):
                continue
            if _is_low_value_alias_term(term):
                continue
            if size == 2 and any(token in _GENERIC_SINGLE_WORD_ALIASES for token in term.split()):
                continue
            terms.append(term)
    return list(dict.fromkeys(terms))


def _capability_name_score(term: str) -> int:
    cleaned = _repair_term_text(_normalize_phrase(term))
    tokens = _tokenize(cleaned)
    if not cleaned or not tokens:
        return -100
    if _is_low_value_alias_term(cleaned):
        return -80

    informative_tokens = _informative_token_count(tokens)
    score = informative_tokens * 5
    if len(tokens) >= 2:
        score += 6
    else:
        score += 2

    if tokens[0] in _ACTIONISH_ALIAS_TOKENS:
        score -= 10
    if tokens[0] in _WEAK_CAPABILITY_NAME_TOKENS:
        score -= 8
    if tokens[-1] in _WEAK_CAPABILITY_NAME_TOKENS:
        score -= 6
    if len(tokens) == 2 and informative_tokens <= 1:
        score -= 5
    if any(token in _TITLE_LIKE_TOKENS for token in tokens):
        score -= 4
    return score


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
    if (
        len(ordered_name_tokens) >= 2
        and collapsed_name_tokens
        and collapsed_name_tokens != cleaned_name
        and not _is_low_value_alias_term(collapsed_name_tokens)
    ):
        short_term_scores[collapsed_name_tokens] += 10
    if len(ordered_name_tokens) > 2:
        for index in range(len(ordered_name_tokens) - 1):
            phrase = " ".join(ordered_name_tokens[index:index + 2]).strip()
            if phrase and phrase != cleaned_name and _is_quality_phrase(phrase) and not _is_low_value_alias_term(phrase):
                short_term_scores[phrase] += 8

    for index, cleaned in enumerate(sources):
        source_bonus = 5 if index == 0 else 3
        phrase_tokens = _tokenize(cleaned)
        if (
            cleaned != cleaned_name
            and len(cleaned.split()) <= 2
            and _is_quality_phrase(cleaned)
            and not _is_low_value_alias_term(cleaned)
            and phrase_tokens
            and _informative_token_count(phrase_tokens) >= 1
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
                if token in name_tokens:
                    if token_counts.get(token, 0) < 4:
                        continue
                elif token_counts.get(token, 0) < 2:
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
            key=lambda item: (
                -int(
                    short_term_scores.get(item[0], 0)
                    + full_phrase_scores.get(item[0], 0)
                    + _alias_quality_bonus(
                        item[0],
                        name_tokens=name_tokens,
                        token_counts=token_counts,
                        from_full_phrase=bool(full_phrase_scores.get(item[0], 0)),
                    )
                ),
                -len(item[0].split()),
                item[0],
            ),
        )
    ]

    aliases: list[str] = []
    seen: set[str] = {cleaned_name}
    for term in ordered_terms:
        normalized = _repair_term_text(_normalize_phrase(term))
        if not normalized or normalized in seen or _is_low_value_alias_term(normalized):
            continue
        quality_bonus = _alias_quality_bonus(
            normalized,
            name_tokens=name_tokens,
            token_counts=token_counts,
            from_full_phrase=bool(full_phrase_scores.get(term, 0)),
        )
        if full_phrase_scores.get(term, 0) and quality_bonus < 8:
            continue
        seen.add(normalized)
        aliases.append(normalized)
        if len(aliases) >= max_aliases:
            break
    return aliases


def choose_capability_name(name: str, raw_aliases: list[str] | None) -> str:
    cleaned_name = _repair_term_text(_normalize_phrase(name))
    derived_aliases = derive_job_description_aliases(cleaned_name or name, raw_aliases or [], max_aliases=6)
    best_alias = next((alias for alias in derived_aliases if not _is_low_value_alias_term(alias)), "")
    name_score = _capability_name_score(cleaned_name)
    alias_score = _capability_name_score(best_alias)
    if best_alias and (name_score < 0 or alias_score >= name_score + 3):
        return best_alias
    if cleaned_name and not _is_low_value_alias_term(cleaned_name):
        return cleaned_name
    return best_alias or cleaned_name


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
