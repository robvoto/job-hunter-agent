# Candidate Application History Sync

- The runtime app reads the local source of truth at `data/runtime/candidate_application_history.json`.
- The temporary migration input is `data/imports/candidate_application_history_export.json`.
- Run `./sync-job-rejections` to import that local export and print the final local-store status.
- When the local `candidate_application_history.sync_before_run` setting is enabled, Job Hunter's own daily scheduled run imports the configured Apps Script `Job_Rejections` sheet before collecting jobs, then refreshes employer rejection counts.
- The sync is not performed at application startup, onboarding, or workspace enrichment. If the sheet import fails, the job collection continues using the last known local history and the scheduler records the failure message.
