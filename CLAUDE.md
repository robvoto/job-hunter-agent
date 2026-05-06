# Start-of-task protocol (Claude Code)

**Do this at the start of every task, in order:**

1. Read `AGENTS.md` — code map, run commands, non-negotiable rules, and the skills index.
2. Identify which domain(s) the task touches.
3. Read **only** the relevant `.skills/<domain>/SKILL.md` file(s) — not all of them.
4. Then plan and act.

**Never skip step 1.** `AGENTS.md` is the source of truth for architecture, rules, and which skill to load.  
**Never read all skills upfront** — they exist to be loaded on demand, one domain at a time, to save tokens.

---

This project uses `AGENTS.md` as the primary AI context file (generic — works with Claude Code, Codex, Cursor, and other tools).

