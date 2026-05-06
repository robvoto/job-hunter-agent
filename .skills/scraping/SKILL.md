# Skill: Scraping

Use before editing SEEK/LinkedIn scrapers or scraped job data shape.

## Rules
- SEEK uses direct job pages only; do not restore pane scraping.
- Scrapers collect evidence; they do not decide fit.
- Preserve raw/important job signals where possible.
- Do not add filtering, scoring, or rejection judgement inside scraper code.
- Normalise job identity consistently for dedup/history.
- Surface partial or low-confidence descriptions; do not hide them.

## Owners
- `scrapers/seek.py`: SEEK scraping.
- `scrapers/linkedin.py`: LinkedIn via python-jobspy.
- `source_connector.py`: orchestration.
- `job_identity.py`: cross-source identity/dedup.
- `description_trust.py`: full-description confidence.

## Checklist
- Is this collection logic, not judgement?
- Is full-description confidence preserved?
- Are missing/partial descriptions surfaced, not hidden?
- Is job identity stable across sources?
- Did you run the smallest relevant scraper/data-shape check?
