---
name: scraping
description: Use ONLY for SEEK/LinkedIn scraping, source connector behaviour, scraped job data shape, source diagnostics, work-mode provenance, and raw evidence capture. Do NOT use for scoring or candidate preference decisions.
---

# Skill: Scraping

Use before editing SEEK/LinkedIn scrapers or scraped job data shape.

See `.skills/scraping/DETAILS.md` for detailed work-mode extraction, source-specific rules, debug logging, and scraper run diagnosis.

## Load order
1. Read `AGENTS.md`.
2. Read this skill.
3. Read `.skills/scraping/DETAILS.md` only for detailed work-mode extraction, source-specific rules, debug logging, or scraper run diagnosis.

## Non-negotiable rules
- Scrapers collect evidence; they do not decide fit, score, rank, or reject beyond source/search validity guards.
- SEEK uses direct job pages only; do not restore pane scraping.
- Preserve raw/important job signals where possible.
- Keep source metadata separate from classification: apply URL/domain, company links, poster identity, ATS hints, work-mode provenance, and description confidence.
- Prefer board-declared/structured metadata over text inference.
- Do not infer salary or pay period from free-text ad prose with deterministic heuristics. Compensation must come from structured source fields or another explicitly approved owner.
- Any new heuristic or hardcoded parsing/classification rule is a red flag and requires explicit human approval before implementation.
- Use fallback text heuristics only when trusted metadata is unavailable, and preserve provenance/review flags.
- Keep fallback heuristics data-driven in managed knowledge/config, not hardcoded in scraper code.
- Normalise job identity consistently for dedup/history.
- Surface partial or low-confidence descriptions; do not hide them.
- Source worker completion is not the same as source health: a source may complete as `healthy`, `partial_failure`, `full_failure`, or `stopped`. Never report a fully failed source as successful merely because its worker returned.
- A healthy source that returns zero jobs is still a valid success; distinguish zero results from transport/provider failure.
- Partial, stopped, timed-out, or failed source collections must never replace a known-good source-discovery snapshot. Only a complete successful collection may write a success snapshot.
- LinkedIn uses a bounded, configurable consecutive-target-failure circuit breaker. Do not increase concurrency to mask blocking/timeouts; when the breaker trips, preserve any successful partial results, mark the collection incomplete, and use the bounded failure-backoff path for full failure.
- `SOURCE_COMPLETE` means the source worker finished. Use explicit health markers such as `SOURCE_FAILED` / `SOURCE_PARTIAL` and the structured source status to describe whether collection actually succeeded.
- Do not treat search keywords as job-level work-mode proof.

## Ownership
- `scrapers/seek_runner.py`: SEEK scrape loop, card review dispatch, parallel detail fetch, result collection.
- `scrapers/seek.py`: SEEK low-level page helpers, selectors, URL building, detail payload fetch.
- `scrapers/linkedin.py`: LinkedIn via python-jobspy.
- `source_runner.py`: routes enabled sources (SEEK/LinkedIn) in a single run.
- `source_connector.py`: source orchestration entry point.
- `job_identity.py`: cross-source identity/dedup.
- `description_trust.py`: full-description confidence.
- `job_types.py`: work type normalization mapping and filter group definitions.

## Search guards
- Reject ads whose `posted_age_days` exceeds `date_range_days` before scoring.
- Never send blank keyword searches to SEEK.
- `/api/run` requires onboarding completion before starting a scrape.
- Debug zero results by checking both `search_settings.keywords` and role/title patterns.

## Current run logs
Use `output/server.log` for the scrape summary. `./run` writes curated INFO-level lines; `./run --debug` raises the same file to DEBUG, adding interleaved worker activity, LLM calls, HTTP lines, and detailed pipeline trace.
Do not rely on stale `output/console.log`.

## Validation
- Run the smallest relevant scraper/data-shape test first.
- Add adjacent validation if source orchestration, identity, work-mode provenance, or filtering boundaries are affected.
- Record the exact validation command before marking work done.
