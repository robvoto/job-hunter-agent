# AWS EC2 Setup Guide for Job Hunter

This is the single canonical AWS operations document for Job Hunter.

Do not create parallel copies such as `aws-ec2-setup.updated.md`, `aws-ec2-setup.final.md`, or one-off notes. Update this file only.

---

## Current production status

Last verified from the real EC2 host over SSH.

```text
Host OS: Ubuntu 24.04.4 LTS
EC2 private host: ip-172-31-18-71
Production app path: /home/ubuntu/job-hunter-agent
Python runtime: /home/ubuntu/job-hunter-agent/.venv/bin/python
FastAPI entry point: python -m job_hunter_agent.fastapi_app
systemd service: job-hunter.service
App bind: http://127.0.0.1:8765
Persistent data: /var/lib/job-hunter
Environment file: /etc/job-hunter/job-hunter.env
Log directory: /var/log/job-hunter
Docker: not used
Xvfb: installed
xvfb-run: installed
xauth: installed
Xvfb wired into service: no
```

Current service command:

```ini
ExecStart=/home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
```

Current process check showed:

```text
/home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
```

No `Xvfb` process was running at the time of verification.

---

## Local versus production boundary

Local development happens on the PC:

```text
Windows path: E:\Programming\job-hunter-agent
WSL path: /mnt/e/Programming/job-hunter-agent
IDE: VS Code
```

Production runs on AWS EC2:

```text
/home/ubuntu/job-hunter-agent
```

Do not diagnose production from local VS Code paths. Do not diagnose production from AWS CloudShell. Production checks must run inside the real EC2 instance shell.

If an AWS assistant, CloudShell session, or generic terminal cannot see `/home/ubuntu/job-hunter-agent`, it is not inspecting the production app.

---

## SSH access

SSH is intentionally restricted to the owner current public IP as a `/32` rule.

Latest known working public IP:

```text
202.92.118.81/32
```

The ISP public IP can change. When it changes, SSH may time out even when the EC2 server is healthy.

If SSH times out:

1. Open AWS Console.
2. Go to EC2 → Instances → select the Job Hunter instance.
3. Open Security → Security Group → Inbound rules.
4. Update the SSH rule:

```text
Type: SSH
Protocol: TCP
Port: 22
Source: current My IP /32
```

Do not open SSH to `0.0.0.0/0`.

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

---

## Canonical production layout

Use this layout for the current production instance:

```text
/home/ubuntu/job-hunter-agent        application code and virtual environment
/home/ubuntu/job-hunter-agent/.venv  Python virtual environment
/var/lib/job-hunter/data             persistent app data
/var/lib/job-hunter/output           persistent app output
/var/log/job-hunter                  log directory
/etc/job-hunter/job-hunter.env       server-only environment file
/etc/systemd/system/job-hunter.service systemd service file
```

Do not introduce a second production app path unless performing a deliberate migration.

---

## Environment file

Current service uses:

```ini
EnvironmentFile=/etc/job-hunter/job-hunter.env
```

The service also sets the core paths explicitly:

```ini
Environment="JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data"
Environment="JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output"
Environment="JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db"
```

Never commit secrets or `.env` files to GitHub.

Protect the env file:

```bash
sudo chown root:ubuntu /etc/job-hunter/job-hunter.env
sudo chmod 640 /etc/job-hunter/job-hunter.env
```

Inspect environment variable names without printing values:

```bash
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value job-hunter)/environ | grep '^JOB_HUNTER_' | sed 's/=.*/=***/'
```

---

## Current systemd service

View the live service file:

```bash
sudo systemctl cat job-hunter
```

Current verified service:

```ini
# /etc/systemd/system/job-hunter.service
[Unit]
Description=Job Hunter FastAPI App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/job-hunter-agent
EnvironmentFile=/etc/job-hunter/job-hunter.env
Environment="PATH=/home/ubuntu/job-hunter-agent/.venv/bin"
Environment="JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data"
Environment="JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output"
Environment="JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db"
ExecStart=/home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Manage the service:

```bash
sudo systemctl status job-hunter --no-pager
sudo systemctl restart job-hunter
sudo journalctl -u job-hunter -n 80 --no-pager
sudo journalctl -u job-hunter -f
```

---

## Quick production health check

Run this only inside the real EC2 host:

```bash
pwd
whoami
hostname
cat /etc/os-release | head -20

echo "---- app paths ----"
ls -la /home/ubuntu/job-hunter-agent 2>&1
ls -la /etc/job-hunter 2>&1
ls -la /var/lib/job-hunter 2>&1
ls -la /var/log/job-hunter 2>&1

echo "---- service ----"
sudo systemctl status job-hunter --no-pager 2>&1

echo "---- ports ----"
sudo ss -tlnp | grep -E ':80|:443|:8765|:8000' || true

echo "---- processes ----"
ps auxww | grep -E 'job_hunter|uvicorn|fastapi|playwright|chromium|nginx|ngrok|Xvfb|xvfb' | grep -v grep || true
```

Expected core result:

```text
job-hunter.service active/running
python -m job_hunter_agent.fastapi_app
app listening on 127.0.0.1:8765
```

---

## Nginx boundary

The app should stay bound to localhost:

```text
127.0.0.1:8765
```

External traffic should go through Nginx and/or a tunnel/domain:

```text
Internet/ngrok/domain → Nginx 80/443 → 127.0.0.1:8765 app
```

Check Nginx:

```bash
sudo nginx -t
sudo systemctl status nginx --no-pager
sudo ss -tlnp | grep -E ':80|:443'
```

Do not expose port `8765` directly to the internet.

---

## Playwright and Xvfb

Reason for Xvfb:

SEEK appears more reliable when Playwright runs Chromium in non-headless mode. EC2 has no physical screen. Xvfb provides a virtual display so Chromium can run as a headed browser without a monitor.

Verified installed binaries:

```text
/usr/bin/Xvfb
/usr/bin/xvfb-run
/usr/bin/xauth
```

Current status:

```text
Installed: yes
Wired into job-hunter.service: no
```

Current production service still starts FastAPI directly:

```ini
ExecStart=/home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
```

Do not change this casually. When approved, back up the service file before wiring Xvfb.

Approved change pattern:

```bash
sudo cp /etc/systemd/system/job-hunter.service /etc/systemd/system/job-hunter.service.bak.$(date +%Y%m%d-%H%M%S)

sudo sed -i 's|^ExecStart=.*|ExecStart=/usr/bin/xvfb-run -a -s "-screen 0 1400x900x24" /home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app|' /etc/systemd/system/job-hunter.service

sudo systemctl daemon-reload
sudo systemctl restart job-hunter
sudo systemctl status job-hunter --no-pager
```

Verify after restart:

```bash
sudo systemctl cat job-hunter
ps auxww | grep -E 'Xvfb|xvfb|job_hunter|python' | grep -v grep
```

Expected `ExecStart` after Xvfb is wired:

```ini
ExecStart=/usr/bin/xvfb-run -a -s "-screen 0 1400x900x24" /home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
```

Rollback:

```bash
ls -1 /etc/systemd/system/job-hunter.service.bak.*
sudo cp /etc/systemd/system/job-hunter.service.bak.<timestamp> /etc/systemd/system/job-hunter.service
sudo systemctl daemon-reload
sudo systemctl restart job-hunter
sudo systemctl status job-hunter --no-pager
```

Admin setting alignment after Xvfb is wired:

```text
Run browser headless = OFF
Viewport = 1400 x 900
```

---

## Updating production code

Run from the real EC2 host:

```bash
cd /home/ubuntu/job-hunter-agent
git status
git pull
source .venv/bin/activate
pip install -r requirements.txt
python -m job_hunter_agent.db_seed --upgrade
sudo systemctl restart job-hunter
sudo systemctl status job-hunter --no-pager
```

Only run `db_seed --overwrite` for a deliberate reset because it can wipe user-approved additions.

---

## Logs

Service logs:

```bash
sudo journalctl -u job-hunter -n 100 --no-pager
sudo journalctl -u job-hunter -f
```

Application log directory:

```bash
ls -la /var/log/job-hunter
```

Runtime output directory:

```bash
ls -la /var/lib/job-hunter/output
```

---

## Common failure interpretations

### SSH timeout

Likely cause: the EC2 Security Group SSH rule is still restricted to an old home IP.

Fix: update SSH TCP 22 source to current `My IP /32`.

### `KeyPair-JobHunter.pem not accessible`

Likely cause: running SSH from the wrong Windows directory or using a relative key path.

Fix: use the full key path:

```powershell
ssh -i "E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem" ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com
```

### AWS CloudShell cannot find the app

Expected. CloudShell is not the EC2 host.

Fix: connect to the real EC2 instance using SSH or Session Manager.

### `System has not been booted with systemd`

You are not in the normal EC2 host OS, or you are in a container-like shell. Do not use that shell for production diagnosis.

### Headless OFF fails on AWS

If Xvfb is not wired into the service, headed Playwright has no display. Wire Xvfb only after approval and with backup/rollback.

---

## Do not do

```text
Do not keep multiple AWS setup docs.
Do not diagnose production from CloudShell.
Do not diagnose production from local VS Code paths.
Do not expose port 8765 publicly.
Do not open SSH to 0.0.0.0/0.
Do not commit .env files or secrets.
Do not introduce Docker unless a future architecture decision explicitly changes the deployment model.
Do not move the production app path from /home/ubuntu/job-hunter-agent without documenting a migration.
```
