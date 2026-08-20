# Job Hunter Agent

Job Hunter is a local-first job discovery and fit-evaluation system. It builds a structured candidate profile, collects jobs from configured sources, applies deterministic eligibility and fit rules, explains its decisions, and preserves uncertain cases for human review.

## Why this project exists

Job boards optimise for showing more listings, not for making defensible candidate decisions. The result is duplicated roles, stale advertisements, weak keyword matches, and unexplained recommendations.

Job Hunter is designed as a strict but fair decision system:

- reject only when an explicit rule or blocker is supported;
- distinguish missing evidence from confirmed mismatch;
- show why a job was kept, rejected, or marked for review;
- learn only through approved user feedback;
- keep candidate data and runtime state under the user's control.

## Current status

Active development with a working web application and AWS deployment path.

Current supported job sources:

- SEEK
- LinkedIn
- APSJobs

The connector architecture is designed to support additional sources without moving source-specific behaviour into the scoring layer.

See [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) for the boundary between implemented, configuration-dependent, and planned capabilities.

## Decision pipeline

```text
Candidate onboarding
        │
        ▼
Structured runtime profile
        │
        ├──────────────┐
        ▼              ▼
Job collection     User preferences
        │              │
        └──────┬───────┘
               ▼
     Normalisation and deduplication
               ▼
     Deterministic hard blockers
               ▼
     Capability and eligibility evidence
               ▼
     Constrained fit review and scoring
               ▼
     Explained keep / review / reject decision
               ▼
     User feedback and approved learning
```

## Implemented capabilities

- guided onboarding from `.docx` or plain-text source material;
- structured candidate profile stored in SQLite;
- configurable role, location, work-mode, sector, salary, and source preferences;
- deterministic hard blockers before probabilistic review;
- capability, eligibility, and requirement evidence tracking;
- explainable bounded fit scores;
- separate potential, applied, and hidden job states;
- explicit review and approval before learned signals affect behaviour;
- local workspace, settings, and administration interfaces;
- daily-agent execution and local digest generation;
- email and Telegram delivery when configured.

## Architecture principles

- **Deterministic before probabilistic** — hard rules and explicit evidence run before any LLM-assisted review.
- **No hidden rejection logic** — every negative decision must be traceable.
- **Profile state is authoritative** — onboarding documents are evidence inputs, not silently retained matching truth.
- **Uncertainty is preserved** — weak evidence becomes a review signal rather than an invisible rejection.
- **Learning requires approval** — generated suggestions cannot directly alter filtering.
- **Local-first privacy** — user profiles, job history, logs, and runtime databases are not packaged or committed.

## Technology

- Python 3.12+
- FastAPI and uvicorn
- Playwright
- `python-jobspy`
- SQLite
- HTML, CSS, and JavaScript templates
- `python-docx` and pandas
- optional OpenAI-assisted review, subject to runtime configuration and privacy rules

## Repository structure

```text
.
├── job_hunter_agent/          # Application, filtering, scoring, and runtime services
│   └── scrapers/              # Source-specific connectors
├── templates/                 # Server-rendered UI templates
│   └── static/                # Frontend assets
├── data/                      # Managed defaults and knowledge data
├── tests/                     # Unit, integration, and browser tests
├── docs/                      # Architecture, operations, user, and integration documentation
└── installer/                 # Desktop packaging source; generated build output is ignored
```

## Run and operate

Setup and runtime commands are maintained in one place to avoid contradictory instructions:

- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) — product use and profile concepts
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — setup, execution, recovery, and validation
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) — development workflow and repository boundaries

## Documentation

- [docs/INDEX.md](docs/INDEX.md)
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)

## Data and security

The repository excludes developer profiles, uploaded CV files, per-user runtime state, scraped payloads, logs, output, browser profiles, databases, credentials, and installer build artefacts. Network deployment requires the session, CSRF, HTTPS, and reverse-proxy controls documented in the operational guidance.

## Licence

Copyright © 2026 Roberto Hernan Voto. All rights reserved.

This project is proprietary software. No permission is granted to copy, modify, distribute, sublicense, commercialise, or create derivative works from the current repository without prior written permission from the copyright owner. See [`LICENSE`](LICENSE) for the full terms.

Versions lawfully obtained while this project was distributed under the MIT License remain subject to the rights granted for those copies under that licence.
