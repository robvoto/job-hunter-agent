# Agent Skill Audit

Purpose: reduce instruction sprawl safely and keep agent routing reliable.

## Current policy

- `AGENTS.md` is the startup router and project-wide rule source.
- `AGENTS.md` contains only a lightweight skill index: name, one-sentence description, and file path.
- Skills are scoped procedures and are loaded on demand.
- `DETAILS.md` is allowed only when the parent `SKILL.md` clearly points to it.
- `CLAUDE.md` and `GEMINI.md` are out of scope for this cleanup.
- Do not delete archived skills until the human explicitly agrees.

## Current counts

- Active `SKILL.md` files indexed in `AGENTS.md`: 16
- Archived skill folders: 4
- `DETAILS.md` files: 3
- `DETAILS.md` parents referenced explicitly: dashboard-ui, onboarding-ui, scraping
- Deleted by human before this audit: prepare-next-task orphan folder

## Completed

- Renamed canonical root instruction file to `AGENTS.md`.
- Added startup protocol: read `AGENTS.md`, load relevant skill, do not use `rg`, do not read everything.
- Added explicit anti-fallback rules to `AGENTS.md`, `.skills/code-change/SKILL.md`, and `.skills/no-hardcoding/SKILL.md`.
- Added visible `DETAILS.md` reference lines to parent skills.
- Trimmed obvious backlog duplication from `AGENTS.md`.
- Sharpened skill frontmatter descriptions to support progressive exposure and reduce semantic drift.
- Converted `AGENTS.md` skill routing table into a lightweight capability index.
- Merged narrow support skill content into owner skills.
- Archived retired skill folders under `docs/archived-skills/`.
- Left `CLAUDE.md` and `GEMINI.md` untouched.

## Archived skills

| Archived skill | Reason | Preserved where |
|---|---|---|
| `workspace-output-sync` | Narrow UI support rule; should not be a first-class routing choice. | Merged into `.skills/dashboard-ui/SKILL.md`. |
| `text-utilities` | Small generic utility guidance; should not compete with code-change/no-hardcoding. | Merged into `.skills/code-change/SKILL.md`. |
| `signal-review-map` | Narrow capability alias diagnostic map. | Merged into `.skills/signal-registry/SKILL.md`. |
| `initialise` | Startup protocol duplicated `AGENTS.md`; nested OpenAI config preserved in archive. | Startup rules now in `AGENTS.md`; folder preserved under `docs/archived-skills/initialise`. |

## Active skills

| Skill | Status | Notes |
|---|---|---|
| `ad-learning` | Active | Pending job-ad learning candidates. Distinct from approved signal governance. |
| `backlog-management` | Active | Critical Google Sheet backlog workflow. Large, but kept because it contains exact sheet/tool rules. |
| `code-change` | Active | Core coding workflow. Now includes text utility rules and anti-fallback rule. |
| `dashboard-ui` | Active | Workspace/dashboard/settings UI. Now includes workspace output sync rule. |
| `history-dedup` | Active | Job history, saved/viewed/applied/hidden state, duplicate identity. |
| `instruction-maintenance` | Active | Maintains agent instruction structure. |
| `job-filtering` | Active | Deterministic pass/fail filters and hard blockers. |
| `knowledge-management` | Active | Managed knowledge/config/source-of-truth ownership. |
| `no-hardcoding` | Active | Cross-cutting config/business-rule/fallback guardrail. |
| `onboarding-ui` | Active | Onboarding wizard/search-basics UI. |
| `preferences` | Active | Candidate preferences and preference-to-filter handoff. |
| `profile-extraction` | Active | CV/profile extraction and normalization. |
| `scoring-ranking` | Active | Fit scoring, ranking, score explanations. |
| `scraping` | Active | SEEK/LinkedIn scraping and source data shape. |
| `signal-registry` | Active | Signal lifecycle/governance. Now includes capability alias map. |
| `suggested-tuning` | Active | Settings > Optimise > Suggested Tuning workflow. Kept because it is feature-specific and detailed. |

## Next checks

1. Ask coding agents to do a dry-run task and verify they read `AGENTS.md`, avoid `rg`, and load one relevant skill.
2. Watch whether any active skill is repeatedly ignored or confused with another.
3. Only after usage evidence, consider further merging.
4. Keep archived skills for now; delete only after human approval.
