# Duplicate Detection Refactor — Phase 1

## Task Brief

**Goal:**
- Replace heuristic duplicate merging in the Python project with deterministic duplicate detection.
- Restrict company suffix usage to safe legal suffixes only.
- Add visible linking for potential duplicates with inspectable metadata.

**Scope:**
- Remove and disable title similarity threshold in identity_rules.json (or corresponding config) and related heuristic merging in Python code.
- Update `company_suffixes` list to exclude risky suffixes like 'group', 'holdings', and 'australia'.
- Implement deterministic duplicate detection based on fields like normalized job_key, canonical URL, ATS requisition ID, platform/source job ID.
- Modify Python duplicate detection and suppression code under /mnt/e/Programming/job-hunter-agent to comply.
- Add metadata for potential duplicates for UI linking.

**Exclusions:**
- Identity graph, learning, adaptive heuristics, user or candidate review flows, and advanced LLM orchestration.

**Acceptance Criteria:**
- Heuristic title similarity merging code removed.
- Company suffix normalization only uses safe suffixes.
- Deterministic duplicate handling controls suppression and merging.
- Potential duplicates visually linked but not merged or suppressed.
- Changes fully logged and auditable.

**Next Steps:**
- Use Codex or preferred coding tool with this precise task brief.
- Request Telegram manual approval before implementing changes.

---

This task brief is tailored to your Python repo path and structure.

Please confirm or provide feedback before I proceed with coding orchestration.