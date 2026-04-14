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
from typing import Any, Dict

from openai import OpenAI

from profile_store import get_evidence_tiers, get_evidence_tier_weights, load_profile


_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if _api_key else None
ALLOWED_DECISIONS = {"KEEP", "REJECT", "MAYBE"}
ALLOWED_GRADES = {"EXCELLENT", "STRONG", "SOLID", "WEAK", "POOR", "MISMATCH"}
DEFAULT_LLM_REVIEW = {"decision": "MAYBE", "grade": "SOLID"}


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    profile = load_profile()
    summary = str(profile.get("candidate_summary") or "").strip()
    strengths = [str(item).strip() for item in profile.get("strengths", []) if str(item).strip()]
    llm_profile_brief = str(profile.get("llm_profile_brief") or "").strip()
    star_evidence_text = str(profile.get("star_evidence_text") or "").strip()
    evidence_tiers = get_evidence_tiers(profile)
    evidence_weights = get_evidence_tier_weights(profile)
    capability_rules = profile.get("capability_profile_rules", [])
    notes = [str(item).strip() for item in profile.get("llm_prompt_notes", []) if str(item).strip()]
    salary_preferences = profile.get("salary_preferences", {})
    match_preferences = profile.get("match_preferences", {}) if isinstance(profile.get("match_preferences", {}), dict) else {}

    parts = []
    if llm_profile_brief:
        parts.append("Candidate fit brief:")
        parts.append(llm_profile_brief[:2500])
    else:
        if summary:
            parts.append("Candidate summary:")
            parts.append(summary)
        if strengths:
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

    if notes:
        parts.append("Important fit notes:")
        parts.extend(f"- {note}" for note in notes[:12])

    preference_lines = []
    minimum_salary_yearly = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    minimum_daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    if minimum_salary_yearly > 0 or minimum_daily_rate > 0:
        preference_lines.append(
            f"Compensation target: permanent roles around {minimum_salary_yearly or 'not set'} yearly, contract roles around {minimum_daily_rate or 'not set'} per day."
        )
    if match_preferences.get("home_location"):
        preference_lines.append(f"Home base: {match_preferences.get('home_location')}.")
    if match_preferences.get("prefer_government"):
        preference_lines.append("Government and regulated-environment roles are a positive signal.")
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
    payload = build_system_prompt() + "\n\nJob description:\n" + str(job_description_text or "")
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


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


def llm_should_consider(job_description_text: str) -> Dict[str, str]:
    if client is None:
        return dict(DEFAULT_LLM_REVIEW)

    try:
        resp = client.responses.create(
            model="gpt-5.2",
            input=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": "Job description:\n" + job_description_text},
            ],
        )
    except Exception as exc:
        print(f"[LLM][ERROR] {exc}")
        return dict(DEFAULT_LLM_REVIEW)

    normalized = normalize_llm_review((resp.output_text or "").strip().upper())
    if normalized == DEFAULT_LLM_REVIEW and (resp.output_text or "").strip():
        print(f"[LLM][UNEXPECTED] {(resp.output_text or '').strip()}")
    return normalized
