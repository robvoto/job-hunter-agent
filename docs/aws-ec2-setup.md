# Job Hunter Agent — AWS EC2 Production Setup

This is the single canonical AWS deployment document for Job Hunter.

Do not keep parallel AWS setup documents. This file should live at:

```text
E:\Programming\job-hunter-agent\docs\aws-ec2-setup.md
```

or in WSL as:

```text
/mnt/e/Programming/job-hunter-agent/docs/aws-ec2-setup.md
```

The production runtime is on AWS EC2. Local development happens on the PC through WSL.

---

## Current production state - 2026-06-18

This section is the current source of truth for the AWS deployment.

### Domain and DNS

The paid domain is:

```text
robvoto.com
```

Current intended routing:

```text
robvoto.com              -> GitHub Pages personal-brand site
www.robvoto.com          -> GitHub Pages personal-brand site
jobhunter.robvoto.com    -> AWS EC2 public IP 32.236.144.98
knowme.robvoto.com       -> AWS EC2 public IP 32.236.144.98
```

`knowme.robvoto.com` is reserved in DNS for KnowMe, but KnowMe is not installed on this EC2 host yet.

### EC2 host

```text
OS: Ubuntu 24.04.4 LTS
Public IP: 32.236.144.98
Private IP: 172.31.18.71
Host: ip-172-31-18-71
SSH user: ubuntu
```

### SSH access

SSH access is restricted by client IP in the AWS security group.

```text
Current known client/home IP: 202.92.118.81/32
```

This IP is dynamic and may change when the internet provider changes the connection. If SSH stops working, check the current public IP from the client machine and update the EC2 security group inbound SSH rule.

Do not open SSH to:

```text
0.0.0.0/0
```

Connect from Windows PowerShell:

```powershell
ssh -i "E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem" ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com
```

The helper script on the PC may contain the same command:

```powershell
.\connectAws.ps1
```

If PowerShell says the identity file is not accessible, check that the key exists at:

```powershell
Test-Path "E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem"
```

### Job Hunter runtime

```text
Application path: /home/ubuntu/job-hunter-agent
Dependency manager: uv
Project environment: /home/ubuntu/job-hunter-agent/.venv
Dependency source: /home/ubuntu/job-hunter-agent/pyproject.toml
Environment file: /etc/job-hunter/job-hunter.env
Persistent data: /var/lib/job-hunter/data
Persistent output: /var/lib/job-hunter/output
Service: job-hunter.service
Service command: /usr/bin/xvfb-run ... /home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
Local bind: 127.0.0.1:8765
Docker: not used
Xvfb: installed
xvfb-run: installed
xauth: installed
Xvfb wired into service: yes
```

`/var/lib/job-hunter` is mounted on a separate data disk.

### Persistent storage contract

```text
/var/lib/job-hunter                     EBS-backed persistent volume
/var/lib/job-hunter/data                JOB_HUNTER_DATA_DIR
/var/lib/job-hunter/output              JOB_HUNTER_OUTPUT_DIR
/var/lib/job-hunter/data/job_hunter.db  JOB_HUNTER_DB_PATH
/etc/job-hunter/job-hunter.env          root-owned runtime config and secrets
```

Keep runtime data on the EBS-backed volume and keep `/etc/job-hunter/job-hunter.env` out of git. The environment file should stay restricted with:

```bash
sudo chown root:ubuntu /etc/job-hunter/job-hunter.env
sudo chmod 640 /etc/job-hunter/job-hunter.env
```

### Nginx routing

Nginx listens on port 80. Job Hunter remains private on localhost and must not expose port `8765` directly to the internet.

Current intended nginx routing:

```text
jobhunter.robvoto.com -> 127.0.0.1:8765
knowme.robvoto.com    -> 127.0.0.1:8001  # reserved; KnowMe not installed yet
unknown hostnames     -> 404
```

The old catch-all behaviour `server_name _` proxying all traffic to Job Hunter should not be used as the main Job Hunter route because it can accidentally route future subdomains to the wrong app.

---

## 1. Environment boundary

### Local development machine

Use local paths only for editing, testing, committing, and pushing code:

```text
Windows: E:\Programming\job-hunter-agent
WSL:     /mnt/e/Programming/job-hunter-agent
```

The supported local runtime is WSL + uv:

```bash
cd /mnt/e/Programming/job-hunter-agent
./scripts/run-jobhunter.sh debug
./scripts/run-jobhunter.sh no-llm
./scripts/run-jobhunter.sh test
```

Do not diagnose AWS production by looking only at the local VS Code terminal.

### AWS production machine

The production app runs on EC2, not on the local PC.

Canonical production layout:

```text
/home/ubuntu/job-hunter-agent                 application code and uv-managed .venv
/var/lib/job-hunter/data                      persistent DB and app data
/var/lib/job-hunter/output                    persistent runtime output if used
/var/log/job-hunter                           server logs if configured
/etc/job-hunter/job-hunter.env                production environment file
/etc/systemd/system/job-hunter.service        systemd service
```

All production diagnostics must be run on the EC2 host after connecting to the actual instance.

Do not use AWS CloudShell as if it were the EC2 server. CloudShell is a separate container-like shell and will not show the EC2 app process, filesystem, systemd service, or Playwright runtime.

---

## 2. Production architecture

Current production model:

```text
Browser / domain
    -> Porkbun DNS
    -> Nginx on EC2 port 80
    -> Job Hunter FastAPI on 127.0.0.1:8765
    -> SQLite DB on /var/lib/job-hunter/data
    -> Playwright Chromium for SEEK scraping
```

Baseline:

```text
Ubuntu Server 24.04 LTS
Python 3.12
uv dependency sync from pyproject.toml
FastAPI
systemd service
Nginx reverse proxy
SQLite on EBS-backed persistent storage
Playwright Chromium
Xvfb available for headed browser execution on Linux servers
```

No Docker baseline. Do not start Docker troubleshooting unless a future deployment explicitly moves to Docker.

---

## 3. Required AWS resources

Use:

```text
EC2 instance: Ubuntu Server 24.04 LTS
Instance type: t3.micro or equivalent for test/staging
Public IP currently in use: 32.236.144.98
Elastic IP: recommended for stable production access
EBS data volume: recommended for persistent app data
Security group: SSH 22 from your IP only, HTTP 80, HTTPS 443
```

Do not expose port `8765` publicly. The app must stay bound to localhost behind Nginx.

Expected access path:

```text
Internet/domain -> Nginx 80 -> 127.0.0.1:8765
```

---

## 4. Connect to the real EC2 host

From Windows PowerShell:

```powershell
ssh -i "E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem" ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com
```

Then:

```bash
cd /home/ubuntu/job-hunter-agent
```

---

## 5. Normal production deploy

Use the installed helper:

```bash
deploy-jobhunter
```

Repo-managed script:

```bash
scripts/ec2/deploy-jobhunter.sh
```

What it does:

1. pulls latest code with `git pull --ff-only`
2. installs uv if missing
3. runs `uv sync --no-dev`
4. installs Playwright Chromium with `uv run playwright install chromium`
5. loads `/etc/job-hunter/job-hunter.env`
6. applies `/var/lib/job-hunter` data/output/DB paths
7. upgrades DB/config seed with `uv run python -m job_hunter_agent.db_seed --upgrade`
8. checks required runtime knowledge files
9. verifies the systemd service contract
10. restarts `job-hunter.service`
11. prints service status, recent logs, and HTTP health check

Do not manually pip install production dependencies. Add dependencies to `pyproject.toml`, commit, push, then run `deploy-jobhunter`.

---

## 6. Service installation / repair

If the service file drifts, reinstall the repo-managed service:

```bash
cd /home/ubuntu/job-hunter-agent
sudo -E ./scripts/ec2/install-jobhunter-service.sh
sudo systemctl restart job-hunter
```

The service should use:

```text
/usr/bin/xvfb-run
/home/ubuntu/job-hunter-agent/.venv/bin/python
```

uv prepares `.venv`; systemd uses the stable interpreter path in that environment.

---

## 7. Diagnostics

Service status:

```bash
sudo systemctl status job-hunter --no-pager
```

Recent logs:

```bash
sudo journalctl -u job-hunter -n 120 --no-pager
```

Health check from EC2:

```bash
curl -I http://127.0.0.1:8765/start
```

Check uv and environment:

```bash
cd /home/ubuntu/job-hunter-agent
uv --version
uv run python --version
```

Check runtime paths:

```bash
sudo systemctl cat job-hunter
```

---

## 8. KnowMe planned runtime

KnowMe should be deployed cheaply on the same EC2 instance, not a second instance, unless capacity becomes a problem.

Planned target:

```text
Application path: /home/ubuntu/knowme
Environment file: /etc/knowme/knowme.env
Persistent data: /var/lib/knowme/data
Service: knowme.service
Local bind: 127.0.0.1:8001
Public route: knowme.robvoto.com
```

KnowMe is currently not installed on this EC2 instance.
