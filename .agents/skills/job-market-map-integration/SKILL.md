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

## Named consumer paging
Normal JH discovery uses its named JMM consumer feed and checkpoint.

For one JH run:
1. First consumer-feed page is requested without `through_id`.
2. Capture returned `snapshot_max_id`.
3. Send that same value as `through_id` on every later consumer-feed page in that run.
4. Checkpoint each page only after that page has been safely analysed.
5. Do **not** persist `through_id`/`snapshot_max_id` as personal activity or as a permanent checkpoint field.
6. If the run fails, the next run starts from the last safely persisted consumer checkpoint and captures a fresh `snapshot_max_id`.

This freezes the market boundary for one run so jobs arriving mid-run wait for the next run.

## JH implementation owners
- Transport/client: `job_hunter_agent/job_market_map_client.py`
- Consumer paging/checkpoint loop: `job_hunter_agent/market_map_source.py`
- Human/reference integration contract: `docs/INTEGRATIONS.md`

Do not duplicate this paging state in another module, DB table, cache, or activity ledger.

## JD and identity rules
- Use JMM exact identity/lookup contracts; do not recreate JMM identity or duplicate logic in JH.
- Request the current JD from JMM only when JH analysis needs it.
- JMM's JD is transient analysis input to JH; do not create another permanent raw-JD owner in JH.

## Validation
For paging/contract changes, validate all three layers:
1. JMM API + named-consumer endpoint tests, including the mid-run-arrival case.
2. JH client/source tests proving `through_id` is forwarded and retained for the run.
3. JH end-to-end contract test proving a job arriving after page 1 is excluded from that run and appears on the next run.

Then run the repository's required broader validation from `mcp-tooling/SKILL.md`. An unrelated Git-hygiene failure in another worktree must be reported separately, not hidden or "fixed" by deleting someone else's work without verification/approval.

## Do not
- Do not turn `snapshot_max_id` into durable user state.
- Do not add another JMM checkpoint column for it.
- Do not reset/rewind a safely persisted JMM checkpoint to recover a failed run.
- Do not change job-selection, fit, scoring, or filtering semantics while working on this transport contract.
