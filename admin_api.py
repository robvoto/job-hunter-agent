import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import OUTPUT_HTML
from profile_learning import build_learning_patch, merge_capability_rules, repair_text, resolve_knowledge_file
from profile_store import DEFAULT_PROFILE, load_profile, patch_profile, save_profile
from review_insights import apply_skill_review_decisions
from source_documents import (
    build_llm_profile_brief,
    import_source_materials_to_profile,
    load_source_materials,
    persist_uploaded_source_pack,
    save_source_materials,
)


HOST = "127.0.0.1"
PORT = 8765
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
RUN_STATS_PATH = OUTPUT_DIR / "seek_run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "seek_review_data.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
SHOWCASE_PATH = ROOT_DIR / "docs" / "SHOWCASE.html"
DASHBOARD_PATH = ROOT_DIR / OUTPUT_HTML

ADMIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Hunter Admin</title>
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
    .tabs {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0 0 22px;
    }
    .tab-button {
      background: white;
      color: var(--accent-2);
      border: 1px solid var(--line);
    }
    .tab-button.active {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    .group {
      margin-top: 22px;
    }
    .tab-panel {
      display: none;
    }
    .tab-panel.active {
      display: block;
    }
    .group-title {
      margin: 0 0 10px;
      font-size: 1.25rem;
    }
    .group-copy {
      margin: 0 0 14px;
      color: var(--muted);
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
    .panel-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
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
    .review-list {
      display: grid;
      gap: 12px;
    }
    .review-card {
      background: white;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
    }
    .review-card h3 {
      margin: 0 0 8px;
      font-size: 1rem;
    }
    .review-card p {
      margin: 0 0 8px;
      color: var(--muted);
    }
    .review-card ul {
      margin: 8px 0 0 18px;
      padding: 0;
    }
    .review-card li {
      margin: 4px 0;
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Job Hunter Admin</h1>
      <p>Use this workspace to tune search, maintain the candidate profile, review what the system has learned, and check the health of the latest run.</p>
    </section>

    <nav class="tabs" aria-label="Admin sections">
      <button class="tab-button active" data-tab-target="search">Search</button>
      <button class="tab-button" data-tab-target="profile">Candidate Profile</button>
      <button class="tab-button" data-tab-target="review">Review</button>
      <button class="tab-button" data-tab-target="test">Test</button>
    </nav>

    <section class="group tab-panel active" data-tab-panel="search">
      <h2 class="group-title">Search</h2>
      <p class="group-copy">This controls what the current live job source gets asked for before we fetch any roles.</p>
      <div class="grid">
      <section class="panel">
        <h2>Search Setup</h2>
        <label for="keywords">Keywords</label>
        <input id="keywords" type="text">
        <div class="help">Use the same words you would search with in the current job source.</div>

        <label for="locations">Locations</label>
        <textarea id="locations"></textarea>
        <div class="help">One source-specific location per line. For the current SEEK connector this should include values such as <code>All Sydney NSW</code> and <code>All Canberra ACT</code>.</div>

        <label for="classification_ids">Classification ids</label>
        <textarea id="classification_ids"></textarea>
        <div class="help">One classification id per line for the current connector. This is a useful pre-filter because it reduces how many roles we ever need to inspect.</div>

        <label for="date_range_days">How far back to search</label>
        <select id="date_range_days">
          <option value="1">Today</option>
          <option value="3">Last 3 days</option>
          <option value="7">Last 7 days</option>
          <option value="14">Last 14 days</option>
          <option value="30">Last 30 days</option>
        </select>
        <div class="help">This updates the source-side date filter before collection starts.</div>

        <label for="max_pages_cap">Max pages to check</label>
        <input id="max_pages_cap" type="number" min="1" max="25">
        <div class="help">Safety limit for broad searches. Keep this low so a loose search does not fan out into huge result sets. The app enforces a hard cap of 25 pages even if a larger value is saved elsewhere.</div>

        <label for="enforce_posted_age_limit">Strictly reject older ads</label>
        <select id="enforce_posted_age_limit">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
        <div class="help">If enabled, roles older than the selected date window are skipped even if the source still returns them.</div>

        <label for="sort_newest_first">Prefer newest jobs first</label>
        <select id="sort_newest_first">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
        <div class="help">If enabled, searches ask the current job source to order results by newest posting date first. This is important for broad searches because the app only checks a limited number of pages.</div>
        <div class="panel-actions">
          <button class="primary" id="save_search">Save Search Settings</button>
        </div>
      </section>
      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="profile">
      <h2 class="group-title">Candidate Profile</h2>
      <p class="group-copy">This is the learning and fit model the job engine should use on every run.</p>
      <div class="grid">
      <section class="panel">
        <h2>Source Documents</h2>
        <p class="help">Normal users should start from the guided onboarding flow. The system keeps an internal local source pack so you do not need to manage file-path plumbing here.</p>
        <div id="source_documents_summary" class="help">No source pack connected yet. Start with onboarding.</div>
        <div class="panel-actions">
          <button class="primary" id="open_onboarding" type="button">Open Onboarding</button>
          <button class="secondary" id="import_source_materials">Rebuild Profile From Source Pack</button>
        </div>
      </section>

      <section class="panel">
        <h2>Candidate Fit</h2>
        <label for="candidate_summary">Candidate summary</label>
        <textarea id="candidate_summary"></textarea>
        <div class="help">This starts from onboarding/imported documents, then becomes your editable top-level positioning summary.</div>

        <label for="llm_profile_brief">AI fit brief</label>
        <textarea id="llm_profile_brief"></textarea>
        <div class="help">This is the compact structured brief the AI uses first. It should summarize strengths, positioning, important capability signals, and practical fit boundaries without repeating every detail from the full background text.</div>

        <label for="strengths">Strengths</label>
        <textarea id="strengths"></textarea>
        <div class="help">Starts from the initial import. Keep one strength per line and edit as you learn what should be emphasized.</div>

        <label for="cv_text">CV / background text</label>
        <textarea id="cv_text"></textarea>
        <div class="help">This is the background text created from onboarding/imported source documents. It is the richest profile context the app uses during matching and LLM review.</div>

        <label for="llm_prompt_notes">Important fit notes</label>
        <textarea id="llm_prompt_notes"></textarea>
        <div class="help">Starts from imported material and your later refinements. Use one note per line for high-signal guidance such as role preferences, domain boundaries, and honest gaps.</div>

        <label for="star_evidence_text">STAR / evidence notes</label>
        <textarea id="star_evidence_text"></textarea>
        <div class="help">Optional deeper examples, impact stories, or evidence snippets. This should contain richer proof points, not general profile summary text.</div>
        <div class="panel-actions">
          <button class="primary" id="save_profile">Save Profile</button>
        </div>
      </section>

      <section class="panel">
        <h2>Learning Inbox</h2>
        <label for="learning_update_text">Paste new candidate knowledge</label>
        <textarea id="learning_update_text"></textarea>
        <div class="help">Paste CV text, capability notes, or a new knowledge dump here. The system will convert it into structured profile fields and save it to <code>profile.json</code>.</div>
        <div class="panel-actions">
          <button class="secondary" id="apply_learning">Apply Learning Update</button>
          <button class="secondary" id="import_knowledge_file">Import Local Capability Note</button>
        </div>
      </section>

      <section class="panel">
        <h2>Capability Matrix</h2>
        <label for="capability_profile_rules">Capability profile rules</label>
        <textarea id="capability_profile_rules"></textarea>
        <div class="help">One line per rule in the format <code>name || level || fit || alias 1, alias 2, alias 3</code>. Use levels like <code>strong</code>, <code>working</code>, <code>basic</code>, <code>low</code>, or <code>none</code>. Use fit like <code>core</code>, <code>supporting</code>, <code>contextual</code>, or <code>avoid</code>.</div>
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
        <div class="help">If the job description contains the phrase on the left, reject it and record the reason on the right. Example: <code>wealth management || DESC_FINANCE:wealth management</code>.</div>

        <label for="reject_description_regex_rules">Reject description regex rules</label>
        <textarea id="reject_description_regex_rules"></textarea>
        <div class="help">One line per rule in the format <code>pattern || reason</code>.</div>

        <label for="must_not_require_skills">Mandatory skills you do not have</label>
        <textarea id="must_not_require_skills"></textarea>
        <div class="help">One skill per line. If the description says that skill is required or essential, the role is rejected. This is how we catch things like mandatory HubSpot CRM experience.</div>

        <label for="canberra_only_description_patterns">Canberra-only description patterns</label>
        <textarea id="canberra_only_description_patterns"></textarea>
        <div class="help">One regex per line. These only trigger when the card location is Canberra and help reject roles that insist you must be Canberra-based.</div>
      </section>
      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="review">
      <h2 class="group-title">Review</h2>
      <p class="group-copy">Use this area to teach the system about new skills and manage review lists without mixing that work into your search settings.</p>
      <div class="grid">
      <section class="panel">
        <h2>Review Controls</h2>
        <label for="applied_job_keys">Applied jobs</label>
        <textarea id="applied_job_keys"></textarea>
        <div class="help">One job URL or job ID per line. These will be hidden from future runs.</div>

        <label for="hidden_job_keys">Hidden jobs</label>
        <textarea id="hidden_job_keys"></textarea>
        <div class="help">One job URL or job ID per line. Use this for anything you never want to see again.</div>
        <div class="panel-actions">
          <button class="primary" id="save_review_controls">Save Review Controls</button>
        </div>
      </section>

      <section class="panel">
        <h2>Unknown Skills Review</h2>
        <div id="unknown_skills_panel" class="help">Run the job source connector to see unclassified skills from recent job descriptions.</div>
        <div class="panel-actions">
          <button class="secondary" id="apply_skill_reviews">Apply Skill Decisions</button>
        </div>
      </section>
      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="test">
      <h2 class="group-title">Test</h2>
      <p class="group-copy">Use this tab to validate what the current run did and spot false rejects quickly.</p>
      <div class="grid">
      <section class="panel">
        <h2>Latest Run Stats</h2>
        <div id="run_stats_panel" class="help">No run stats loaded yet.</div>
      </section>

      <section class="panel">
        <h2>Rejected Samples</h2>
        <div id="rejections_panel" class="help">Rejected roles grouped by reason will appear here after a run.</div>
        <div class="panel-actions">
          <button class="secondary" id="refresh_review">Refresh Test Data</button>
          <button class="secondary" id="reload">Reload Profile</button>
        </div>
      </section>
      </div>
    </section>

    <div class="status" id="status"></div>
  </main>

  <script>
    const statusEl = document.getElementById('status');
    const tabButtons = Array.from(document.querySelectorAll('[data-tab-target]'));
    const tabPanels = Array.from(document.querySelectorAll('[data-tab-panel]'));

    const listTextAreas = [
      'locations',
      'strengths',
      'cv_text',
      'llm_prompt_notes',
      'target_title_patterns',
      'adjacent_title_patterns',
      'classification_ids',
      'must_not_require_skills',
      'canberra_only_description_patterns',
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

    function setActiveTab(tabName) {
      const tabExists = tabButtons.some(button => button.dataset.tabTarget === tabName);
      const resolvedTab = tabExists ? tabName : 'search';
      for (const button of tabButtons) {
        button.classList.toggle('active', button.dataset.tabTarget === resolvedTab);
      }
      for (const panel of tabPanels) {
        panel.classList.toggle('active', panel.dataset.tabPanel === resolvedTab);
      }
      try {
        window.localStorage.setItem('seekAdminActiveTab', resolvedTab);
      } catch (error) {
      }
    }

    function toLines(value) {
      return value.split(/\\r?\\n/).map(line => line.trim()).filter(Boolean);
    }

    function rulesToText(rules, key) {
      return (rules || []).map(rule => `${rule[key] || ''} || ${rule.reason || ''}`).join('\\n');
    }

    function capabilityRulesToText(rules) {
      return (rules || []).map(rule => {
        const aliases = (rule.aliases || []).join(', ');
        return `${rule.name || ''} || ${rule.level || ''} || ${rule.fit || ''} || ${aliases}`;
      }).join('\\n');
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

    function textToCapabilityRules(value) {
      return toLines(value).map(line => {
        const parts = line.split('||');
        const aliasesIndex = parts.length >= 4 ? 3 : 2;
        return {
          name: (parts[0] || '').trim(),
          level: (parts[1] || '').trim().toLowerCase(),
          fit: (parts.length >= 4 ? (parts[2] || '') : '').trim().toLowerCase(),
          aliases: (parts[aliasesIndex] || '').split(',').map(item => item.trim()).filter(Boolean),
        };
      }).filter(rule => rule.name && rule.level && rule.aliases.length);
    }

    function fillForm(profile) {
      document.getElementById('keywords').value = profile.search_settings?.keywords || '';
      document.getElementById('locations').value = (profile.search_settings?.locations || []).join('\\n');
      document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\\n');
      document.getElementById('date_range_days').value = String(profile.search_settings?.date_range_days ?? '');
      document.getElementById('max_pages_cap').value = String(profile.search_settings?.max_pages_cap ?? '');
      document.getElementById('enforce_posted_age_limit').value = String(Boolean(profile.search_settings?.enforce_posted_age_limit));
      document.getElementById('sort_newest_first').value = String(Boolean(profile.search_settings?.sort_newest_first ?? true));
      document.getElementById('candidate_summary').value = profile.candidate_summary || '';
      document.getElementById('llm_profile_brief').value = profile.llm_profile_brief || '';
      document.getElementById('cv_text').value = profile.cv_text || '';
      document.getElementById('star_evidence_text').value = profile.star_evidence_text || '';
      document.getElementById('capability_profile_rules').value = capabilityRulesToText(profile.capability_profile_rules);

      for (const id of ['strengths', 'llm_prompt_notes', 'target_title_patterns', 'adjacent_title_patterns', 'must_not_require_skills', 'canberra_only_description_patterns']) {
        document.getElementById(id).value = (profile[id] || []).join('\\n');
      }

      for (const [id, key] of ruleTextAreas) {
        document.getElementById(id).value = rulesToText(profile[id], key);
      }

      document.getElementById('applied_job_keys').value = (profile.review_controls?.applied_job_keys || []).join('\\n');
      document.getElementById('hidden_job_keys').value = (profile.review_controls?.hidden_job_keys || []).join('\\n');
    }

    function fillSourceMaterials(materials) {
      const panel = document.getElementById('source_documents_summary');
      const sources = materials.profile_sources || [];
      if (!sources.length) {
        panel.innerHTML = 'No source pack connected yet. Start with onboarding.';
        return;
      }
      const sourceHtml = sources.map(item => `<li><strong>${escapeHtml(item.label || 'Source document')}</strong></li>`).join('');
      panel.innerHTML = `
        <p><strong>Connected source pack:</strong> ${sources.length} item(s)</p>
        <ul>${sourceHtml}</ul>
        <p>${escapeHtml(materials.notes || 'Stored locally for profile generation and later application work.')}</p>
      `;
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

    async function loadSourceMaterials() {
      const response = await fetch('/api/source-materials');
      if (!response.ok) {
        throw new Error('Could not load source documents');
      }
      const materials = await response.json();
      fillSourceMaterials(materials);
    }

    function renderRunStats(stats) {
      const panel = document.getElementById('run_stats_panel');
      if (!stats || !stats.run_started_at) {
        panel.innerHTML = '<p>No run stats yet. Run the current job-source connector once and reload this page.</p>';
        return;
      }
      const rejectHtml = (stats.top_reject_reasons || [])
        .map(item => `<li><strong>${item.reason}</strong>: ${item.count}</li>`)
        .join('');
      const targets = Object.entries(stats.search_targets || {})
        .map(([name, pages]) => `<li><strong>${name}</strong>: pages ${pages.join(', ')}</li>`)
        .join('');
      panel.innerHTML = `
        <p><strong>Run:</strong> ${stats.run_started_at}</p>
        <p><strong>Pages crawled:</strong> ${stats.page_count} | <strong>Cards seen:</strong> ${stats.cards_seen} | <strong>Detail pages opened:</strong> ${stats.detail_fetches} | <strong>Keep rate:</strong> ${(Number(stats.keep_rate || 0) * 100).toFixed(1)}%</p>
        <p><strong>Search window:</strong> last ${stats.search_window_days} day(s) | <strong>Prefer newest jobs first:</strong> ${stats.sort_newest_first ? 'Yes' : 'No'}</p>
        <p><strong>Search targets:</strong></p>
        <ul>${targets || '<li>None</li>'}</ul>
        <p><strong>Top reject reasons:</strong></p>
        <ul>${rejectHtml || '<li>None</li>'}</ul>
      `;
    }

    async function loadRunStats() {
      const response = await fetch('/api/run-stats');
      if (!response.ok) {
        renderRunStats(null);
        return;
      }
      const stats = await response.json();
      renderRunStats(stats);
    }

    function escapeHtml(value) {
      return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function reviewOptionMarkup(selectedValue) {
      const options = [
        ['', 'Choose a fit decision'],
        ['no_knowledge', 'No knowledge'],
        ['basic_only', 'Basic only'],
        ['working_knowledge', 'Working knowledge'],
        ['strong', 'Strong'],
        ['avoid', 'Avoid'],
        ['not_core_but_acceptable', 'Not core but acceptable'],
      ];
      return options.map(([value, label]) => {
        const selected = value === selectedValue ? ' selected' : '';
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
      }).join('');
    }

    function renderUnknownSkills(items) {
      const panel = document.getElementById('unknown_skills_panel');
      if (!items || !items.length) {
        panel.innerHTML = '<p>No unknown skills from recent runs. That means the profile already knows the repeated concepts it has been seeing.</p>';
        return;
      }

      panel.innerHTML = `
        <div class="review-list">
          ${items.map(item => `
            <div class="review-card">
              <h3>${escapeHtml(item.skill)}</h3>
              <p>Seen ${Number(item.count || 0)} time(s) in recent descriptions.</p>
              <label>How should we treat this?</label>
              <select class="skill-choice" data-skill="${escapeHtml(item.skill)}">
                ${reviewOptionMarkup('')}
              </select>
              <p>Examples:</p>
              <ul>
                ${(item.examples || []).map(example => `
                  <li>
                    <a href="${escapeHtml(example.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(example.title || 'Untitled role')}</a>
                    ${example.company ? ` - ${escapeHtml(example.company)}` : ''}
                    ${example.search_location ? ` (${escapeHtml(example.search_location)})` : ''}
                  </li>
                `).join('')}
              </ul>
            </div>
          `).join('')}
        </div>
      `;
    }

    function renderRejections(items) {
      const panel = document.getElementById('rejections_panel');
      if (!items || !items.length) {
        panel.innerHTML = '<p>No rejected sample data yet. Run the current job-source connector and then refresh review data.</p>';
        return;
      }

      panel.innerHTML = `
        <div class="review-list">
          ${items.map(item => `
            <div class="review-card">
              <h3>${escapeHtml(item.reason)}</h3>
              <p>${Number(item.count || 0)} job(s) rejected for this reason.</p>
              <ul>
                ${(item.samples || []).map(sample => `
                  <li>
                    <a href="${escapeHtml(sample.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(sample.title || 'Untitled role')}</a>
                    ${sample.company ? ` - ${escapeHtml(sample.company)}` : ''}
                    ${sample.search_location ? ` (${escapeHtml(sample.search_location)})` : ''}
                  </li>
                `).join('')}
              </ul>
            </div>
          `).join('')}
        </div>
      `;
    }

    async function loadReviewData() {
      const response = await fetch('/api/review-data');
      if (!response.ok) {
        renderUnknownSkills([]);
        renderRejections([]);
        return;
      }
      const payload = await response.json();
      renderUnknownSkills(payload.unknown_skills || []);
      renderRejections(payload.rejections_by_reason || []);
    }

    async function applyLearningUpdate() {
      const text = document.getElementById('learning_update_text').value.trim();
      if (!text) {
        throw new Error('Paste some new knowledge first.');
      }
      const response = await fetch('/api/learning', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not apply learning update');
      }
      fillForm(payload.profile || {});
      document.getElementById('learning_update_text').value = '';
      showStatus(payload.message || 'Learning update applied.', 'ok');
    }

    async function importKnowledgeFile() {
      const response = await fetch('/api/import-knowledge-file', {
        method: 'POST',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not import knowledge file');
      }
      fillForm(payload.profile || {});
      showStatus(payload.message || 'Knowledge file imported.', 'ok');
    }

    async function importSourceMaterials() {
      const response = await fetch('/api/import-source-materials', {
        method: 'POST',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not import source documents');
      }
      fillSourceMaterials(payload.materials || {});
      fillForm(payload.profile || {});
      const importedCount = Number((payload.imported_sources || []).length || 0);
      const missingCount = Number((payload.missing_sources || []).length || 0);
      const suffix = missingCount ? ` Imported ${importedCount}, skipped ${missingCount}.` : '';
      showStatus((payload.message || 'Source documents imported.') + suffix, 'ok');
    }

    function collectProfile() {
      return {
        search_settings: {
          keywords: document.getElementById('keywords').value.trim(),
          locations: toLines(document.getElementById('locations').value),
          classification_ids: toLines(document.getElementById('classification_ids').value),
          date_range_days: Number(document.getElementById('date_range_days').value),
          max_pages_cap: Number(document.getElementById('max_pages_cap').value),
          enforce_posted_age_limit: document.getElementById('enforce_posted_age_limit').value === 'true',
          sort_newest_first: document.getElementById('sort_newest_first').value === 'true',
        },
        review_controls: {
          applied_job_keys: toLines(document.getElementById('applied_job_keys').value),
          hidden_job_keys: toLines(document.getElementById('hidden_job_keys').value),
        },
        candidate_summary: document.getElementById('candidate_summary').value.trim(),
        llm_profile_brief: document.getElementById('llm_profile_brief').value.trim(),
        strengths: toLines(document.getElementById('strengths').value),
        cv_text: document.getElementById('cv_text').value.trim(),
        star_evidence_text: document.getElementById('star_evidence_text').value.trim(),
        capability_profile_rules: textToCapabilityRules(document.getElementById('capability_profile_rules').value),
        llm_prompt_notes: toLines(document.getElementById('llm_prompt_notes').value),
        target_title_patterns: toLines(document.getElementById('target_title_patterns').value),
        adjacent_title_patterns: toLines(document.getElementById('adjacent_title_patterns').value),
        must_not_require_skills: toLines(document.getElementById('must_not_require_skills').value),
        canberra_only_description_patterns: toLines(document.getElementById('canberra_only_description_patterns').value),
        reject_title_rules: textToRules(document.getElementById('reject_title_rules').value, 'pattern'),
        reject_description_phrase_rules: textToRules(document.getElementById('reject_description_phrase_rules').value, 'phrase'),
        reject_description_regex_rules: textToRules(document.getElementById('reject_description_regex_rules').value, 'pattern'),
      };
    }

    async function patchProfile(payload, successMessage) {
      const response = await fetch('/api/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => ({}));
        throw new Error(errorPayload.error || 'Could not save profile');
      }
      const updated = await response.json();
      fillForm(updated);
      showStatus(successMessage, 'ok');
      return updated;
    }

    async function saveSearchSettings() {
      const profile = collectProfile();
      await patchProfile(
        { search_settings: profile.search_settings },
        'Search settings saved to profile.json.'
      );
    }

    async function saveProfileSection() {
      const profile = collectProfile();
      await patchProfile(
        {
          candidate_summary: profile.candidate_summary,
          llm_profile_brief: profile.llm_profile_brief,
          strengths: profile.strengths,
          cv_text: profile.cv_text,
          star_evidence_text: profile.star_evidence_text,
          capability_profile_rules: profile.capability_profile_rules,
          llm_prompt_notes: profile.llm_prompt_notes,
          target_title_patterns: profile.target_title_patterns,
          adjacent_title_patterns: profile.adjacent_title_patterns,
          must_not_require_skills: profile.must_not_require_skills,
          canberra_only_description_patterns: profile.canberra_only_description_patterns,
          reject_title_rules: profile.reject_title_rules,
          reject_description_phrase_rules: profile.reject_description_phrase_rules,
          reject_description_regex_rules: profile.reject_description_regex_rules,
        },
        'Candidate profile saved to profile.json.'
      );
    }

    async function saveReviewControls() {
      const profile = collectProfile();
      await patchProfile(
        { review_controls: profile.review_controls },
        'Review controls saved to profile.json.'
      );
    }

    async function applySkillReviews() {
      const decisions = Array.from(document.querySelectorAll('.skill-choice'))
        .map(element => ({
          skill: element.dataset.skill || '',
          choice: element.value || '',
        }))
        .filter(item => item.skill && item.choice);

      if (!decisions.length) {
        throw new Error('Choose at least one skill decision first.');
      }

      const response = await fetch('/api/skill-decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not apply skill decisions');
      }
      fillForm(payload.profile || {});
      await loadReviewData();
      showStatus(payload.message || 'Skill decisions applied to profile.json.', 'ok');
    }

    document.getElementById('save_search').addEventListener('click', async () => {
      try {
        await saveSearchSettings();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('save_profile').addEventListener('click', async () => {
      try {
        await saveProfileSection();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('save_review_controls').addEventListener('click', async () => {
      try {
        await saveReviewControls();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('apply_learning').addEventListener('click', async () => {
      try {
        await applyLearningUpdate();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('import_knowledge_file').addEventListener('click', async () => {
      try {
        await importKnowledgeFile();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('import_source_materials').addEventListener('click', async () => {
      try {
        await importSourceMaterials();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('open_onboarding').addEventListener('click', () => {
      window.location.href = '/start';
    });

    document.getElementById('reload').addEventListener('click', async () => {
      try {
        await loadProfile();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('refresh_review').addEventListener('click', async () => {
      try {
        await Promise.all([
          loadRunStats(),
          loadReviewData(),
        ]);
        showStatus('Review data refreshed.', 'ok');
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('apply_skill_reviews').addEventListener('click', async () => {
      try {
        await applySkillReviews();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    for (const button of tabButtons) {
      button.addEventListener('click', () => setActiveTab(button.dataset.tabTarget));
    }

    try {
      const savedTab = window.localStorage.getItem('seekAdminActiveTab');
      if (savedTab) {
        setActiveTab(savedTab);
      }
    } catch (error) {
    }

    Promise.all([
      loadProfile(),
      loadSourceMaterials(),
      loadRunStats(),
      loadReviewData(),
    ]).catch(error => showStatus(error.message, 'error'));
  </script>
</body>
</html>
"""

ONBOARDING_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Hunter Agent Onboarding</title>
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
      max-width: 980px;
      margin: 0 auto;
      padding: 28px 18px 52px;
    }
    .hero, .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
    }
    .hero {
      padding: 26px;
      margin-bottom: 20px;
    }
    .hero h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 3.1rem);
      letter-spacing: -0.04em;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }
    .grid {
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    }
    .panel {
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 1.15rem;
    }
    label {
      display: block;
      margin: 12px 0 6px;
      font-weight: 700;
    }
    input, textarea {
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
      font-size: 0.92rem;
      line-height: 1.5;
    }
    .actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 22px;
    }
    button, a.button-link {
      border: 0;
      border-radius: 999px;
      padding: 11px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .primary {
      background: var(--accent);
      color: white;
    }
    .secondary, a.button-link.secondary {
      background: white;
      color: var(--accent-2);
      border: 1px solid var(--line);
    }
    .status {
      margin-top: 18px;
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
    .summary-box {
      margin-top: 18px;
      padding: 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: white;
      display: none;
    }
    .summary-box.visible {
      display: block;
    }
    .summary-box h3 {
      margin: 0 0 8px;
    }
    .summary-box p {
      margin: 0 0 10px;
      color: var(--muted);
      line-height: 1.5;
    }
    .summary-box ul {
      margin: 8px 0 0 18px;
      padding: 0;
      color: var(--muted);
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Set Up Your Profile</h1>
      <p>Start with one strong detailed CV. If you have extra background or longer career history, you can add that too. We will turn those documents into a working profile the job engine can use, and you can refine it later in admin.</p>
    </section>

    <div class="grid">
      <section class="panel">
        <h2>Step 1. Primary CV</h2>
        <label for="primary_cv">Detailed CV</label>
        <input id="primary_cv" type="file" accept=".docx,.md,.txt">
        <div class="help">This is the only required file. Use the most detailed CV you have, not the prettiest final layout.</div>

        <label for="supporting_cv">Optional supporting background</label>
        <input id="supporting_cv" type="file" accept=".docx,.md,.txt">
        <div class="help">Optional: a long-form career history or extra background document.</div>

        <label for="extra_notes">Optional extra notes</label>
        <textarea id="extra_notes" placeholder="Anything important you want the system to know, in plain English."></textarea>
        <div class="help">You can leave this blank. STAR examples can come later if you want.</div>

        <div class="actions">
          <button class="primary" id="create_profile" type="button">Create Profile</button>
          <a class="button-link secondary" href="/admin">Go To Admin</a>
        </div>
        <div class="status" id="status"></div>
      </section>

      <section class="panel">
        <h2>What Happens Next</h2>
        <div class="help">
          1. We read your uploaded document text.<br>
          2. We build or enrich <code>profile.json</code>.<br>
          3. You review the generated summary, strengths, and fit notes in admin.<br>
          4. Then you can run the current job-source connector and use the dashboard.
        </div>
        <div class="summary-box" id="summary_box">
          <h3>Generated Profile Snapshot</h3>
          <p id="summary_text"></p>
          <ul id="strengths_list"></ul>
        </div>
      </section>
    </div>
  </main>

  <script>
    const statusEl = document.getElementById('status');
    const summaryBox = document.getElementById('summary_box');
    const summaryText = document.getElementById('summary_text');
    const strengthsList = document.getElementById('strengths_list');

    function showStatus(message, kind) {
      statusEl.textContent = message;
      statusEl.className = `status ${kind}`;
    }

    async function fileToPayload(file, label) {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
        reader.readAsDataURL(file);
      });
      const parts = dataUrl.split(',', 2);
      return {
        label,
        filename: file.name,
        content_base64: parts[1] || '',
      };
    }

    function renderProfileSnapshot(profile) {
      summaryText.textContent = profile.candidate_summary || 'Profile created.';
      const strengths = (profile.strengths || []).slice(0, 8);
      strengthsList.innerHTML = strengths.map(item => `<li>${item}</li>`).join('');
      summaryBox.classList.add('visible');
    }

    async function createProfile() {
      const primary = document.getElementById('primary_cv').files[0];
      const supporting = document.getElementById('supporting_cv').files[0];
      const extraNotes = document.getElementById('extra_notes').value.trim();

      if (!primary) {
        throw new Error('Choose your detailed CV first.');
      }

      const files = [await fileToPayload(primary, 'Primary CV')];
      if (supporting) {
        files.push(await fileToPayload(supporting, 'Supporting Background'));
      }

      const response = await fetch('/api/onboarding/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files,
          extra_text: extraNotes,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not create profile');
      }
      renderProfileSnapshot(payload.profile || {});
      showStatus(payload.message || 'Profile created.', 'ok');
    }

    document.getElementById('create_profile').addEventListener('click', async () => {
      try {
        await createProfile();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });
  </script>
</body>
</html>
"""


class AdminHandler(BaseHTTPRequestHandler):
    @staticmethod
    def _combine_text_sections(*sections: str) -> str:
        cleaned: list[str] = []
        seen: set[str] = set()
        for section in sections:
            value = repair_text(str(section or ""))
            if not value:
                continue
            normalized = value.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(value)
        return "\n\n".join(cleaned).strip()

    @staticmethod
    def _merge_profile_learning_patch(current: dict, patch: dict, raw_text: str) -> dict:
        merged_patch = dict(patch or {})
        current = current or load_profile()

        imported_summary = str(merged_patch.get("candidate_summary") or "").strip()
        existing_summary = str(current.get("candidate_summary") or "").strip()
        default_summary = str(DEFAULT_PROFILE.get("candidate_summary") or "").strip()
        if imported_summary and existing_summary and existing_summary != default_summary:
            merged_patch.pop("candidate_summary", None)

        if merged_patch.get("strengths"):
            merged_patch["strengths"] = list(dict.fromkeys([
                *current.get("strengths", []),
                *merged_patch.get("strengths", []),
            ]))[:20]

        if merged_patch.get("capability_profile_rules"):
            merged_patch["capability_profile_rules"] = merge_capability_rules(
                merge_capability_rules(
                    DEFAULT_PROFILE.get("capability_profile_rules", []),
                    current.get("capability_profile_rules", []),
                ),
                merged_patch.get("capability_profile_rules", []),
            )

        if merged_patch.get("llm_prompt_notes"):
            merged_patch["llm_prompt_notes"] = list(dict.fromkeys([
                *current.get("llm_prompt_notes", []),
                *merged_patch.get("llm_prompt_notes", []),
            ]))[:30]

        merged_cv_text = AdminHandler._combine_text_sections(current.get("cv_text", ""), raw_text)
        if merged_cv_text:
            merged_patch["cv_text"] = merged_cv_text

        final_summary = str(
            merged_patch.get("candidate_summary")
            or current.get("candidate_summary")
            or ""
        ).strip()
        final_strengths = merged_patch.get("strengths") or current.get("strengths", [])
        final_rules = merged_patch.get("capability_profile_rules") or current.get("capability_profile_rules", [])
        final_notes = merged_patch.get("llm_prompt_notes") or current.get("llm_prompt_notes", [])
        llm_profile_brief = build_llm_profile_brief(
            summary=final_summary,
            strengths=final_strengths,
            capability_rules=final_rules,
            notes=final_notes,
        )
        if llm_profile_brief:
            merged_patch["llm_profile_brief"] = llm_profile_brief

        return merged_patch

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        current = current or load_profile()

        if "llm_profile_brief" in normalized:
            cleaned_brief = str(normalized.get("llm_profile_brief") or "").strip()
            if cleaned_brief:
                normalized["llm_profile_brief"] = cleaned_brief
            else:
                auto_brief = build_llm_profile_brief(
                    summary=str(normalized.get("candidate_summary", current.get("candidate_summary", "")) or "").strip(),
                    strengths=normalized.get("strengths", current.get("strengths", [])),
                    capability_rules=normalized.get(
                        "capability_profile_rules",
                        current.get("capability_profile_rules", []),
                    ),
                    notes=normalized.get("llm_prompt_notes", current.get("llm_prompt_notes", [])),
                )
                normalized["llm_profile_brief"] = auto_brief
        elif not str(current.get("llm_profile_brief") or "").strip():
            relevant_fields = {
                "candidate_summary",
                "strengths",
                "capability_profile_rules",
                "llm_prompt_notes",
            }
            if any(field in normalized for field in relevant_fields):
                auto_brief = build_llm_profile_brief(
                    summary=str(normalized.get("candidate_summary", current.get("candidate_summary", "")) or "").strip(),
                    strengths=normalized.get("strengths", current.get("strengths", [])),
                    capability_rules=normalized.get(
                        "capability_profile_rules",
                        current.get("capability_profile_rules", []),
                    ),
                    notes=normalized.get("llm_prompt_notes", current.get("llm_prompt_notes", [])),
                )
                if auto_brief:
                    normalized["llm_profile_brief"] = auto_brief

        if "star_evidence_text" in normalized:
            normalized["star_evidence_text"] = str(normalized.get("star_evidence_text") or "").strip()
        return normalized

    @staticmethod
    def _load_job_history() -> dict:
        if not JOB_HISTORY_PATH.exists():
            return {}
        try:
            payload = json.loads(JOB_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    @staticmethod
    def _save_job_history(history: dict) -> None:
        JOB_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOB_HISTORY_PATH.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _apply_learning_text(text: str) -> dict:
        cleaned = repair_text(text)
        if not cleaned:
            raise ValueError("No learning text provided")
        patch = build_learning_patch(cleaned)
        if not patch:
            raise ValueError("Could not extract structured learning from that text")
        current = load_profile()
        patch = AdminHandler._merge_profile_learning_patch(current, patch, cleaned)
        profile = patch_profile(patch)
        return {
            "ok": True,
            "message": "Learning update applied to profile.json.",
            "profile": profile,
        }

    @staticmethod
    def _normalize_job_key(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        import re

        match = re.search(r"/job/(\d+)", raw)
        if match:
            return match.group(1)
        if re.fullmatch(r"\d+", raw):
            return raw
        return raw.split("#", 1)[0]

    @classmethod
    def _persist_review_event(cls, action: str, job_key: str, url: str = "", title: str = "") -> None:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            return

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title and not entry.get("title"):
            entry["title"] = title
        if url:
            entry["url"] = url

        if action == "hidden":
            entry["is_hidden"] = True
            if not entry.get("first_hidden_at"):
                entry["first_hidden_at"] = now_iso
            entry["last_hidden_at"] = now_iso
        elif action == "unhide":
            entry["is_hidden"] = False
            entry["last_unhidden_at"] = now_iso
        elif action == "applied":
            if not entry.get("first_applied_at"):
                entry["first_applied_at"] = now_iso
            entry["last_applied_at"] = now_iso

        history[normalized] = entry
        cls._save_job_history(history)

    @classmethod
    def _append_review_key(cls, action: str, job_key: str, url: str = "", title: str = "") -> dict:
        normalized = cls._normalize_job_key(job_key)
        if not normalized:
            raise ValueError("Missing job key")

        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})

        list_name = {
            "applied": "applied_job_keys",
            "hidden": "hidden_job_keys",
        }.get(action)
        if not list_name:
            raise ValueError("Unsupported review action")

        existing = [
            cls._normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if cls._normalize_job_key(value)
        ]
        if normalized not in existing:
            existing.append(normalized)
        review_controls[list_name] = existing
        save_profile(profile)
        cls._persist_review_event(action, normalized, url=url, title=title)
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(existing),
        }

    @classmethod
    def _remove_review_key(cls, action: str, job_key: str, url: str = "", title: str = "") -> dict:
        normalized = cls._normalize_job_key(job_key)
        if not normalized:
            raise ValueError("Missing job key")

        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})

        list_name = {
            "unhide": "hidden_job_keys",
        }.get(action)
        if not list_name:
            raise ValueError("Unsupported review action")

        existing = [
            cls._normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if cls._normalize_job_key(value)
        ]
        updated = [value for value in existing if value != normalized]
        review_controls[list_name] = updated
        save_profile(profile)
        cls._persist_review_event(action, normalized, url=url, title=title)
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(updated),
        }

    @classmethod
    def _record_job_view(cls, job_key: str, url: str = "", title: str = "") -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title and not entry.get("title"):
            entry["title"] = title
        if url:
            entry["url"] = url
        entry["times_viewed"] = int(entry.get("times_viewed", 0) or 0) + 1
        if not entry.get("first_viewed_at"):
            entry["first_viewed_at"] = now_iso
        entry["last_viewed_at"] = now_iso

        history[normalized] = entry
        cls._save_job_history(history)
        return {
            "ok": True,
            "action": "viewed",
            "job_key": normalized,
            "times_viewed": entry["times_viewed"],
            "last_viewed_at": entry["last_viewed_at"],
        }

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, PATCH, POST, OPTIONS")
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
        if self.path in {"/", "/admin", "/profile", "/demo", "/start", "/onboarding", "/dashboard"}:
            if self.path == "/profile":
                self._redirect("/admin")
                return
            if self.path in {"/start", "/onboarding"}:
                self._send_html(ONBOARDING_HTML)
                return
            if self.path == "/dashboard":
                if DASHBOARD_PATH.exists():
                    self._send_html(DASHBOARD_PATH.read_text(encoding="utf-8", errors="ignore"))
                    return
                self._send_html("<h1>Dashboard not found yet</h1><p>Run the current job-source connector first.</p>")
                return
            if self.path == "/demo":
                if SHOWCASE_PATH.exists():
                    self._send_html(SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
                    return
                self._send_html("<h1>Demo page not found</h1>")
                return
            self._send_html(ADMIN_HTML)
            return
        if self.path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/api/run-stats":
            if RUN_STATS_PATH.exists():
                try:
                    payload = json.loads(RUN_STATS_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if self.path == "/api/review-data":
            if REVIEW_DATA_PATH.exists():
                try:
                    payload = json.loads(REVIEW_DATA_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if self.path == "/api/profile":
            self._send_json(200, load_profile())
            return
        if self.path == "/api/source-materials":
            self._send_json(200, load_source_materials(create_if_missing=True))
            return
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
        if self.path != "/api/profile":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            current = load_profile()
            patch = self._normalize_profile_patch_for_save(current, self._read_json_body())
            updated = patch_profile(patch)
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, updated)

    def do_PUT(self) -> None:
        if self.path == "/api/profile":
            try:
                updated = save_profile(self._read_json_body())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, updated)
            return
        if self.path == "/api/source-materials":
            try:
                updated = save_source_materials(self._read_json_body())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, updated)
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path == "/api/learning":
            try:
                payload = self._read_json_body()
                result = self._apply_learning_text(str(payload.get("text") or ""))
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/import-knowledge-file":
            try:
                knowledge_file = resolve_knowledge_file(create_if_missing=True)
                if not knowledge_file.exists():
                    raise FileNotFoundError(f"Could not find {knowledge_file}")
                result = self._apply_learning_text(knowledge_file.read_text(encoding="utf-8", errors="ignore"))
                result["message"] = f"Imported learning from {knowledge_file}."
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/import-source-materials":
            try:
                payload = self._read_json_body()
                materials = save_source_materials(payload) if payload else load_source_materials(create_if_missing=True)
                result = import_source_materials_to_profile(materials)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/onboarding/import":
            try:
                payload = self._read_json_body()
                files = payload.get("files", [])
                extra_text = str(payload.get("extra_text") or "")
                if not isinstance(files, list):
                    raise ValueError("files must be a list")
                materials = persist_uploaded_source_pack(files, extra_text=extra_text)
                result = import_source_materials_to_profile(materials)
                result["materials"] = materials
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/skill-decisions":
            try:
                payload = self._read_json_body()
                decisions = payload.get("decisions", [])
                if not isinstance(decisions, list):
                    raise ValueError("decisions must be a list")
                profile = load_profile()
                updated = apply_skill_review_decisions(profile, decisions)
                save_profile(updated)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Skill review decisions applied to profile.json.",
                    "profile": updated,
                },
            )
            return
        if self.path != "/api/review":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json_body()
            action = str(payload.get("action", "")).strip().lower()
            if action == "viewed":
                result = self._record_job_view(
                    str(payload.get("job_key") or payload.get("url") or "").strip(),
                    str(payload.get("url") or "").strip(),
                    str(payload.get("title") or "").strip(),
                )
            elif action == "unhide":
                result = self._remove_review_key(
                    action,
                    str(payload.get("job_key") or payload.get("url") or "").strip(),
                    str(payload.get("url") or "").strip(),
                    str(payload.get("title") or "").strip(),
                )
            else:
                result = self._append_review_key(
                    action,
                    str(payload.get("job_key") or payload.get("url") or "").strip(),
                    str(payload.get("url") or "").strip(),
                    str(payload.get("title") or "").strip(),
                )
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, result)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), AdminHandler)
    print(f"Admin console listening at http://{HOST}:{PORT}/admin")
    server.serve_forever()
