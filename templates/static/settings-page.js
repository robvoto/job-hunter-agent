var LINKEDIN_EASY_APPLY_ONLY = window.LINKEDIN_EASY_APPLY_ONLY || 'linkedin_easy_apply_only';
window.LINKEDIN_EASY_APPLY_ONLY = LINKEDIN_EASY_APPLY_ONLY;

const statusEl = document.getElementById('status');
const isTestMode = document.body?.dataset.testMode === 'true';
const runNowButton = document.getElementById('run_now');
const rebuildProfileButton = document.getElementById('rebuild_profile');
const capabilityUi = window.JobHunterCapabilityUi || {};
const settingsCurrencyUi = window.JobHunterCurrencyUi || {};
const locationUi = window.JobHunterLocationUi || {};
const governmentPreferenceOptions = Array.isArray(window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__
  : [];
const governmentPreferenceDefault = String(
  window.__JOB_HUNTER_GOVERNMENT_PREFERENCE_DEFAULT__
  || governmentPreferenceOptions?.[0]?.value
  || 'any'
).trim().toLowerCase();
const workModePreferenceOptions = Array.isArray(window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__)
  ? window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__
  : [];

function normalizeWorkModePreferences(value) {
  const values = Array.isArray(value)
    ? value
    : String(value || '').split(/[,\n|/]+/);
  const selected = [];
  const seen = new Set();
  for (const option of workModePreferenceOptions) {
    const key = String(option.value || '').trim().toLowerCase();
    if (!key) continue;
    if (values.some((item) => String(item || '').trim().toLowerCase() === key) && !seen.has(key)) {
      seen.add(key);
      selected.push(key);
    }
  }
  return selected;
}

function getWorkModePreferenceValues() {
  return normalizeWorkModePreferences(
    Array.from(document.querySelectorAll('input[name="work_mode_preference"]:checked')).map((input) => input.value)
  );
}

function setWorkModePreferenceValues(values) {
  const selected = new Set(normalizeWorkModePreferences(values));
  document.querySelectorAll('input[name="work_mode_preference"]').forEach((input) => {
    input.checked = selected.size === 0 || selected.has(String(input.value || '').trim().toLowerCase());
  });
}

function readOnboardingWelcomeSearchKeywords() {
  try {
    const raw = window.sessionStorage.getItem('jobHunter.onboardingWelcome');
    if (!raw) return '';
    const parsed = JSON.parse(raw);
    return String(parsed?.search_keywords || '').trim();
  } catch {
    return '';
  }
}
    let telegramConnectLink = '';
    let loadedUserSettings = null;
    let loadedProfile = null;
    let loadedGlobalSettings = null;
    let capabilityRuleState = [];
    let expandedCapabilityRows = new Set();
    let suppressDirtyTracking = true;
    let statusHideTimer = null;
    const pageMode = document.body?.dataset.pageMode === 'admin' ? 'admin' : 'settings';
    const isAdminPage = pageMode === 'admin';
    const bootstrapGlobalSettings = window.__JOB_HUNTER_GLOBAL_SETTINGS__ || null;
    document.querySelectorAll('[data-test-only]').forEach((element) => {
      element.hidden = !isTestMode;
    });
    document.querySelectorAll('[data-debug-only]').forEach((element) => {
      element.hidden = !isTestMode;
    });
    document.querySelectorAll('[data-screen]').forEach((element) => {
      element.hidden = element.dataset.screen !== pageMode;
    });
    if (isAdminPage && bootstrapGlobalSettings) {
      fillGlobalForm(bootstrapGlobalSettings);
    }
    const listTextAreas = [
      'primary_job_title_pattern',
      'secondary_title_patterns',
      'classification_ids',
      'must_not_require_skills',
    ];

    const ruleTextAreas = [
      ['reject_title_rules', 'pattern'],
      ['reject_description_phrase_rules', 'phrase'],
    ];

    function settingsField(id) {
      const aliases = {
        secondary_title_patterns: 'adjacent_title_patterns',
        secondary_title_patterns_add: 'adjacent_title_patterns_add',
        secondary_title_patterns_chips: 'adjacent_title_patterns_chips',
      };
      return document.getElementById(id) || document.getElementById(aliases[id] || '');
    }

    function bindCurrencyFields() {
      ['minimum_salary_yearly', 'minimum_daily_rate', 'salary_limit_minimum_salary_yearly_max', 'salary_limit_minimum_daily_rate_max'].forEach((id) => {
        settingsCurrencyUi.bindCurrencyInput?.(document.getElementById(id));
      });
    }

    function setCurrencyFieldValue(id, value) {
      const input = document.getElementById(id);
      if (!input) return;
      if (settingsCurrencyUi.setCurrencyInputValue) {
        settingsCurrencyUi.setCurrencyInputValue(input, value);
      } else {
        input.value = String(value ?? '');
      }
    }

    function readCurrencyFieldValue(id, fallback = 0) {
      const input = document.getElementById(id);
      if (!input) return fallback;
      const parsed = settingsCurrencyUi.parseCurrencyValue ? settingsCurrencyUi.parseCurrencyValue(input.value) : Number(String(input.value || '').replace(/,/g, ''));
      return Number.isFinite(parsed) && parsed !== '' ? parsed : fallback;
    }

    function renderLocationOptions() {
      const select = document.getElementById('locations');
      if (!select || !locationUi.renderLocationOptions) return;
      locationUi.renderLocationOptions(select);
      const preferred = String(loadedProfile?.search_settings?.locations?.[0] || locationUi.defaultLocation || select.value || '').trim();
      if (preferred) {
        select.value = preferred;
      }
    }

    function hideStatus() {
      if (!statusEl) return;
      statusEl.className = 'status';
      statusEl.textContent = '';
    }

    function showStatus(message, kind, options = {}) {
      if (!statusEl) return;
      window.clearTimeout(statusHideTimer);
      statusEl.textContent = message;
      statusEl.className = `status is-visible ${kind}`;
      const autoHideMs = Number(options.autoHideMs || 0);
      if (autoHideMs > 0) {
        statusHideTimer = window.setTimeout(hideStatus, autoHideMs);
      }
    }

    function showInlineStatus(element, message, kind) {
      if (!element) return;
      element.textContent = message;
      element.className = `inline-status ${kind}`;
    }

    function toLines(value) {
      return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    }

    function rulesToText(rules, key) {
      return (rules || []).map(rule => `${rule[key] || ''} || ${rule.reason || ''}`).join('\n');
    }

    function capabilityRulesToText(rules) {
      return (rules || []).filter(rule => (rule.name || '').trim() && (rule.level || '').trim()).map(rule => {
        const aliases = (rule.aliases || []).join(', ');
        return `${rule.name || ''} || ${rule.level || ''} || ${rule.fit || 'supporting'} || ${aliases}`;
      }).join('\n');
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
        const hasFit = parts.length >= 4;
        return {
          name: (parts[0] || '').trim(),
          level: (parts[1] || '').trim().toLowerCase(),
          fit: hasFit ? (parts[2] || 'supporting').trim().toLowerCase() : 'supporting',
          aliases: (hasFit ? (parts[3] || '') : (parts[2] || '')).split(',').map(item => item.trim()).filter(Boolean),
        };
      }).filter(rule => rule.name && rule.level);
    }

    const capabilityLevelMeta = capabilityUi.capabilityLevelMeta || {};

    function normalizeCapabilityAliasValue(value) {
      return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function normalizeCapabilityRule(rule) {
      const name = String(rule?.name || '').replace(/\s+/g, ' ').trim();
      const rawLevel = String(rule?.level || 'historical').trim().toLowerCase();
      const validLevels = new Set(['strong', 'intermediate', 'historical']);
      const level = validLevels.has(rawLevel) ? rawLevel : 'historical';

      const rawFit = String(rule?.fit || 'supporting').trim().toLowerCase();
      const validFits = new Set(['core', 'supporting']);
      const fit = validFits.has(rawFit) ? rawFit : 'supporting';

      const aliases = [];
      const seen = new Set();
      for (const value of Array.isArray(rule?.aliases) ? rule.aliases : []) {
        const cleaned = normalizeCapabilityAliasValue(value);
        if (!cleaned || cleaned === name.toLowerCase() || seen.has(cleaned)) continue;
        seen.add(cleaned);
        aliases.push(cleaned);
      }
      return {
        name,
        level,
        fit,
        aliases,
        aliases_open: Boolean(rule?.aliases_open),
        needs_review: Boolean(rule?.needs_review) || aliases.length > 0,
      };
    }

    function capabilityStrengthMeta(level) {
      const key = String(level || '').trim().toLowerCase();
      if (!key) return null;
      return capabilityLevelMeta[key] || capabilityLevelMeta.historical || { label: 'Historical' };
    }

    function setCapabilityRuleState(rules) {
      capabilityRuleState = (rules || [])
        .map(normalizeCapabilityRule)
        .filter(rule => rule.name);
      expandedCapabilityRows = new Set(
        [...expandedCapabilityRows].filter(index => index >= 0 && index < capabilityRuleState.length)
      );
      settingsField('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
      renderCapabilityRuleEditor();
    }

    function collectCapabilityRuleState() {
      const cleaned = capabilityRuleState
        .map(normalizeCapabilityRule)
        .filter(rule => rule.name);
      capabilityRuleState = cleaned;
      settingsField('capability_profile_rules').value = capabilityRulesToText(cleaned);
      return cleaned;
    }

    function collectProfile() {
      flushChipEditorInputs();
      const locationSelect = document.getElementById('locations');
      const searchDateWindow = Number(document.getElementById('search_date_window')?.value || '3');
      const hoursMap = { 0: 720, 1: 24, 3: 72, 7: 168, 15: 360, 30: 720 };
      const linkedinEasyApplyRaw = document.getElementById(LINKEDIN_EASY_APPLY_ONLY)?.value;
      return {
        search_settings: {
          keywords: toLines(settingsField('keywords').value).join(', '),
          locations: locationSelect && locationSelect.value.trim() ? [locationSelect.value.trim()] : [],
          classification_ids: toLines(document.getElementById('classification_ids').value),
          date_range_days: searchDateWindow === 0 ? 30 : searchDateWindow,
          linkedin_hours_old: hoursMap[searchDateWindow] ?? 72,
          seek_max_pages: Number(document.getElementById('seek_max_pages').value),
          enforce_posted_age_limit: document.getElementById('enforce_posted_age_limit').value === 'true',
          sort_newest_first: document.getElementById('sort_newest_first').value === 'true',
          linkedin_results_per_search: Number(document.getElementById('linkedin_results_per_search').value) || 25,
          [LINKEDIN_EASY_APPLY_ONLY]: linkedinEasyApplyRaw === '' ? null : linkedinEasyApplyRaw === 'true',
        },
        salary_preferences: {
          minimum_salary_yearly: settingsCurrencyUi.parseCurrencyValue
            ? settingsCurrencyUi.parseCurrencyValue(document.getElementById('minimum_salary_yearly')?.value)
            : Number(String(document.getElementById('minimum_salary_yearly')?.value || '').replace(/,/g, '')) || 0,
          minimum_daily_rate: settingsCurrencyUi.parseCurrencyValue
            ? settingsCurrencyUi.parseCurrencyValue(document.getElementById('minimum_daily_rate')?.value)
            : Number(String(document.getElementById('minimum_daily_rate')?.value || '').replace(/,/g, '')) || 0,
        },
        match_preferences: {
          engagement_type: document.getElementById('engagement_type').value,
          work_mode_preference: getWorkModePreferenceValues(),
          prefer_government: String(document.getElementById('prefer_government').value || governmentPreferenceDefault).trim().toLowerCase(),
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
        llm_profile_brief_mode: 'auto',
        llm_profile_brief: '',
        capability_profile_rules: collectCapabilityRuleState(),
        primary_job_title_pattern: toLines(settingsField('primary_job_title_pattern').value),
        secondary_title_patterns: toLines(settingsField('secondary_title_patterns').value),
        must_not_require_skills: toLines(settingsField('must_not_require_skills').value),
        reject_title_rules: textToRules(settingsField('reject_title_rules').value, 'pattern'),
        reject_description_phrase_rules: textToRules(settingsField('reject_description_phrase_rules').value, 'phrase'),
      };
    }
 
    function renderCapabilityRuleEditor() {
      const container = document.getElementById('capability_matrix_editor');
      if (!container) return;
      if (!capabilityRuleState.length) {
        container.innerHTML = '<div class="capability-editor-empty">No capability rules yet. Run onboarding or add a capability row here.</div>';
        return;
      }
      const filterTerm = String(document.getElementById('capability_matrix_filter')?.value || '').trim().toLowerCase();
      const rows = capabilityRuleState
        .map((rule, index) => ({ rule, index }))
        .filter(item => {
          if (!filterTerm) return true;
          return item.rule.name.toLowerCase().includes(filterTerm)
            || item.rule.aliases.some(alias => alias.includes(filterTerm));
        });
      const cardsHtml = rows.length
        ? rows.map(({ rule, index }) => {
            const titleCaseName = rule.name.toLowerCase().split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
            const aliases = Array.isArray(rule.aliases) ? rule.aliases : [];
            const aliasCount = aliases.length;
            const aliasChips = aliases.map(alias => `
              <span class="cap-alias-chip" title="${escapeHtml(alias)}">${escapeHtml(alias)}</span>
            `).join('');
            return `
              <article class="capability-card" data-capability-index="${index}">
                <div class="capability-card-head">
                  <input class="cap-name-input capability-card-name" type="text" data-capability-field="name" aria-label="Capability name"
                         value="${escapeHtml(titleCaseName)}"
                         placeholder="e.g. Agile Delivery">
                  <button class="cap-remove-btn capability-remove-btn" type="button" data-remove-capability="${index}"
                          aria-label="Remove ${escapeHtml(rule.name || 'capability')}"
                          title="Remove capability">
                    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" class="cap-remove-icon">
                      <path d="M9 3.5h6l1 1.5H19v2H5v-2h3l1-1.5Zm-1 5h8l-.6 9.3A2 2 0 0 1 13.4 20H10.6a2 2 0 0 1-1.99-1.7L8 8.5Zm2 2v6m4-6v6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path>
                    </svg>
                  </button>
                </div>
                <div class="capability-card-meta">
                  <span class="cap-alias-summary">${escapeHtml(aliasCount ? `${aliasCount} alias${aliasCount === 1 ? '' : 'es'}` : 'No aliases')}</span>
                  ${aliasCount ? `
                    <details class="capability-alias-drawer"${expandedCapabilityRows.has(index) ? ' open' : ''}>
                      <summary>View aliases</summary>
                      <div class="cap-alias-chips">${aliasChips}</div>
                    </details>
                  ` : ''}
                </div>
                <label class="cap-strength-label">
                  <span>Strength</span>
                    <select class="cap-level-select capability-strength-select level-${escapeHtml(rule.level || 'historical')}"
                          data-capability-field="level" aria-label="Capability strength">
                    <option value="strong"${rule.level === 'strong' ? ' selected' : ''}>${escapeHtml(capabilityStrengthMeta('strong')?.label || 'Expert')}</option>
                      <option value="intermediate"${rule.level === 'intermediate' ? ' selected' : ''}>${escapeHtml(capabilityStrengthMeta('intermediate')?.label || 'Intermediate')}</option>
                      <option value="historical"${rule.level === 'historical' ? ' selected' : ''}>${escapeHtml(capabilityStrengthMeta('historical')?.label || 'Historical')}</option>
                  </select>
                </label>
              </article>
            `;
          }).join('')
        : '<div class="capability-editor-empty-group">No matching capabilities.</div>';

      container.innerHTML = `
        <section class="capability-group">
          <div class="capability-group-head">
            <div>
              <h4 style="color: var(--accent);">Capabilities</h4>
              <p class="capability-group-copy">Keep the set tight. These rows feed fit scoring, CV learning, and review.</p>
            </div>
            <span class="cap-count">${escapeHtml(String(rows.length))} shown</span>
          </div>
          <div class="capability-grid">
            ${cardsHtml}
          </div>
        </section>
      `;
    }

    // Attach listener globally to document so that it actually catches the non-bubbling 'toggle' event [3]
    document.addEventListener('toggle', function(e) {
      if (e.target.classList?.contains('capability-alias-drawer')) {
        const card = e.target.closest('[data-capability-index]');
        if (card) {
          const index = Number(card.dataset.capabilityIndex);
          if (e.target.open) {
            expandedCapabilityRows.add(index);
          } else {
            expandedCapabilityRows.delete(index);
          }
        }
      }
      if (e.target.classList?.contains('capability-alias-drawer') && e.target.open) {
        // Find all details elements strictly inside your matrix container
        const allDetails = document.querySelectorAll('#capability_matrix_editor details.capability-alias-drawer');
        allDetails.forEach(details => {
          if (details !== e.target && details.open) {
            details.open = false;
          }
        });
      }
    }, true); // The 'true' activates event capturing which safely bypasses the bubbling restriction [3]


    const chipEditors = {
      keywords: { kind: 'list', listId: 'keywords_chips', inputId: 'keywords_add', emptyText: 'No search keywords yet.', minItems: 1 },
      primary_job_title_pattern: { kind: 'list', listId: 'primary_job_title_pattern_chips', inputId: 'primary_job_title_pattern_add', emptyText: 'No primary job titles yet.' },
      secondary_title_patterns: { kind: 'list', listId: 'secondary_title_patterns_chips', inputId: 'secondary_title_patterns_add', emptyText: 'No secondary job titles yet.' },
      must_not_require_skills: { kind: 'list', listId: 'must_not_require_skills_chips', inputId: 'must_not_require_skills_add', emptyText: 'No mandatory skills to reject yet.' },
      reject_title_rules: { kind: 'rule', key: 'pattern', listId: 'reject_title_rules_chips', inputId: 'reject_title_rules_add', emptyText: 'No blocked job titles yet.' },
      reject_description_phrase_rules: { kind: 'rule', key: 'phrase', listId: 'reject_description_phrase_rules_chips', inputId: 'reject_description_phrase_rules_add', emptyText: 'No excluded keywords or phrases yet.' },
    };

    function escapeRegExp(value) {
      return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function normalizePlainPhrase(value) {
      return String(value || '').replace(/\s+/g, ' ').trim();
    }

    function normalizeReasonToken(value) {
      return normalizePlainPhrase(value).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'custom';
    }

    function titlePhraseToPattern(value) {
      const tokens = normalizePlainPhrase(value).toLowerCase().match(/[a-z0-9]+/g) || [];
      if (!tokens.length) return '';
      return `\\b${tokens.map(escapeRegExp).join('\\s+')}\\b`;
    }

    function normalizeTitleBlockPhrase(value) {
      const tokens = String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);
      return tokens.slice(0, 3).join(' ');
    }

    function patternToLabel(pattern) {
      return normalizePlainPhrase(
        String(pattern || '')
          .replace(/\\b/g, '')
          .replace(/\\s\+/g, ' ')
          .replace(/\\ /g, ' ')
          .replace(/\\/g, '')
      );
    }

    function friendlyListLabel(id, value) {
      if (id === 'primary_job_title_pattern' || id === 'secondary_title_patterns') {
        return patternToLabel(value) || value;
      }
      return normalizePlainPhrase(value);
    }

    function friendlyRuleLabel(id, rule) {
      if (id === 'reject_title_rules') {
        const reason = String(rule.reason || '');
        const label = reason.startsWith('TITLE_BAD_KEYWORD:') ? reason.replace('TITLE_BAD_KEYWORD:', '') : '';
        return normalizePlainPhrase(label || patternToLabel(rule.pattern) || rule.pattern);
      }
      return normalizePlainPhrase(rule.phrase || rule.pattern || '');
    }

    function listIdentity(id, value) {
      return friendlyListLabel(id, value).toLowerCase();
    }

    function ruleIdentity(id, rule) {
      return friendlyRuleLabel(id, rule).toLowerCase();
    }

    function getListItems(id) {
      const field = settingsField(id);
      return field ? toLines(field.value) : [];
    }

    function setListItems(id, items) {
      const field = settingsField(id);
      if (field) field.value = (items || []).join('\n');
    }

    function getRuleItems(id) {
      const editor = chipEditors[id];
      const field = settingsField(id);
      return field && editor ? textToRules(field.value, editor.key) : [];
    }

    function setRuleItems(id, items) {
      const editor = chipEditors[id];
      const field = settingsField(id);
      if (field && editor) field.value = rulesToText(items || [], editor.key);
    }

    function markDirty() {
      if (suppressDirtyTracking) return;
      if (activeSaveButton) activeSaveButton.disabled = false;
      if (stickySaveBar) {
        stickySaveBar.hidden = false;
        stickySaveBar.dataset.dirty = 'true';
      }
    }

    function clearDirty() {
      if (activeSaveButton) activeSaveButton.disabled = true;
      if (stickySaveBar) {
        stickySaveBar.hidden = true;
        delete stickySaveBar.dataset.dirty;
      }
      showInlineStatus(globalStatus, '', '');
    }

    function buildChipValue(id, rawValue) {
      const raw = normalizePlainPhrase(rawValue);
      if (!raw) return null;
      if (id === 'primary_job_title_pattern' || id === 'secondary_title_patterns') return titlePhraseToPattern(raw);
      if (id === 'must_not_require_skills') return raw;
      if (id === 'reject_title_rules') {
        const phrase = normalizeTitleBlockPhrase(raw);
        if (!phrase) return null;
        return { pattern: titlePhraseToPattern(phrase), reason: `TITLE_BAD_KEYWORD:${phrase}` };
      }
      if (id === 'reject_description_phrase_rules') {
        const phrase = raw.toLowerCase();
        return { phrase, reason: `DESC_REJECT:${normalizeReasonToken(phrase)}` };
      }
      return raw;
    }

    function renderChipEditor(id) {
      const editor = chipEditors[id];
      const list = editor ? settingsField(editor.listId) : null;
      if (!editor || !list) return;

      const isRule = editor.kind === 'rule';
      const items = isRule ? getRuleItems(id) : getListItems(id);
      if (!items.length) {
        list.innerHTML = `<span class="badge-editor-empty">${escapeHtml(editor.emptyText)}</span>`;
        return;
      }
      list.innerHTML = items.map((item, index) => {
        const label = isRule ? friendlyRuleLabel(id, item) : friendlyListLabel(id, item);
        const title = isRule ? (item[editor.key] || label) : item;
        return `<span class="rule-chip">
          <span title="${escapeHtml(title)}">${escapeHtml(label || title)}</span>
          <button type="button" data-remove-chip="${escapeHtml(id)}" data-chip-index="${index}" title="Remove ${escapeHtml(label || title)}">&#215;</button>
        </span>`;
      }).join('');
    }

    function renderGlobaldChipEditors() {
      Object.keys(chipEditors).forEach(renderChipEditor);
    }

    function addChipValue(id) {
      const editor = chipEditors[id];
      const input = editor ? settingsField(editor.inputId) : null;
      if (!editor || !input) return false;
      const value = buildChipValue(id, input.value);
      if (!value) return false;
      if (editor.kind === 'rule') {
        const items = getRuleItems(id);
        const identity = ruleIdentity(id, value);
        if (identity && !items.some(item => ruleIdentity(id, item) === identity)) {
          items.push(value);
          setRuleItems(id, items);
        }
      } else {
        const items = getListItems(id);
        const identity = listIdentity(id, value);
        if (identity && !items.some(item => listIdentity(id, item) === identity)) {
          items.push(value);
          setListItems(id, items);
        }
      }
      input.value = '';
      renderChipEditor(id);
      markDirty();
      return true;
    }

    function removeChipValue(id, index) {
      const editor = chipEditors[id];
      if (!editor) return;
      if (editor.kind === 'rule') {
        const items = getRuleItems(id);
        if (editor.minItems && items.length <= editor.minItems) return;
        items.splice(index, 1);
        setRuleItems(id, items);
      } else {
        const items = getListItems(id);
        if (editor.minItems && items.length <= editor.minItems) return;
        items.splice(index, 1);
        setListItems(id, items);
      }
      renderChipEditor(id);
      markDirty();
    }

    function flushChipEditorInputs() {
      Object.keys(chipEditors).forEach(id => {
        const input = settingsField(chipEditors[id].inputId);
        if (input && input.value.trim()) addChipValue(id);
      });
    }

    function fillForm(profile) {
      const savedKeywords = String(profile.search_settings?.keywords || '').trim();
      const onboardingKeywords = savedKeywords ? '' : readOnboardingWelcomeSearchKeywords();
      const keywordList = (savedKeywords || onboardingKeywords || '')
        .split(',')
        .map(k => k.trim())
        .filter(Boolean);
      settingsField('keywords').value = keywordList.join('\n');
      renderChipEditor('keywords');
      renderLocationOptions();
      const locationSelect = document.getElementById('locations');
      if (locationSelect) {
        locationSelect.value = String(profile.search_settings?.locations?.[0] || locationUi.defaultLocation || locationSelect.value || '').trim();
      }
      document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\n');
      document.getElementById('seek_max_pages').value = String(profile.search_settings?.seek_max_pages);
      document.getElementById('enforce_posted_age_limit').value = String(Boolean(profile.search_settings?.enforce_posted_age_limit));
      document.getElementById('sort_newest_first').value = String(Boolean(profile.search_settings?.sort_newest_first));
      document.getElementById('linkedin_results_per_search').value = String(profile.search_settings?.linkedin_results_per_search );
      const _dateWindowEl = document.getElementById('search_date_window');
      if (_dateWindowEl) {
        const _savedDays = profile.search_settings?.date_range_days;
        const _windowValues = [1, 3, 7, 15, 30];
        const _closest = _windowValues.includes(_savedDays) ? _savedDays
          : _windowValues.reduce((p, c) => Math.abs(c - _savedDays) < Math.abs(p - _savedDays) ? c : p);
        _dateWindowEl.value = String(_closest);
      }
      const _minScoreSelect = document.getElementById('workspace_minimum_score');
      if (_minScoreSelect) {
        const _levels = (profile.match_levels || []).slice().sort((a, b) => (a.minimum_score || 0) - (b.minimum_score || 0));
        _minScoreSelect.innerHTML = '<option value="0">All roles</option>' +
          _levels.map(l => `<option value="${l.minimum_score}">${escapeHtml(l.label)} &amp; above</option>`).join('');
        const _savedScore = loadedUserSettings?.workspace?.minimum_score;
        if (_savedScore !== undefined) _minScoreSelect.value = String(_savedScore);
      }
      const _liEasyApply = profile.search_settings?.[LINKEDIN_EASY_APPLY_ONLY];
      document.getElementById(LINKEDIN_EASY_APPLY_ONLY).value = (_liEasyApply === null || _liEasyApply === undefined) ? '' : String(_liEasyApply);
      document.getElementById('engagement_type').value = profile.match_preferences?.engagement_type || 'both';
      setWorkModePreferenceValues(profile.match_preferences?.work_mode_preference || []);
      const governmentPreference = document.getElementById('prefer_government');
      if (governmentPreference) {
        governmentPreference.value = String(profile.match_preferences?.prefer_government || governmentPreferenceDefault).trim().toLowerCase();
      }
      document.getElementById('llm_profile_brief').value = profile.llm_profile_brief || '';
      setCurrencyFieldValue('minimum_salary_yearly', profile.salary_preferences?.minimum_salary_yearly ?? 0);
      setCurrencyFieldValue('minimum_daily_rate', profile.salary_preferences?.minimum_daily_rate ?? 0);
      document.getElementById('fit_weight').value = String(profile.preference_weights?.fit);
      document.getElementById('salary_weight').value = String(profile.preference_weights?.salary);
      document.getElementById('location_weight').value = String(profile.preference_weights?.location);
      document.getElementById('work_mode_weight').value = String(profile.preference_weights?.work_mode);
      document.getElementById('contract_weight').value = String(profile.preference_weights?.contract);
      document.getElementById('government_weight').value = String(profile.preference_weights?.government);
      document.getElementById('freshness_weight').value = String(profile.preference_weights?.freshness);
      setCapabilityRuleState(profile.capability_profile_rules || []);
      document.getElementById('cv_text_debug').value = (profile.cv_text || '').trim();
      for (const id of ['primary_job_title_pattern', 'secondary_title_patterns', 'must_not_require_skills']) {
        settingsField(id).value = (profile[id] || []).join('\n');
      }
      for (const [id, key] of ruleTextAreas) {
        settingsField(id).value = rulesToText(profile[id], key);
      }
      renderGlobaldChipEditors();
    }

    // Populate the global settings form from the server payload.
    function fillGlobalForm(settings) {
      loadedGlobalSettings = settings || {};
      const fitHl = loadedGlobalSettings.fit_highlights || {};
      const searchDefaults = loadedGlobalSettings.search_settings || {};
      const limits = loadedGlobalSettings.limits || {};
      const searchLimits = limits.search || {};
      const evidenceWeights = loadedGlobalSettings.candidate_profile_tier_weights || {};
      const preferenceWeights = loadedGlobalSettings.preference_weights || {};
      const historySettings = loadedGlobalSettings.history_settings || {};
      const descriptionTrustSettings = loadedGlobalSettings.description_trust_settings || {};
      const sourceDocumentSettings = loadedGlobalSettings.source_document_settings || {};
      const defaultCountrySuffix = loadedGlobalSettings.default_country_suffix || '';
      const salaryLimits = limits.salary || {};
      const onboarding = loadedGlobalSettings.onboarding_settings || {};
      const llmSettings = loadedGlobalSettings.llm_settings || {};
      const playwrightSettings = loadedGlobalSettings.playwright_settings || {};
      const setBounds = (id, bounds) => {
        const input = document.getElementById(id);
        if (!input || !bounds) return;
        if (bounds.min !== undefined) input.min = String(bounds.min);
        if (bounds.max !== undefined) input.max = String(bounds.max);
      };

      document.getElementById('highlight_strong_capability_count').value = String(fitHl.strong_capability_count ?? '');
      document.getElementById('highlight_working_capability_count').value = String(fitHl.working_capability_count ?? '');
      document.getElementById('highlight_basic_capability_count').value = String(fitHl.basic_capability_count ?? '');
      document.getElementById('highlight_reviewed_signal_count').value = String(fitHl.reviewed_signal_count ?? '');
      document.getElementById('highlight_max_highlights').value = String(fitHl.max_highlights ?? '');

      document.getElementById('search_default_date_range_days').value = String(searchDefaults.date_range_days ?? '');
      document.getElementById('search_default_seek_max_pages').value = String(searchDefaults.seek_max_pages ?? '');
      document.getElementById('search_default_linkedin_hours_old').value = String(searchDefaults.linkedin_hours_old ?? '');
      document.getElementById('search_default_linkedin_results_per_search').value = String(searchDefaults.linkedin_results_per_search ?? '');
      document.getElementById('search_default_enforce_posted_age_limit').value = searchDefaults.enforce_posted_age_limit === false ? 'false' : 'true';
      document.getElementById('search_default_sort_newest_first').value = searchDefaults.sort_newest_first === false ? 'false' : 'true';
      const liEasyApply = searchDefaults[LINKEDIN_EASY_APPLY_ONLY];
      document.getElementById('search_default_' + LINKEDIN_EASY_APPLY_ONLY).value = (liEasyApply === null || liEasyApply === undefined) ? '' : String(liEasyApply);
      setBounds('search_default_date_range_days', searchLimits.date_range_days);
      setBounds('search_default_seek_max_pages', searchLimits.seek_max_pages);
      setBounds('search_default_linkedin_hours_old', searchLimits.linkedin_hours_old);
      setBounds('search_default_linkedin_results_per_search', searchLimits.linkedin_results_per_search);
      document.getElementById('default_country_suffix').value = defaultCountrySuffix;
      document.getElementById('playwright_viewport_width').value = String(playwrightSettings.playwright_viewport_width ?? '');
      document.getElementById('playwright_viewport_height').value = String(playwrightSettings.playwright_viewport_height ?? '');
      document.getElementById('playwright_selector_timeout').value = String(playwrightSettings.playwright_selector_timeout ?? '');

      const rangeText = (value) => value?.min !== undefined && value?.max !== undefined ? `${value.min} to ${value.max}` : 'managed by the server';
      document.getElementById('search_default_date_range_days_bounds').textContent = rangeText(searchLimits.date_range_days);
      document.getElementById('search_default_seek_max_pages_bounds').textContent = rangeText(searchLimits.seek_max_pages);
      document.getElementById('search_default_linkedin_hours_old_bounds').textContent = rangeText(searchLimits.linkedin_hours_old);
      document.getElementById('search_default_linkedin_results_per_search_bounds').textContent = rangeText(searchLimits.linkedin_results_per_search);

      document.getElementById('evidence_primary_weight').value = String(evidenceWeights.primary_candidate_profile_context ?? '');
      document.getElementById('evidence_secondary_weight').value = String(evidenceWeights.secondary_candidate_profile_context ?? '');
      document.getElementById('evidence_supplementary_weight').value = String(evidenceWeights.supplementary_candidate_profile_context ?? '');

      document.getElementById('preference_fit_weight').value = String(preferenceWeights.fit ?? '');
      document.getElementById('preference_salary_weight').value = String(preferenceWeights.salary ?? '');
      document.getElementById('preference_location_weight').value = String(preferenceWeights.location ?? '');
      document.getElementById('preference_work_mode_weight').value = String(preferenceWeights.work_mode ?? '');
      document.getElementById('preference_contract_weight').value = String(preferenceWeights.contract ?? '');
      document.getElementById('preference_government_weight').value = String(preferenceWeights.government ?? '');
      document.getElementById('preference_freshness_weight').value = String(preferenceWeights.freshness ?? '');

      document.getElementById('history_max_history_sightings').value = String(historySettings.max_history_sightings ?? '');
      document.getElementById('history_repeated_listing_min_times_seen').value = String(historySettings.repeated_listing_min_times_seen ?? '');
      document.getElementById('history_repeated_listing_min_span_days').value = String(historySettings.repeated_listing_min_span_days ?? '');
      document.getElementById('history_multi_listing_red_flag_min_listings').value = String(historySettings.multi_listing_red_flag_min_listings ?? '');
      document.getElementById('history_multi_listing_red_flag_min_span_days').value = String(historySettings.multi_listing_red_flag_min_span_days ?? '');
      document.getElementById('onboarding_extraction_lookback_years').value = String(onboarding.extraction_lookback_years ?? '');
      document.getElementById('onboarding_title_extraction_min_months').value = String(onboarding.title_extraction_min_months ?? '');
      document.getElementById('onboarding_max_target_patterns').value = String(onboarding.max_target_patterns ?? '');
      document.getElementById('onboarding_max_secondary_patterns').value = String(onboarding.max_secondary_patterns ?? '');
      document.getElementById('onboarding_capability_alias_limit').value = String(onboarding.capability_alias_limit ?? '');
      document.getElementById('onboarding_signal_cluster_min_alias_hits').value = String(onboarding.signal_cluster_min_alias_hits ?? '');
      document.getElementById('onboarding_signal_cluster_min_snippet_hits').value = String(onboarding.signal_cluster_min_snippet_hits ?? '');
      document.getElementById('onboarding_signal_cluster_dense_snippet_alias_hits').value = String(onboarding.signal_cluster_dense_snippet_alias_hits ?? '');
      document.getElementById('onboarding_capability_strength_preset').value = onboarding.capability_strength_preset || '';
      document.getElementById('llm_model_options').value = (llmSettings.model_options || []).join('\n');
      setBounds('llm_max_llm_chars', llmSettings.max_llm_chars_limits);
      document.getElementById('llm_max_llm_chars').value = String(llmSettings.max_llm_chars ?? '');
      document.getElementById('llm_pricing_per_1m').value = JSON.stringify(llmSettings.pricing_per_1m || {}, null, 2);
      document.getElementById('llm_prompt_settings').value = JSON.stringify(llmSettings.llm_prompt_settings || {}, null, 2);

      document.getElementById('history_archive_stale_after_days').value = String(historySettings.archive_stale_after_days ?? '');
      document.getElementById('history_hidden_review_days').value = String(historySettings.hidden_review_days ?? '');
      document.getElementById('description_trust_min_trusted_description_length').value = String(descriptionTrustSettings.min_trusted_description_length ?? '');
      document.getElementById('source_document_allowed_suffixes').value = (sourceDocumentSettings.allowed_suffixes || []).join('\n');
      document.getElementById('source_document_allowed_suffixes').setAttribute('readonly', 'readonly');

      // Keep the shared search guardrails editable from the same global settings source.
      document.getElementById('search_limit_date_range_days_min').value = String(searchLimits.date_range_days?.min ?? '');
      document.getElementById('search_limit_date_range_days_max').value = String(searchLimits.date_range_days?.max ?? '');
      document.getElementById('search_limit_seek_max_pages_min').value = String(searchLimits.seek_max_pages?.min ?? '');
      document.getElementById('search_limit_seek_max_pages_max').value = String(searchLimits.seek_max_pages?.max ?? '');
      document.getElementById('search_limit_linkedin_hours_old_min').value = String(searchLimits.linkedin_hours_old?.min ?? '');
      document.getElementById('search_limit_linkedin_hours_old_max').value = String(searchLimits.linkedin_hours_old?.max ?? '');
      document.getElementById('search_limit_linkedin_results_per_search_min').value = String(searchLimits.linkedin_results_per_search?.min ?? '');
      document.getElementById('search_limit_linkedin_results_per_search_max').value = String(searchLimits.linkedin_results_per_search?.max ?? '');
      setCurrencyFieldValue('salary_limit_minimum_salary_yearly_max', salaryLimits.minimum_salary_yearly?.max ?? '');
      setCurrencyFieldValue('salary_limit_minimum_daily_rate_max', salaryLimits.minimum_daily_rate?.max ?? '');

      // Render the preset table read-only so the global tuning remains visible without duplicating edit logic.
      const presetPanel = document.getElementById('capability_strength_presets_panel');
      const presetTable = onboarding.capability_strength_presets || {};
      if (presetPanel) {
        const presetRows = Object.entries(presetTable).map(([presetName, presetValues]) => `
          <tr>
            <th scope="row">${escapeHtml(presetName)}</th>
            <td>${escapeHtml(Object.entries(presetValues || {}).map(([key, value]) => `${key}: ${value}`).join(' | ') || 'No values')}</td>
          </tr>
        `).join('');
        presetPanel.innerHTML = `
          <table class="settings-table">
            <thead>
              <tr>
                <th>Preset</th>
                <th>Values</th>
              </tr>
            </thead>
            <tbody>
              ${presetRows || '<tr><td colspan="2">No capability presets loaded.</td></tr>'}
            </tbody>
          </table>
        `;
      }
      renderLlmModelOptions();
    }

    // Build the payload that saves only the global settings.
    function collectGlobalSettings() {
      const current = loadedGlobalSettings || {};
      const currentSearch = current.search_settings || {};
      const currentLimitsGroup = current.limits || {};
      const currentSearchLimits = currentLimitsGroup.search || {};
      const currentSalaryLimits = currentLimitsGroup.salary || {};
      const currentHistory = current.history_settings || {};
      const currentDescriptionTrust = current.description_trust_settings || {};
      const currentSourceDocuments = current.source_document_settings || {};
      const currentEvidenceWeights = current.candidate_profile_tier_weights || {};
      const currentReviewSettings = current.review_settings || {};
      const currentPlaywright = current.playwright_settings || {};
      const currentOnboarding = current.onboarding_settings || {};
      const readNumber = (id, fallback) => {
        const raw = Number(document.getElementById(id).value);
        return Number.isNaN(raw) ? fallback : raw;
      };
      const readBoolean = (id, fallback) => {
        const raw = document.getElementById(id).value;
        if (raw === 'true') return true;
        if (raw === 'false') return false;
        return fallback;
      };
      return {
        fit_highlights: {
          strong_capability_count: readNumber('highlight_strong_capability_count', current.fit_highlights?.strong_capability_count),
          working_capability_count: readNumber('highlight_working_capability_count', current.fit_highlights?.working_capability_count),
          basic_capability_count: readNumber('highlight_basic_capability_count', current.fit_highlights?.basic_capability_count),
          reviewed_signal_count: readNumber('highlight_reviewed_signal_count', current.fit_highlights?.reviewed_signal_count),
          max_highlights: readNumber('highlight_max_highlights', current.fit_highlights?.max_highlights),
        },
        search_settings: {
          ...currentSearch,
          date_range_days: readNumber('search_default_date_range_days', currentSearch.date_range_days),
          seek_max_pages: readNumber('search_default_seek_max_pages', currentSearch.seek_max_pages),
          linkedin_hours_old: readNumber('search_default_linkedin_hours_old', currentSearch.linkedin_hours_old),
          linkedin_results_per_search: readNumber('search_default_linkedin_results_per_search', currentSearch.linkedin_results_per_search),
          enforce_posted_age_limit: readBoolean('search_default_enforce_posted_age_limit', currentSearch.enforce_posted_age_limit),
          sort_newest_first: readBoolean('search_default_sort_newest_first', currentSearch.sort_newest_first),
          [LINKEDIN_EASY_APPLY_ONLY]: (() => {
            const raw = document.getElementById('search_default_' + LINKEDIN_EASY_APPLY_ONLY).value;
            if (raw === '') return null;
            return raw === 'true';
          })(),
        },
        default_country_suffix: document.getElementById('default_country_suffix').value.trim(),
        limits: {
          search: {
            ...currentSearchLimits,
            date_range_days: {
              min: readNumber('search_limit_date_range_days_min', currentSearchLimits.date_range_days?.min),
              max: readNumber('search_limit_date_range_days_max', currentSearchLimits.date_range_days?.max),
            },
            seek_max_pages: {
              min: readNumber('search_limit_seek_max_pages_min', currentSearchLimits.seek_max_pages?.min),
              max: readNumber('search_limit_seek_max_pages_max', currentSearchLimits.seek_max_pages?.max),
            },
            linkedin_hours_old: {
              min: readNumber('search_limit_linkedin_hours_old_min', currentSearchLimits.linkedin_hours_old?.min),
              max: readNumber('search_limit_linkedin_hours_old_max', currentSearchLimits.linkedin_hours_old?.max),
            },
            linkedin_results_per_search: {
              min: readNumber('search_limit_linkedin_results_per_search_min', currentSearchLimits.linkedin_results_per_search?.min),
              max: readNumber('search_limit_linkedin_results_per_search_max', currentSearchLimits.linkedin_results_per_search?.max),
            },
          },
          salary: {
            ...currentSalaryLimits,
            minimum_salary_yearly: {
              min: currentSalaryLimits.minimum_salary_yearly?.min ?? 0,
              max: readCurrencyFieldValue('salary_limit_minimum_salary_yearly_max', currentSalaryLimits.minimum_salary_yearly?.max),
            },
            minimum_daily_rate: {
              min: currentSalaryLimits.minimum_daily_rate?.min ?? 0,
              max: readCurrencyFieldValue('salary_limit_minimum_daily_rate_max', currentSalaryLimits.minimum_daily_rate?.max),
            },
          },
          candidate_profile_tier_weights: {
            ...currentEvidenceWeights,
            primary_candidate_profile_context: readNumber('evidence_primary_weight', currentEvidenceWeights.primary_candidate_profile_context),
            secondary_candidate_profile_context: readNumber('evidence_secondary_weight', currentEvidenceWeights.secondary_candidate_profile_context),
            supplementary_candidate_profile_context: readNumber('evidence_supplementary_weight', currentEvidenceWeights.supplementary_candidate_profile_context),
          },
          history_settings: {
            ...currentHistory,
            archive_stale_after_days: readNumber('history_archive_stale_after_days', currentHistory.archive_stale_after_days),
            hidden_review_days: readNumber('history_hidden_review_days', currentHistory.hidden_review_days),
            max_history_sightings: readNumber('history_max_history_sightings', currentHistory.max_history_sightings),
            repeated_listing_min_times_seen: readNumber('history_repeated_listing_min_times_seen', currentHistory.repeated_listing_min_times_seen),
            repeated_listing_min_span_days: readNumber('history_repeated_listing_min_span_days', currentHistory.repeated_listing_min_span_days),
            multi_listing_red_flag_min_listings: readNumber('history_multi_listing_red_flag_min_listings', currentHistory.multi_listing_red_flag_min_listings),
            multi_listing_red_flag_min_span_days: readNumber('history_multi_listing_red_flag_min_span_days', currentHistory.multi_listing_red_flag_min_span_days),
          },
          description_trust_settings: {
            ...currentDescriptionTrust,
            min_trusted_description_length: readNumber(
              'description_trust_min_trusted_description_length',
              currentDescriptionTrust.min_trusted_description_length,
            ),
          },
          source_document_settings: {
            ...currentSourceDocuments,
          },
          onboarding_settings: {
            ...currentOnboarding,
            extraction_lookback_years: readNumber('onboarding_extraction_lookback_years', currentOnboarding.extraction_lookback_years),
            title_extraction_min_months: readNumber('onboarding_title_extraction_min_months', currentOnboarding.title_extraction_min_months),
            max_target_patterns: readNumber('onboarding_max_target_patterns', currentOnboarding.max_target_patterns),
            max_secondary_patterns: readNumber('onboarding_max_secondary_patterns', currentOnboarding.max_secondary_patterns),
            capability_alias_limit: readNumber('onboarding_capability_alias_limit', currentOnboarding.capability_alias_limit),
            signal_cluster_min_alias_hits: readNumber('onboarding_signal_cluster_min_alias_hits', currentOnboarding.signal_cluster_min_alias_hits),
            signal_cluster_min_snippet_hits: readNumber('onboarding_signal_cluster_min_snippet_hits', currentOnboarding.signal_cluster_min_snippet_hits),
            signal_cluster_dense_snippet_alias_hits: readNumber('onboarding_signal_cluster_dense_snippet_alias_hits', currentOnboarding.signal_cluster_dense_snippet_alias_hits),
            capability_strength_preset: document.getElementById('onboarding_capability_strength_preset').value || currentOnboarding.capability_strength_preset,
          },
          llm_settings: {
            ...current.llm_settings,
            model_options: toLines(document.getElementById('llm_model_options').value),
            max_llm_chars: readNumber('llm_max_llm_chars', current.llm_settings?.max_llm_chars),
            pricing_per_1m: JSON.parse(document.getElementById('llm_pricing_per_1m').value.trim() || '{}'),
            llm_prompt_settings: JSON.parse(document.getElementById('llm_prompt_settings').value.trim() || '{}'),
          },
          review_settings: {
            ...currentReviewSettings,
          },
          playwright_settings: {
            ...currentPlaywright,
            playwright_viewport_width: readNumber('playwright_viewport_width', currentPlaywright.playwright_viewport_width),
            playwright_viewport_height: readNumber('playwright_viewport_height', currentPlaywright.playwright_viewport_height),
            playwright_selector_timeout: readNumber('playwright_selector_timeout', currentPlaywright.playwright_selector_timeout),
          },
        },
      };
    }

    const chipHtmlIdAliases = { adjacent_title_patterns: 'secondary_title_patterns' };
    function resolveChipEditorId(id) { return chipHtmlIdAliases[id] || id; }

    document.addEventListener('click', async e => {
      const addBtn = e.target.closest('[data-add-chip]');
      if (addBtn) {
        addChipValue(resolveChipEditorId(addBtn.dataset.addChip));
        return;
      }
      const removeBtn = e.target.closest('[data-remove-chip]');
      if (removeBtn) {
        removeChipValue(resolveChipEditorId(removeBtn.dataset.removeChip), Number(removeBtn.dataset.chipIndex));
      }
    });

    document.addEventListener('keydown', e => {
      const input = e.target.closest('[data-chip-input]');
      if (!input || e.key !== 'Enter') return;
      e.preventDefault();
      addChipValue(resolveChipEditorId(input.dataset.chipInput));
    });

    function renderTelegramSubscribers(subscribers) {
      const panel = document.getElementById('telegram_subscribers_panel');
      if (!subscribers || !subscribers.length) {
        panel.innerHTML = '<p class="field-help">You haven\'t linked a Telegram account to receive alerts yet.</p>';
        return;
      }
      panel.innerHTML = `
        <p><strong>Job alerts are currently being sent to:</strong></p>
        <ul style="margin-top: 8px;">
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
      const renderConnectHelp = (bodyHtml) => `
        <details class="help-drawer">
          <summary>Connect your Telegram account</summary>
          <div class="help-box">
            ${bodyHtml}
          </div>
        </details>
      `;
      if (!settings?.telegram?.bot_token_present) {
        telegramConnectLink = '';
        panel.innerHTML = renderConnectHelp(`
          <p class="field-help">Save your Bot Token and Bot Username first. After that, this area will show the Telegram link you open to connect your own account to this bot.</p>
        `);
        return;
      }
      if (!telegramConnectLink) {
        panel.innerHTML = renderConnectHelp(`
          <p class="field-help">Settings are saved. Click <strong>Open Telegram Link</strong> below to open the bot chat in Telegram, then press <strong>Start</strong>.</p>
        `);
        return;
      }
      panel.innerHTML = renderConnectHelp(`
        <div class="help">This step tells your personal bot which Telegram account should receive alerts.</div>
        <div class="help">Telegram link: <a href="${escapeHtml(telegramConnectLink)}" target="_blank" rel="noreferrer" style="word-break: break-all;">${escapeHtml(telegramConnectLink)}</a></div>
        <div class="help">What "Open Telegram Link" means: it opens this bot chat in Telegram on this device so you can press Start.</div>
        <div class="help">Finish setup:</div>
        <ol>
          <li>Click <strong>Open Telegram Link</strong>.</li>
          <li>Telegram opens the bot chat.</li>
          <li>Press <strong>Start</strong> once.</li>
          <li>Come back here and click <strong>Refresh Telegram Connection</strong>.</li>
        </ol>
        <p class="field-help" style="margin-top: 12px;"><em>If the link does not open, make sure Telegram is installed or open the link on your phone.</em></p>
      `);
    }

    function renderLlmModelOptions() {
      const select = document.getElementById('llm_model');
      if (!select) return;
      const modelOptions = loadedGlobalSettings?.llm_settings?.model_options;
      const options = Array.isArray(modelOptions)
        ? modelOptions.map(model => String(model || '').trim()).filter(Boolean)
        : [];
      const currentModel = String(loadedUserSettings?.llm?.model || '').trim();
      const mergedOptions = currentModel && !options.includes(currentModel)
        ? [currentModel, ...options]
        : options;
      select.innerHTML = ['<option value="">Select a model</option>']
        .concat(mergedOptions.map(model => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`))
        .join('');
      if (currentModel) {
        select.value = currentModel;
      }
    }

    function fillUserSettings(settings) {
      loadedUserSettings = settings || {};
      const workspace = settings?.workspace || {};
      document.getElementById('workspace_minimum_score').value = String(workspace.minimum_score ?? '');
      const schedule = settings?.schedule || {};
      document.getElementById('schedule_daily_time_local').value = schedule.daily_time_local || '08:30';
      const telegram = settings?.telegram || {};
      document.getElementById('telegram_enabled').value = String(Boolean(telegram.enabled));
      document.getElementById('telegram_bot_token').value = '';
      document.getElementById('telegram_bot_username').value = telegram.bot_username || '';
      document.getElementById('telegram_disable_link_preview').value = String(Boolean(telegram.disable_link_preview));
      telegramConnectLink = telegram.bot_username ? `https://t.me/${telegram.bot_username}?start=connect` : telegramConnectLink;
      renderTelegramSubscribers(telegram.subscribers || []);
      renderTelegramConnectPanel(settings);
      renderLlmModelOptions();
    }

    async function loadProfile() {
      const response = await jobHunterFetch('/api/profile');
      if (!response.ok) throw new Error('Could not load profile');
      const profile = await response.json();
      loadedProfile = profile;
      fillForm(profile);
      showStatus('Profile loaded.', 'ok', { autoHideMs: 2600 });
    }

    async function loadGlobalSettings() {
      const response = await jobHunterFetch('/api/global-settings');
      if (!response.ok) throw new Error('Could not load global settings');
      const settings = await response.json();
      loadedGlobalSettings = settings;
      fillGlobalForm(settings);
    }

    function collectUserSettings() {
      const currentSchedule = loadedUserSettings?.schedule || {};
      const currentLlmModel = String(
        document.getElementById('llm_model')?.value
        || loadedUserSettings?.llm?.model
        || ''
      ).trim();
      return {
        workspace: {
          minimum_score: (() => {
            const raw = document.getElementById('workspace_minimum_score').value;
            return raw !== '' ? Number(raw) : (loadedUserSettings?.workspace?.minimum_score ?? 0);
          })(),
        },
        schedule: {
          daily_time_local: document.getElementById('schedule_daily_time_local').value || '08:30',
          loop_sleep_seconds: Number(currentSchedule.loop_sleep_seconds || 300),
        },
        telegram: {
          enabled: document.getElementById('telegram_enabled').value === 'true',
          bot_token: document.getElementById('telegram_bot_token').value.trim(),
          bot_username: document.getElementById('telegram_bot_username').value.trim().replace(/^@+/, ''),
          disable_link_preview: document.getElementById('telegram_disable_link_preview').value === 'true',
        },
        llm: currentLlmModel ? { model: currentLlmModel } : {},
      };
    }

    async function loadUserSettings() {
      const response = await jobHunterFetch('/api/user-settings');
      if (!response.ok) throw new Error('Could not load alert settings');
      const settings = await response.json();
      fillUserSettings(settings);
    }

    async function loadTelegramConnectLink() {
      const response = await jobHunterFetch('/api/telegram/connect-link');
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not build Telegram connect link');
      telegramConnectLink = payload.connect_link || '';
      renderTelegramConnectPanel({ telegram: { bot_token_present: true } });
      return payload;
    }

    async function syncTelegramSubscribers() {
      const response = await jobHunterFetch('/api/telegram/sync', { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not refresh the connected Telegram account');
      fillUserSettings(payload.settings || {});
      if (payload.result?.bot_username) {
        telegramConnectLink = `https://t.me/${payload.result.bot_username}?start=connect`;
      }
      renderTelegramConnectPanel(payload.settings || {});
      showStatus(payload.message || 'Connected Telegram account refreshed.', 'ok');
      return payload;
    }

    async function sendTelegramTestMessage() {
      const response = await jobHunterFetch('/api/telegram/test-message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not send Telegram test message');
      showStatus(payload.message || 'Telegram test message sent.', 'ok');
      return payload;
    }

    function renderRunStats(stats) {
      const panel = document.getElementById('run_stats_panel');
      const lastAttemptAt = stats?.last_run_attempt_at || stats?.run_started_at || '';
      if (!stats || !lastAttemptAt) {
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
        <p><strong>Last attempt:</strong> ${lastAttemptAt}</p>
        <p><strong>Pages crawled:</strong> ${stats.page_count} | <strong>Cards seen:</strong> ${stats.cards_seen} | <strong>Detail pages opened:</strong> ${stats.detail_fetches} | <strong>Keep rate:</strong> ${(Number(stats.keep_rate || 0) * 100).toFixed(1)}%</p>
        <p><strong>Search window:</strong> last ${stats.search_window_days} day(s) | <strong>Prefer newest jobs first:</strong> ${stats.sort_newest_first ? 'Yes' : 'No'}</p>
        <p><strong>Search targets:</strong></p>
        <ul>${targets || '<li>None</li>'}</ul>
        <p><strong>Top reject reasons:</strong></p>
        <ul>${rejectHtml || '<li>None</li>'}</ul>
      `;
    }

    async function loadRunStats() {
      if (!isTestMode) {
        const panel = document.getElementById('run_stats_panel');
        if (panel) {
          panel.innerHTML = '';
        }
        return;
      }
      const response = await jobHunterFetch('/api/run-stats');
      if (!response.ok) { renderRunStats(null); return; }
      const stats = await response.json();
      renderRunStats(stats);
    }
  
    function setRunButtonState(isRunning) {
      if (!runNowButton) return;
      runNowButton.disabled = Boolean(isRunning);
      runNowButton.classList.toggle('is-working', Boolean(isRunning));
      runNowButton.textContent = isRunning ? 'Run in progress...' : 'Run Search Now';
    }

    function escapeHtml(value) {
      return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    document.getElementById('reload')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Reloading...';
      try {
        await loadProfile();
        initSliders();
        clearDirty();
        showStatus('Profile reloaded from disk.', 'ok', { autoHideMs: 2600 });
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    }); 

    document.getElementById('open_telegram_connect')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Generating...';
      try {
        if (!telegramConnectLink) await loadTelegramConnectLink();
        if (!telegramConnectLink) throw new Error('No Telegram connect link available yet.');
        showStatus('Opening Telegram... If it fails to open, copy the link from the panel below.', 'ok', { autoHideMs: 5000 });
        window.open(telegramConnectLink, '_blank', 'noopener');
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

    document.getElementById('sync_telegram_subscribers')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Syncing...';
      try {
        await syncTelegramSubscribers();
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

    document.getElementById('send_telegram_test')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Sending...';
      try {
        await sendTelegramTestMessage();
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

    document.getElementById('add_capability_rule')?.addEventListener('click', () => {
      capabilityRuleState = [...capabilityRuleState, { name: '', level: 'intermediate', aliases: [] }];
      expandedCapabilityRows.add(capabilityRuleState.length - 1);
      renderCapabilityRuleEditor();
      markDirty();
    });

    document.getElementById('capability_matrix_filter')?.addEventListener('input', () => {
      renderCapabilityRuleEditor();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('input', (event) => {
      const field = event.target.closest('[data-capability-field]');
      if (!field) return;
      const card = field.closest('[data-capability-index]');
      if (!card) return;
      const index = Number(card.dataset.capabilityIndex);
      const key = field.dataset.capabilityField;
      capabilityRuleState[index] = {
        ...capabilityRuleState[index],
        [key]: key === 'name' ? String(field.value || '').replace(/\s+/g, ' ').trim() : String(field.value || '').trim().toLowerCase(),
      };
      settingsField('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('change', (event) => {
      const field = event.target.closest('[data-capability-field]');
      if (!field) return;
      const card = field.closest('[data-capability-index]');
      if (!card) return;
      const index = Number(card.dataset.capabilityIndex);
      const key = field.dataset.capabilityField;
      capabilityRuleState[index] = {
        ...capabilityRuleState[index],
        [key]: key === 'name' ? String(field.value || '').replace(/\s+/g, ' ').trim() : String(field.value || '').trim().toLowerCase(),
      };
      renderCapabilityRuleEditor();
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('click', (event) => {
      const removeCard = event.target.closest('[data-remove-capability]');
      if (removeCard) {
        const index = Number(removeCard.dataset.removeCapability);
        capabilityRuleState.splice(index, 1);
        expandedCapabilityRows = new Set(
          [...expandedCapabilityRows]
            .filter(value => value !== index)
            .map(value => value > index ? value - 1 : value)
        );
        setCapabilityRuleState(capabilityRuleState);
        markDirty();
        return;
      }
    });

    // -- Navigation --------------------------------------------
    document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
      btn.addEventListener('click', () => {
        const sectionId = btn.dataset.section;
        document.querySelectorAll('.settings-group').forEach(group => {
          group.classList.toggle('is-active', group.id === sectionId);
        });
        document.querySelectorAll('.nav-item').forEach(item => {
          item.classList.toggle('is-active', item === btn);
        });
        window.location.hash = sectionId;
      });
    });

    if (window.location.hash) {
      const target = document.querySelector(`.nav-item[data-section="${window.location.hash.replace('#','')}"]`);
      if (target && !target.hidden) target.click();
    }
    if (!document.querySelector(`.settings-group.is-active[data-screen="${pageMode}"]`)) {
      const firstVisibleSection = document.querySelector(`.settings-group[data-screen="${pageMode}"]`);
      const firstVisibleNav = document.querySelector(`.nav-item[data-screen="${pageMode}"][data-section="${firstVisibleSection?.id || ''}"]`);
      document.querySelectorAll('.settings-group').forEach(group => {
        group.classList.toggle('is-active', group === firstVisibleSection);
      });
      document.querySelectorAll('.nav-item[data-section]').forEach(item => {
        item.classList.toggle('is-active', item === firstVisibleNav);
      });
      if (firstVisibleSection) {
        window.location.hash = firstVisibleSection.id;
      }
    }

    // -- Sliders -----------------------------------------------
    function updateSliderLabel(slider) {
      const label = document.getElementById(slider.id + '_label');
      if (!label) return;
      const val = parseFloat(slider.value);
      const map = { 0: 'Ignore', 0.5: 'Light', 1: 'Normal', 1.5: 'High', 2: 'Very high' };
      label.textContent = map[val] || val;
    }

    document.querySelectorAll('[data-weight-slider]').forEach(slider => {
      slider.addEventListener('input', () => {
        updateSliderLabel(slider);
        markDirty();
      });
    });

    function initSliders() {
      document.querySelectorAll('[data-weight-slider]').forEach(updateSliderLabel);
    }

    // -- Save Management ---------------------------------------
    const stickySaveBar = document.getElementById('sticky_save_bar');
    const saveSettingsBtn = document.getElementById('save_settings_btn');
    const saveAdminBtn = document.getElementById('save_admin_btn');
    const activeSaveButton = isAdminPage ? saveAdminBtn : saveSettingsBtn;
    const discardSettingsBtn = document.getElementById('discard_changes_btn');
    const discardAdminBtn = document.getElementById('discard_admin_changes_btn');
    const activeDiscardButton = isAdminPage ? discardAdminBtn : discardSettingsBtn;
    const globalStatus = document.getElementById('global_save_status');

    if (activeSaveButton) {
      activeSaveButton.disabled = true;
    }

    bindCurrencyFields();

    document.querySelectorAll('input, select, textarea').forEach(el => {
      if (el.id === 'capability_matrix_filter' || el.classList.contains('is-readonly') || el.type === 'hidden') return;
      el.addEventListener('change', markDirty);
      if (el.tagName === 'TEXTAREA' || ['text', 'time', 'number', 'password', 'search'].includes(el.type)) {
        el.addEventListener('input', markDirty);
      }
    });
    document.querySelectorAll('input[name="work_mode_preference"]').forEach((cb) => {
      cb.addEventListener('change', () => {
        if (!cb.checked) {
          const anyChecked = document.querySelectorAll('input[name="work_mode_preference"]:checked').length > 0;
          if (!anyChecked) cb.checked = true;
        }
      });
    });

    activeDiscardButton?.addEventListener('click', () => {
      window.location.reload();
    });

    async function saveActivePage() {
      if (!activeSaveButton) return;
      const originalLabel = activeSaveButton.textContent;
      activeSaveButton.classList.add('is-working');
      activeSaveButton.disabled = true;
      activeSaveButton.textContent = 'Saving...';
      showInlineStatus(globalStatus, isAdminPage ? 'Saving global settings...' : 'Saving settings...', 'loading');
      try {
        if (isAdminPage) {
          const globalSettings = collectGlobalSettings();
          const globalResponse = await jobHunterFetch('/api/global-settings', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(globalSettings),
          });
          const globalPayload = await globalResponse.json().catch(() => ({}));
          if (!globalResponse.ok) {
            throw new Error(globalPayload.error || 'Could not save global settings.');
          }
          fillGlobalForm(globalPayload);
          showInlineStatus(globalStatus, 'Global settings saved.', 'ok');
          showStatus('Global settings saved successfully.', 'ok');
        } else {
          const profile = collectProfile();
      const agentSettings = collectUserSettings();

          const profileResponse = await jobHunterFetch('/api/profile', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(profile),
          });
          const profilePayload = await profileResponse.json().catch(() => ({}));
          if (!profileResponse.ok) {
            throw new Error(profilePayload.error || 'Could not save profile settings.');
          }

      const userResponse = await jobHunterFetch('/api/user-settings', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(agentSettings),
          });
      const userPayload = await userResponse.json().catch(() => ({}));
      if (!userResponse.ok) {
        throw new Error(userPayload.error || 'Could not save user settings.');
      }

          fillForm(profilePayload);
        fillUserSettings(userPayload);
          initSliders();
          showInlineStatus(globalStatus, 'Settings saved.', 'ok');
          showStatus('Settings saved successfully.', 'ok', { autoHideMs: 2500 });
        }
        clearDirty();
      } catch (err) {
        if (activeSaveButton) activeSaveButton.disabled = false;
        showInlineStatus(globalStatus, err?.message || 'Could not save changes.', 'error');
        showStatus(err?.message || 'Could not save changes.', 'error');
      } finally {
        activeSaveButton.classList.remove('is-working');
        activeSaveButton.textContent = originalLabel;
      }
    }

    activeSaveButton?.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      saveActivePage();
    });
    const pageLoads = isAdminPage
      ? [loadGlobalSettings()]
      : [loadProfile(), loadUserSettings()];
    if (!isAdminPage) {
      pageLoads.push(loadRunStats());
    }
    Promise.all(pageLoads).then(() => {
        initSliders();
        suppressDirtyTracking = false;
        clearDirty();
    }).catch(error => showStatus(error.message, 'error'));
