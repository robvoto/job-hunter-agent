# Project Context - Job Hunter Agent

This file contains Job Hunter-specific context for otherwise reusable agent instructions and skills.

## Product

Job Hunter is a local-first job discovery system:

`scrape -> deterministic filters -> optional LLM -> fit score -> workspace`

It is a strict, explainable job-fit system, not a vague recommender.

## Runtime truth

- Windows project path: `E:\Programming\job-hunter-agent`.
- WSL project path: `/mnt/e/Programming/job-hunter-agent`.
- OpenClaw/coding-agent workspace path: `/home/robvoto/.openclaw/workspace/coding-agent`.
- Runtime state lives in SQLite via `JOB_HUNTER_DB_PATH`.
- Per-user rendered workspace output lives under `data/users/<user_id>/`.
- Approved knowledge seeds live in `data/knowledge/*.json`.
- Global admin settings seed lives in `data/config/global_settings.json`.
- Runtime signal files live in `data/signals/*.json` and are gitignored.
- Use `config/projects.json` in the coding-agent workspace to resolve this repo for OpenClaw runtime work.
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
| `.skills/dashboard-ui/SKILL.md` | Workspace/dashboard/settings UI |
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