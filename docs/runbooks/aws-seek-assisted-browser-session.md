# AWS SEEK Assisted Browser Session Runbook

This runbook is for production SEEK scraping failures on AWS EC2.

It exists because SEEK can show a human-verification or bot-challenge page before job cards load. Generic timeouts only prevent the app from hanging; they do not make SEEK scraping work.

## Rule

Use the project runtime through `uv run` for manual Python commands on EC2.

Do not use raw `python` or assume `python` exists on Ubuntu. Do not use local VS Code output as proof of AWS runtime state.

## Known required production paths

```text
App path:        /home/ubuntu/job-hunter-agent
Data dir:        /var/lib/job-hunter/data
Output dir:      /var/lib/job-hunter/output
DB path:         /var/lib/job-hunter/data/job_hunter.db
Service:         job-hunter
noVNC local:     127.0.0.1:7900
VNC local:       127.0.0.1:5901
Display:         :99
Playwright data: /var/lib/job-hunter/data/playwright_user_data
```

## 1. Become the app user

Session Manager commonly starts as `ssm-user`. Switch to `ubuntu` first:

```bash
use-ubuntu
cd /home/ubuntu/job-hunter-agent
```

If `use-ubuntu` is not installed yet:

```bash
sudo -iu ubuntu
cd /home/ubuntu/job-hunter-agent
```

## 2. Confirm service and browser-session processes

```bash
sudo systemctl status job-hunter --no-pager
ss -ltnp | grep -E '(:7900|:5901|:8765)'
ps -ef | grep -E 'Xvfb|openbox|x11vnc|websockify|chromium|chrome|fastapi_app' | grep -v grep
```

Expected:

```text
Xvfb :99
openbox
x11vnc listening on 127.0.0.1:5901
websockify/noVNC listening on 127.0.0.1:7900
FastAPI listening on 127.0.0.1:8765
```

Openbox may log this non-fatal warning:

```text
Unable to find a valid menu file "/var/lib/openbox/debian-menu.xml"
```

That warning only means the right-click Openbox menu is missing. It does not mean the display is broken.

## 3. Check browser-session logs

```bash
tail -n 80 \
  /var/lib/job-hunter/output/xvfb.log \
  /var/lib/job-hunter/output/openbox.log \
  /var/lib/job-hunter/output/x11vnc.log \
  /var/lib/job-hunter/output/novnc.log
```

Fatal examples:

```text
openbox: command not found
Xvfb: command not found
x11vnc: command not found
websockify: command not found
```

Fix missing system packages through the repo-managed deploy path where possible. For immediate EC2 repair, install the missing package, then restart:

```bash
sudo apt-get update
sudo apt-get install -y openbox xvfb x11vnc websockify novnc
sudo systemctl restart job-hunter
```

## 4. Seed or upgrade the production DB with uv

If a manual settings check fails with:

```text
sqlite3.OperationalError: no such table: global_settings
```

the DB at `JOB_HUNTER_DB_PATH` is not seeded/upgraded.

Run:

```bash
cd /home/ubuntu/job-hunter-agent && \
JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db \
JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data \
JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output \
uv run python -m job_hunter_agent.db_seed --upgrade
```

Do not use raw `python` for this project. Use `uv run python`.

## 5. Check SEEK browser settings

```bash
cd /home/ubuntu/job-hunter-agent && \
JOB_HUNTER_DB_PATH=/var/lib/job-hunter/data/job_hunter.db \
JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data \
JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output \
uv run python - <<'PY'
from job_hunter_agent.global_settings import load_global_settings
s = load_global_settings()["playwright_settings"]
print(s)
print("headless =", s.get("headless"))
print("playwright_browser_mode =", s.get("playwright_browser_mode"))
print("seek_assisted_verification_enabled =", s.get("seek_assisted_verification_enabled"))
PY
```

Required for AWS assisted SEEK scraping:

```text
headless = False
playwright_browser_mode = persistent
seek_assisted_verification_enabled = True
```

If `headless` is `True`, the browser will not be visible in noVNC and Rob cannot clear SEEK verification.

If `playwright_browser_mode` is not `persistent`, the verification state will not reliably survive between browser sessions.

If `seek_assisted_verification_enabled` is not `True`, the SEEK challenge path will fail instead of waiting for manual verification.

## 6. Open noVNC securely

From the local machine, tunnel the EC2 noVNC port. Do not expose VNC/noVNC publicly.

SSH example:

```bash
ssh -L 7900:127.0.0.1:7900 ubuntu@YOUR_EC2_HOST
```

Then open locally:

```text
http://127.0.0.1:7900/vnc.html?autoconnect=1&resize=remote
```

When using AWS Systems Manager Session Manager, forward local port `7900` to the instance's `127.0.0.1:7900`.

## 7. Interpret SEEK failure correctly

If logs show:

```text
SEEK bot challenge detected; waiting for auto-resolve
```

or the browser page shows:

```text
Just a moment...
Help us keep SEEK secure, confirm you are human
```

then SEEK has not loaded job cards. The scraper is blocked before extraction.

The correct fix is not more selector work and not a longer timeout. The correct operational path is:

1. confirm headed persistent browser settings;
2. open the AWS noVNC browser session;
3. complete SEEK verification manually;
4. rerun the scrape;
5. confirm logs show `cards=N` for SEEK.

## 8. Success criteria

A working AWS SEEK scrape must show:

```text
[SEEK p1/N] cards=<number greater than 0>
```

A timeout or challenge page is not a successful scrape.

## 9. Do not do

Do not:

```text
Use raw python commands when uv is available
Assume service active means DB is seeded
Expose noVNC or VNC publicly
Treat x11vnc/noVNC listening as proof that Chromium is visible
Add CAPTCHA bypass, proxy tricks, or stealth escalation
Call a timeout fix a scraping fix
Silently ignore SEEK challenge exceptions
```
