# Candidate Application History Sync

- The runtime app reads the local source of truth at `data/runtime/candidate_application_history.json`.
- The normal rejection-sync path is: Gmail Apps Script -> configured `Job_Rejections` Google Sheet -> `import_candidate_rejections_from_sheet()` -> local candidate application history -> employer rejection counts.
- When the local `candidate_application_history.sync_before_run` setting is enabled, Job Hunter's daily scheduled run performs that Sheet import before collecting jobs, then refreshes employer rejection counts.
- The sync is not performed at application startup, onboarding, or workspace enrichment. If the Sheet import fails, the job collection continues using the last known local history and the scheduler records the failure message.
