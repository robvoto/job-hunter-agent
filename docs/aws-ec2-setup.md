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

The production runtime is on AWS EC2. Local development happens on the PC in VS Code.

---

## Current production state - 2026-06-07

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
Virtual environment: /home/ubuntu/job-hunter-agent/.venv
Environment file: /etc/job-hunter/job-hunter.env
Persistent data: /var/lib/job-hunter/data
Persistent output: /var/lib/job-hunter/output
Service: job-hunter.service
Service command: /home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
Local bind: 127.0.0.1:8765
Docker: not used
Xvfb: installed
xvfb-run: installed
xauth: installed
Xvfb wired into service: no
```

`/var/lib/job-hunter` is mounted on a separate data disk.

### Nginx routing

Nginx listens on port 80. Job Hunter remains private on localhost and must not expose port `8765` directly to the internet.

Current intended nginx routing:

```text
jobhunter.robvoto.com -> 127.0.0.1:8765
knowme.robvoto.com    -> 127.0.0.1:8001  # reserved; KnowMe not installed yet
unknown hostnames     -> 404
```

The old catch-all behaviour `server_name _` proxying all traffic to Job Hunter should not be used as the main Job Hunter route because it can accidentally route future subdomains to the wrong app.

### KnowMe planned runtime

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

---

## 1. Environment boundary

### Local development machine

Use local paths only for editing, testing, committing, and pushing code:

```text
Windows: E:\Programming\job-hunter-agent
WSL:     /mnt/e/Programming/job-hunter-agent
```

Local development may run:

```bash
python -m job_hunter_agent.fastapi_app --debug
python -m job_hunter_agent.source_connector --no-llm
python -m pytest
```

Do not diagnose AWS production by looking only at the local VS Code terminal.

### AWS production machine

The production app runs on EC2, not on the local PC.

Canonical production layout:

```text
/home/ubuntu/job-hunter-agent                 application code and .venv
/var/lib/job-hunter/data                      persistent DB and app data
/var/lib/job-hunter/output                    persistent runtime output if used
/var/log/job-hunter                           server logs
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

After login, confirm you are on the EC2 host:

```bash
hostname
pwd
lsb_release -a
systemctl --version
ls -la /home/ubuntu/job-hunter-agent
```

If `systemctl` says:

```text
System has not been booted with systemd as init system
```

then you are probably not inside the actual EC2 host OS. You may be in AWS CloudShell, a container, or another restricted shell. Stop diagnosing there and reconnect to the actual EC2 instance.

---

## 5. Install base packages on EC2

Run on the EC2 host:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl wget build-essential python3 python3-venv python3-pip nginx tmux xvfb xauth
```

Check:

```bash
git --version
python3 --version
nginx -v
tmux -V
which Xvfb
which xvfb-run
which xauth
```

Expected Python on Ubuntu 24.04:

```text
Python 3.12.x
```

---

## 6. Create production directories

Run on EC2:

```bash
sudo mkdir -p /home/ubuntu/job-hunter-agent
sudo mkdir -p /var/lib/job-hunter/data
sudo mkdir -p /var/lib/job-hunter/output
sudo mkdir -p /var/log/job-hunter
sudo mkdir -p /etc/job-hunter

sudo chown -R ubuntu:ubuntu /home/ubuntu/job-hunter-agent
sudo chown -R ubuntu:ubuntu /var/lib/job-hunter
sudo chown -R ubuntu:ubuntu /var/log/job-hunter
```

Check:

```bash
ls -ld /home/ubuntu/job-hunter-agent /var/lib/job-hunter/data /var/log/job-hunter /etc/job-hunter
```

---

## 7. Optional EBS data volume

For production-like use, mount a separate EBS volume at:

```text
/var/lib/job-hunter
```

After attaching the volume, identify it:

```bash
lsblk
```

Format once only:

```bash
sudo mkfs.ext4 /dev/nvme1n1
```

Mount:

```bash
sudo mkdir -p /var/lib/job-hunter
sudo mount /dev/nvme1n1 /var/lib/job-hunter
sudo chown -R ubuntu:ubuntu /var/lib/job-hunter
```

Persist mount:

```bash
sudo blkid /dev/nvme1n1
```

Add the real UUID to `/etc/fstab`:

```bash
UUID=<actual-uuid> /var/lib/job-hunter ext4 defaults,nofail 0 2
```

Test:

```bash
sudo mount -a
df -h /var/lib/job-hunter
```

Expected: `/var/lib/job-hunter` is on the EBS disk, not only the root disk.

---

## 8. Clone or update the repo on EC2

Clone once:

```bash
git clone https://github.com/robvoto/job-hunter-agent.git /home/ubuntu/job-hunter-agent
```

For a private repo, use GitHub credentials or a deploy key. Do not paste tokens into logs, screenshots, docs, or chat.

For later deployments:

```bash
cd /home/ubuntu/job-hunter-agent
git pull
```

The source of truth for code is GitHub. The local PC edits and pushes. EC2 pulls the production version.

---

## 9. Create Python virtual environment

Run on EC2:

```bash
cd /home/ubuntu/job-hunter-agent
python3 -m venv .venv
source .venv/bin/activate
python --version
which python
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Expected:

```text
/home/ubuntu/job-hunter-agent/.venv/bin/python
```

---

## 10. Install Playwright Chromium

Run on EC2 with the venv active:

```bash
cd /home/ubuntu/job-hunter-agent
source .venv/bin/activate
python -m playwright install chromium
sudo /home/ubuntu/job-hunter-agent/.venv/bin/python -m playwright install-deps chromium
python -m playwright install chromium
```

Check:

```bash
python - <<'PY'
from playwright.sync_api import sync_playwright
print('playwright import ok')
PY
```

---

## 11. Production environment file

Create:

```bash
sudo nano /etc/job-hunter/job-hunter.env
```

Required shape:

```env
JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data
JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output
JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db
JOB_HUNTER_BASE_URL=http://jobhunter.robvoto.com
JOB_HUNTER_ADMIN_EMAIL=<admin-email>
JOB_HUNTER_AUTH_SESSION_SECRET=<random-secret>
JOB_HUNTER_CORS_ALLOWED_ORIGINS=http://jobhunter.robvoto.com
JOB_HUNTER_SESSION_COOKIE_SECURE=true
```

Optional, only when OAuth is configured:

```env
JOB_HUNTER_GOOGLE_CLIENT_ID=<google-client-id>
JOB_HUNTER_GOOGLE_CLIENT_SECRET=<google-client-secret>
```

Optional, only when live LLM review is enabled:

```env
OPENAI_API_KEY=<server-side-key>
```

Protect the file:

```bash
sudo chown root:ubuntu /etc/job-hunter/job-hunter.env
sudo chmod 640 /etc/job-hunter/job-hunter.env
```

Never commit `.env` files or secrets to GitHub.

Inspect environment variable names without printing values:

```bash
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value job-hunter)/environ | grep '^JOB_HUNTER_' | sed 's/=.*/=***/'
```

---

## 12. Seed or upgrade the database

Run after first install and after schema/config changes:

```bash
cd /home/ubuntu/job-hunter-agent
source .venv/bin/activate
set -a
source /etc/job-hunter/job-hunter.env
set +a
python -m job_hunter_agent.db_seed --upgrade
```

Use `--overwrite` only for a deliberate hard reset because it can wipe approved local knowledge.

---

## 13. Current systemd service

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

Expected:

```text
Active: active (running)
```

---

## 14. Xvfb for non-headless Playwright on AWS

SEEK may behave differently when Playwright runs in normal headless mode. The preferred AWS setup is:

```text
Playwright headless setting: OFF
Linux server display: Xvfb virtual display
```

This lets Chromium run as a headed browser even though the EC2 server has no physical screen.

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

Do not add Playwright stealth patches as the first fix. First make headed Chromium under Xvfb reliable.

---

## 15. Configure Nginx reverse proxy

Create:

```bash
sudo nano /etc/nginx/sites-available/job-hunter
```

Recommended config:

```nginx
server {
    listen 80;
    server_name jobhunter.robvoto.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80 default_server;
    server_name _;
    return 404;
}
```

Enable:

```bash
sudo ln -sf /etc/nginx/sites-available/job-hunter /etc/nginx/sites-enabled/job-hunter
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Test locally on EC2:

```bash
curl -I http://127.0.0.1/
curl -I http://127.0.0.1:8765/start
```

Do not expose port `8765` directly to the internet.

---

## 16. ngrok temporary HTTPS path

Use ngrok only for temporary testing. The preferred public route is `jobhunter.robvoto.com` through nginx.

Flow:

```text
Browser -> https://<ngrok-host> -> EC2 localhost:80 -> Nginx -> 127.0.0.1:8765
```

Start manually:

```bash
ngrok http 80
```

Or run in tmux:

```bash
tmux new-session -d -s ngrok "ngrok http 80"
tmux attach -t ngrok
```

Detach without stopping:

```text
Ctrl+B then D
```

When the ngrok URL changes, update both:

```text
/etc/job-hunter/job-hunter.env -> JOB_HUNTER_BASE_URL and JOB_HUNTER_CORS_ALLOWED_ORIGINS
Google OAuth redirect URI -> https://<ngrok-host>/api/auth/google/callback
```

Then restart:

```bash
sudo systemctl restart job-hunter
```

---

## 17. Deployment from local PC to AWS

Local PC / VS Code:

```bash
cd /mnt/e/Programming/job-hunter-agent
git status
git add .
git commit -m "Update Job Hunter"
git push
```

AWS EC2:

```bash
ssh -i "E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem" ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com
cd /home/ubuntu/job-hunter-agent
git pull
source .venv/bin/activate
pip install -r requirements.txt
set -a
source /etc/job-hunter/job-hunter.env
set +a
python -m job_hunter_agent.db_seed --upgrade
sudo systemctl restart job-hunter
sudo systemctl status job-hunter --no-pager
```

Check logs:

```bash
sudo journalctl -u job-hunter -n 80 --no-pager
tail -n 80 /var/log/job-hunter/app.log
```

---

## 18. Production diagnostics

Run these only on the real EC2 host.

### Confirm app directory

```bash
pwd
ls -la /home/ubuntu/job-hunter-agent
cd /home/ubuntu/job-hunter-agent
git status --short
git branch --show-current
git log -1 --oneline
```

### Confirm service

```bash
sudo systemctl status job-hunter --no-pager
sudo systemctl cat job-hunter
sudo journalctl -u job-hunter -n 100 --no-pager
```

### Confirm listening ports

```bash
sudo ss -tlnp | grep -E ':80|:443|:8765'
```

Expected:

```text
nginx listening on 80/443 if configured
python/app listening on 127.0.0.1:8765
```

### Confirm Python/FastAPI process

```bash
ps auxww | grep -E "job_hunter_agent|uvicorn|fastapi|python" | grep -v grep
```

### Confirm Playwright/Chromium/Xvfb

During a scrape run:

```bash
ps auxww | grep -E "Xvfb|xvfb|chromium|chrome|playwright" | grep -v grep
```

Expected for AWS non-headless scraping after Xvfb is wired:

```text
xvfb-run or Xvfb is active for the service
Chromium appears during scrape
```

Check environment names without leaking values:

```bash
PID=$(systemctl show -p MainPID --value job-hunter)
sudo tr '\0' '\n' < /proc/$PID/environ | grep -E '^(JOB_HUNTER_|DISPLAY|OPENAI_)' | sed 's/=.*/=***/'
```

### Confirm Nginx

```bash
sudo nginx -t
sudo tail -n 80 /var/log/nginx/access.log
sudo tail -n 80 /var/log/nginx/error.log
```

---

## 19. How to interpret bad diagnostics

If you see only this listening address:

```text
127.0.0.11:<port>
```

that usually points to a container/DNS stub environment, not the real EC2 app stack.

If these return nothing:

```bash
ps aux | grep -E "fastapi|uvicorn|python|gunicorn" | grep -v grep
ps aux | grep -E "chromium|chrome|playwright" | grep -v grep
sudo ss -tlnp | grep -E ':80|:443|:8765'
```

then Job Hunter is not visibly running in that shell environment.

If this fails:

```bash
systemctl status job-hunter
```

with:

```text
System has not been booted with systemd as init system
```

then you are not diagnosing the real EC2 host OS, or systemd is unavailable in that environment.

Correct next step:

```text
Reconnect to the EC2 instance itself using SSH or EC2 Session Manager, then run diagnostics from /home/ubuntu/job-hunter-agent.
```

---

## 20. Useful commands

Restart app:

```bash
sudo systemctl restart job-hunter
```

View service:

```bash
sudo systemctl status job-hunter --no-pager
```

Live logs:

```bash
sudo journalctl -u job-hunter -f
```

Recent logs:

```bash
sudo journalctl -u job-hunter --since "10 minutes ago" --no-pager
```

Check app directly:

```bash
curl -I http://127.0.0.1:8765/start
```

Check through Nginx:

```bash
curl -I http://127.0.0.1/
```

Check Xvfb installation:

```bash
which Xvfb
which xvfb-run
which xauth
```

Check Xvfb process after it is wired:

```bash
pgrep -af "Xvfb|xvfb"
```

Check Chromium during scrape:

```bash
pgrep -af "chromium|chrome"
```

---

## 21. Do not do

Do not:

```text
Create a second AWS setup document
Keep old updated/final copies beside the canonical file
Use Docker unless the deployment model is deliberately changed
Expose port 8765 publicly
Store production state in /home/ubuntu accidentally outside the repo and configured data paths
Commit .env files or secrets
Paste tokens into docs, tickets, screenshots, or chat
Use AWS CloudShell diagnostics as proof of EC2 runtime state
Use local VS Code terminal as proof of AWS runtime state
Rely on headless Playwright for SEEK if headed + Xvfb is required
Add stealth patches before validating Xvfb headed mode
Move the production app path without documenting a migration
```

---

## 22. Future improvements

Only after the current EC2 deployment is stable:

```text
Add HTTPS for jobhunter.robvoto.com and knowme.robvoto.com
Add automated EBS snapshots or S3 backup exports
Send logs to CloudWatch
Use a deploy key or GitHub Actions deployment flow
Move from repo clone to packaged release
Consider PostgreSQL/RDS only after the data model stabilizes
```
