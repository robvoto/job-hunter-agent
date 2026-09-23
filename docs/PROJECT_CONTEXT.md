# Project Context - Job Hunter Agent

This file contains Job Hunter-specific context for otherwise reusable agent instructions and skills.

## Product

Job Hunter is a local-first job discovery system. A run first selects one market-acquisition
lane, then keeps that lane for the whole run:

`JMM neutral search OR built-in source scrapers -> deterministic personal filters -> optional LLM -> fit score -> workspace`

When JMM is selected, current JDs are consumed through JMM's cached-JD GET contract and
JMM remains the neutral market owner. There is no mid-run switch from JMM to direct scraping.

It is a strict, explainable job-fit system, not a vague recommender.

## Runtime truth

- Repo root: `/home/robvoto/projects/job-hunter-agent`.
- Agent orchestration: scheduled/on-demand coordination is implemented in `job_hunter_agent/agent_runner.py`.
- Job Market Map is the local market-data and current-JD owner. Local Job Hunter consumes it through the /v3 HTTP API; JMM is not hosted or deployed on AWS.
- Runtime state lives in SQLite via `JOB_HUNTER_DB_PATH`.
- Workspace output is account-scoped and resolved from the authenticated session; the on-disk path is an internal runtime detail.
- Approved knowledge seeds live in `data/knowledge/*.json`.
- Global admin settings seed lives in `data/config/global_settings.json`.
- Runtime signal files live in `data/signals/*.json` and are gitignored.
- Treat `instruction_file` and `instruction_skills` as project metadata references, not automatically injected runtime instructions.
- **Runtime lifecycle approval:** starting, stopping, restarting, killing, or relaunching JH, JMM, Human MCP, or its shared browser broker requires explicit approval for that target/action in the current conversation. Approval is single-use and does not carry over; Git/test/release/health work never implies it. Read-only inspection is allowed, but unexpected runtime state is reported rather than corrected without fresh approval.
- **Applied-history rendering integrity:** historical/applied workspace cards must use real title/company identity; do not fabricate `Untitled`, `N/A`, or `href="#"`. Reconstruct SEEK/LinkedIn URLs only from stable platform IDs when the stored URL is missing, and load `job_history` during workspace rebuild so persistent applied state remains reconstructable.

## Project reference docs

- `docs/ARCHITECTURE.md`: system design, runtime layers, module ownership.
- `docs/PRINCIPLES.md`: product and decision philosophy.
- `docs/OPERATIONS.md`: commands, flags, diagnostics, recovery.

## Project-specific skill routing

Use `.agents/skills/INDEX.md` as the single skill-routing catalogue. Load the smallest matching skill, then combine with reusable skills only when the task crosses ownership boundaries. Do not duplicate the active skill list here. Git workflow and PR/branch cleanup are single-owned by `.agents/skills/git-lifecycle/SKILL.md`; project docs should not retain PR-specific handoff links or obsolete branch references.

## Backlog

Backlog items live only in the canonical Google Sheet. For any backlog read/write/grooming task, use `.agents/skills/backlog-management/SKILL.md`; do not create a parallel backlog in repository files or runtime-specific task tools.
