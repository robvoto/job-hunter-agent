# Job Hunter Agent - Agent Instructions

## Startup protocol

Before searching or editing:
1. Read this file.
2. Load the most relevant .skills/<area>/SKILL.md.
3. Use repo-supported search commands only.

Do not use rg in this repo. It is unreliable in the current shell. Use the project file search tool, PowerShell Select-String, or targeted file reads instead.

Do not read everything. Read only the skill, docs, code files, or git history needed for the task.

## Project

Local-first job discovery system:

`scrape -> deterministic filters -> optional LLM -> fit score -> workspace`

Runtime source of truth:
- SQLite DB via `JOB_HUNTER_DB_PATH`: per-user profile, history, settings, run outputs, and runtime state.
- `data/users/<user_id>/workspace_results.html`: rendered workspace output.

Managed knowledge:
- `data/knowledge/*.json`: approved business rules seeded into DB.
- `data/config/global_settings.json`: admin-controlled settings seed.
- `data/signals/*.json`: signal registry/defaults, runtime-created and gitignored.

Operational commands, flags, recovery, and diagnostics are owned by `docs/OPERATIONS.md`.

## Source hierarchy

- `AGENTS.md`: project-wide non-negotiables and routing.
- `CLAUDE.md` / `GEMINI.md`: thin adapter files only; do not duplicate core rules.
- `.skills/*/SKILL.md`: scoped operating rules for a work area.
- `.skills/*/DETAILS.md`: longer examples/patterns split out of skills.
- `docs/*`: human/reference documentation.
- Google Sheet backlog: planning/tracking only, not instructions.

## Reading workflow

Do not read everything. Load the most relevant skill before acting, then read only the linked details, docs, code files, or git history needed for the task.

## Skill routing

Do not read all skills. Choose the single best matching skill from this index, then open only that `SKILL.md` before acting.

| Skill | Use when | File |
|---|---|---|
| `code-change` | Use for any code/test/runtime implementation change. Do NOT use for backlog-only edits, instruction cleanup, or business-rule ownership questions unless code also changes. | `.skills/code-change/SKILL.md` |
| `backlog-management` | Use ONLY for backlog work: Google Sheet rows, JH IDs, priorities, duplicates, implementation state, evidence, human review flags, or adding/updating backlog items. Do NOT use for code implementation except to update backlog evidence. | `.skills/backlog-management/SKILL.md` |
| `instruction-maintenance` | Use ONLY when editing agent instruction files: AGENTS.md, adapter files, .skills, DETAILS.md, or docs that define agent workflow. Do NOT use for product/code changes. | `.skills/instruction-maintenance/SKILL.md` |
| `no-hardcoding` | Use whenever changing thresholds, labels, mappings, schema fields, defaults, business rules, fallback values, or rule IDs. Usually combine with the task domain skill. | `.skills/no-hardcoding/SKILL.md` |
| `job-filtering` | Use ONLY for deterministic pass/fail filters, hard blockers, rejection reasons, and pre-scoring job eligibility. Do NOT use for ranking scores; use scoring-ranking. | `.skills/job-filtering/SKILL.md` |
| `scoring-ranking` | Use ONLY for fit score calculation, ranking, score explanations, score weights, and score regression tests. Do NOT use for hard rejection filters; use job-filtering. | `.skills/scoring-ranking/SKILL.md` |
| `profile-extraction` | Use ONLY for CV parsing, profile extraction, candidate capabilities, role history, role duration, and profile normalization. Do NOT use for job-ad learning. | `.skills/profile-extraction/SKILL.md` |
| `signal-registry` | Use ONLY for approved learning signal lifecycle: pending/approved/ignored signals, promotion into runtime knowledge, and signal governance. Do NOT use for raw ad extraction; use ad-learning. | `.skills/signal-registry/SKILL.md` |
| `preferences` | Use ONLY for candidate preference inputs and settings such as location, contract, government, salary, work mode, source settings, and preference-to-filter handoff. Do NOT use for scoring implementation. | `.skills/preferences/SKILL.md` |
| `dashboard-ui` | Use ONLY for workspace/dashboard/settings UI routes, templates, scripts, rendered results, score/highlight display, and visible UI behaviour. Do NOT use for onboarding UI; use onboarding-ui. | `.skills/dashboard-ui/SKILL.md` |
| `onboarding-ui` | Use ONLY for onboarding wizard/search-basics UI, onboarding templates/scripts/routes, bootstrap data, reset/resume flow, upload flow, and onboarding validation. Do NOT use for workspace/dashboard UI. | `.skills/onboarding-ui/SKILL.md` |
| `scraping` | Use ONLY for SEEK/LinkedIn scraping, source connector behaviour, scraped job data shape, source diagnostics, work-mode provenance, and raw evidence capture. Do NOT use for scoring or candidate preference decisions. | `.skills/scraping/SKILL.md` |
| `ad-learning` | Use ONLY for extracting learning candidates from job ads after scraping/review. Do NOT use for approved signal storage; use signal-registry instead. | `.skills/ad-learning/SKILL.md` |
| `knowledge-management` | Use ONLY for managed knowledge/config sources, DB-seeded knowledge, rule loaders, file/path ownership, and source-of-truth questions. Do NOT use for UI or scraper logic directly. | `.skills/knowledge-management/SKILL.md` |
| `history-dedup` | Use ONLY for job history, viewed/applied/hidden/saved state, duplicate job identity, and cross-source deduplication. Do NOT use for scoring or filtering rules. | `.skills/history-dedup/SKILL.md` |
| `suggested-tuning` | Use ONLY for Settings > Optimise > Suggested Tuning: empty suggestions, scrape/review-derived tuning items, capability suggestion confirmation, and rejection-pattern exclusion suggestions. | `.skills/suggested-tuning/SKILL.md` |

## Non-negotiables

- Deterministic filters run before LLM.
- Business judgement belongs in managed config, knowledge, profile data, or reviewed learning flows, not feature code.
- Do not hardcode scoring weights, thresholds, fallback labels, schema guesses, or hidden defaults in feature logic.
- Hard rejection is only for explicit blockers backed by approved rules.
- Producers define and normalise schema. Consumers must not guess field names or invent fallback values.
- Weak or uncertain signals are preserved for review, not silently deleted.
- Learning flows through the signal registry before becoming runtime knowledge.
- New user-facing surfaces must include concise help text or inline guidance for any non-obvious control or action; if a surface needs reusable wording, centralise it in the owning source or skill rather than hardcoding it in feature code.
- Every Python module should start with a concise top-level docstring that states its purpose.
- Touch only files required for the task. Avoid unrelated refactors.
- Remove unused code and dead paths instead of preserving legacy paths.
- Surface missing/invalid values as explicit degraded/error states. Do not create silent business fallbacks.
- Do not mask errors with fallback encoders, fallback parsers, fallback labels, default models, guessed config, alternate fields, or broad exception swallowing. Stop and expose the failure unless the human explicitly approves a fallback for a stated reason.
- UI/UX changes must follow existing theme, shared components, and owning UI skills.

## Backlog rules

- Working backlog: `https://docs.google.com/spreadsheets/d/1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0/`.
- The Google Sheet is the backlog source of truth; local Excel/markdown backlog files are reference only unless explicitly requested.
- Do not select or implement rows where `Implementation State = Done` unless the human explicitly asks to audit, reopen, correct, or revise that row.
- For backlog work, read `.skills/backlog-management/SKILL.md` before acting.

## Testing rule

Use risk-based validation.

- For every code change, run the smallest relevant tests that directly cover the changed behaviour.
- Before declaring work done, run enough adjacent validation to prove the immediate integration path still works.
- Run the full test suite when the change touches shared infrastructure, auth, persistence, routing, app startup, global settings, shared templates/bootstrap, scoring/filtering core, common utilities, multiple modules, or release/merge preparation.
- Record the exact validation run before marking work done.
- Do not claim `Done` without test evidence.

## Definition of Done

A change is done only when:

1. Implementation is tested according to the testing rule, and test commands are recorded.
2. New tests are added or existing tests updated when behaviour changes.
3. The solution is not an unapproved fallback, hardcoding, or heuristic.
4. Current project patterns are followed, including modular frontend ownership where applicable.
5. Unused code is removed.
6. Helpful code comments are added where intent or ownership is not obvious.
7. Relevant docs, skills, backlog evidence, or operations notes are updated.

## Design standard

- Prefer small, single-purpose modules over monoliths.
- If the requested approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith, say so before editing and propose the professional alternative.
- Do not add backward-compatibility shims, duplicate implementations, or dead paths unless explicitly agreed.
- If a weaker design is genuinely needed, get human agreement and document the reason.

