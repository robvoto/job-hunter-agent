# Skill: Scoring & Ranking

Read this before editing `fit_scoring.py`, `capability_matching.py`, `signal_detection.py`, `score_labels.py`, or `match_labels.py`.

## Scoring pipeline order

```
fit_score(record)
  └─ fit_score_breakdown(record)          # assembles all score entries
       ├─ llm_description_fit_entry()     # LLM grade → points (if present)
       ├─ capability_evidence_score()     # capability rules → points + evidence
       │    └─ capability_scored_matches()  # per-rule match scoring
       ├─ convergence_bonus_entry()       # bonus when LLM + capabilities agree
       ├─ competitive_signal_breakdown()  # competitive signals → penalty/boost entries
       └─ [preference entries]            # salary, location, work_mode, etc. via weighted_points()
```

`fit_score()` returns a single integer. `fit_score_breakdown()` returns a list of entry dicts (each with `label`, `points`, `weight`, `detail`). `build_fit_highlights()` returns human-readable strings for the dashboard card.

## Key functions

| Function | File | What it does |
|---|---|---|
| `fit_score(record, profile=None)` | `fit_scoring.py` | Final integer score |
| `fit_score_breakdown(record, profile=None)` | `fit_scoring.py` | List of scored entry dicts |
| `build_fit_highlights(record, details_text, profile=None)` | `fit_scoring.py` | List of highlight strings for UI |
| `capability_evidence_score(record, profile=None)` | `fit_scoring.py` | `(score_int, evidence_dict)` |
| `capability_scored_matches(source_text, profile)` | `fit_scoring.py` | Per-capability rule match list |
| `convergence_bonus_entry(record, ...)` | `fit_scoring.py` | Convergence bonus dict or None |
| `find_profile_capability_matches(details_text, profile)` | `capability_matching.py` | `{"core": [...], "supporting": [...], ...}` |
| `evidence_tier_alignment_score(profile, aliases)` | `capability_matching.py` | Float 0–1 based on recency tier |
| `hard_block_reasons(record, profile=None)` | `signal_detection.py` | List of hard blocker strings |
| `competitive_signal_assessments(record, profile=None)` | `signal_detection.py` | List of signal assessment dicts |
| `competitive_fit_highlights(record, profile=None)` | `signal_detection.py` | List of highlight strings for competitive signals |
| `_capability_rule_strength(rule)` | `signal_detection.py` | Float 0–1 from rule.level |

## LLM grade → points mapping

```python
grade_map = {
    "strong_fit":    ("Strong fit",    100),
    "good_fit":      ("Good fit",       80),
    "possible_fit":  ("Possible fit",   55),
    "weak_fit":      ("Weak fit",       30),
    "poor_fit":      ("Poor fit",       10),
    "no_fit":        ("No fit",          0),
}
```

Stored in `record["llm_fit_grade"]`. Fallback legacy keys: `KEEP` → `good_fit`, `MAYBE` → `possible_fit`, `REJECT` → `no_fit`.

## Capability match categories

`find_profile_capability_matches()` returns a dict with these keys:
- `"core"` — rules with level=strong in primary evidence tier
- `"supporting"` — rules with level=working/basic
- `"strong"` / `"working"` / `"basic"` / `"limited_depth"` — by rule level
- `"must_not"` — matched a must-not-require rule (negative signal)

## Evidence tier weights (recency)

Loaded from `profile["evidence_tier_weights"]` via `get_evidence_tier_weights(profile)`:
| Tier | Default weight |
|---|---|
| `primary_current_evidence` | 1.0 |
| `secondary_older_evidence` | 0.55 |
| `background_optional_evidence` | 0.25 |

Recency multiplier inside `capability_matching.py`: 0–5 yr = 1.0, 5–10 yr = 0.6, 10+ yr = 0.3.

## Capability rule strength levels

| Level string | Float |
|---|---|
| `"strong"` | 1.0 |
| `"working"` | 0.72 |
| `"basic"` | 0.55 |
| `"low"` | 0.22 |
| (other/missing) | 0.45 |

## Score entry dict shape

Each entry in `fit_score_breakdown()`:
```python
{
    "label": str,       # human-readable label
    "points": int,      # raw points contribution
    "weight": float,    # from preference weights
    "detail": str,      # optional extra context
    "source": str,      # "llm" | "capability" | "convergence" | "competitive" | "preference"
}
```

## Match bands

Loaded from `data/match_level_defaults.json` via `match_labels.py`. Configurable thresholds — do not hardcode score band numbers in Python. Use `get_match_levels(profile)` or `score_labels.py` functions.

## Convergence bonus

Applied when LLM grade ≥ `possible_fit` AND capability evidence score ≥ threshold (from `profile["scoring_rules"]["convergence"]`). Reward for both signals agreeing.

## Competitive signals

`detect_competitive_signals()` checks `profile["dominant_signal_clusters"]`. A signal fires when:
- ≥1 alias matched in source text
- `snippet_hits` ≥ `min_snippet_hits` (default 2)

`evaluate_competitive_signal_alignment()` returns `fit` / `watchout` / `risk` assessment per signal.

## Scoring rules config keys in `profile.json`

```json
{
  "scoring_rules": {
    "llm_grade_points": {...},        // override grade_map
    "convergence": { "threshold": 60, "bonus": 15 },
    "fit_breakdown": { ... },
    "freshness": { ... },
    "work_mode": { ... }
  },
  "preference_weights": {
    "fit": 1.0, "salary": 1.0, "location": 1.0,
    "work_mode": 1.0, "contract": 1.0, "government": 1.0, "freshness": 1.0
  },
  "evidence_tier_weights": {
    "primary_current_evidence": 1.0,
    "secondary_older_evidence": 0.55,
    "background_optional_evidence": 0.25
  }
}
```

## Common gotchas

- `build_fit_highlights` must stay in `fit_scoring.py` — it calls `competitive_fit_highlights` from `signal_detection.py`, which imports from `capability_matching.py`. Putting it in `capability_matching.py` would create a circular import.
- `viewed_by_user()` lives in `history.py` (not `source_connector.py`) so `fit_scoring.py` can import it without a cycle.
- `hard_block_reasons()` returns strings, not dicts. `hard_block_entries()` returns dicts with `blocker_type`.
- Score is always an integer; `fit_score()` rounds before returning.
- Never bypass hard blockers to increase score. Rule 3 in AGENTS.md: false-negative rejection is forbidden; hard blocking is only for explicit blockers.

## Related files

| File | Role |
|---|---|
| `fit_scoring.py` | Score assembly, entry building, highlights |
| `capability_matching.py` | Capability rule matching, tier alignment |
| `signal_detection.py` | Competitive signals, hard blockers, skill learning |
| `score_labels.py` | Score display labels, badge HTML |
| `match_labels.py` | Score band thresholds from JSON |
| `scoring_utils.py` | `weighted_points()`, source text builder |
| `data/match_level_defaults.json` | Configurable score band thresholds |
| `data/profile.json` | Scoring rules, preference weights, evidence tier weights |
