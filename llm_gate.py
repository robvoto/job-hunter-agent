# llm_gate.py
import os

from openai import OpenAI

from profile_store import load_profile


_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if _api_key else None


def llm_is_enabled() -> bool:
    return client is not None


def build_system_prompt() -> str:
    profile = load_profile()
    summary = profile.get("candidate_summary", "")
    strengths = profile.get("strengths", [])
    notes = profile.get("llm_prompt_notes", [])

    parts = [
        "You are helping me decide whether to apply for jobs.",
        summary,
    ]
    if strengths:
        parts.append("Strong fit areas: " + ", ".join(strengths) + ".")
    if notes:
        parts.append("Important preferences:")
        parts.extend(f"- {note}" for note in notes)
    parts.append(
        "Answer with exactly ONE word, in uppercase: KEEP, REJECT, or MAYBE. "
        "Do not explain your answer."
    )
    return "\n".join(part for part in parts if part)


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
