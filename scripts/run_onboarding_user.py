"""Run onboarding for thewriter30@gmail.com and report target_occupation_queries."""
import os
from pathlib import Path
import logging

# Load .env manually so OPENAI_API_KEY and JOB_HUNTER_DB_PATH are available
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

from job_hunter_agent.user_context import set_user_id
from job_hunter_agent.auth import user_id_from_email
from job_hunter_agent.source_documents import run_onboarding, load_source_materials

uid = user_id_from_email("thewriter30@gmail.com")
set_user_id(uid)

print(f"\n=== Running onboarding for {uid} ===\n")
sm = load_source_materials(create_if_missing=False)
result = run_onboarding(sm)

print(f"\n=== Onboarding result: ok={result['ok']} ===")
from job_hunter_agent.profile_store import load_profile
profile = result.get("profile") or load_profile()
queries = profile.get("target_occupation_queries") or []
print(f"\ntarget_occupation_queries ({len(queries)} items):")
for q in queries:
    print(f"  - {q}")
print(f"\ntarget_roles:        {profile.get('target_roles')}")
print(f"also_consider_roles: {profile.get('also_consider_roles')}")
