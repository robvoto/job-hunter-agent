---
name: job-market-map-integration
description: Use when changing or diagnosing Job Hunter's integration with Job Market Map (JMM): consumer feeds/checkpoints, JMM HTTP client contract, run-scoped snapshot paging, JD hydration, identity lookup, or JMM/JH integration tests.
---

# Skill: Job Market Map Integration

Use this for any Job Hunter work that reads from or coordinates with JMM.

## Ownership
- JMM owns neutral market collection, canonical market identity/card facts, duplicate evidence, current JD storage/enrichment, coverage, and per-consumer processing checkpoints.
- Job Hunter owns candidate analysis, ranking, workspace state, and personal activity/outcomes.
- Job Hunter consumes JMM through the supported `/v3` HTTP API only. Do not read/write JMM SQLite from JH and do not silently fall back to JH's retired collectors.
- JMM's authoritative contract lives in `/home/robvoto/projects/job-market-map/docs/API.md` and `docs/CONSUMER_CONTRACT.md`. If JMM code itself must change, also read that repo's `AGENTS.md` and `.agents/skills/job-market-map/SKILL.md` before editing.
- JMM lifecycle is protected by the JH/JMM/Human-MCP lifecycle approval rule in `docs/PROJECT_CONTEXT.md`. Integration diagnosis is read-only by default; never start, stop, restart, kill, or relaunch JMM merely to test or verify JH without fresh explicit approval for that exact action.

## Stateless search paging
Normal JH discovery uses JMM's stateless `/v3/jobs/search` contract, not the legacy named-consumer feed/checkpoint lane.

For one JH run:
1. Request the first bounded search page without `through_id`.
2. Capture returned `snapshot_max_id`.
3. Send that same value as `through_id` on every later page and every source/filter scope in that run.
4. Reject a changing snapshot boundary or changing `total` within one fixed scope.
5. Do **not** persist `through_id`/`snapshot_max_id` as personal activity or permanent consumer state.

This freezes the market boundary for one run so jobs arriving mid-run wait for the next run while JH keeps no second market cache.

### Neutral filter ownership
- Reuse JH's existing user controls for role terms, source selection, location/geography, freshness, work type, work mode, apply method, and salary floors.
- Optional `classification`, `subclassification`, and `company` settings are literal neutral source text forwarded to JMM; JH must not translate or infer board taxonomies.
- Legacy `classification_ids` are source-native identifiers and must never be forwarded as JMM textual classifications.
- JH may read `/v3/capabilities/fields`. `unknown` capability remains usable/uncertain; only an explicit unsupported/not-applicable capability may suppress a neutral filter for that source.
- JMM remains responsible for uncertain-field eligibility and structured salary comparability; JH applies personal filtering after candidate return.

## JH implementation owners
- Transport/client: `job_hunter_agent/job_market_map_client.py`
- Consumer paging/checkpoint loop: `job_hunter_agent/market_map_source.py`
- Human/reference integration contract: `docs/INTEGRATIONS.md`

Do not duplicate this paging state in another module, DB table, cache, or activity ledger.

## JD and identity rules
- Use JMM exact identity/lookup contracts; do not recreate JMM identity or duplicate logic in JH.
- Read the current JD through cached-only `GET /v3/jobs/{id}/jd` only when JH analysis needs it. A 409 is a per-job cache miss, not a JMM outage; do not POST-enrich from JH.
- JMM's JD is transient analysis input to JH; do not create another permanent raw-JD owner in JH.

## Validation
For paging/contract changes, validate all three layers:
1. JMM `/v3/jobs/search`, field-capability, readiness, and cached-JD contracts as relevant.
2. JH client/source tests proving neutral filters and `through_id` are forwarded without taxonomy/salary reconstruction.
3. JH end-to-end contract tests proving one fixed run boundary plus correct cached-JD/409 behavior.

Then run the repository's required broader validation from `mcp-tooling/SKILL.md`. An unrelated Git-hygiene failure in another worktree must be reported separately, not hidden or "fixed" by deleting someone else's work without verification/approval.

## Do not
- Do not turn `snapshot_max_id` into durable user state.
- Do not add JMM consumer checkpoint state for stateless JH search.
- Do not change job-selection, fit, scoring, or filtering semantics while working on this transport contract.
