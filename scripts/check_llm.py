"""Check if LLM client is available."""
import os
os.environ.setdefault("JOB_HUNTER_DB_PATH", r"E:\Programming\job-hunter-agent\data\app.db")

from job_hunter_agent.llm_gate import client, get_llm_model
print(f"LLM client: {client}")
print(f"LLM model: {get_llm_model()}")
print(f"OPENAI_API_KEY set: {bool(os.environ.get('OPENAI_API_KEY'))}")
print(f"ANTHROPIC_API_KEY set: {bool(os.environ.get('ANTHROPIC_API_KEY'))}")
