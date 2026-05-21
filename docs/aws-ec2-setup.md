# AWS EC2 Setup Guide for Job Hunter

This is the repeatable setup guide for running Job Hunter on AWS EC2 with Ubuntu.

It is not a chat log. It documents the intended setup path and the important lessons learned.

## Target setup

```text
AWS EC2 Ubuntu server
Python 3.12 installed with pyenv
Project virtual environment in .venv
Private GitHub repo cloned with GitHub token
App tested locally on 127.0.0.1:8765
Later: systemd + Nginx + HTTPS + database
```

## Important Python decision

Do not use Python 3.14 for this project yet.

The EC2 image used in this setup came with Python 3.14.4. The project dependency stack is not ready for that version at the moment. During install, pip attempted to build NumPy from source and failed. We also saw pandas/numpy dependency resolution issues.

Use Python 3.12 for now.

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

Recommended:

```text
Name: job-hunter-ec2
AMI: Ubuntu Server
Instance type: t3.micro or free-tier equivalent
Key pair: KeyPair-JobHunter
Storage: default is fine for learning
```

Ubuntu SSH username:

```text
ubuntu
```

Amazon Linux username, if using Amazon Linux instead:

```text
ec2-user
```

## 3. Security group

Use a tight security group.

```text
SSH    TCP 22   Source: your public IP /32 only
HTTP   TCP 80   Source: 0.0.0.0/0 later, when Nginx is ready
HTTPS  TCP 443  Source: 0.0.0.0/0 later, when TLS is ready
```

Do not expose the app port `8765` publicly for normal use. The app should later sit behind Nginx.

Final direction:

```text
Internet → Nginx 80/443 → app on 127.0.0.1:8765
```

## 4. Connection options

### EC2 Instance Connect

AWS Console:

```text
EC2 → Instances → select instance → Connect → EC2 Instance Connect
```

This can fail on corporate networks that block SSH-style access.

### Session Manager

Use AWS Systems Manager Session Manager when company networks block SSH.

Requirement: attach an IAM role to the EC2 instance with:

```text
AmazonSSMManagedInstanceCore
```

IAM role path:

```text
EC2 → Instances → select instance → Actions → Security → Modify IAM role
```

Connection path:

```text
EC2 → Instances → select instance → Connect → Session Manager
```

### Local SSH from Windows PowerShell

Example:

```powershell
ssh -i E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem ubuntu@ec2-public-dns.amazonaws.com
```

If prompted about host authenticity, type:

```text
yes
```

## 5. Fix Windows PEM permissions

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

## 6. Install base Ubuntu packages

On the EC2 instance:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl wget build-essential
```

Check:

```bash
git --version
```

## 7. Install Python 3.12 using pyenv

The EC2 Ubuntu image may not provide Python 3.12 through apt. If this fails:

```bash
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

with package not found errors, use pyenv.

Install build dependencies:

```bash
sudo apt update && sudo apt install -y build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev \
libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

Install pyenv runtime if available:

```bash
sudo apt install -y pyenv-runtime
```

Install Python 3.12.8:

```bash
pyenv install 3.12.8
pyenv versions
```

Expected: `3.12.8` is listed.

## 8. Clone the private GitHub repo

Repo:

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

Windows Git Credential Manager is not available on Ubuntu EC2. This command does not work there:

```bash
git config --global credential.helper manager
```

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

## 10. Set project Python to 3.12

Inside the repo:

```bash
cd ~/job-hunter-agent
pyenv local 3.12.8
python --version
```

Expected:

```text
Python 3.12.8
```

Create the virtual environment:

```bash
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
python --version
which python
```

Expected Python path:

```text
/home/ubuntu/job-hunter-agent/.venv/bin/python
```

## 11. Install project dependencies

With `.venv` active:

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

If a dev requirements file exists and is needed:

```bash
pip install -r requirements-dev.txt
```

If you see `externally-managed-environment`, the virtual environment is not active.

Fix:

```bash
source .venv/bin/activate
which pip
```

Expected:

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

If you see `No module named playwright`, dependencies were not installed into the active venv.

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

## 14. Next production-style steps

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

## Common errors

### `.venv/bin/activate: No such file or directory`

The venv does not exist yet.

```bash
python -m venv .venv
source .venv/bin/activate
```

### `externally-managed-environment`

You are using system pip, not venv pip.

```bash
source .venv/bin/activate
which pip
```

### NumPy or pandas failure on Python 3.14

Symptoms:

```text
NumPy builds from source
c++ fatal error: Killed
ResolutionImpossible
No matching distributions for numpy/pandas
```

Fix: use Python 3.12 via pyenv.

### `Permission denied (publickey)`

Check:

```text
Correct username
Correct key pair
PEM file permissions
EC2 key pair name
```

### GitHub password rejected

Use a GitHub token, not the GitHub account password.

## Do not do yet

Until the app works locally:

```text
Do not create RDS
Do not create Lambda
Do not create Lightsail
Do not expose port 8765 publicly
Do not configure Nginx before the local smoke test passes
```
