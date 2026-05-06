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
import json as _json_mod
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI

from job_hunter_agent.agent_settings import load_agent_settings, DEFAULT_AGENT_SETTINGS
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_DECISIONS,
    LLM_ALLOWED_GRADES,
    LLM_CHEAP_MODEL,
    LLM_EVIDENCE_TIERS,
    LLM_PROMPT_CAPABILITY_LEVELS_HEADER,
    LLM_PROMPT_CAPABILITY_NAMING_INTRO,
    LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER,
    LLM_PROMPT_CLUSTERS_HEADER,
    LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER,
    LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER,
    LLM_PROMPT_DO_NOT_INVENT,
    LLM_PROMPT_DO_NOT_SAVE,
    LLM_PROMPT_JOB_DESCRIPTION_PREFIX,
    LLM_PROMPT_JSON_ONLY,
    LLM_PROMPT_LEARNING_PENDING_ONLY,
    LLM_PROMPT_MATCH_PREFERENCES_HEADER,
    LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
    LLM_PROMPT_REVIEW_OUTPUT_FORMAT,
    LLM_PROMPT_SYSTEM_REVIEW_INTRO,
    LLM_PROMPT_USE_AT_MOST_FOUR,
    LLM_PROMPT_USE_AT_MOST_SIX,
    LLM_PROMPT_USE_VISIBLE_STRINGS,
    LLM_PROMPT_USER_CAPABILITY_NAMING_GUIDANCE_HEADER,
    LLM_PROMPT_USER_FIT_REVIEW_GUIDANCE_HEADER,
    LLM_LEARNING_ONLY_PROMPT_SHAPE,
    LLM_MAX_TOKENS_CV_EXTRACTION,
    LLM_MAX_TOKENS_FIT_DECISION,
    LLM_MAX_TOKENS_REJECTION_SUGGESTIONS,
    LLM_REVIEW_GRADE_GUIDANCE,
    LLM_REVIEW_PROMPT_SHAPE,
)
from job_hunter_agent.profile_store import (
    get_candidate_profile_tier_weights,
    get_candidate_profile_tiers,
    DATA_DIR,
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_CAPABILITY_PROFILE_RULES,
    load_profile,
)
from job_hunter_agent.paths import (
    FIT_REVIEW_DEFAULTS_PATH as _FIT_REVIEW_DEFAULTS_PATH,
    LLM_CAPABILITY_NAMING_DEFAULTS_PATH as _CAPABILITY_NAMING_DEFAULTS_PATH,
    LLM_COSTS_PATH as _LLM_COSTS_PATH,
    PROFILE_PATH as _PROFILE_PATH,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_HARD_BLOCKER_PATTERN,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    VALID_SIGNAL_CATEGORIES,
)
from job_hunter_agent.paths import REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH as _REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH

load_dotenv()

# Cheap-llm flag: mirrors the same argv check in source_connector
_CHEAP_LLM_MODE = "--cheap-llm" in sys.argv

MODEL_FALLBACK = DEFAULT_AGENT_SETTINGS["llm"]["model"]


_profile_fingerprint_cache: str | None = None
#HARCODED
# Cost logging --------------------------------------------------------
_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini":              {"input": 0.15,  "output": 0.60},
    "gpt-4o-mini-2024-07-18":  {"input": 0.15,  "output": 0.60},
    "gpt-4o":                   {"input": 2.50,  "output": 10.00},
    "gpt-4o-2024-08-06":       {"input": 2.50,  "output": 10.00},
}
_session_cost_usd: float = 0.0


def _log_llm_call(resp: Any, purpose: str, model: str) -> None:
    global _session_cost_usd
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    # Responses API uses input_tokens/output_tokens; Chat uses prompt_tokens/completion_tokens
    tok_in  = getattr(usage, "input_tokens",  None) or getattr(usage, "prompt_tokens",     0) or 0
    tok_out = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens",  0) or 0
    prices  = _PRICING_PER_1M.get(model, {"input": 2.50, "output": 10.00})
    cost    = (tok_in * prices["input"] + tok_out * prices["output"]) / 1_000_000
    _session_cost_usd += cost

    entry = {
        "ts":          datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose":     purpose,
        "model":       model,
        "tok_in":      tok_in,
        "tok_out":     tok_out,
        "cost_usd":    round(cost, 6),
        "session_usd": round(_session_cost_usd, 6),
    }
    try:
        with open(_LLM_COSTS_PATH, "a", encoding="utf-8") as fh:
            fh.write(_json_mod.dumps(entry) + "\n")
    except Exception:
        pass
    print(
        f"[LLM] {purpose} | {model} | "
        f"in={tok_in} out={tok_out} | "
        f"${cost:.6f} | session=${_session_cost_usd:.6f}"
    )


def _profile_fingerprint() -> str:
    """Cheap fingerprint of the profile file - mtime + size, no read/parse.
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
    """Return the configured model, falling back to MODEL_FALLBACK.
    In cheap-llm mode uses LLM_CHEAP_MODEL to reduce cost when evaluating more jobs.
    """
    if _CHEAP_LLM_MODE:
        return LLM_CHEAP_MODEL
    return load_agent_settings().get("llm", {}).get("model", MODEL_FALLBACK)


_llm_model_logged = False


def _log_llm_model_once() -> str:
    """Print the active model to the terminal on first use. Returns the model string."""
    global _llm_model_logged
    model = _get_llm_model()
    if not _llm_model_logged:
        source = "cheap-llm override" if _CHEAP_LLM_MODE else "agent_settings.json"
        print(f"[LLM] Model: {model}  (source: {source})")
        _llm_model_logged = True
    return model


_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if _api_key else None
ALLOWED_LEARNING_CATEGORIES = frozenset(VALID_SIGNAL_CATEGORIES - {CATEGORY_HARD_BLOCKER_PATTERN})


def _load_managed_prompt_lines(path, filename: str) -> tuple[str, ...]:
    payload = _json_mod.loads(path.read_text(encoding="utf-8"))
    lines = payload.get("lines")
    if not isinstance(lines, list):
        raise ValueError(f"{filename} must contain a lines list")
    cleaned = tuple(str(line).strip() for line in lines if str(line).strip())
    if not cleaned:
        raise ValueError(f"{filename} must define at least one prompt line")
    return cleaned


def _load_hard_blocker_rules() -> frozenset[str]:
    payload = _json_mod.loads(_REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("rejection_rule_categories.json must contain an entries list")

    kinds: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        value = str(entry.get("value") or "").strip()
        if value:
            kinds.append(value)
    if not kinds:
        raise ValueError("rejection_rule_categories.json must define at least one enabled kind")
    return frozenset(kinds)


def _hard_blocker_rules() -> frozenset[str]:
    return _load_hard_blocker_rules()
FIT_REVIEW_DEFAULT_LINES = _load_managed_prompt_lines(_FIT_REVIEW_DEFAULTS_PATH, "llm_fit_review_defaults.json")
CAPABILITY_NAMING_DEFAULT_LINES = _load_managed_prompt_lines(_CAPABILITY_NAMING_DEFAULTS_PATH, "llm_capability_naming_defaults.json")


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    profile = load_profile()
    llm_profile_brief = str(profile.get("llm_profile_brief") or "").strip()
    star_evidence_text = str(profile.get("star_evidence_text") or "").strip()
    evidence_tiers = get_candidate_profile_tiers(profile)
    evidence_weights = get_candidate_profile_tier_weights(profile)
    capability_rules = profile.get(KEY_CAPABILITY_PROFILE_RULES, [])
    salary_preferences = profile.get("salary_preferences", {})
    match_preferences = profile.get("match_preferences", {}) if isinstance(profile.get("match_preferences", {}), dict) else {}

    parts = []
    if llm_profile_brief:
        parts.append(LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER)
        parts.append(llm_profile_brief[:2500])

    if isinstance(capability_rules, list) and capability_rules:
        parts.append(LLM_PROMPT_CAPABILITY_LEVELS_HEADER)
        for rule in capability_rules[:20]:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("name") or "").strip()
            level = str(rule.get("level") or "").strip()
            fit = str(rule.get("fit") or "").strip()
            raw_aliases = rule.get("aliases", [])
            aliases_list = raw_aliases if isinstance(raw_aliases, list) else []
            aliases = ", ".join(str(alias).strip() for alias in aliases_list[:8] if str(alias).strip())
            if name and level:
                label = f"- {name}: {level}"
                if fit:
                    label += f", {fit}"
                if aliases:
                    label += f" ({aliases})"
                parts.append(label)

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
        parts.append(LLM_PROMPT_MATCH_PREFERENCES_HEADER)
        parts.extend(f"- {line}" for line in preference_lines)

    # star_evidence_text intentionally excluded from fit-scoring prompt.
    # Field is preserved in profile.json for future application/CV generation.
    # See docs/ARCHITECTURE.md parked decisions.

    primary_evidence = str(evidence_tiers.get(KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()
    secondary_evidence = str(evidence_tiers.get(KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()
    background_evidence = str(evidence_tiers.get(KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()

    if primary_evidence:
        tier_key, tier_label, tier_weight, tier_limit = LLM_EVIDENCE_TIERS[0]
        parts.append(f"{tier_label} (strongest weight {evidence_weights.get(tier_key, tier_weight):.2f}):")
        parts.append(primary_evidence[:tier_limit])
    if secondary_evidence:
        tier_key, tier_label, tier_weight, tier_limit = LLM_EVIDENCE_TIERS[1]
        parts.append(f"{tier_label} (lower weight {evidence_weights.get(tier_key, tier_weight):.2f}):")
        parts.append(secondary_evidence[:tier_limit])
    if background_evidence:
        tier_key, tier_label, tier_weight, tier_limit = LLM_EVIDENCE_TIERS[2]
        parts.append(f"{tier_label} (weakest weight {evidence_weights.get(tier_key, tier_weight):.2f}):")
        parts.append(background_evidence[:tier_limit])

    return "\n".join(part for part in parts if part)


def build_fit_review_guidance(profile: dict[str, Any] | None = None) -> str:
    active_profile = profile if isinstance(profile, dict) else load_profile()
    parts = [LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER]
    parts.extend(f"- {line}" for line in FIT_REVIEW_DEFAULT_LINES)
    guidance = str(active_profile.get("llm_fit_review_guidance") or "").strip()
    if guidance:
        parts.append(LLM_PROMPT_USER_FIT_REVIEW_GUIDANCE_HEADER)
        parts.append(guidance[:1200])
    return "\n".join(parts)


def build_capability_naming_guidance(profile: dict[str, Any] | None = None) -> str:
    active_profile = profile if isinstance(profile, dict) else load_profile()
    parts = [
        LLM_PROMPT_CAPABILITY_NAMING_INTRO,
        "",
        LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER,
    ]
    parts.extend(f"- {line}" for line in CAPABILITY_NAMING_DEFAULT_LINES)
    guidance = str(active_profile.get("llm_capability_naming_guidance") or "").strip()
    if guidance:
        parts.extend(["", LLM_PROMPT_USER_CAPABILITY_NAMING_GUIDANCE_HEADER, guidance[:1200]])
    parts.extend(["", LLM_PROMPT_CLUSTERS_HEADER])
    return "\n".join(parts)

def build_system_prompt() -> str:
    profile = load_profile()
    parts = [
        LLM_PROMPT_SYSTEM_REVIEW_INTRO,
        build_fit_review_guidance(profile),
        build_profile_prompt_context(),
    ]
    parts.append(
        f"{LLM_PROMPT_REVIEW_OUTPUT_FORMAT} "
        f"DECISION must be {', '.join(sorted(LLM_ALLOWED_DECISIONS))}. "
        f"GRADE must be {', '.join(sorted(LLM_ALLOWED_GRADES))}. "
        f"{LLM_REVIEW_GRADE_GUIDANCE} "
        "Do not explain your answer."
    )
    return "\n".join(part for part in parts if part)


def build_llm_cache_key(job_description_text: str) -> str:
    desc_hash = hashlib.sha256(str(job_description_text or "").encode("utf-8", errors="ignore")).hexdigest()
    return f"{_profile_fingerprint()}:{desc_hash}"


def _require_fit_review(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        decision = str(value.get("decision") or "").strip().upper()
        grade = str(value.get("grade") or "").strip().upper()
        if not decision:
            raise ValueError("LLM fit review is missing decision")
        if not grade:
            raise ValueError("LLM fit review is missing grade")
        if decision not in LLM_ALLOWED_DECISIONS:
            raise ValueError(f"LLM fit review decision must be one of {sorted(LLM_ALLOWED_DECISIONS)}: {decision!r}")
        if grade not in LLM_ALLOWED_GRADES:
            raise ValueError(f"LLM fit review grade must be one of {sorted(LLM_ALLOWED_GRADES)}: {grade!r}")
        return {"decision": decision, "grade": grade}

    if isinstance(value, str):
        text = value.strip().upper()
        if "|" not in text:
            raise ValueError("LLM fit review must be DECISION|GRADE")
        decision, _, grade = text.partition("|")
        return _require_fit_review({"decision": decision, "grade": grade})

    raise ValueError(f"LLM fit review must be a dict or DECISION|GRADE string, got {type(value).__name__}")


def normalize_llm_review(value: Any) -> Dict[str, str]:
    return _require_fit_review(value)


def _clean_learning_candidate_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_llm_learning_candidates(value: Any, max_items: int = 6) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("learning_candidates") or value.get("candidates") or []
    if isinstance(value, str):
        try:
            value = _json_mod.loads(_strip_json_fence(value))
        except Exception:
            return []
    if not isinstance(value, list):
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        signal = _clean_learning_candidate_text(item.get(LEARNING_SIGNAL_KEY) or item.get("value") or item.get("name"))
        category = re.sub(r"[^a-z0-9_]+", "_", _clean_learning_candidate_text(item.get(LEARNING_SUGGESTED_CATEGORY_KEY))).strip("_").lower()
        if not signal or category not in ALLOWED_LEARNING_CATEGORIES:
            continue
        if any(char in signal for char in "\r\n") or re.search(r"[.!?]", signal):
            continue
        key = (signal.lower(), category)
        if key in seen:
            continue
        original_texts = []
        seen_texts: set[str] = set()
        raw_originals = item.get(LEARNING_ORIGINAL_TEXTS_KEY) or []
        if isinstance(raw_originals, str):
            raw_originals = [raw_originals]
        if not isinstance(raw_originals, list):
            raw_originals = []
        for text in [signal, *raw_originals]:
            cleaned = _clean_learning_candidate_text(text)
            lowered = cleaned.lower()
            if not cleaned or lowered in seen_texts:
                continue
            seen_texts.add(lowered)
            original_texts.append(cleaned)
        seen.add(key)
        candidates.append(
            {
                LEARNING_SIGNAL_KEY: signal,
                LEARNING_SUGGESTED_CATEGORY_KEY: category,
                LEARNING_ORIGINAL_TEXTS_KEY: original_texts or [signal],
            }
        )
        if len(candidates) >= max_items:
            break
    return candidates


def normalize_llm_review_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        has_explicit_fit_review = "fit_review" in value or "decision" in value or "grade" in value
        if has_explicit_fit_review:
            fit_review = value.get("fit_review")
            if fit_review is None:
                fit_review = {
                    "decision": value.get("decision"),
                    "grade": value.get("grade"),
                }
            return {
                "fit_review": _require_fit_review(fit_review),
                "learning_candidates": normalize_llm_learning_candidates(value.get("learning_candidates")),
            }

        if "learning_candidates" in value or value.get("learning_only"):
            return {
                "fit_review": None,
                "learning_candidates": normalize_llm_learning_candidates(value.get("learning_candidates")),
            }

        raise ValueError("LLM review payload is missing fit_review")

    if isinstance(value, str):
        text = value.strip()
        if "|" in text and not text.lstrip().startswith("{"):
            decision, _, grade = text.strip().upper().partition("|")
            return {
                "fit_review": _require_fit_review({"decision": decision, "grade": grade}),
                "learning_candidates": [],
            }
        try:
            parsed = _json_mod.loads(_strip_json_fence(text))
        except Exception:
            raise ValueError("LLM review payload must be JSON or DECISION|GRADE")
        return normalize_llm_review_payload(parsed)

    raise ValueError(f"LLM review payload must be a dict or string, got {type(value).__name__}")


def _strip_json_fence(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return raw


def normalize_rejection_blocker_suggestions(value: Any, max_items: int = 6) -> list[str]:
    if isinstance(value, str):
        try:
            value = _json_mod.loads(_strip_json_fence(value))
        except Exception:
            return []
    if isinstance(value, dict):
        value = value.get("blockers") or value.get("suggestions") or []
    if not isinstance(value, list):
        return []

    suggestions: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = re.sub(r"[^a-z_]+", "_", str(item.get("kind") or "").strip().lower()).strip("_")
        if kind not in _hard_blocker_rules():
            continue
        phrase = re.sub(r"\s+", " ", str(item.get("term") or "").strip().lower())
        if not phrase:
            continue
        if len(phrase) < 2 or len(phrase) > 80:
            continue
        if re.search(r"[\r\n.;!?]", phrase):
            continue
        if len(phrase.split()) > 6:
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        suggestions.append(phrase)
        if len(suggestions) >= max_items:
            break
    return suggestions


def llm_suggest_rejection_blockers(job_description_text: str, llm_client: Any = None) -> list[str]:
    active_client = llm_client or client
    description = str(job_description_text or "").strip()
    if active_client is None or not description:
        return []

    system_prompt = "\n".join(
        part for part in [
            "You suggest candidate-controlled blocker terms for a job-search assistant.",
            "The user will explicitly approve any suggestion before it is saved. Do not decide or save anything.",
            "Use the candidate profile context to avoid suggesting requirements already evidenced by the candidate.",
            "Suggest only concise blocker terms that appear to be hard requirements for this specific job and are not clearly evidenced by the candidate profile.",
            "Hard blockers can be from any field: credentials, clearances, licences, work authorization, language, location, regulated/domain experience, industry background, products, platforms, tools, or specialist experience.",
            "Do not suggest desirable, preferred, nice-to-have, generic duties, soft skills, broad transferable capabilities, sentence fragments, or broad work verbs.",
            "Classify each suggestion with one kind from: " + ", ".join(sorted(_hard_blocker_rules())) + ".",
            f"{LLM_PROMPT_JSON_ONLY}, in this exact shape: {{\"blockers\":[{{\"term\":\"term\",\"kind\":\"kind\"}}]}}. Return an empty array if unsure.",
            build_profile_prompt_context(),
        ]
        if part
    )

    try:
        model = _log_llm_model_once()
        resp = active_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + description[:5000]},
            ],
            max_output_tokens=LLM_MAX_TOKENS_REJECTION_SUGGESTIONS,
        )
        _log_llm_call(resp, "rejection_suggestions", model)
    except Exception as exc:
        print(f"[LLM][REJECTION_SUGGESTIONS][ERROR] {exc}")
        return []

    suggestions = normalize_rejection_blocker_suggestions(getattr(resp, "output_text", ""))
    raw_output = str(getattr(resp, "output_text", "") or "").strip()
    if raw_output:
        print(f"[LLM][REJECTION_SUGGESTIONS][RAW] {raw_output[:1200]}")
    print(f"[LLM][REJECTION_SUGGESTIONS][NORMALIZED] {suggestions}")
    if not suggestions and str(getattr(resp, "output_text", "") or "").strip():
        print(f"[LLM][REJECTION_SUGGESTIONS][UNEXPECTED] {str(resp.output_text).strip()}")
    return suggestions


def name_capability_clusters(clusters: list[dict[str, Any]], llm_client: Any = None) -> list[str]:
    """Use the LLM only to label pre-selected deterministic capability clusters."""
    active_client = llm_client or client
    if active_client is None or not clusters:
        return []

    payload: list[dict[str, Any]] = []
    for item in clusters:
        seed = str(item.get("name") or "").strip().lower()
        aliases = [
            str(alias).strip().lower()
            for alias in (item.get("aliases") or [])
            if str(alias).strip()
        ]
        if not seed:
            continue
        payload.append({
            "seed": seed,
            "aliases": aliases[:6],
        })
    if not payload:
        return []

    prompt = build_capability_naming_guidance()

    try:
        _model = _get_llm_model()
        resp = active_client.responses.create(
            model=_model,
            input=[{"role": "user", "content": prompt + _json_mod.dumps(payload, ensure_ascii=False)}],
            max_output_tokens=LLM_MAX_TOKENS_CV_EXTRACTION,
        )
        _log_llm_call(resp, "capability_naming", _model)
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        labels = _json_mod.loads(raw)
        if not isinstance(labels, list):
            return []
        return [str(label).strip().lower() for label in labels[: len(payload)]]
    except Exception:
        return []

def llm_should_consider(job_description_text: str) -> Dict[str, str]:
    return normalize_llm_review(llm_should_consider_with_learning(job_description_text).get("fit_review"))


def _build_learning_prompt(job_description_text: str, *, fit_review: bool) -> str:
    parts = [
        "You help decide whether a candidate should apply for a job and identify only pending learning signals.",
        LLM_PROMPT_JSON_ONLY,
        LLM_PROMPT_DO_NOT_SAVE,
        LLM_PROMPT_DO_NOT_INVENT,
        LLM_PROMPT_USE_VISIBLE_STRINGS,
        LLM_PROMPT_LEARNING_PENDING_ONLY,
    ]
    if fit_review:
        parts.extend([
            f"Return exactly this shape: {LLM_REVIEW_PROMPT_SHAPE}",
            LLM_PROMPT_USE_AT_MOST_SIX,
        ])
    else:
        parts.extend([
            f"Return exactly this shape: {LLM_LEARNING_ONLY_PROMPT_SHAPE}",
            LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
            LLM_PROMPT_USE_AT_MOST_FOUR,
        ])
    parts.append(build_profile_prompt_context())
    return "\n".join(part for part in parts if part)


def _request_learning_payload(job_description_text: str, *, fit_review: bool) -> dict[str, Any]:
    if client is None:
        raise RuntimeError("LLM review requested but OPENAI_API_KEY is missing")

    try:
        model = _log_llm_model_once() if fit_review else LLM_CHEAP_MODEL
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": _build_learning_prompt(job_description_text, fit_review=fit_review)},
                {"role": "user", "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + job_description_text},
            ],
            max_output_tokens=LLM_MAX_TOKENS_FIT_DECISION if fit_review else LLM_MAX_TOKENS_CV_EXTRACTION,
        )
        _log_llm_call(resp, "job_review_with_learning" if fit_review else "job_learning_candidates", model)
    except Exception as exc:
        raise RuntimeError(f"LLM review request failed: {exc}") from exc

    payload = normalize_llm_review_payload(resp.output_text)
    if fit_review:
        if payload.get("fit_review") is None:
            raise ValueError("LLM fit review payload is missing fit_review")
    return payload


def llm_should_consider_with_learning(job_description_text: str) -> dict[str, Any]:
    return _request_learning_payload(job_description_text, fit_review=True)


def llm_should_consider_learning_candidates(job_description_text: str) -> list[dict[str, Any]]:
    return normalize_llm_review_payload(_request_learning_payload(job_description_text, fit_review=False)).get("learning_candidates", [])


def get_cost_summary() -> dict[str, Any]:
    """Read llm_costs.jsonl and return totals by purpose - useful for debugging."""
    totals: dict[str, dict[str, Any]] = {}
    try:
        with open(_LLM_COSTS_PATH, encoding="utf-8") as fh:
            for line in fh:
                entry = _json_mod.loads(line)
                p = entry.get("purpose", "unknown")
                if p not in totals:
                    totals[p] = {"calls": 0, "tok_in": 0, "tok_out": 0, "cost_usd": 0.0}
                totals[p]["calls"]    += 1
                totals[p]["tok_in"]   += entry.get("tok_in", 0)
                totals[p]["tok_out"]  += entry.get("tok_out", 0)
                totals[p]["cost_usd"] += entry.get("cost_usd", 0.0)
    except FileNotFoundError:
        pass
    grand = sum(v["cost_usd"] for v in totals.values())
    return {"by_purpose": totals, "grand_total_usd": round(grand, 6)}
