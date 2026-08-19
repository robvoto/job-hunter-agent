# Candidate Application History Sync

- The runtime app reads the local source of truth at `data/runtime/candidate_application_history.json`.
- The temporary migration input is `data/imports/candidate_application_history_export.json`.
- Run `./sync-job-rejections` to import that local export and print the final local-store status.
- Candidate application history is never refreshed from a Google Sheet during startup, onboarding, or workspace enrichment.
