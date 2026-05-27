# Agent Instruction Structure

This project uses a layered instruction model so agents receive the right guidance without flooding context.

## Why this structure exists

Large root instruction files become noisy and can crowd out task context. Professional agent projects keep universal rules short, then load scoped instructions only when needed.

## Layers

1. `AGENTS.md`
   - Project-wide source of truth.
   - Contains only universal rules, source hierarchy, testing rule, backlog rule, Definition of Done, and skill routing.

2. Agent adapter files such as `CLAUDE.md` and `GEMINI.md`
   - Thin adapters for a specific agent environment.
   - Should point back to `AGENTS.md` instead of redefining project rules.

3. `.skills/*/SKILL.md`
   - Compact scoped instructions for a work area.
   - Should answer: when to use, what must not be violated, where ownership lives, and how to validate.

4. `.skills/*/DETAILS.md`
   - Longer reference content split out of a skill.
   - Use for examples, patterns, component maps, source-specific details, and historical traps.

5. `docs/*`
   - Human/reference documentation.
   - Architecture, operations, setup, rationale, and detailed explanations.

6. Backlog tracker
   - Current source of truth is the shared Google Sheet backlog.
   - Planning and tracking only.
   - Not an instruction source.
   - Local `docs/backlog/backlog_review.xlsx` is archive/export/reference only unless the human explicitly asks to update it.

## Maintenance rules

- Prefer moving detail from `AGENTS.md` into a relevant skill or doc.
- Prefer moving long skill examples into `DETAILS.md`.
- Avoid duplicating the same rule across files.
- Do not let adapter files redefine project rules.
- Remove stale architecture claims once verified wrong.
- Preserve hard project constraints: no hardcoding, risk-based validation, Google Sheet backlog source of truth, Excel export compatibility when explicitly used, and do-not-pick-Done backlog items.

## Current cleanup decisions

- `AGENTS.md` was reduced to the project-wide source of truth.
- Testing rules were consolidated into `AGENTS.md` and referenced from `.skills/code-change/SKILL.md`.
- `.skills/scraping/SKILL.md` was shortened; the previous long content was preserved in `.skills/scraping/DETAILS.md`.
- Backlog source of truth moved from local Excel to the shared Google Sheet.
- Skills now use discovery frontmatter (`name` and `description`) so agents can route by skill metadata instead of hardcoded trigger lists in `AGENTS.md`.
- Tool expectations are documented in `docs/AGENT_TOOLS_AND_SKILLS.md`.
- `GEMINI.md` was intentionally not updated because the human asked not to edit it.

