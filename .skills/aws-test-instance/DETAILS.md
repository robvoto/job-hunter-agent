# AWS Test Instance Details

Use this file only when the task needs exact AWS host facts or repeatable CLI commands.

## Current instance facts

- AWS account: `325771562143`
- Region: `ap-southeast-2`
- Instance name: `JobHunter_Test`
- Instance ID: `i-055b97e901418d3ad`
- Instance type: `t3.micro`
- Availability Zone: `ap-southeast-2c`
- Public IP: `32.236.144.98`
- Private IP: `172.31.18.71`
- VPC: `vpc-065844e2aa7ab0a0c`
- Subnet: `subnet-0fdc6ad514007ac9a`
- Security group: `sg-032b6b0eebe34e0c3` (`launch-wizard-1`)
- IAM instance profile: `EC2-SSM-Role`
- SSM state verified on August 1, 2026: `Online`

## Instance-side app paths

- App dir: `/home/ubuntu/job-hunter-agent`
- Service unit: `/etc/systemd/system/job-hunter.service`
- Service name: `job-hunter.service`
- Service launcher: `/home/ubuntu/job-hunter-agent/scripts/ec2/run-jobhunter-browser-session.sh`
- Browser-session wrapper: `/home/ubuntu/job-hunter-agent/scripts/ec2/start-aws-browser-session.sh`
- Data dir: `/var/lib/job-hunter/data`
- Output dir: `/var/lib/job-hunter/output`
- DB path: `/var/lib/job-hunter/data/job_hunter.db`

## Instance-side logs

Primary files:
- `/var/lib/job-hunter/output/server.log`
- `/var/lib/job-hunter/output/last_run_report.log`
- `/var/lib/job-hunter/output/uncertainty.jsonl`

Browser-session helper logs:
- `/var/lib/job-hunter/output/xvfb.log`
- `/var/lib/job-hunter/output/openbox.log`
- `/var/lib/job-hunter/output/x11vnc.log`
- `/var/lib/job-hunter/output/novnc.log`

## Standard AWS CLI checks

Identity:

```bash
aws sts get-caller-identity
aws configure get region
```

Instance details:

```bash
aws ec2 describe-instances \
  --instance-ids i-055b97e901418d3ad \
  --region ap-southeast-2
```

Security group:

```bash
aws ec2 describe-security-groups \
  --group-ids sg-032b6b0eebe34e0c3 \
  --region ap-southeast-2
```

SSM online check:

```bash
aws ssm describe-instance-information \
  --filters Key=InstanceIds,Values=i-055b97e901418d3ad \
  --region ap-southeast-2
```

## Standard SSM diagnosis commands

List runtime/log paths:

```bash
cmd_id=$(aws ssm send-command \
  --instance-ids i-055b97e901418d3ad \
  --document-name AWS-RunShellScript \
  --comment "Inspect Job Hunter paths" \
  --parameters commands='["pwd","whoami","ls -la /var/lib/job-hunter/output || true","ls -la /var/lib/job-hunter || true"]' \
  --region ap-southeast-2 \
  --query 'Command.CommandId' \
  --output text)

sleep 2

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id i-055b97e901418d3ad \
  --region ap-southeast-2
```

Tail the main logs:

```bash
cmd_id=$(aws ssm send-command \
  --instance-ids i-055b97e901418d3ad \
  --document-name AWS-RunShellScript \
  --comment "Read Job Hunter logs" \
  --parameters commands='["tail -n 150 /var/lib/job-hunter/output/server.log || true","echo","cat /var/lib/job-hunter/output/last_run_report.log || true"]' \
  --region ap-southeast-2 \
  --query 'Command.CommandId' \
  --output text)

sleep 2

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id i-055b97e901418d3ad \
  --region ap-southeast-2
```

Service state:

```bash
cmd_id=$(aws ssm send-command \
  --instance-ids i-055b97e901418d3ad \
  --document-name AWS-RunShellScript \
  --comment "Inspect job-hunter service" \
  --parameters commands='["systemctl status job-hunter --no-pager || true","echo","journalctl -u job-hunter --since \"10 minutes ago\" --no-pager || true"]' \
  --region ap-southeast-2 \
  --query 'Command.CommandId' \
  --output text)

sleep 2

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id i-055b97e901418d3ad \
  --region ap-southeast-2
```

## Diagnosis heuristics

### If a run says "No fresh cards were captured"

Check in this order:
1. `last_run_report.log`
2. `server.log`
3. `systemctl status job-hunter`
4. EC2 console output if the app seems to have restarted

### Known host-side failure already observed

Verified on August 1, 2026:
- Run began at `2026-08-01 17:25:48 AEST`
- Run ended at `2026-08-01 17:30:16 AEST`
- `Pages read: 0`, `Jobs seen: 0`
- `uvicorn` shut down mid-run
- EC2 console output showed:
  - `Out of memory: Killed process ... (chrome-headless)`

Interpretation:
- on this host, zero captured cards can be caused by instance memory pressure rather than app logic
- the current instance type (`t3.micro`) is vulnerable to Playwright/Chrome OOM kills
- `job-hunter.service` has `Restart=always`, so an exit restarts the whole app and interrupts in-flight scraping

### Distinguish host failure vs app logic

Likely host/runtime failure:
- zero cards seen on all boards
- source timeout messages with no cards captured
- `uvicorn` shutdown/restart during the same run
- OOM or service restart evidence

Likely app-level behaviour:
- cards seen/read but all rejected
- LLM errors or incomplete keep data
- renderer/workspace warnings after cards were already captured

## Notes

- IMDS on the instance requires `HttpTokens=required` (IMDSv2), so plain metadata `curl` may return nothing without a token.
- Prefer AWS CLI from the local workstation over manual EC2 console clicking when diagnosing repeatable issues.
