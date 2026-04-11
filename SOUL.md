# SOUL.md - Job Hunter Agent

> This file is the project source of truth for AI assistants working in this repo.
> Keep it updated as the project evolves. Last updated: April 2026.
> Repo target name: `job-hunter-agent`
> Repo URL: https://github.com/robvoto/job-hunter-agent

---

## What this project is

A local-first job-hunting system focused on finding strong-fit Business Analyst roles with as little noise as possible.

Near-term goal:
- reliably scrape and filter BA roles
- learn the candidate profile over time
- produce a clean shortlist with clear reject reasons

Long-term goal:
- become a true autonomous job agent that runs daily and sends only meaningful matches

This project exists to solve a real job-search problem while also becoming a practical agent/automation learning project.

---

## Current stage

### Stage 2 underway

The project is past the initial prototype stage.

### What works now

- SEEK scraping uses the direct-page approach in `scraper_direct.py`
- deterministic filtering happens before any LLM call
- LLM fallback is constrained to `KEEP`, `REJECT`, or `MAYBE`
- search settings are configurable from the local admin UI
- search supports date window, sort by newest, locations, and classification filters
- runtime profile is persisted in `data/profile.json`
- human-editable capability note is stored in `data/rob_capability_profile.txt`
- unknown-skill review exists in admin so the system can learn from repeated concepts in job descriptions
- applied and hidden jobs can be recorded from the review workflow
- outputs are written to `output/` as HTML, JSON, run stats, and review data
- history and cache are persisted locally

### What is still incomplete

- this is not yet a true agent
- no scheduler yet
- no WhatsApp or Telegram delivery yet
- no LinkedIn scraper yet
- no authenticated SEEK session reuse yet
- no durable cloud persistence yet
- filtering still needs ongoing tuning to reduce false positives and false rejects

---

## Current architecture decision

### Preferred scraper path

Use direct job pages, not SEEK's right-hand details pane.

Why:
- pane updates were flaky
- HTML capture could be empty or inconsistent
- direct job pages are easier to reason about and debug

Do not move the project back to pane-based scraping unless there is a very strong reason.

---

## File structure

| Path | Purpose |
|------|---------|
| `main.py` | Thin entry point for local runs |
| `scraper_direct.py` | Main SEEK scraper using direct job pages |
| `filters.py` | Deterministic title and content filtering |
| `llm_gate.py` | Optional constrained LLM decision step |
| `admin_api.py` | Local admin console and profile/review API |
| `profile_store.py` | Runtime profile loading, defaults, and persistence |
| `profile_learning.py` | Converts free-text knowledge into structured profile updates |
| `review_insights.py` | Unknown skill extraction and rejected-sample review data |
| `utils.py` | Shared parsing and URL helpers |
| `data/profile.json` | Runtime source of truth for the candidate profile |
| `data/rob_capability_profile.txt` | Human-readable master note for candidate knowledge |
| `data/job_history.json` | Seen/applied/hidden history support |
| `data/llm_cache.json` | Cached LLM decisions |
| `output/seek_results.html` | Human-readable shortlist |
| `output/seek_results.json` | Full audit/debug output |
| `output/seek_run_stats.json` | Latest run metrics |
| `output/seek_review_data.json` | Unknown skills and reject-sample review data |
| `legacy/` | Older scraper drafts kept for reference only |
| `docs/OPERATIONS.md` | Persistence and runtime behavior notes |

---

## Design principles

1. Deterministic first. Rules before LLM, always.
2. LLM constrained. Output must stay `KEEP`, `REJECT`, or `MAYBE`.
3. Cost-aware. Cache responses, minimize prompt size, and only use LLM when needed.
4. Explainable. A reject should have a visible reason whenever possible.
5. Local-first. The project should run on a personal machine without cloud infrastructure.
6. Learnable. The system should get better through explicit user feedback, not hidden magic.
7. Maintainable. Important runtime state must live in files or storage, not buried in code.

---

## Target job profile

- Primary role family: Business Analyst
- Primary market: Sydney, Australia
- Secondary market: Canberra, configurable
- Primary source: SEEK
- Planned source: LinkedIn
- Preferred domains: tech, digital delivery, transformation, discovery, process improvement, stakeholder-heavy BA work
- Avoid domains: cyber/security-heavy roles, specialist platform admin roles, pure finance/banking ops, ERP-heavy roles unless clearly BA-shaped

The exact live fit model is not fully hardcoded. It is driven by:
- `data/profile.json`
- the imported capability profile
- admin-reviewed unknown skills

---

## Admin model

The admin UI is the main local control surface.

Tabs:
- `Search`: what SEEK gets asked for
- `Rob Profile`: summary, CV text, capability matrix, title/description rules
- `Review`: applied/hidden controls and unknown skill decisions
- `Test`: latest run stats and rejected samples

Important rule:
- selecting a skill decision does nothing until `Apply Skill Decisions` is pressed

When applied, new knowledge is written into `data/profile.json` and should then appear in the capability matrix.

---

## Persistence rules

- `data/profile.json` is the runtime source of truth
- `data/rob_capability_profile.txt` is the human master note
- generated outputs under `output/` are disposable and can be recreated
- profile/history/cache under `data/` should be treated as valuable local state

The code now resolves these files relative to the repo location, not the shell working directory. That is important for local reliability and later cloud migration.

---

## Roadmap

### Stage 2 - Reliable data pipeline

- [x] Switch to direct-page SEEK scraping
- [x] Add structured HTML and JSON output
- [x] Add run stats and reject review data
- [x] Add local admin UI
- [x] Add profile persistence and learning loop
- [ ] Keep improving title/content filtering quality
- [ ] Add better extraction for hidden or collapsed job requirements
- [ ] Add export/import helpers for profile portability

### Stage 3 - Real job agent

- [ ] Add scheduling
- [ ] Add message delivery
- [ ] Add application feedback loop
- [ ] Add source expansion beyond SEEK
- [ ] Add durable cloud storage model
- [ ] Wrap cleanly for OpenClaw or similar agent runtime

---

## Tech stack

- Python
- Playwright
- OpenAI API
- optional Anthropic-style future agent integration
- local HTML admin UI backed by Python `http.server`
- JSON file persistence

---

## Guardrails for future AI agents

- Do not reintroduce pane-based scraping as the main path.
- Do not replace deterministic filters with a free-form LLM agent.
- Do not hide important runtime state inside prompts only.
- Do not assume the profile is disposable; preserve `data/profile.json`.
- Do not optimize for hype over reliability.
- Do keep the system understandable enough that a human can inspect why a job was kept or rejected.
