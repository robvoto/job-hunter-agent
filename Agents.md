# Job Hunter Agent — AI Context
 
## Local Environment url
http://localhost:8765/

## Project

Local-first job discovery system:

scrape → deterministic filters → optional LLM → fit score → workspace

Runtime source of truth:
- `data/users/<user_id>/profile.json`

Managed knowledge:
- `data/knowledge/*.json`

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
