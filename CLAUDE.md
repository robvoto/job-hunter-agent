# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start-of-task protocol

**Do this at the start of every task, in order:**

1. Read `AGENTS.md` — architecture, commands, non-negotiable rules, and the skills index.
2. Identify which domain(s) the task touches.
3. Read **only** the relevant `.skills/<domain>/SKILL.md` file(s) — not all of them.
4. Then plan and act.

**Never skip step 1.** `AGENTS.md` is the source of truth.  
**Never read all skills upfront** — they are loaded on demand, one domain at a time, to save tokens.

## Quick reference

| Task | Command |
|---|---|
| Scrape + build dashboard | `python -m job_hunter_agent.source_connector` |
| Rebuild dashboard only | `python -m job_hunter_agent.source_connector --rebuild-dashboard` |
| Local web UI | `python -m job_hunter_agent.fastapi_app` |
| Run tests | `python -m pytest` |
| Run a single test | `python -m pytest tests/test_<name>.py -k "<selector>" -v` |
| Daily agent | `python -m job_hunter_agent.agent_runner` |

Full runtime flags: `docs/OPERATIONS.md`  
Full architecture: `docs/ARCHITECTURE.md`
