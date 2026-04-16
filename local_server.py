import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_settings import load_agent_settings, save_agent_settings
from config import OUTPUT_HTML
from filters import build_title_block_rule, detect_rejection_signals, normalize_title_block_phrase, suggest_title_block_phrase
from notifiers.telegram_notifier import build_telegram_connect_link, send_telegram_notification, sync_telegram_subscribers
from profile_learning import build_learning_patch, merge_capability_rules, repair_text, resolve_knowledge_file
from profile_store import DEFAULT_PROFILE, load_profile, patch_profile, save_profile
from profile_store import build_evidence_tiers_from_sections, get_evidence_tiers
from review_insights import apply_capability_tuning_decisions, build_suggested_tuning_from_saved_review
from llm_gate import extract_strengths_from_cv
from source_documents import (
    build_llm_profile_brief,
    import_source_materials_to_profile,
    load_source_materials,
    persist_uploaded_source_pack,
    run_onboarding,
    save_source_materials,
)


HOST = "127.0.0.1"
PORT = 8765
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
RUN_STATS_PATH = OUTPUT_DIR / "run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "review_data.json"
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
      max-width: 1380px;
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
      align-items: center;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    button[disabled] {
      opacity: 0.7;
      cursor: progress;
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
    .inline-status {
      display: none;
      font-size: 0.92rem;
      font-weight: 600;
    }
    .inline-status.loading,
    .inline-status.ok,
    .inline-status.error {
      display: inline-flex;
      align-items: center;
    }
    .inline-status.loading {
      color: var(--muted);
    }
    .inline-status.ok {
      color: #14532d;
    }
    .inline-status.error {
      color: #9a3412;
    }
    .panel-copy {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.45;
    }
    .panel-kicker {
      display: inline-block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .help-drawer {
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.55);
      overflow: hidden;
    }
    .help-drawer summary {
      cursor: pointer;
      list-style: none;
      padding: 12px 14px;
      font-weight: 700;
      color: var(--accent-2);
    }
    .help-drawer summary::-webkit-details-marker {
      display: none;
    }
    .help-drawer p {
      margin: 0;
      padding: 0 14px 14px;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }
    .profile-shell {
      display: grid;
      grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.95fr);
      gap: 20px;
      align-items: start;
    }
    .profile-main,
    .profile-side {
      min-width: 0;
    }
    .profile-side {
      display: grid;
      gap: 18px;
    }
    .profile-main-panel {
      padding: 22px 22px 24px;
    }
    .profile-panel-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 18px;
      padding-bottom: 18px;
      margin-bottom: 10px;
      border-bottom: 1px solid var(--line);
    }
    .profile-panel-head h2,
    .advanced-head h2 {
      margin: 0;
      font-size: 1.35rem;
    }
    .profile-panel-actions {
      justify-content: flex-end;
      margin-top: 0;
    }
    .profile-group {
      padding-top: 18px;
      margin-top: 18px;
      border-top: 1px solid rgba(230, 220, 205, 0.72);
    }
    .profile-group:first-of-type {
      border-top: 0;
      margin-top: 0;
      padding-top: 0;
    }
    .profile-group h3 {
      margin: 0;
      font-size: 1rem;
    }
    .profile-group-copy {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }
    .profile-fields-grid,
    .field-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      align-items: start;
    }
    .field-block {
      min-width: 0;
    }
    .field-block.field-span-2 {
      grid-column: 1 / -1;
    }
    .field-block label:first-child {
      margin-top: 14px;
    }
    .field-help {
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.4;
    }
    .field-help code {
      font-size: 0.82rem;
    }
    .checkbox-row {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 14px;
      font-weight: 700;
    }
    .checkbox-row input {
      width: auto;
      margin: 0;
    }
    textarea.is-readonly {
      background: #f7f2ea;
      color: #5b6470;
    }
    #llm_profile_brief {
      min-height: 170px;
    }
    #strengths,
    #star_evidence_text,
    #learning_update_text {
      min-height: 180px;
    }
    #cv_text {
      min-height: 460px;
    }
    #capability_profile_rules {
      min-height: 180px;
    }
    #target_title_patterns,
    #adjacent_title_patterns,
    #reject_title_rules,
    #reject_description_phrase_rules,
    #reject_description_regex_rules,
    #must_not_require_skills {
      min-height: 120px;
    }
    .side-panel {
      padding: 18px;
    }
    .summary-box {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.56);
      padding: 12px 14px;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }
    .advanced-shell {
      grid-column: 1 / -1;
      padding: 22px;
    }
    .advanced-head {
      margin-bottom: 14px;
    }
    .advanced-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .subpanel {
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      min-width: 0;
    }
    .subpanel h3 {
      margin: 0 0 10px;
      font-size: 1rem;
    }
    .subpanel .field-help {
      margin-bottom: 6px;
    }
    .review-list {
      display: grid;
      gap: 12px;
    }
    .tuning-summary {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .tuning-summary-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.72);
      padding: 12px;
    }
    .tuning-summary-card strong {
      display: block;
      font-size: 1.35rem;
      margin-bottom: 4px;
    }
    .tuning-summary-card span {
      color: var(--muted);
      font-size: 0.9rem;
    }
    .tuning-group + .tuning-group {
      margin-top: 16px;
    }
    .tuning-group h3 {
      margin: 0 0 6px;
      font-size: 1rem;
    }
    .tuning-group-copy {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }
    .suggestion-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0;
    }
    .suggestion-chip {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 5px 10px;
      background: rgba(244, 239, 231, 0.9);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
    }
    @media (max-width: 1180px) {
      .profile-shell {
        grid-template-columns: 1fr;
      }
      .advanced-grid {
        grid-template-columns: 1fr;
      }
      .tuning-summary {
        grid-template-columns: 1fr;
      }
    }
    @media (max-width: 760px) {
      .profile-panel-head,
      .profile-fields-grid,
      .field-grid {
        grid-template-columns: 1fr;
        display: grid;
      }
      .profile-panel-head {
        display: block;
      }
      .profile-panel-actions {
        justify-content: flex-start;
        margin-top: 14px;
      }
      .field-block.field-span-2 {
        grid-column: auto;
      }
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
      <button class="tab-button" data-tab-target="notifications">Notifications</button>
      <button class="tab-button" data-tab-target="test">Last Run</button>
    </nav>

    <section class="group tab-panel active" data-tab-panel="search">
      <h2 class="group-title">Search</h2>
      <p class="group-copy">Configure what to search for and where. Fit scoring is handled separately in the Candidate Profile tab.</p>
      <div class="grid">

      <section class="panel">
        <h2>Common</h2>
        <label for="keywords">Search keywords</label>
        <input id="keywords" type="text">
        <div class="help">Used by all enabled sources. Keep broad — fit filtering happens later.</div>

        <label for="minimum_salary_yearly">Minimum annual salary</label>
        <input id="minimum_salary_yearly" type="number" min="0" step="1000">
        <div class="help">Used when permanent roles list salary. Set 0 to ignore.</div>

        <label for="minimum_daily_rate">Minimum daily rate</label>
        <input id="minimum_daily_rate" type="number" min="0" step="50">
        <div class="help">Used when contract roles list a day rate. Set 0 to ignore.</div>
      </section>

      <section class="panel">
        <h2>SEEK</h2>
        <p class="panel-copy">These settings apply only when <code>seek</code> is listed in enabled sources.</p>

        <label for="locations">Locations</label>
        <textarea id="locations"></textarea>
        <div class="help">One location per line, e.g. <code>All Sydney NSW</code>.</div>

        <label for="classification_ids">Classification IDs</label>
        <textarea id="classification_ids"></textarea>
        <div class="help">One ID per line. Broad pre-filter before fit logic runs.</div>

        <label for="date_range_days">How far back to search</label>
        <select id="date_range_days">
          <option value="1">Today</option>
          <option value="3">Last 3 days</option>
          <option value="7">Last 7 days</option>
          <option value="14">Last 14 days</option>
          <option value="30">Last 30 days</option>
        </select>

        <label for="max_pages_cap">Max pages to check</label>
        <input id="max_pages_cap" type="number" min="1" max="25">
        <div class="help">Hard cap of 25 pages is always enforced.</div>

        <label for="enforce_posted_age_limit">Strictly reject older ads</label>
        <select id="enforce_posted_age_limit">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>

        <label for="sort_newest_first">Prefer newest jobs first</label>
        <select id="sort_newest_first">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </section>

      <section class="panel">
        <h2>LinkedIn</h2>
        <p class="panel-copy">These settings apply only when <code>linkedin</code> is listed in enabled sources.</p>

        <label for="linkedin_hours_old">How far back to search (hours)</label>
        <input id="linkedin_hours_old" type="number" min="1" max="168">
        <div class="help">24 = last day, 72 = last 3 days.</div>

        <label for="linkedin_results_per_search">Results per search</label>
        <input id="linkedin_results_per_search" type="number" min="5" max="100">
        <div class="help">Max results per keyword + location pair.</div>

        <label for="linkedin_easy_apply_only">Easy Apply filter</label>
        <select id="linkedin_easy_apply_only">
          <option value="">Both (no filter)</option>
          <option value="true">Easy Apply only</option>
          <option value="false">Non-Easy Apply only</option>
        </select>
      </section>

      </div>
      <div class="panel-actions" style="padding: 0 0 1.5rem 0;">
        <button class="primary" id="save_search">Save Search Settings</button>
      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="profile">
      <h2 class="group-title">Candidate Profile</h2>
      <p class="group-copy">Upload your CV during onboarding. Refine strengths, notes, and matching rules here.</p>
      <div class="profile-shell">
      <div class="profile-main">
      <section class="panel profile-main-panel">
        <div class="profile-panel-head">
          <div>
            <div class="panel-kicker">Main profile editing</div>
            <h2>Candidate Profile</h2>
            <p class="panel-copy">Your CV is the source of truth. Strengths and notes here refine how the engine scores fit.</p>
          </div>
          <div class="panel-actions profile-panel-actions">
            <button class="primary" id="save_profile">Save Profile</button>
            <span class="inline-status" id="save_profile_status" aria-live="polite"></span>
          </div>
        </div>

        <section class="profile-group">
          <details class="help-drawer">
            <summary>Advanced AI context</summary>
            <p>The AI fit brief is normally auto-generated from your CV and strengths. Only turn on manual override if you want to force a custom machine-facing brief.</p>
            <div class="field-grid" style="padding: 0 14px 14px;">
              <div class="field-block field-span-2">
                <label class="checkbox-row" for="llm_profile_brief_manual_override">
                  <input id="llm_profile_brief_manual_override" type="checkbox">
                  Manually override AI fit brief
                </label>
                <div class="field-help" id="llm_profile_brief_mode_hint">Auto-generated from your main profile inputs.</div>
              </div>
              <div class="field-block field-span-2">
                <label for="llm_profile_brief">AI fit brief preview</label>
                <textarea id="llm_profile_brief"></textarea>
                <div class="field-help" id="llm_profile_brief_help">Preview only while auto mode is active.</div>
              </div>
            </div>
          </details>
        </section>

        <section class="profile-group">
          <h3>Strength Signals</h3>
          <p class="profile-group-copy">Auto-extracted from your CV. Add or remove signals to tune how the engine scores fit.</p>
          <div class="profile-fields-grid">
            <div class="field-block field-span-2">
              <label for="strengths">Strengths</label>
              <textarea id="strengths"></textarea>
              <div class="field-help">One signal per line. Re-extracted automatically when CV changes.</div>
            </div>
          </div>
        </section>


        <section class="profile-group">
          <h3>Decision Weights</h3>
          <p class="profile-group-copy">Tell the ranking engine what matters more right now. Leave everything at Normal if you want the default balance.</p>
          <div class="field-grid">
            <div class="field-block">
              <label for="fit_weight">Overall fit</label>
              <select id="fit_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Scales title fit, description fit, evidence, specialist signals, and watchout penalties.</div>
            </div>
            <div class="field-block">
              <label for="salary_weight">Salary</label>
              <select id="salary_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Use this when market reality matters more than your ideal pay floor, or the reverse.</div>
            </div>
            <div class="field-block">
              <label for="location_weight">Location / travel</label>
              <select id="location_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Scales Sydney preference and Canberra travel/on-site penalties.</div>
            </div>
            <div class="field-block">
              <label for="work_mode_weight">Remote / hybrid</label>
              <select id="work_mode_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Scales the hybrid and remote bonuses.</div>
            </div>
            <div class="field-block">
              <label for="contract_weight">Contract shape</label>
              <select id="contract_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Scales the permanent bonus and contract-length preference.</div>
            </div>
            <div class="field-block">
              <label for="government_weight">Government context</label>
              <select id="government_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Use this if government delivery context matters more or less than usual.</div>
            </div>
            <div class="field-block">
              <label for="freshness_weight">Freshness</label>
              <select id="freshness_weight">
                <option value="0">Ignore for now</option>
                <option value="0.5">Light</option>
                <option value="1" selected>Normal</option>
                <option value="1.5">High</option>
                <option value="2">Very high</option>
              </select>
              <div class="field-help">Scales how much newer postings get rewarded over older but still relevant roles.</div>
            </div>
          </div>
        </section>

        <section class="profile-group">
          <h3>Core Source Text</h3>
          <p class="profile-group-copy">Main evidence the engine can draw from during matching and AI review.</p>
          <div class="profile-fields-grid">
            <div class="field-block field-span-2">
              <label for="cv_text">CV / background text</label>
              <textarea id="cv_text"></textarea>
              <div class="field-help">Primary source material used for matching, specialist-fit checks, and AI review.</div>
            </div>
            <div class="field-block field-span-2">
              <label for="star_evidence_text">STAR / evidence notes</label>
              <textarea id="star_evidence_text"></textarea>
              <div class="field-help">Optional examples, impact stories, or selection-criteria style evidence.</div>
            </div>
          </div>
        </section>
      </section>
      </div>

      <aside class="profile-side">
      <section class="panel side-panel">
        <div class="panel-kicker">Source management</div>
        <h2>Source Documents</h2>
        <p class="panel-copy">Saved onboarding files and profile rebuild tools.</p>
        <div id="source_documents_summary" class="summary-box">No source pack connected yet. Start with onboarding.</div>
        <details class="help-drawer">
          <summary>What this is for</summary>
          <p>The app stores uploaded source material locally so you can rebuild the candidate profile later without pasting everything again.</p>
        </details>
        <div class="panel-actions">
          <button class="secondary" id="open_onboarding" type="button">Open Onboarding / Source Pack</button>
          <span class="inline-status" id="source_materials_status" aria-live="polite"></span>
        </div>
        <details class="help-drawer" style="margin-top:14px;border:1px solid #f9a8a8;border-radius:10px;padding:10px 12px;background:#fff5f5;">
          <summary style="font-weight:700;color:#9a3412;cursor:pointer;">Danger: Rebuild Profile From Saved Documents</summary>
          <p style="margin:8px 0 10px;color:#7f1d1d;font-size:0.9rem;">This overwrites your current profile strengths, capability rules, and evidence tiers using the last uploaded source documents. Any manual edits made since onboarding will be replaced. Only use this if you have re-uploaded a new version of your CV.</p>
          <button class="secondary" id="import_source_materials" style="border-color:#f87171;color:#9a3412;">Rebuild Profile Now</button>
        </details>
      </section>

      <section class="panel side-panel">
        <div class="panel-kicker">Incremental learning</div>
        <h2>Learning Inbox</h2>
        <p class="panel-copy">Add new capability notes without editing the whole profile manually.</p>
        <label for="learning_update_text">Paste new candidate knowledge</label>
        <textarea id="learning_update_text"></textarea>
        <div class="field-help">Paste CV text, capability notes, or a focused knowledge update.</div>
        <div class="panel-actions">
          <button class="secondary" id="apply_learning">Apply Learning Update</button>
          <button class="secondary" id="import_knowledge_file">Import Local Capability Note</button>
          <span class="inline-status" id="learning_status" aria-live="polite"></span>
        </div>
      </section>
      </aside>

      <section class="panel advanced-shell">
        <div class="advanced-head">
          <div class="panel-kicker">Advanced tuning</div>
          <h2>Advanced Matching Rules</h2>
          <p class="panel-copy">Engine-tuning controls kept separate from the main candidate profile editor.</p>
        </div>
        <details class="help-drawer">
          <summary>When to edit these rules</summary>
          <p>Use these controls when the engine is matching too broadly or missing obvious rejects. These are tuning rules, not core profile storytelling fields.</p>
        </details>
        <div class="advanced-grid">
          <section class="subpanel">
            <h3>Capability Matrix</h3>
            <label for="capability_profile_rules">Capability profile rules</label>
            <textarea id="capability_profile_rules"></textarea>
            <div class="field-help">Format: <code>name || level || fit || alias 1, alias 2</code>.</div>
          </section>

          <section class="subpanel">
            <h3>Title Matching</h3>
            <label for="target_title_patterns">Target title patterns</label>
            <textarea id="target_title_patterns"></textarea>
            <div class="field-help">One strong-match regex per line.</div>

            <label for="adjacent_title_patterns">Adjacent title patterns</label>
            <textarea id="adjacent_title_patterns"></textarea>
            <div class="field-help">One possible-match regex per line.</div>

            <label for="reject_title_rules">Reject title rules</label>
            <div id="reject_title_rules_chips" class="rule-chips" style="margin-bottom:8px;display:flex;flex-wrap:wrap;gap:6px;"></div>
            <textarea id="reject_title_rules"></textarea>
            <div class="field-help">Format: <code>pattern || reason</code>. Rules added via the dashboard appear above automatically.</div>
          </section>

          <section class="subpanel">
            <h3>Description Exclusions</h3>
            <label for="reject_description_phrase_rules">Reject description phrases</label>
            <textarea id="reject_description_phrase_rules"></textarea>
            <div class="field-help">Format: <code>phrase || reason</code>.</div>

            <label for="reject_description_regex_rules">Reject description regex rules</label>
            <textarea id="reject_description_regex_rules"></textarea>
            <div class="field-help">Format: <code>pattern || reason</code>.</div>

            <label for="must_not_require_skills">Mandatory skills you do not have</label>
            <textarea id="must_not_require_skills"></textarea>
            <div class="field-help">One skill per line for essential-skill rejection.</div>

          </section>

          <section class="subpanel">
            <h3>Onboarding Settings</h3>
            <p class="panel-copy" style="font-size:0.88rem;">Controls used when running onboarding or Rebuild Profile. Change these before re-running onboarding if the extracted title patterns were too broad or too narrow.</p>

            <label for="os_lookback_years">Title extraction lookback (years)</label>
            <input id="os_lookback_years" type="number" min="1" max="20" step="1">
            <div class="field-help">Only include roles that ended within this many years. Default 8.</div>

            <label for="os_min_months">Minimum role duration (months)</label>
            <input id="os_min_months" type="number" min="1" max="24" step="1">
            <div class="field-help">Skip roles held for fewer than this many months. Default 6.</div>

            <label for="os_max_target">Max target title patterns</label>
            <input id="os_max_target" type="number" min="1" max="20" step="1">
            <div class="field-help">Cap on target_title_patterns extracted. Default 8.</div>

            <label for="os_max_adjacent">Max adjacent title patterns</label>
            <input id="os_max_adjacent" type="number" min="1" max="20" step="1">
            <div class="field-help">Cap on adjacent_title_patterns extracted. Default 6.</div>
          </section>
        </div>
      </section>
      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="review">
      <h2 class="group-title">Review</h2>
      <p class="group-copy">Manage review state here, then act on repeated tuning signals from viable roles and filtered noise.</p>
      <div class="grid">
      <section class="panel">
        <h2>Suggested Tuning</h2>
        <div id="tuning_suggestions_panel" class="help">Run the job source connector to see capability suggestions and repeated junk-role signals.</div>
        <div class="panel-actions">
          <button class="secondary" id="refresh_review_data">Refresh Suggestions</button>
        </div>
      </section>
      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="notifications">
      <h2 class="group-title">Notifications</h2>
      <p class="group-copy">Configure how and when the agent notifies you about new matches.</p>
      <div class="grid">

      <section class="panel">
        <h2>Alerts</h2>
        <label for="telegram_enabled">Telegram alerts enabled</label>
        <select id="telegram_enabled">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>

        <label for="telegram_bot_token">Telegram bot token</label>
        <input id="telegram_bot_token" type="password" placeholder="123456:ABC...">
        <div class="help">Only you paste the bot token here. End users never need to see chat ids.</div>

        <label for="telegram_bot_username">Telegram bot username</label>
        <input id="telegram_bot_username" type="text" placeholder="JobNotifierBot">
        <div class="help">This is used to build the one-tap connect link. Leave off the @ symbol.</div>

        <label for="telegram_disable_link_preview">Disable dashboard link preview</label>
        <select id="telegram_disable_link_preview">
          <option value="false">No</option>
          <option value="true">Yes</option>
        </select>

        <div id="telegram_connect_panel" class="help">Save Telegram settings to generate a one-tap connect link.</div>
        <div id="telegram_subscribers_panel" class="help">No Telegram subscribers synced yet.</div>

        <label for="telegram_test_message">Telegram test message</label>
        <textarea id="telegram_test_message">Job Hunter test message.</textarea>

        <div class="panel-actions">
          <button class="primary" id="save_alerts">Save Alert Settings</button>
          <button class="secondary" id="open_telegram_connect" type="button">Open Connect Link</button>
          <button class="secondary" id="sync_telegram_subscribers" type="button">Sync Telegram Subscribers</button>
          <button class="secondary" id="send_telegram_test" type="button">Send Telegram Test</button>
        </div>
      </section>

      </div>
    </section>

    <section class="group tab-panel" data-tab-panel="test">
      <h2 class="group-title">Last Run</h2>
      <p class="group-copy">Latest run stats and false-reject debugging tools.</p>
      <div class="grid">
      <section class="panel">
        <h2>Latest Run Stats</h2>
        <div id="run_stats_panel" class="help">No run stats loaded yet.</div>
        <div class="panel-actions">
          <button class="secondary" id="refresh_review">Refresh Admin Data</button>
          <button class="secondary" id="reload">Reload Profile</button>
        </div>
      </section>
      </div>
    </section>

    <div class="status" id="status"></div>
  </main>

  <script>
    const statusEl = document.getElementById('status');
    const saveProfileButton = document.getElementById('save_profile');
    const saveProfileStatusEl = document.getElementById('save_profile_status');
    const llmProfileBriefModeToggle = document.getElementById('llm_profile_brief_manual_override');
    const llmProfileBriefEl = document.getElementById('llm_profile_brief');
    const llmProfileBriefModeHintEl = document.getElementById('llm_profile_brief_mode_hint');
    const llmProfileBriefHelpEl = document.getElementById('llm_profile_brief_help');
    const importSourceMaterialsButton = document.getElementById('import_source_materials');
    const sourceMaterialsStatusEl = document.getElementById('source_materials_status');
    const applyLearningButton = document.getElementById('apply_learning');
    const importKnowledgeFileButton = document.getElementById('import_knowledge_file');
    const learningStatusEl = document.getElementById('learning_status');
    const tabButtons = Array.from(document.querySelectorAll('[data-tab-target]'));
    const tabPanels = Array.from(document.querySelectorAll('[data-tab-panel]'));
    let telegramConnectLink = '';

    const listTextAreas = [
      'locations',
      'strengths',
      'cv_text',
      'target_title_patterns',
      'adjacent_title_patterns',
      'classification_ids',
      'must_not_require_skills',
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

    function showInlineStatus(element, message, kind) {
      if (!element) {
        return;
      }
      element.textContent = message;
      element.className = `inline-status ${kind}`;
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

    function syncLlmProfileBriefMode() {
      const manualMode = Boolean(llmProfileBriefModeToggle?.checked);
      if (llmProfileBriefEl) {
        llmProfileBriefEl.readOnly = !manualMode;
        llmProfileBriefEl.classList.toggle('is-readonly', !manualMode);
      }
      if (llmProfileBriefModeHintEl) {
        llmProfileBriefModeHintEl.textContent = manualMode
          ? 'Manual override is active. This text will be saved exactly as written.'
          : 'Auto-generated from your main profile inputs.';
      }
      if (llmProfileBriefHelpEl) {
        llmProfileBriefHelpEl.textContent = manualMode
          ? 'Use this only when you need to override the generated AI-facing brief.'
          : 'Preview only while auto mode is active.';
      }
    }

    function fillForm(profile) {
      document.getElementById('keywords').value = profile.search_settings?.keywords || '';
      document.getElementById('locations').value = (profile.search_settings?.locations || []).join('\\n');
      document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\\n');
      document.getElementById('date_range_days').value = String(profile.search_settings?.date_range_days ?? '');
      document.getElementById('max_pages_cap').value = String(profile.search_settings?.max_pages_cap ?? '');
      document.getElementById('enforce_posted_age_limit').value = String(Boolean(profile.search_settings?.enforce_posted_age_limit));
      document.getElementById('sort_newest_first').value = String(Boolean(profile.search_settings?.sort_newest_first ?? true));
      document.getElementById('linkedin_hours_old').value = String(profile.search_settings?.linkedin_hours_old ?? 24);
      document.getElementById('linkedin_results_per_search').value = String(profile.search_settings?.linkedin_results_per_search ?? 25);
      const _liEasyApply = profile.search_settings?.linkedin_easy_apply_only;
      document.getElementById('linkedin_easy_apply_only').value = (_liEasyApply === null || _liEasyApply === undefined) ? '' : String(_liEasyApply);
      document.getElementById('llm_profile_brief').value = profile.llm_profile_brief || '';
      document.getElementById('llm_profile_brief_manual_override').checked = (profile.llm_profile_brief_mode || 'auto') === 'manual';
      document.getElementById('minimum_salary_yearly').value = String(profile.salary_preferences?.minimum_salary_yearly || '');
      document.getElementById('minimum_daily_rate').value = String(profile.salary_preferences?.minimum_daily_rate || '');
      document.getElementById('fit_weight').value = String(profile.preference_weights?.fit ?? 1);
      document.getElementById('salary_weight').value = String(profile.preference_weights?.salary ?? 1);
      document.getElementById('location_weight').value = String(profile.preference_weights?.location ?? 1);
      document.getElementById('work_mode_weight').value = String(profile.preference_weights?.work_mode ?? 1);
      document.getElementById('contract_weight').value = String(profile.preference_weights?.contract ?? 1);
      document.getElementById('government_weight').value = String(profile.preference_weights?.government ?? 1);
      document.getElementById('freshness_weight').value = String(profile.preference_weights?.freshness ?? 1);
      document.getElementById('cv_text').value = profile.cv_text || '';
      document.getElementById('star_evidence_text').value = profile.star_evidence_text || '';
      document.getElementById('capability_profile_rules').value = capabilityRulesToText(profile.capability_profile_rules);

      for (const id of ['strengths', 'target_title_patterns', 'adjacent_title_patterns', 'must_not_require_skills']) {
        document.getElementById(id).value = (profile[id] || []).join('\\n');
      }

      for (const [id, key] of ruleTextAreas) {
        document.getElementById(id).value = rulesToText(profile[id], key);
      }

      const os = profile.onboarding_settings || {};
      document.getElementById('os_lookback_years').value = String(os.title_extraction_lookback_years ?? 8);
      document.getElementById('os_min_months').value = String(os.title_extraction_min_months ?? 6);
      document.getElementById('os_max_target').value = String(os.max_target_patterns ?? 8);
      document.getElementById('os_max_adjacent').value = String(os.max_adjacent_patterns ?? 6);

      syncLlmProfileBriefMode();
      renderTitleBlockChips(profile.reject_title_rules || []);
    }

    function renderTitleBlockChips(rules) {
      const container = document.getElementById('reject_title_rules_chips');
      if (!container) return;
      if (!rules.length) {
        container.innerHTML = '<span style="color:var(--muted);font-size:0.85rem;">No title blocks yet. Rules added from the dashboard appear here.</span>';
        return;
      }
      container.innerHTML = rules.map(rule => {
        const reason = (rule.reason || '').replace('TITLE_BAD_KEYWORD:', '');
        const pattern = escapeHtml(rule.pattern || '');
        return `<span class="rule-chip" style="display:inline-flex;align-items:center;gap:6px;background:rgba(154,52,18,0.07);border:1px solid rgba(154,52,18,0.18);border-radius:999px;padding:4px 10px;font-size:0.83rem;">
          <span title="${pattern}">${escapeHtml(reason || pattern)}</span>
          <button type="button" data-delete-title-block="${pattern}" title="Remove this title block" style="background:none;border:none;cursor:pointer;color:var(--muted);font-size:1rem;line-height:1;padding:0;">×</button>
        </span>`;
      }).join('');
    }

    document.addEventListener('click', async e => {
      const deleteBtn = e.target.closest('[data-delete-title-block]');
      if (!deleteBtn) return;
      const pattern = deleteBtn.dataset.deleteTitleBlock;
      if (!pattern) return;
      deleteBtn.disabled = true;
      try {
        const resp = await fetch('/api/rule/title-block', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pattern }),
        });
        const payload = await resp.json();
        if (payload.ok) {
          renderTitleBlockChips(payload.reject_title_rules || []);
          const ta = document.getElementById('reject_title_rules');
          if (ta) ta.value = rulesToText(payload.reject_title_rules, 'pattern');
        } else {
          alert(payload.error || 'Could not remove rule.');
          deleteBtn.disabled = false;
        }
      } catch {
        deleteBtn.disabled = false;
      }
    });

    function renderTelegramSubscribers(subscribers) {
      const panel = document.getElementById('telegram_subscribers_panel');
      if (!subscribers || !subscribers.length) {
        panel.innerHTML = 'No Telegram subscribers synced yet.';
        return;
      }
      panel.innerHTML = `
        <p><strong>Connected Telegram users:</strong> ${subscribers.length}</p>
        <ul>
          ${subscribers.map(item => `
            <li>
              ${escapeHtml(item.first_name || item.username || item.chat_id || 'Telegram user')}
              ${item.username ? ` (@${escapeHtml(item.username)})` : ''}
            </li>
          `).join('')}
        </ul>
      `;
    }

    function renderTelegramConnectPanel(settings) {
      const panel = document.getElementById('telegram_connect_panel');
      if (!settings?.telegram?.bot_token_present) {
        telegramConnectLink = '';
        panel.innerHTML = 'Save Telegram settings to generate a one-tap connect link.';
        return;
      }
      if (!telegramConnectLink) {
        panel.innerHTML = 'Bot token saved. Use Open Connect Link to generate the one-tap Telegram join link.';
        return;
      }
      panel.innerHTML = `
        <p><strong>One-tap connect link:</strong></p>
        <p><a href="${escapeHtml(telegramConnectLink)}" target="_blank" rel="noreferrer">${escapeHtml(telegramConnectLink)}</a></p>
        <p>Share that link with users. They just tap it and press Start in Telegram once.</p>
      `;
    }

    function fillAgentSettings(settings) {
      const telegram = settings?.telegram || {};
      document.getElementById('telegram_enabled').value = String(Boolean(telegram.enabled));
      document.getElementById('telegram_bot_token').value = '';
      document.getElementById('telegram_bot_username').value = telegram.bot_username || '';
      document.getElementById('telegram_disable_link_preview').value = String(Boolean(telegram.disable_link_preview));
      telegramConnectLink = telegram.bot_username ? `https://t.me/${telegram.bot_username}?start=connect` : telegramConnectLink;
      renderTelegramSubscribers(telegram.subscribers || []);
      renderTelegramConnectPanel(settings);
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
        <p><strong>Saved source documents:</strong> ${sources.length} item(s)</p>
        <ul>${sourceHtml}</ul>
        <p>${escapeHtml(materials.notes || 'Stored locally so the app can rebuild your profile and later application outputs from the same source material.')}</p>
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

    function collectAgentSettings() {
      return {
        telegram: {
          enabled: document.getElementById('telegram_enabled').value === 'true',
          bot_token: document.getElementById('telegram_bot_token').value.trim(),
          bot_username: document.getElementById('telegram_bot_username').value.trim().replace(/^@+/, ''),
          disable_link_preview: document.getElementById('telegram_disable_link_preview').value === 'true',
        }
      };
    }

    async function loadAgentSettings() {
      const response = await fetch('/api/agent-settings');
      if (!response.ok) {
        throw new Error('Could not load alert settings');
      }
      const settings = await response.json();
      fillAgentSettings(settings);
    }

    async function saveAgentSettings() {
      const response = await fetch('/api/agent-settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectAgentSettings()),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not save alert settings');
      }
      fillAgentSettings(payload);
      showStatus('Alert settings saved.', 'ok');
      return payload;
    }

    async function loadTelegramConnectLink() {
      const response = await fetch('/api/telegram/connect-link');
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not build Telegram connect link');
      }
      telegramConnectLink = payload.connect_link || '';
      renderTelegramConnectPanel({ telegram: { bot_token_present: true } });
      return payload;
    }

    async function syncTelegramSubscribers() {
      const response = await fetch('/api/telegram/sync', { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not sync Telegram subscribers');
      }
      fillAgentSettings(payload.settings || {});
      if (payload.result?.bot_username) {
        telegramConnectLink = `https://t.me/${payload.result.bot_username}?start=connect`;
      }
      renderTelegramConnectPanel(payload.settings || {});
      showStatus(payload.message || 'Telegram subscribers synced.', 'ok');
      return payload;
    }

    async function sendTelegramTestMessage() {
      const response = await fetch('/api/telegram/test-message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: document.getElementById('telegram_test_message').value.trim() }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not send Telegram test message');
      }
      showStatus(payload.message || 'Telegram test message sent.', 'ok');
      return payload;
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

    function buildLegacySuggestedTuning(payload) {
      const capabilitySuggestions = (payload.unknown_skills || []).map(item => ({
        kind: 'capability',
        skill: item.skill,
        count: Number(item.count || 0),
        headline: `Classify ${item.skill} as a known capability signal`,
        detail: `Seen in ${Number(item.count || 0)} recent role description(s) and still unclassified.`,
        target: 'Capability matrix',
        recommended_choice: Number(item.count || 0) >= 3 ? 'working_knowledge' : 'not_core_but_acceptable',
        recommended_label: Number(item.count || 0) >= 3 ? 'Working knowledge' : 'Not core but acceptable',
        current_treatment: 'Unclassified',
        examples: item.examples || [],
      }));
      const ruleSuggestions = (payload.rejections_by_reason || []).slice(0, 4).map(item => ({
        kind: 'rule',
        reason: item.reason,
        count: Number(item.count || 0),
        headline: item.reason,
        detail: `${Number(item.count || 0)} role(s) were filtered for this reason.`,
        target: 'Matching rules',
        recommendation: 'Review this signal and decide whether the matching rules need refinement.',
        samples: item.samples || [],
      }));
      return {
        summary: {
          capability_count: capabilitySuggestions.length,
          rule_count: ruleSuggestions.length,
        },
        capability_suggestions: capabilitySuggestions,
        rule_suggestions: ruleSuggestions,
      };
    }

    function suggestionExamplesMarkup(items, emptyLabel) {
      if (!items || !items.length) {
        return `<p>${escapeHtml(emptyLabel)}</p>`;
      }
      return `
        <ul>
          ${items.map(item => `
            <li>
              <a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(item.title || 'Untitled role')}</a>
              ${item.company ? ` - ${escapeHtml(item.company)}` : ''}
              ${item.search_location ? ` (${escapeHtml(item.search_location)})` : ''}
            </li>
          `).join('')}
        </ul>
      `;
    }

    function renderSuggestedTuning(suggestions) {
      const panel = document.getElementById('tuning_suggestions_panel');
      const capabilitySuggestions = suggestions.capability_suggestions || [];
      const ruleSuggestions = suggestions.rule_suggestions || [];
      const summary = suggestions.summary || {};

      if (!capabilitySuggestions.length && !ruleSuggestions.length) {
        panel.innerHTML = '<p>No tuning suggestions yet. Once the current run sees repeated useful signals or repeat junk patterns, they will show up here.</p>';
        return;
      }

      const capabilityHtml = capabilitySuggestions.length ? `
        <div class="tuning-group">
          <h3>Capability signals from viable roles</h3>
          <p class="tuning-group-copy">Repeated concepts from kept roles that are worth classifying or upgrading. <em>Capability Matrix: Skills and tools the engine uses to score how well a job description matches your profile.</em></p>
          <div class="review-list">
            ${capabilitySuggestions.map(item => `
              <div class="review-card">
                <h3>${escapeHtml(item.headline || item.skill || 'Capability signal')}</h3>
                <p>${escapeHtml(item.detail || '')}</p>
                <div class="suggestion-meta">
                  <span class="suggestion-chip">Target: ${escapeHtml(item.target || 'Capability matrix')}</span>
                  <span class="suggestion-chip">Suggested: ${escapeHtml(item.recommended_label || 'Review')}</span>
                  <span class="suggestion-chip">Current: ${escapeHtml(item.current_treatment || 'Unclassified')}</span>
                </div>
                <label>Recommended classification</label>
                <select class="skill-choice" data-skill="${escapeHtml(item.skill || '')}">
                  ${reviewOptionMarkup(item.recommended_choice || '')}
                </select>
                <p>Examples from kept roles:</p>
                ${suggestionExamplesMarkup(item.examples || [], 'No example roles saved for this signal yet.')}
                <div class="card-actions" style="margin-top:10px;">
                  <button class="primary confirm-skill-btn" data-skill="${escapeHtml(item.skill || '')}" style="font-size:0.9rem;padding:8px 16px;">Confirm</button>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : '';

      const actionableRules = ruleSuggestions.filter(item => !(item.reason || '').startsWith('TITLE_NOT_TARGET') && !(item.reason || '').startsWith('TITLE_BAD_KEYWORD'));
      const workingFilters = ruleSuggestions.filter(item => (item.reason || '').startsWith('TITLE_BAD_KEYWORD'));

      function ruleCardMarkup(item) {
        return `
          <div class="review-card">
            <h3>${escapeHtml(item.headline || item.reason || 'Rule signal')}</h3>
            <p>${escapeHtml(item.detail || '')}</p>
            <div class="suggestion-meta">
              <span class="suggestion-chip">Target: ${escapeHtml(item.target || 'Matching rules')}</span>
              <span class="suggestion-chip">Count: ${escapeHtml(String(item.count || 0))}</span>
            </div>
            <p><strong>Suggested action:</strong> ${escapeHtml(item.recommendation || 'Review this signal and decide whether the matching rules need refinement.')}</p>
            <p>Examples:</p>
            ${suggestionExamplesMarkup(item.samples || [], 'No sample roles saved for this signal yet.')}
            ${(item.reason || '').startsWith('DESC_CAPABILITY_LOW') ? `
            <div class="card-actions" style="margin-top:10px;">
              <button class="secondary add-phrase-exclusion-btn" data-reason="${escapeHtml(item.reason || '')}" style="font-size:0.9rem;padding:8px 16px;border-color:#f87171;color:#9a3412;">Add to exclusions</button>
            </div>` : ''}
            ${(item.reason || '').startsWith('TITLE_BAD_KEYWORD') ? `
            <div class="card-actions" style="margin-top:10px;">
              <button class="secondary dismiss-rule-card-btn" style="font-size:0.9rem;padding:8px 16px;">Dismiss</button>
            </div>` : ''}
          </div>`;
      }

      const ruleHtml = (actionableRules.length || workingFilters.length) ? `
        <div class="tuning-group">
          <h3>Repeated junk-role signals</h3>
          <p class="tuning-group-copy">Patterns from rejects that are worth keeping, strengthening, or watching before you touch search keywords.</p>
          ${actionableRules.length ? `<div class="review-list">${actionableRules.map(ruleCardMarkup).join('')}</div>` : ''}
          ${workingFilters.length ? `
          <details style="margin-top:14px;">
            <summary style="cursor:pointer;color:var(--muted);font-size:0.88rem;">Filters already working correctly (${workingFilters.length})</summary>
            <div class="review-list" style="margin-top:10px;">${workingFilters.map(ruleCardMarkup).join('')}</div>
          </details>` : ''}
        </div>
      ` : '';

      panel.innerHTML = `
        <div class="tuning-summary">
          <div class="tuning-summary-card">
            <strong>${escapeHtml(String(summary.capability_count || capabilitySuggestions.length || 0))}</strong>
            <span>Capability suggestions</span>
          </div>
          <div class="tuning-summary-card">
            <strong>${escapeHtml(String(summary.rule_count || ruleSuggestions.length || 0))}</strong>
            <span>Rule signals to review</span>
          </div>
        </div>
        ${capabilityHtml}
        ${ruleHtml}
      `;
    }

    async function loadReviewData() {
      const response = await fetch('/api/review-data');
      if (!response.ok) {
        renderSuggestedTuning({ capability_suggestions: [], rule_suggestions: [], summary: {} });
        return;
      }
      const payload = await response.json();
      renderSuggestedTuning(payload.suggested_tuning || buildLegacySuggestedTuning(payload));
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
      await loadReviewData();
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
      await loadReviewData();
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
      await loadReviewData();
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
          linkedin_hours_old: Number(document.getElementById('linkedin_hours_old').value) || 24,
          linkedin_results_per_search: Number(document.getElementById('linkedin_results_per_search').value) || 25,
          linkedin_easy_apply_only: (() => { const v = document.getElementById('linkedin_easy_apply_only').value; return v === '' ? null : v === 'true'; })(),
        },
        salary_preferences: {
          minimum_salary_yearly: Number(document.getElementById('minimum_salary_yearly').value || 0),
          minimum_daily_rate: Number(document.getElementById('minimum_daily_rate').value || 0),
        },
        preference_weights: {
          fit: Number(document.getElementById('fit_weight').value || 1),
          salary: Number(document.getElementById('salary_weight').value || 1),
          location: Number(document.getElementById('location_weight').value || 1),
          work_mode: Number(document.getElementById('work_mode_weight').value || 1),
          contract: Number(document.getElementById('contract_weight').value || 1),
          government: Number(document.getElementById('government_weight').value || 1),
          freshness: Number(document.getElementById('freshness_weight').value || 1),
        },
        llm_profile_brief_mode: document.getElementById('llm_profile_brief_manual_override').checked ? 'manual' : 'auto',
        llm_profile_brief: document.getElementById('llm_profile_brief_manual_override').checked
          ? document.getElementById('llm_profile_brief').value.trim()
          : '',
        strengths: toLines(document.getElementById('strengths').value),
        cv_text: document.getElementById('cv_text').value.trim(),
        star_evidence_text: document.getElementById('star_evidence_text').value.trim(),
        capability_profile_rules: textToCapabilityRules(document.getElementById('capability_profile_rules').value),
        target_title_patterns: toLines(document.getElementById('target_title_patterns').value),
        adjacent_title_patterns: toLines(document.getElementById('adjacent_title_patterns').value),
        must_not_require_skills: toLines(document.getElementById('must_not_require_skills').value),
        reject_title_rules: textToRules(document.getElementById('reject_title_rules').value, 'pattern'),
        reject_description_phrase_rules: textToRules(document.getElementById('reject_description_phrase_rules').value, 'phrase'),
        reject_description_regex_rules: textToRules(document.getElementById('reject_description_regex_rules').value, 'pattern'),
        onboarding_settings: {
          title_extraction_lookback_years: Number(document.getElementById('os_lookback_years').value || 8),
          title_extraction_min_months: Number(document.getElementById('os_min_months').value || 6),
          max_target_patterns: Number(document.getElementById('os_max_target').value || 8),
          max_adjacent_patterns: Number(document.getElementById('os_max_adjacent').value || 6),
        },
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
        {
          search_settings: profile.search_settings,
          salary_preferences: profile.salary_preferences,
        },
        'Search settings saved to profile.json.'
      );
    }

    async function saveProfileSection() {
      const profile = collectProfile();
      await patchProfile(
        {
          llm_profile_brief_mode: profile.llm_profile_brief_mode,
          llm_profile_brief: profile.llm_profile_brief,
          preference_weights: profile.preference_weights,
          strengths: profile.strengths,
          cv_text: profile.cv_text,
          star_evidence_text: profile.star_evidence_text,
          capability_profile_rules: profile.capability_profile_rules,
          target_title_patterns: profile.target_title_patterns,
          adjacent_title_patterns: profile.adjacent_title_patterns,
          must_not_require_skills: profile.must_not_require_skills,
          reject_title_rules: profile.reject_title_rules,
          reject_description_phrase_rules: profile.reject_description_phrase_rules,
          reject_description_regex_rules: profile.reject_description_regex_rules,
          onboarding_settings: profile.onboarding_settings,
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

    async function applyOneSkipDecision(skill, choice) {
      const response = await fetch('/api/tuning-decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions: [{ skill, choice }] }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not apply');
      return payload;
    }

    document.getElementById('save_search').addEventListener('click', async () => {
      try {
        await saveSearchSettings();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    saveProfileButton.addEventListener('click', async () => {
      const originalLabel = saveProfileButton.textContent;
      saveProfileButton.disabled = true;
      saveProfileButton.textContent = 'Saving...';
      showInlineStatus(saveProfileStatusEl, 'Saving profile...', 'loading');
      try {
        await saveProfileSection();
        await loadReviewData();
        showInlineStatus(saveProfileStatusEl, 'Profile saved to profile.json.', 'ok');
      } catch (error) {
        showStatus(error.message, 'error');
        showInlineStatus(saveProfileStatusEl, error.message, 'error');
      } finally {
        saveProfileButton.disabled = false;
        saveProfileButton.textContent = originalLabel;
      }
    });


    applyLearningButton.addEventListener('click', async () => {
      applyLearningButton.disabled = true;
      importKnowledgeFileButton.disabled = true;
      showInlineStatus(learningStatusEl, 'Applying learning update...', 'loading');
      try {
        await applyLearningUpdate();
        showInlineStatus(learningStatusEl, 'Learning update applied.', 'ok');
      } catch (error) {
        showStatus(error.message, 'error');
        showInlineStatus(learningStatusEl, error.message, 'error');
      } finally {
        applyLearningButton.disabled = false;
        importKnowledgeFileButton.disabled = false;
      }
    });

    importKnowledgeFileButton.addEventListener('click', async () => {
      applyLearningButton.disabled = true;
      importKnowledgeFileButton.disabled = true;
      showInlineStatus(learningStatusEl, 'Importing capability note...', 'loading');
      try {
        await importKnowledgeFile();
        showInlineStatus(learningStatusEl, 'Capability note imported.', 'ok');
      } catch (error) {
        showStatus(error.message, 'error');
        showInlineStatus(learningStatusEl, error.message, 'error');
      } finally {
        applyLearningButton.disabled = false;
        importKnowledgeFileButton.disabled = false;
      }
    });

    importSourceMaterialsButton.addEventListener('click', async () => {
      importSourceMaterialsButton.disabled = true;
      showInlineStatus(sourceMaterialsStatusEl, 'Refreshing profile from source documents...', 'loading');
      try {
        await importSourceMaterials();
        showInlineStatus(sourceMaterialsStatusEl, 'Profile refreshed from saved source documents.', 'ok');
      } catch (error) {
        showStatus(error.message, 'error');
        showInlineStatus(sourceMaterialsStatusEl, error.message, 'error');
      } finally {
        importSourceMaterialsButton.disabled = false;
      }
    });

    document.getElementById('open_onboarding').addEventListener('click', () => {
      window.location.href = '/start';
    });

    document.getElementById('refresh_review_data').addEventListener('click', async () => {
      try {
        await loadReviewData();
        showStatus('Suggested tuning refreshed.', 'ok');
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

    document.getElementById('save_alerts').addEventListener('click', async () => {
      try {
        await saveAgentSettings();
        await loadTelegramConnectLink().catch(() => ({}));
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('open_telegram_connect').addEventListener('click', async () => {
      try {
        if (!telegramConnectLink) {
          await loadTelegramConnectLink();
        }
        if (!telegramConnectLink) {
          throw new Error('No Telegram connect link available yet.');
        }
        window.open(telegramConnectLink, '_blank', 'noopener');
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('sync_telegram_subscribers').addEventListener('click', async () => {
      try {
        await syncTelegramSubscribers();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('send_telegram_test').addEventListener('click', async () => {
      try {
        await sendTelegramTestMessage();
      } catch (error) {
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('tuning_suggestions_panel').addEventListener('click', async (e) => {
      const btn = e.target.closest('.confirm-skill-btn');
      if (!btn) return;
      const card = btn.closest('.review-card');
      const select = card?.querySelector('.skill-choice');
      const skill = btn.dataset.skill;
      const choice = select?.value;
      if (!skill || !choice) return;
      btn.disabled = true;
      btn.textContent = 'Saving…';
      try {
        await applyOneSkipDecision(skill, choice);
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
        btn.textContent = 'Applied';
      } catch (error) {
        btn.disabled = false;
        btn.textContent = 'Confirm';
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('tuning_suggestions_panel').addEventListener('click', async (e) => {
      const btn = e.target.closest('.add-phrase-exclusion-btn');
      if (!btn) return;
      const card = btn.closest('.review-card');
      const reason = btn.dataset.reason || '';
      const suffix = reason.split(':').slice(1).join(':').replace(/_/g, ' ').trim().toLowerCase();
      if (!suffix) return;
      btn.disabled = true;
      btn.textContent = 'Saving…';
      try {
        const response = await fetch('/api/rule/phrase', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phrase: suffix, reason: 'low-fit specialist area' }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || 'Could not add rule');
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
        btn.textContent = 'Added';
      } catch (error) {
        btn.disabled = false;
        btn.textContent = 'Add to exclusions';
        showStatus(error.message, 'error');
      }
    });

    document.getElementById('tuning_suggestions_panel').addEventListener('click', (e) => {
      const btn = e.target.closest('.dismiss-rule-card-btn');
      if (!btn) return;
      const card = btn.closest('.review-card');
      if (card) {
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
        btn.textContent = 'Dismissed';
      }
    });

    llmProfileBriefModeToggle?.addEventListener('change', () => {
      syncLlmProfileBriefMode();
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
      loadAgentSettings(),
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
      <p>Start with one strong detailed CV. We will turn it into a working profile the job engine can use, and you can refine it later in admin.</p>
    </section>

    <div class="grid">
      <section class="panel">
        <h2>Step 1. Primary CV</h2>
        <label for="primary_cv">Detailed CV</label>
        <input id="primary_cv" type="file" accept=".docx,.md,.txt">
        <div class="help">This is the only required file. Use the most detailed CV you have, not the prettiest final layout.</div>

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
      const extraNotes = document.getElementById('extra_notes').value.trim();

      if (!primary) {
        throw new Error('Choose your detailed CV first.');
      }

      const files = [await fileToPayload(primary, 'Primary CV')];

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


        merged_cv_text = AdminHandler._combine_text_sections(current.get("cv_text", ""), raw_text)
        if merged_cv_text:
            merged_patch["cv_text"] = merged_cv_text
            current_tiers = get_evidence_tiers(current)
            inferred_tiers = build_evidence_tiers_from_sections([{"label": "Admin Input", "text": raw_text}])
            merged_patch["evidence_tiers"] = {
                "primary_current_evidence": AdminHandler._combine_text_sections(
                    current_tiers.get("primary_current_evidence", ""),
                    inferred_tiers.get("primary_current_evidence", ""),
                ),
                "secondary_older_evidence": AdminHandler._combine_text_sections(
                    current_tiers.get("secondary_older_evidence", ""),
                    inferred_tiers.get("secondary_older_evidence", ""),
                ),
                "background_optional_evidence": AdminHandler._combine_text_sections(
                    current_tiers.get("background_optional_evidence", ""),
                    inferred_tiers.get("background_optional_evidence", ""),
                ),
            }

        final_strengths = merged_patch.get("strengths") or current.get("strengths", [])
        final_rules = merged_patch.get("capability_profile_rules") or current.get("capability_profile_rules", [])
        brief_mode = str(
            merged_patch.get("llm_profile_brief_mode", current.get("llm_profile_brief_mode", "auto")) or "auto"
        ).strip().lower()
        if brief_mode != "manual":
            llm_profile_brief = build_llm_profile_brief(
                strengths=final_strengths,
                capability_rules=final_rules,
            )
            if llm_profile_brief:
                merged_patch["llm_profile_brief"] = llm_profile_brief
            merged_patch["llm_profile_brief_mode"] = "auto"

        return merged_patch

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        current = current or load_profile()
        brief_mode = str(
            normalized.get("llm_profile_brief_mode", current.get("llm_profile_brief_mode", "auto")) or "auto"
        ).strip().lower()
        if brief_mode != "manual":
            brief_mode = "auto"
        normalized["llm_profile_brief_mode"] = brief_mode

        if brief_mode == "manual":
            normalized["llm_profile_brief"] = str(normalized.get("llm_profile_brief") or "").strip()
        else:
            auto_brief = build_llm_profile_brief(
                strengths=normalized.get("strengths", current.get("strengths", [])),
                capability_rules=normalized.get(
                    "capability_profile_rules",
                    current.get("capability_profile_rules", []),
                ),
            )
            normalized["llm_profile_brief"] = auto_brief

        if "star_evidence_text" in normalized:
            normalized["star_evidence_text"] = str(normalized.get("star_evidence_text") or "").strip()
        if "cv_text" in normalized:
            new_cv = str(normalized.get("cv_text") or "").strip()
            if new_cv:
                extracted = extract_strengths_from_cv(new_cv)
                if extracted:
                    existing = current.get("strengths") or []
                    merged = list(dict.fromkeys([*existing, *extracted]))[:20]
                    normalized.setdefault("strengths", merged)
        if "cv_text" in normalized and "evidence_tiers" not in normalized:
            inferred_tiers = build_evidence_tiers_from_sections([{
                "label": "Primary CV",
                "text": str(normalized.get("cv_text") or "").strip(),
            }])
            if any(inferred_tiers.values()):
                normalized["evidence_tiers"] = inferred_tiers
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
    def _sanitize_agent_settings_payload(payload: dict) -> dict:
        telegram = payload.get("telegram", {}) if isinstance(payload, dict) else {}
        return {
            "telegram": {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token": str(telegram.get("bot_token") or "").strip(),
                "bot_username": str(telegram.get("bot_username") or "").strip().lstrip("@"),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
            }
        }

    @staticmethod
    def _public_agent_settings_payload(settings: dict) -> dict:
        telegram = settings.get("telegram", {}) if isinstance(settings, dict) else {}
        subscribers = telegram.get("subscribers", []) if isinstance(telegram, dict) else []
        return {
            "telegram": {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token_present": bool(str(telegram.get("bot_token") or "").strip()),
                "bot_username": str(telegram.get("bot_username") or "").strip(),
                "chat_id_present": bool(str(telegram.get("chat_id") or "").strip()),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
                "subscriber_count": len(subscribers) if isinstance(subscribers, list) else 0,
                "subscribers": subscribers if isinstance(subscribers, list) else [],
            }
        }

    @staticmethod
    def _normalize_job_key(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        import re

        # Pass through pre-namespaced keys (e.g. 'linkedin:4056789012')
        if re.match(r"^(seek|linkedin|indeed|glassdoor):[^\s]+$", raw):
            return raw
        match = re.search(r"/job/(\d+)", raw)
        if match:
            return match.group(1)
        if re.fullmatch(r"\d+", raw):
            return raw
        return raw.split("#", 1)[0]

    @classmethod
    def _append_review_event(
        cls,
        entry: dict,
        action: str,
        job_key: str,
        occurred_at: str,
        title: str = "",
        company: str = "",
        url: str = "",
        teaser: str = "",
        extra: dict | None = None,
    ) -> None:
        snapshot = entry.get("last_kept_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}

        event = {
            "action": action,
            "job_key": job_key,
            "timestamp": occurred_at,
        }
        resolved_title = title or entry.get("title") or snapshot.get("title") or ""
        resolved_company = company or entry.get("company") or snapshot.get("company") or ""
        resolved_url = url or entry.get("url") or snapshot.get("url") or ""
        resolved_teaser = teaser or snapshot.get("teaser") or entry.get("teaser") or ""

        if resolved_title:
            event["title"] = resolved_title
        if resolved_company:
            event["company"] = resolved_company
        if resolved_url:
            event["url"] = resolved_url
        if resolved_teaser:
            event["teaser"] = resolved_teaser

        if isinstance(extra, dict):
            for key, value in extra.items():
                if value in (None, "", [], {}):
                    continue
                event[key] = value

        events = entry.get("review_events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        entry["review_events"] = events[-50:]

    @classmethod
    def _persist_review_event(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        extra: dict | None = None,
    ) -> None:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            return

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title:
            entry["title"] = title
        if company:
            entry["company"] = company
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
        elif action == "not_for_me":
            entry["last_not_for_me_at"] = now_iso
            entry["times_not_for_me"] = int(entry.get("times_not_for_me", 0) or 0) + 1
        elif action in ("block_similar", "block_title"):
            entry["last_block_title_at"] = now_iso
            entry["times_block_title"] = int(entry.get("times_block_title", 0) or 0) + 1

        cls._append_review_event(
            entry,
            action,
            normalized,
            now_iso,
            title=title,
            company=company,
            url=url,
            teaser=teaser,
            extra=extra,
        )

        history[normalized] = entry
        cls._save_job_history(history)

    @classmethod
    def _append_review_key(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
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
        cls._persist_review_event(
            action,
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(existing),
        }

    @classmethod
    def _remove_review_key(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
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
        cls._persist_review_event(
            action,
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(updated),
        }

    @classmethod
    def _save_not_for_me_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        cls._persist_review_event(
            "not_for_me",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": "not_for_me",
            "job_key": normalized,
            "message": "Saved as Not For Me. This is stored as learning feedback, not a permanent title block.",
        }

    @classmethod
    def _save_block_similar_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        block_phrase: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        phrase = normalize_title_block_phrase(block_phrase) or suggest_title_block_phrase(title)
        if not phrase:
            raise ValueError("Could not suggest a title keyword to block from this title yet")

        rule = build_title_block_rule(phrase)
        profile = load_profile()
        existing = list(profile.get("reject_title_rules", []))
        rule_exists = any(str(item.get("pattern") or "").strip() == rule["pattern"] for item in existing)
        if not rule_exists:
            existing.append(rule)
            profile["reject_title_rules"] = existing
            save_profile(profile)

        cls._persist_review_event(
            "block_title",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
            extra={
                "extracted_phrase": phrase,
                "reject_title_pattern": rule["pattern"],
                "reject_title_reason": rule["reason"],
                "rule_added": not rule_exists,
            },
        )
        return {
            "ok": True,
            "action": "block_similar",
            "job_key": normalized,
            "block_phrase": phrase,
            "rule": rule,
            "rule_added": not rule_exists,
            "message": (
                f"Added title block for '{phrase}'. Similar jobs will be filtered in future runs."
                if not rule_exists
                else f"Title block for '{phrase}' already existed."
            ),
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
                        payload["suggested_tuning"] = build_suggested_tuning_from_saved_review(
                            payload,
                            load_profile(),
                        )
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if self.path == "/api/job-history":
            history = self._load_job_history()
            slim_history: dict[str, dict] = {}
            for job_key, entry in history.items():
                if not isinstance(entry, dict):
                    continue
                slim_history[str(job_key)] = {
                    "times_viewed": int(entry.get("times_viewed", 0) or 0),
                    "first_viewed_at": entry.get("first_viewed_at"),
                    "last_viewed_at": entry.get("last_viewed_at"),
                }
            self._send_json(200, {"jobs": slim_history})
            return
        if self.path == "/api/profile":
            self._send_json(200, load_profile())
            return
        if self.path == "/api/agent-settings":
            self._send_json(200, self._public_agent_settings_payload(load_agent_settings(create_if_missing=True)))
            return
        if self.path == "/api/telegram/connect-link":
            try:
                settings = load_agent_settings(create_if_missing=True)
                link = build_telegram_connect_link(settings["telegram"])
                save_agent_settings(settings)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "connect_link": link,
                    "bot_username": str(settings["telegram"].get("bot_username") or "").strip(),
                },
            )
            return
        if self.path == "/api/source-materials":
            self._send_json(200, load_source_materials(create_if_missing=True))
            return
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
        if self.path == "/api/agent-settings":
            try:
                current = load_agent_settings(create_if_missing=True)
                patch = self._sanitize_agent_settings_payload(self._read_json_body())
                telegram_patch = patch.get("telegram", {})
                if not str(telegram_patch.get("bot_token") or "").strip():
                    telegram_patch.pop("bot_token", None)
                current.setdefault("telegram", {}).update(telegram_patch)
                updated = save_agent_settings(current)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, self._public_agent_settings_payload(updated))
            return
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
        if self.path == "/api/detect-signals":
            try:
                payload = self._read_json_body()
                description = str(payload.get("description") or "").strip()
                if not description:
                    raise ValueError("description is required")
                signals = detect_rejection_signals(description)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, signals)
            return
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
                result = run_onboarding(materials)
                result["materials"] = materials
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
                result = run_onboarding(materials)
                result["materials"] = materials
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/onboarding/confirm-title-patterns":
            try:
                payload = self._read_json_body()
                target = [str(p).strip() for p in payload.get("target_title_patterns", []) if str(p).strip()]
                adjacent = [str(p).strip() for p in payload.get("adjacent_title_patterns", []) if str(p).strip()]
                keyword = str(payload.get("search_keyword") or "").strip()
                if not target:
                    raise ValueError("target_title_patterns must not be empty")
                profile_patch: dict = {"target_title_patterns": target}
                if adjacent:
                    profile_patch["adjacent_title_patterns"] = adjacent
                if keyword:
                    current = load_profile()
                    search_settings = dict(current.get("search_settings", {}))
                    search_settings["keywords"] = keyword
                    profile_patch["search_settings"] = search_settings
                updated = patch_profile(profile_patch)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "message": "Title patterns and search keyword saved.", "profile": updated})
            return
        if self.path in {"/api/tuning-decisions", "/api/skill-decisions"}:
            try:
                payload = self._read_json_body()
                decisions = payload.get("decisions", [])
                if not isinstance(decisions, list):
                    raise ValueError("decisions must be a list")
                profile = load_profile()
                updated = apply_capability_tuning_decisions(profile, decisions)
                save_profile(updated)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Capability tuning suggestions applied to profile.json.",
                    "profile": updated,
                },
            )
            return
        if self.path == "/api/rule/phrase":
            try:
                payload = self._read_json_body()
                phrase = str(payload.get("phrase") or "").strip().lower()
                reason = str(payload.get("reason") or "").strip()
                if not phrase:
                    raise ValueError("phrase is required")
                profile = load_profile()
                existing = list(profile.get("reject_description_phrase_rules", []))
                if not any(str(r.get("phrase") or "").strip().lower() == phrase for r in existing):
                    existing.append({"phrase": phrase, "reason": reason or f"DESC_REJECT:{phrase}"})
                    profile["reject_description_phrase_rules"] = existing
                    updated = save_profile(profile)
                else:
                    updated = profile
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "message": f"Phrase rule added: {phrase}", "profile": updated})
            return
        if self.path == "/api/telegram/sync":
            try:
                settings = load_agent_settings(create_if_missing=True)
                result = sync_telegram_subscribers(settings["telegram"])
                updated = save_agent_settings(settings)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": f"Telegram sync complete. {result['total_subscribers']} subscriber(s) available.",
                    "result": result,
                    "settings": self._public_agent_settings_payload(updated),
                },
            )
            return
        if self.path == "/api/telegram/test-message":
            try:
                payload = self._read_json_body()
                settings = load_agent_settings(create_if_missing=True)
                message_text = str(payload.get("message") or "").strip() or "Job Hunter test message."
                result = send_telegram_notification(message_text, "", settings["telegram"])
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Telegram test message sent.",
                    "result": result,
                },
            )
            return
        if self.path != "/api/review":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json_body()
            action = str(payload.get("action", "")).strip().lower()
            job_key = str(payload.get("job_key") or payload.get("url") or "").strip()
            url = str(payload.get("url") or "").strip()
            title = str(payload.get("title") or "").strip()
            company = str(payload.get("company") or "").strip()
            teaser = str(payload.get("teaser") or "").strip()
            if action == "viewed":
                result = self._record_job_view(
                    job_key,
                    url,
                    title,
                )
            elif action == "not_for_me":
                result = self._save_not_for_me_feedback(
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
            elif action == "block_similar":
                result = self._save_block_similar_feedback(
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                    str(payload.get("block_phrase") or "").strip(),
                )
            elif action == "unhide":
                result = self._remove_review_key(
                    action,
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
            else:
                result = self._append_review_key(
                    action,
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, result)

    def do_DELETE(self) -> None:
        if self.path == "/api/rule/title-block":
            try:
                payload = self._read_json_body()
                pattern = str(payload.get("pattern") or "").strip()
                if not pattern:
                    raise ValueError("pattern is required")
                profile = load_profile()
                existing = list(profile.get("reject_title_rules", []))
                updated_rules = [r for r in existing if str(r.get("pattern") or "").strip() != pattern]
                if len(updated_rules) == len(existing):
                    self._send_json(404, {"error": "Rule not found"})
                    return
                profile["reject_title_rules"] = updated_rules
                saved = save_profile(profile)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "reject_title_rules": saved.get("reject_title_rules", [])})
            return
        self._send_json(404, {"error": "Not found"})

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), AdminHandler)
    print(f"Local server running at http://{HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"Admin: http://{HOST}:{PORT}/admin")
    print(f"Onboarding: http://{HOST}:{PORT}/start")
    server.serve_forever()
