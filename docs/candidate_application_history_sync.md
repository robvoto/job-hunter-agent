# Candidate Application History Sync

- The `Job_Rejections` Google Sheet is the import source.
- The runtime app reads the local JSON store at `data/runtime/candidate_application_history.json`.
- Run `python -m job_hunter_agent.candidate_application_history import-from-sheet` before a scrape or run if you want the latest rejection flags in the local store.
- Set `candidate_application_history.sync_before_run` to `true` if you want the workspace to refresh the local store before enrichment.
