# AWS EC2 Setup Notes for Job Hunter

This document records the AWS setup path used for the Job Hunter learning deployment.

It is not a production runbook yet. It captures the exact practical steps taken so far, the problems encountered, and the fixes applied.

## Current goal

Deploy the latest `robvoto/job-hunter-agent` code from GitHub onto an AWS EC2 Ubuntu instance for learning and experimentation.

## Repository

```text
https://github.com/robvoto/job-hunter-agent.git
```

The repository is private, so EC2 needs GitHub authentication to clone it.

## AWS account setup

### 1. Created AWS account

A new AWS account was created for learning. The account has AWS credits available.

### 2. Added a low budget alert

A low AWS Budget was recommended first to avoid surprise costs.

Recommended starting budget:

```text
Budget type: Cost budget
Period: Monthly
Amount: $1 USD
Alert: 80% actual spend
Optional alert: 100% forecasted spend
```

Important: the budget does not block spending. It only warns early that something is generating AWS cost. The credits still pay for eligible AWS usage.

## Hosting choice discussion

We compared:

```text
Render      = simple free-ish app hosting
Lightsail  = simplified AWS VPS
EC2         = full AWS virtual server
Lambda      = serverless functions, not ideal for browser-based scraping
RDS         = managed relational database
```

Decision for now:

```text
Use EC2 for the learning deployment.
Do not create a separate Lightsail instance.
Use PostgreSQL/RDS later if needed.
Avoid SQLite for this project because we want a proper database path.
```

## EC2 instance

An EC2 instance was created and confirmed as running.

Confirmed details from the session:

```text
Instance state: running
Public access: yes
Operating system: Ubuntu
SSH username: ubuntu
Public DNS used: ec2-184-73-80-9.compute-1.amazonaws.com
Private hostname seen after login: ip-172-31-9-76
```

The instance was reachable over SSH from the local machine after fixing the `.pem` key permissions.

## Security group access

Inbound rules observed:

```text
SSH    TCP 22   source: user's public IP /32
HTTP   TCP 80   source: 0.0.0.0/0
HTTPS  TCP 443  source: 0.0.0.0/0
```

Important notes:

- SSH should stay restricted to `My IP` or a known `/32` IP.
- HTTP and HTTPS can be public later when the app is ready.
- Do not open SSH to `0.0.0.0/0` unless temporarily required and explicitly understood.

## Connection methods tried

### EC2 Instance Connect

Tried first from AWS Console:

```text
EC2 → Instances → select instance → Connect → EC2 Instance Connect
```

This failed with an SSH connection error. The likely practical cause was the corporate/work network blocking direct SSH-style access.

### AWS Systems Manager Session Manager

Session Manager was discussed as the better AWS-internal browser shell option when corporate networks block SSH.

Requirement:

```text
EC2 IAM role with policy: AmazonSSMManagedInstanceCore
```

AWS Console path:

```text
EC2 → Instances → select instance → Connect → Session Manager
```

If disabled, attach/create an IAM role with `AmazonSSMManagedInstanceCore`, then wait a few minutes.

### Local SSH from Windows PowerShell

A local script was used:

```powershell
.\connectAws.ps1
```

First connection prompt:

```text
The authenticity of host ... can't be established.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Answer used:

```text
yes
```

This adds the EC2 host fingerprint to the local `known_hosts` file.

## Windows `.pem` private key permission fix

SSH initially rejected the private key because the `.pem` file had overly broad permissions.

Error seen:

```text
WARNING: UNPROTECTED PRIVATE KEY FILE!
Bad permissions.
```

Fix attempted from PowerShell in the project directory:

```powershell
cd E:\Programming\job-hunter-agent

icacls .\KeyPair-JobHunter.pem /inheritance:r
icacls .\KeyPair-JobHunter.pem /remove:g "Users" "Authenticated Users" "Everyone"
icacls .\KeyPair-JobHunter.pem /grant:r "$($env:USERNAME):R"
```

If an unknown SID appears in the error, remove it explicitly:

```powershell
icacls .\KeyPair-JobHunter.pem /remove:g "*S-1-5-21-918216458-3027456311-2496836407-332114931"
```

Validate permissions:

```powershell
icacls .\KeyPair-JobHunter.pem
```

Expected result: the current Windows user has read permission and broad groups are removed.

## SSH username issue

When testing SSH, this failed:

```text
ubuntu@ec2-184-73-80-9.compute-1.amazonaws.com: Permission denied (publickey)
```

We checked the OS assumption:

- Amazon Linux usually uses `ec2-user`.
- Ubuntu uses `ubuntu`.

Final successful connection showed:

```text
ubuntu@ip-172-31-9-76:~$
```

So the instance is Ubuntu and `ubuntu` is the correct username.

## Server package setup

Once connected to EC2, package updates were checked and installed using `apt`, because the instance is Ubuntu.

Commands:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip
```

Validated versions:

```bash
git --version
python3 --version
python3 -m pip --version
```

Observed:

```text
git version 2.53.0
Python 3.14.4
pip 25.1.1 from /usr/lib/python3/dist-packages/pip (python 3.14)
```

## GitHub token setup

Because the repository is private, cloning from EC2 requires GitHub authentication.

A GitHub personal access token was created.

Important security note:

- A token was accidentally shown in a screenshot.
- Any token shown in chat or screenshots must be treated as exposed.
- Exposed tokens must be deleted/revoked immediately.
- Never paste tokens into chat.

Recommended fine-grained token setup:

```text
Repository access: Only selected repositories
Selected repository: job-hunter-agent
Repository permissions:
  Contents: Read-only
  Metadata: Read-only
Expiration: 90 days preferred for learning
```

For classic token fallback:

```text
Scope: repo
Expiration: 90 days
```

## Cloning the repository on EC2

Run from the EC2 terminal:

```bash
cd ~
git clone https://github.com/robvoto/job-hunter-agent.git
```

When prompted:

```text
Username: robvoto
Password: paste the GitHub token
```

The token should be pasted as one continuous string with no spaces.

After cloning:

```bash
cd ~/job-hunter-agent
git status
ls -la
```

## Common errors and fixes

### `apt: command not found`

This means the instance is probably not Ubuntu, likely Amazon Linux.

Amazon Linux commands:

```bash
sudo dnf update -y
sudo dnf install -y git python3 python3-pip
```

Fallback:

```bash
sudo yum update -y
sudo yum install -y git python3 python3-pip
```

In our actual setup, the instance turned out to be Ubuntu, so `apt` was correct.

### `fatal: could not create work tree dir 'job-hunter-agent': Permission denied`

This means the clone command was run from a directory where the current user cannot write.

Fix:

```bash
whoami
pwd
ls -ld .
cd ~
git clone https://github.com/robvoto/job-hunter-agent.git
```

Do not use `sudo git clone` unless absolutely necessary because it creates ownership problems later.

### `Permission denied (publickey)`

Possible causes:

```text
Wrong SSH username
Wrong .pem key file
.pem permissions too broad
Instance was created with a different key pair
```

Checks:

```text
EC2 → Instances → select instance → Details → Key pair name
```

Usernames:

```text
Ubuntu: ubuntu
Amazon Linux: ec2-user
```

### GitHub password rejected

GitHub does not accept account passwords for Git over HTTPS.

Use:

```text
Username: robvoto
Password: GitHub personal access token
```

## Current status

Completed:

```text
AWS account created
EC2 instance created
Security group inspected
SSH key permission issue fixed
Connected to Ubuntu EC2 instance
Git installed
Python installed
pip installed
GitHub token created for private repo access
```

Next step:

```bash
cd ~
git clone https://github.com/robvoto/job-hunter-agent.git
cd ~/job-hunter-agent
ls -la
```

After that, inspect the repository structure and identify the correct application entry point before installing/running dependencies.

## Do not do yet

Avoid these until the basic app is understood:

```text
Do not create RDS yet
Do not create Lambda yet
Do not create Lightsail now
Do not expose app ports broadly before the app runs locally on EC2
Do not run random install scripts without checking the repo structure
```
