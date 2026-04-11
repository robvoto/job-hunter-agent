import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from profile_store import load_profile, patch_profile, save_profile


HOST = "127.0.0.1"
PORT = 8765

ADMIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEEK Admin Console</title>
  <style>
    :root {
      --bg: #f4efe7;
      --card: #fffaf2;
      --ink: #1f2933;
      --muted: #5b6470;
      --line: #e6dccd;
      --accent: #14532d;
      --accent-2: #1d4ed8;
      --shadow: 0 12px 30px rgba(31, 41, 51, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    .page {
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px 18px 48px;
    }
    .hero, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
    }
    .hero {
      padding: 24px;
      margin-bottom: 20px;
    }
    .hero h1 {
      margin: 0 0 8px;
      font-size: 2rem;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
    }
    .panel {
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 14px;
      font-size: 1.1rem;
    }
    label {
      display: block;
      margin: 12px 0 6px;
      font-weight: 600;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font: inherit;
      background: white;
      color: var(--ink);
    }
    textarea {
      min-height: 120px;
      resize: vertical;
    }
    .help {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.88rem;
    }
    .actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 22px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    .primary {
      background: var(--accent);
      color: white;
    }
    .secondary {
      background: white;
      color: var(--accent-2);
      border: 1px solid var(--line);
    }
    .status {
      margin-top: 16px;
      padding: 12px 14px;
      border-radius: 12px;
      font-weight: 600;
      display: none;
    }
    .status.ok {
      display: block;
      background: #e6f4ea;
      color: #14532d;
    }
    .status.error {
      display: block;
      background: #fff0e6;
      color: #9a3412;
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>SEEK Admin Console</h1>
      <p>Update your fit profile, exclusions, search window, and manual review lists here. Saving updates <code>profile.json</code> for the scraper and LLM.</p>
    </section>

    <div class="grid">
      <section class="panel">
        <h2>Search Window</h2>
        <label for="date_range_days">How far back to search</label>
        <select id="date_range_days">
          <option value="1">Today</option>
          <option value="3">Last 3 days</option>
          <option value="7">Last 7 days</option>
          <option value="14">Last 14 days</option>
          <option value="30">Last 30 days</option>
        </select>
        <div class="help">This updates SEEK's own date filter before scraping starts.</div>

        <label for="max_pages_cap">Max pages to crawl</label>
        <input id="max_pages_cap" type="number" min="1" max="100">
        <div class="help">Guardrail so broad searches do not run forever.</div>

        <label for="enforce_posted_age_limit">Strictly reject older ads</label>
        <select id="enforce_posted_age_limit">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
        <div class="help">If enabled, ads older than the selected date window are skipped even if SEEK still returns them.</div>
      </section>

      <section class="panel">
        <h2>Candidate Fit</h2>
        <label for="candidate_summary">Candidate summary</label>
        <textarea id="candidate_summary"></textarea>
        <div class="help">Short paragraph describing what you are good at and the kind of work you want.</div>

        <label for="strengths">Strengths</label>
        <textarea id="strengths"></textarea>
        <div class="help">One strength per line.</div>

        <label for="llm_prompt_notes">Important fit notes</label>
        <textarea id="llm_prompt_notes"></textarea>
        <div class="help">One note per line. Example: reject cyber or security-heavy roles.</div>
      </section>

      <section class="panel">
        <h2>Title Matching</h2>
        <label for="target_title_patterns">Target title patterns</label>
        <textarea id="target_title_patterns"></textarea>
        <div class="help">One regex pattern per line. These are strong matches.</div>

        <label for="adjacent_title_patterns">Adjacent title patterns</label>
        <textarea id="adjacent_title_patterns"></textarea>
        <div class="help">One regex pattern per line. These are possible matches.</div>

        <label for="reject_title_rules">Reject title rules</label>
        <textarea id="reject_title_rules"></textarea>
        <div class="help">One line per rule in the format <code>pattern || reason</code>.</div>
      </section>

      <section class="panel">
        <h2>Description Exclusions</h2>
        <label for="reject_description_phrase_rules">Reject description phrases</label>
        <textarea id="reject_description_phrase_rules"></textarea>
        <div class="help">One line per rule in the format <code>phrase || reason</code>. Example: <code>wealth management || DESC_FINANCE:wealth management</code>.</div>

        <label for="reject_description_regex_rules">Reject description regex rules</label>
        <textarea id="reject_description_regex_rules"></textarea>
        <div class="help">One line per rule in the format <code>pattern || reason</code>.</div>
      </section>

      <section class="panel">
        <h2>Review Controls</h2>
        <label for="applied_job_keys">Applied jobs</label>
        <textarea id="applied_job_keys"></textarea>
        <div class="help">One SEEK job URL or job ID per line. These will be hidden from future runs.</div>

        <label for="hidden_job_keys">Hidden jobs</label>
        <textarea id="hidden_job_keys"></textarea>
        <div class="help">One SEEK job URL or job ID per line. Use this for anything you never want to see again.</div>
      </section>
    </div>

    <div class="actions">
      <button class="primary" id="save">Save Changes</button>
      <button class="secondary" id="reload">Reload Profile</button>
    </div>

    <div class="status" id="status"></div>
  </main>

  <script>
    const statusEl = document.getElementById('status');

    const listTextAreas = [
      'strengths',
      'llm_prompt_notes',
      'target_title_patterns',
      'adjacent_title_patterns',
      'applied_job_keys',
      'hidden_job_keys',
    ];

    const ruleTextAreas = [
      ['reject_title_rules', 'pattern'],
      ['reject_description_phrase_rules', 'phrase'],
      ['reject_description_regex_rules', 'pattern'],
    ];

    function showStatus(message, kind) {
      statusEl.textContent = message;
      statusEl.className = `status ${kind}`;
    }

    function toLines(value) {
      return value.split(/\\r?\\n/).map(line => line.trim()).filter(Boolean);
    }

    function rulesToText(rules, key) {
      return (rules || []).map(rule => `${rule[key] || ''} || ${rule.reason || ''}`).join('\\n');
    }

    function textToRules(value, key) {
      return toLines(value).map(line => {
        const parts = line.split('||');
        return {
          [key]: (parts[0] || '').trim(),
          reason: (parts[1] || '').trim(),
        };
      }).filter(rule => rule[key]);
    }

    function fillForm(profile) {
      document.getElementById('date_range_days').value = String(profile.search_settings?.date_range_days ?? 3);
      document.getElementById('max_pages_cap').value = String(profile.search_settings?.max_pages_cap ?? 10);
      document.getElementById('enforce_posted_age_limit').value = String(Boolean(profile.search_settings?.enforce_posted_age_limit));
      document.getElementById('candidate_summary').value = profile.candidate_summary || '';

      for (const id of ['strengths', 'llm_prompt_notes', 'target_title_patterns', 'adjacent_title_patterns']) {
        document.getElementById(id).value = (profile[id] || []).join('\\n');
      }

      for (const [id, key] of ruleTextAreas) {
        document.getElementById(id).value = rulesToText(profile[id], key);
      }

      document.getElementById('applied_job_keys').value = (profile.review_controls?.applied_job_keys || []).join('\\n');
      document.getElementById('hidden_job_keys').value = (profile.review_controls?.hidden_job_keys || []).join('\\n');
    }

    async function loadProfile() {
      const response = await fetch('/api/profile');
      if (!response.ok) {
        throw new Error('Could not load profile');
      }
      const profile = await response.json();
      fillForm(profile);
      showStatus('Profile loaded.', 'ok');
    }

    function collectProfile() {
      return {
        search_settings: {
          date_range_days: Number(document.getElementById('date_range_days').value),
          max_pages_cap: Number(document.getElementById('max_pages_cap').value),
          enforce_posted_age_limit: document.getElementById('enforce_posted_age_limit').value === 'true',
        },
        review_controls: {
          applied_job_keys: toLines(document.getElementById('applied_job_keys').value),
          hidden_job_keys: toLines(document.getElementById('hidden_job_keys').value),
        },
        candidate_summary: document.getElementById('candidate_summary').value.trim(),
        strengths: toLines(document.getElementById('strengths').value),
        llm_prompt_notes: toLines(document.getElementById('llm_prompt_notes').value),
        target_title_patterns: toLines(document.getElementById('target_title_patterns').value),
        adjacent_title_patterns: toLines(document.getElementById('adjacent_title_patterns').value),
        reject_title_rules: textToRules(document.getElementById('reject_title_rules').value, 'pattern'),
        reject_description_phrase_rules: textToRules(document.getElementById('reject_description_phrase_rules').value, 'phrase'),
        reject_description_regex_rules: textToRules(document.getElementById('reject_description_regex_rules').value, 'pattern'),
      };
    }

    async function saveProfile() {
      const response = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectProfile()),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || 'Could not save profile');
      }
      showStatus('Profile saved to profile.json.', 'ok');
    }

    document.getElementById('save').addEventListener('click', async () => {
      try {
        await saveProfile();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('reload').addEventListener('click', async () => {
      try {
        await loadProfile();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    loadProfile().catch(error => showStatus(error.message, 'error'));
  </script>
</body>
</html>
"""


class AdminHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        if self.path in {"/", "/admin", "/profile"}:
            if self.path == "/profile":
                self._redirect("/admin")
                return
            self._send_html(ADMIN_HTML)
            return
        if self.path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/api/profile":
            self._send_json(200, load_profile())
            return
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
        if self.path != "/api/profile":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            updated = patch_profile(self._read_json_body())
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, updated)

    def do_PUT(self) -> None:
        if self.path != "/api/profile":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            updated = save_profile(self._read_json_body())
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, updated)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), AdminHandler)
    print(f"Admin console listening at http://{HOST}:{PORT}/admin")
    server.serve_forever()
