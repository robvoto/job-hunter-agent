# OpenClaw Backlog

## OpenClaw / Agent Runtime

### Core goal

- [ ] Convert the Python job-hunter prototype into an OpenClaw tool-first agent

  Context:
  - Keep existing scraper/filter logic.
  - Do not rewrite everything.
  - Wrap the scraper as a callable tool inside an OpenClaw workspace.
  - Preserve the current repo structure unless change is necessary.
  - Prefer simple, debuggable code over clever abstractions.

---

### Scheduling

- [ ] Add scheduled job runs at 12pm and 6pm

  Context:
  - OpenClaw has heartbeat/scheduling built in.
  - The agent should check for new worthwhile jobs twice daily.
  - It should update the SEEK/job dashboard output automatically.

---

### Learning from outcomes

- [ ] Learn from applied jobs and interview/call outcomes

  Context:
  - OpenClaw can read user decisions and update profile/rules.
  - The agent should learn from jobs applied to.
  - The agent should learn from interviews or calls.
  - Rejection emails should be matched back to role/CV where possible.
  - Rejection data should feed future scoring and rules.

---

### Prompt/code improvement

- [ ] Allow OpenClaw to suggest prompt and code improvements

  Context:
  - OpenClaw can read and edit repo files.
  - It can improve prompts.
  - It can propose code diffs.
  - Changes must remain small, debuggable, and reviewable.

---

### Token usage monitoring

- [ ] Investigate OpenAI token usage monitoring

  Context:
  - Feasible, but not native to OpenClaw.
  - Needs an OpenAI API usage call.
  - Useful to avoid burning tokens.

---

### Test console

- [ ] Build a test console for Job Hunter agent behaviour

  Context:
  - This is a Job Hunter feature, not OpenClaw itself.
  - Should show whether key agent tests pass/fail.

---

### Interview conversation learning

- [ ] Investigate whether OpenClaw can learn from interview conversations

  Context:
  - Original question: can OpenClaw or similar listen to interview conversations and improve?
  - Needs privacy, consent, and technical feasibility review.

---

### Stop behaviour

- [ ] Clarify what “Stop” means in the agent workflow

  Context:
  - For now, “Stop” means alert only.
  - It cannot reach OpenAI or execute actions without valid credentials.

---

### Local-first and LLM constraints

- [ ] Keep LLM usage optional and limited to shortlisted jobs

  Context:
  - Local-first where possible.
  - Minimise paid model usage.
  - Avoid unnecessary LLM calls.

---

### Logging

- [ ] Add clear logging and JSON output for all jobs processed

  Context:
  - Every processed job should have structured output.
  - Logs should support debugging, learning, and later analysis.

---

### Ollama cleanup

- [ ] Remove unused local Ollama models

  Context:
  - Models are taking too much disk space.
  - Commands:
    ```bash
    ollama list
    ollama rm llama3.1:8b
    ollama rm qwen3.5
    ```

---

### OpenClaw auth issue

- [ ] Investigate OpenClaw auth.json regeneration bug

  Context:
  - OpenClaw is recreating `auth.json`.
  - Versions 2026.3.22 and later may trigger forced OAuth re-authorisation on every startup.
  - This invalidates refresh tokens and overwrites credentials.
  - Result: broken authentication loop where credentials cannot persist.

### Evidence / STAR / Candidate Input

- [ ] Re-evaluate STAR / evidence notes approach

  Context:
  - Current idea:
    - STAR / evidence notes (optional examples, impact stories, selection criteria)
  - Concern:
    - feels weak
    - many users will NOT have this
  - Question:
    - what replaces it?
  - Idea:
    - free text box with strong guidance to capture useful evidence
  - Goal:
    - still learn from candidates (manual or OpenClaw-assisted)

---

### Testing system (very important)

- [ ] Build structured test cases + test console

  Context:
  - Cover all scenarios
  - Visual board:
    - green = pass
    - red = fail
  - Could reuse existing tab or create new one

---

- [ ] Show token usage / limits if possible

  Context:
  - Ideally integrate OpenAI usage:
    - https://platform.openai.com/settings/organization/usage
  - Show remaining tokens / cost awareness

---

- and also we need to be sure about cost, but this is another agent