# Integrations Guide

This guide describes which integrations exist, which ones are packaged product behavior, which ones are local-only owner conveniences, and which boundaries must stay private.

## Packaged job-source integrations

### Job Market Map (JH-306)

- Normal Job Hunter discovery is consumed from JMM's supported `/v3` HTTP API.
- Configure `JOB_HUNTER_MARKET_MAP_BASE_URL` to the deployed JMM API base,
  including `/v3`; there is no direct SQLite access or silent scraper fallback.
- JMM owns neutral identity, card facts, current JD storage, source collection,
  and on-demand JD enrichment. JH owns candidate analysis and decisions.
- JH requests a current JD from JMM only after the JH card gate says detail is
  needed. JMM's current JD is transient analysis input; new JH workspace/history
  records retain JMM identity and JD provenance without copying the JD.
- JMM processing cursors are namespaced per authenticated JH user. They are
  workflow checkpoints, not personal activity; JH-305 remains the activity owner.
- JH sends its existing role terms, locations, date window, and selected boards to
  JMM's stateless `/v3/jobs/search` endpoint. JMM evaluates those filters against
  any active linked source row and returns each canonical vacancy once.
- Each JH market search uses a transient JMM snapshot boundary for its stateless
  search pages. It is not persisted and does not advance a consumer checkpoint.
- Existing JH scraper/history data is retained only for the bounded JH-308
  retirement path and is not a fallback source for the JMM-backed run.

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

### Candidate application history cutover input

- Local override file: `data/runtime/rob_candidate_application_history_import.local.json`
- Owner: `job_hunter_agent.global_settings`
- Purpose: allow the owner-only JH-308 cutover command to read the configured Job_Rejections source without shipping personal values in committed settings.
- Boundary: this file is gitignored runtime state and must not ship in desktop builds, packaged defaults, sample data, or public docs with real values.
- The normal runtime does not synchronise this sheet. JH-308 uses it only as bounded migration evidence and writes exact, supported identities to the canonical activity ledger; unresolved evidence stays in the noncanonical historical archive.

### Runtime-local state

- `data/users/`, `data/runtime/`, `output/`, and local auth/runtime DBs are local runtime state, not source material to commit or package.
- Personal spreadsheets, job history, scraped results, and private examples stay outside repo-managed defaults.

## AWS and runtime deployment boundaries

- Canonical AWS setup: [aws-ec2-setup.md](aws-ec2-setup.md)
- Runtime env roots:
  - `JOB_HUNTER_DATA_DIR`
  - `JOB_HUNTER_OUTPUT_DIR`
  - `JOB_HUNTER_DB_PATH`
- Seed/deploy rule: `uv run python -m job_hunter_agent.db_seed` syncs only the approved repo-managed JSON seed manifest. It does not recursively copy arbitrary JSON files from `data/knowledge`.
- Required runtime knowledge includes the managed knowledge JSON plus the O*NET occupation taxonomy JSON files needed at runtime.
- O*NET runtime lookup is local. Network access to `onetcenter.org` is an explicit maintenance/CI refresh action only; job searches do not depend on a live O*NET service.
- The weekly O*NET refresh reads the official database-page metadata, downloads the advertised JSON database, validates/regenerates local reference data, and opens a pull request only when the generated fingerprint changes.
- Boundary: production-only environment files, secrets, service definitions, and mounted data paths must stay out of git and out of packaged defaults.

## LLM and provider boundary

- Current runtime direction: OpenAI-backed structured review and scoring support.
- Product rule: provider-neutral architecture remains the target boundary even if the current implementation uses OpenAI-specific settings and pricing metadata.
- Credential rule: user-owned credentials only. No shared packaged key, no committed private provider token, and no global/team learning side channel.
- Desktop v1 rule still applies: no global keys, no shared learning, no upload without consent.

## Project-management-only integrations

- The shared Google Sheet backlog is project-management infrastructure for implementation tracking, not packaged app functionality.
- Connector/tooling used by coding agents to read or update backlog rows must not be described as an in-product user feature.

## Canonical activity API and external agents

JH-305 exposes one authenticated, per-user activity contract for Job Hunter and
external agents. The API is designed for the deployed AWS HTTPS endpoint; it
does not depend on localhost or Google browser cookies.

- `POST /api/agent-tokens` creates a token from an authenticated dashboard
  session. The plaintext token is returned once; only its hash is stored.
- `GET /api/agent-tokens` lists token metadata, and
  `DELETE /api/agent-tokens/{token_id}` revokes one token.
- Settings -> Notifications -> External plan access provides the dashboard UI
  for creating, copying once, listing, and revoking these tokens without
  exposing token hashes or persisted plaintext.
- External agents send `Authorization: Bearer <token>` to
  `POST /api/activity/events` and `GET /api/activity/jobs/{job_key}`.
  `GET /api/activity/jobs/{job_key}?agent_id=chatgpt` returns same-agent
  presentation state; omitting `agent_id` returns any-agent state.
- `GET /api/activity/employers/{employer_key}` returns the derived employer
  rollup for the authenticated user.
- Activity writes by bearer tokens are bounded per token and UTC minute. The
  default can be changed for deployment with
  `JOB_HUNTER_ACTIVITY_RATE_LIMIT_PER_MINUTE`; a rejected write returns HTTP
  429 and a retry interval.

### External plan-agent read contract (JH-310)

Plan Z, Edge, Remote, and future standalone plan agents read jobs directly
from JMM and keep their own plan analysis/presentation history outside Job
Hunter. Before deciding whether to show a job, a plan can check whether Rob
has already viewed, hidden, applied to, rejected, interviewed for, or
otherwise acted on that exact job by calling the existing
`GET /api/activity/jobs/{job_key}` contract described above.

- `job_key` accepts either JH's own canonical `source:id` key (e.g.
  `seek:94548768`) or JMM's `identity_key` exactly as JMM publishes it (e.g.
  `seek:id:94548768`); both resolve to the same stored activity. No fuzzy
  matching and no plan-specific job key are introduced.
- The response's `activity` object is the same canonical state JH itself
  uses: `viewed`, `hidden`, `applied`, `rejected`, `interview`, `progressed`,
  `no_response`, and `latest_outcome`, plus the underlying `events`.
- Reads are strictly read-only: a plan analysing or presenting a job does not
  create a `presented` or `viewed` event in Job Hunter and does not change
  Job Hunter runtime behaviour. Only Job Hunter's own runtime, or an explicit
  `POST /api/activity/events` call, writes activity.
- Job Hunter stays plan-agnostic: it has no concept of Plan Z, Edge, Remote,
  or any other plan ID, plan policy, plan analysis result, or plan
  decision/reason, and it does not store `found_at`, `analysed_at`, or
  `presented_at`. Standalone plan analysis, decisions, and presentation
  history live only in the separate Career_Search_Agents shared plan-history
  store, never in Job Hunter.

Managed agent IDs are `job_hunter`, `chatgpt`, `claude`, and `manual`. Gmail
and rejection-sheet imports are evidence sources, never agents. The canonical
activity types include append-only reversals: `liked`/`unliked`,
`hidden`/`unhidden`, `applied`/`withdrawn`, `rejected`/`unrejected`, and
`no_response`/`un_no_response`, plus `presented`, `viewed`, `interview`, and
`progressed`. Every event requires a current `source:id` job identity,
`occurred_at`, source, evidence/idempotency data, and authenticated user scope.
Current state is ordered by event time and stable event ID, not request arrival.

`job_activity_events` is the personal source of truth. `job_history`, profile
review lists, and employer outcomes are projections. Old unkeyed
`candidate_application_events` and other history stores remain reconciliation
evidence only; they are not migrated without a trustworthy job identity and
are never written by the JH-305 runtime.

## Related docs

- [INDEX.md](INDEX.md)
- [OPERATIONS.md](OPERATIONS.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SOURCE_REGISTER.md](SOURCE_REGISTER.md)
