# Project Context - Job Hunter Agent

This file contains Job Hunter-specific context for otherwise reusable agent instructions and skills.

## Product

Job Hunter is a local-first job discovery system:

`scrape -> deterministic filters -> optional LLM -> fit score -> workspace`

It is a strict, explainable job-fit system, not a vague recommender.

## Runtime truth

- Repo root: `/home/robvoto/projects/job-hunter-agent`.
- Agent orchestration: LangGraph-based bounded workflow (classify -> cost/risk estimate -> approval gate -> run agent -> log). OpenClaw is retired; do not reference it as the runtime.
- Runtime state lives in SQLite via `JOB_HUNTER_DB_PATH`.
- Workspace output is account-scoped and resolved from the authenticated session; the on-disk path is an internal runtime detail.
- Approved knowledge seeds live in `data/knowledge/*.json`.
- Global admin settings seed lives in `data/config/global_settings.json`.
- Runtime signal files live in `data/signals/*.json` and are gitignored.
- Treat `instruction_file` and `instruction_skills` as project metadata references, not automatically injected runtime instructions.

## Project reference docs

- `docs/ARCHITECTURE.md`: system design, runtime layers, module ownership.
- `docs/PRINCIPLES.md`: product and decision philosophy.
- `docs/OPERATIONS.md`: commands, flags, diagnostics, recovery.

## Project-specific skill routing

Choose the best matching skill. Combine with reusable skills such as `code-change`, `no-hardcoding`, or `css-design-system` when relevant.

| Skill | Use for |
|---|---|
| `.skills/backlog-management/SKILL.md` | Google Sheet backlog rows, state, evidence |
| `.skills/job-filtering/SKILL.md` | Deterministic filters, hard blockers, reject reasons |
| `.skills/scoring-ranking/SKILL.md` | Fit score, ranking, scoring explanations |
| `.skills/profile-extraction/SKILL.md` | CV/profile extraction and normalization |
| `.skills/signal-registry/SKILL.md` | Approved learning signal lifecycle |
| `.skills/preferences/SKILL.md` | Location, contract, government, salary, work mode preferences |
| `.skills/dashboard-ui/SKILL.md` | Workspace and settings UI |
| `.skills/onboarding-ui/SKILL.md` | Onboarding wizard, upload, reset/resume flow |
| `.skills/scraping/SKILL.md` | SEEK/LinkedIn scraping and raw evidence capture |
| `.skills/ad-learning/SKILL.md` | Extracting learning candidates from job ads |
| `.skills/knowledge-management/SKILL.md` | Managed knowledge/config sources and loaders |
| `.skills/history-dedup/SKILL.md` | Job history, viewed/applied/hidden state, deduplication |
| `.skills/suggested-tuning/SKILL.md` | Settings > Optimise > Suggested Tuning |

## Job Hunter non-negotiables

- Deterministic filters run before LLM.
- Hard rejection is only for explicit blockers backed by approved rules.
- Weak or uncertain signals are preserved for review, not silently deleted.
- Learning flows through the signal registry before becoming runtime knowledge.

## Backlog

For backlog work, read `.skills/backlog-management/SKILL.md` first. Do not implement rows marked `Implementation State = Done` unless the human explicitly asks to audit, reopen, correct, or revise them.

Backlog items (tasks, stories, bugs) live only in the Google Sheet via `.skills/backlog-management/SKILL.md`. Never track them with the TodoWrite tool — TodoWrite is for in-conversation step tracking only, not backlog state.
