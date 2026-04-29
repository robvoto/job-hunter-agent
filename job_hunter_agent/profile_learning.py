"""Profile learning helpers.

Main goals:
- repair imported text
- extract capabilities and title patterns from CV text via LLM
- structural parsing (sections, dates, roles) shared with other pipeline modules
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from job_hunter_agent.paths import REPO_ROOT
from job_hunter_agent.profile_store import DEFAULT_ONBOARDING_SETTINGS


ROOT_DIR = REPO_ROOT

_VALID_LEVELS = {"strong", "working", "basic", "low", "none"}
_VALID_FITS = {"core", "supporting", "contextual", "avoid"}
_CURRENT_YEAR = datetime.now().year
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


class _CapabilityExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: Literal["strong", "working", "basic"]
    fit: Literal["core", "supporting", "contextual"]
    aliases: list[str] = Field(default_factory=list)


class _MatchPreferenceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_permanent: bool | None = None
    work_mode_preference: Literal["remote", "hybrid", "onsite"] | None = None
    home_location: str = ""


class _CvExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[_CapabilityExtraction] = Field(default_factory=list)
    target_title_patterns: list[str] = Field(default_factory=list)
    secondary_title_patterns: list[str] = Field(default_factory=list)
    suggested_search_keywords: list[str] = Field(default_factory=list)
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
    return _resolve_onboarding_int(onboarding_settings, "extraction_lookback_years")


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
            if look_raw.lstrip().startswith("#"):
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
            if _is_heading_line(look_back_raw) or look_back_raw.lstrip().startswith(("-", "*")):
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
            if _is_heading_line(look_raw):
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
            roles.append(
                {
                    "title": "",
                    "employer": "",
                    "header_lines": [item for item in candidate_lines if item][:3],
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
        "- capabilities: transferable professional skills only. Not company/project names, domains, or generic duties. "
        "Use explicit role titles when present, plus header_lines and bullets, as evidence. level=strong if repeated across multiple roles or clearly senior; "
        "fit=core if recent and repeated.\n"
        "- target_title_patterns: short searchable patterns from the most recent substantial roles in the lookback window.\n"
        "- secondary_title_patterns: other plausible patterns from the same window.\n"
        "- suggested_search_keywords: 2-4 short phrases describing the candidate's primary expertise.\n"
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
            max_output_tokens=900,
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
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        level = str(item.get("level") or "basic").strip().lower()
        fit = str(item.get("fit") or "contextual").strip().lower()
        aliases = [str(a).strip().lower() for a in (item.get("aliases") or []) if str(a).strip()]
        if not name:
            continue
        result.append({
            "name": name,
            "level": level if level in _VALID_LEVELS else "basic",
            "fit": fit if fit in _VALID_FITS else "contextual",
            "aliases": aliases[:6],
        })
    return result[:20]


def _validate_patterns(raw: Any, limit: int = 6) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(p).strip().lower() for p in raw if str(p).strip()][:limit]


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
) -> dict[str, Any]:
    source_text = repair_text(text)
    if not source_text:
        return {}

    lookback_years = _resolve_extraction_lookback_years(onboarding_settings)
    extracted = _llm_extract_from_cv(source_text, lookback_years)

    patch: dict[str, Any] = {"cv_text": source_text}

    capabilities = _validate_capabilities(extracted.get("capabilities", []))
    if capabilities:
        patch["capability_profile_rules"] = capabilities

    raw_prefs = extracted.get("match_preferences") or {}
    match_prefs = {k: v for k, v in raw_prefs.items() if v is not None and v != ""}
    if match_prefs:
        patch["match_preferences"] = match_prefs

    return patch


def extract_title_pattern_suggestions(
    source_text: str,
    onboarding_settings: dict | None = None,
) -> dict[str, list[str]]:
    source_text = repair_text(source_text)
    settings = onboarding_settings or {}
    lookback_years = _resolve_extraction_lookback_years(settings)
    max_target = _resolve_onboarding_int(settings, "max_target_patterns")
    max_secondary = _resolve_onboarding_int(settings, "max_secondary_patterns")
    extracted = _llm_extract_from_cv(source_text, lookback_years)

    return {
        "target_title_patterns": _validate_patterns(extracted.get("target_title_patterns"), max_target),
        "secondary_title_patterns": _validate_patterns(extracted.get("secondary_title_patterns"), max_secondary),
        "suggested_search_keywords": _validate_patterns(extracted.get("suggested_search_keywords"), 4),
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
