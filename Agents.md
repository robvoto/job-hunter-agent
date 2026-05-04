# Job Hunter Agent — AI Context

> Generic AI context file. Works with Claude Code, Codex, Cursor, and other AI coding tools.
> Keep this file short. Deep context lives in `docs/` and `.skills/`.

## What this project does
Local-first job discovery: scrape SEEK + LinkedIn → deterministic filters → optional LLM → fit score → local dashboard.
Runtime source of truth: `data/profile.json`. Main entry point: `source_connector.py`.

## Run commands
| Task | Command |
|------|---------|
| Scrape + build dashboard | `python -m job_hunter_agent.source_connector` |
| Rebuild dashboard only | `python -m job_hunter_agent.source_connector --rebuild-dashboard` |
| Local web UI | `python -m job_hunter_agent.local_server` |
| Daily agent | `python -m job_hunter_agent.agent_runner` |
| Tests | `python -m pytest` |

See `docs/RUN_COMMANDS.txt` for full flag reference.

## Code map

### Orchestration
| File | Purpose |
|------|---------|
| `source_connector.py` | Entry: scrape → filter → score → write dashboard |
| `local_server.py` | Web UI server (settings, dashboard, onboarding) |
| `agent_runner.py` | Scheduled daily runner + notifiers |
| `dashboard_data.py` | Historical dashboard record sets |

### Filtering & scoring
| File | Purpose |
|------|---------|
| `filters.py` | Deterministic title + content filters |
| `fit_scoring.py` | `fit_score()`, `fit_score_breakdown()`, `build_fit_highlights()` |
| `capability_matching.py` | Profile capability matching against job text |
| `signal_detection.py` | Competitive signals + hard blocker detection |
| `preferences.py` | Location, contract, government, salary preferences |
| `score_labels.py` | Score display labels and badge HTML |

### Profile & knowledge
| File | Purpose |
|------|---------|
| `profile_store.py` | Load `data/profile.json`, scoring rules, weights |
| `profile_learning.py` | Free-text → structured profile updates |
| `cv_pipeline.py` | CV parsing and capability clustering |
| `capability_matrix.py` | Capability matrix building + scoring |
| `capability_knowledge.py` | JSON-backed capability rules module |
| `hard_blocker_rules.py` | JSON-backed hard blocker patterns |
| `role_title_knowledge.py` | JSON-backed role title token patterns |
| `signal_registry.py` | Learning inbox: surfaced patterns awaiting user approval |

### Supporting modules
| File | Purpose |
|------|---------|
| `paths.py` | All file paths — single source of truth |
| `io_utils.py` | JSON I/O and file helpers |
| `history.py` | Job view/keep/apply history + `viewed_by_user()` |
| `posting_utils.py` | Timestamp parsing, job key normalisation |
| `job_identity.py` | Cross-source deduplication |
| `description_trust.py` | Full-description confidence (`HIGH`/`LOW`) |
| `scoring_utils.py` | `weighted_points()`, source text builder |
| `text_processing.py` | `compact_whitespace()`, `dedupe_preserve_order()`, etc. |
| `role_analysis.py` | Government context, sector inference, posting channel |
| `salary_utils.py` | Salary parsing and comparison |
| `match_labels.py` | Score bands from `data/match_level_defaults.json` |

### Scrapers
| File | Purpose |
|------|---------|
| `scrapers/seek.py` | SEEK card + detail page scraping |
| `scrapers/linkedin.py` | LinkedIn via python-jobspy |

### Key data files
| File | Purpose |
|------|---------|
| `data/profile.json` | Runtime candidate profile (never discard) |
| `data/capability_knowledge.json` | Managed capability rules + aliases |
| `data/hard_blocker_rules.json` | Managed hard blocker patterns |
| `data/role_title_knowledge.json` | Managed role title token patterns |
| `data/signal_registry.json` | Learned signals awaiting review |
| `data/match_level_defaults.json` | Score band thresholds (configurable) |

## Domain skills — load before deep work
`.skills/` holds focused context for each domain. Read the relevant skill before editing that area.

| Skill | When to use |
|-------|-------------|
| `.skills/job-filtering/SKILL.md` | Editing filters, reject reasons, content rules |
| `.skills/scoring-ranking/SKILL.md` | Editing fit score, capability evidence, match bands |
| `.skills/scraping/SKILL.md` | Editing SEEK/LinkedIn scrapers, data shape |
| `.skills/profile-extraction/SKILL.md` | Editing CV pipeline, capability clustering, profile building |
| `.skills/signal-registry/SKILL.md` | Editing signal registry, learning flow, signal approval |
| `.skills/history-dedup/SKILL.md` | Editing job history, deduplication, posting timestamps |
| `.skills/preferences/SKILL.md` | Editing location, salary, contract, government preferences |
| `.skills/knowledge-management/SKILL.md` | Editing capability/blocker/title knowledge JSONs, paths |
| `.skills/dashboard-ui/SKILL.md` | Editing local server, dashboard data, score badges |
| `.skills/text-utilities/SKILL.md` | Editing text normalisation, scoring utils, description trust |

## Architecture in one line
```
scrape → title filter → content filter → [LLM] → fit_score() → dashboard HTML
                  ↑ all driven by data/profile.json + knowledge JSONs
```
Full design: `docs/ARCHITECTURE.md`

## Non-negotiable rules
1. **Deterministic first.** Title + content filters run before any LLM call. Never swap them out.
2. **Knowledge-managed.** Business rules live in JSON-backed modules — not Python constants. Don't hardcode.
3. **No false-negative rejection.** Only hard-block for explicit blockers (work rights, mandatory clearance/cert). Everything else scores down and stays visible.
4. **Preserve signals.** Weak/uncertain signals get `needs_review: true`, not silent deletion.
5. **Explainable.** Every keep/reject must have a visible reason.
6. **Minimal changes.** Touch only what the task requires. Don't refactor unrelated code.
7. **User-controlled learning.** Learning flows through the signal registry. Don't embed learned behaviour into filters.
8. **Protect `data/profile.json`.** Never treat it as disposable or regenerate it silently.
9. **No pane-based SEEK scraping.** Direct job pages only.
10. **Check `BACKLOG.md`** before starting any new feature.
