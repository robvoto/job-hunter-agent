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
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI

from job_hunter_agent.agent_settings import load_agent_settings
from job_hunter_agent.profile_store import DATA_DIR, get_evidence_tiers, get_evidence_tier_weights, load_profile

load_dotenv()

# Token budgets â€” keep fit decisions tight; extraction can be generous
MAX_TOKENS_FIT_DECISION = 50
MAX_TOKENS_CV_EXTRACTION = 500

# Test-mode flag: mirrors the same argv check in source_connector
_TEST_SCRAPE_MODE = "--test-scrape-mode" in sys.argv

_PROFILE_PATH = DATA_DIR / "profile.json"
_profile_fingerprint_cache: str | None = None

# â”€â”€ Cost logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” €â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— â”— ⏩
_LLM_COSTS_PATH = DATA_DIR / "llm_costs.jsonl"
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
    """Cheap fingerprint of the profile file â€” mtime + size, no read/parse.
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


def build_system_prompt() -> str:
    parts = [
        "You are helping decide whether a candidate should apply for a job.",
        "Judge fit primarily from the job description and the candidate profile evidence below, not from title alone.",
        "Be honest about gaps. Adjacent titles can still fit when responsibilities match the candidate background.",
        "Recent directly relevant experience matters more than older exposure from many years ago.",
        "Treat primary current evidence as strongest proof. Treat older evidence as weaker, and background-only context such as certifications, broad industry mentions, or optional supporting history as weakest.",
        "Use capability levels and aliases from the candidate profile context as supporting evidence when responsibilities align.",
        "Treat desirable or nice-to-have gaps as softer concerns than essential or mandatory gaps.",
        "Grade the full description fit, not just keyword overlap.",
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

    prompt = (
        "You are renaming already-detected professional capability clusters.\n\n"
        "Important rules:\n"
        "- The clusters already exist. Do not decide whether they are valid.\n"
        "- Your job is only to produce a cleaner 1-4 word lowercase capability label for each cluster.\n"
        "- Prefer broad transferable capability names over raw task fragments.\n"
        "- Do not invent new evidence.\n"
        "- Do not output tools unless the cluster is clearly about that tool.\n"
        "- Keep the same order as input.\n"
        "- Return a JSON array of strings only, one label per input cluster.\n\n"
        "Clusters:\n"
    )
    import json as _json

    try:
        _model = _get_llm_model()
        resp = active_client.responses.create(
            model=_model,
            input=[{"role": "user", "content": prompt + _json.dumps(payload, ensure_ascii=False)}],
            max_output_tokens=MAX_TOKENS_CV_EXTRACTION,
        )
        _log_llm_call(resp, "capability_naming", _model)
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        labels = _json.loads(raw)
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
    """Read llm_costs.jsonl and return totals by purpose — useful for debugging."""
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
