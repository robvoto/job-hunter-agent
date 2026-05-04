# Architecture — Job Hunter Agent

> Deep design context. Not always loaded. Referenced by `CLAUDE.md`.
> Last updated: May 2026.

---

## What this project is

A local-first job-hunting system. The candidate gives the app strong source material (CV, STAR notes), the app builds a working profile, reviews jobs against that profile, and keeps a meaningful shortlist instead of forcing the user to search manually every day.

**Near-term goal:** reliably scrape and filter target roles from a configurable candidate profile, learn the candidate profile over time, produce a clean shortlist with clear reject reasons.

**Long-term goal:** become a true autonomous job agent that runs daily and sends only meaningful matches.

---

## Current stage — Stage 2

Past the prototype. Actively transitioning from hardcoded business logic toward a JSON-backed knowledge management system.

### What works
- SEEK direct-page scraping + LinkedIn via python-jobspy
- Deterministic filtering before any LLM call
- LLM fallback constrained to `KEEP`, `REJECT`, `MAYBE` — cached in `data/llm_cache.json`
- Runtime profile persisted in `data/profile.json`; source documents importable via the admin UI
- Persistent dashboard with history, archive, hidden review, score/age/work-mode filters, pagination
- Viewed/applied/hidden jobs tracked locally
- Signal registry for surfacing and approving learned patterns
- Cross-source deduplication (`job_identity.py`)
- All paths centralised in `paths.py`
- Knowledge modules: capability, hard blocker, role title — all JSON-backed

### What is still incomplete
- Not yet a true scheduled agent (scheduling is in Stage 3)
- No WhatsApp delivery
- No authenticated SEEK session reuse
- No durable cloud persistence
- Filtering still needs ongoing tuning
- No application-pack workflow (tailored CVs, cover letters, criteria responses)
- Many hardcoded judgment items remain (tracked in `docs/HARD_CODED_JUDGEMENT_BACKLOG.md`)

---

## Product model

| Layer | Source |
|-------|--------|
| Human truth | Source documents (CV, STAR notes) |
| Runtime machine truth | `data/profile.json` |
| Control surface | Settings UI (`local_server.py`) |
| Rule layer | Knowledge JSON files under `data/` |
| Generated outputs | `output/` (disposable, can be recreated) |

**Intended onboarding flow:**
1. Import one strong detailed CV
2. Optionally import richer evidence (STAR notes, long-form experience)
3. Generate distilled runtime profile in `data/profile.json`
4. Maintain and refine from the settings UI
5. Use that profile for scraping, filtering, LLM review, and later application generation

`data/profile.json` is not meant to be hand-authored from scratch — it should be generated from source documents, then edited incrementally.

---

## Architecture decisions

### SEEK: direct job pages (not the right-hand pane)
The detail pane was flaky and inconsistently captured. Direct job pages are the only approved approach. **Do not revert to pane-based scraping.**

### Knowledge-managed over hardcoded
Business rules are being systematically migrated from sealed Python constants into JSON-backed knowledge modules:

| Module | JSON file |
|--------|-----------|
| `capability_knowledge.py` | `data/capability_knowledge.json` |
| `hard_blocker_rules.py` | `data/hard_blocker_rules.json` |
| `role_title_knowledge.py` | `data/role_title_knowledge.json` |
| `signal_registry.py` | `data/signal_registry.json` |

**Do not revert knowledge rules to hardcoded constants.**

### Scoring model
Fit score is a 0–100 integer built as a weighted sum. Weights are per category and configurable via `data/profile.json` (`preference_weights`). Points are computed via `weighted_points(raw, weight)` in `scoring_utils.py`.

| Component | Range | Weight category |
|-----------|-------|-----------------|
| Title signal (direct / secondary) | 0–15 | `fit` |
| LLM description grade | −8–25 | `fit` |
| Content filter pass | 0–3 | `fit` |
| Full description confidence penalty | 0 or −8 | `fit` |
| Capability evidence score | 0–20 | `fit` |
| Convergence bonus | 0, 3, or 5 | `fit` |
| Competitive signal adjustments | variable | `fit` |
| Freshness | 0–10 | `freshness` |
| Location preference | −5–8 | `location` |
| Contract preference | −5–10 | `contract` |
| Government preference | 0–4 | `government` |
| Work mode | −2–5 | `work_mode` |
| Salary signal | −5–7 | `salary` |
| Already viewed penalty | −3 | unweighted |

Full rationale: `docs/SCORING_RATIONALE.md`.

**Capability evidence score** is the evidence-based component. For each matching capability rule:
```
combined     = max(rule_strength, evidence_tier_alignment_score)
contribution = combined × fit_weight  # 4 for core, 2 for supporting
```
`evidence_tier_alignment_score` is computed from the candidate's profile text — recency, role coverage, and alias density.

**Match score bands** are loaded from `data/match_level_defaults.json` via `match_labels.py` (not hardcoded):

| Band | Default score |
|------|---------------|
| Strong match | 85–100 |
| Good match | 70–84 |
| Possible fit | 55–69 |
| Stretch | 0–54 |

### LLM model
The LLM is optional and constrained.

- Title filters run first → content filters second → only surviving jobs reach LLM
- LLM sees job detail text + profile context from `data/profile.json`
- Response limited to `KEEP`, `REJECT`, `MAYBE`; cached in `data/llm_cache.json`
- If `OPENAI_API_KEY` is missing → falls back to `MAYBE`
- Current provider: OpenAI (`gpt-4o-mini` for cheap pass, `gpt-4o` configurable)
- Titles are a cheap first pass; the real fit decision is driven by description evidence + profile fit

Profile inputs used by the LLM prompt: candidate fit brief, capability profile rules, match preferences, evidence tiers.

### Dashboard model
The dashboard is a persistent local workspace, not a throwaway report.

- Served via `workspace.html` at `http://127.0.0.1:8765/dashboard`
- Multi-view: Potential Jobs, Applied, Hidden Jobs
- Fresh kept jobs first; previously kept jobs stay visible in saved sections
- Filters: sort, scope, posted age, work mode, score, pagination
- `dashboard_data.py` handles data transformation separately from the scraper
- `history.py` tracks per-job view/keep/apply state

---

## Settings UI

Served by `local_server.py`. Templates under `templates/`.

| Tab | Purpose |
|-----|---------|
| Search | What SEEK/LinkedIn gets asked for |
| Candidate Profile | CV text, capability matrix, title/description rules |
| Review | Applied/hidden controls, unknown skill decisions |
| Signal Registry | Approve patterns surfaced during scraping |
| Test | Latest run stats and rejected samples |

Important: signal registry decisions and skill decisions do nothing until explicitly applied.

---

## Persistence rules

| Category | Treatment |
|----------|-----------|
| `data/profile.json`, `data/job_history.json`, `data/*.json` knowledge files | Valuable local state — never discard |
| `output/` | Disposable — recreatable from a fresh run |
| `data/llm_cache.json`, `data/agent_settings.json` | Local-only, never commit |

All paths resolved via `paths.py` relative to the repo root.

---

## Tech stack

| Tech | Role |
|------|------|
| Python 3.11+ | Core language |
| Playwright | Browser automation for SEEK |
| python-jobspy | LinkedIn and multi-board scraping |
| OpenAI API | Optional LLM review (gpt-4o-mini / gpt-4o) |
| python-docx | CV and document parsing |
| pandas | Data manipulation |
| requests | Notifications and external APIs |
| python-dotenv | Environment variable management |
| Local HTML/JS | Settings UI backed by Python `http.server` |
| JSON files | All runtime state and knowledge |

---

## Design principles

1. Deterministic first. Rules before LLM, always.
2. LLM constrained. Output must stay `KEEP`, `REJECT`, or `MAYBE`.
3. Cost-aware. Cache responses, minimise prompt size, use LLM only when needed.
4. Explainable. A reject should have a visible reason whenever possible.
5. Local-first. Runs on a personal machine without cloud infrastructure.
6. Learnable. Gets better through explicit user feedback, not hidden magic.
7. Maintainable. Important runtime state lives in files, not buried in code.
8. Knowledge-managed. Business rules belong in JSON-backed modules.

---

## Parked decisions

### `star_evidence_text` — parked April 2026
- Field exists in `data/profile.json` and is populated by onboarding/import.
- Removed from admin UI and excluded from LLM fit-scoring prompt.
- Reason: adds prompt tokens without improving KEEP/REJECT/MAYBE decisions. Evidence tiers already carry the CV substance.
- Where it belongs: application generation (cover letters, criteria responses). Build that feature first, then re-expose.
- See comments in `llm_gate.py` → `build_profile_prompt_context()` and `local_server.py`.

---

## Roadmap

### Stage 2 — Reliable data pipeline
- [x] Direct-page SEEK scraping
- [x] Structured HTML + JSON output, run stats, reject review data
- [x] Local admin UI
- [x] Profile persistence and learning loop
- [x] Persistent dashboard with archive and hidden review
- [x] Source-document import from CV and STAR material
- [x] Configurable match bands and rejection rule categories
- [x] Knowledge-managed capability, hard blocker, and role title modules
- [x] Signal registry for reviewing and approving learned patterns
- [x] Cross-source deduplication (`job_identity.py`)
- [x] Centralised paths (`paths.py`)
- [x] Workspace multi-view dashboard (`workspace.html`)
- [ ] Improve title/content filtering quality
- [ ] Better extraction for hidden/collapsed job requirements
- [ ] Migrate remaining hardcoded judgment items (see `docs/HARD_CODED_JUDGEMENT_BACKLOG.md`)

### Stage 3 — Real job agent
- [ ] Scheduling and message delivery
- [ ] Application feedback loop + application-pack workflow
- [ ] Durable cloud storage
- [ ] OpenClaw / agent runtime integration (see `BACKLOG.md`)
