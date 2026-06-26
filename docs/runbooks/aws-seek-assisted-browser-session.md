# AWS SEEK Assisted Browser Session Runbook

This is the operational runbook for production SEEK scraping failures on AWS EC2.

SEEK can show a human-verification or bot-challenge page before job cards load. A timeout only prevents Job Hunter from hanging; it does not prove SEEK scraping works. The pass condition is always that SEEK reaches job cards and logs `cards=N`.

## Canonical rule

Use the project runtime through `uv run` for manual Python commands on EC2.

Do not use raw `python` or assume `python` exists on Ubuntu. Do not use local VS Code output as proof of AWS runtime state.

## Related docs

| Doc | Purpose |
| --- | --- |
| `docs/aws-ec2-setup.md` | Full AWS deployment and production topology. |
| `docs/OPERATIONS.md` | General operational commands and recovery model. |
| `docs/runbooks/aws-seek-assisted-browser-session.md` | This focused SEEK/AWS troubleshooting path. |

## Required production paths

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

## What good looks like

A working AWS SEEK scrape must eventually show this in logs:

```text
[SEEK p1/N] cards=<number greater than 0>
```

These are not success:

```text
SEEK bot challenge detected; waiting for auto-resolve
SEEK did not finish in time and was skipped
LinkedIn did not finish in time and was skipped
Just a moment...
Help us keep SEEK secure, confirm you are human
```

Those mean the scraper has not extracted SEEK job cards.

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

Run on the EC2 host:

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

If `openbox` is missing, noVNC can connect but the virtual desktop may be blank, unstable, or hard to use.

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

Immediate EC2 repair:

```bash
sudo apt-get update
sudo apt-get install -y openbox xvfb x11vnc websockify novnc
sudo systemctl restart job-hunter
```

Permanent repair should still go through the repo-managed deploy path if a dependency is missing from the installer/deploy scripts.

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

Interpretation:

| Setting | Required | Why it matters |
| --- | --- | --- |
| `headless` | `False` | Browser must be visible in noVNC so Rob can complete the check. |
| `playwright_browser_mode` | `persistent` | Verification/session state must survive in the Playwright profile. |
| `seek_assisted_verification_enabled` | `True` | SEEK challenge path waits for manual verification instead of failing immediately. |

If one of these is wrong, fix settings first. Do not continue debugging selectors.

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

## 7. Run one SEEK scrape and watch logs

Start the scrape from the UI, then watch logs from EC2:

```bash
sudo journalctl -u job-hunter -f
```

If SEEK shows verification in noVNC, complete it manually in the visible browser. Then return to the workspace and confirm the run continues.

Expected success:

```text
[SEEK p1/N] cards=<number greater than 0>
```

Expected bounded failure:

```text
[SEEK][SOURCE_TIMEOUT]
```

A bounded failure is better than a hang, but it is still a failed SEEK scrape.

## 8. Interpret SEEK failure correctly

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

The correct operational path is:

1. confirm headed persistent browser settings;
2. confirm noVNC is reachable;
3. complete SEEK verification manually;
4. rerun the scrape;
5. confirm logs show `cards=N` for SEEK.

## 9. Common false conclusions

| False conclusion | Correct interpretation |
| --- | --- |
| `systemctl` says active, so app is healthy. | Not enough. Also check `curl` and logs. |
| noVNC port is listening, so browser is usable. | Not enough. Confirm Xvfb, openbox, x11vnc, websockify, and Chromium. |
| Timeout fired, so SEEK is fixed. | No. Timeout only prevents a frozen run. |
| LinkedIn returned jobs, so SEEK works. | No. Sources must be checked separately. |
| `global_settings` missing means settings are wrong. | The production DB was not seeded/upgraded at the configured path. |

## 10. Do not do

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
