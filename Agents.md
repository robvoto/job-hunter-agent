Job Hunter Agent — Project Specifications

Purpose

This project is an Agentic AI Job Hunter system.

The system must:
- scrape jobs from sources
- extract candidate profile signals
- filter jobs strictly but fairly
- explain all decisions
- improve through user review over time

---

Tech Stack & Execution

Core:
- Python 3.11+
- Playwright (scraping)
- OpenAI (optional LLM layer)
- Local storage (JSON / SQLite depending on module)

Canonical commands:

- Setup
  py -3.11 -m venv .venv
  .venv\Scripts\Activate.ps1
  pip install -r requirements-dev.txt
  python -m playwright install chromium

- Run normal manual refresh
  python -m job_hunter_agent.source_connector

- Rebuild dashboard only
  python -m job_hunter_agent.source_connector --rebuild-dashboard

- Run local web UI
  python -m job_hunter_agent.local_server

- Run daily agent once
  python -m job_hunter_agent.agent_runner

- Run tests
  python -m pytest
  
Notes:
- For detailed flags and workflows, read RUN_COMMANDS.txt  
- Do not invent new commands
- Always follow existing module entry points
- If unclear, inspect the repo before acting

---

Core Rules (Behavioral Guardrails)

1. No hardcoded judgement

Do not hardcode business judgement unless explicitly approved.

Do not add:
- fixed filtering dictionaries
- hidden rejection rules
- scoring shortcuts
- artificial values to force outcomes

The system must rely on data, scoring logic, and user-driven learning.

---

2. Preserve signals

Do not silently delete candidate or job signals.

If a signal is:
- weak
- ambiguous
- incomplete
- low confidence

Preserve it and mark it for review.

Example:

{
  "signal": "API experience",
  "evidence": "used Postman and integration requirements",
  "confidence": "medium",
  "needs_review": true
}

Meaning:
The system found evidence but is not fully confident.

This does NOT trigger rejection.

---

3. No false-negative rejection

Do not reject jobs because:
- capability is low or basic
- experience is indirect
- match is imperfect

Hard rejection is allowed only for explicit blockers:
- work rights
- mandatory clearance
- mandatory location
- mandatory certification
- clearly stated non-negotiable requirements

Everything else:
- must remain visible
- must be downgraded via scoring or warnings

---

4. Data integrity

Treat all input data as evidence.

Do not:
- fabricate data
- inject fake signals
- alter meaning
- rewrite CV or job content to fit logic

Allowed:
- normalisation
- structuring
- tagging uncertainty

---

5. Learning control

Do not simulate learning through code.

Learning must come from:
- user review feedback
- approved knowledge updates
- managed knowledge sources

Do not:
- embed learned behaviour into filters
- bypass review via assumptions

Learning must remain:
- inspectable
- reversible

---

6. Review signals (core mechanism)

Uncertain signals must not be collapsed into decisions.

They must:
- remain visible
- be marked (e.g. needs_review=true)
- influence scoring without forcing rejection

Review signals are inputs to learning, not outputs to hide.

---

7. Explainability

Every decision must be explainable.

The system must show:
- what decision was made
- why it was made
- what evidence contributed
- what was uncertain

Do not introduce:
- hidden scoring
- opaque thresholds
- silent ranking behaviour

---

8. No legacy code

This is a prototype.

Do not:
- add backward compatibility layers
- preserve outdated logic

If found:
- flag it
- remove only if within scope

---

9. Minimal changes

- modify only what is required
- avoid unrelated files
- keep changes small and traceable

---

10. Testing discipline

- run only relevant validation
- avoid full test runs unless required
- explicitly state when broader testing is needed

---

11. System thinking

Always consider the full system:

- data ingestion
- filtering and scoring
- explanation layer
- user review loop

Do not optimise one layer in isolation.

---

12. Consistent language

Use consistent terminology across the system.

Do not introduce multiple names for the same concept.

---

13. Challenge bad design

Push back if a change:
- introduces hidden judgement
- creates false negatives
- breaks explainability
- bypasses learning
- hardcodes behaviour

---

Output Format (for coding tasks)

Return only:

- changed
- removed
- remaining
- validation