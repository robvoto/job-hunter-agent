# Job Hunter Agent — AI Context
 
## Local Environment url
http://localhost:8765/

## Project

Local-first job discovery system:

scrape → deterministic filters → optional LLM → fit score → workspace

Runtime source of truth:
- SQLite DB (`JOB_HUNTER_DB_PATH`) — per-user profile, history, run outputs, settings
- `data/users/<user_id>/workspace_results.html` — rendered workspace (filesystem)

Managed knowledge (seeded into DB via `db_seed.py`):
- `data/knowledge/*.json` — approved business rules
- `data/config/global_settings.json` — admin-controlled runtime settings seed
- `data/signals/*.json` — signal registry and defaults (gitignored; created at runtime)

Operational entry points and commands are owned by `docs/OPERATIONS.md`.

## Environment defaults

- This repo may be used manually from VS Code or programmatically by OpenClaw.
- When running inside WSL, use WSL/Linux shell commands and `/mnt/...` paths.

## Commands

Do not duplicate runtime command tables here.

Use `docs/OPERATIONS.md` for runtime commands, flags, rebuild flows, diagnostics, recovery, and validation commands.

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
| `.skills/onboarding-ui/SKILL.md` | Onboarding wizard, search basics, and onboarding page UI |
| `.skills/workspace-output-sync/SKILL.md` | Live workspace HTML vs source template sync |
| `.skills/scraping/SKILL.md` | SEEK/LinkedIn scraping |
| `.skills/text-utilities/SKILL.md` | Text normalisation, matching helpers, description trust |
| `.skills/ad-learning/SKILL.md` | Learning candidates from job ads, signal suggestions |
| `.skills/knowledge-management/SKILL.md` | Managed JSON knowledge, rule loaders, path ownership |
| `.skills/signal-review-map/SKILL.md` | Capability alias flow: dominant_signal_clusters vs capability_profile_rules |
| `.skills/history-dedup/SKILL.md` | Job history, viewed/applied/hidden state, deduplication |
| `.skills/initialise/SKILL.md` | Repo bootstrap and workflow guardrails |

## Context hygiene

- Start here, then load only the needed skill.
- Prefer updating skills/docs over expanding this file.
- Keep changes small and targeted.
- Run the smallest relevant validation.

## Backlog management

- The working backlog is `docs/backlog/backlog_review.xlsx`.
- Treat the workbook as the backlog source of truth, not the old markdown backlog notes.
- Do not regenerate a new backlog structure unless explicitly agreed.
- Keep existing backlog IDs stable.
- Do not delete backlog rows without human agreement.
- If an item looks duplicate, obsolete, already done, or unclear, mark it in the workbook with evidence instead of deleting it.
- New agreed backlog items should be added to the workbook.
- When creating or updating a backlog row, fill or update every relevant column, not just the title. At minimum maintain: ID, Title, Epic, Type, Priority, Size, Problem, Outcome, Acceptance Criteria, Source Files, Duplicate Of, Depends On, Notes, Implementation State, Implementation Date, Implemented By, and Evidence when those columns exist.
- Adapt to workbook schema changes made by the human. Read the header row first and update existing columns by name rather than assuming fixed column positions.
- Maintain Excel 2013 compatibility for `backlog_review.xlsx`. Avoid workbook features that Excel 2013 may repair/remove, and test compatibility before adding Excel features such as filters, panes, tables, validations, or hidden helper sheets.
- Do not remove or rename workbook columns unless explicitly agreed.
- Old markdown backlog files may be archived only after coverage has been checked and agreed.

## Definition of Done

A change is done only when all relevant checks below are satisfied:

1. The implementation is tested.
   - Run the smallest relevant test set first, then add adjacent tests and at least one representative integration, end-to-end, or page-render path for any change that crosses modules, auth, UI, persistence, or shared bootstrap/template code.
   - If the change is broad, risky, or still leaves uncertainty, say that a wider pass is needed instead of treating the minimal set as enough.
   - Add new tests or update existing tests.
   - Link or name the relevant tests in the implementation notes, PR, or backlog evidence.
2. The solution is not an unapproved fallback, hardcoding, or heuristic.
   - Business judgement belongs in managed config, knowledge, profile data, or reviewed learning flows.
   - If a fallback, hardcoding, or heuristic is genuinely needed, get human agreement first and document the reason.
3. Current project patterns and frontend best practices are followed.
   - For frontend work, prefer the established modular JavaScript / ES module-style ownership patterns where applicable.
   - If a weaker or legacy pattern is used, get human agreement first and document the reason.
4. Unused code is removed.
   - Do not leave dead paths, duplicate implementations, or compatibility shims unless explicitly agreed.
5. Code help text is added or updated where it helps a human understand the implementation.
   - Add concise module, class, function, or complex-block comments when the purpose is not obvious.
   - Comments should explain intent and ownership, not repeat the code line-by-line.
   - This is mainly for human maintainability, not agent prompting.
6. Documentation is updated.
   - Update the relevant docs, skills, backlog evidence, or operations notes for the touched area.

## Design and code quality

- Prefer small, single-purpose modules over large monolithic files.
- If a change mixes unrelated responsibilities, split by ownership rather than adding more logic to one file.
- Before writing code, check whether the approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith.
- If it is, say so explicitly before editing files: name the pattern, explain why it is suboptimal, and state the professional alternative.
- If a better approach is feasible within scope, ask before using the weaker one.
- Do not add backward-compatibility code, duplicate implementations, or dead paths unless explicitly requested.
- Remove unused code instead of preserving it.
- If the task would require a workaround or weaker design, call that out before changing anything.

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
9. No legacy code. Remove unused code and dead paths instead of leaving them in place.
10. No bad heuristics or silent fallbacks. Surface missing/invalid values as explicit errors.
11. UI/UX updates must respect the themes implementation.
12. For Settings booleans and sector preferences, reuse the shared switch or choice-strip patterns and update the owning skill/docs/tests instead of adding one-off controls.

## Failure handling rule

Do not use silent fallback business values. f an LLM output, grade, label, threshold, or decision is missing/invalid, surface it as an explicit degraded/error state. Do not invent defaults unless explicitly approved.
