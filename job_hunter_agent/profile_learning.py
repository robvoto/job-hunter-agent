"""Profile learning helpers.

This module provides utilities for processing and learning from candidate CV text.
It focuses on extracting structured information, such as capabilities, role titles,
and role directions, for use in the job matching and profile building processes.

Key functionalities include:
- Repairing common text encoding and formatting issues in imported CV text.
- Extracting capabilities and role titles from CV text using LLMs.
- Building learning signals for new capabilities and title normalization candidates.

The module integrates with LLMs for advanced extraction tasks and includes
mechanisms for caching LLM responses to improve efficiency. It also handles
the normalization and validation of extracted data to ensure consistency.
"""

import hashlib
import logging
import os
import re
import traceback
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Literal

logger = logging.getLogger(__name__)

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.profile_item_names import normalize_profile_item_name
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    KEY_ALIASES,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_QUALIFICATIONS,
    KEY_ICON_KEY,
    KEY_LEVEL,
    KEY_LOOKBACK_YEARS,
    KEY_MATCH_PREFS,
    KEY_MAX_SECONDARY,
    KEY_MAX_TARGET,
    KEY_NAME,
    KEY_PRIMARY_PATTERNS,
    KEY_ROLE_EXPERIENCE,
    KEY_SECONDARY_PATTERNS,
    VALID_CAPABILITY_ICON_KEYS,
    CapabilityLevel,
)
from job_hunter_agent.runtime_helpers import is_desktop_runtime
from job_hunter_agent.text_processing import compact_whitespace

KEY_NEEDS_REVIEW = "needs_review"
# Transient onboarding output. It is shown for user review and is never persisted.
ROLE_SUGGESTIONS_KEY = "role_suggestions"


def _simple_title(value: str) -> str:
    """Normalize a role title for onboarding: trim, lowercase, collapse whitespace only."""
    return compact_whitespace(value).lower()


from job_hunter_agent.global_settings import (
    KEY_CAPABILITY_ALIAS_LIMIT,
    get_llm_capability_naming_max_output_tokens,
    get_llm_profile_extraction_max_output_tokens,
)
from job_hunter_agent.signal_registry import register_signals, signal_in_approved_knowledge
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    LEARNING_CATEGORY_KEY,
    LEARNING_CONTEXT_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_KNOWLEDGE_MATCH_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    SIGNAL_ALIASES_KEY,
    SOURCE_CV_PARSING,
)

# Internal result key
KEY_CAPABILITIES = "capabilities"

# Signal categories
CAT_CAPABILITY = CATEGORY_CAPABILITY_CONCEPT

_VALID_LEVELS = {CapabilityLevel.STRONG, CapabilityLevel.WORKING, CapabilityLevel.BASIC}
_CURRENT_YEAR = datetime.now().year


def _cap_log(msg: str) -> None:
    logger.info("%s", msg)


def resolve_role_family(
    title: str,
    llm_client: Any = None,
    *,
    benchmark_model: str | None = None,
) -> dict[str, Any]:
    """Resolve a proposed role label before it becomes saved search intent."""
    cleaned_title = compact_whitespace(title)
    if not cleaned_title:
        raise ValueError("Role title is required")

    from job_hunter_agent.llm_gate import (
        _llm_generation_kwargs,
        _log_llm_call,
        client,
        get_llm_model,
    )

    active_client = llm_client or client
    if active_client is None:
        raise RuntimeError("Role-family resolution requires an available LLM client")
    prompt = (
        "Resolve the supplied job title into one neutral occupation-family label. "
        "Return the exact title unchanged only when it already names the neutral family. "
        "Do not include seniority, level, rank, employment status, or other qualifiers "
        "that narrow discovery. If the family cannot be resolved confidently, return "
        "an empty role_family and resolved=false. Do not invent a different occupation."
    )
    model = benchmark_model or get_llm_model()
    try:
        response = active_client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": cleaned_title},
            ],
            text_format=_RoleFamilyResolution,
            max_output_tokens=get_llm_capability_naming_max_output_tokens(),
            **_llm_generation_kwargs(model),
        )
        _log_llm_call(response, "role_family_resolution", model)
    except Exception as exc:
        logger.exception("[ONBOARDING][ROLE_FAMILY_RESOLUTION_ERROR] title=%r", cleaned_title)
        raise RuntimeError(f"Could not resolve role family: {type(exc).__name__}") from exc

    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("Role-family resolution returned no structured result")
    role_family = compact_whitespace(parsed.role_family)
    resolved = bool(parsed.resolved and role_family)
    return {"role_family": role_family if resolved else "", "resolved": resolved}


_BULLET_PREFIX_RE = re.compile(r"^[\-*•–—]+\s*")

# Bump whenever the extracted CV shape changes so every cached extraction misses
# and is genuinely re-run. v4 added role_experience[].duration_as_of; v5 makes
# extraction_lookback_years part of the actual LLM instruction rather than only
# the cache key/logging contract, so older cached extractions must not be reused.
_CV_EXTRACTION_CACHE_CONTRACT_VERSION = 5
_cv_extraction_cache: dict[str, dict[str, Any]] = {}
_cv_extraction_cache_loaded = False


class _CapabilityExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: Literal["strong", "working", "basic"]
    aliases: list[str] = Field(default_factory=list)
    icon_key: str
    # Semantic ownership stays with the extraction LLM. False means the row is
    # an umbrella/mixed concept and must never become reusable capability knowledge.
    atomic_concept: bool
    needs_review: bool = False


class _EligibilityExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: StrictBool = True
    evidence: list[str] = Field(default_factory=list)
    needs_review: bool = False


class _QualificationExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    aliases: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    needs_review: bool = False


class _MatchPreferenceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_permanent: bool | None = None
    work_mode_preference: Literal["remote", "hybrid", "onsite"] | None = None
    home_location: str = ""


class _RoleExperienceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    canonical_title: str = ""
    duration_months: int = 0
    end_year: int = 0
    is_current: bool = False


class _RoleFamilyResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_family: str = ""
    resolved: bool = False


class _CvExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[_CapabilityExtraction] = Field(default_factory=list)
    eligibility: list[_EligibilityExtraction] = Field(default_factory=list)
    qualifications: list[_QualificationExtraction] = Field(default_factory=list)
    match_preferences: _MatchPreferenceExtraction = Field(
        default_factory=_MatchPreferenceExtraction
    )
    role_experience: list[_RoleExperienceExtraction] = Field(default_factory=list)
    role_titles: list[str] = Field(default_factory=list)
    preferred_role_titles: list[str] = Field(default_factory=list)
    alternative_role_titles: list[str] = Field(default_factory=list)


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


def _cv_work_history_lookback_rule(lookback_years: int) -> str:
    return (
        f"Use only work-history evidence from the most recent {lookback_years} years when extracting "
        "role_experience, role_titles, preferred_role_titles, alternative_role_titles, and capabilities. "
        "A role is in scope when it is current or overlaps that lookback window. Do not derive those "
        "fields from roles entirely older than the window. Qualifications and current eligibility facts "
        "may still be extracted when they are explicitly stated because they can remain current beyond "
        "the work-history window."
    )


# ── Text utilities ─────────────────────────────────────────────────────────────


def _clean_line(text: str) -> str:
    cleaned = re.sub(r"[*_`#]+", " ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:\t")
    return cleaned


def _normalize_token(token: str) -> str:
    cleaned = re.sub(r"[^a-z0-9+#/&-]", "", str(token or "").lower()).strip("-/")
    if cleaned.endswith("ies") and len(cleaned) > 4:
        cleaned = cleaned[:-3] + "y"
    elif (
        cleaned.endswith("s")
        and len(cleaned) > 4
        and not cleaned.endswith("ss")
        and not cleaned.endswith("is")
    ):
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
    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("parsing_rules") or {}


def get_parsing_rule_set(key: str) -> set[str]:
    rules = _load_parsing_rules()
    items = rules.get(key)
    if isinstance(items, list):
        return {str(item).lower().strip() for item in items if item}
    return set()


def _strip_bullet_prefix(text: str) -> str:
    return _clean_line(_BULLET_PREFIX_RE.sub("", str(text or "").lstrip()))


# ── LLM extraction ─────────────────────────────────────────────────────────────


def _stamp_current_role_extraction_dates(result: dict[str, Any]) -> None:
    """Record today's date as ``duration_as_of`` on each current role in place.

    Called only from the uncached LLM path so the date always pairs with a
    freshly extracted ``duration_months``. Downstream aggregation carries it into
    the role family's ``segments`` so job-match time can accrue elapsed months.
    """
    today = date.today().isoformat()
    for item in result.get(KEY_ROLE_EXPERIENCE) or []:
        if isinstance(item, dict) and bool(item.get("is_current")):
            item["duration_as_of"] = today


def _ensure_cv_extraction_cache_loaded() -> None:
    global _cv_extraction_cache_loaded
    if _cv_extraction_cache_loaded:
        return
    _cv_extraction_cache_loaded = True
    try:
        from job_hunter_agent.io_utils import load_cv_extraction_cache

        _cv_extraction_cache.update(load_cv_extraction_cache())
    except Exception:
        pass


def _llm_extract_from_cv(
    source_text: str,
    lookback_years: int,
    alias_limit: int,
    *,
    benchmark_model: str | None = None,
) -> dict[str, Any]:
    """Single LLM call: extract capabilities, title patterns, and match preferences from CV text."""
    _ensure_cv_extraction_cache_loaded()
    cache_key = hashlib.sha256(
        (
            f"role-tier-v{_CV_EXTRACTION_CACHE_CONTRACT_VERSION}:"
            f"{lookback_years}:{alias_limit}:{source_text}"
        ).encode()
    ).hexdigest()[:16]
    if benchmark_model is None and cache_key in _cv_extraction_cache:
        cached = _cv_extraction_cache[cache_key]
        _cap_log(
            "[ONBOARDING][LLM_CACHE_HIT] purpose=cv_extraction "
            f"cache_key={cache_key} "
            f"capabilities={len(cached.get(KEY_CAPABILITIES, []) or [])} "
            f"role_experience={len(cached.get(KEY_ROLE_EXPERIENCE, []) or [])} "
            f"role_titles={len(cached.get('role_titles', []) or [])} "
            f"preferred_role_titles={len(cached.get('preferred_role_titles', []) or [])} "
            f"alternative_role_titles={len(cached.get('alternative_role_titles', []) or [])}"
        )
        return cached

    try:
        from job_hunter_agent.llm_gate import (
            _llm_generation_kwargs,
            _log_llm_call,
            client,
            get_llm_model,
        )
    except Exception:
        return {}

    if client is None:
        reason = (
            "desktop_runtime"
            if is_desktop_runtime()
            else (
                "missing_openai_api_key"
                if not str(os.environ.get("OPENAI_API_KEY") or "").strip()
                else "llm_client_unavailable"
            )
        )
        _cap_log(
            "[ONBOARDING][LLM_CALL_SKIPPED] purpose=cv_extraction "
            f"cache_key={cache_key} reason={reason}"
        )
        return {}
    profile_extraction_max_output_tokens = get_llm_profile_extraction_max_output_tokens()
    prompt = (
        "Extract structured data from this CV text.\n\n"
        "Return data that matches the requested response schema exactly.\n\n"
        "Rules:\n"
        f"- Current year is {_CURRENT_YEAR}.\n"
        "- Treat the raw CV text as the source of truth.\n"
        f"- {_cv_work_history_lookback_rule(lookback_years)}\n"
        "- capabilities: extract 8–15 transferable professional skills when the CV supports them. "
        "Not company names, employer names, job titles, or raw phrase fragments. "
        "Each capability must be one atomic reusable skill or practice area grounded in the CV bullets, skills section, summary, or experience text. "
        "Do not use an umbrella label to group distinct tools, products, methods, or skills; return those concrete concepts as separate capability rows when the CV supports them. "
        "Set atomic_concept=true only when the row names one reusable concept. If you cannot isolate one concept confidently, set atomic_concept=false and needs_review=true; that umbrella row will not be learned. "
        "Set level='strong' only for current or recent strengths that are repeated and clearly senior. "
        "Older evidence should usually be 'working' or 'basic' unless the CV still shows current depth. "
        "Set needs_review=true when the atomic capability is plausible but you are not confident it belongs in the final profile. "
        f"For each capability include up to {alias_limit} aliases: known abbreviations, acronyms, and recruiter synonyms "
        "that refer to the same capability. Never place a different tool, product, method, or skill in aliases merely because it appeared beside the capability in the CV. "
        "Only include aliases that are grounded in the evidence or are widely recognised industry synonyms.\n"
        f"For each capability, set icon_key to exactly one of: {', '.join(sorted(VALID_CAPABILITY_ICON_KEYS))}.\n"
        "- match_preferences: infer only from explicit statements; leave fields empty or null when not stated.\n"
        "- role_experience: for each explicit role in the CV, return the title as shown, a canonical_title when close title variants clearly belong to the same role family, plus duration_months and end_year.\n"
        "  Example: BA, Business Analyst, and Senior BA can share canonical_title='Business Analyst' when the CV evidence clearly supports that grouping.\n"
        "  Keep title as the displayed role wording from the CV. Use the current year for Present/current roles and skip entries where the title cannot be identified.\n"
        "- role_titles: list the job titles explicitly shown in the CV. One entry per role, no duplicates.\n"
        "  If one displayed role clearly combines two standalone roles (for example with ' - ' or '/'), split it into separate role title entries instead of returning one composite title.\n"
        "- preferred_role_titles: list the candidate's main role directions from the CV.\n"
        "  These should be the strongest current or core occupation-family titles the candidate would most likely target first.\n"
        "  Return neutral occupation-family labels, not seniority or level variants; for example, use Systems Analyst for Senior Systems Analyst.\n"
        "  Keep the exact CV/employment wording in role_experience.title; role_experience.canonical_title is only the family grouping.\n"
        "  Use standalone role titles only, no duplicates.\n"
        "- alternative_role_titles: list credible adjacent or secondary role directions from the CV that are less central than preferred_role_titles.\n"
        "  Use the same neutral occupation-family convention; do not narrow a source search by seniority.\n"
        "  Do not repeat any preferred_role_titles entry here. Use standalone role titles only, no duplicates.\n"
        "- eligibility: extract only current, independently verifiable facts the candidate actually holds or is legally allowed to claim now. "
        "Examples include an existing clearance, citizenship, work rights, licence, or registration. "
        "Do not treat future possibility, willingness, suitability, or being eligible/able to obtain something as a current eligibility fact. "
        "For example, 'eligible to obtain a clearance' is not the same as holding that clearance and must not be returned as eligibility=true. "
        "Return one concise fact per item; split independent facts instead of combining them. "
        "Only include facts directly supported by the CV text.\n"
        "- qualifications: extract explicit education, degrees, certifications, and formal qualifications. "
        "Return one concise reusable concept per item (for example CBAP, PRINCE2, Bachelor of Information Technology, or Diploma of Project Management), plus aliases and source evidence. "
        "Never use a full CV sentence or a list of alternatives as the qualification name. Only include items directly supported by the CV text.\n"
        "- Do not invent employers, titles, capabilities, or preferences that are not grounded in the evidence.\n"
        "- Return only schema-valid output.\n\n"
        f"CV text:\n{source_text}"
    )

    _cap_log(f"[ONBOARDING][LLM_CALL_START] purpose=cv_extraction cache_key={cache_key}")
    try:
        model = benchmark_model or get_llm_model()
        resp = client.responses.parse(
            model=model,
            input=[{"role": "user", "content": prompt}],
            text_format=_CvExtractionResponse,
            max_output_tokens=profile_extraction_max_output_tokens,
            **_llm_generation_kwargs(model),
        )
        _log_llm_call(resp, "cv_extraction", model)
        parsed = resp.output_parsed
        result = parsed.model_dump() if parsed is not None else {}
    except Exception as exc:
        _cap_log(
            f"[ONBOARDING][LLM_CALL_ERROR] purpose=cv_extraction cache_key={cache_key} error={exc}"
        )
        traceback.print_exc()
        raise

    # Stamp the real extraction date onto every current role. This only happens
    # on a genuine (uncached) LLM call, so duration_as_of always pairs with a
    # freshly extracted duration_months; the cache then replays the true date.
    _stamp_current_role_extraction_dates(result)

    _cap_log(
        "[ONBOARDING][LLM_CALL_DONE] purpose=cv_extraction "
        f"cache_key={cache_key} "
        f"capabilities={len(result.get(KEY_CAPABILITIES, []) or [])} "
        f"eligibility={len(result.get('eligibility', []) or [])} "
        f"qualifications={len(result.get('qualifications', []) or [])} "
        f"role_experience={len(result.get(KEY_ROLE_EXPERIENCE, []) or [])} "
        f"role_titles={len(result.get('role_titles', []) or [])} "
        f"preferred_role_titles={len(result.get('preferred_role_titles', []) or [])} "
        f"alternative_role_titles={len(result.get('alternative_role_titles', []) or [])}"
    )

    if benchmark_model is None:
        _cv_extraction_cache[cache_key] = result
        try:
            from job_hunter_agent.io_utils import save_cv_extraction_cache

            save_cv_extraction_cache(_cv_extraction_cache)
        except Exception:
            pass
    return result


def _validate_capabilities(raw: list[Any], *, alias_limit: int) -> list[dict[str, Any]]:
    result = []
    rejected: list[str] = []
    _cap_log(f"[CAP_VALIDATE] LLM returned {len(raw or [])} raw capability candidate(s)")
    for item in raw or []:
        if not isinstance(item, dict):
            rejected.append("<non-dict>")
            continue
        name = str(item.get(KEY_NAME) or "").strip().lower()
        level = str(item.get(KEY_LEVEL) or CapabilityLevel.BASIC).strip().lower()
        aliases = [str(a).strip().lower() for a in (item.get(KEY_ALIASES) or []) if str(a).strip()]
        icon_key = str(item.get(KEY_ICON_KEY) or "").strip().lower()
        if icon_key not in VALID_CAPABILITY_ICON_KEYS:
            raise ValueError(
                f"LLM capability {name!r} has missing or invalid icon_key: {icon_key!r}."
            )
        if not name:
            rejected.append("<empty name>")
            continue
        atomic_concept = item.get("atomic_concept")
        if not isinstance(atomic_concept, bool):
            raise ValueError(f"LLM capability {name!r} is missing atomic_concept judgement.")
        needs_review = bool(item.get(KEY_NEEDS_REVIEW))
        result.append(
            {
                KEY_NAME: name,
                KEY_LEVEL: level if level in _VALID_LEVELS else CapabilityLevel.BASIC,
                KEY_ALIASES: aliases[:alias_limit],
                KEY_ICON_KEY: icon_key,
                "atomic_concept": atomic_concept,
                KEY_NEEDS_REVIEW: needs_review,
            }
        )
    capped = result[:20]
    cap_overflow = result[20:]
    if cap_overflow:
        rejected.extend(f"{r['name']} [cap-20 overflow]" for r in cap_overflow)
    kept_names = [r["name"] for r in capped]
    _cap_log(f"[CAP_VALIDATE] kept {len(capped)}: {kept_names}")
    if rejected:
        _cap_log(f"[CAP_VALIDATE] rejected {len(rejected)}: {rejected}")
    return capped


def _validate_eligibility(raw: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    rejected: list[str] = []
    _cap_log(f"[ELIGIBILITY_VALIDATE] LLM returned {len(raw or [])} raw eligibility candidate(s)")
    for item in raw or []:
        if not isinstance(item, dict):
            rejected.append("<non-dict>")
            continue
        name = compact_whitespace(str(item.get("name") or item.get("label") or "")).strip()
        if not normalize_profile_item_name(name):
            rejected.append(name or "<empty name>")
            continue
        raw_value = item.get("value", True)
        if not isinstance(raw_value, bool):
            raise ValueError(
                f"Eligibility value must be a boolean; received {type(raw_value).__name__} for {name!r}"
            )
        value = raw_value
        evidence_raw = item.get("evidence") or []
        if isinstance(evidence_raw, str):
            evidence_raw = [evidence_raw]
        evidence = [compact_whitespace(str(text)) for text in evidence_raw if compact_whitespace(str(text))]
        result.append(
            {
                "name": name,
                "value": value,
                "evidence": evidence[:6],
                "needs_review": bool(item.get("needs_review")),
            }
        )
    capped = result[:20]
    overflow = result[20:]
    if overflow:
        rejected.extend(f"{r['name']} [eligibility-20 overflow]" for r in overflow)
    kept_names = [r["name"] for r in capped]
    _cap_log(f"[ELIGIBILITY_VALIDATE] kept {len(capped)}: {kept_names}")
    if rejected:
        _cap_log(f"[ELIGIBILITY_VALIDATE] rejected {len(rejected)}: {rejected}")
    return capped


def _validate_qualifications(raw: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = compact_whitespace(item.get("name") or item.get("label"))
        name_key = name.casefold()
        if not name_key or name_key in seen:
            continue
        aliases = item.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        evidence = item.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        result.append(
            {
                "name": name,
                "aliases": [compact_whitespace(value) for value in aliases if compact_whitespace(value)],
                "evidence": [compact_whitespace(value) for value in evidence if compact_whitespace(value)],
                "value": True,
                "needs_review": bool(item.get("needs_review")),
            }
        )
        seen.add(name_key)
        if len(result) >= 20:
            break
    return result


def _aggregate_role_experience(raw: list[Any]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}

    for item in raw or []:
        if not isinstance(item, dict):
            continue

        display_title = compact_whitespace(str(item.get("title") or ""))
        raw_title = _simple_title(display_title)
        canonical_title = _simple_title(item.get("canonical_title") or "")
        normalized_title = canonical_title or raw_title
        if not normalized_title:
            continue

        duration_months = max(int(item.get("duration_months") or 0), 0)
        end_year = max(int(item.get("end_year") or 0), 0)
        is_current = bool(item.get("is_current"))
        if is_current:
            end_year = max(end_year, _CURRENT_YEAR)

        existing = aggregated.setdefault(
            normalized_title,
            {
                "normalized_title": normalized_title,
                "total_duration_months": 0,
                "most_recent_end_year": 0,
                "title_variants": {},
                "segments": [],
            },
        )
        existing["total_duration_months"] = int(existing["total_duration_months"]) + duration_months
        existing["most_recent_end_year"] = max(int(existing["most_recent_end_year"]), end_year)

        # Keep each raw segment's is_current so job-match time can accrue elapsed
        # months onto a still-current role. duration_as_of is stamped upstream
        # (_stamp_current_role_extraction_dates) only for genuine extractions.
        segment: dict[str, Any] = {
            "duration_months": duration_months,
            "is_current": is_current,
        }
        if is_current:
            duration_as_of = str(item.get("duration_as_of") or "").strip()
            if duration_as_of:
                segment["duration_as_of"] = duration_as_of
        existing["segments"].append(segment)

        variant_title = raw_title or normalized_title
        variants = existing["title_variants"]
        variant = variants.setdefault(
            variant_title,
            {
                "title": display_title or variant_title,
                "normalized_title": variant_title,
                "total_duration_months": 0,
                "most_recent_end_year": 0,
            },
        )
        variant["total_duration_months"] = int(variant["total_duration_months"]) + duration_months
        variant["most_recent_end_year"] = max(int(variant["most_recent_end_year"]), end_year)

    result: list[dict[str, Any]] = []
    for key in sorted(aggregated):
        row = aggregated[key]
        variants = row.pop("title_variants", {})
        row["title_variants"] = [variants[name] for name in sorted(variants)]
        result.append(row)
    return result


def _dedupe_role_titles(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        cleaned = _simple_title(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _resolve_extracted_role_families(
    titles: list[str], role_experience: list[dict[str, Any]]
) -> list[str]:
    """Use the same extraction response to propose confirmed role families."""
    family_by_variant: dict[str, set[str]] = {}
    for row in role_experience:
        if not isinstance(row, dict):
            continue
        family = _simple_title(row.get("normalized_title") or "")
        if not family:
            continue
        for variant in row.get("title_variants") or []:
            if not isinstance(variant, dict):
                continue
            title = _simple_title(variant.get("normalized_title") or "")
            if title:
                family_by_variant.setdefault(title, set()).add(family)

    resolved: list[str] = []
    for title in titles:
        candidates = family_by_variant.get(_simple_title(title), set())
        resolved.append(next(iter(candidates)) if len(candidates) == 1 else title)
    return _dedupe_role_titles(resolved)


def _capability_context_sections(
    capability_name: str,
    aliases: list[str],
    source_sections: list[dict[str, str]] | None = None,
    *,
    max_hits: int = 3,
) -> list[str]:
    if not source_sections:
        return []

    terms = [
        str(capability_name or "").strip(),
        *(str(alias or "").strip() for alias in aliases or []),
    ]
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


def _split_learning_capabilities(
    capabilities: list[dict[str, Any]],
    *,
    source_sections: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    approved: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []

    for item in capabilities:
        name = str(item.get(KEY_NAME) or "").strip()
        aliases = [
            str(alias).strip() for alias in (item.get(KEY_ALIASES) or []) if str(alias).strip()
        ]
        needs_review = bool(item.get(KEY_NEEDS_REVIEW))
        atomic_concept = bool(item.get("atomic_concept"))
        if not atomic_concept:
            # The LLM could not reduce this row to one reusable concept. The
            # concrete atomic rows it emitted separately remain eligible for review.
            continue
        known_signal, knowledge_match = signal_in_approved_knowledge(CAT_CAPABILITY, name, aliases)

        if needs_review and not known_signal:
            review_signals.append(
                {
                    LEARNING_SIGNAL_KEY: name,
                    LEARNING_CATEGORY_KEY: CAT_CAPABILITY,
                    LEARNING_SOURCE_KEY: SOURCE_CV_PARSING,
                    LEARNING_CONTEXT_KEY: _capability_context_sections(
                        name, aliases, source_sections
                    ),
                    LEARNING_EVIDENCE_KEY: [name, *aliases],
                    SIGNAL_ALIASES_KEY: aliases,
                    LEARNING_NEEDS_REVIEW_KEY: True,
                }
            )
            continue

        cleaned = dict(item)
        cleaned.pop("atomic_concept", None)
        cleaned[KEY_NEEDS_REVIEW] = False if known_signal else needs_review
        if knowledge_match:
            cleaned[LEARNING_KNOWLEDGE_MATCH_KEY] = knowledge_match
        approved.append(cleaned)

    return approved, review_signals


def build_learning_patch(
    text: str,
    onboarding_settings: dict[str, Any] | None = None,
    source_sections: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    source_text = repair_text(text)
    if not source_text:
        return {}

    lookback_years = _resolve_extraction_lookback_years(onboarding_settings)
    alias_limit = _resolve_onboarding_int(onboarding_settings or {}, KEY_CAPABILITY_ALIAS_LIMIT)
    preset_name = (
        str((onboarding_settings or {}).get("capability_strength_preset") or "").strip()
        or "(default)"
    )
    _cap_log(
        format_log_block(
            "BUILD_LEARNING_PATCH",
            {
                "route": "onboarding",
                "capability_strength_preset": preset_name,
                "lookback_years": lookback_years,
                "alias_limit": alias_limit,
                "source_sections": len(source_sections or []),
                "source_chars": len(source_text),
            },
        )
    )
    extracted = _llm_extract_from_cv(source_text, lookback_years, alias_limit)

    patch: dict[str, Any] = {}

    raw_caps = extracted.get(KEY_CAPABILITIES, [])
    raw_eligibility = extracted.get("eligibility", [])
    _cap_log(
        f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(raw_caps)} capability candidate(s) before validation"
    )
    capabilities = _validate_capabilities(raw_caps, alias_limit=alias_limit)
    eligibility = _validate_eligibility(raw_eligibility)
    qualifications = _validate_qualifications(extracted.get("qualifications") or [])
    role_experience = _aggregate_role_experience(extracted.get(KEY_ROLE_EXPERIENCE) or [])
    approved_capabilities, review_signals = _split_learning_capabilities(
        capabilities, source_sections=source_sections
    )
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(approved_capabilities)} capability group(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(eligibility)} eligibility fact(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(qualifications)} qualification(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(role_experience)} role experience row(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(review_signals)} capability signal(s) need review")

    raw_titles = extracted.get("role_titles") or []
    extracted_titles = _dedupe_role_titles(raw_titles)
    preferred_titles = _resolve_extracted_role_families(
        _dedupe_role_titles(extracted.get("preferred_role_titles") or []), role_experience
    )
    alternative_titles_raw = _resolve_extracted_role_families(
        _dedupe_role_titles(extracted.get("alternative_role_titles") or []), role_experience
    )
    alternative_titles = [
        value for value in alternative_titles_raw if value not in set(preferred_titles)
    ]
    _cap_log(
        f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(extracted_titles)} role title(s)"
    )
    _cap_log(
        f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(preferred_titles)} preferred role title(s)"
    )
    _cap_log(
        f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(alternative_titles)} alternative role title(s)"
    )

    missing: list[str] = []
    if not approved_capabilities:
        missing.append("capability groups")
    if not extracted_titles:
        missing.append("role titles")
    if not preferred_titles:
        missing.append("preferred role titles")
    if missing:
        raise ValueError("LLM did not return required onboarding data: " + ", ".join(missing) + ".")

    _cap_log(
        "[ONBOARDING][LLM_CALL_DONE] purpose=cv_extraction "
        f"capability_count={len(approved_capabilities)} role_title_count={len(extracted_titles)} "
        f"preferred_role_count={len(preferred_titles)} alternative_role_count={len(alternative_titles)} "
        "role_suggestions_are_transient=true"
    )

    patch[KEY_CANDIDATE_CAPABILITIES] = approved_capabilities
    patch[KEY_CANDIDATE_ELIGIBILITY] = eligibility
    patch[KEY_CANDIDATE_QUALIFICATIONS] = qualifications
    patch[KEY_ROLE_EXPERIENCE] = role_experience
    if review_signals and not is_desktop_runtime():
        register_signals(review_signals)

    max_target = _resolve_onboarding_int(onboarding_settings, KEY_MAX_TARGET)
    max_secondary = _resolve_onboarding_int(onboarding_settings, KEY_MAX_SECONDARY)
    patch[ROLE_SUGGESTIONS_KEY] = {
        KEY_PRIMARY_PATTERNS: preferred_titles[:max_target],
        KEY_SECONDARY_PATTERNS: alternative_titles[:max_secondary],
    }

    raw_prefs = extracted.get(KEY_MATCH_PREFS) or {}
    match_prefs = {k: v for k, v in raw_prefs.items() if v is not None and v != ""}
    if match_prefs:
        patch[KEY_MATCH_PREFS] = match_prefs

    return patch


def build_role_history_patch(
    text: str,
    onboarding_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract role history only from CV text.

    This exists for the settings-screen refresh action. It intentionally replaces the
    entire ``role_experience`` section with a fresh first-pass extraction from the
    saved CV source pack. It does not merge, diff, or preserve previous rows.
    """
    source_text = repair_text(text)
    if not source_text:
        return {KEY_ROLE_EXPERIENCE: []}

    lookback_years = _resolve_extraction_lookback_years(onboarding_settings)
    alias_limit = _resolve_onboarding_int(onboarding_settings or {}, KEY_CAPABILITY_ALIAS_LIMIT)
    _cap_log(
        format_log_block(
            "BUILD_ROLE_HISTORY_PATCH",
            {
                "route": "settings_role_history_refresh",
                "lookback_years": lookback_years,
                "alias_limit": alias_limit,
                "source_chars": len(source_text),
            },
        )
    )
    extracted = _llm_extract_from_cv(source_text, lookback_years, alias_limit)
    role_experience = _aggregate_role_experience(extracted.get(KEY_ROLE_EXPERIENCE) or [])
    _cap_log(f"[BUILD_ROLE_HISTORY_PATCH] {len(role_experience)} role experience row(s) written")
    return {KEY_ROLE_EXPERIENCE: role_experience}
