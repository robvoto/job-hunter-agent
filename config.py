# config.py

SEEK_URL = "https://www.seek.com.au/business-analyst-jobs/in-All-Sydney-NSW?classification=6076%2C1209%2C6123%2C6281%2C1223&daterange=3"

OUTPUT_HTML = "output/seek_results.html"

# Scrape tuning
MAX_PAGES_CAP = 10
DETAILS_MIN_LEN = 200

# Fast waits (keep small; we don't want 10-20s per card)
PANE_UPDATE_TIMEOUT_MS = 2500     # confirm pane updated for clicked job
PANE_TEXT_TIMEOUT_SECONDS = 2.5   # fallback wait for details text change
