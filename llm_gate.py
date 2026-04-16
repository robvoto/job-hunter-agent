"""LLM fit-decision gateway.

Main goals:
- build the compact candidate context sent to the LLM
- request a constrained decision plus graded description-fit tier
- keep prompt structure and cache keys aligned with the current profile state

Notes:
- deterministic filters run before this in the main source connector flow
- the AI fit brief is preferred over raw background text to reduce noise and cost
"""

import hashlib
import os
import sys
from typing import Any, Dict

from openai import OpenAI

from agent_settings import load_agent_settings
from profile_store import DATA_DIR, get_evidence_tiers, get_evidence_tier_weights, load_profile

# Token budgets — keep fit decisions tight; extraction can be generous
MAX_TOKENS_FIT_DECISION = 20
MAX_TOKENS_CV_EXTRACTION = 500

# Test-mode flag: mirrors the same argv check in source_connector
_TEST_SCRAPE_MODE = "--test-scrape-mode" in sys.argv

_PROFILE_PATH = DATA_DIR / "profile.json"
_profile_fingerprint_cache: str | None = None


def _profile_fingerprint() -> str:
    """Cheap fingerprint of the profile file — mtime + size, no read/parse.
    Cached for the lifetime of the process so repeated cache-key lookups in a
    single scraping run are O(1) after the first call.
    """
    global _profile_fingerprint_cache
    if _profile_fingerprint_cache is not None:
        return _profile_fingerprint_cache
    try:
        st = _PROFILE_PATH.stat()
        raw = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        raw = "no-profile"
    _profile_fingerprint_cache = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return _profile_fingerprint_cache


def _get_llm_model() -> str:
    """Return the configured model, falling back to gpt-4.1-mini.
    In test-scrape mode uses gpt-4o-mini to reduce cost during testing.
    """
    if _TEST_SCRAPE_MODE:
        return "gpt-4o-mini"
    return load_agent_settings().get("llm", {}).get("model", "gpt-4.1-mini")


_llm_model_logged = False


def _log_llm_model_once() -> str:
    """Print the active model to the terminal on first use. Returns the model string."""
    global _llm_model_logged
    model = _get_llm_model()
    if not _llm_model_logged:
        source = "test-scrape override" if _TEST_SCRAPE_MODE else "agent_settings.json"
        print(f"[LLM] Model: {model}  (source: {source})")
        _llm_model_logged = True
    return model


_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if _api_key else None
ALLOWED_DECISIONS = {"KEEP", "REJECT", "MAYBE"}
ALLOWED_GRADES = {"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"}
DEFAULT_LLM_REVIEW = {"decision": "MAYBE", "grade": "SOLID"}


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    profile = load_profile()
    strengths = [str(item).strip() for item in profile.get("strengths", []) if str(item).strip()]
    llm_profile_brief = str(profile.get("llm_profile_brief") or "").strip()
    star_evidence_text = str(profile.get("star_evidence_text") or "").strip()
    evidence_tiers = get_evidence_tiers(profile)
    evidence_weights = get_evidence_tier_weights(profile)
    capability_rules = profile.get("capability_profile_rules", [])
    salary_preferences = profile.get("salary_preferences", {})
    match_preferences = profile.get("match_preferences", {}) if isinstance(profile.get("match_preferences", {}), dict) else {}

    parts = []
    if llm_profile_brief:
        parts.append("Candidate fit brief:")
        parts.append(llm_profile_brief[:2500])
    elif strengths:
        parts.append("Core strengths: " + ", ".join(strengths[:12]) + ".")

    if capability_rules:
        parts.append("Capability levels:")
        for rule in capability_rules[:12]:
            name = str(rule.get("name") or "").strip()
            level = str(rule.get("level") or "").strip()
            fit = str(rule.get("fit") or "").strip()
            aliases = ", ".join(str(alias).strip() for alias in rule.get("aliases", [])[:8] if str(alias).strip())
            if name and level:
                fit_text = f", {fit}" if fit else ""
                parts.append(f"- {name}: {level}{fit_text}" + (f" ({aliases})" if aliases else ""))

    preference_lines = []
    minimum_salary_yearly = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    minimum_daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    if minimum_salary_yearly > 0 or minimum_daily_rate > 0:
        preference_lines.append(
            f"Compensation target: permanent roles around {minimum_salary_yearly or 'not set'} yearly, contract roles around {minimum_daily_rate or 'not set'} per day."
        )
    if match_preferences.get("home_location"):
        preference_lines.append(f"Home base: {match_preferences.get('home_location')}.")
    if match_preferences.get("prefer_permanent"):
        preference_lines.append("Prefer permanent roles first, then 12+ month contracts with extensions, then shorter contracts.")
    if preference_lines:
        parts.append("Match preferences:")
        parts.extend(f"- {line}" for line in preference_lines)

    if star_evidence_text:
        parts.append("STAR / evidence examples:")
        parts.append(star_evidence_text[:1500])

    primary_evidence = str(evidence_tiers.get("primary_current_evidence") or "").strip()
    secondary_evidence = str(evidence_tiers.get("secondary_older_evidence") or "").strip()
    background_evidence = str(evidence_tiers.get("background_optional_evidence") or "").strip()

    if primary_evidence:
        parts.append(
            f"Primary current evidence (strongest weight {evidence_weights.get('primary_current_evidence', 1.0):.2f}):"
        )
        parts.append(primary_evidence[:1600])
    if secondary_evidence:
        parts.append(
            f"Secondary older evidence (lower weight {evidence_weights.get('secondary_older_evidence', 0.55):.2f}):"
        )
        parts.append(secondary_evidence[:900])
    if background_evidence:
        parts.append(
            f"Background-only context (weakest weight {evidence_weights.get('background_optional_evidence', 0.25):.2f}):"
        )
        parts.append(background_evidence[:600])

    return "\n".join(part for part in parts if part)


def build_system_prompt() -> str:
    parts = [
        "You are helping decide whether a candidate should apply for a job.",
        "Judge fit primarily from the job description and the candidate profile evidence below, not from title alone.",
        "Be honest about gaps. Adjacent titles can still fit when responsibilities match the candidate background.",
        "Recent directly relevant experience matters more than older exposure from many years ago.",
        "Treat primary current evidence as strongest proof. Treat older evidence as weaker, and background-only context such as certifications, broad industry mentions, or optional supporting history as weakest.",
        "Treat desirable or nice-to-have gaps as softer concerns than essential or mandatory gaps.",
        "Grade the full description fit, not just keyword overlap.",
        "Do not reject only because finance, treasury, or ERP terms appear if the core work still reads like generalist business analysis.",
        "Reward roles that match BPMN, workshops, user stories, stakeholder alignment, discovery, process mapping, and government delivery context.",
        build_profile_prompt_context(),
    ]
    parts.append(
        "Answer with exactly ONE line in uppercase using this format: DECISION|GRADE. "
        "DECISION must be KEEP, REJECT, or MAYBE. "
        "GRADE must be EXCELLENT, STRONG, SOLID, WEAK, POOR, or MISMATCH. "
        "Use EXCELLENT or STRONG for clearly aligned roles, SOLID for broadly aligned roles with manageable gaps, "
        "WEAK for superficial or mixed fit, POOR for very limited fit, and MISMATCH for clear mismatch. "
        "Do not explain your answer."
    )
    return "\n".join(part for part in parts if part)


def build_llm_cache_key(job_description_text: str) -> str:
    desc_hash = hashlib.sha256(str(job_description_text or "").encode("utf-8", errors="ignore")).hexdigest()
    return f"{_profile_fingerprint()}:{desc_hash}"


def normalize_llm_review(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        decision = str(value.get("decision") or "").strip().upper()
        grade = str(value.get("grade") or "").strip().upper()
        if decision in ALLOWED_DECISIONS and grade in ALLOWED_GRADES:
            return {"decision": decision, "grade": grade}

    if isinstance(value, str):
        text = value.strip().upper()
        if "|" in text:
            decision, _, grade = text.partition("|")
            if decision in ALLOWED_DECISIONS and grade in ALLOWED_GRADES:
                return {"decision": decision, "grade": grade}
        if text in ALLOWED_DECISIONS:
            legacy_grade_map = {
                "KEEP": "STRONG",
                "MAYBE": "SOLID",
                "REJECT": "MISMATCH",
            }
            return {"decision": text, "grade": legacy_grade_map[text]}

    return dict(DEFAULT_LLM_REVIEW)


def extract_strengths_from_cv(cv_text: str) -> list[str]:
    """Call LLM to extract skill/strength keywords from CV text. Returns [] if LLM unavailable."""
    if client is None or not str(cv_text or "").strip():
        return []
    prompt = (
        "Extract the candidate's core professional strengths from the CV below. "
        "Rules: only include a skill if (1) used for 2 or more years total, "
        "(2) used within the last 7 years, and (3) was a core responsibility not a side tool. "
        "Return a JSON array of short keyword phrases (1-4 words each), maximum 20 items, "
        "ordered by relevance. Only return the JSON array, no explanation.\n\nCV:\n"
        + str(cv_text)[:4000]
    )
    try:
        resp = client.responses.create(
            model=_get_llm_model(),
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=MAX_TOKENS_CV_EXTRACTION,
        )
        import json as _json
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        items = _json.loads(raw)
        if isinstance(items, list):
            return [str(item).strip().lower() for item in items if str(item).strip()][:20]
    except Exception:
        pass
    return []


def extract_title_patterns_from_cv(cv_text: str, onboarding_settings: dict | None = None) -> dict:
    """Call LLM to extract title/search patterns from CV work history.

    Returns {"target_title_patterns": [...], "adjacent_title_patterns": [...], "suggested_search_keywords": [...]}
    or empty lists if LLM is unavailable or extraction fails.
    """
    if client is None:
        print("[TITLE_PATTERNS] Skipped — LLM client is None (no OPENAI_API_KEY?)")
        return {"target_title_patterns": [], "adjacent_title_patterns": [], "suggested_search_keywords": []}
    if not str(cv_text or "").strip():
        print("[TITLE_PATTERNS] Skipped — cv_text is empty")
        return {"target_title_patterns": [], "adjacent_title_patterns": [], "suggested_search_keywords": []}

    settings = onboarding_settings or {}
    lookback_years = max(1, int(settings.get("title_extraction_lookback_years") or 8))
    min_months = max(1, int(settings.get("title_extraction_min_months") or 6))
    max_target = max(1, int(settings.get("max_target_patterns") or 8))
    max_adjacent = max(1, int(settings.get("max_adjacent_patterns") or 6))

    print(f"[TITLE_PATTERNS] Calling LLM with {len(cv_text)} chars of CV text (lookback={lookback_years}y, min={min_months}mo, max_target={max_target}, max_adjacent={max_adjacent})")
    prompt = (
        "You are reading a candidate's CV. Extract job search targeting patterns from their work history.\n\n"
        "Return a JSON object with exactly three keys:\n"
        f"- \"target_title_patterns\": regex patterns (case-insensitive, matched against lowercase job titles) "
        f"for roles the candidate directly targets. Use \\\\b word-boundary anchors. Up to {max_target} patterns.\n"
        f"- \"adjacent_title_patterns\": regex patterns for roles the candidate could step into based on their experience. Up to {max_adjacent} patterns.\n"
        "- \"suggested_search_keywords\": broad job-title search terms for a job board like Seek. 2-4 keywords.\n\n"
        "Rules for target_title_patterns:\n"
        f"- Only include roles the candidate actually held for more than {min_months} months.\n"
        f"- Only include roles that ended within the last {lookback_years} years (today is 2026-04-16).\n"
        "- Base patterns on real job titles from the CV work history — not skills, tools, or certifications.\n"
        "- If uncertain whether a role qualifies, exclude it. Fewer accurate patterns beat many noisy ones.\n\n"
        "Rules for adjacent_title_patterns:\n"
        "- Adjacent means a real job title the candidate could credibly apply for, based on their experience.\n"
        "- Do NOT include tool or platform names as adjacent titles (SAP, Salesforce, Guidewire, Workday etc. are tools, not job titles).\n\n"
        "Rules for suggested_search_keywords:\n"
        "- Must be a broad job title phrase of 2-3 words maximum (e.g. 'business analyst', 'product owner').\n"
        "- Do NOT use tool names, certifications, or domain terms as keywords.\n\n"
        "Use lowercase for all patterns and keywords. Only return the JSON object, no explanation.\n\nCV:\n"
        + str(cv_text)[:4000]
    )
    try:
        resp = client.responses.create(
            model=_get_llm_model(),
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=MAX_TOKENS_CV_EXTRACTION,
        )
        import json as _json
        raw = (resp.output_text or "").strip()
        print(f"[TITLE_PATTERNS] Raw LLM response: {raw[:300]}")
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = _json.loads(raw)
        if isinstance(data, dict):
            result = {
                "target_title_patterns": [str(p).strip() for p in data.get("target_title_patterns", []) if str(p).strip()][:max_target],
                "adjacent_title_patterns": [str(p).strip() for p in data.get("adjacent_title_patterns", []) if str(p).strip()][:max_adjacent],
                "suggested_search_keywords": [str(p).strip() for p in data.get("suggested_search_keywords", []) if str(p).strip()][:5],
            }
            print(f"[TITLE_PATTERNS] Extracted: {len(result['target_title_patterns'])} target, {len(result['adjacent_title_patterns'])} adjacent, {len(result['suggested_search_keywords'])} keywords")
            return result
        print(f"[TITLE_PATTERNS] LLM returned non-dict: {type(data)}")
    except Exception as exc:
        print(f"[TITLE_PATTERNS] Exception: {exc}")
    return {"target_title_patterns": [], "adjacent_title_patterns": [], "suggested_search_keywords": []}


def llm_should_consider(job_description_text: str) -> Dict[str, str]:
    if client is None:
        return dict(DEFAULT_LLM_REVIEW)

    try:
        resp = client.responses.create(
            model=_log_llm_model_once(),
            input=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": "Job description:\n" + job_description_text},
            ],
            max_output_tokens=MAX_TOKENS_FIT_DECISION,
        )
    except Exception as exc:
        print(f"[LLM][ERROR] {exc}")
        return dict(DEFAULT_LLM_REVIEW)

    normalized = normalize_llm_review((resp.output_text or "").strip().upper())
    if normalized == DEFAULT_LLM_REVIEW and (resp.output_text or "").strip():
        print(f"[LLM][UNEXPECTED] {(resp.output_text or '').strip()}")
    return normalized
