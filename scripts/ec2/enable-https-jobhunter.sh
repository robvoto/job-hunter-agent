#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${JOB_HUNTER_DOMAIN:-jobhunter.robvoto.com}"
EMAIL="${LETSENCRYPT_EMAIL:-rob.voto.au@gmail.com}"

cat <<INFO
Enable HTTPS for Job Hunter on AWS EC2.

What this does:
  1. checks that Nginx exists
  2. installs certbot and the Nginx plugin if missing
  3. requests a Let's Encrypt certificate for ${DOMAIN}
  4. lets certbot update the Nginx site config
  5. tests HTTPS route

Before running:
  - DNS for ${DOMAIN} must point to this EC2 public IP.
  - Security group must allow inbound 80 and 443.
  - Nginx must already route ${DOMAIN} to 127.0.0.1:8765.
INFO

read -r -p "Continue enabling HTTPS for ${DOMAIN}? Type YES: " confirm
if [[ "$confirm" != "YES" ]]; then
  echo "Cancelled."
  exit 1
fi

if ! command -v nginx >/dev/null 2>&1; then
  echo "ERROR: nginx is not installed." >&2
  exit 1
fi

echo "==> Install certbot if needed"
sudo apt update
sudo apt install -y certbot python3-certbot-nginx

echo "==> Test Nginx config before certificate request"
sudo nginx -t

echo "==> Request/install Let's Encrypt certificate"
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect

echo "==> Test Nginx config after certificate install"
sudo nginx -t
sudo systemctl reload nginx

echo "==> HTTPS health check"
curl -I "https://${DOMAIN}/start"

echo "==> Done. Browser should now show HTTPS/secure for https://${DOMAIN}/start"
