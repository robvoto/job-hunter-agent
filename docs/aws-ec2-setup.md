# Job Hunter Agent — AWS EC2 Production Setup

This is the single canonical AWS deployment document for Job Hunter.

Do not keep parallel AWS setup documents. This file lives in the repository at
`docs/aws-ec2-setup.md`.

The production runtime is on AWS EC2. Local development happens in the native
repository checkout.

---

## Current production state - 2026-06-19

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

Connect from your local shell:

```bash
ssh -i "<path-to-KeyPair-JobHunter.pem>" ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com
```

If the shell says the identity file is not accessible, check that the key path
you passed exists before reconnecting.

```bash
test -f "<path-to-KeyPair-JobHunter.pem>"
```

### Job Hunter runtime

```text
Application path: /home/ubuntu/job-hunter-agent
Virtual environment: /home/ubuntu/job-hunter-agent/.venv
Environment file: /etc/job-hunter/job-hunter.env
Persistent data: /var/lib/job-hunter/data
Persistent output: /var/lib/job-hunter/output
Service: job-hunter.service
ExecStart: /home/ubuntu/job-hunter-agent/scripts/ec2/run-jobhunter-browser-session.sh
Local bind: 127.0.0.1:8765
Docker: not used
Xvfb wired into service: YES
noVNC/VNC wired into service: YES (localhost only)
Playwright headless setting: OFF (headed in the AWS browser session)
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

Keep the runtime data on the EBS-backed volume and keep `/etc/job-hunter/job-hunter.env`
out of git. The environment file should stay restricted with:

```bash
sudo chown root:ubuntu /etc/job-hunter/job-hunter.env
sudo chmod 640 /etc/job-hunter/job-hunter.env
```

### Runtime seed boundary

Fresh AWS builds must seed only the approved repo-managed JSON set.

- DB/bootstrap seeding is run via `python -m job_hunter_agent.db_seed`.
- The seed flow copies only the explicit approved runtime manifest from `data/knowledge/` plus the required O*NET taxonomy JSON files.
- Do not replace this with a recursive "copy every JSON file under data/knowledge" step.
- Local examples, private JSON files, or ad-hoc scratch files under `data/knowledge` must never become production runtime data by accident.

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
/home/robvoto/projects/job-hunter-agent
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

From your local shell:

```bash
ssh -i "<path-to-KeyPair-JobHunter.pem>" ubuntu@ec2-32-236-144-98.ap-southeast-2.compute.amazonaws.com
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
which x11vnc
which websockify
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

## 9. Run the first deploy

`deploy-jobhunter-release` handles venv, dependencies, Playwright browser + OS libs, service install, and DB seed in one command for an explicit release tag:

```bash
cd /home/ubuntu/job-hunter-agent
sudo bash scripts/ec2/install-helpers.sh
deploy-jobhunter-release vX.Y.Z
```

`install-helpers.sh` is only needed once to put `deploy-jobhunter-release` on PATH. After that, every future update is just:

```bash
use-ubuntu
deploy-jobhunter-release vX.Y.Z
```

---

## 10. Production environment file

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

## 12. DB seed (manual)

`deploy-jobhunter-release` runs this automatically. Only run manually for a hard reset:

```bash
# upgrade (safe — preserves approved knowledge)
uv run python -m job_hunter_agent.db_seed --upgrade

# overwrite (destructive — wipes approved knowledge)
uv run python -m job_hunter_agent.db_seed --overwrite
```

Set production env vars first if running outside the service context:

```bash
export JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data
export JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db
```

---

## 13. Systemd service

The repo-managed service file is `scripts/ec2/job-hunter.service`. `deploy-jobhunter-release` installs it automatically.

Current service:

```ini
[Unit]
Description=Job Hunter FastAPI App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/job-hunter-agent
EnvironmentFile=/etc/job-hunter/job-hunter.env
Environment="PATH=/home/ubuntu/job-hunter-agent/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="TZ=Australia/Sydney"
Environment="JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data"
Environment="JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output"
Environment="JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db"
ExecStart=/home/ubuntu/job-hunter-agent/scripts/ec2/run-jobhunter-browser-session.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Manage:

```bash
sudo systemctl restart job-hunter && jobhunter-status
sudo systemctl restart job-hunter && jobhunter-status --verbose
sudo systemctl restart job-hunter && jobhunter-status -f   # + live log tail
```

---

## 14. AWS browser session for non-headless Playwright

Xvfb is active. The service runs Chromium in headed mode via a virtual display and exposes it through localhost-only noVNC/VNC so SEEK scraping can pause for human verification when needed.

```text
Installed: yes
Wired into job-hunter.service: YES (AWS browser session launcher)
Playwright headless setting: OFF
Viewport: 1400x900
Browser access: localhost-only noVNC/VNC
```

`deploy-jobhunter-release` installs and maintains this automatically via `scripts/ec2/install-aws-browser-session.sh`, `scripts/ec2/start-aws-browser-session.sh`, and `scripts/ec2/job-hunter.service`.

Verify during a scrape:

```bash
ps auxww | grep -E 'Xvfb|xvfb|chromium|chrome' | grep -v grep
```

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

Local (push code):

```bash
git add <files>
git commit -m "..."
git push
```

AWS EC2 (deploy):

```bash
use-ubuntu
deploy-jobhunter-release vX.Y.Z
```

That's it. `deploy-jobhunter-release` fetches the requested release tag, checks out that exact tagged commit, verifies the tag matches `pyproject.toml`, syncs deps, updates service, seeds DB, restarts, rebuilds saved workspace output on startup, and health-checks.

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
Xvfb and the AWS browser session launcher are active for the service
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
which x11vnc
which websockify
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

---

## Production deploy command

Every deploy — first install or update — is the same single command:

```bash
use-ubuntu
deploy-jobhunter-release vX.Y.Z
```

`deploy-jobhunter-release` is safe to run repeatedly for the same explicit release tag. It:

1. Removes known old server scripts
2. Fetches the requested remote release tag and checks out the exact tagged commit
3. Installs/updates uv if missing
4. Syncs Python dependencies (`uv sync --no-dev`)
5. Installs Playwright Chromium browser binary
6. Installs Playwright OS system libraries (`libatk`, `libgbm`, etc.)
7. Installs repo-managed helpers into `/usr/local/bin`
8. Installs repo-managed AWS browser-session packages, launcher scripts, and systemd service (full PATH)
9. Runs `db_seed --upgrade`
10. Restarts `job-hunter.service`
11. Rebuilds saved workspace output during startup so the rendered page matches the current code
12. Waits for a successful health-check

## Non-production AWS test deploy command

For AWS smoke tests or debugging that should not cut a release tag, use the separate ref-based helper:

```bash
use-ubuntu
deploy-jobhunter-latest
deploy-jobhunter-latest <branch-or-sha>
```

Examples:

```bash
deploy-jobhunter-latest
deploy-jobhunter-latest main
deploy-jobhunter-latest feature/my-fix
deploy-jobhunter-latest ef720a7
```

`deploy-jobhunter-latest` fetches `origin`, resolves the requested branch/ref/commit to an exact commit, checks out detached `HEAD`, validates `pyproject.toml` / `uv.lock` / UI version integrity, then runs the same dependency, seed, restart, and health-check steps as the production deploy helper. With no argument it targets the latest commit from `main`.

Rules:

1. Use `deploy-jobhunter-release vX.Y.Z` for production.
2. Use `deploy-jobhunter-latest` or `deploy-jobhunter-latest <branch-or-sha>` only for staging, smoke tests, or debugging.
3. Do not move or reuse an existing production tag to get newer code onto AWS.
4. If a test ref proves good and should become production, cut a normal release tag and deploy that tag.

## 23. Production checklist

Before calling the environment ready for use, check these in order:

1. Confirm `/var/lib/job-hunter` is mounted on the EBS data disk, not only the root volume.
2. Confirm `/etc/job-hunter/job-hunter.env` exists, is not committed to git, and keeps the `640` permissions above.
3. Run `deploy-jobhunter-release vX.Y.Z` or `sudo systemctl restart job-hunter` after code or env changes.
4. Verify service health with `sudo systemctl status job-hunter --no-pager`, `sudo journalctl -u job-hunter -n 80 --no-pager`, and `curl -I http://127.0.0.1:8765/start`.
5. Confirm Nginx proxies the public host to `127.0.0.1:8765` and does not expose FastAPI directly.
6. Confirm browser access uses HTTPS for `jobhunter.robvoto.com`.
7. Confirm the backup plan exists, either EBS snapshots or S3 exports of `/var/lib/job-hunter`.

## AWS Session Manager access

Preferred access is AWS Systems Manager Session Manager because the home IP changes frequently and SSH client-IP allowlisting becomes unreliable.

Session Manager initially logs in as `ssm-user`. Switch to the app owner before running app commands:

```bash
use-ubuntu
```

If the helper does not exist yet, the equivalent command is:

```bash
sudo -iu ubuntu
```

Do not open SSH to `0.0.0.0/0`.

## AWS health-check helper

Create a helper command named:

```bash
jobhunter-status
```

It should run:

```bash
sudo systemctl status job-hunter --no-pager
sudo journalctl -u job-hunter -n 80 --no-pager
curl -I http://127.0.0.1:8765/start
```

Meaning:

- `systemctl status` checks whether systemd thinks the service is alive.
- `journalctl` shows why Python failed or what the app logged.
- `curl` proves the web app is actually listening on port `8765`.

`Active: active (running)` alone is not enough proof immediately after restart. Always confirm with `curl`.

## Runtime seed and dependency rules

The app reads production runtime files from `JOB_HUNTER_DATA_DIR`, currently:

```text
/var/lib/job-hunter/data
```

Versioned source JSON files live in the repo under `/home/ubuntu/job-hunter-agent/data`. Deployment must not rely on manual copying.

`python -m job_hunter_agent.db_seed --upgrade` is responsible for syncing required runtime-managed files into `JOB_HUNTER_DATA_DIR`, including:

```text
config/global_settings.json
defaults/user_settings.json
```

If code imports a Python package, that package must be declared in `pyproject.toml`. Do not manually install packages on AWS as the permanent solution. Fix `pyproject.toml`, cut a release tag, then run `deploy-jobhunter-release vX.Y.Z`.

## Version-controlled EC2 helper scripts

EC2 helper scripts are version-controlled under:

```text
scripts/ec2/
```

Current helpers:

```text
scripts/ec2/deploy-jobhunter-release.sh        # deploy an explicit Git tag and health-check it
scripts/ec2/deploy-jobhunter-latest.sh         # deploy latest main by default or a branch/commit for staging/debug
scripts/ec2/jobhunter-status.sh        # concise health summary, optional verbose/follow logs
scripts/ec2/install-helpers.sh         # install wrappers into /usr/local/bin
scripts/ec2/enable-https-jobhunter.sh  # enable HTTPS with certbot/nginx for jobhunter.robvoto.com
```

Install or refresh helper commands on EC2:

```bash
cd /home/ubuntu/job-hunter-agent
sudo bash scripts/ec2/install-helpers.sh
```

Installed commands:

```text
/usr/local/bin/deploy-jobhunter-release
/usr/local/bin/deploy-jobhunter-latest
/usr/local/bin/jobhunter-status
/usr/local/bin/use-ubuntu
```

After installing helpers, normal deployment remains:

```bash
use-ubuntu
deploy-jobhunter-release vX.Y.Z
```

`deploy-jobhunter-release` intentionally waits briefly after restart before checking health because `systemctl` can report `active` before Python has finished importing and binding to port `8765`.

## HTTPS enablement

The app is currently healthy over HTTP when this check succeeds:

```bash
curl -I http://jobhunter.robvoto.com/start
```

For production, browser access should use HTTPS:

```text
https://jobhunter.robvoto.com/start
```

Enable HTTPS on EC2 with:

```bash
cd /home/ubuntu/job-hunter-agent
sudo bash scripts/ec2/enable-https-jobhunter.sh
```

Prerequisites:

- `jobhunter.robvoto.com` DNS points to the EC2 public IP.
- AWS security group allows inbound `80` and `443`.
- Nginx routes `jobhunter.robvoto.com` to `127.0.0.1:8765`.

Do not expose FastAPI port `8765` publicly. HTTPS terminates at Nginx; FastAPI remains private on EC2 localhost.

---

## Current AWS access and OAuth truth - 2026-06-10

### Access method

Primary AWS access is now **AWS Systems Manager Session Manager**, not direct SSH.

Reason:

- the home/client IP changes frequently
- SSH allowlisting becomes unreliable
- SSM avoids opening SSH broadly
- SSM gives direct access to the EC2 host without changing the security group every time

Normal access flow:

```bash
use-ubuntu
cd /home/ubuntu/job-hunter-agent
```

Session Manager logs in as `ssm-user`. `use-ubuntu` switches to the `ubuntu` app owner.

SSH is now a fallback/emergency path only. Do not make SSH the default operational workflow. Do not open SSH to `0.0.0.0/0`.

### Current Job Hunter production URLs

```text
Public app:      https://jobhunter.robvoto.com/start
Internal app:    http://127.0.0.1:8765/start  # only from inside EC2
Public HTTP:     http://jobhunter.robvoto.com/start redirects/serves through Nginx
```

FastAPI must remain private on EC2 localhost. Nginx is the public front door and handles HTTPS.

### HTTPS state

Job Hunter HTTPS has been enabled for:

```text
jobhunter.robvoto.com
```

Browser access should use:

```text
https://jobhunter.robvoto.com/start
```

Do not test Job Hunter by using `knowme.robvoto.com`. KnowMe is a separate subdomain and requires its own app deployment, Nginx route, and certificate.

### KnowMe state

`knowme.robvoto.com` is reserved but is not the Job Hunter route.

If `https://knowme.robvoto.com` shows `NET::ERR_CERT_COMMON_NAME_INVALID`, that does not mean Job Hunter is broken. It means the certificate/subdomain does not match KnowMe yet.

KnowMe needs a separate deployment before it can be considered healthy.

### Google OAuth production redirect

Google login must redirect back to Job Hunter production, not ngrok and not KnowMe.

Required Google OAuth redirect URI:

```text
https://jobhunter.robvoto.com/api/auth/google/callback
```

Required Google OAuth JavaScript origin:

```text
https://jobhunter.robvoto.com
```

Old ngrok callback URLs such as this are not production-safe:

```text
https://griminess-magazine-landowner.ngrok-free.dev/api/auth/google/callback
```

If login sends the browser to an ngrok URL, the Google OAuth client still has the old callback selected or the production environment still has an old base URL.

Check AWS env without exposing secrets:

```bash
sudo grep -E "JOB_HUNTER_BASE_URL|JOB_HUNTER_CORS_ALLOWED_ORIGINS|GOOGLE" /etc/job-hunter/job-hunter.env | sed 's/CLIENT_SECRET=.*/CLIENT_SECRET=***/'
```

Expected:

```text
JOB_HUNTER_BASE_URL=https://jobhunter.robvoto.com
JOB_HUNTER_CORS_ALLOWED_ORIGINS=https://jobhunter.robvoto.com
```

After changing `/etc/job-hunter/job-hunter.env`, restart and check:

```bash
sudo systemctl restart job-hunter
jobhunter-status
```

### Latest production health checks

Run from EC2:

```bash
jobhunter-status
```

Or manually:

```bash
curl -I http://127.0.0.1:8765/start
curl -I https://jobhunter.robvoto.com/start
```

Expected healthy result is a redirect to login:

```text
HTTP 302
location: /login?next=%2Fstart
```

That means the app is alive and auth is enforcing login correctly.

---

## Deployment runtime path fix - 2026-06-10

The live `job-hunter.service` defines these production runtime paths inline in systemd:

```text
JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data
JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output
JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db
```

These values may not appear in `/etc/job-hunter/job-hunter.env`, because that file mainly holds secrets and public URL settings.

`deploy-jobhunter-release` must therefore apply the same production runtime path defaults before running:

```bash
python -m job_hunter_agent.db_seed --upgrade
```

Otherwise the seed step writes required runtime files into the repo `data/` folder instead of the real production data directory.

The symptom was onboarding crashing with:

```text
RuntimeError: locations_au.json is missing
```

Root cause:

```text
locations_au.json existed in the repo, but not in /var/lib/job-hunter/data/knowledge/
```

Permanent fix:

- `db_seed.py` includes `data/knowledge/locations_au.json` in required runtime file sync.
- `deploy-jobhunter-release` exports the production runtime path defaults before seed.
- `deploy-jobhunter-release` verifies `/var/lib/job-hunter/data/knowledge/locations_au.json` exists before restarting the service.
- `install-helpers.sh` strips any UTF-8 BOM from installed helper scripts so Ubuntu executes the shebang correctly.

Do not manually copy `locations_au.json` as the permanent fix. Fix repo seed/deploy logic, then run:

```bash
cd /home/ubuntu/job-hunter-agent
sudo bash scripts/ec2/install-helpers.sh
deploy-jobhunter-release vX.Y.Z
```
