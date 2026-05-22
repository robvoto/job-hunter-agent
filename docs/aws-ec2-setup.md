# AWS EC2 Setup Guide for Job Hunter

This guide describes the clean test/staging setup for running Job Hunter on AWS EC2.

## Target setup

```text
AWS EC2 Ubuntu 24.04 LTS server
Python 3.12
Project virtual environment in .venv
Private GitHub repo cloned from GitHub
Persistent app data on a separate EBS volume mounted at /var/lib/job-hunter
SQLite database stored on the EBS data volume
systemd runs the FastAPI app as a service
Nginx exposes the app on public HTTP port 80
Google OAuth provides login
Later: HTTPS + domain + package-based deployment + backups
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

```text
EC2 → Instances → Launch instance
```

Recommended settings:

```text
Name: job-hunter-ec2
AMI: Ubuntu Server 24.04 LTS
Instance type: t3.micro or free-tier equivalent
Key pair: KeyPair-JobHunter
Storage: default root disk is fine for OS and code
```

Ubuntu SSH username:

```text
ubuntu
```

## 3. Security group

Create or select a security group with these inbound rules:

```text
SSH    TCP 22   Source: your public IP /32 only
HTTP   TCP 80   Source: 0.0.0.0/0 for the test site
HTTPS  TCP 443  Source: 0.0.0.0/0 later, when TLS is configured
```

Do not expose the app port `8765` publicly. The app should stay private behind Nginx.

Target path:

```text
Internet → Nginx 80/443 → app on 127.0.0.1:8765
```

## 4. Allocate a stable public address

Do not rely on the default EC2 public IP for OAuth because it can change.

For this test instance, allocate an Elastic IP:

```text
EC2 → Network & Security → Elastic IPs → Allocate Elastic IP address
```

Associate it with the EC2 instance:

```text
Select Elastic IP → Actions → Associate Elastic IP address → choose the Job Hunter EC2 instance
```

Use this Elastic IP for:

```text
JOB_HUNTER_BASE_URL=http://<elastic-ip>
Google OAuth redirect URI=http://<elastic-ip>/api/auth/google/callback
```

Later, replace the Elastic IP URL with a real domain and HTTPS.

## 5. Create persistent EBS data volume

The EC2 root disk is not the right place for application data. Use a separate EBS volume for persistent Job Hunter data.

Create the volume:

```text
EC2 → Elastic Block Store → Volumes → Create volume
```

Recommended settings:

```text
Volume type: gp3
Size: 10 GiB for learning/test
IOPS: 3000 baseline
Throughput: 125 MiB/s baseline
Availability Zone: same as the EC2 instance
Name tag: job-hunter-data
Encryption: enabled if available
```

Attach it:

```text
Select volume → Actions → Attach volume
Instance: job-hunter EC2 instance
Device name: /dev/sdf
```

`/dev/sdf` is the AWS attach label. On Ubuntu/Nitro EC2 it usually appears as `/dev/nvme1n1`.

Identify the new disk:

```bash
lsblk
```

Expected shape:

```text
nvme0n1      8G   disk   root disk
nvme1n1     10G   disk   new EBS data disk
```

Format the new EBS disk once:

```bash
sudo mkfs.ext4 /dev/nvme1n1
```

Create the application data mount point:

```bash
sudo mkdir -p /var/lib/job-hunter
```

Mount the EBS volume:

```bash
sudo mount /dev/nvme1n1 /var/lib/job-hunter
```

Verify it is mounted correctly:

```bash
df -h /var/lib/job-hunter
```

Expected: the filesystem should be `/dev/nvme1n1`, not `/dev/root`.

```text
/dev/nvme1n1   10G   ...   /var/lib/job-hunter
```

## 6. Make the EBS mount survive reboot

Get the EBS filesystem UUID:

```bash
sudo blkid /dev/nvme1n1
```

Example output:

```text
/dev/nvme1n1: UUID="8c180247-0d33-4769-89a9-84135a414f34" BLOCK_SIZE="4096" TYPE="ext4"
```

Add the mount to `/etc/fstab` using the actual UUID:

```bash
echo 'UUID=8c180247-0d33-4769-89a9-84135a414f34 /var/lib/job-hunter ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

Test the mount entry:

```bash
sudo umount /var/lib/job-hunter
sudo mount -a
sudo systemctl daemon-reload
df -h /var/lib/job-hunter
```

Expected:

```text
/dev/nvme1n1   10G   ...   /var/lib/job-hunter
```

`nofail` lets the instance boot even if the data volume is temporarily missing.

## 7. Create data and log folders

Create the app data and log folders:

```bash
sudo mkdir -p /var/lib/job-hunter/data
sudo mkdir -p /var/lib/job-hunter/output
sudo mkdir -p /var/log/job-hunter
sudo chown -R ubuntu:ubuntu /var/lib/job-hunter /var/log/job-hunter
```

Verify permissions:

```bash
ls -ld /var/lib/job-hunter /var/lib/job-hunter/data /var/log/job-hunter
```

Expected owner:

```text
ubuntu ubuntu
```

Optional write test:

```bash
touch /var/lib/job-hunter/data/write-test.txt
ls -l /var/lib/job-hunter/data/write-test.txt
rm /var/lib/job-hunter/data/write-test.txt
```

## 8. Optional IAM role for Session Manager

Session Manager is useful when SSH is blocked by a corporate network.

Attach an IAM role to the EC2 instance with this AWS managed policy:

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

## 9. Connect with SSH from Windows PowerShell

Example:

```powershell
ssh -i E:\Programming\job-hunter-agent\KeyPair-JobHunter.pem ubuntu@ec2-public-dns.amazonaws.com
```

If prompted about host authenticity, type:

```text
yes
```

If SSH rejects the key with an unprotected private key warning, fix permissions from PowerShell:

```powershell
cd E:\Programming\job-hunter-agent
icacls .\KeyPair-JobHunter.pem /inheritance:r
icacls .\KeyPair-JobHunter.pem /remove:g "Users" "Authenticated Users" "Everyone"
icacls .\KeyPair-JobHunter.pem /grant:r "$($env:USERNAME):R"
```

## 10. Install base Ubuntu packages

On the EC2 instance:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl wget build-essential python3 python3-venv python3-pip nginx
```

Check:

```bash
git --version
python3 --version
nginx -v
```

Expected Python version on Ubuntu 24.04 LTS:

```text
Python 3.12.x
```

## 11. Clone the private GitHub repo

Repository:

```text
https://github.com/robvoto/job-hunter-agent.git
```

Clone:

```bash
cd ~
git clone https://github.com/robvoto/job-hunter-agent.git
cd ~/job-hunter-agent
```

For a private repo, use a GitHub credential with read access when prompted.

For short-term learning on EC2, Git can store the credential:

```bash
git config --global credential.helper store
```

Later, replace this with a deploy key or cleaner deployment process.

## 12. Create the project virtual environment

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

## 13. Install project dependencies

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

## 14. Install Playwright browser

With `.venv` active:

```bash
python -m playwright install chromium
```

If Linux libraries are missing:

```bash
sudo .venv/bin/python -m playwright install-deps chromium
python -m playwright install chromium
```

## 15. Configure secrets and environment

Do not commit `.env` to GitHub.

For a test instance, either keep `.env` in the repo working directory or use a safer system path. Preferred server path:

```text
/etc/job-hunter/job-hunter.env
```

Create the folder:

```bash
sudo mkdir -p /etc/job-hunter
```

The environment file should define these values:

```env
JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data
JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output
JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db
JOB_HUNTER_BASE_URL=http://<elastic-ip-or-domain>
JOB_HUNTER_GOOGLE_CLIENT_ID=<google-client-id>
JOB_HUNTER_GOOGLE_CLIENT_SECRET=<google-client-secret>
JOB_HUNTER_ADMIN_EMAIL=<admin-email>
JOB_HUNTER_AUTH_SESSION_SECRET=<random-secret>
```

Generate a session secret:

```bash
openssl rand -hex 32
```

Protect the env file:

```bash
sudo chown root:ubuntu /etc/job-hunter/job-hunter.env
sudo chmod 640 /etc/job-hunter/job-hunter.env
```

If using `/home/ubuntu/job-hunter-agent/.env` for testing, do not commit it and keep permissions restricted.

## 16. Configure Google OAuth

In Google Cloud Console, create or update the OAuth client.

Authorized redirect URI must match the app base URL:

```text
http://<elastic-ip-or-domain>/api/auth/google/callback
```

Do not use localhost for the EC2 deployment:

```text
http://localhost:8765/api/auth/google/callback
```

`localhost` points to the user's own computer, not the EC2 instance.

## 17. Run app with systemd

Create the service file:

```bash
sudo nano /etc/systemd/system/job-hunter.service
```

Service file:

```ini
[Unit]
Description=Job Hunter FastAPI App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/job-hunter-agent
EnvironmentFile=/etc/job-hunter/job-hunter.env
Environment="PATH=/home/ubuntu/job-hunter-agent/.venv/bin"
ExecStart=/home/ubuntu/job-hunter-agent/.venv/bin/python -m job_hunter_agent.fastapi_app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

If using the temporary repo-local env file, use this instead:

```ini
EnvironmentFile=/home/ubuntu/job-hunter-agent/.env
```

Start and enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable job-hunter
sudo systemctl start job-hunter
sudo systemctl status job-hunter --no-pager
```

Expected:

```text
Active: active (running)
```

Check that environment variables reached the running app without printing values:

```bash
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value job-hunter)/environ | grep '^JOB_HUNTER_' | sed 's/=.*/=***/'
```

Expected names include:

```text
JOB_HUNTER_DATA_DIR=***
JOB_HUNTER_OUTPUT_DIR=***
JOB_HUNTER_DB_PATH=***
JOB_HUNTER_BASE_URL=***
JOB_HUNTER_GOOGLE_CLIENT_ID=***
JOB_HUNTER_GOOGLE_CLIENT_SECRET=***
JOB_HUNTER_ADMIN_EMAIL=***
JOB_HUNTER_AUTH_SESSION_SECRET=***
```

## 18. View logs

Live logs:

```bash
sudo journalctl -u job-hunter -f
```

Last 50 lines:

```bash
sudo journalctl -u job-hunter -n 50 --no-pager
```

Recent logs:

```bash
sudo journalctl -u job-hunter --since "10 minutes ago" --no-pager
```

Nginx logs:

```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

Later, production should send logs to CloudWatch Logs.

## 19. Configure Nginx reverse proxy

Create the Nginx site:

```bash
sudo nano /etc/nginx/sites-available/job-hunter
```

Config:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/job-hunter /etc/nginx/sites-enabled/job-hunter
```

Remove the default site if Nginx warns about a conflicting `_` server name:

```bash
sudo rm /etc/nginx/sites-enabled/default
```

Test Nginx config:

```bash
sudo nginx -t
```

Expected:

```text
syntax is ok
test is successful
```

Reload Nginx:

```bash
sudo systemctl reload nginx
```

Local test from EC2:

```bash
curl -I http://127.0.0.1/
```

Expected: response from Nginx and redirect or HTML from the app.

Public test from browser:

```text
http://<elastic-ip-or-public-ip>/
```

Expected: login page or redirect to login.

## 20. Useful EC2 metadata checks

If IMDSv1 returns blank, use IMDSv2.

Get token:

```bash
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
```

Get public IP:

```bash
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4
```

## 21. Quick checks

Confirm OS:

```bash
lsb_release -a
```

Confirm Python:

```bash
python3 --version
```

Confirm EBS mount:

```bash
df -h /var/lib/job-hunter
```

Confirm service:

```bash
sudo systemctl status job-hunter --no-pager
```

Confirm Nginx:

```bash
sudo nginx -t
curl -I http://127.0.0.1/
```

Confirm app env names:

```bash
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value job-hunter)/environ | grep '^JOB_HUNTER_' | sed 's/=.*/=***/'
```

## Do not do yet

Until this test deployment is stable:

```text
Do not create RDS
Do not create Lambda
Do not create Lightsail
Do not expose port 8765 publicly
Do not commit .env or secrets to GitHub
Do not rely on the default public EC2 IP for OAuth long term
```

## Later improvements

```text
Move from repo clone to package/artifact deployment
Use /opt/job-hunter/app for installed application code
Keep /var/lib/job-hunter/data for persistent data
Keep /var/log/job-hunter for logs
Add HTTPS using a domain and certificate
Add CloudWatch Logs
Add EBS snapshots or S3 backups
Consider RDS PostgreSQL when the data model stabilizes
```
