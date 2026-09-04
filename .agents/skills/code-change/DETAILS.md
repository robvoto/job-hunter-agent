# Code Change Details

Loaded only when the task needs the detailed contracts/examples below.

## Text utility changes
Use this section for reusable text normalization, matching/parsing helpers, scoring source text, and description-trust utilities.

Rules:
- Utility code should stay judgement-free.
- Do not add business categories, labels, thresholds, or scoring policy here.
- Keep helpers small, deterministic, and reusable.
- Do not hide data loss in aggressive cleaning.
- Text utilities may normalise shape; they must not decide fit.
- Consumers should receive predictable canonical output.

Owners:
- `text_processing.py`: whitespace/dedup/text cleanup.
- `scoring_utils.py`: scoring source text and weighted points helper.
- `description_trust.py`: full-description confidence.
- `role_analysis.py`: role text bundles and context helpers.

## Incorrect-output diagnosis

Use this workflow when the user reports a wrong classification, score, badge, state, or generated explanation:

1. Capture the exact incorrect output and identify the concrete record/job key.
2. Inspect the persisted record and the relevant human/debug logs before proposing a fix.
3. Trace the value through producer/extractor, LLM response if applicable, normalizer/validator, scoring or business-rule consumer, persistence, and renderer.
4. Identify the first point where the value became wrong. Do not patch the final UI when the source data is already wrong.
5. State the root defect in one plain-English sentence before editing.
6. Fix the generic contract or rule, not the reported phrase/company/job alone.
7. Search for superseded configuration, lists, helpers, tests, or branches and remove them when the new design makes them obsolete.
8. Add a regression test for the reported case and an unrelated case when the rule is intended to be reusable.
9. Run targeted tests plus adjacent tests for every downstream owner touched.

Do not create a new project skill for a single diagnosis pattern when this workflow belongs in the general code-change process.

## Runtime diagnosis
- Server log: `output/server.log`. `./run` writes curated INFO-level per-board summaries; `./run --debug` raises it to DEBUG in the same file, adding raw LLM/API/pipeline detail and interleaved worker activity.
- Per-job report: `output/last_run_report.log`. Overwritten at the end of every run with the aggregate run summary plus a clean human-readable block (title, company, source, decision, why, URL, time, LLM cost) for every job processed that run — read/rejected/kept. Not duplicated into `server.log`.
- Find the last relevant log line before a hang/error, then read the code that runs next.
- Geolocation lookup (`/api/onboarding/lookup-location-by-geolocation`) is a separate network call and can appear to delay extraction.
- **Dependency version regressions**: if a 3rd-party call fails with `unexpected keyword argument` or similar, check `git log -- uv.lock` and diff the old vs new version before touching calling code. The lock may have resolved to a lower version than the one the code was written against. Fix the version constraint; do not rewrite calling code to work around the wrong version.
