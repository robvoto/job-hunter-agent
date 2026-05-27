"""Check source materials and run onboarding for a given user."""
import sys
import os

os.environ.setdefault("JOB_HUNTER_DB_PATH", r"E:\Programming\job-hunter-agent\data\app.db")

from job_hunter_agent.user_context import set_user_id
from job_hunter_agent.auth import user_id_from_email
from job_hunter_agent.profile_store import load_profile
from job_hunter_agent.source_documents import load_source_materials, normalize_source_materials, _collect_import_sources

uid = user_id_from_email("thewriter30@gmail.com")
set_user_id(uid)
profile = load_profile()

sm = load_source_materials(create_if_missing=False)
resolved = normalize_source_materials(sm)
sources = _collect_import_sources(resolved)
print(f"import_sources found: {len(sources)}")
for s in sources:
    label = s.get("label", "")
    content = s.get("content", "")
    print(f"  {label!r}: {len(content)} chars")
