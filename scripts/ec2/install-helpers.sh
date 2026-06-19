#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"

echo "Installing Job Hunter EC2 helper commands..."
echo "Teaching: these wrappers keep AWS commands consistent and version-controlled in the repo."

sudo install -m 0755 "$APP_DIR/scripts/ec2/deploy-jobhunter.sh" /usr/local/bin/deploy-jobhunter
sudo install -m 0755 "$APP_DIR/scripts/ec2/jobhunter-status.sh" /usr/local/bin/jobhunter-status
sudo install -m 0755 "$APP_DIR/sync-knowledge" /usr/local/bin/sync-knowledge

# Defend Ubuntu from Windows-edited files that may carry a UTF-8 BOM.
sudo sed -i '1s/^\xEF\xBB\xBF//' /usr/local/bin/deploy-jobhunter /usr/local/bin/jobhunter-status /usr/local/bin/sync-knowledge

sudo tee /usr/local/bin/use-ubuntu >/dev/null <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
echo "Switching to ubuntu user for Job Hunter work..."
echo "Teaching: SSM logs you in as ssm-user. The app files belong to ubuntu."
exec sudo -iu ubuntu
EOS
sudo chmod 0755 /usr/local/bin/use-ubuntu

echo "Installed:"
echo "  /usr/local/bin/deploy-jobhunter"
echo "  /usr/local/bin/jobhunter-status"
echo "  /usr/local/bin/sync-knowledge"
echo "  /usr/local/bin/use-ubuntu"
