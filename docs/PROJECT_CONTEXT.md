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

Use `.agents/skills/INDEX.md` as the single skill-routing catalogue. Load the smallest matching skill, then combine with reusable skills only when the task crosses ownership boundaries. Do not duplicate the active skill list here.

## Job Hunter non-negotiables

- Deterministic filters run before LLM.
- Hard rejection is only for explicit blockers backed by approved rules.
- Weak or uncertain signals are preserved for review, not silently deleted.
- Learning flows through the signal registry before becoming runtime knowledge.
- Do not infer salary or pay period from free-text ad prose with deterministic heuristics. Compensation must come from structured source data or another explicitly approved owner; otherwise keep it unknown.
- Any new heuristic or hardcoded business/display rule is a red flag and requires explicit human approval before implementation.

## Backlog

For backlog work, read `.agents/skills/backlog-management/SKILL.md` first. Do not implement rows marked `Implementation State = Done` unless the human explicitly asks to audit, reopen, correct, or revise them.

Backlog items (tasks, stories, bugs) live only in the Google Sheet via `.agents/skills/backlog-management/SKILL.md`. Never track them with the TodoWrite tool — TodoWrite is for in-conversation step tracking only, not backlog state.
