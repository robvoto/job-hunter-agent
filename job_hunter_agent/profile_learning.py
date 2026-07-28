"""Profile learning helpers.

This module provides utilities for processing and learning from candidate CV text.
It focuses on extracting structured information, such as capabilities, role titles,
and occupation queries, for use in the job matching and profile building processes.

Key functionalities include:
- Repairing common text encoding and formatting issues in imported CV text.
- Extracting capabilities, role titles, and occupation queries from CV text using LLMs.
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
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal

logger = logging.getLogger(__name__)

from pydantic import BaseModel, ConfigDict, Field

from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.paths import OUTPUT_DIR
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    KEY_ALIASES,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CANDIDATE_ELIGIBILITY,
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
    KEY_TARGET_OCCUPATION_QUERIES,
    VALID_CAPABILITY_ICON_KEYS,
    CapabilityLevel,
)
from job_hunter_agent.runtime_helpers import is_desktop_runtime
from job_hunter_agent.text_processing import compact_whitespace

KEY_NEEDS_REVIEW = "needs_review"


def _simple_title(value: str) -> str:
    """Normalize a role title for onboarding: trim, lowercase, collapse whitespace only."""
    return compact_whitespace(value).lower()


from job_hunter_agent.global_settings import (
    KEY_CAPABILITY_ALIAS_LIMIT,
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

CAP_DEBUG_LOG = OUTPUT_DIR / "capability_debug.log"

# Internal result key
KEY_CAPABILITIES = "capabilities"

# Signal categories
CAT_CAPABILITY = CATEGORY_CAPABILITY_CONCEPT

_VALID_LEVELS = {CapabilityLevel.STRONG, CapabilityLevel.WORKING, CapabilityLevel.BASIC}
_CURRENT_YEAR = datetime.now().year


def _cap_log(msg: str) -> None:
    logger.info("%s", msg)
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with CAP_DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception as exc:
        logger.warning("[CAP_LOG ERROR] could not write capability_debug.log: %s", exc)


def clear_capability_debug_log() -> None:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        CAP_DEBUG_LOG.write_text(
            f"# capability_debug.log — onboarding run {datetime.now().isoformat()}Z\n",
            encoding="utf-8",
        )
        logger.info("[CAP_LOG] capability_debug.log reset at %s", CAP_DEBUG_LOG)
    except Exception as exc:
        logger.warning("[CAP_LOG ERROR] could not reset capability_debug.log: %s", exc)


_BULLET_PREFIX_RE = re.compile(r"^[\-*•–—]+\s*")

_cv_extraction_cache: dict[str, dict[str, Any]] = {}
_cv_extraction_cache_loaded = False


class _CapabilityExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: Literal["strong", "working", "basic"]
    aliases: list[str] = Field(default_factory=list)
    icon_key: str
    needs_review: bool = False


class _EligibilityExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: bool = True
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


class _CvExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[_CapabilityExtraction] = Field(default_factory=list)
    eligibility: list[_EligibilityExtraction] = Field(default_factory=list)
    match_preferences: _MatchPreferenceExtraction = Field(
        default_factory=_MatchPreferenceExtraction
    )
    role_experience: list[_RoleExperienceExtraction] = Field(default_factory=list)
    role_titles: list[str] = Field(default_factory=list)
    target_occupation_queries: list[str] = Field(default_factory=list)


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


def _llm_extract_from_cv(source_text: str, lookback_years: int, alias_limit: int) -> dict[str, Any]:
    """Single LLM call: extract capabilities, title patterns, and match preferences from CV text."""
    _ensure_cv_extraction_cache_loaded()
    cache_key = hashlib.sha256(
        f"icon-v3:{lookback_years}:{alias_limit}:{source_text}".encode()
    ).hexdigest()[:16]
    if cache_key in _cv_extraction_cache:
        cached = _cv_extraction_cache[cache_key]
        _cap_log(
            "[ONBOARDING][LLM_CACHE_HIT] purpose=cv_extraction "
            f"cache_key={cache_key} "
            f"capabilities={len(cached.get(KEY_CAPABILITIES, []) or [])} "
            f"role_experience={len(cached.get(KEY_ROLE_EXPERIENCE, []) or [])} "
            f"role_titles={len(cached.get('role_titles', []) or [])} "
            f"target_queries={len(cached.get(KEY_TARGET_OCCUPATION_QUERIES, []) or [])}"
        )
        return cached

    try:
        from job_hunter_agent.llm_gate import _log_llm_call, client, get_llm_model
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
        "- capabilities: extract 8–15 transferable professional skills when the CV supports them. "
        "Not company names, employer names, job titles, or raw phrase fragments. "
        "Each capability must be a named skill or practice area grounded in the CV bullets, skills section, summary, or experience text. "
        "Set level='strong' only for current or recent strengths that are repeated and clearly senior. "
        "Older evidence should usually be 'working' or 'basic' unless the CV still shows current depth. "
        "Set needs_review=true when the capability is plausible but you are not confident it belongs in the final profile. "
        f"For each capability include up to {alias_limit} aliases: known abbreviations, acronyms, and recruiter synonyms "
        "that refer to the same skill (e.g. for 'business process modeling': ['bpmn', 'process mapping', 'workflow design']). "
        "Only include aliases that are grounded in the evidence or are widely recognised industry synonyms.\n"
        f"For each capability, set icon_key to exactly one of: {', '.join(sorted(VALID_CAPABILITY_ICON_KEYS))}.\n"
        "- match_preferences: infer only from explicit statements; leave fields empty or null when not stated.\n"
        "- role_experience: for each explicit role in the CV, return the title as shown, a canonical_title when close title variants clearly belong to the same role family, plus duration_months and end_year.\n"
        "  Example: BA, Business Analyst, and Senior BA can share canonical_title='Business Analyst' when the CV evidence clearly supports that grouping.\n"
        "  Keep title as the displayed role wording from the CV. Use the current year for Present/current roles and skip entries where the title cannot be identified.\n"
        "- role_titles: list the job titles explicitly shown in the CV. One entry per role, no duplicates.\n"
        "- target_occupation_queries: generate 3 to 8 machine-facing occupation query strings that match the candidate's occupation family.\n"
        "  Use standard job titles a job-search system could match against.\n"
        "- eligibility: extract explicit true/false facts the candidate formally holds or is legally allowed to claim. "
        "Examples include clearances, citizenship, work rights, licences, registrations, and certifications. "
        "Only include facts that are directly supported by the CV text.\n"
        "- Do not invent employers, titles, capabilities, or preferences that are not grounded in the evidence.\n"
        "- Return only schema-valid output.\n\n"
        f"CV text:\n{source_text}"
    )

    _cap_log(f"[ONBOARDING][LLM_CALL_START] purpose=cv_extraction cache_key={cache_key}")
    try:
        model = get_llm_model()
        resp = client.responses.parse(
            model=model,
            input=[{"role": "user", "content": prompt}],
            text_format=_CvExtractionResponse,
            max_output_tokens=profile_extraction_max_output_tokens,
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

    _cap_log(
        "[ONBOARDING][LLM_CALL_DONE] purpose=cv_extraction "
        f"cache_key={cache_key} "
        f"capabilities={len(result.get(KEY_CAPABILITIES, []) or [])} "
        f"eligibility={len(result.get('eligibility', []) or [])} "
        f"role_experience={len(result.get(KEY_ROLE_EXPERIENCE, []) or [])} "
        f"role_titles={len(result.get('role_titles', []) or [])} "
        f"target_queries={len(result.get(KEY_TARGET_OCCUPATION_QUERIES, []) or [])}"
    )

    _cv_extraction_cache[cache_key] = result
    try:
        from job_hunter_agent.io_utils import save_cv_extraction_cache

        save_cv_extraction_cache(_cv_extraction_cache)
    except Exception:
        pass
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
        needs_review = bool(item.get(KEY_NEEDS_REVIEW))
        result.append(
            {
                KEY_NAME: name,
                KEY_LEVEL: level if level in _VALID_LEVELS else CapabilityLevel.BASIC,
                KEY_ALIASES: aliases[:6],
                KEY_ICON_KEY: icon_key,
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
        if not name:
            rejected.append("<empty name>")
            continue
        raw_value = item.get("value", True)
        if isinstance(raw_value, str):
            lowered_value = raw_value.strip().lower()
            if lowered_value in {"false", "no", "n", "0", "absent", "missing", "none"}:
                value = False
            elif lowered_value in {"true", "yes", "y", "1", "have", "has", "held", "present"}:
                value = True
            else:
                value = bool(raw_value)
        else:
            value = bool(raw_value)
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


def _aggregate_role_experience(raw: list[Any]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}

    for item in raw or []:
        if not isinstance(item, dict):
            continue

        raw_title = _simple_title(item.get("title") or "")
        canonical_title = _simple_title(item.get("canonical_title") or "")
        normalized_title = canonical_title or raw_title
        if not normalized_title:
            continue

        duration_months = max(int(item.get("duration_months") or 0), 0)
        end_year = max(int(item.get("end_year") or 0), 0)
        if bool(item.get("is_current")):
            end_year = max(end_year, _CURRENT_YEAR)

        existing = aggregated.setdefault(
            normalized_title,
            {
                "normalized_title": normalized_title,
                "total_duration_months": 0,
                "most_recent_end_year": 0,
                "title_variants": {},
            },
        )
        existing["total_duration_months"] = int(existing["total_duration_months"]) + duration_months
        existing["most_recent_end_year"] = max(int(existing["most_recent_end_year"]), end_year)

        variant_title = raw_title or normalized_title
        variants = existing["title_variants"]
        variant = variants.setdefault(
            variant_title,
            {
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
    capabilities = _validate_capabilities(raw_caps)
    eligibility = _validate_eligibility(raw_eligibility)
    role_experience = _aggregate_role_experience(extracted.get(KEY_ROLE_EXPERIENCE) or [])
    approved_capabilities, review_signals = _split_learning_capabilities(
        capabilities, source_sections=source_sections
    )
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(approved_capabilities)} capability group(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(eligibility)} eligibility fact(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(role_experience)} role experience row(s) written")
    _cap_log(f"[BUILD_LEARNING_PATCH] {len(review_signals)} capability signal(s) need review")

    raw_titles = extracted.get("role_titles") or []
    extracted_titles = list(
        dict.fromkeys(_simple_title(value) for value in raw_titles if _simple_title(value))
    )
    raw_queries = extracted.get(KEY_TARGET_OCCUPATION_QUERIES) or []
    occupation_queries = list(
        dict.fromkeys(
            compact_whitespace(value) for value in raw_queries if str(value or "").strip()
        )
    )
    _cap_log(
        f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(extracted_titles)} role title(s)"
    )
    _cap_log(
        f"[BUILD_LEARNING_PATCH] LLM extraction returned {len(occupation_queries)} target occupation query(ies)"
    )

    missing: list[str] = []
    if not approved_capabilities:
        missing.append("capability groups")
    if not extracted_titles:
        missing.append("role titles")
    if not occupation_queries:
        missing.append("target occupation queries")
    if missing:
        raise ValueError("LLM did not return required onboarding data: " + ", ".join(missing) + ".")

    _cap_log(
        "[ONBOARDING][LLM_CALL_DONE] purpose=cv_extraction "
        f"capability_count={len(approved_capabilities)} target_count={len(extracted_titles)} "
        f"occupation_query_count={len(occupation_queries)}"
    )

    patch[KEY_CANDIDATE_CAPABILITIES] = approved_capabilities
    patch[KEY_CANDIDATE_ELIGIBILITY] = eligibility
    patch[KEY_ROLE_EXPERIENCE] = role_experience
    if review_signals and not is_desktop_runtime():
        register_signals(review_signals)

    max_target = _resolve_onboarding_int(onboarding_settings, KEY_MAX_TARGET)
    max_secondary = _resolve_onboarding_int(onboarding_settings, KEY_MAX_SECONDARY)
    patch[KEY_PRIMARY_PATTERNS] = extracted_titles[:max_target]
    patch[KEY_SECONDARY_PATTERNS] = extracted_titles[max_target : max_target + max_secondary]
    patch[KEY_TARGET_OCCUPATION_QUERIES] = occupation_queries

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
