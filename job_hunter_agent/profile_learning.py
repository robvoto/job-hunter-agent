"""Profile learning helpers.

Main goals:
- repair imported text
- extract capabilities and title patterns from CV text via LLM
- structural parsing (sections, dates, roles) shared with other pipeline modules
"""

import hashlib
import json
import re
from functools import lru_cache
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from job_hunter_agent.paths import OUTPUT_DIR, REPO_ROOT, PARSING_RULES_PATH
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    KEY_CV_TEXT,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_MATCH_PREFS,
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
    KEY_LOOKBACK_YEARS,
    KEY_MIN_MONTHS,
    KEY_MAX_TARGET,
    KEY_MAX_SECONDARY,
    KEY_NAME,
    KEY_LEVEL,
    KEY_ALIASES,
    KEY_NEEDS_REVIEW,
    LEVEL_STRONG,
    LEVEL_WORKING,
    LEVEL_BASIC,
    LEVEL_LOW,
)
from job_hunter_agent.role_title_knowledge import load_role_title_knowledge
from job_hunter_agent.title_normalization_rules import (
    derive_base_title_from_seniority,
    learn_title_normalization_candidates,
    load_title_normalization_rules,
    normalize_title_text,
)
from job_hunter_agent.signal_registry import register_signals, signal_in_approved_knowledge
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_ROLE_TITLE_TOKEN,
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    LEARNING_CATEGORY_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_KNOWLEDGE_MATCH_KEY,
    LEARNING_CONTEXT_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    SOURCE_CV_PARSING,
)

ROOT_DIR = REPO_ROOT
CAP_DEBUG_LOG = OUTPUT_DIR / "capability_debug.log"

# Internal result keys
KEY_CAPABILITIES = "capabilities"
KEY_SUGGESTED_KEYWORDS = "suggested_search_keywords"

# Signal categories
CAT_CAPABILITY = CATEGORY_CAPABILITY_CONCEPT
CAT_ROLE_TITLE = CATEGORY_ROLE_TITLE_TOKEN
CAT_TITLE_NORM = CATEGORY_TITLE_NORMALIZATION_CANDIDATE
KEY_TITLE_PARSE_BLOCKERS = "title_parse_blockers"

_VALID_LEVELS = {LEVEL_STRONG, LEVEL_WORKING, LEVEL_BASIC, LEVEL_LOW}
_CURRENT_YEAR = datetime.now().year


def _cap_log(msg: str) -> None:
    print(msg)
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with CAP_DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception as exc:
        print(f"[CAP_LOG ERROR] could not write capability_debug.log: {exc}")


def clear_capability_debug_log() -> None:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        CAP_DEBUG_LOG.write_text(
            f"# capability_debug.log — onboarding run {datetime.now().isoformat()}Z\n",
            encoding="utf-8",
        )
        print(f"[CAP_LOG] capability_debug.log reset at {CAP_DEBUG_LOG}")
    except Exception as exc:
        print(f"[CAP_LOG ERROR] could not reset capability_debug.log: {exc}")


_CURRENT_MONTH = datetime.now().month
_MONTH_NAME_TO_NUMBER = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
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

_BULLET_PREFIX_RE = re.compile(r"^[\-*•–—]+\s*")

_cv_extraction_cache: dict[str, dict[str, Any]] = {}


@lru_cache(maxsize=1)
def _load_generic_role_tokens() -> frozenset[str]:
    """Load a list of job role words (like 'manager' or 'engineer') from saved settings.

    Normalization includes:
    - Lowercasing and removing non-standard punctuation.
    - Basic singularization (stripping 's', converting 'ies' to 'y') to improve match rates.
    What it does:
    1. It reads words from the file 'data/role_title_knowledge.json'.
    2. It cleans them by making them lowercase and removing symbols.
    3. It simplifies plural words: it turns 'engineers' into 'engineer' and 'consultancies' 
       into 'consultancy'. This ensures the system recognizes the role even if the 
       CV uses a plural version. It only does this for words longer than 4 letters 
       and avoids words like 'boss' to prevent breaking them.

    Caching:
    The result is cached using @lru_cache(maxsize=1). Since this function takes no
    arguments, it effectively computes the normalized set once per process. This
    avoids repeated disk I/O and regex overhead during high-frequency CV parsing.
    Examples:
    It looks for core role words like 'analyst', 'developer', or 'officer'. It does 
    NOT look for seniority words like 'senior' or 'junior' (those are handled elsewhere).

    Returns:
        A frozenset of normalized, singularized role tokens.
    How the cache works:
    The '@lru_cache' tells the computer to remember the final list in its memory. This 
    way, it only has to read the file and clean the words once. When it scans your CV, 
    it reuses that memory instead of doing the work over and over, making it much faster.
    """
    try:
        entries = load_role_title_knowledge()
    except Exception:
        return frozenset()

    tokens: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = str(entry.get("value") or "").strip()
        token = re.sub(r"[^a-z0-9+#/&-]", "", value.lower()).strip("-/")
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 4 and not token.endswith("ss") and not token.endswith("is"):
            token = token[:-1]
        if token:
            tokens.append(token)
    return frozenset(tokens)


def _generic_role_tokens() -> frozenset[str]:
    return _load_generic_role_tokens()


def _has_approved_role_title_token(text: str) -> bool:
    return any(token in _generic_role_tokens() for token in _pattern_tokens(text))


def _load_title_seniority_modifiers() -> frozenset[str]:
    try:
        rules = load_title_normalization_rules()
    except Exception:
        return frozenset()
    modifiers = rules.get("seniority_modifiers")
    if not isinstance(modifiers, list):
        return frozenset()
    return frozenset(
        _normalize_token(value)
        for value in modifiers
        if _normalize_token(value)
    )


class _CapabilityExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: Literal[LEVEL_STRONG, LEVEL_WORKING, LEVEL_BASIC]
    aliases: list[str] = Field(default_factory=list)
    needs_review: bool = False


class _MatchPreferenceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_permanent: bool | None = None
    work_mode_preference: Literal["remote", "hybrid", "onsite"] | None = None
    home_location: str = ""


class _CvExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[_CapabilityExtraction] = Field(default_factory=list)
    match_preferences: _MatchPreferenceExtraction = Field(default_factory=_MatchPreferenceExtraction)


# ── Text repair ────────────────────────────────────────────────────────────────

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
    for source, target in {"—": "-", "–": "-", "→": "->"}.items():
        repaired = repaired.replace(source, target)
    return repaired.strip()


# ── Settings resolution ────────────────────────────────────────────────────────

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
    return _resolve_onboarding_int(onboarding_settings, KEY_LOOKBACK_YEARS)


# ── Text utilities ─────────────────────────────────────────────────────────────

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
    return " ".join(token for token in tokens if token).strip()


# ── Structural parsing helpers ─────────────────────────────────────────────────

def _is_bullet_line(text: str) -> bool:
    return bool(_BULLET_PREFIX_RE.match(str(text or "").lstrip()))


def _is_heading_line(text: str) -> bool:
    return str(text or "").lstrip().startswith("#")


def _is_plain_section_label(text: str) -> bool:
    cleaned = _clean_line(text)
    if not cleaned:
        return False
    if cleaned.lower().startswith("key achievement:"):
        return True
    letters = re.sub(r"[^A-Za-z]+", "", cleaned)
    words = cleaned.split()
    return bool(letters) and cleaned == cleaned.upper() and len(words) <= 4

@lru_cache(maxsize=1)
def _load_parsing_rules() -> dict[str, Any]:
    """Load parsing heuristics from JSON."""
    if not PARSING_RULES_PATH.exists():
        return {}
    try:
        return json.loads(PARSING_RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

def get_parsing_rule_set(key: str) -> set[str]:
    rules = _load_parsing_rules()
    items = rules.get(key)
    if isinstance(items, list):
        return {str(item).lower().strip() for item in items if item}
    return set()



def _looks_like_role_title_line(text: str) -> bool:
    cleaned = _clean_line(text)
    if not cleaned:
        return False
    if len(cleaned) > 80:
        return False
    if cleaned.endswith(".") or "," in cleaned:
        return False
    normalized = _normalize_role_title_value(cleaned)
    tokens = _pattern_tokens(normalized)
    if not tokens or len(tokens) > 7:
        return False
    if tokens[0] in get_parsing_rule_set(KEY_TITLE_PARSE_BLOCKERS):
        return False
    if _has_approved_role_title_token(normalized):
        return True
    # ── SEALED: do not weaken this guard ──────────────────────────────────────
    # Multi-word lines that contain no recognised role token are almost always
    # company names (e.g. "TechCorp (contract)", "Digital Solutions Group") or
    # description fragments — not job titles.  Weakening this check causes
    # company names to be promoted to title patterns, which breaks extraction
    # every time the test CV is re-processed.  See TITLE_SELECTION_RATIONALE.md.
    return False


def _select_role_title_and_employer(candidate_lines: list[str]) -> tuple[str, str]:
    title = ""
    employer = ""
    title_indexes = [index for index, line in enumerate(candidate_lines) if _looks_like_role_title_line(line)]
    if not title_indexes:
        return title, employer

    strong_title_indexes = [
        index
        for index, line in enumerate(candidate_lines)
        if any(token in _generic_role_tokens() for token in _pattern_tokens(line))
    ]
    if strong_title_indexes:
        title_index = strong_title_indexes[0]
    else:
        title_index = title_indexes[0]

    title = candidate_lines[title_index]
    for index in range(title_index - 1, -1, -1):
        line = candidate_lines[index]
        if line != title and not _looks_like_role_title_line(line):
            employer = line
            break
    if not employer:
        for index in range(title_index + 1, len(candidate_lines)):
            line = candidate_lines[index]
            if line != title and not _looks_like_role_title_line(line):
                employer = line
                break
    return title, employer


def _strip_bullet_prefix(text: str) -> str:
    return _clean_line(_BULLET_PREFIX_RE.sub("", str(text or "").lstrip()))


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
    end_month = _CURRENT_MONTH if is_current else _MONTH_NAME_TO_NUMBER.get(end_month_name, 12)
    duration_months = max(((end_year - start_year) * 12) + (end_month - start_month) + 1, 1)
    return {
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
        "is_current": is_current,
        "duration_months": duration_months,
    }


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
    title_pipe_dates_re = re.compile(
        rf"^(?P<title>.+?)\s*\|\s*(?P<dates>(?:(?:{_MONTH_TOKEN_PATTERN})\s*[.,]?\s*)?(?:19|20)\d{{2}}\s*(?:-|–|—|to|/)\s*(?:(?:{_MONTH_TOKEN_PATTERN})\s*[.,]?\s*)?(?:present|current|now|ongoing|(?:19|20)\d{{2}}))(?:\s*\|\s*(?P<tail>.*))?$",
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
            if look_raw.lstrip().startswith("#") or _is_plain_section_label(look_raw):
                break
            if _extract_year_range(look):
                break
            if _is_bullet_line(look_raw):
                details.append(_strip_bullet_prefix(look_raw))
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

        if _is_heading_line(raw_line):
            current_section = cleaned.lower()
            i += 1
            continue

        inline_match = inline_role_re.match(cleaned)
        if inline_match:
            date_info = _extract_year_range(inline_match.group("dates"))
            bullets, j = collect_role_detail_lines(i + 1)
            if date_info:
                inline_left = _clean_line(inline_match.group("employer"))
                inline_right = _clean_line(inline_match.group("title"))
                roles.append(
                    {
                        "title": inline_right,
                        "employer": inline_left if inline_left != inline_right else "",
                        "header_lines": [item for item in [inline_left, inline_right] if item],
                        "section": current_section,
                        "bullets": bullets,
                        **date_info,
                    }
                )
            i = max(j, i + 1)
            continue

        title_pipe_dates_match = title_pipe_dates_re.match(cleaned)
        if title_pipe_dates_match:
            date_info = _extract_year_range(title_pipe_dates_match.group("dates"))
            if date_info:
                bullets, j = collect_role_detail_lines(i + 1)
                title = _clean_line(title_pipe_dates_match.group("title"))
                employer = ""
                if i > 0:
                    previous_line = _clean_line(lines[i - 1].strip())
                    if (
                        previous_line
                        and not _is_heading_line(lines[i - 1].strip())
                        and not _extract_year_range(previous_line)
                    ):
                        employer = previous_line
                roles.append(
                    {
                        "title": title,
                        "employer": employer,
                        "header_lines": [item for item in [employer, title] if item],
                        "section": current_section,
                        "bullets": bullets,
                        **date_info,
                    }
                )
            i = max(j, i + 1)
            continue

        title_with_dates_match = title_with_dates_re.match(cleaned)
        if title_with_dates_match:
            date_info = _extract_year_range(title_with_dates_match.group("dates"))
            if date_info:
                title = _clean_line(title_with_dates_match.group("title"))
                bullets, j = collect_role_detail_lines(i + 1)
                roles.append(
                    {
                        "title": title,
                        "employer": "",
                        "header_lines": [title],
                        "section": current_section,
                        "bullets": bullets,
                        **date_info,
                    }
                )
            i = max(j, i + 1)
            continue

        date_info = _extract_year_range(cleaned)
        if not date_info:
            i += 1
            continue

        prefix_candidate_lines: list[str] = []
        k = i - 1
        while k >= 0 and len(prefix_candidate_lines) < 3:
            look_back_raw = lines[k].strip()
            look_back = _clean_line(look_back_raw)
            if not look_back:
                break
            if _is_heading_line(look_back_raw) or _is_plain_section_label(look_back_raw) or look_back_raw.lstrip().startswith(("-", "*")):
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
            if _is_heading_line(look_raw) or _is_plain_section_label(look_raw):
                break
            if _extract_year_range(look):
                break
            if _is_bullet_line(look_raw):
                bullets.append(_strip_bullet_prefix(look_raw))
            elif prefix_candidate_lines:
                bullets.append(look)
            elif not bullets and len(candidate_lines) < 3:
                candidate_lines.append(look)
            j += 1

        if candidate_lines:
            title, employer = _select_role_title_and_employer(candidate_lines)
            if not title:
                i = max(j, i + 1)
                continue
            roles.append(
                {
                    "title": title,
                    "employer": employer,
                    "header_lines": [item for item in [employer, title] if item] or [item for item in candidate_lines if item][:3],
                    "section": current_section,
                    "bullets": bullets,
                    **date_info,
                }
            )
        i = max(j, i + 1)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for role in roles:
        header_key = " | ".join(
            _normalize_phrase(item)
            for item in (role.get("header_lines") or [])
            if _normalize_phrase(item)
        )
        role_key = _normalize_phrase(role.get("title", "")) or header_key
        key = (
            role_key,
            int(role.get("start_year", 0) or 0),
            int(role.get("end_year", 0) or 0),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(role)
    return deduped


def _build_cv_evidence_payload(source_text: str, lookback_years: int) -> dict[str, Any]:
    recent_from_year = _CURRENT_YEAR - lookback_years
    structured_roles: list[dict[str, Any]] = []

    for index, role in enumerate(_parse_role_entries(source_text)):
        structured_roles.append(
            {
                "role_index": index,
                "title": str(role.get("title") or "").strip(),
                "employer": str(role.get("employer") or "").strip(),
                "header_lines": [str(item).strip() for item in (role.get("header_lines") or []) if str(item).strip()][:3],
                "section": str(role.get("section") or "").strip(),
                "start_year": int(role.get("start_year") or 0),
                "start_month": int(role.get("start_month") or 0),
                "end_year": int(role.get("end_year") or 0),
                "end_month": int(role.get("end_month") or 0),
                "is_current": bool(role.get("is_current")),
                "duration_months": int(role.get("duration_months") or 0),
                "is_recent": int(role.get("end_year") or 0) >= recent_from_year,
                "bullets": [str(item).strip() for item in (role.get("bullets") or []) if str(item).strip()][:8],
            }
        )

    return {
        "current_year": _CURRENT_YEAR,
        "lookback_years": lookback_years,
        "recent_from_year": recent_from_year,
        "roles": structured_roles,
    }


# ── LLM extraction ─────────────────────────────────────────────────────────────

def _llm_extract_from_cv(source_text: str, lookback_years: int) -> dict[str, Any]:
    """Single LLM call: extract capabilities, title patterns, and match preferences from CV text."""
    cache_key = hashlib.sha256(f"{lookback_years}:{source_text}".encode()).hexdigest()[:16]
    if cache_key in _cv_extraction_cache:
        return _cv_extraction_cache[cache_key]

    try:
        from job_hunter_agent.llm_gate import client, _get_llm_model, _log_llm_call
    except Exception:
        return {}

    if client is None:
        return {}

    recent_from = _CURRENT_YEAR - lookback_years
    evidence_payload = _build_cv_evidence_payload(source_text, lookback_years)
    evidence_json = json.dumps(evidence_payload, ensure_ascii=True)
    prompt = (
        "Extract structured data from this CV evidence pack.\n\n"
        "Return data that matches the requested response schema exactly.\n\n"
        "Rules:\n"
        f"- Current year is {_CURRENT_YEAR}. Recent means {recent_from} onward.\n"
        "- Treat the evidence pack as the source of truth. Use raw CV text only as fallback context when evidence is incomplete.\n"
        "- For each role, trust header_lines plus dates and bullets more than any best-effort title/employer fields.\n"
        "- capabilities: extract 8–15 transferable professional skills when the evidence supports them. "
        "Not company names, employer names, job titles, or raw phrase fragments. "
        "Each capability must be a named skill or practice area grounded in the CV bullets or role headers. "
        "Use explicit role titles when present, plus header_lines and bullets, as evidence. "
        "Set level=strong only for current or recent strengths that are repeated and clearly senior. "
        "Older evidence should usually be working or basic unless the CV still shows current depth. "
        "Set needs_review=true when the capability is plausible but you are not confident it belongs in the final profile.\n"
        "- match_preferences: infer only from explicit statements; leave fields empty or null when not stated.\n"
        "- Do not invent employers, titles, capabilities, or preferences that are not grounded in the evidence.\n"
        "- Return only schema-valid output.\n\n"
        f"Evidence pack JSON:\n{evidence_json[:12000]}\n\n"
        f"Raw CV fallback:\n{source_text[:3000]}"
    )

    try:
        model = _get_llm_model()
        resp = client.responses.parse(
            model=model,
            input=[{"role": "user", "content": prompt}],
            text_format=_CvExtractionResponse,
            max_output_tokens=1500,
        )
        _log_llm_call(resp, "cv_extraction", model)
        parsed = resp.output_parsed
        result = parsed.model_dump() if parsed is not None else {}
    except Exception:
        result = {}

    _cv_extraction_cache[cache_key] = result
    return result


def _validate_capabilities(raw: list[Any]) -> list[dict[str, Any]]:
    result = []
    rejected: list[str] = []
    _cap_log(f"[CAP_VALIDATE] LLM returned {len(raw or [])} raw capability candidate(s)")
    for item in raw or []:
        if not isinstance(item, dict):
            rejected.append("<non-dict>")
            continue
        name = str(item.get(KEY_NAME) or "").strip().lower()
        level = str(item.get(KEY_LEVEL) or LEVEL_BASIC).strip().lower()
        aliases = [str(a).strip().lower() for a in (item.get(KEY_ALIASES) or []) if str(a).strip()]
        if not name:
            rejected.append("<empty name>")
            continue
        name_tokens = re.findall(r"[a-z0-9]+", name)
        if name_tokens and len(name_tokens) <= 3 and name_tokens[-1] in _generic_role_tokens():
            rejected.append(f"{name} [generic-role-token filter]")
            continue
        needs_review = bool(item.get(KEY_NEEDS_REVIEW))
        result.append({
            KEY_NAME: name,
            KEY_LEVEL: level if level in _VALID_LEVELS else LEVEL_BASIC,
            KEY_ALIASES: aliases[:6],
            KEY_NEEDS_REVIEW: needs_review,
        })
    capped = result[:20]
    cap_overflow = result[20:]
    if cap_overflow:
        rejected.extend(f"{r['name']} [cap-20 overflow]" for r in cap_overflow)
    kept_names = [r["name"] for r in capped]
    _cap_log(f"[CAP_VALIDATE] kept {len(capped)}: {kept_names}")
    if rejected:
        _cap_log(f"[CAP_VALIDATE] rejected {len(rejected)}: {rejected}")
    return capped


def _capability_context_sections(
    capability_name: str,
    aliases: list[str],
    source_sections: list[dict[str, str]] | None = None,
    *,
    max_hits: int = 3,
) -> list[str]:
    if not source_sections:
        return []

    terms = [str(capability_name or "").strip(), *(str(alias or "").strip() for alias in aliases or [])]
    terms = [term for term in terms if term]
    if not terms:
        return []

    snippets: list[str] = []
    seen: set[str] = set()
    for section in source_sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "Source").strip()
        text = repair_text(str(section.get("text") or ""))
        if not text:
            continue
        for line in text.splitlines():
            cleaned = _clean_line(line)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if not any(term.lower() in lowered for term in terms):
                continue
            snippet = f"{label}: {cleaned}"
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(snippet)
            break
        if len(snippets) >= max_hits:
            break
    return snippets


def _role_title_context_sections(
    title: str,
    source_sections: list[dict[str, str]] | None = None,
    *,
    max_hits: int = 3,
) -> list[str]:
    if not source_sections:
        return []

    normalized_title = _normalize_role_title_value(title)
    if not normalized_title:
        return []

    title_terms = [normalized_title, *_pattern_tokens(normalized_title)]
    title_terms = [term for term in title_terms if term]

    snippets: list[str] = []
    seen: set[str] = set()
    for section in source_sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "Source").strip()
        text = repair_text(str(section.get("text") or ""))
        if not text:
            continue
        for line in text.splitlines():
            cleaned = _clean_line(line)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if normalized_title not in lowered and not all(term in lowered for term in title_terms):
                continue
            snippet = f"{label}: {cleaned}"
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(snippet)
            break
        if len(snippets) >= max_hits:
            break
    return snippets


def build_role_title_review_signals(
    titles: list[str],
    source_sections: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    review_signals: list[dict[str, Any]] = []
    seen: set[str] = set()

    for title in titles or []:
        cleaned_title = _clean_line(title)
        review_token = _role_title_review_token(cleaned_title)
        if not review_token or review_token in seen:
            continue
        seen.add(review_token)

        known_signal, knowledge_match = signal_in_approved_knowledge(CAT_ROLE_TITLE, review_token)
        if known_signal:
            continue

        review_signal: dict[str, Any] = {
            LEARNING_SIGNAL_KEY: review_token,
            LEARNING_CATEGORY_KEY: CAT_ROLE_TITLE,
            LEARNING_SOURCE_KEY: SOURCE_CV_PARSING,
            LEARNING_CONTEXT_KEY: _role_title_context_sections(cleaned_title, source_sections),
            LEARNING_EVIDENCE_KEY: [cleaned_title, _normalize_role_title_value(cleaned_title)],
            LEARNING_NEEDS_REVIEW_KEY: True,
        }
        if knowledge_match:
            review_signal[LEARNING_KNOWLEDGE_MATCH_KEY] = knowledge_match
        review_signals.append(review_signal)

    return review_signals


def _split_learning_capabilities(
    capabilities: list[dict[str, Any]],
    *,
    source_sections: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    approved: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []

    for item in capabilities:
        name = str(item.get(KEY_NAME) or "").strip()
        aliases = [str(alias).strip() for alias in (item.get(KEY_ALIASES) or []) if str(alias).strip()]
        needs_review = bool(item.get(KEY_NEEDS_REVIEW))
        known_signal, knowledge_match = signal_in_approved_knowledge(CAT_CAPABILITY, name, aliases)

        if needs_review and not known_signal:
            review_signals.append({
                LEARNING_SIGNAL_KEY: name,
                LEARNING_CATEGORY_KEY: CAT_CAPABILITY,
                LEARNING_SOURCE_KEY: SOURCE_CV_PARSING,
                LEARNING_CONTEXT_KEY: _capability_context_sections(name, aliases, source_sections),
                LEARNING_EVIDENCE_KEY: [name, *aliases],
                LEARNING_NEEDS_REVIEW_KEY: True,
            })
            continue

        cleaned = dict(item)
        cleaned[KEY_NEEDS_REVIEW] = False if known_signal else needs_review
        if knowledge_match:
            cleaned[LEARNING_KNOWLEDGE_MATCH_KEY] = knowledge_match
        approved.append(cleaned)

    return approved, review_signals


def _pattern_tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _normalize_role_title_value(value: str) -> str:
    return normalize_title_text(_clean_line(value))


def _role_title_review_token(title: str) -> str:
    normalized = _normalize_role_title_value(title)
    if not normalized:
        return ""
    tokens = [_normalize_token(token) for token in re.split(r"\s+", normalized) if _normalize_token(token)]
    if len(tokens) < 2:
        return ""
    modifiers = _load_title_seniority_modifiers()
    filtered = [token for token in tokens if token not in modifiers]
    if len(filtered) < 2:
        return ""
    candidate = filtered[-1]
    if candidate in _generic_role_tokens():
        return ""
    return candidate


def _split_compound_role_title(title: str) -> list[str]:
    cleaned = _normalize_role_title_value(title)
    if not cleaned:
        return []
    raw_parts = [
        _normalize_role_title_value(part)
        for part in re.split(r"\s*/\s*|\s*\|\s*|\s+\band\b\s+", cleaned)
        if _normalize_role_title_value(part)
    ]
    if len(raw_parts) <= 1:
        return [cleaned]
    if not all(any(token in _generic_role_tokens() for token in _pattern_tokens(part)) for part in raw_parts):
        return [cleaned]
    return list(dict.fromkeys(raw_parts))


def _sorted_roles_for_title_selection(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        roles,
        key=lambda role: (
            0 if bool(role.get("is_current")) else 1,
            -(int(role.get("end_year") or 0)),
            -(int(role.get("end_month") or 0)),
            -(int(role.get("start_year") or 0)),
            -(int(role.get("start_month") or 0)),
        ),
    )


def _collect_title_evidence(roles: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    evidence: dict[str, dict[str, int]] = {}
    for index, role in enumerate(_sorted_roles_for_title_selection(roles)):
        raw_title = str(role.get("title") or "").strip()
        if not raw_title:
            continue
        titles = _split_compound_role_title(raw_title)
        is_compound = len(titles) > 1
        for title in titles:
            bucket = evidence.setdefault(
                title,
                {
                    "current_occurrences": 0,
                    "recent_occurrences": 0,
                    "older_occurrences": 0,
                    "standalone_occurrences": 0,
                    "compound_occurrences": 0,
                    "total_occurrences": 0,
                },
            )
            bucket["total_occurrences"] += 1
            if bool(role.get("is_current")):
                bucket["current_occurrences"] += 1
            elif index <= 2:
                bucket["recent_occurrences"] += 1
            else:
                bucket["older_occurrences"] += 1
            if is_compound:
                bucket["compound_occurrences"] += 1
            else:
                bucket["standalone_occurrences"] += 1
    return evidence


def _classify_titles_from_evidence(
    title_evidence: dict[str, dict[str, int]],
    *,
    max_target: int,
    max_secondary: int,
) -> dict[str, list[str]]:
    primary: list[str] = []
    secondary: list[str] = []

    def primary_sort_key(item: tuple[str, dict[str, int]]) -> tuple[int, int, int, int, str]:
        title, stats = item
        return (
            -int(stats["current_occurrences"]),
            -int(stats["recent_occurrences"]),
            -int(stats["standalone_occurrences"]),
            -int(stats["total_occurrences"]),
            title,
        )

    def secondary_sort_key(item: tuple[str, dict[str, int]]) -> tuple[int, int, int, int, str]:
        title, stats = item
        return (
            -(int(stats["current_occurrences"]) + int(stats["recent_occurrences"])),
            -int(stats["standalone_occurrences"]),
            -int(stats["total_occurrences"]),
            -int(stats["compound_occurrences"]),
            title,
        )

    sorted_items = sorted(title_evidence.items(), key=primary_sort_key)
    for title, stats in sorted_items:
        has_recent_signal = bool(stats["current_occurrences"] or stats["recent_occurrences"])
        has_standalone_signal = stats["standalone_occurrences"] > 0
        repeated = stats["total_occurrences"] > 1
        compound_only = stats["compound_occurrences"] > 0 and stats["standalone_occurrences"] == 0

        if has_recent_signal and has_standalone_signal:
            primary.append(title)
            continue
        if has_recent_signal and repeated and not compound_only:
            primary.append(title)

    primary = primary[:max_target]
    primary_set = set(primary)

    for title, stats in sorted(title_evidence.items(), key=secondary_sort_key):
        if title in primary_set:
            continue
        has_recent_signal = bool(stats["current_occurrences"] or stats["recent_occurrences"])
        has_standalone_signal = stats["standalone_occurrences"] > 0
        repeated = stats["total_occurrences"] > 1
        compound_only = stats["compound_occurrences"] > 0 and stats["standalone_occurrences"] == 0
        older_only = not has_recent_signal and stats["older_occurrences"] > 0

        if compound_only and not repeated and not has_recent_signal:
            continue
        if older_only or compound_only or not has_standalone_signal or not repeated:
            secondary.append(title)
        if len(secondary) >= max_secondary:
            break

    return {
        KEY_PRIMARY_PATTERNS: primary,
        KEY_SECONDARY_PATTERNS: secondary,
    }


# ── Match preference extraction ────────────────────────────────────────────────

def _extract_match_preferences(text: str) -> dict[str, Any]:
    prefs = {}
    lowered = text.lower()

    if re.search(r"\b(permanent only|no contracts|prefer permanent|seeking permanent)\b", lowered):
        prefs["prefer_permanent"] = True
    elif re.search(r"\b(contract only|prefer contracts|freelance|interim)\b", lowered):
        prefs["prefer_permanent"] = False

    if re.search(r"\b(remote only|100% remote|work from home only)\b", lowered):
        prefs["work_mode_preference"] = "remote"
    elif re.search(r"\b(hybrid|flexible working|mix of office and home)\b", lowered):
        prefs["work_mode_preference"] = "hybrid"

    loc = extract_location_hint(text)
    if loc:
        prefs["home_location"] = loc

    return prefs


def extract_location_hint(text: str) -> str:
    match = re.search(
        r"(?i)\b(?:based in|location|reside in|lives in|home base|resident of):\s*([A-Za-z\s,]+?)(?=\n|[,.]?\s+and\b|[,.]?\s+with\b|[.!?]|\s{2,}|\Z)",
        text,
    )
    if match:
        loc = match.group(1).strip()
        loc = re.sub(r"(?i)[,\s]+\w{2,3}$", "", loc).strip()
        if 2 < len(loc) < 60:
            return loc
    return ""


# ── Public API ─────────────────────────────────────────────────────────────────

def build_learning_patch(
    text: str,
    onboarding_settings: dict[str, Any] | None = None,
    source_sections: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    source_text = repair_text(text)
    if not source_text:
        return {}

    lookback_years = _resolve_extraction_lookback_years(onboarding_settings)
    extracted = _llm_extract_from_cv(source_text, lookback_years)

    patch: dict[str, Any] = {KEY_CV_TEXT: source_text}

    role_titles = [
        str(role.get("title") or "").strip()
        for role in _parse_role_entries(source_text)
        if str(role.get("title") or "").strip()
    ]
    if role_titles:
        learn_title_normalization_candidates(
            role_titles,
            source=SOURCE_CV_PARSING,
            source_text=source_text,
        )

    raw_caps = extracted.get(KEY_CAPABILITIES, [])
    _cap_log(f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(raw_caps)} capabilities before validation")
    capabilities = _validate_capabilities(raw_caps)
    approved_capabilities, review_signals = _split_learning_capabilities(capabilities, source_sections=source_sections)
    _cap_log(
        f"[BUILD_LEARNING_PATCH] {len(approved_capabilities)} capability rule(s) will be written to capability_profile_rules"
    )
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(review_signals)} capability signal(s) need review")
    if approved_capabilities:
        patch[KEY_CAPABILITY_PROFILE_RULES] = approved_capabilities
    if review_signals:
        register_signals(review_signals)

    raw_prefs = extracted.get(KEY_MATCH_PREFS) or {}
    match_prefs = {k: v for k, v in raw_prefs.items() if v is not None and v != ""}
    if match_prefs:
        patch[KEY_MATCH_PREFS] = match_prefs

    return patch


def extract_title_pattern_suggestions(
    source_text: str,
    onboarding_settings: dict | None = None,
) -> dict[str, list[str]]:
    source_text = repair_text(source_text)
    settings = onboarding_settings or {}
    max_target = _resolve_onboarding_int(settings, KEY_MAX_TARGET)
    max_secondary = _resolve_onboarding_int(settings, KEY_MAX_SECONDARY)
    roles = _parse_role_entries(source_text)
    title_evidence = _collect_title_evidence(roles)
    classified = _classify_titles_from_evidence(
        title_evidence,
        max_target=max_target,
        max_secondary=max_secondary,
    )

    target_patterns = [
        _normalize_role_title_value(value)
        for value in (classified.get(KEY_PRIMARY_PATTERNS) or [])
        if _normalize_role_title_value(value)
    ][:max_target]
    secondary_patterns = [
        _normalize_role_title_value(value)
        for value in (classified.get(KEY_SECONDARY_PATTERNS) or [])
        if _normalize_role_title_value(value)
    ][:max_secondary]
    derived_secondary_patterns: list[str] = []
    seen_secondary = {pattern for pattern in secondary_patterns if pattern}
    for primary in target_patterns:
        derived = derive_base_title_from_seniority(primary)
        if not derived or derived in seen_secondary or derived in target_patterns:
            continue
        seen_secondary.add(derived)
        derived_secondary_patterns.append(derived)
    secondary_patterns = list(dict.fromkeys([*secondary_patterns, *derived_secondary_patterns]))[:max_secondary]
    suggested_search_keywords = target_patterns[:4]

    return {
        KEY_PRIMARY_PATTERNS: list(dict.fromkeys(target_patterns)),
        KEY_SECONDARY_PATTERNS: list(dict.fromkeys(secondary_patterns)),
        KEY_SUGGESTED_KEYWORDS: list(dict.fromkeys(suggested_search_keywords))[:4],
    }


def merge_capability_rules(
    existing: list[dict[str, Any]],
    learned: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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
