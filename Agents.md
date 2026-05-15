# Job Hunter Agent — AI Context
 
## Local Environment url
http://localhost:8765/

## Project

Local-first job discovery system:

scrape → deterministic filters → optional LLM → fit score → workspace

Runtime source of truth:
- `data/profile.json`

Managed knowledge:
- `data/*.json`

Main entry point:
- `python -m job_hunter_agent.source_connector`

## Environment defaults

- This repo may be used manually from VS Code or programmatically by OpenClaw.
- When running inside WSL, use WSL/Linux shell commands and `/mnt/...` paths.

## Commands

| Task | Command |
|---|---|
| Scrape + build workspace | `python -m job_hunter_agent.source_connector` |
| Rebuild workspace only | `python -m job_hunter_agent.source_connector --rebuild-workspace` |
| Local web UI | `python -m job_hunter_agent.fastapi_app` |
| Daily agent | `python -m job_hunter_agent.agent_runner` |
| Tests | `python -m pytest` |

See `docs/OPERATIONS.md` for full runtime flags.

## Skills

Load the relevant skill before editing that area.

| Skill | Purpose |
|---|---|
| `.skills/code-change/SKILL.md` | General code edits |
| `.skills/no-hardcoding/SKILL.md` | Config, defaults, thresholds, schema ownership |
| `.skills/job-filtering/SKILL.md` | Filters and rejection logic |
| `.skills/scoring-ranking/SKILL.md` | Fit scoring and ranking |
| `.skills/profile-extraction/SKILL.md` | CV/profile extraction |
| `.skills/signal-registry/SKILL.md` | Learning and approval flow |
| `.skills/preferences/SKILL.md` | Location/contract/government/salary |
| `.skills/dashboard-ui/SKILL.md` | Workspace and FastAPI UI |
| `.skills/scraping/SKILL.md` | SEEK/LinkedIn scraping |

## Context hygiene

- Start here, then load only the needed skill.
- Prefer updating skills/docs over expanding this file.
- Keep changes small and targeted.
- Run the smallest relevant validation.

## Architecture

```text
scrape
→ title filter
→ content filter
→ optional LLM
→ fit_score()
→ workspace
```

System design:
- `docs/ARCHITECTURE.md`

Product and decision philosophy:
- `docs/PRINCIPLES.md`

## Non-negotiable rules

1. Deterministic filters run before LLM.
2. Business judgement belongs in managed config/knowledge/profile sources — not feature code.
3. Do not hardcode scoring weights, thresholds, fallback labels, or hidden defaults in feature logic.
4. Hard rejection is reserved for explicit blockers backed by approved rules.
5. Producers define and normalise schema. Consumers must not guess field names or invent fallback values.
6. Weak/uncertain signals are preserved for review — not silently deleted.
7. Learning flows through the signal registry before becoming runtime knowledge.
8. Touch only files required for the task. Avoid unrelated refactors.
9. We dont want legacy coding... this is not a production application. Remove Unused Remove Legacy
10. You code like PRO and don't use bad heuristics and silent fallbacks
11. UI UX updates must respect themes implementation?

## Failure handling rule

Do not use silent fallback business values. f an LLM output, grade, label, threshold, or decision is missing/invalid, surface it as an explicit degraded/error state. Do not invent defaults unless explicitly approved.
