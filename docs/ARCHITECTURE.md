# Job Hunter Agent — Architecture

## System Purpose

Job Hunter is a local-first agentic job filtering system.

The system:

* scrapes jobs from multiple sources
* extracts candidate evidence from onboarding and source documents
* filters jobs using deterministic and explainable rules
* ranks jobs using configurable scoring
* preserves uncertain evidence for review
* learns through explicit user approval
* avoids hidden rejection logic

The system is designed as a strict filtering engine, not a generic recommender.

---

# Runtime Architecture

## Runtime Layers

| Layer             | Responsibility                                   |
| ----------------- | ------------------------------------------------ |
| Scraping          | Collect raw jobs from SEEK and LinkedIn          |
| Parsing           | Normalize job structure and extract signals      |
| Candidate Profile | Store runtime candidate evidence and preferences |
| Filtering         | Deterministic rejection and fit gating           |
| Scoring           | Weighted ranking and evidence evaluation         |
| Learning          | Capture candidate-approved learned signals       |
| Review            | Surface uncertain or pending decisions           |
| Security          | Dynamic session hardening and transport safety   |
| Dashboard         | Present explainable ranked jobs                  |
| Settings          | Runtime control surface                          |

---

# Core Runtime Components

## Scraping

Primary modules:

* `scrapers/seek.py`
* `scrapers/linkedin.py`
* `source_connector.py`

Responsibilities:

* source collection
* normalization
* deduplication preparation
* scrape metadata

The scraper layer does not make business-fit decisions.

---

## Candidate Profile Runtime

Primary files:

* `data/profile.json`
* `profile_store.py`
* `profile_learning.py`
* `cv_pipeline.py`

Responsibilities:

* maintain runtime candidate evidence
* preserve extracted capabilities
* maintain preference weights
* preserve learning state
* provide scoring context
* ensure data integrity during concurrent background updates (atomic writes/locking)

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
4. Capability evidence matching
5. Description evaluation
6. Competitive-fit analysis
7. LLM constrained review
8. Final score generation

Rules:

* deterministic filters run before LLM review
* hidden rejection logic is forbidden
* weak evidence should produce review signals instead of silent deletion
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
* evidence-based
* bounded

Scoring inputs include:

* title alignment
* capability evidence
* profile evidence tiers
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

* `capability_knowledge.json`
* `hard_blocker_rules.json`
* `role_title_knowledge.json`
* `signal_registry.json`
* `scoring_rules.json`
* `match_level_defaults.json`

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

# Dashboard Architecture

Primary modules:

* `dashboard_renderer.py`
* `dashboard_data.py`
* `workspace.html`

Dashboard responsibilities:

* ranked shortlist presentation
* explainable decisions
* review visibility
* hidden/applied state management
* filtering visibility
* diagnostics visibility

The dashboard is a persistent operational workspace.

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
| `data/profile.json`           | Runtime candidate truth             |
| Knowledge JSON files          | Approved runtime business knowledge |
| Signal registry pending items | Review-only                         |
| `output/` files               | Disposable runtime output           |
| Dashboard state/history       | Persistent operational state        |

---

# Runtime Constraints

The system must:

* avoid silent false negatives
* preserve explainability
* preserve inspectability
* prefer review over deletion
* remain locally operable
* protect local state (JSON) from write corruption during concurrent operations
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
| JSON runtime files | State and knowledge persistence |
| HTML/CSS/JS        | Dashboard and settings UI       |

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
