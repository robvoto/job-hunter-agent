---
name: backlog-management
description: Use ONLY for Job Hunter backlog reads, grooming, JH IDs, duplicates, status, evidence, or adding/updating backlog rows. Do NOT use for product implementation except to update backlog evidence.
---

# Skill: Backlog Management

## Source of truth

- Canonical spreadsheet: `1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0`, sheet `Backlog`.
- The live Google Sheet is the only backlog source of truth. Local exports are reference/archive only unless the human explicitly asks otherwise.
- Use an authorised live Sheets capability. In ChatGPT connector runtimes, load `mcp-tooling` first and keep the same authorised connector path for the task.
- If live read/write access is unavailable or a required write fails, stop backlog work and report the exact blocked action; do not substitute an export or cached copy.

## Schema contract

- Read the live header before backlog work and address fields by column name, never fixed position.
- Do not encode a fixed column order, allowed-value list, or historical schema in this skill.
- Do not add, remove, or rename columns without explicit human agreement.
- Populate only columns that exist in the live header; do not recreate removed fields under new names.

## IDs and new rows

- For a new item, read live IDs, find the highest valid `JH-###`, and increment by one. Ignore malformed placeholders.
- Search existing titles plus descriptive text before creating a row. Update an existing item when it already covers the same work.
- Turn a rough human idea into a useful row without asking them to fill every field: preserve the intent, concise title/summary, delivery state/priority when those live columns exist, source/context, blockers, next action, and useful references.
- Do not invent evidence, dependencies, dates, owners, review fields, or other columns absent from the live schema.

## Reading and selecting work

- Read one row by `ID` when inspecting one item; read broadly only for deduplication, next-ID lookup, or bounded grooming.
- Treat the live `Status` column as authoritative. Do not select terminal/obsolete work for implementation unless the human explicitly asks to reopen, audit, or correct it.
- Do not maintain a hard-coded status/priority/area vocabulary here; use the values present in the live sheet and preserve their meaning.
- Respect `Blocked By` when present. Do not silently start blocked work.

## Updating and grooming

- Preserve the human's original intent; improve wording only when clarity improves without changing meaning.
- Do not delete backlog rows without explicit human agreement.
- Mark duplicates conservatively using the live fields available (normally `Notes` and/or `External Ref`) rather than inventing a removed duplicate column.
- Mark work obsolete only when current product/repository evidence supports that conclusion.
- When implementation is verified, update the live status and record concise evidence in the available evidence-bearing fields (`Notes` and/or `External Ref`); name concrete files/functions/tests where useful.
- Use `Next Action` for the next actionable follow-up rather than burying it in narrative notes.
- For grooming, check for duplicates, invalid/misaligned values, stale references, weak summaries/notes, blockers, and completion claims unsupported by current evidence.
- For large grooming passes, work in bounded ID ranges and report exactly what changed.

## Finish

Report the row IDs created/updated, any suspected duplicates or blockers, and any status changes with the evidence used. Never claim a live Sheet update unless the write was verified.
