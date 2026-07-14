# Integrations Guide

This guide describes which integrations exist, which ones are packaged product behavior, which ones are local-only owner conveniences, and which boundaries must stay private.

## Packaged job-source integrations

### SEEK

- Owner flow: `job_hunter_agent.source_connector` orchestrates the run, and `job_hunter_agent.source_runner` dispatches the SEEK source.
- Scraping path: Playwright-backed SEEK scraping lives under `job_hunter_agent.scrapers.seek*`.
- Runtime note: AWS/browser-session troubleshooting belongs in [runbooks/aws-seek-assisted-browser-session.md](runbooks/aws-seek-assisted-browser-session.md).
- Boundary: assisted verification is an operational/browser mode, not a separate product source.

### LinkedIn

- Owner flow: `job_hunter_agent.source_runner` dispatches the LinkedIn source independently of SEEK.
- Scraping path: LinkedIn ingestion currently uses `python-jobspy` through `job_hunter_agent.scrapers.linkedin`.
- Boundary: LinkedIn failures must stay isolated so the rest of the run can complete with preserved partial results.

### APSJobs

- Owner flow: `job_hunter_agent.source_runner` dispatches APSJobs like the other enabled sources.
- Scraping path: APSJobs uses the Playwright scraper in `job_hunter_agent.scrapers.apsjobs`.
- Boundary: APSJobs keeps its own isolated state and participates in the same concurrent source-runner lane when enabled.

### Future source adapter contract

- New sources plug into the same source-runner boundary instead of inventing parallel orchestration.
- The adapter must return source-scoped kept records, audit rows, and skill observations through the shared `SourceRunResult` shape.
- New sources must respect the existing runtime rules: deterministic filtering before LLM review, explicit stop handling, and no hidden per-source fit semantics.

## Local-only and private integrations

### Candidate application history override

- Local override file: `data/runtime/rob_candidate_application_history_import.local.json`
- Owner: `job_hunter_agent.global_settings`
- Purpose: allow a local owner-only spreadsheet id/tab override for candidate application history import without shipping personal values in committed settings.
- Boundary: this file is gitignored runtime state and must not ship in desktop builds, packaged defaults, sample data, or public docs with real values.

### Runtime-local state

- `data/users/`, `data/runtime/`, `output/`, and local auth/runtime DBs are local runtime state, not source material to commit or package.
- Personal spreadsheets, job history, scraped results, and private examples stay outside repo-managed defaults.

## AWS and runtime deployment boundaries

- Canonical AWS setup: [aws-ec2-setup.md](aws-ec2-setup.md)
- Runtime env roots:
  - `JOB_HUNTER_DATA_DIR`
  - `JOB_HUNTER_OUTPUT_DIR`
  - `JOB_HUNTER_DB_PATH`
- Seed/deploy rule: `python -m job_hunter_agent.db_seed` syncs only the approved repo-managed JSON seed manifest. It does not recursively copy arbitrary JSON files from `data/knowledge`.
- Required runtime knowledge includes the managed knowledge JSON plus the O*NET occupation taxonomy JSON files needed at runtime.
- Boundary: production-only environment files, secrets, service definitions, and mounted data paths must stay out of git and out of packaged defaults.

## LLM and provider boundary

- Current runtime direction: OpenAI-backed structured review and scoring support.
- Product rule: provider-neutral architecture remains the target boundary even if the current implementation uses OpenAI-specific settings and pricing metadata.
- Credential rule: user-owned credentials only. No shared packaged key, no committed private provider token, and no global/team learning side channel.
- Desktop v1 rule still applies: no global keys, no shared learning, no upload without consent.

## Project-management-only integrations

- The shared Google Sheet backlog is project-management infrastructure for implementation tracking, not packaged app functionality.
- Connector/tooling used by coding agents to read or update backlog rows must not be described as an in-product user feature.

## Related docs

- [INDEX.md](INDEX.md)
- [OPERATIONS.md](OPERATIONS.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SOURCE_REGISTER.md](SOURCE_REGISTER.md)
