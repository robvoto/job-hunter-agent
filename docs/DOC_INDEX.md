# Documentation Ownership Map

Canonical navigation starts at [docs/INDEX.md](INDEX.md).

This file is the ownership map for deciding where doc changes belong. It is not the primary front door for humans or coding agents.

Use this file to decide where information belongs. Do not create a new markdown file unless none of these owners fit.

## Root Files

| File | Owner |
|---|---|
| `README.md` | Project overview, quick start, and links to deeper docs. |
| `AGENTS.md` | Tiny reusable agent loader only. |
| `.clinerules/` | Thin Cline-specific adapter rules. |
| `docs/INDEX.md` | Canonical documentation routing index. |

## Core Docs

| File | Owner |
|---|---|
| `docs/PROJECT_CONTEXT.md` | Job Hunter product context, runtime truth, repo-root path, project-specific skill routing, startup/run notes, backlog pointer. |
| `docs/CLINE_MEMORY.md` | Cline-specific durable session context; loaded through `.clinerules/`, never through shared `AGENTS.md`. |
| `docs/AGENT_OPERATING_MODEL.md` | Agent instruction layering, skill discovery, adapter ownership, tool-vs-skill rules, active/archived skill summary. |
| `docs/ARCHITECTURE.md` | System design, runtime layers, and module ownership. |
| `docs/PRINCIPLES.md` | Product and decision philosophy. |
| `docs/DEVELOPER_GUIDE.md` | Developer workflow and code ownership map. |
| `docs/OPERATIONS.md` | Commands, flags, diagnostics, recovery, and deployment operations. |
| `docs/USER_GUIDE.md` | User-facing application behaviour and usage. |
| `docs/SHOWCASE_NOTES.md` | Local demo, showcase, and product-positioning notes tied to visible proof. |
| `docs/aws-ec2-setup.md` | Current AWS EC2 production setup. |

## Operational Runbooks

| File/folder | Owner |
|---|---|
| `docs/runbooks/README.md` | Runbook index and rules for creating operational troubleshooting procedures. |
| `docs/runbooks/aws-seek-assisted-browser-session.md` | AWS SEEK assisted browser troubleshooting: DB seed, uv commands, noVNC/Xvfb checks, browser settings, and SEEK pass condition. |

Runbooks are for live incident-style procedures. They should contain exact commands, expected outputs, failure interpretation, and pass criteria. They should not become design diaries.

## Domain/Reference Docs

| File | Owner |
|---|---|
| `docs/CONFIG_AND_RULES_GOVERNANCE.md` | Config, rule, knowledge, and governance ownership. |
| `docs/SOURCE_REGISTER.md` | External/internal source inventory and source-specific notes. |
| `docs/SCORING_RATIONALE.md` | Fit score rationale, scoring model explanation, and scoring decision history. |
| `docs/UI_COMPONENT_MAP.md` | UI component ownership and reusable UI map. |
| `docs/ALIAS_LOGIC_RATIONALE.md` | Alias/title matching rationale. Candidate to merge into a future decision log. |
| `docs/CAPABILITY_AGING_RATIONALE.md` | Capability aging/strength rationale. Candidate to merge into a future decision log. |
| `docs/OCCUPATION_TAXONOMY_RATIONALE.md` | Occupation taxonomy rationale. Candidate to merge into a future decision log. |
| `docs/candidate_application_history_sync.md` | Candidate application history sync notes. Candidate to merge into operations/config governance. |

## Backlog

Backlog source of truth is the shared Google Sheet. `docs/backlog/` is intentionally gitignored and may contain local historical extraction/reference notes, but those files are not repository documentation and must not be required by repo-health tests.

## Skills

| Folder | Owner |
|---|---|
| `.skills/INDEX.md` | Canonical skill-routing index. One short routing line per active skill. |
| `.skills/*/SKILL.md` | One active agent workflow/domain each. Must include YAML `name` and `description`. |
| `.skills/aws-test-instance/SKILL.md` | AWS Job Hunter test EC2 instance facts, SSM access workflow, instance-side logs, and host/runtime diagnosis. |
| `.skills/release-management/SKILL.md` | Release version ownership, gates, tags, and publishing workflow. |
| `.skills/mcp-tooling/SKILL.md` | Repository/filesystem and connected-service access, with runtime-scoped Human MCP browser/Gmail tooling and failure recovery. |
| `.skills/aws-test-instance/DETAILS.md` | Exact AWS test instance identifiers, app/log paths, SSM commands, and known host-side failure patterns. |
| `.skills/*/DETAILS.md` | Longer examples/details loaded only when the parent skill points to them. |
| `docs/archived-skills/` | Retired skills kept for history only. Not active routing. |

## Release Automation

| File | Owner |
|---|---|
| `scripts/release-jobhunter.sh` | Clean-main release orchestration: version bump, tests, commit, annotated tag, and atomic push. |
| `scripts/ec2/deploy-jobhunter-release.sh` | Production AWS deploys from immutable `vX.Y.Z` tags only. |
| `scripts/ec2/deploy-jobhunter-latest.sh` | Non-production AWS smoke/debug deploys from `main` by default or from a branch/commit ref when supplied. |
| `scripts/check-release-integrity.py` | `pyproject.toml`, `uv.lock`, rendered UI metadata, and Git-tag version validation. |
| `.github/workflows/release-integrity.yml` | GitHub validation for branch/tag release integrity and tagged-release E2E coverage. |

## Rules for New Docs

- Prefer updating an existing owner before creating a new doc.
- Use `docs/runbooks/` for exact live troubleshooting procedures with commands and pass/fail criteria.
- If a doc is historical, put it under an `archive/` folder or mark it clearly as historical.
- If a rule tells all agents how to act, it usually belongs in `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, or one `.skills/*/SKILL.md`.
- Agent-specific session context belongs only in that agent's adapter or memory owner and must not be promoted into shared `AGENTS.md`.
- If a doc repeats another owner, merge or link instead of duplicating.
