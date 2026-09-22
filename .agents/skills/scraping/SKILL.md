---
name: scraping
description: Use ONLY for SEEK, LinkedIn, and APSJobs discovery/scraping, source connector behaviour, discovery caching/health, scraped job data shape, source diagnostics, work-mode provenance, and raw evidence capture. Do NOT use for scoring or candidate preference decisions.
---

# Skill: Scraping

Use before editing SEEK, LinkedIn, or APSJobs discovery/scrapers, source health/cache behaviour, or scraped job data shape.

See `.agents/skills/scraping/DETAILS.md` for detailed work-mode extraction, source-specific rules, debug logging, and scraper run diagnosis.

## Load order
1. Read `AGENTS.md`.
2. Read this skill.
3. Read `.agents/skills/scraping/DETAILS.md` only for detailed work-mode extraction, source-specific rules, debug logging, or scraper run diagnosis.

## Non-negotiable rules
- Scrapers collect evidence; they do not decide fit, score, rank, or reject beyond source/search validity guards.
- SEEK uses direct job pages only; do not restore pane scraping.
- Preserve raw/important job signals where possible.
- Keep source metadata separate from classification: apply URL/domain, company links, poster identity, ATS hints, work-mode provenance, and description confidence.
- Prefer board-declared/structured metadata over text inference.
- Do not infer salary or pay period from free-text ad prose with deterministic heuristics. Compensation must come from structured source fields or another explicitly approved owner.
- Use fallback text heuristics only when trusted metadata is unavailable, and preserve provenance/review flags.
- Keep fallback heuristics data-driven in managed knowledge/config, not hardcoded in scraper code.
- Normalise job identity consistently for dedup/history.
- Surface partial or low-confidence descriptions; do not hide them.
- Source worker completion is not the same as source health: a source may complete as `healthy`, `partial_failure`, `full_failure`, or `stopped`. Never report a fully failed source as successful merely because its worker returned.
- A healthy source that returns zero jobs is still a valid success; distinguish zero results from transport/provider failure.
- Partial, stopped, timed-out, or failed source collections must never replace a known-good source-discovery snapshot. Only a complete successful collection may write a success snapshot.
- LinkedIn uses cheap JobSpy card discovery first (`linkedin_fetch_description=False`), then source-native dedup and one bounded canonical-vacancy detail fetch; the vacancy header is checked before the shared pre-detail gate so explicit closure cannot reach LLM review, and the same page evidence is reused rather than re-fetched.
- LinkedIn uses a bounded, configurable consecutive-target-failure circuit breaker. Do not increase concurrency or simply raise the target timeout to mask blocking/timeouts; when the breaker trips, preserve truthful source health and use the bounded failure-backoff/stale-fallback contracts.
- `STALE_FALLBACK` is older known-good source evidence, not a successful live run or normal cache `HIT`. Failure/partial/fallback data must never overwrite the last complete successful discovery snapshot.
- SEEK remembered search-plan pruning may be used only after the currently selected terms are genuinely corroborated by their persisted per-term selection counts. Bootstrap/incomplete/stopped evidence must remain conservative and must not teach a trusted plan.
- APSJobs uses direct filtered search URLs where supported, source-native APS IDs for early deduplication, and treats a legitimate zero-result query as healthy success rather than source failure.
- `SOURCE_COMPLETE` means the source worker finished. Use explicit health markers such as `SOURCE_FAILED` / `SOURCE_PARTIAL` and the structured source status to describe whether collection actually succeeded.
- Do not treat search keywords as job-level work-mode proof.
- **Search-semantics boundary:** user-facing role/preference labels, canonical occupation/taxonomy identity, machine-facing source queries, seniority or other ranking/eligibility preferences, and source-cache signatures are separate contracts. Do not make one automatically own or overwrite another merely to simplify search planning.
- Any change to how profile/user values become SEEK, LinkedIn, or APSJobs query terms is a business-semantics change. Before implementation, follow `.agents/skills/code-change/SKILL.md`'s approval gate and show the exact before/after query set for representative current values, including whether the number of source targets increases or decreases and whether discovery becomes broader or narrower.
- Search-term derivation must not be implemented as hardcoded role lists or one-off title exceptions. If the desired mapping between a user role and a machine query is not already an approved product contract, stop and ask rather than inventing it.
- Changing search-term inputs or cache/signature composition must include an explicit cache-impact statement: which discovery snapshots/search plans/reviews become invalid, which remain reusable, and why. A cache-version bump must not invalidate a more expensive independent cache unless that cache's own behavioural contract actually changed.

## Ownership
- `scrapers/seek_runner.py`: SEEK scrape loop, card review dispatch, parallel detail fetch, result collection.
- `scrapers/seek.py`: SEEK low-level page helpers, selectors, URL building, detail payload fetch.
- `scrapers/linkedin.py`: LinkedIn JobSpy card discovery plus canonical-vacancy header preflight and single-detail-fetch evidence reuse.
- `scrapers/apsjobs.py`: APSJobs direct filtered search, native-ID discovery/dedup, and source parsing.
- `source_runner.py`: routes enabled SEEK, LinkedIn, and APSJobs sources and owns discovery cache/backoff/fallback orchestration.
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
