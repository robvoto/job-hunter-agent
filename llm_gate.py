# llm_gate.py
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SYSTEM_PROMPT = (
    "You are helping me decide whether to apply for jobs.\n"
    "I’m a Senior Business Analyst focused on digital delivery, discovery, and process, "
    "not hands-on implementation of specialist platforms.\n"
    "Answer with exactly ONE word, in uppercase: KEEP, REJECT, or MAYBE. "
    "Do not explain your answer."
)

def llm_should_consider(job_description_text: str) -> str:
    resp = client.responses.create(
        model="gpt-5.2",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Job description:\n" + job_description_text},
        ],
    )

    # pull the text output and normalize
    text = (resp.output_text or "").strip().upper()

    # hard guardrail in case the model misbehaves
    if text not in {"KEEP", "REJECT", "MAYBE"}:
        print(f"{text}")
        return "MAYBE"
    return text
