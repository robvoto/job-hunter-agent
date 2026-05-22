# AWS EC2 Setup Guide for Job Hunter

This guide describes the clean first-time setup for running Job Hunter on AWS EC2.

The deployment model assumes a small EBS-backed root volume and a production-style service lifecycle, so keep storage, logging, and recovery choices simple and explicit.

It is a setup document, not a troubleshooting diary.

## Directory layout

```text
/opt/job-hunter/app        application code and virtualenv
/var/lib/job-hunter/data   persistent app data (EBS-backed)
/var/log/job-hunter        application logs
```

These are the only three locations the app touches at runtime. Nothing lives in the home directory.

## Required platform

```text
Ubuntu Server 24.04 LTS
Python 3.12
pandas 2.x
Playwright Chromium
```

Do not choose preview/non-LTS Ubuntu releases. Use Ubuntu 24.04 LTS so Python and Playwright stay on a supported path.

## 1. AWS account safety

Create a budget before building services.

AWS Console:

```text
Billing and Cost Management → Budgets → Create budget
```

Recommended starter budget:

```text
Budget type: Cost budget
Period: Monthly
Amount: $1 USD
Alert: 80% actual spend
Optional alert: 100% forecasted spend
```

A budget does not block spending. It only warns early.

## 2. Create EC2 instance

AWS Console:

```text
EC2 → Instances → Launch instance
```

Recommended settings:

```text
Name: job-hunter-ec2
AMI: Ubuntu Server 24.04 LTS
Instance type: t3.micro or free-tier equivalent
Key pair: KeyPair-JobHunter
Storage: small EBS root volume is enough for the current workload
```

Ubuntu SSH username:

```text
ubuntu
```

## 3. Security group

Create or select a security group with these inbound rules:

```text
SSH    TCP 22   Source: your public IP /32 only
HTTP   TCP 80   Source: 0.0.0.0/0 later, when Nginx is ready
HTTPS  TCP 443  Source: 0.0.0.0/0 later, when TLS is ready
```

Do not expose the app port `8765` publicly. The app sits behind Nginx.

Target public path:

```text
Internet → Nginx 80/443 → app on 127.0.0.1:8765
```

## 4. Optional IAM role for Session Manager

Session Manager is useful when SSH is blocked by a corporate network.

Create or attach an IAM role to the EC2 instance with this AWS managed policy:

```text
AmazonSSMManagedInstanceCore
```

Attach role path:

```text
EC2 → Instances → select instance → Actions → Security → Modify IAM role
```

Connect path:

```text
EC2 → Instances → select instance → Connect → Session Manager
```

## 5. Connect with SSH from Windows PowerShell

Example:

```powershell
ssh -i E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem ubuntu@ec2-public-dns.amazonaws.com
```

If prompted about host authenticity, type:

```text
yes
```

This stores the EC2 host fingerprint in the local `known_hosts` file.

## 6. Fix Windows PEM permissions if SSH rejects the key

If SSH rejects the key with an unprotected private key warning, fix file permissions from PowerShell:

```powershell
cd E:\Programming\job-hunter-agent
icacls .\KeyPair-JobHunter.pem /inheritance:r
icacls .\KeyPair-JobHunter.pem /remove:g "Users" "Authenticated Users" "Everyone"
icacls .\KeyPair-JobHunter.pem /grant:r "$($env:USERNAME):R"
```

Check:

```powershell
icacls .\KeyPair-JobHunter.pem
```

Expected: the current Windows user has read permission and broad groups are removed.

## 7. Install base Ubuntu packages

On the EC2 instance:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl wget build-essential python3 python3-venv python3-pip
```

Check:

```bash
git --version
python3 --version
```

Expected Python version on Ubuntu 24.04 LTS:

```text
Python 3.12.x
```

## 8. Create the directory layout

Create all three directories and set ownership before cloning or creating data:

```bash
sudo mkdir -p /opt/job-hunter/app
sudo mkdir -p /var/lib/job-hunter/data
sudo mkdir -p /var/log/job-hunter
sudo chown -R ubuntu:ubuntu /opt/job-hunter
sudo chown -R ubuntu:ubuntu /var/lib/job-hunter
sudo chown -R ubuntu:ubuntu /var/log/job-hunter
```

Check:

```bash
ls -ld /opt/job-hunter/app /var/lib/job-hunter/data /var/log/job-hunter
```

Expected: all three directories exist and are owned by `ubuntu`.

## 9. Clone the private GitHub repo

Repository:

```text
https://github.com/robvoto/job-hunter-agent.git
```

Create a GitHub personal access token with repository read access.

Recommended fine-grained token:

```text
Repository access: Only selected repositories
Selected repository: job-hunter-agent
Repository permissions:
  Contents: Read-only
  Metadata: Read-only
Expiration: 90 days for learning
```

Clone directly into `/opt/job-hunter/app`:

```bash
git clone https://github.com/robvoto/job-hunter-agent.git /opt/job-hunter/app
```

When prompted:

```text
Username: robvoto
Password: paste GitHub token
```

Never paste the token into chat or screenshots. If exposed, revoke it.

## 10. Git credential handling on EC2

Windows Git Credential Manager is not available on Ubuntu EC2.

For short-term learning on EC2:

```bash
git config --global credential.helper store
```

Then run a pull and enter the token once:

```bash
cd /opt/job-hunter/app
git pull
```

Check:

```bash
git config --global --get credential.helper
```

Expected:

```text
store
```

Later, replace this with a deploy key or cleaner deployment process.

## 11. Create the project virtual environment

```bash
cd /opt/job-hunter/app
python3 -m venv .venv
source .venv/bin/activate
python --version
which python
```

Expected:

```text
Python 3.12.x
/opt/job-hunter/app/.venv/bin/python
```

## 12. Install project dependencies

With `.venv` active:

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

For this project, `python-jobspy` requires pandas below version 3, so `requirements.txt` uses pandas 2.x:

```text
pandas>=2.0.0,<3
```

Check:

```bash
which pip
```

Expected:

```text
/opt/job-hunter/app/.venv/bin/pip
```

## 13. Install Playwright browser

With `.venv` active:

```bash
python -m playwright install chromium
```

If Linux libraries are missing:

```bash
sudo /opt/job-hunter/app/.venv/bin/python -m playwright install-deps chromium
python -m playwright install chromium
```

## 14. Smoke test the app

The smoke test requires the environment variables to be set. Export them for this session only before running:

```bash
export JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data
export JOB_HUNTER_OUTPUT_DIR=/var/log/job-hunter
export JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/app.db

cd /opt/job-hunter/app
source .venv/bin/activate
python -m job_hunter_agent.fastapi_app
```

In another SSH session:

```bash
curl http://127.0.0.1:8765/start
```

Expected: HTML response.

Do not use `export` in normal operation. Env vars belong in the systemd service file only.

## 15. Create the systemd service

This is how the app runs in production. All configuration lives here — never in Python files.

Create the service unit file:

```bash
sudo nano /etc/systemd/system/job-hunter.service
```

Paste this content exactly:

```ini
[Unit]
Description=Job Hunter Agent
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/job-hunter/app
Environment=JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data
Environment=JOB_HUNTER_OUTPUT_DIR=/var/log/job-hunter
Environment=JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/app.db
ExecStart=/opt/job-hunter/app/.venv/bin/uvicorn job_hunter_agent.fastapi_app:app --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/job-hunter/app.log
StandardError=append:/var/log/job-hunter/app.log

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable job-hunter
sudo systemctl start job-hunter
sudo systemctl status job-hunter
```

Expected: `active (running)`.

### To change any configuration

Edit the service file and reload. Never edit a Python file:

```bash
sudo nano /etc/systemd/system/job-hunter.service
sudo systemctl daemon-reload
sudo systemctl restart job-hunter
```

### Environment variables

| Variable | Purpose | Value on EC2 |
|---|---|---|
| `JOB_HUNTER_DATA_DIR` | Persistent app data | `/var/lib/job-hunter/data` |
| `JOB_HUNTER_OUTPUT_DIR` | Log output directory | `/var/log/job-hunter` |
| `JOB_HUNTER_DB_PATH` | SQLite database file | `/var/lib/job-hunter/data/app.db` |

All three must be set. The app raises an explicit error if `JOB_HUNTER_DB_PATH` is missing.

## 16. Production-style next steps

After the service is running:

```text
Configure Nginx reverse proxy
Expose only 80/443 publicly (keep app bound to 127.0.0.1:8765)
Add HTTPS / domain via Certbot
```

## Quick checks

Confirm OS:

```bash
lsb_release -a
```

Expected:

```text
Ubuntu 24.04 LTS
```

Confirm Python:

```bash
python3 --version
```

Expected:

```text
Python 3.12.x
```

Confirm venv Python:

```bash
source /opt/job-hunter/app/.venv/bin/activate
python --version
which python
```

Expected:

```text
Python 3.12.x
/opt/job-hunter/app/.venv/bin/python
```

Check service logs:

```bash
tail -f /var/log/job-hunter/app.log
```

## Do not do yet

Until the app works locally:

```text
Do not create RDS
Do not create Lambda
Do not create Lightsail
Do not expose port 8765 publicly
Do not configure Nginx before the local smoke test passes
```
