# Skill: History & Dedup

Use before editing job history, viewed/applied/hidden state, posting timestamps, or deduplication.

## Rules
- History is valuable local state; do not discard it.
- Rebuilds must preserve viewed/applied/hidden state.
- Output files are disposable; data/history files are not.
- Deduplication should be stable across SEEK and LinkedIn where possible.
- Job keys must not depend on unstable UI-only text when stronger identifiers exist.
- Posting timestamps should be normalised consistently before ranking/filtering.

## Owners
- `history.py`: review state.
- `job_identity.py`: stable job keys and cross-source dedup.
- `posting_utils.py`: posting dates and age.
- `workspace_data.py`: historical workspace records.
- `data/job_history.json`: local review history.

## Checklist
- Does this preserve applied/hidden/viewed state?
- Does workspace rebuild keep history?
- Is the job key stable across sources and runs?
- Are timestamps normalised before use?
- Did you run the smallest relevant history/dedup check?
