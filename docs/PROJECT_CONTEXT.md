# Project Context - Job Hunter Agent

This file contains Job Hunter-specific context for otherwise reusable agent instructions and skills.

## Product

Job Hunter is a local-first job discovery system:

`local JMM discovery -> card fetch -> on-demand JD -> deterministic filters -> optional LLM -> fit score -> workspace`

It is a strict, explainable job-fit system, not a vague recommender.

## Runtime truth

- Repo root: `/home/robvoto/projects/job-hunter-agent`.
- Agent orchestration: LangGraph-based bounded workflow (classify -> cost/risk estimate -> approval gate -> run agent -> log). OpenClaw is retired; do not reference it as the runtime.
- Job Market Map is the local market-data and current-JD owner. Local Job Hunter consumes it through the /v3 HTTP API; JMM is not hosted or deployed on AWS.
- Runtime state lives in SQLite via `JOB_HUNTER_DB_PATH`.
- Workspace output is account-scoped and resolved from the authenticated session; the on-disk path is an internal runtime detail.
- Approved knowledge seeds live in `data/knowledge/*.json`.
- Global admin settings seed lives in `data/config/global_settings.json`.
- Runtime signal files live in `data/signals/*.json` and are gitignored.
- Treat `instruction_file` and `instruction_skills` as project metadata references, not automatically injected runtime instructions.
- **Runtime lifecycle approval:** never start or restart Job Hunter (local, desktop-launcher, service, AWS, or equivalent runtime) unless Rob explicitly approves that specific start/restart in the current conversation or task. Code changes, tests, commits, merges, pushes, release/version checks, or a request to verify that code is ready to test do not imply permission to run it. Stopping Job Hunter also requires an explicit stop request, except for the stop/start pair inherent in a restart that Rob has already approved. Process/service inspection that does not change runtime state does not require approval.

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
- Deterministic salary extraction is allowed only where the source structure makes the interpretation reliable and testable. If a reliable value is not present, preserve salary as unknown and let the LLM identify missing evidence where the workflow supports it; never guess.
- New heuristics must be deterministic, source-grounded, testable, and explicitly approved. Unreliable heuristics or hidden hardcoded business/display rules are not acceptable.

## Backlog

For backlog work, read `.agents/skills/backlog-management/SKILL.md` first. Do not implement rows marked `Implementation State = Done` unless the human explicitly asks to audit, reopen, correct, or revise them.

Backlog items (tasks, stories, bugs) live only in the Google Sheet via `.agents/skills/backlog-management/SKILL.md`. Never track them with the TodoWrite tool — TodoWrite is for in-conversation step tracking only, not backlog state.
