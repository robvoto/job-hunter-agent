"""Profile learning helpers.

Main goals:
- repair imported text
- extract summaries, notes, and capability rules from human material
- provide a local knowledge-note fallback for profile enrichment

Notes:
- capability_profile.txt is a local editable knowledge note
- capability_profile.template.txt is the committed starter template for new users
"""

from collections import Counter, defaultdict
from datetime import datetime
import re
from typing import Any

from job_hunter_agent.paths import DATA_DIR, REPO_ROOT
from job_hunter_agent.profile_store import DEFAULT_ONBOARDING_SETTINGS


ROOT_DIR = REPO_ROOT


def repair_text(text: str) -> str:
    if not text:
        return ""
    repaired = text.replace("\r\n", "\n")
    if "Ã¢" in repaired or "Ãƒ" in repaired:
        try:
            candidate = repaired.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            if candidate.count("Ã¢") < repaired.count("Ã¢"):
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


def _resolve_onboarding_int(
    onboarding_settings: dict[str, Any] | None,
    key: str,
    *,
    minimum: int = 1,
) -> int:
    settings = onboarding_settings or {}
    value = settings.get(key)
    if value not in (None, ""):
        try:
            return max(minimum, int(value))
        except Exception:
            pass
    return max(minimum, int(DEFAULT_ONBOARDING_SETTINGS[key]))


def _resolve_extraction_lookback_years(onboarding_settings: dict[str, Any] | None = None) -> int:
    return _resolve_onboarding_int(onboarding_settings, "extraction_lookback_years")


def _extract_section(text: str, header: str) -> str:
    pattern = rf"##\s+{re.escape(header)}\s*\n(.*?)(?=\n##\s+|\Z)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


 

def _extract_bullets(text: str) -> list[str]:
    return [match.strip() for match in re.findall(r"^\*\s+(.+)$", text, flags=re.MULTILINE)]


def _clean_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -\n")


_VALID_LEVELS = {"strong", "working", "basic", "low", "none"}
_VALID_FITS = {"core", "supporting", "contextual", "avoid"}
_CURRENT_YEAR = datetime.now().year
_CURRENT_MONTH = datetime.now().month
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
    "architect", "officer", "director", "administrator", "owner", "lead", "executive", "master",
    "head", "staff", "project", "business",
}
_EMPLOYER_MARKERS = {
    "bank", "group", "consulting", "services", "solutions", "systems", "technology", "technologies",
    "university", "college", "school", "council", "government", "department", "agency", "institute",
    "pty", "ltd", "llc", "inc", "corp", "corporation", "company", "limited", "holdings", "partners",
    "association", "authority", "commission", "office", "hospital", "health", "care", "trust",
}
_TITLE_PATTERN_ANCHOR_NOUNS = {
    "analyst",
    "manager",
    "coordinator",
    "consultant",
    "specialist",
    "developer",
    "engineer",
    "architect",
    "officer",
    "director",
    "administrator",
    "lead",
    "master",
}
_MONTH_NAME_TO_NUMBER = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_TOKEN_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DATE_RANGE_PATTERN = re.compile(
    rf"(?:(?P<start_month>{_MONTH_TOKEN_PATTERN})\s*[.,]?\s*)?"
    rf"(?P<start_year>(?:19|20)\d{{2}})"
    rf"\s*(?:-|–|—|to|/)\s*"
    rf"(?:(?P<end_month>{_MONTH_TOKEN_PATTERN})\s*[.,]?\s*)?"
    rf"(?:(?P<end_year>(?:19|20)\d{{2}})|(?P<end_relative>present|current|now|ongoing))",
    flags=re.IGNORECASE,
)


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
    match = _DATE_RANGE_PATTERN.search(str(text or ""))
    if not match:
        return None
    start_year = int(match.group("start_year"))
    start_month_name = str(match.group("start_month") or "").strip().lower()
    end_month_name = str(match.group("end_month") or "").strip().lower()
    raw_end_relative = str(match.group("end_relative") or "").strip().lower()
    is_current = raw_end_relative in {"present", "current", "now", "ongoing"}
    end_year = _CURRENT_YEAR if is_current else int(match.group("end_year"))
    start_month = _MONTH_NAME_TO_NUMBER.get(start_month_name, 1)
    if is_current:
        end_month = _CURRENT_MONTH
    else:
        end_month = _MONTH_NAME_TO_NUMBER.get(end_month_name, 12)
    duration_months = max(((end_year - start_year) * 12) + (end_month - start_month) + 1, 1)
    return {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
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


def _title_signal_score(text: str) -> int:
    cleaned = _clean_line(text)
    tokens = [_normalize_token(token) for token in cleaned.split()]
    if not cleaned:
        return 0
    score = 0
    if _looks_like_title(cleaned):
        score += 1
    score += sum(2 for token in tokens if token in _GENERIC_ROLE_NOUNS)
    score += sum(1 for token in tokens if token in _TITLE_MODIFIERS)
    if len(tokens) <= 6:
        score += 1
    if re.search(r"[,&/]", cleaned):
        score += 1
    return score


def _employer_signal_score(text: str) -> int:
    cleaned = _clean_line(text)
    tokens = [_normalize_token(token) for token in cleaned.split()]
    if not cleaned:
        return 0
    score = 0
    score += sum(2 for token in tokens if token in _EMPLOYER_MARKERS)
    if cleaned.isupper() and len(tokens) <= 5:
        score += 1
    if "&" in cleaned:
        score += 1
    return score


def _is_plausible_role_title(text: str) -> bool:
    cleaned = _clean_line(text)
    if not _looks_like_title(cleaned):
        return False

    normalized = _normalize_phrase(cleaned)
    tokens = [_normalize_token(token) for token in cleaned.split()]
    tokens = [token for token in tokens if token]
    if not normalized or not tokens:
        return False
    if tokens[0] in _GENERIC_PHRASE_STOPWORDS:
        return False
    if normalized in _GENERIC_PHRASE_BLACKLIST:
        return False

    has_role_signal = any(token in _GENERIC_ROLE_NOUNS or token in _TITLE_PATTERN_ANCHOR_NOUNS for token in tokens)
    if not has_role_signal:
        return False

    if _employer_signal_score(cleaned) >= 2 and not any(token in _TITLE_PATTERN_ANCHOR_NOUNS for token in tokens):
        return False

    return True


def _pick_role_title_and_employer(candidate_lines: list[str], prefer_prefix_order: bool = False) -> tuple[str, str]:
    if not candidate_lines:
        return "", ""
    if len(candidate_lines) == 1:
        only = candidate_lines[0]
        return (only, "") if _looks_like_title(only) else ("", only)

    first = candidate_lines[0]
    second = candidate_lines[1]
    first_title_score = _title_signal_score(first)
    second_title_score = _title_signal_score(second)
    first_employer_score = _employer_signal_score(first)
    second_employer_score = _employer_signal_score(second)

    first_beats_second = (
        first_title_score > second_title_score and second_employer_score >= first_employer_score
    )
    second_beats_first = (
        second_title_score > first_title_score and first_employer_score >= second_employer_score
    )

    if first_beats_second:
        return first, second
    if second_beats_first:
        return second, first

    if first_title_score > second_title_score:
        return first, ""
    if second_title_score > first_title_score:
        return second, ""

    if prefer_prefix_order and _looks_like_title(first):
        return first, second
    if _looks_like_title(second) and not _looks_like_title(first):
        return second, first
    if _looks_like_title(first):
        return first, ""
    if _looks_like_title(second):
        return second, ""
    return "", ""


def _parse_role_entries(source_text: str) -> list[dict[str, Any]]:
    lines = source_text.splitlines()
    roles: list[dict[str, Any]] = []
    current_section = ""
    i = 0

    inline_role_re = re.compile(
        rf"^(?P<employer>.+?)\s*-\s*(?P<title>.+?)\s*\((?P<dates>.*?(?:{_MONTH_TOKEN_PATTERN}\s*[.,]?\s*)?(?:19|20)\d{{2}}.*?(?:present|current|now|ongoing|(?:{_MONTH_TOKEN_PATTERN}\s*[.,]?\s*)?(?:19|20)\d{{2}}))\)\s*$",
        flags=re.IGNORECASE,
    )
    title_with_dates_re = re.compile(
        rf"^(?P<title>.+?)\s*\((?P<dates>.*?(?:{_MONTH_TOKEN_PATTERN}\s*[.,]?\s*)?(?:19|20)\d{{2}}.*?(?:present|current|now|ongoing|(?:{_MONTH_TOKEN_PATTERN}\s*[.,]?\s*)?(?:19|20)\d{{2}}))\)\s*$",
        flags=re.IGNORECASE,
    )

    def collect_role_detail_lines(start_index: int) -> tuple[list[str], int]:
        details: list[str] = []
        j = start_index
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
                details.append(_clean_line(re.sub(r"^[-*]\s*", "", look_raw)))
            else:
                details.append(look)
            j += 1
        return details, j

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
            bullets, j = collect_role_detail_lines(i + 1)
            if date_info:
                inline_left = _clean_line(inline_match.group("employer"))
                inline_right = _clean_line(inline_match.group("title"))
                title, employer = _pick_role_title_and_employer(
                    [inline_left, inline_right],
                    prefer_prefix_order=False,
                )
                if not title:
                    title = inline_right
                    employer = inline_left
                if not _is_plausible_role_title(title) and _is_plausible_role_title(employer):
                    title, employer = employer, title
                if not _is_plausible_role_title(title):
                    i = max(j, i + 1)
                    continue
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
            continue

        title_with_dates_match = title_with_dates_re.match(cleaned)
        if title_with_dates_match and _section_kind(current_section) != "ignore":
            date_info = _extract_year_range(title_with_dates_match.group("dates"))
            if date_info:
                title = _clean_line(title_with_dates_match.group("title"))
                if not _is_plausible_role_title(title):
                    i += 1
                    continue
                bullets, j = collect_role_detail_lines(i + 1)
                roles.append(
                    {
                        "title": title,
                        "employer": "",
                        "section": current_section,
                        "bullets": bullets,
                        **date_info,
                    }
                )
            i = max(j, i + 1)
            continue

        date_info = _extract_year_range(cleaned)
        if not date_info or _section_kind(current_section) == "ignore":
            i += 1
            continue

        prefix_candidate_lines: list[str] = []
        k = i - 1
        while k >= 0 and len(prefix_candidate_lines) < 3:
            look_back_raw = lines[k].strip()
            look_back = _clean_line(look_back_raw)
            if not look_back:
                break
            if look_back_raw.lstrip().startswith("#") or look_back_raw.lstrip().startswith(("-", "*")):
                break
            if _extract_year_range(look_back):
                break
            prefix_candidate_lines.append(look_back)
            k -= 1
        prefix_candidate_lines.reverse()

        candidate_lines: list[str] = list(prefix_candidate_lines)
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

        using_prefix_fallback = bool(prefix_candidate_lines) and candidate_lines[:len(prefix_candidate_lines)] == prefix_candidate_lines
        title, employer = _pick_role_title_and_employer(candidate_lines, prefer_prefix_order=using_prefix_fallback)
        if title and not _is_plausible_role_title(title):
            plausible_candidates = [line for line in candidate_lines if _is_plausible_role_title(line)]
            if plausible_candidates:
                title = plausible_candidates[0]
                employer = next((line for line in candidate_lines if line != title), "")
            else:
                title = ""

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

 

def _make_title_pattern(title: str) -> str:
    normalized = _clean_line(title).lower()
    return rf"\b{re.escape(normalized)}\b" if normalized else ""


def _contains_role_noun(text: str) -> bool:
    tokens = [_normalize_token(token) for token in _clean_line(text).split()]
    return any(token in _GENERIC_ROLE_NOUNS for token in tokens)


def _title_pattern_candidates(title: str) -> list[str]:
    cleaned = _clean_line(title)
    if not cleaned:
        return []

    seen: set[str] = set()
    candidates: list[str] = []

    def push(value: str) -> None:
        candidate = _clean_line(value)
        normalized = _normalize_phrase(candidate)
        if not candidate or not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(candidate)

    base_title = _clean_line(re.sub(r"\([^)]*\)", "", cleaned))
    if not base_title:
        return []

    components: list[str] = [base_title]
    if " - " in base_title:
        left, right = [part.strip() for part in base_title.split(" - ", 1)]
        if left and right and not _contains_role_noun(right):
            components.append(left)

    split_components: list[str] = []
    for component in components:
        if "/" in component:
            split_components.extend(
                _clean_line(part)
                for part in re.split(r"\s*/\s*", component)
                if _clean_line(part)
            )
            continue
        split_components.append(component)

    for component in split_components:
        tokens = [_normalize_token(token) for token in component.split()]
        tokens = [token for token in tokens if token and token != "&"]
        if len(tokens) == 1 and tokens[0] in _GENERIC_ROLE_NOUNS:
            continue

        for index, token in enumerate(tokens):
            if token not in _TITLE_PATTERN_ANCHOR_NOUNS:
                continue
            if index >= 1:
                push(" ".join(tokens[index - 1:index + 1]))
            if index >= 2 and tokens[index - 2] in _TITLE_MODIFIERS:
                push(" ".join(tokens[index - 2:index + 1]))

        if len(tokens) <= 3 and any(token in _TITLE_PATTERN_ANCHOR_NOUNS for token in tokens):
            push(" ".join(tokens))

    return candidates


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


def _collect_phrase_stats(
    source_text: str,
    roles: list[dict[str, Any]],
    onboarding_settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "score": 0.0,
            "roles": set(),
            "recent_roles": set(),
            "variants": Counter(),
            "source_types": set(),
        }
    )
    recent_cutoff = _CURRENT_YEAR - _resolve_extraction_lookback_years(onboarding_settings)

    for role in roles:
        role_key = f"{role.get('title','')}|{role.get('start_year','')}"
        recent = int(role.get("end_year", 0) or 0) >= recent_cutoff
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


def _parse_capabilities(
    source_text: str,
    onboarding_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_text = repair_text(source_text)
    if not source_text:
        return []

    roles = _parse_role_entries(source_text)
    ranked = _rank_phrase_items(_collect_phrase_stats(source_text, roles, onboarding_settings=onboarding_settings))
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
        if len(capabilities) >= 20:
            break
    return _apply_llm_capability_names(capabilities)


def _apply_llm_capability_names(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not capabilities:
        return []
    try:
        from job_hunter_agent.llm_gate import name_capability_clusters

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


def _extract_match_preferences(text: str) -> dict[str, Any]:
    """Extract candidate preferences/warnings from the source text."""
    prefs = {}
    lowered = text.lower()

    # Engagement Preference
    if re.search(r"\b(permanent only|no contracts|prefer permanent|seeking permanent)\b", lowered):
        prefs["prefer_permanent"] = True
    elif re.search(r"\b(contract only|prefer contracts|freelance|interim)\b", lowered):
        prefs["prefer_permanent"] = False

    # Work Mode
    if re.search(r"\b(remote only|100% remote|work from home only)\b", lowered):
        prefs["work_mode_preference"] = "remote"
    elif re.search(r"\b(hybrid|flexible working|mix of office and home)\b", lowered):
        prefs["work_mode_preference"] = "hybrid"

    # Location hint (e.g., "Based in Melbourne" or "Home base: Sydney")
    loc = extract_location_hint(text)
    if loc:
        prefs["home_location"] = loc

    return prefs


def extract_location_hint(text: str) -> str:
    """Extract a home location hint from text (e.g. 'Based in Melbourne')."""
    match = re.search(
        r"(?i)\b(?:based in|location|reside in|lives in|home base|resident of):\s*([A-Za-z\s,]+?)(?=\n|[,.]?\s+and\b|[,.]?\s+with\b|[.!?]|\s{2,}|\Z)",
        text
    )
    if match:
        loc = match.group(1).strip()
        # Cleanup trailing geographical noise
        loc = re.sub(r"(?i)[,\s]+(australia|vic|nsw|qld|wa|sa|tas|act|nt)$", "", loc).strip()
        if 2 < len(loc) < 60:
            return loc
    return ""


def build_learning_patch(
    text: str,
    onboarding_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_text = repair_text(text)
    if not source_text:
        return {}

    patch: dict[str, Any] = {
        "cv_text": source_text,
    }

    capability_rules = _parse_capabilities(source_text, onboarding_settings=onboarding_settings)
    if capability_rules:
        patch["capability_profile_rules"] = capability_rules

    match_prefs = _extract_match_preferences(source_text)
    if match_prefs:
        patch["match_preferences"] = match_prefs

    return patch


def extract_title_pattern_suggestions(source_text: str, onboarding_settings: dict | None = None) -> dict[str, list[str]]:
    source_text = repair_text(source_text)
    settings = onboarding_settings or {}
    lookback_years = _resolve_extraction_lookback_years(settings)
    min_months = _resolve_onboarding_int(settings, "title_extraction_min_months")
    max_target = _resolve_onboarding_int(settings, "max_target_patterns")
    max_secondary = _resolve_onboarding_int(settings, "max_secondary_patterns")
    roles = _parse_role_entries(source_text)

    target_titles: list[str] = []
    secondary_titles: list[str] = []
    suggested_keywords: list[str] = []
    recent_cutoff = _CURRENT_YEAR - lookback_years
    strong_role_titles: list[str] = []
    supporting_role_titles: list[str] = []

    for role in roles:
        title = _clean_line(role.get("title", ""))
        if not title:
            continue
        pattern_candidates = _title_pattern_candidates(title)
        end_year = int(role.get("end_year", 0) or 0)
        duration_months = int(role.get("duration_months", 0) or 0)
        in_lookback = end_year >= recent_cutoff

        if not in_lookback:
            # STRICT LOOKBACK: Ignore roles that fall outside the extraction window.
            continue

        if duration_months >= min_months:
            strong_role_titles.extend(pattern_candidates or [title])
        else:
            supporting_role_titles.extend(pattern_candidates or [title])

    # Use only the first couple of strong recent titles as direct targets.
    # Other valid titles still matter, but they belong in the softer bucket so
    # the app does not treat every past role as a primary search direction.
    direct_target_limit = max(1, min(2, max_target))
    target_titles.extend(strong_role_titles[:direct_target_limit])
    secondary_titles.extend(strong_role_titles[direct_target_limit:])
    secondary_titles.extend(supporting_role_titles)
    suggested_keywords.extend(target_titles[:2])

    def _dedupe_patterns(titles: list[str], limit: int, exclude: set[str] | None = None) -> list[str]:
        patterns: list[str] = []
        seen_patterns: set[str] = set()
        blocked = exclude or set()
        for title in titles:
            pattern = _make_title_pattern(title)
            if pattern and pattern not in seen_patterns and pattern not in blocked:
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

    target_patterns = _dedupe_patterns(target_titles, max_target)
    secondary_patterns = _dedupe_patterns(secondary_titles, max_secondary, exclude=set(target_patterns))

    return {
        "target_title_patterns": target_patterns,
        "secondary_title_patterns": secondary_patterns,
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
