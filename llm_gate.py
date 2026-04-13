"""LLM fit-decision gateway.

Main goals:
- build the compact candidate context sent to the LLM
- request a simple KEEP / REJECT / MAYBE decision for a job description
- keep prompt structure and cache keys aligned with the current profile state

Notes:
- deterministic filters run before this in the main source connector flow
- the AI fit brief is preferred over raw background text to reduce noise and cost
"""

import os
import hashlib

from openai import OpenAI

from profile_store import load_profile


_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if _api_key else None


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    profile = load_profile()
    summary = str(profile.get("candidate_summary") or "").strip()
    strengths = [str(item).strip() for item in profile.get("strengths", []) if str(item).strip()]
    llm_profile_brief = str(profile.get("llm_profile_brief") or "").strip()
    star_evidence_text = str(profile.get("star_evidence_text") or "").strip()
    cv_text = str(profile.get("cv_text") or "").strip()
    capability_rules = profile.get("capability_profile_rules", [])
    notes = [str(item).strip() for item in profile.get("llm_prompt_notes", []) if str(item).strip()]

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

    if star_evidence_text:
        parts.append("STAR / evidence examples:")
        parts.append(star_evidence_text[:1500])

    if cv_text:
        fallback_limit = 1200 if llm_profile_brief else 2500
        parts.append("Background fallback:")
        parts.append(cv_text[:fallback_limit])

    return "\n".join(part for part in parts if part)


def build_system_prompt() -> str:
    parts = [
        "You are helping decide whether a candidate should apply for a job.",
        "Judge fit primarily from the job description and the candidate profile evidence below, not from title alone.",
        "Be honest about gaps. Adjacent titles can still fit when responsibilities match the candidate background.",
        build_profile_prompt_context(),
    ]
    parts.append(
        "Answer with exactly ONE word, in uppercase: KEEP, REJECT, or MAYBE. "
        "Do not explain your answer."
    )
    return "\n".join(part for part in parts if part)


def build_llm_cache_key(job_description_text: str) -> str:
    payload = build_system_prompt() + "\n\nJob description:\n" + str(job_description_text or "")
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def llm_should_consider(job_description_text: str) -> str:
    if client is None:
        return "MAYBE"

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
        return "MAYBE"

    text = (resp.output_text or "").strip().upper()
    if text not in {"KEEP", "REJECT", "MAYBE"}:
        print(f"[LLM][UNEXPECTED] {text}")
        return "MAYBE"
    return text
