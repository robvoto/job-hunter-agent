#!/usr/bin/env bash
set -euo pipefail

# Installs small admin helpers into /usr/local/bin so operators can run
# common maintenance tasks without remembering long paths or sudo patterns.
APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"

# Install the main helpers. These are plain shell wrappers and should be
# executable by root; some of the helpers themselves `sudo -iu ubuntu` where
# appropriate to run git and other user-scoped commands.
sudo install -m 0755 "$APP_DIR/scripts/ec2/deploy-jobhunter.sh" /usr/local/bin/deploy-jobhunter
sudo install -m 0755 "$APP_DIR/scripts/ec2/deploy-jobhunter-ref.sh" /usr/local/bin/deploy-jobhunter-ref
sudo install -m 0755 "$APP_DIR/scripts/ec2/jobhunter-status.sh" /usr/local/bin/jobhunter-status
sudo install -m 0755 "$APP_DIR/scripts/ec2/jobhunter-logs.sh" /usr/local/bin/jobhunter-logs
sudo install -m 0755 "$APP_DIR/sync-knowledge" /usr/local/bin/sync-knowledge

# Strip UTF-8 BOM that Windows editors sometimes add.
sudo sed -i '1s/^\xEF\xBB\xBF//' /usr/local/bin/deploy-jobhunter /usr/local/bin/deploy-jobhunter-ref /usr/local/bin/jobhunter-status /usr/local/bin/jobhunter-logs /usr/local/bin/sync-knowledge

# Helper to drop into the ubuntu user's shell when needed.
sudo tee /usr/local/bin/use-ubuntu >/dev/null <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
exec sudo -iu ubuntu
EOS
sudo chmod 0755 /usr/local/bin/use-ubuntu

echo "Helpers installed: deploy-jobhunter, deploy-jobhunter-ref, jobhunter-status, jobhunter-logs, sync-knowledge, use-ubuntu"
