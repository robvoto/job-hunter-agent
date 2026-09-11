# Documentation Index

Use this as the canonical documentation routing index for the repo. It should stay short and point to the current source-of-truth docs rather than becoming a manual itself.

## Source-of-truth docs

- [README.md](../README.md) — project overview, quick start, and top-level product framing.
- [USER_GUIDE.md](USER_GUIDE.md) — day-to-day app use, onboarding, settings, and workspace flow.
- [OPERATIONS.md](OPERATIONS.md) — setup, runtime commands, desktop launcher and installer flow, diagnostics, rebuilds, and recovery.
- [ARCHITECTURE.md](ARCHITECTURE.md) — runtime layers, module ownership, and system boundaries.
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — developer workflow and code ownership map.
- [INTEGRATIONS.md](INTEGRATIONS.md) — packaged integrations, local-only overrides, AWS/runtime boundaries, and LLM/provider rules.
- [SOURCE_REGISTER.md](SOURCE_REGISTER.md) — external sources used to justify product and design decisions.
- [SCORING_RATIONALE.md](SCORING_RATIONALE.md) — scoring model intent, decision history, and the scoring-process diagram links.
- [aws-ec2-setup.md](aws-ec2-setup.md) — canonical AWS EC2 production setup and deployment notes.

## Supporting and reference docs

- [PRINCIPLES.md](PRINCIPLES.md) — product and decision philosophy.
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — Job Hunter-specific agent/project context.
- [PROJECT_STATUS.md](PROJECT_STATUS.md) — implemented, configuration-dependent, and explicitly not-complete product capabilities.
- [AGENT_OPERATING_MODEL.md](AGENT_OPERATING_MODEL.md) — ownership model for AGENTS, skills, adapters, and docs.
- [STANDARDS_INDEX.md](STANDARDS_INDEX.md) — pointers to the canonical shared Google project standards.
- [SHOWCASE_NOTES.md](SHOWCASE_NOTES.md) — proof-oriented demo and positioning notes.
- [UI_COMPONENT_MAP.md](UI_COMPONENT_MAP.md) — UI ownership and reusable component map.
- [runbooks/README.md](runbooks/README.md) — operational runbook index.
- [DOC_INDEX.md](DOC_INDEX.md) — documentation ownership map for deciding where future doc changes belong.

## Diagram and domain references

- [SCORING_RATIONALE.md](SCORING_RATIONALE.md#process-flow-overview) — primary scoring flow explanation plus links to the Mermaid and HTML render files under `docs/diagrams/`.
- [CONFIG_AND_RULES_GOVERNANCE.md](CONFIG_AND_RULES_GOVERNANCE.md) — governance for managed config, rules, and knowledge.
- [candidate_application_history_sync.md](candidate_application_history_sync.md) — retired rejection-sheet sync and JH-308 migration/cutover note; not a live sync procedure.
- [ALIAS_LOGIC_RATIONALE.md](ALIAS_LOGIC_RATIONALE.md) — alias/title matching rationale and historical decisions.
- [CAPABILITY_AGING_RATIONALE.md](CAPABILITY_AGING_RATIONALE.md) — capability recency/aging rationale.
- [OCCUPATION_TAXONOMY_RATIONALE.md](OCCUPATION_TAXONOMY_RATIONALE.md) — occupation taxonomy ownership, matching rationale, and refresh process.
- [REQUIREMENT_DECOMPOSITION_RATIONALE.md](REQUIREMENT_DECOMPOSITION_RATIONALE.md) — the fit-review `decomposition` block, AND/OR requirement semantics, and bounded `capability_judgement`.
