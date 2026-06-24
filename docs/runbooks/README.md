# Job Hunter Runbooks

Runbooks are step-by-step operational procedures for live troubleshooting.

They are not design notes and not backlog. They should answer: what is broken, how to prove it, what to run, and what success looks like.

## Active runbooks

| Runbook | Use when |
| --- | --- |
| `aws-seek-assisted-browser-session.md` | SEEK scraping on AWS hangs, times out, shows verification, or fails before job cards load. |

## Runbook rules

- Use project-standard commands.
- On EC2, use `uv run python ...` for manual Python module execution.
- Always state the pass condition.
- Always separate bounded failure from actual success.
- Do not treat timeouts as scraping success.
- Do not document attempts to defeat third-party site protections.

## Where information belongs

| Information | Owner |
| --- | --- |
| Full AWS topology and deployment | `docs/aws-ec2-setup.md` |
| General commands and recovery model | `docs/OPERATIONS.md` |
| Specific live troubleshooting procedure | `docs/runbooks/*.md` |
| Product/design rationale | `docs/ARCHITECTURE.md`, `docs/PRINCIPLES.md`, or relevant domain doc |
