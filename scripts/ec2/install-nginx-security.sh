#!/usr/bin/env bash
# Install shared Nginx request hardening for Job Hunter and KnowMe on the EC2 host.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HTTP_SOURCE="$SCRIPT_DIR/nginx/robvoto-security-http.conf"
SERVER_SOURCE="$SCRIPT_DIR/nginx/robvoto-security-server.conf"
HTTP_TARGET="/etc/nginx/conf.d/robvoto-security-http.conf"
SERVER_TARGET="/etc/nginx/snippets/robvoto-security-server.conf"
INCLUDE_LINE="    include $SERVER_TARGET;"
SITE_FILES=(
  "/etc/nginx/sites-available/job-hunter"
  "/etc/nginx/sites-available/knowme"
)

for source_file in "$HTTP_SOURCE" "$SERVER_SOURCE"; do
  if [[ ! -f "$source_file" ]]; then
    echo "ERROR: Missing required source file: $source_file" >&2
    exit 1
  fi
done

for site_file in "${SITE_FILES[@]}"; do
  if [[ ! -f "$site_file" ]]; then
    echo "ERROR: Missing required Nginx site: $site_file" >&2
    exit 1
  fi
done

backup_dir="$(mktemp -d)"
rollback_required=true

rollback() {
  if [[ "$rollback_required" != true ]]; then
    return
  fi

  echo "Nginx validation failed; restoring the previous configuration." >&2
  for site_file in "${SITE_FILES[@]}"; do
    sudo install -m 0644 "$backup_dir/$(basename "$site_file")" "$site_file"
  done

  if [[ -f "$backup_dir/robvoto-security-http.conf" ]]; then
    sudo install -m 0644 "$backup_dir/robvoto-security-http.conf" "$HTTP_TARGET"
  else
    sudo rm -f "$HTTP_TARGET"
  fi

  if [[ -f "$backup_dir/robvoto-security-server.conf" ]]; then
    sudo install -m 0644 "$backup_dir/robvoto-security-server.conf" "$SERVER_TARGET"
  else
    sudo rm -f "$SERVER_TARGET"
  fi
}

cleanup() {
  rm -rf "$backup_dir"
}

trap 'rollback; cleanup' ERR

for site_file in "${SITE_FILES[@]}"; do
  cp "$site_file" "$backup_dir/$(basename "$site_file")"
done
[[ ! -f "$HTTP_TARGET" ]] || sudo cp "$HTTP_TARGET" "$backup_dir/robvoto-security-http.conf"
[[ ! -f "$SERVER_TARGET" ]] || sudo cp "$SERVER_TARGET" "$backup_dir/robvoto-security-server.conf"

sudo install -m 0644 "$HTTP_SOURCE" "$HTTP_TARGET"
sudo install -m 0644 "$SERVER_SOURCE" "$SERVER_TARGET"

for site_file in "${SITE_FILES[@]}"; do
  if grep -Fq "$SERVER_TARGET" "$site_file"; then
    continue
  fi

  staged_file="$(mktemp)"
  awk -v include_line="$INCLUDE_LINE" '
    {
      print
      if (!added && $0 ~ /^[[:space:]]*server_name[[:space:]]+/) {
        print include_line
        added = 1
      }
    }
  ' "$site_file" >"$staged_file"
  sudo install -m 0644 "$staged_file" "$site_file"
  rm -f "$staged_file"
done

sudo nginx -t
sudo systemctl reload nginx

rollback_required=false
cleanup
trap - ERR

echo "Nginx request hardening installed and reloaded successfully."
