---
name: backlog-management
description: Use ONLY for backlog work: Google Sheet rows, JH IDs, priorities, duplicates, implementation state, evidence, human review flags, or adding/updating backlog items. Do NOT use for code implementation except to update backlog evidence.
---

# Skill: Backlog Management

Use when creating, updating, deduplicating, or analysing backlog items.

## Source of truth
- Working backlog: `https://docs.google.com/spreadsheets/d/1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0/`.
- This Google Sheet is the backlog source of truth because it supports concurrent editing.
- Local `docs/backlog/backlog_review.xlsx` is archive/export/reference only unless the human explicitly asks to update it.
- Read the sheet header row first and update by column name, never by fixed position.
- Do not add, remove, or rename columns unless explicitly agreed.

## How to read and write the sheet (MCP tools)

The HUMAN MCP SERVER provides three Sheets tools. Always use these — do not use the built-in Google Drive connector for backlog writes.

**Spreadsheet ID:** `1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0`  
**Sheet name:** `Backlog`

### Read a single row by ID (preferred — low token cost)
```
sheets_read_row_by_id(
    spreadsheet_id="1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0",
    sheet_name="Backlog",
    row_id="JH-001"
)
```
Returns the row as a dict keyed by header. Use this when you only need one row.

### Append a new row
```
sheets_append_row(
    spreadsheet_id="1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0",
    sheet_name="Backlog",
    values=["JH-191", "Agent", "Title here", ...]
)
```
Values must be in column order matching the header row. Safe for concurrent agents — no read-modify-write needed.

### Update a single cell
```
sheets_update_cell(
    spreadsheet_id="1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0",
    sheet_name="Backlog",
    row=5,      # 1-based, row 1 is the header
    col=15,     # 1-based, col 15 = Implementation State
    value="Done"
)
```
Use this to update a specific field on an existing row. Get the row number from `sheets_read_row_by_id`.

### Read all rows (use sparingly — high token cost)
```
sheets_read_rows(
    spreadsheet_id="1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0",
    sheet_name="Backlog"
)
```
Only call this when you genuinely need the full backlog (e.g. deduplication scan, next ID lookup). Avoid in tight loops.

### Getting the next JH ID
Call `sheets_read_rows`, extract all values in column A, find the highest JH-### number, increment by 1.

## Column order (as of 2026-05-26)
1. ID, 2. Creator, 3. Title, 4. Epic, 5. Type, 6. Priority, 7. Size, 8. Problem, 9. Outcome, 10. Acceptance Criteria, 11. Original Source, 12. Duplicate Of, 13. Depends On, 14. Notes, 15. Implementation State, 16. Implementation Date, 17. Implemented By, 18. Evidence, 19. Human Review Needed, 20. Review Category, 21. Review Reason

## Creating a backlog row from a rough idea
When the human gives a rough idea, create a complete row rather than asking them to fill every field.

Fill the columns that exist in the sheet:
- `ID`: next stable `JH-###` number.
- `Creator`: `Human` if the human supplied the idea; `Agent` only if the agent discovered it while working.
- `Title`: concise action phrase.
- `Epic`: use an existing epic where possible.
- `Type`: one of `Story`, `Bug`, `Task`, `Spike`, `Decision`, `Risk`.
- `Priority`: `High`, `Medium`, or `Low`.
- `Size`: `S`, `M`, `L`, or `XL`.
- `Problem`: why this matters.
- `Outcome`: what success looks like.
- `Acceptance Criteria`: testable completion checks.
- `Original Source`: file, conversation, or code area that triggered it.
- `Duplicate Of`: leave blank unless clearly duplicate.
- `Depends On`: existing IDs that must happen first.
- `Notes`: assumptions, uncertainty, or implementation cautions.
- `Implementation State`: `Not Done` by default unless implementation is verified.
- `Implementation Date`, `Implemented By`, `Evidence`: fill only when implementation is verified.

## Selecting work
- Do not pick or implement rows where `Implementation State = Done`.
- Done rows may only be touched when the human explicitly asks to audit, reopen, correct evidence, or revise that specific row.
- Normal agent task selection must use rows where `Implementation State` is not `Done`, preferably `Not Done` or `Partially Done` after confirming scope.

## Human review marking
Use review columns to flag items that need the human's judgement because the agent cannot safely resolve them alone. Examples of useful review reasons include unclear intent, missing information, possible duplicates, possibly old/obsolete items, or items that seem wrong or inconsistent.

Do not use `Needs code check` as a human-review category. Code inspection status is agent work, not useful human triage by itself.

## Updating existing rows
- Do not delete rows without human agreement.
- If a row looks duplicate, fill `Duplicate Of` and explain in `Notes` or `Evidence`.
- If a row is obsolete, set `Implementation State = Obsolete` and add evidence.
- If implementation is verified, update `Implementation State`, `Implementation Date`, `Implemented By`, and `Evidence` when those columns exist.
- Preserve original meaning. Do not rewrite human wording unless clarity improves and meaning is preserved.

## Implementation State rules
- `Implementation State` is a delivery/status field, not an audit todo field.
- Do not write `Needs Code Check` into `Implementation State`.
- Allowed values are:
  - `Done`: code/docs/tests meet the acceptance criteria.
  - `Not Done`: not implemented yet or not proven done.
  - `Partially Done`: some required capability exists but acceptance criteria are not fully met.
  - `Obsolete`: no longer relevant because architecture/product direction changed.
- Code-check uncertainty belongs in review columns such as `Human Review Needed`, `Review Category`, and `Review Reason`, not in `Implementation State`.

## Code-check evidence
Evidence must name files/functions/tests, not vague claims.
Good evidence:
- `profile_store.save_profile()` now writes to SQLite `user_profile`; test X covers persistence.
Bad evidence:
- `Looks implemented`.

## Deduplication
Before adding a row:
1. Search workbook titles and notes for similar words.
2. If similar, update the existing row rather than adding a duplicate.
3. If uncertain, add the new row but note the possible duplicate in `Notes`.

## Finish format
Report:
- Row(s) created or updated.
- Any duplicates suspected.
- Any implementation state changes and evidence.
- Any workbook compatibility concerns.
