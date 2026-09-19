---
name: backlog-management
description: "Use ONLY for backlog work: Google Sheet rows, JH IDs, priorities, duplicates, implementation state, evidence, human review flags, or adding/updating backlog items. Do NOT use for code implementation except to update backlog evidence."
---

# Skill: Backlog Management

Use when creating, updating, deduplicating, grooming, or analysing backlog items.

## Source of truth
- Working backlog: `https://docs.google.com/spreadsheets/d/1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0/edit?gid=218702820#gid=218702820`.
- This Google Sheet is the only backlog source of truth.
- The shared backlog access identity is `agent-backlog-access@robvoto-agent-platform-iam.gserviceaccount.com`; it should have access to all relevant project backlog spreadsheets. Do not infer that other configured service accounts are prohibited.
- Local `docs/backlog/backlog_review.xlsx` is archive/export/reference only unless the human explicitly asks to update it.
- Read the sheet header row first and update by column name, never by fixed position.
- Do not add, remove, or rename columns unless explicitly agreed.

## Required skill pairing
- For every backlog read, search, analysis, or write, use this skill together with an authorised live Google Sheets capability exposed by the current runtime. In a ChatGPT connector runtime, load `.agents/skills/mcp-tooling/SKILL.md` first and use the connector route it defines. The canonical spreadsheet ID and sheet name are pinned below, so routine backlog work does not require generic Drive discovery.
- Once live backlog access is established through one authorised connector path, keep that path for the backlog/repo investigation. Do not casually switch to a second connector merely because both are available. Escalate to a different connector only when the current authorised path genuinely lacks the required operation, and make that isolated boundary explicit.
- In Codex/Claude/local runtimes, use their authorised live-Sheets/API capability if one exists. If the current runtime has no authorised live-Sheet capability, stop rather than substituting a local export.
- This skill owns Job Hunter backlog rules; the Google Sheets skill owns live spreadsheet metadata, bounded reads, validation checks, precise writes, and post-write verification.
- When the human provides the backlog URL, go directly to this spreadsheet. Do not search local exports or GitHub issues for JH IDs first.

## How to read and write the sheet

Use the authorised live Google Sheets tool available in the current runtime. This may be a local MCP Sheets tool, a cloud Sheets connector, or another approved runtime-specific Sheets integration.

**Spreadsheet ID:** `1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0`  
**Sheet name:** `Backlog`

### Required access rule
If no authorised tool can read and write the live Google Sheet, or a write fails:
- Stop backlog work.
- Do not claim the sheet was updated.
- Do not use local exports, docs, copied spreadsheets, or archive files as a substitute backlog.
- Report the blocker and the exact backlog action that could not be completed.

### Required operations
Use the equivalent live-Sheets operations for the current runtime:
- Read row by `ID` when inspecting one item.
- Append a row when creating a new item.
- Update a single cell or row fields when changing an existing item.
- Read all rows only when needed for deduplication, next-ID lookup, or bounded grooming.

### Getting the next JH ID
Read existing IDs from the live `Backlog` sheet, find the highest valid `JH-###` number, and increment by 1. Ignore malformed placeholders such as `JH-NEXT`.

## Column order (verified 2026-08-14)
1. ID, 2. Creator, 3. Title, 4. Epic, 5. Type, 6. Priority, 7. Size, 8. Problem, 9. Outcome, 10. Acceptance Criteria, 11. Original Source, 12. Duplicate Of, 13. Depends On, 14. Notes, 15. Implementation State, 16. Implementation Date, 17. Implemented By, 18. Evidence, 19. Human Review Needed, 20. Review Category, 21. Review Reason, 22. Created Date, 23. Modified Date, 24. Resolved Date

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
- `Created Date`: set when a new row is created.
- `Modified Date`: update when the row is materially changed.
- `Resolved Date`: set when the item is resolved; leave blank while still open.

## Selecting work
- Do not pick or implement rows where `Implementation State = Done`.
- Done rows may only be touched when the human explicitly asks to audit, reopen, correct evidence, or revise that specific row.
- Normal agent task selection must use rows where `Implementation State` is not `Done`, preferably `Not Done` or `Partially Done` after confirming scope.

## Grooming existing rows
Grooming means improving backlog quality, not implementing product code.

For each row, check only what can be proven from the live sheet and, when needed, the repo:
- duplicate or near-duplicate item;
- invalid `Implementation State` value;
- malformed or shifted columns;
- stale references to removed files, old JSON paths, or obsolete architecture;
- weak rows with missing Problem, Outcome, or Acceptance Criteria;
- rows marked `Done` without file/function/test evidence.

Update conservatively:
- Do not delete rows unless the human explicitly agrees.
- Prefer marking duplicates with `Duplicate Of` and evidence.
- Mark obsolete only when architecture/code evidence proves it.
- If unsure, use `Human Review Needed`, `Review Category`, and `Review Reason` instead of rewriting the row.
- For large grooming, work in small ID ranges and report exactly what changed.

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
