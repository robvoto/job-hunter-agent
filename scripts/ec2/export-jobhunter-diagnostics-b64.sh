#!/usr/bin/env bash
set -euo pipefail

# Export a sanitized Job Hunter EC2 diagnostic bundle as gzip+base64 text.
# Intended for AWS Session Manager where downloading files is awkward.
# Usage:
#   bash scripts/ec2/export-jobhunter-diagnostics-b64.sh
# Optional:
#   JOB_HUNTER_DIAG_GREP="seek|playwright|cloudflare|timeout|blocked|linkedin|error|traceback" \
#     bash scripts/ec2/export-jobhunter-diagnostics-b64.sh
#   JOB_HUNTER_DIAG_SINCE="6 hours ago" bash scripts/ec2/export-jobhunter-diagnostics-b64.sh

SERVICE_NAME="${JOB_HUNTER_SERVICE:-job-hunter}"
SINCE="${JOB_HUNTER_DIAG_SINCE:-24 hours ago}"
GREP_PATTERN="${JOB_HUNTER_DIAG_GREP:-seek|playwright|cloudflare|captcha|human|verification|blocked|timeout|403|429|error|exception|traceback|linkedin}"
OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
APP_LOG="${JOB_HUNTER_SERVER_LOG:-$OUTPUT_DIR/server.log}"
OUT_DIR="${JOB_HUNTER_DIAG_OUT_DIR:-/home/ubuntu}"
TS="$(date +"%Y%m%d-%H%M%S")"
TXT_OUT="$OUT_DIR/jobhunter-diagnostics-$TS.txt"
GZ_OUT="$TXT_OUT.gz"
B64_OUT="$GZ_OUT.b64"

run_section() {
  local title="$1"
  shift
  echo
  echo "===== $title ====="
  "$@" || true
}

mkdir -p "$OUT_DIR"

{
  echo "===== JOB HUNTER AWS DIAGNOSTICS ====="
  echo "timestamp: $(date -Is)"
  echo "host: $(hostname)"
  echo "service: $SERVICE_NAME"
  echo "since: $SINCE"
  echo "grep_pattern: $GREP_PATTERN"

  run_section "SERVICE STATUS: $SERVICE_NAME" systemctl status "$SERVICE_NAME" --no-pager -l

  run_section "LAST SYSTEMD LOGS: $SERVICE_NAME" journalctl -u "$SERVICE_NAME" --since "$SINCE" --no-pager

  echo
  echo "===== APP LOG: $APP_LOG ====="
  if [[ -f "$APP_LOG" ]]; then
    cat "$APP_LOG"
  else
    echo "app log not found: $APP_LOG"
  fi

  echo
  echo "===== FOCUSED MATCHES ====="
  {
    journalctl -u "$SERVICE_NAME" --since "$SINCE" --no-pager || true
    if [[ -f "$APP_LOG" ]]; then
      cat "$APP_LOG" || true
    fi
  } | grep -Ei "$GREP_PATTERN" -C 5 || true

  echo
  echo "===== FILES ====="
  ls -lh "$TXT_OUT" "$APP_LOG" 2>/dev/null || true
} > "$TXT_OUT"

chmod 0644 "$TXT_OUT"

if command -v gzip >/dev/null 2>&1; then
  gzip -c "$TXT_OUT" > "$GZ_OUT"
else
  python3 - "$TXT_OUT" "$GZ_OUT" <<'PY'
import gzip
import pathlib
import sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
with src.open('rb') as f_in, gzip.open(dst, 'wb') as f_out:
    f_out.write(f_in.read())
PY
fi

if command -v base64 >/dev/null 2>&1; then
  if base64 --help 2>&1 | grep -q -- '-w'; then
    base64 -w 0 "$GZ_OUT" > "$B64_OUT"
  else
    base64 "$GZ_OUT" | tr -d '\n' > "$B64_OUT"
  fi
else
  python3 - "$GZ_OUT" "$B64_OUT" <<'PY'
import base64
import pathlib
import sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
dst.write_text(base64.b64encode(src.read_bytes()).decode('ascii'), encoding='ascii')
PY
fi

cat <<EOF
Created diagnostic files:
$(ls -lh "$TXT_OUT" "$GZ_OUT" "$B64_OUT")

===== JOBHUNTER_DIAGNOSTICS_B64_BEGIN =====
$(cat "$B64_OUT")
===== JOBHUNTER_DIAGNOSTICS_B64_END =====
EOF
