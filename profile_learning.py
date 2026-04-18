"""Profile learning helpers.

Main goals:
- repair imported text
- extract summaries, evidence signals, notes, and capability rules from human material
- provide a local knowledge-note fallback for profile enrichment

Notes:
- capability_profile.txt is a local editable knowledge note
- capability_profile.template.txt is the committed starter template for new users
"""

from collections import Counter, defaultdict
from datetime import datetime
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"


def repair_text(text: str) -> str:
    if not text:
        return ""
    repaired = text.replace("\r\n", "\n")
    if "â" in repaired or "Ã" in repaired:
        try:
            candidate = repaired.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            if candidate.count("â") < repaired.count("â"):
                repaired = candidate
        except Exception:
            pass
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2192": "->",
    }
    for source, target in replacements.items():
        repaired = repaired.replace(source, target)
    return repaired.strip()


def _find_rating(text: str) -> float | None:
    match = re.search(r"Level:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _level_from_rating(rating: float | None) -> str:
    if rating is None:
        return "basic"
    if rating >= 8.0:
        return "strong"
    if rating >= 6.0:
        return "working"
    if rating >= 4.5:
        return "basic"
    if rating > 0:
        return "low"
    return "none"


def _extract_section(text: str, header: str) -> str:
    pattern = rf"##\s+{re.escape(header)}\s*\n(.*?)(?=\n##\s+|\Z)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_subsection(text: str, header: str) -> str:
    pattern = rf"###\s+{re.escape(header)}\s*\n(.*?)(?=\n###\s+|\n##\s+|\Z)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_named_section(text: str, header: str) -> str:
    return _extract_subsection(text, header) or _extract_section(text, header)


def _extract_bullets(text: str) -> list[str]:
    return [match.strip() for match in re.findall(r"^\*\s+(.+)$", text, flags=re.MULTILINE)]


def _clean_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -\n")


_VALID_LEVELS = {"strong", "working", "basic", "low", "none"}
_VALID_FITS = {"core", "supporting", "contextual", "avoid"}
_CURRENT_YEAR = datetime.now().year
_ROLE_SECTION_HINTS = ("experience", "employment", "career", "work history", "professional")
_SKILL_SECTION_HINTS = ("skill", "capabilit", "tool", "technology", "competenc", "summary", "profile")
_IGNORE_SECTION_HINTS = ("education", "certification", "certificate", "training", "award")
_GENERIC_PHRASE_STOPWORDS = {
    "a", "an", "and", "the", "to", "for", "of", "in", "on", "with", "by", "from", "into", "across",
    "using", "use", "used", "within", "through", "across", "under", "over", "per", "or", "as", "at",
    "is", "are", "was", "were", "be", "been", "being", "that", "this", "these", "those", "their",
    "our", "your", "my", "his", "her", "its", "will", "would", "can", "could", "should", "may",
}
_GENERIC_PHRASE_BLACKLIST = {
    "experience", "responsibility", "responsibilities", "project", "projects", "domain", "outcome",
    "outcomes", "location", "present", "profile", "professional experience", "professional summary",
    "core profile", "tools", "technologies", "skills", "summary",
}
_TITLE_MODIFIERS = {
    "senior", "lead", "principal", "technical", "functional", "digital", "delivery", "staff",
    "junior", "associate", "executive", "chief", "head", "contract", "consulting", "consultant",
}
_GENERIC_ROLE_NOUNS = {
    "analyst", "manager", "coordinator", "consultant", "specialist", "developer", "engineer",
    "architect", "officer", "director", "administrator", "owner", "lead", "executive",
    "head", "staff", "project", "business",
}


def _clean_line(text: str) -> str:
    cleaned = re.sub(r"[*_`#]+", " ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\t")
    return cleaned


def _normalize_token(token: str) -> str:
    cleaned = re.sub(r"[^a-z0-9+#/&-]", "", str(token or "").lower()).strip("-/")
    if cleaned.endswith("ies") and len(cleaned) > 4:
        cleaned = cleaned[:-3] + "y"
    elif cleaned.endswith("s") and len(cleaned) > 4 and not cleaned.endswith("ss") and not cleaned.endswith("is"):
        cleaned = cleaned[:-1]
    return cleaned


def _normalize_phrase(text: str) -> str:
    tokens = [_normalize_token(token) for token in re.split(r"\s+", str(text or ""))]
    tokens = [token for token in tokens if token]
    while tokens and tokens[0] in _GENERIC_PHRASE_STOPWORDS:
        tokens.pop(0)
    while tokens and tokens[-1] in _GENERIC_PHRASE_STOPWORDS:
        tokens.pop()
    return " ".join(tokens).strip()


def _section_kind(section_name: str) -> str:
    lowered = str(section_name or "").strip().lower()
    if any(hint in lowered for hint in _IGNORE_SECTION_HINTS):
        return "ignore"
    if any(hint in lowered for hint in _ROLE_SECTION_HINTS):
        return "experience"
    if any(hint in lowered for hint in _SKILL_SECTION_HINTS):
        return "skills"
    return "other"


def _extract_year_range(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"(?P<start>(?:19|20)\d{2})\s*(?:-|–|to|/)\s*(?P<end>present|current|now|(?:19|20)\d{2})",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    start_year = int(match.group("start"))
    raw_end = match.group("end").lower()
    is_current = raw_end in {"present", "current", "now"}
    end_year = _CURRENT_YEAR if is_current else int(raw_end)
    duration_months = max(((end_year - start_year) + 1) * 12, 12)
    return {
        "start_year": start_year,
        "end_year": end_year,
        "is_current": is_current,
        "duration_months": duration_months,
    }


def _looks_like_title(text: str) -> bool:
    cleaned = _clean_line(text)
    lowered = cleaned.lower()
    if not cleaned or len(cleaned.split()) > 8:
        return False
    if re.search(r"\b(degree|certified|certification|university|college|school)\b", lowered):
        return False
    if ":" in cleaned:
        return False
    if _extract_year_range(cleaned):
        return False
    return True


def _parse_role_entries(source_text: str) -> list[dict[str, Any]]:
    lines = source_text.splitlines()
    roles: list[dict[str, Any]] = []
    current_section = ""
    i = 0

    inline_role_re = re.compile(
        r"^(?P<employer>.+?)\s*-\s*(?P<title>.+?)\s*\((?P<dates>(?:19|20)\d{2}.*?(?:present|current|now|(?:19|20)\d{2}))\)\s*$",
        flags=re.IGNORECASE,
    )

    while i < len(lines):
        raw_line = lines[i].strip()
        cleaned = _clean_line(raw_line)
        if not cleaned:
            i += 1
            continue

        if raw_line.lstrip().startswith("#"):
            current_section = cleaned.lower()
            i += 1
            continue

        inline_match = inline_role_re.match(cleaned)
        if inline_match and _section_kind(current_section) != "ignore":
            date_info = _extract_year_range(inline_match.group("dates"))
            if date_info:
                roles.append(
                    {
                        "title": _clean_line(inline_match.group("title")),
                        "employer": _clean_line(inline_match.group("employer")),
                        "section": current_section,
                        "bullets": [],
                        **date_info,
                    }
                )
            i += 1
            continue

        date_info = _extract_year_range(cleaned)
        if not date_info or _section_kind(current_section) == "ignore":
            i += 1
            continue

        candidate_lines: list[str] = []
        bullets: list[str] = []
        j = i + 1
        while j < len(lines):
            look_raw = lines[j].strip()
            look = _clean_line(look_raw)
            if not look:
                j += 1
                continue
            if look_raw.lstrip().startswith("#"):
                break
            if _extract_year_range(look):
                break
            if look_raw.lstrip().startswith(("-", "*")):
                bullets.append(_clean_line(re.sub(r"^[-*]\s*", "", look_raw)))
            elif not bullets and len(candidate_lines) < 3:
                candidate_lines.append(look)
            j += 1

        employer = candidate_lines[0] if candidate_lines else ""
        title = ""
        if len(candidate_lines) >= 2 and _looks_like_title(candidate_lines[1]):
            title = candidate_lines[1]
        elif candidate_lines and _looks_like_title(candidate_lines[0]):
            title = candidate_lines[0]

        if title:
            roles.append(
                {
                    "title": title,
                    "employer": employer if employer != title else "",
                    "section": current_section,
                    "bullets": bullets,
                    **date_info,
                }
            )
        i = max(j, i + 1)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for role in roles:
        key = (
            _normalize_phrase(role.get("title", "")),
            int(role.get("start_year", 0) or 0),
            int(role.get("end_year", 0) or 0),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(role)
    return deduped


def _simplify_title(title: str) -> str:
    tokens = [_normalize_token(token) for token in _clean_line(title).split()]
    while tokens and tokens[0] in _TITLE_MODIFIERS:
        tokens.pop(0)
    simplified = " ".join(token for token in tokens if token)
    return simplified.strip()


def _make_title_pattern(title: str) -> str:
    normalized = _clean_line(title).lower()
    return rf"\b{re.escape(normalized)}\b" if normalized else ""


def _is_quality_phrase(phrase: str) -> bool:
    cleaned = _normalize_phrase(phrase)
    if not cleaned or cleaned in _GENERIC_PHRASE_BLACKLIST:
        return False
    tokens = cleaned.split()
    if not tokens or len(tokens) > 4:
        return False
    if len(tokens) == 1 and len(tokens[0]) < 4:
        return False
    if all(token in _GENERIC_PHRASE_STOPWORDS for token in tokens):
        return False
    return True


def _is_generic_title_phrase(phrase: str) -> bool:
    tokens = _normalize_phrase(phrase).split()
    return bool(tokens) and all(token in _TITLE_MODIFIERS or token in _GENERIC_ROLE_NOUNS for token in tokens)


def _phrase_variants_from_text(text: str) -> list[str]:
    cleaned = _clean_line(text)
    if not cleaned:
        return []

    variants: list[str] = []
    chunks = [chunk.strip() for chunk in re.split(r"[;,]|(?:\s{2,})", cleaned) if chunk.strip()]
    for chunk in chunks or [cleaned]:
        normalized_chunk = _normalize_phrase(chunk)
        if _is_quality_phrase(normalized_chunk):
            variants.append(normalized_chunk)

        tokens = [_normalize_token(token) for token in chunk.split()]
        tokens = [token for token in tokens if token and token not in _GENERIC_PHRASE_STOPWORDS]
        for size in (3, 2, 1):
            if size == 1 and len(tokens) > 1:
                continue
            for start in range(0, max(len(tokens) - size + 1, 0)):
                phrase = " ".join(tokens[start:start + size])
                if _is_quality_phrase(phrase):
                    variants.append(phrase)
    return list(dict.fromkeys(variants))


def _collect_phrase_stats(source_text: str, roles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "score": 0.0,
            "roles": set(),
            "recent_roles": set(),
            "variants": Counter(),
            "source_types": set(),
        }
    )

    for role in roles:
        role_key = f"{role.get('title','')}|{role.get('start_year','')}"
        recent = int(role.get("end_year", 0) or 0) >= (_CURRENT_YEAR - 5)
        for phrase in _phrase_variants_from_text(role.get("title", "")):
            entry = stats[phrase]
            entry["score"] += 2.2
            entry["roles"].add(role_key)
            if recent:
                entry["recent_roles"].add(role_key)
            entry["variants"][phrase] += 1
            entry["source_types"].add("role_title")
        for bullet in role.get("bullets", []):
            for phrase in _phrase_variants_from_text(bullet):
                entry = stats[phrase]
                entry["score"] += 1.1
                entry["roles"].add(role_key)
                if recent:
                    entry["recent_roles"].add(role_key)
                entry["variants"][phrase] += 1
                entry["source_types"].add("role_bullet")

    current_section = ""
    for raw_line in source_text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        if raw_line.lstrip().startswith("#"):
            current_section = line.lower()
            continue
        section_kind = _section_kind(current_section)
        if section_kind == "ignore":
            continue
        if section_kind == "experience" and _extract_year_range(line):
            continue
        weight = 3.0 if section_kind == "skills" else 0.7
        for phrase in _phrase_variants_from_text(line):
            entry = stats[phrase]
            entry["score"] += weight
            entry["variants"][phrase] += 1
            entry["source_types"].add(section_kind or "other")
    return stats


def _rank_phrase_items(stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for phrase, item in stats.items():
        roles = len(item["roles"])
        recent_roles = len(item["recent_roles"])
        score = float(item["score"]) + (roles * 0.8) + (recent_roles * 0.6)
        ranked.append(
            {
                "phrase": phrase,
                "score": score,
                "roles": roles,
                "recent_roles": recent_roles,
                "variants": [variant for variant, _ in item["variants"].most_common(6)],
                "source_types": set(item["source_types"]),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], -item["roles"], item["phrase"]))
    return ranked


def _parse_capabilities(source_text: str) -> list[dict[str, Any]]:
    source_text = repair_text(source_text)
    if not source_text:
        return []

    roles = _parse_role_entries(source_text)
    ranked = _rank_phrase_items(_collect_phrase_stats(source_text, roles))
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in ranked:
        phrase = item["phrase"]
        if phrase in seen:
            continue
        if item["source_types"] == {"role_title"}:
            continue
        if _is_generic_title_phrase(phrase):
            continue
        min_score = 2.0 if "skills" in item["source_types"] else 3.0
        if item["score"] < min_score:
            continue
        seen.add(phrase)

        if item["score"] >= 8 or item["roles"] >= 3:
            level = "strong"
        elif item["score"] >= 5 or item["roles"] >= 2:
            level = "working"
        else:
            level = "basic"

        if item["roles"] >= 2 and item["recent_roles"] >= 1:
            fit = "core"
        elif item["score"] >= 4:
            fit = "supporting"
        else:
            fit = "contextual"

        aliases = [variant for variant in item["variants"] if variant != phrase][:6]
        capabilities.append(
            {
                "name": phrase,
                "level": level if level in _VALID_LEVELS else "basic",
                "fit": fit if fit in _VALID_FITS else "contextual",
                "aliases": aliases,
            }
        )
        if len(capabilities) >= 12:
            break
    return _apply_llm_capability_names(capabilities)


def _parse_capabilities_llm_legacy(source_text: str) -> list[dict[str, Any]]:
    """Extract capability rules from any CV using the LLM.

    Works for any profession and CV format — no hardcoded headings.
    Returns [] if LLM is unavailable (no API key); caller handles the fallback.
    """
    from llm_gate import client, _get_llm_model, MAX_TOKENS_CV_EXTRACTION

    if client is None:
        print("[CAPABILITIES] Skipped — no LLM client (OPENAI_API_KEY not set)")
        return []
    if not (source_text or "").strip():
        return []

    prompt = (
        "Read this CV and extract the candidate's professional capabilities.\n\n"
        "Return a JSON array. Each item must have exactly these keys:\n"
        '  "name"    — short capability label in lowercase\n'
        '  "level"   — one of: strong | working | basic | low | none\n'
        '              (based on recency and depth of use, not just whether it appears)\n'
        '  "fit"     — one of: core | supporting | contextual | avoid\n'
        '              core = daily job, supporting = used regularly, contextual = occasionally, avoid = not wanted\n'
        '  "aliases" — list of 4–10 lowercase phrases a job ad would use for this skill\n\n'
        "Rules:\n"
        "- Prefer broad, transferable capability clusters over single tools or platforms\n"
        "- Do NOT include incidental tools mentioned once unless they were a major recurring responsibility\n"
        "- Include 6–15 capabilities that represent the full professional picture\n"
        "- Aliases must be job-ad language, not CV phrasing\n"
        "- Do NOT include soft skills — only professional capabilities\n"
        "- Only return the JSON array, no explanation\n\n"
        "CV:\n" + source_text[:5000]
    )

    try:
        resp = client.responses.create(
            model=_get_llm_model(),
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=MAX_TOKENS_CV_EXTRACTION,
        )
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            print(f"[CAPABILITIES] LLM returned non-list: {type(items)}")
            return []

        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            level = str(item.get("level") or "").strip().lower()
            fit = str(item.get("fit") or "").strip().lower()
            aliases = [
                str(a).strip().lower()
                for a in (item.get("aliases") or [])
                if str(a).strip()
            ]
            if not name or level not in _VALID_LEVELS or fit not in _VALID_FITS:
                continue
            result.append({"name": name, "level": level, "fit": fit, "aliases": aliases[:10]})

        print(f"[CAPABILITIES] Extracted {len(result)} capability rules via LLM")
        return result[:15]

    except Exception as exc:
        print(f"[CAPABILITIES] LLM extraction failed: {exc}")
        return []


def _apply_llm_capability_names(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not capabilities:
        return []
    try:
        from llm_gate import name_capability_clusters

        labels = name_capability_clusters(capabilities)
    except Exception:
        return capabilities

    if not labels:
        return capabilities

    renamed: list[dict[str, Any]] = []
    for capability, label in zip(capabilities, labels):
        updated = dict(capability)
        cleaned = _normalize_phrase(label)
        if not _is_quality_phrase(cleaned) or _is_generic_title_phrase(cleaned):
            renamed.append(updated)
            continue
        original_name = str(updated.get("name") or "").strip().lower()
        if cleaned and cleaned != original_name:
            aliases = [original_name, *updated.get("aliases", [])]
            deduped_aliases: list[str] = []
            seen_aliases: set[str] = {cleaned}
            for alias in aliases:
                normalized_alias = _normalize_phrase(alias)
                if not normalized_alias or normalized_alias in seen_aliases:
                    continue
                seen_aliases.add(normalized_alias)
                deduped_aliases.append(normalized_alias)
            updated["name"] = cleaned
            updated["aliases"] = deduped_aliases[:6]
        renamed.append(updated)

    if len(capabilities) > len(labels):
        renamed.extend(dict(item) for item in capabilities[len(labels):])
    return renamed


def _parse_summary(source_text: str) -> str:
    experience = _extract_section(source_text, "EXPERIENCE SUMMARY (REALITY BASELINE)")
    roles = _extract_bullets(_extract_section(source_text, "EXPERIENCE SUMMARY (REALITY BASELINE)"))
    primary_strength_match = re.search(r"Primary strength:\s*(.+)", _extract_section(source_text, "CORE STRENGTH IDENTITY"), flags=re.IGNORECASE)
    years_match = re.search(r"Years in IT:\s*([^\n]+)", experience, flags=re.IGNORECASE)

    parts = []
    if years_match:
        parts.append(f"{_clean_sentence(years_match.group(1))} in IT")
    if roles:
        parts.append("Primary roles: " + ", ".join(roles[:3]))
    if primary_strength_match:
        parts.append(_clean_sentence(primary_strength_match.group(1)).replace("->", "").replace(">", ""))
    summary = ". ".join(part.strip(". ") for part in parts if part).strip()
    if summary:
        return summary

    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    headers = {
        "executive summary",
        "professional summary",
        "summary",
        "profile",
        "career profile",
    }
    for index, line in enumerate(lines):
        if line.lower().lstrip("#").strip().rstrip(":") not in headers:
            continue
        collected: list[str] = []
        for candidate in lines[index + 1:]:
            normalized = candidate.strip()
            lowered = normalized.lower().lstrip("#").strip().rstrip(":")
            if lowered in headers:
                break
            if normalized.startswith("#"):
                break
            if len(normalized.split()) <= 8 and normalized.upper() == normalized:
                break
            collected.append(normalized)
            if len(" ".join(collected)) >= 420:
                break
        if collected:
            return " ".join(collected)[:500].strip()
    return ""




def build_learning_patch(text: str) -> dict[str, Any]:
    source_text = repair_text(text)
    if not source_text:
        return {}

    patch: dict[str, Any] = {
        "cv_text": source_text,
    }

    summary = _parse_summary(source_text)
    if summary:
        patch["candidate_summary"] = summary

    evidence_signals = derive_evidence_signals(source_text)
    if evidence_signals:
        patch["evidence_signals"] = evidence_signals

    capability_rules = _parse_capabilities(source_text)
    if capability_rules:
        patch["capability_profile_rules"] = capability_rules

    return patch


def derive_evidence_signals(source_text: str) -> list[str]:
    source_text = repair_text(source_text)
    if not source_text:
        return []
    roles = _parse_role_entries(source_text)
    ranked = _rank_phrase_items(_collect_phrase_stats(source_text, roles))
    signals: list[str] = []
    seen: set[str] = set()

    for role in roles:
        title = _normalize_phrase(role.get("title", ""))
        if title and title not in seen:
            seen.add(title)
            signals.append(title)

    for item in ranked:
        phrase = item["phrase"]
        if phrase in seen or item["score"] < 2.0:
            continue
        seen.add(phrase)
        signals.append(phrase)
        if len(signals) >= 20:
            break
    return signals[:20]


def extract_title_pattern_suggestions(source_text: str, onboarding_settings: dict | None = None) -> dict[str, list[str]]:
    source_text = repair_text(source_text)
    settings = onboarding_settings or {}
    lookback_years = max(1, int(settings.get("title_extraction_lookback_years") or 8))
    min_months = max(1, int(settings.get("title_extraction_min_months") or 6))
    max_target = max(1, int(settings.get("max_target_patterns") or 8))
    max_adjacent = max(1, int(settings.get("max_adjacent_patterns") or 6))
    roles = _parse_role_entries(source_text)

    target_titles: list[str] = []
    adjacent_titles: list[str] = []
    suggested_keywords: list[str] = []
    recent_cutoff = _CURRENT_YEAR - lookback_years

    for role in roles:
        title = _clean_line(role.get("title", ""))
        if not title:
            continue
        simplified = _simplify_title(title)
        end_year = int(role.get("end_year", 0) or 0)
        duration_months = int(role.get("duration_months", 0) or 0)
        recent_enough = end_year >= recent_cutoff and duration_months >= min_months

        if recent_enough:
            target_titles.append(title)
            if simplified and simplified != _normalize_phrase(title):
                target_titles.append(simplified)
            suggested_keywords.append(simplified or _normalize_phrase(title))
        else:
            adjacent_titles.append(title)
            if simplified:
                adjacent_titles.append(simplified)

    def _dedupe_patterns(titles: list[str], limit: int) -> list[str]:
        patterns: list[str] = []
        seen_patterns: set[str] = set()
        for title in titles:
            pattern = _make_title_pattern(title)
            if pattern and pattern not in seen_patterns:
                seen_patterns.add(pattern)
                patterns.append(pattern)
            if len(patterns) >= limit:
                break
        return patterns

    deduped_keywords: list[str] = []
    seen_keywords: set[str] = set()
    for keyword in suggested_keywords:
        cleaned = _normalize_phrase(keyword)
        if not cleaned or cleaned in seen_keywords:
            continue
        seen_keywords.add(cleaned)
        deduped_keywords.append(cleaned)
        if len(deduped_keywords) >= 4:
            break

    return {
        "target_title_patterns": _dedupe_patterns(target_titles, max_target),
        "adjacent_title_patterns": _dedupe_patterns(adjacent_titles, max_adjacent),
        "suggested_search_keywords": deduped_keywords,
    }


def merge_capability_rules(existing: list[dict[str, Any]], learned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rule in existing or []:
        name = str(rule.get("name") or "").strip().lower()
        if name:
            merged[name] = dict(rule)
    for rule in learned or []:
        name = str(rule.get("name") or "").strip().lower()
        if name:
            merged[name] = dict(rule)
    return list(merged.values())
