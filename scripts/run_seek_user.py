"""Run SEEK pipeline for thewriter30@gmail.com, logging to a file."""
import os
import sys
import logging
from pathlib import Path

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

log_path = Path(__file__).parent.parent / "output" / "seek_run.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ],
)

from job_hunter_agent.user_context import set_user_id
from job_hunter_agent.auth import user_id_from_email

uid = user_id_from_email("thewriter30@gmail.com")
set_user_id(uid)

print(f"\n=== Running SEEK for {uid} — log: {log_path} ===\n")

from job_hunter_agent.source_connector import scrape_jobs_direct
scrape_jobs_direct(headless=True)

print(f"\n=== SEEK run complete. Check {log_path} for ONET logs ===")
