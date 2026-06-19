#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"

sudo install -m 0755 "$APP_DIR/scripts/ec2/deploy-jobhunter.sh" /usr/local/bin/deploy-jobhunter
sudo install -m 0755 "$APP_DIR/scripts/ec2/jobhunter-status.sh" /usr/local/bin/jobhunter-status
sudo install -m 0755 "$APP_DIR/sync-knowledge" /usr/local/bin/sync-knowledge

# Strip UTF-8 BOM that Windows editors sometimes add.
sudo sed -i '1s/^\xEF\xBB\xBF//' /usr/local/bin/deploy-jobhunter /usr/local/bin/jobhunter-status /usr/local/bin/sync-knowledge

sudo tee /usr/local/bin/use-ubuntu >/dev/null <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
exec sudo -iu ubuntu
EOS
sudo chmod 0755 /usr/local/bin/use-ubuntu

echo "Helpers installed: deploy-jobhunter, jobhunter-status, sync-knowledge, use-ubuntu"
