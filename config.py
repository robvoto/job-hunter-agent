# config.py

OUTPUT_HTML = "output/dashboard.html"

# Scrape tuning
MAX_PAGES_CAP = 10
DETAILS_MIN_LEN = 200

# Fast waits (keep small; we don't want 10-20s per card)
PANE_UPDATE_TIMEOUT_MS = 2500     # confirm pane updated for clicked job
PANE_TEXT_TIMEOUT_SECONDS = 2.5   # fallback wait for details text change
