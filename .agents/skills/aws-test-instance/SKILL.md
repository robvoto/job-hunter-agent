---
name: aws-test-instance
description: Use ONLY for the Job Hunter AWS test EC2 instance, AWS CLI or SSM access to that instance, instance-side runtime/log diagnosis, service restarts, browser-session host issues, and EC2 environment facts. Do NOT use for normal local-only debugging or product behaviour changes without the owning domain skill.
---

# Skill: AWS Test Instance

Use before diagnosing Job Hunter behaviour on the shared AWS test box or when an agent needs the exact EC2/SSM/log paths for that host.

See `.agents/skills/aws-test-instance/DETAILS.md` for the exact instance facts, file paths, and ready-to-run AWS CLI commands.

## Load order
1. Read `AGENTS.md`.
2. Read this skill.
3. Read `.agents/skills/aws-test-instance/DETAILS.md` when the task needs AWS instance facts, SSM commands, service ownership, or known-host failure modes.

## Trigger
Use this skill when the user mentions any of:
- the AWS Job Hunter test instance
- `i-055b97e901418d3ad`
- `JobHunter_Test`
- SSM access to the EC2 host
- `/var/lib/job-hunter/output`
- `job-hunter.service`
- noVNC/Xvfb/browser-session issues on AWS

## Non-negotiable rules
- Prefer AWS CLI + SSM for inspection; do not assume the browser console is the best source.
- Treat the EC2 host as a runtime environment, not the source of truth for code edits. Make code changes in the repo, not on the instance.
- Start with instance logs and service state before hypothesizing product bugs.
- Distinguish infrastructure failure from product behaviour:
  - zero cards + scraper timeouts + service restart signals suggest host/runtime failure
  - captured cards + rejects/LLM activity suggest app-level pipeline behaviour
- Keep AWS facts current by verifying with CLI when possible; do not rely on stale memory for instance state.

## Ownership
- AWS host facts and standard diagnosis workflow: this skill + `DETAILS.md`
- EC2 service wrapper: `scripts/ec2/start-aws-browser-session.sh`
- App-level scraping logic: `.agents/skills/scraping/SKILL.md`
- Workspace/UI behaviour: `.agents/skills/dashboard-ui/SKILL.md`
- Release/deploy flow: `.agents/skills/release-management/SKILL.md`

## Validation
- Record the exact AWS CLI or SSM command used for diagnosis.
- When reporting a host issue, include the instance ID, region, and the file/command that proved it.
- If the diagnosis points to app logic rather than host/runtime state, switch to the owning domain skill before editing code.
