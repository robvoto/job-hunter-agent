# Cline project adapter

At the start of every task:

1. Read `AGENTS.md` for shared rules that apply to every coding agent.
2. Read `docs/CLINE_MEMORY.md` for Cline-specific durable session context.
3. Read `docs/PROJECT_CONTEXT.md` only when project context, runtime truth, or domain routing is needed.
4. Load only the relevant `.agents/skills/*/SKILL.md` files required for the task.

Do not copy Cline-specific memory into `AGENTS.md`. Keep shared rules in their existing owners and keep Cline-only session context in `docs/CLINE_MEMORY.md`.

Do not edit `AGENTS.md`, `.clinerules/`, `docs/CLINE_MEMORY.md`, `docs/AGENT_OPERATING_MODEL.md`, `docs/DOC_INDEX.md`, or `.agents/skills/` unless the human explicitly requested instruction maintenance. Product work must not rewrite Cline's own instructions.
