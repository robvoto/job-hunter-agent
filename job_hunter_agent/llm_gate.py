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
from job_hunter_agent.profile_store import (
    DATA_DIR,
    FIT_REVIEW_DEFAULTS_PATH as _FIT_REVIEW_DEFAULTS_PATH,
    HARD_BLOCKER_KINDS_PATH as _HARD_BLOCKER_KINDS_PATH,
    LLM_CAPABILITY_NAMING_DEFAULTS_PATH as _CAPABILITY_NAMING_DEFAULTS_PATH,
    LLM_COSTS_PATH as _LLM_COSTS_PATH,
    PROFILE_PATH as _PROFILE_PATH,
    get_evidence_tiers,
    get_evidence_tier_weights,
    load_profile,
)

load_dotenv()

# Token budgets - keep fit decisions tight; extraction can be generous
MAX_TOKENS_FIT_DECISION = 50
MAX_TOKENS_CV_EXTRACTION = 500
MAX_TOKENS_REJECTION_SUGGESTIONS = 300

# Cheap-llm flag: mirrors the same argv check in source_connector
_CHEAP_LLM_MODE = "--cheap-llm" in sys.argv

# Model configuration
MODEL_CHEAP = "gpt-4o-mini"
MODEL_FALLBACK = DEFAULT_AGENT_SETTINGS["llm"]["model"]


_profile_fingerprint_cache: str | None = None

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
    In cheap-llm mode uses MODEL_CHEAP to reduce cost when evaluating more jobs.
    """
    if _CHEAP_LLM_MODE:
        return MODEL_CHEAP
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
ALLOWED_DECISIONS = {"KEEP", "REJECT", "MAYBE"}
ALLOWED_GRADES = {"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"}
DEFAULT_LLM_REVIEW = {"decision": "MAYBE", "grade": "SOLID"}


def _load_managed_prompt_lines(path, filename: str) -> tuple[str, ...]:
    payload = _json_mod.loads(path.read_text(encoding="utf-8"))
    lines = payload.get("lines")
    if not isinstance(lines, list):
        raise ValueError(f"{filename} must contain a lines list")
    cleaned = tuple(str(line).strip() for line in lines if str(line).strip())
    if not cleaned:
        raise ValueError(f"{filename} must define at least one prompt line")
    return cleaned


def _load_hard_blocker_kinds() -> frozenset[str]:
    payload = _json_mod.loads(_HARD_BLOCKER_KINDS_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("hard_blocker_kinds.json must contain an entries list")

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
        raise ValueError("hard_blocker_kinds.json must define at least one enabled kind")
    return frozenset(kinds)


HARD_BLOCKER_KINDS = _load_hard_blocker_kinds()
FIT_REVIEW_DEFAULT_LINES = _load_managed_prompt_lines(_FIT_REVIEW_DEFAULTS_PATH, "llm_fit_review_defaults.json")
CAPABILITY_NAMING_DEFAULT_LINES = _load_managed_prompt_lines(_CAPABILITY_NAMING_DEFAULTS_PATH, "llm_capability_naming_defaults.json")


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    profile = load_profile()
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

    if isinstance(capability_rules, list) and capability_rules:
        parts.append("Capability levels:")
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
        parts.append("Match preferences:")
        parts.extend(f"- {line}" for line in preference_lines)

    # star_evidence_text intentionally excluded from fit-scoring prompt.
    # Field is preserved in profile.json for future application/CV generation.
    # See SOUL.md parked decisions.

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


def build_fit_review_guidance(profile: dict[str, Any] | None = None) -> str:
    active_profile = profile if isinstance(profile, dict) else load_profile()
    parts = ["Default fit review guidance:"]
    parts.extend(f"- {line}" for line in FIT_REVIEW_DEFAULT_LINES)
    guidance = str(active_profile.get("llm_fit_review_guidance") or "").strip()
    if guidance:
        parts.append("User fit review guidance:")
        parts.append(guidance[:1200])
    return "\n".join(parts)


def build_capability_naming_guidance(profile: dict[str, Any] | None = None) -> str:
    active_profile = profile if isinstance(profile, dict) else load_profile()
    parts = [
        "You are reviewing and labelling candidate professional capability clusters extracted from a CV.",
        "",
        "Default capability naming guidance:",
    ]
    parts.extend(f"- {line}" for line in CAPABILITY_NAMING_DEFAULT_LINES)
    guidance = str(active_profile.get("llm_capability_naming_guidance") or "").strip()
    if guidance:
        parts.extend(["", "User capability naming guidance:", guidance[:1200]])
    parts.extend(["", "Clusters:"])
    return "\n".join(parts)


def build_system_prompt() -> str:
    profile = load_profile()
    parts = [
        "You are helping decide whether a candidate should apply for a job.",
        build_fit_review_guidance(profile),
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

    return dict(DEFAULT_LLM_REVIEW)


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
        if kind not in HARD_BLOCKER_KINDS:
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
            "Classify each suggestion with one kind from: " + ", ".join(sorted(HARD_BLOCKER_KINDS)) + ".",
            "Return JSON only, in this exact shape: {\"blockers\":[{\"term\":\"term\",\"kind\":\"kind\"}]}. Return an empty array if unsure.",
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
                {"role": "user", "content": "Job description:\n" + description[:5000]},
            ],
            max_output_tokens=MAX_TOKENS_REJECTION_SUGGESTIONS,
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
            max_output_tokens=MAX_TOKENS_CV_EXTRACTION,
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
    if client is None:
        return dict(DEFAULT_LLM_REVIEW)

    try:
        _model = _log_llm_model_once()
        resp = client.responses.create(
            model=_model,
            input=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": "Job description:\n" + job_description_text},
            ],
            max_output_tokens=MAX_TOKENS_FIT_DECISION,
        )
        _log_llm_call(resp, "job_review", _model)
    except Exception as exc:
        print(f"[LLM][ERROR] {exc}")
        return dict(DEFAULT_LLM_REVIEW)

    normalized = normalize_llm_review((resp.output_text or "").strip().upper())
    if normalized == DEFAULT_LLM_REVIEW and (resp.output_text or "").strip():
        print(f"[LLM][UNEXPECTED] {(resp.output_text or '').strip()}")
    return normalized


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
