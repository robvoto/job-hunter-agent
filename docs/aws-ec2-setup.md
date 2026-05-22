# AWS EC2 Setup Guide for Job Hunter

This guide describes the clean first-time setup for running Job Hunter on AWS EC2.

It is a setup document, not a troubleshooting diary.

## Target setup

```text
AWS EC2 Ubuntu 24.04 LTS server
Python 3.12
Project virtual environment in .venv
Private GitHub repo cloned with GitHub token
App tested locally on 127.0.0.1:8765
Later: systemd + Nginx + HTTPS + database
```

## Required platform

Use this platform for Job Hunter:

```text
Ubuntu Server 24.04 LTS
Python 3.12
pandas 2.x
Playwright Chromium
```

Do not choose preview/non-LTS Ubuntu releases for this setup. Use Ubuntu 24.04 LTS so Python and Playwright stay on a supported path.

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
Storage: default is fine for learning
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

Do not expose the app port `8765` publicly for normal use. The app should later sit behind Nginx.

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

## 8. Clone the private GitHub repo

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

Clone:

```bash
cd ~
git clone https://github.com/robvoto/job-hunter-agent.git
cd ~/job-hunter-agent
```

When prompted:

```text
Username: robvoto
Password: paste GitHub token
```

Never paste the token into chat or screenshots. If exposed, revoke it.

## 9. Git credential handling on EC2

Windows Git Credential Manager is not available on Ubuntu EC2.

For short-term learning on EC2:

```bash
git config --global credential.helper store
```

Then run a pull and enter the token once:

```bash
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

## 10. Create the project virtual environment

```bash
cd ~/job-hunter-agent
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python --version
which python
```

Expected:

```text
Python 3.12.x
/home/ubuntu/job-hunter-agent/.venv/bin/python
```

## 11. Install project dependencies

With `.venv` active:

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

For this project, `python-jobspy` requires pandas below version 3, so `requirements.txt` should use pandas 2.x:

```text
pandas>=2.0.0,<3
```

If the virtual environment is active, `which pip` should return:

```text
/home/ubuntu/job-hunter-agent/.venv/bin/pip
```

## 12. Install Playwright browser

With `.venv` active:

```bash
python -m playwright install chromium
```

If Linux libraries are missing:

```bash
sudo .venv/bin/python -m playwright install-deps chromium
python -m playwright install chromium
```

## 13. Smoke test the app

Manual run is only a smoke test.

```bash
cd ~/job-hunter-agent
source .venv/bin/activate
python -m job_hunter_agent.fastapi_app
```

In another SSH session:

```bash
curl http://127.0.0.1:8765/start
```

Expected: HTML response.

## 14. Production-style next steps

After the smoke test works:

```text
Create a systemd service
Configure Nginx reverse proxy
Expose only 80/443 publicly
Keep the app bound to 127.0.0.1:8765
Add environment variable handling
Add logs
Later: database/RDS
Later: HTTPS/domain
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
source ~/job-hunter-agent/.venv/bin/activate
python --version
which python
```

Expected:

```text
Python 3.12.x
/home/ubuntu/job-hunter-agent/.venv/bin/python
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
