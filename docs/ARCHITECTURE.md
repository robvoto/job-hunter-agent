# Job Hunter Agent — Architecture

## System Purpose

Job Hunter is a local-first agentic job filtering system.

The current deployment target is AWS EC2 with a small EBS-backed root volume, so the runtime, storage, and operational choices should be treated as server deployment concerns rather than desktop-only shortcuts.

The system:

* scrapes jobs from multiple sources
* extracts candidate profile support from onboarding and source documents
* filters jobs using deterministic and explainable rules
* ranks jobs using configurable scoring
* preserves uncertain evidence for review
* learns through explicit user approval
* avoids hidden rejection logic

The system is designed as a strict filtering engine, not a generic recommender.

The implementation should remain production-oriented: keep ownership boundaries clear, avoid prototype shortcuts, and prefer explicit runtime contracts over ad hoc behavior.

---

# Job Identification Standard

To prevent "Duplicate Noise" and ensure reliable "History Reuse", all jobs are identified by a **Canonical Job Key**.

Standard format: `source:platform_id` (e.g., `seek:7945621` or `linkedin:39845512`).

*   **Central Authority**: `job_hunter_agent.job_identity.normalize_job_key` is the only function allowed to generate these keys.
*   **Source Normalization**: Scrapers must normalize keys immediately upon ingestion.
*   **Lookup**: The UI and History modules must normalize any incoming identifier (URL or ID) before querying the state store.

---

# Runtime Architecture

## Runtime Layers

| Layer             | Responsibility                                   |
| ----------------- | ------------------------------------------------ |
| Scraping          | Collect raw jobs from SEEK, LinkedIn, APSJobs, and future enabled sources |
| Parsing           | Normalize job structure and extract signals      |
| Candidate Profile | Store runtime candidate profile support and preferences |
| Filtering         | Deterministic rejection and fit gating           |
| Scoring           | Weighted ranking and evidence evaluation         |
| Learning          | Capture candidate-approved learned signals       |
| Review            | Surface uncertain or pending decisions           |
| Security          | Transport-aware session hardening and CSRF       |
| Workspace         | Present explainable ranked jobs                  |
| Settings          | Runtime control surface                          |

State-changing UI actions use `POST` plus CSRF protection. `GET /logout` is not supported.

## Operational warnings

Runtime events are stored in SQLite `system_warnings`. The admin **System health** surface shows only unresolved operational problems by default; routine job-level uncertainties are grouped into an optional, read-only technical-diagnostics drill-down. Supported incidents expose a real operator check, acknowledgement hides only the current occurrence, and recurrence reopens the problem. Debug/audit uncertainty events also write to `output/uncertainty.jsonl`.

---

# Core File Map

| Area | Primary files | Notes |
| --- | --- | --- |
| Candidate profile runtime | `job_hunter_agent/profile_store.py`, `job_hunter_agent/profile_learning.py`, `job_hunter_agent/cv_pipeline.py` | Owns the saved profile, eligibility facts, capability support, and onboarding extraction flow. |
| Fit review and scoring | `job_hunter_agent/llm_gate.py`, `job_hunter_agent/source_learning.py`, `job_hunter_agent/fit_scoring.py`, `job_hunter_agent/capability_matching.py` | Builds LLM prompts, normalizes review payloads, and turns support evidence into explainable scores. |
| Workspace UI | `job_hunter_agent/workspace_renderer.py`, `job_hunter_agent/workspace_service.py`, `templates/results.html` | Renders the shortlist, tabs, cards, filters, and workspace panel state. |
| Settings and shared labels | `job_hunter_agent/server_helpers.py`, `job_hunter_agent/routes/pages.py`, `data/knowledge/ui_labels.json` | Loads centrally managed copy for settings, onboarding, and workspace labels. |
| Runtime I/O and cache files | `job_hunter_agent/io_utils.py`, `job_hunter_agent/run_context.py`, `job_hunter_agent/scrape_finalize.py`, `job_hunter_agent/system_warnings.py` | Loads/saves run state, cache files, workspace outputs, and runtime warning/diagnostic records. |

---

# Core Runtime Components

## Scraping

Primary modules:

* `scrapers/seek_runner.py` — SEEK scrape loop, card review dispatch, parallel detail fetch, result collection
* `scrapers/seek.py` — SEEK low-level page helpers, selectors, URL building, detail payload fetch
* `scrapers/linkedin.py` — LinkedIn via python-jobspy; owns bounded target concurrency, truthful collection-health accounting, and the configurable consecutive-failure circuit breaker
* `scrapers/apsjobs.py` — APSJobs Playwright scraper for government-seeking profiles
* `source_runner.py` — routes enabled sources; checks the persisted per-source discovery snapshot before running a board search; enabled sources run concurrently via `ThreadPoolExecutor` with isolated mutable state per source when more than one source is active; distinguishes worker completion from source health (`healthy`, `partial_failure`, `full_failure`, `stopped`); commits discovery snapshots only for complete successful collections; step-through keeps the run serial for manual inspection; SEEK can pause a visible persistent browser for manual verification when the assisted flag is enabled
* `source_discovery_cache.py` — persists normalized pre-decision source evidence and bounded LinkedIn failure state; it never stores final fit decisions. Failed, partial, stopped, or interrupted collections cannot overwrite a known-good success snapshot.
* `search_plan_state.py` — persists complete per-user/source/signature/location role-query coverage and corroborated deterministic query covers; fresh trusted covers prune redundant LinkedIn and APSJobs targets, while SEEK retains its bounded first-page probes and prunes deeper pagination.
* `source_connector.py` — orchestration entry point

Responsibilities:

* source collection
* normalization
* deduplication preparation
* scrape metadata

The scraper layer does not make business-fit decisions.

### Source publisher metadata contract

* `source_metadata.poster_company` identifies the board-listed publisher/advertiser when the source exposes it.
* `source_metadata.hiring_company` is populated only from an explicit hirer/employer fact; it must not default to the publisher/company profile.
* Publisher industry, company-profile links, ATS/application URLs, and hirer references are factual context, not automatic proof of a direct-employer relationship.
* Posting-channel classification (`direct_employer`, `agency_or_recruiter`, `unknown`) is versioned derived data. Explicit recruiter metadata can decide deterministically; otherwise the LLM interprets the ad and source facts.
* The combined fit review is the first posting-channel pass. An explicit `unknown` triggers one small posting-only LLM judgement using the same managed guidance and source/ad facts, with a profile-independent cache; genuinely ambiguous results may remain `unknown`.
* Stale posting-channel classifications are not reused or displayed as current. Cached detail text may still be reused while obsolete source metadata is discarded.

---

## Candidate Profile Runtime

Primary modules:

* `profile_store.py`
* `profile_learning.py`
* `cv_pipeline.py`

Storage: SQLite `user_profile` table (per user). Accessed via `profile_store.load_profile()` / `save_profile()`.

Responsibilities:

* maintain runtime candidate profile support
* preserve extracted capabilities and explicit eligibility facts
* preserve extracted `role_experience` rows for title-duration evidence
* maintain preference weights
* preserve learning state
* provide scoring context

The runtime profile is authoritative system state.

Source onboarding material is evidence input, not runtime truth.

Raw uploaded CV retention decision:

* uploaded CV files are onboarding input, not long-term user-facing records
* the app imports extracted profile support into the SQLite runtime profile
* raw uploaded CV files must not be treated as canonical matching state
* future application-pack features must ask for or manage source documents explicitly instead of silently relying on old uploaded CV files
* packaged or shared builds must not include a developer's personal CV, profile, job history, scraped jobs, logs, output, runtime DB, or private examples

---

## Filtering Pipeline

Primary modules:

* `filters.py`
* `hard_blocker_rules.py`
* `role_analysis.py`
* `capability_matching.py`
* `signal_detection.py`

Pipeline order:

1. Source normalization
2. Hard blockers
3. Title analysis
4. Capability support matching
5. Description evaluation
6. Competitive-fit analysis
7. LLM constrained review
8. Final score generation

Rules:

* deterministic filters run before LLM review
* hidden rejection logic is forbidden
* weak support should produce review signals instead of silent deletion
* uncertain signals should be preserved where possible

---

# Scoring Architecture

Primary modules:

* `fit_scoring.py`
* `scoring_utils.py`
* `match_labels.py`
* `score_labels.py`

Scoring characteristics:

* weighted
* explainable
* configurable
* support-based
* bounded

The current implemented fit score is intentionally narrow. It uses:

* requirement coverage
* candidate capability support levels
* candidate eligibility facts
* occupation alignment adjustment
* hard blockers

Title analysis, salary, work mode, location, freshness, and similar convenience or preference signals still matter elsewhere in the system, but they are handled as filters, checks, metadata, or separate ranking/display context rather than direct fit-score inputs.

The scoring layer must remain inspectable.

Hidden score budgets and invisible penalties are prohibited.

---

# Learning Architecture

Primary modules:

* `signal_registry.py`
* `review_insights.py`
* `profile_learning.py`

Learning categories:

* capability concepts
* government context
* title normalization
* role-title signals
* hard-blocker patterns

Rules:

* learning requires review approval
* pending learning cannot directly alter runtime filtering
* learning data must remain inspectable
* system-generated suggestions are not trusted automatically

---

# Knowledge Management

Primary knowledge files:

* `data/knowledge/capability_knowledge.json`
* `data/knowledge/hard_blocker_rules.json`
* `data/signals/signal_defaults.json`
* `data/knowledge/scoring_rules.json`
* `data/knowledge/match_level_defaults.json`

Approved and pending learned signals are stored in the SQLite signal registry; `signal_defaults.json` only seeds baseline records.

Rules:

* business judgement belongs in managed knowledge
* avoid sealed hardcoded dictionaries
* preserve explainability
* avoid hidden filtering shortcuts
* avoid legacy compatibility layers unless explicitly required

---

# LLM Architecture

Primary modules:

* `llm_gate.py`
* `user_settings.py`

LLM responsibilities:

* constrained fit review
* onboarding extraction assistance
* evidence interpretation
* capability naming assistance

LLM boundaries:

* deterministic rules run first
* LLM output is constrained
* LLM decisions must remain inspectable
* runtime should survive without LLM access
* LLM should not silently override deterministic blockers

---

# Workspace Architecture

Primary modules:

* `workspace_renderer.py`
* `workspace_data.py`
* `templates/workspace.html`
* `templates/results.html`

Workspace responsibilities:

* ranked shortlist presentation
* explainable decisions
* review visibility
* hidden/applied state management
* filtering visibility
* diagnostics visibility

Workspace sidebar totals are account-scoped and should be read from the same authenticated session bucket that produced the latest run. A zeroed sidebar after a successful scrape usually means the request or run context resolved a different account scope, not that the scrape found nothing.

The workspace is a persistent operational workspace.

---

# Settings Architecture

Primary template:

* `templates/settings.html`

Current sections:

* Search
* Profile
* Capability Matrix
* Rules
* Messaging
* Learning
* Optimise

## Optimise Section

`Optimise` is an internal runtime tuning area.

Purpose:

* diagnostics
* runtime analysis
* ranking inspection
* review tooling
* experimental controls
* highlight tuning
* scrape analysis

It is not intended for normal end-user preferences.

---

# Data Authority Model

| Data Type                     | Authority Level                     |
| ----------------------------- | ----------------------------------- |
| DB `user_profile` table       | Runtime candidate truth             |
| DB `job_history` table        | Persistent job state and dedup      |
| DB `run_stats`, `audit_records`, `review_data`, `workspace_pool` tables | Scrape run outputs (disposable) |
| Account-scoped workspace output | Rendered workspace output |
| Knowledge JSON files          | Approved runtime business knowledge |
| Signal registry pending items | Review-only                         |
| `data/runtime/` files         | Disposable runtime output (costs, cache) |

---

# Runtime Constraints

The system must:

* avoid silent false negatives
* preserve explainability
* preserve inspectability
* prefer review over deletion
* remain locally operable
* protect DB state from write corruption during concurrent operations (SQLite WAL mode)
* separate runtime truth from onboarding evidence
* enforce secure session management (HTTPS) when exposed to a network

The system must not:

* hide rejection logic
* hardcode invisible business judgement
* silently discard extracted evidence
* use opaque scoring shortcuts
* allow unapproved learning to alter runtime behaviour

---

# Current Technical Stack

| Technology         | Responsibility                  |
| ------------------ | ------------------------------- |
| Python             | Core runtime                    |
| FastAPI            | Local server and APIs           |
| Playwright         | SEEK scraping                   |
| python-jobspy      | LinkedIn ingestion              |
| OpenAI API         | Optional constrained LLM review |
| SQLite (WAL mode) | Per-user state and run output persistence |
| JSON files (`data/knowledge/`, `data/config/`) | Approved business knowledge and seed defaults |
| HTML/CSS/JS        | Workspace and settings UI       |

---

# Expansion Direction

Future expansion areas:

* autonomous orchestration
* OpenClaw runtime integration
* application generation workflows
* review-driven adaptive tuning
* managed external knowledge systems
* multi-agent coordination
* runtime diagnostics agents

Expansion must preserve:

* explainability
* deterministic reviewability
* inspectable learning
* runtime transparency


## Current fit-review architecture note 2026-06-02

The current fit review has two layers. The LLM returns a holistic decision/grade plus contextual capability matches and job requirements. The scoring layer then consumes those stored fields. Capability matches are credited only when they match exact candidate capability names and have a configured credit confidence.

As of 2026-07-21, explicit duration requirements such as "5+ years as Business Analyst" also compare the reviewed requirement text against stored onboarding `role_experience` rows. This does not add a new hidden score. Instead, it tightens `requirement_coverage` evidence: a row can be downgraded from `supported` to `partially_supported` when the runtime profile cannot prove the required role-duration threshold from saved title-duration evidence.

Ongoing architecture direction: required job requirements should become the main scoring spine. Candidate capabilities should be used as evidence to prove those requirements. The current implementation is not fully requirement-coverage-driven yet.

O*NET is used as a conservative occupation-family helper. Runtime lookup is local against a generated index built from the current full O*NET Job Titles data. Candidate occupation context is derived from the current user-selected `target_roles` and `also_consider_roles`; CV extraction can provide transient role suggestions for review but cannot create future job-search intent. Rebuilding a profile preserves confirmed role selections until the final review confirmation explicitly replaces them. Ambiguous real-world aliases cannot silently widen the candidate's target occupation family. Uncertain O*NET results continue to title-LLM/detail review rather than rejecting the job.

Taxonomy matching applies the same candidate-code rule to exact and embedded title phrases: all codes outside the target set can classify `far`; all inside can classify `near`; mixed codes, missing target context, or unresolved titles remain `uncertain`. Generic one-word job-title aliases are not used as decisive embedded matches. Generated taxonomy metadata tracks the O*NET database release and dataset fingerprint so cache rows from older data cannot be reused. See `docs/OCCUPATION_TAXONOMY_RATIONALE.md`.
