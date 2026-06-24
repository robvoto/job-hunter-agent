#!/usr/bin/env bash
# Manual AWS smoke test for SEEK in the headed browser session.
# Run this on the EC2 host when you want to verify that SEEK cards appear
# after completing human verification in the headed AWS browser session.
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
SMOKE_URL="${JOB_HUNTER_SMOKE_SEEK_URL:-}"
SMOKE_TIMEOUT_MS="${JOB_HUNTER_SMOKE_TIMEOUT_MS:-60000}"

if [[ -z "$SMOKE_URL" ]]; then
  echo "ERROR: JOB_HUNTER_SMOKE_SEEK_URL must be set to a SEEK search URL." >&2
  exit 1
fi

exec "$APP_DIR/scripts/ec2/start-aws-browser-session.sh" python - "$SMOKE_URL" "$SMOKE_TIMEOUT_MS" <<'PY'
import sys

from playwright.sync_api import sync_playwright

from job_hunter_agent.paths import PLAYWRIGHT_USER_DATA_DIR
from job_hunter_agent.scrapers.seek import SELECTOR_CARDS

url = sys.argv[1]
timeout_ms = int(sys.argv[2])

PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
        headless=False,
        viewport={"width": 1400, "height": 900},
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(SELECTOR_CARDS, timeout=timeout_ms)
        cards = page.query_selector_all(SELECTOR_CARDS)
        print(f"cards={len(cards)}")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        body = page.text_content("body") or ""
        print(f"body_snippet={body[:500]}")
        raise
    finally:
        context.close()
PY
