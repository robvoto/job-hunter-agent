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
| Scraping          | Collect raw jobs from SEEK and LinkedIn          |
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

---

# Core Runtime Components

## Scraping

Primary modules:

* `scrapers/seek_runner.py` — SEEK scrape loop, card review dispatch, parallel detail fetch, result collection
* `scrapers/seek.py` — SEEK low-level page helpers, selectors, URL building, detail payload fetch
* `scrapers/linkedin.py` — LinkedIn via python-jobspy
* `source_runner.py` — routes enabled sources; when both SEEK and LinkedIn are enabled they run concurrently via `ThreadPoolExecutor(max_workers=2)` with isolated mutable state per source
* `source_connector.py` — orchestration entry point

Responsibilities:

* source collection
* normalization
* deduplication preparation
* scrape metadata

The scraper layer does not make business-fit decisions.

---

## Candidate Profile Runtime

Primary modules:

* `profile_store.py`
* `profile_learning.py`
* `cv_pipeline.py`

Storage: SQLite `user_profile` table (per user). Accessed via `profile_store.load_profile()` / `save_profile()`.

Responsibilities:

* maintain runtime candidate profile support
* preserve extracted capabilities
* maintain preference weights
* preserve learning state
* provide scoring context

The runtime profile is authoritative system state.

Source onboarding material is evidence input, not runtime truth.

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

Scoring inputs include:

* title alignment
* capability support
* profile support tiers
* description quality
* competitive fit
* salary alignment
* work mode
* location preference
* government context
* freshness

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
* `data/knowledge/role_title_knowledge.json`
* `data/signals/signal_registry.json`
* `data/knowledge/scoring_rules.json`
* `data/knowledge/match_level_defaults.json`

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
* `agent_settings.py`

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
* `workspace.html`

Workspace responsibilities:

* ranked shortlist presentation
* explainable decisions
* review visibility
* hidden/applied state management
* filtering visibility
* diagnostics visibility

Workspace sidebar totals are user-scoped and should be read from the same active user bucket that produced the latest run. A zeroed sidebar after a successful scrape usually means the request or run context resolved a different user id, not that the scrape found nothing.

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
* Alerts & AI
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
| `data/users/<user_id>/workspace_results.html` | Rendered workspace output |
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

Ongoing architecture direction: mandatory job requirements should become the main scoring spine. Candidate capabilities should be used as evidence to prove those requirements. The current implementation is not fully requirement-coverage-driven yet.

O*NET is used as a conservative occupation-family helper. It uses onboarding-generated target_occupation_queries to derive target occupation codes. Uncertain O*NET results continue to detail/LLM review rather than rejecting the job.

Taxonomy matching must not discard useful embedded phrase evidence just because one phrase maps to multiple O*NET codes. If all candidate occupation codes for an embedded phrase are outside the candidate target occupation set, the title may be classified as `far`. If candidate codes are mixed, missing, or target context is unavailable, the result remains `uncertain`. See `docs/OCCUPATION_TAXONOMY_RATIONALE.md`.
