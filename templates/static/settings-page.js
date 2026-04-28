
    const statusEl = document.getElementById('status');
    const runStatusPillEl = document.getElementById('run_status_pill');
    const runLastRunEl = document.getElementById('run_last_run');
    const runNowButton = document.getElementById('run_now');
    const rebuildProfileButton = document.getElementById('rebuild_profile');
    let telegramConnectLink = '';
    let loadedAgentSettings = null;
    let loadedProfile = null;
    let capabilityRuleState = [];
    let expandedCapabilityRows = new Set();
    let runStatusPollHandle = null;
    let lastObservedRunStatus = 'idle';
    let suppressDirtyTracking = true;
    let statusHideTimer = null;
    const listTextAreas = [
      'locations',
      'target_title_patterns',
      'adjacent_title_patterns',
      'classification_ids',
      'must_not_require_skills',
    ];

    const ruleTextAreas = [
      ['reject_title_rules', 'pattern'],
      ['reject_description_phrase_rules', 'phrase'],
    ];

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
        return `${rule.name || ''} || ${rule.level || ''} || ${rule.fit || ''} || ${aliases}`;
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
        const aliasesIndex = parts.length >= 4 ? 3 : 2;
        return {
          name: (parts[0] || '').trim(),
          level: (parts[1] || '').trim().toLowerCase(),
          fit: (parts.length >= 4 ? (parts[2] || '') : '').trim().toLowerCase(),
          aliases: (parts[aliasesIndex] || '').split(',').map(item => item.trim()).filter(Boolean),
        };
      }).filter(rule => rule.name && rule.level);
    }

    const capabilityModeMeta = {
      core_skill: {
        label: 'Core skill',
        summary: 'One of your main strengths for the roles you want.',
        level: 'strong',
        fit: 'core',
      },
      useful_support: {
        label: 'Useful support',
        summary: 'A real skill that helps matching, but should not define it.',
        level: 'working',
        fit: 'supporting',
      },
      background_only: {
        label: 'Background only',
        summary: 'Acceptable context, but it should not pull roles up by itself.',
        level: 'basic',
        fit: 'contextual',
      },
      not_for_me: {
        label: 'Not for me',
        summary: 'If a role leans on this capability, it is probably the wrong direction.',
        level: 'none',
        fit: 'avoid',
      },
    };

    const capabilityPriorityMeta = {
      core: {
        label: 'Core skills',
        summary: 'Main strengths that should actively pull matching roles up.',
      },
      supporting: {
        label: 'Useful support',
        summary: 'Helpful skills that should improve matching without defining it.',
      },
      contextual: {
        label: 'Background only',
        summary: 'Acceptable context that should stay in the background.',
      },
      avoid: {
        label: 'Not for me',
        summary: 'Capabilities that point toward the wrong kinds of roles.',
      },
    };

    const capabilityPriorityOrder = ['core', 'supporting', 'contextual', 'avoid'];

    function normalizeCapabilityAliasValue(value) {
      return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function capabilityModeFromRule(rule) {
      const level = String(rule?.level || '').trim().toLowerCase();
      const fit = String(rule?.fit || '').trim().toLowerCase();
      if (fit === 'avoid' || level === 'none') return 'not_for_me';
      if (fit === 'core') return 'core_skill';
      if (fit === 'supporting') return 'useful_support';
      return 'background_only';
    }

    function applyCapabilityModeToRule(rule, mode) {
      const meta = capabilityModeMeta[mode] || capabilityModeMeta.background_only;
      return {
        ...(rule || {}),
        level: meta.level,
        fit: meta.fit,
      };
    }

    function capabilityAliasPreview(aliases) {
      const cleaned = Array.isArray(aliases) ? aliases.filter(Boolean) : [];
      if (!cleaned.length) return 'Job ad keywords: none yet';
      const preview = cleaned.slice(0, 3).join(', ');
      return cleaned.length > 3
        ? `Job ad keywords: ${preview}, +${cleaned.length - 3} more`
        : `Job ad keywords: ${preview}`;
    }

    function normalizeCapabilityRule(rule) {
      const name = String(rule?.name || '').replace(/\s+/g, ' ').trim();
      const rawLevel = String(rule?.level || 'basic').trim().toLowerCase();
      const rawFit = String(rule?.fit || 'contextual').trim().toLowerCase();
      const validLevels = new Set(['strong', 'working', 'basic', 'low', 'none']);
      const validFits = new Set(['core', 'supporting', 'contextual', 'avoid']);
      const level = validLevels.has(rawLevel) ? rawLevel : 'basic';
      const fit = validFits.has(rawFit) ? rawFit : 'contextual';
      const aliases = [];
      const seen = new Set();
      for (const value of Array.isArray(rule?.aliases) ? rule.aliases : []) {
        const cleaned = normalizeCapabilityAliasValue(value);
        if (!cleaned || cleaned === name.toLowerCase() || seen.has(cleaned)) continue;
        seen.add(cleaned);
        aliases.push(cleaned);
      }
      return { name, level, fit, aliases };
    }

    function setCapabilityRuleState(rules) {
      capabilityRuleState = (rules || [])
        .map(normalizeCapabilityRule)
        .filter(rule => rule.name);
      expandedCapabilityRows = new Set(
        [...expandedCapabilityRows].filter(index => index >= 0 && index < capabilityRuleState.length)
      );
      document.getElementById('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
      renderCapabilityRuleEditor();
    }

    function collectCapabilityRuleState() {
      const cleaned = capabilityRuleState
        .map(normalizeCapabilityRule)
        .filter(rule => rule.name);
      capabilityRuleState = cleaned;
      document.getElementById('capability_profile_rules').value = capabilityRulesToText(cleaned);
      return cleaned;
    }

    function renderCapabilityRuleEditor() {
      const container = document.getElementById('capability_matrix_editor');
      if (!container) return;
      if (!capabilityRuleState.length) {
        container.innerHTML = '<div class="capability-editor-empty">No capability rules yet. Run onboarding or add a capability row here.</div>';
        return;
      }
      const filterTerm = String(document.getElementById('capability_matrix_filter')?.value || '').trim().toLowerCase();
      const groups = capabilityPriorityOrder.map(priority => {
        const rules = capabilityRuleState
          .map((rule, index) => ({ rule, index }))
          .filter(item => item.rule.fit === priority)
          .filter(item => {
            if (!filterTerm) return true;
            return item.rule.name.toLowerCase().includes(filterTerm)
              || item.rule.aliases.some(alias => alias.includes(filterTerm));
          });
        return { priority, rules };
      });

      container.innerHTML = groups.map(group => {
        const priorityMeta = capabilityPriorityMeta[group.priority];
        const rowsHtml = group.rules.length
          ? group.rules.map(({ rule, index }) => `
              <details class="capability-row" data-capability-index="${index}"${expandedCapabilityRows.has(index) || filterTerm ? ' open' : ''}>
                <summary class="capability-row-summary">
                  <div class="capability-row-summary-main">
                    <strong class="capability-row-title">${escapeHtml(rule.name || 'Untitled capability')}</strong>
                    <span class="capability-row-summary-copy">${escapeHtml(capabilityAliasPreview(rule.aliases))}</span>
                  </div>
                  <div class="capability-row-summary-meta">
                    <span class="suggestion-chip">${escapeHtml(capabilityModeMeta[capabilityModeFromRule(rule)]?.label || 'Background only')}</span>
                    <span class="suggestion-chip">${escapeHtml(String(rule.aliases.length))} job ad keyword${rule.aliases.length === 1 ? '' : 's'}</span>
                  </div>
                </summary>
                <div class="capability-row-body">
                  <div class="capability-row-fields">
                    <div>
                      <label for="capability_name_${index}">Capability</label>
                      <input id="capability_name_${index}" type="text" data-capability-field="name" value="${escapeHtml(rule.name)}" placeholder="e.g. Agile delivery">
                    </div>
                    <div>
                      <label for="capability_mode_${index}">How should the app treat this?</label>
                      <select id="capability_mode_${index}" data-capability-mode>
                        <option value="core_skill"${capabilityModeFromRule(rule) === 'core_skill' ? ' selected' : ''}>Core skill</option>
                        <option value="useful_support"${capabilityModeFromRule(rule) === 'useful_support' ? ' selected' : ''}>Useful support</option>
                        <option value="background_only"${capabilityModeFromRule(rule) === 'background_only' ? ' selected' : ''}>Background only</option>
                        <option value="not_for_me"${capabilityModeFromRule(rule) === 'not_for_me' ? ' selected' : ''}>Not for me</option>
                      </select>
                    </div>
                    <div class="capability-row-actions">
                      <button class="secondary" type="button" data-remove-capability="${index}">Remove</button>
                    </div>
                  </div>
                  <div class="capability-meta">
                    <span class="suggestion-chip">${escapeHtml(capabilityModeMeta[capabilityModeFromRule(rule)]?.label || 'Background only')}</span>
                    <span class="suggestion-chip">${escapeHtml(String(rule.aliases.length))} job ad keyword${rule.aliases.length === 1 ? '' : 's'}</span>
                  </div>
                  <p class="capability-copy">${escapeHtml(capabilityModeMeta[capabilityModeFromRule(rule)]?.summary || '')}</p>
                  <details class="capability-alias-shell">
                    <summary class="capability-alias-summary">Job ad keywords (${rule.aliases.length})</summary>
                    <p class="field-help">Short words or phrases the app looks for in job descriptions. Use JD language like <code>agile</code>, <code>scrum</code>, <code>kanban</code>, not CV sentence fragments.</p>
                    <div class="badge-editor">
                      <div class="badge-editor-list">
                        ${rule.aliases.length ? rule.aliases.map((alias, aliasIndex) => `
                          <span class="rule-chip">
                            <span>${escapeHtml(alias)}</span>
                            <button type="button" data-remove-capability-alias="${index}" data-alias-index="${aliasIndex}" title="Remove ${escapeHtml(alias)}">&#215;</button>
                          </span>
                        `).join('') : '<span class="badge-editor-empty">No job ad keywords yet.</span>'}
                      </div>
                      <div class="badge-editor-form">
                        <input type="text" data-capability-alias-input="${index}" placeholder="Add a short job-ad keyword">
                        <button class="secondary" type="button" data-add-capability-alias="${index}">Add</button>
                      </div>
                    </div>
                  </details>
                </div>
              </details>
            `).join('')
          : '<div class="capability-editor-empty-group">No matching capabilities in this group.</div>';
        return `
          <section class="capability-group">
            <div class="capability-group-head">
              <h4>${escapeHtml(priorityMeta.label)} capabilities</h4>
              <span class="suggestion-chip">${escapeHtml(String(group.rules.length))} shown</span>
            </div>
            <p class="capability-group-copy">${escapeHtml(priorityMeta.summary)}</p>
            <div class="capability-row-list">${rowsHtml}</div>
          </section>
        `;
      }).join('');
    }

    const chipEditors = {
      target_title_patterns: { kind: 'list', listId: 'target_title_patterns_chips', inputId: 'target_title_patterns_add', emptyText: 'No target titles yet.' },
      adjacent_title_patterns: { kind: 'list', listId: 'adjacent_title_patterns_chips', inputId: 'adjacent_title_patterns_add', emptyText: 'No secondary titles yet.' },
      must_not_require_skills: { kind: 'list', listId: 'must_not_require_skills_chips', inputId: 'must_not_require_skills_add', emptyText: 'No mandatory-skill blocks yet.' },
      reject_title_rules: { kind: 'rule', key: 'pattern', listId: 'reject_title_rules_chips', inputId: 'reject_title_rules_add', emptyText: 'No blocked title words yet. Rules added from the dashboard appear here.' },
      reject_description_phrase_rules: { kind: 'rule', key: 'phrase', listId: 'reject_description_phrase_rules_chips', inputId: 'reject_description_phrase_rules_add', emptyText: 'No blocked description phrases yet.' },
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
      if (id === 'target_title_patterns' || id === 'adjacent_title_patterns') {
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
      const field = document.getElementById(id);
      return field ? toLines(field.value) : [];
    }

    function setListItems(id, items) {
      const field = document.getElementById(id);
      if (field) field.value = (items || []).join('\n');
    }

    function getRuleItems(id) {
      const editor = chipEditors[id];
      const field = document.getElementById(id);
      return field && editor ? textToRules(field.value, editor.key) : [];
    }

    function setRuleItems(id, items) {
      const editor = chipEditors[id];
      const field = document.getElementById(id);
      if (field && editor) field.value = rulesToText(items || [], editor.key);
    }

    function markDirty() {
      if (suppressDirtyTracking) return;
      stickySaveBar?.removeAttribute('hidden');
    }

    function clearDirty() {
      stickySaveBar?.setAttribute('hidden', '');
      showInlineStatus(globalStatus, '', '');
    }

    function buildChipValue(id, rawValue) {
      const raw = normalizePlainPhrase(rawValue);
      if (!raw) return null;
      if (id === 'target_title_patterns' || id === 'adjacent_title_patterns') return titlePhraseToPattern(raw);
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
      const list = editor ? document.getElementById(editor.listId) : null;
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

    function renderAdvancedChipEditors() {
      Object.keys(chipEditors).forEach(renderChipEditor);
    }

    function addChipValue(id) {
      const editor = chipEditors[id];
      const input = editor ? document.getElementById(editor.inputId) : null;
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
        items.splice(index, 1);
        setRuleItems(id, items);
      } else {
        const items = getListItems(id);
        items.splice(index, 1);
        setListItems(id, items);
      }
      renderChipEditor(id);
      markDirty();
    }

    function flushChipEditorInputs() {
      Object.keys(chipEditors).forEach(id => {
        const input = document.getElementById(chipEditors[id].inputId);
        if (input && input.value.trim()) addChipValue(id);
      });
    }

    function fillForm(profile) {
      document.getElementById('keywords').value = profile.search_settings?.keywords || '';
      document.getElementById('locations').value = (profile.search_settings?.locations || []).join('\n');
      document.getElementById('classification_ids').value = (profile.search_settings?.classification_ids || []).join('\n');
      document.getElementById('date_range_days').value = String(profile.search_settings?.date_range_days ?? '');
      document.getElementById('max_pages_cap').value = String(profile.search_settings?.max_pages_cap ?? '');
      document.getElementById('enforce_posted_age_limit').value = String(Boolean(profile.search_settings?.enforce_posted_age_limit));
      document.getElementById('sort_newest_first').value = String(Boolean(profile.search_settings?.sort_newest_first ?? true));
      document.getElementById('linkedin_hours_old').value = String(profile.search_settings?.linkedin_hours_old ?? 24);
      document.getElementById('linkedin_results_per_search').value = String(profile.search_settings?.linkedin_results_per_search ?? 25);
      const _liEasyApply = profile.search_settings?.linkedin_easy_apply_only;
      document.getElementById('linkedin_easy_apply_only').value = (_liEasyApply === null || _liEasyApply === undefined) ? '' : String(_liEasyApply);
      document.getElementById('llm_profile_brief').value = profile.llm_profile_brief || '';
      document.getElementById('minimum_salary_yearly').value = String(profile.salary_preferences?.minimum_salary_yearly || '');
      document.getElementById('minimum_daily_rate').value = String(profile.salary_preferences?.minimum_daily_rate || '');
      document.getElementById('fit_weight').value = String(profile.preference_weights?.fit ?? 1);
      document.getElementById('salary_weight').value = String(profile.preference_weights?.salary ?? 1);
      document.getElementById('location_weight').value = String(profile.preference_weights?.location ?? 1);
      document.getElementById('work_mode_weight').value = String(profile.preference_weights?.work_mode ?? 1);
      document.getElementById('contract_weight').value = String(profile.preference_weights?.contract ?? 1);
      document.getElementById('government_weight').value = String(profile.preference_weights?.government ?? 1);
      document.getElementById('freshness_weight').value = String(profile.preference_weights?.freshness ?? 1);
      setCapabilityRuleState(profile.capability_profile_rules || []);
      document.getElementById('cv_text_debug').value = (profile.cv_text || '').trim();
      for (const id of ['target_title_patterns', 'adjacent_title_patterns', 'must_not_require_skills']) {
        document.getElementById(id).value = (profile[id] || []).join('\n');
      }
      for (const [id, key] of ruleTextAreas) {
        document.getElementById(id).value = rulesToText(profile[id], key);
      }
      renderAdvancedChipEditors();
    }

    document.addEventListener('click', async e => {
      const addBtn = e.target.closest('[data-add-chip]');
      if (addBtn) {
        addChipValue(addBtn.dataset.addChip);
        return;
      }
      const removeBtn = e.target.closest('[data-remove-chip]');
      if (removeBtn) {
        removeChipValue(removeBtn.dataset.removeChip, Number(removeBtn.dataset.chipIndex));
      }
    });

    document.addEventListener('keydown', e => {
      const input = e.target.closest('[data-chip-input]');
      if (!input || e.key !== 'Enter') return;
      e.preventDefault();
      addChipValue(input.dataset.chipInput);
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
      if (!settings?.telegram?.bot_token_present) {
        telegramConnectLink = '';
        panel.innerHTML = '<div class="help-box"><p><strong>Connect your Telegram account</strong></p><p class="field-help">Save your Bot Token and Bot Username first. After that, this area will show the Telegram link you open to connect your own account to this bot.</p></div>';
        return;
      }
      if (!telegramConnectLink) {
        panel.innerHTML = '<div class="help-box"><p><strong>Connect your Telegram account</strong></p><p class="field-help">Settings are saved. Click <strong>Open Telegram Link</strong> below to open the bot chat in Telegram, then press <strong>Start</strong>.</p></div>';
        return;
      }
      panel.innerHTML = `
        <div class="help-box">
          <p><strong>Connect your Telegram account</strong></p>
          <p class="field-help">This step tells your personal bot which Telegram account should receive alerts.</p>
          <p class="field-help"><strong>Telegram link:</strong> <a href="${escapeHtml(telegramConnectLink)}" target="_blank" rel="noreferrer" style="word-break: break-all;">${escapeHtml(telegramConnectLink)}</a></p>
          <p class="field-help"><strong>What “Open Telegram Link” means:</strong> it opens this bot chat in Telegram on this device so you can press <strong>Start</strong>.</p>
          <p class="field-help"><strong>Finish setup:</strong></p>
          <ol style="margin: 0; padding-left: 20px; color: var(--muted); font-size: 0.9rem; line-height: 1.5;">
            <li>Click <strong>Open Telegram Link</strong>.</li>
            <li>Telegram opens the bot chat.</li>
            <li>Press <strong>Start</strong> once.</li>
            <li>Come back here and click <strong>Refresh Telegram Connection</strong>.</li>
          </ol>
          <p class="field-help" style="margin-top: 12px;"><em>If the link does not open, make sure Telegram is installed or open the link on your phone.</em></p>
        </div>
      `;
    }

    function fillAgentSettings(settings) {
      loadedAgentSettings = settings || {};
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
      const llm = settings?.llm || {};
      if (llm.model) document.getElementById('llm_model').value = llm.model;
    }

    async function loadProfile() {
      const response = await fetch('/api/profile');
      if (!response.ok) throw new Error('Could not load profile');
      const profile = await response.json();
      loadedProfile = profile;
      fillForm(profile);
      showStatus('Profile loaded.', 'ok', { autoHideMs: 2600 });
    }

    function collectAgentSettings() {
      const currentSchedule = loadedAgentSettings?.schedule || {};
      return {
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
        llm: {
          model: document.getElementById('llm_model').value.trim(),
        },
      };
    }

    async function loadAgentSettings() {
      const response = await fetch('/api/agent-settings');
      if (!response.ok) throw new Error('Could not load alert settings');
      const settings = await response.json();
      fillAgentSettings(settings);
    }

    async function loadTelegramConnectLink() {
      const response = await fetch('/api/telegram/connect-link');
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not build Telegram connect link');
      telegramConnectLink = payload.connect_link || '';
      renderTelegramConnectPanel({ telegram: { bot_token_present: true } });
      return payload;
    }

    async function syncTelegramSubscribers() {
      const response = await fetch('/api/telegram/sync', { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not refresh the connected Telegram account');
      fillAgentSettings(payload.settings || {});
      if (payload.result?.bot_username) {
        telegramConnectLink = `https://t.me/${payload.result.bot_username}?start=connect`;
      }
      renderTelegramConnectPanel(payload.settings || {});
      showStatus(payload.message || 'Connected Telegram account refreshed.', 'ok');
      return payload;
    }

    async function sendTelegramTestMessage() {
      const response = await fetch('/api/telegram/test-message', {
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
      if (!response.ok) { renderRunStats(null); return; }
      const stats = await response.json();
      renderRunStats(stats);
    }

    function setRunStatus(status, lastRunAt) {
      const normalized = status === 'running' ? 'running' : 'idle';
      runStatusPillEl.textContent = normalized === 'running' ? 'Running...' : 'Idle';
      runStatusPillEl.className = `status-pill ${normalized}`;
      
      let dateLabel = '';
      if (lastRunAt) {
        const d = new Date(lastRunAt);
        dateLabel = isNaN(d.valueOf()) ? lastRunAt : d.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
      }
      runLastRunEl.textContent = dateLabel ? `Last run: ${dateLabel}` : 'Ready to search';
      lastObservedRunStatus = normalized;
    }

    function ensureRunStatusPolling(shouldPoll) {
      if (shouldPoll) {
        if (runStatusPollHandle) return;
        runStatusPollHandle = window.setInterval(() => {
          loadRunStatus().catch(() => {});
        }, 10000);
        return;
      }
      if (runStatusPollHandle) {
        window.clearInterval(runStatusPollHandle);
        runStatusPollHandle = null;
      }
    }

    async function loadRunStatus() {
      const previousStatus = lastObservedRunStatus;
      const response = await fetch('/api/run-status');
      if (!response.ok) throw new Error('Could not load run status');
      const payload = await response.json();
      const status = payload.status === 'running' ? 'running' : 'idle';
      setRunStatus(status, payload.last_run_at || '');
      ensureRunStatusPolling(status === 'running');
      if (previousStatus === 'running' && status === 'idle') {
        await loadRunStats().catch(() => {});
        showStatus('Run complete. Go back to results to see the latest matches.', 'ok');
      }
      return payload;
    }

    function escapeHtml(value) {
      return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function getReviewChoiceMeta(choice) {
      const meta = {
        '': { label: 'Choose an option', summary: 'Pick the simplest description of how this capability fits your target roles.', useWhen: 'Choose the closest option based on your CV and the kept-role examples.', engineEffect: 'Nothing changes until you confirm.' },
        core_skill: { label: 'Core skill', summary: 'This is one of your main strengths for the roles you want.', useWhen: 'Use this when you want the app to strongly value this capability in matching.', engineEffect: 'The app will treat it as a strong core capability.' },
        useful_support: { label: 'Useful support', summary: 'This is a real skill, but it should support matching rather than define it.', useWhen: 'Use this when the capability is helpful and relevant, but not central to your pitch.', engineEffect: 'The app will treat it as a positive supporting capability.' },
        background_only: { label: 'Background only', summary: 'This is acceptable context, but it should not drive matching on its own.', useWhen: 'Use this for adjacent or lighter experience that should stay in the background.', engineEffect: 'The app will keep it as a weak contextual signal.' },
        not_for_me: { label: 'Not for me', summary: 'Jobs that lean on this capability are probably the wrong direction.', useWhen: 'Use this when the capability points toward work you do not want the app to favour.', engineEffect: 'The app will treat it as a capability to avoid.' },
      };
      return meta[choice] || meta[''];
    }

    function renderReviewChoiceGuide(choice) {
      const meta = getReviewChoiceMeta(choice);
      return `
        <strong>${escapeHtml(meta.label)}</strong>
        <p>${escapeHtml(meta.summary)}</p>
        <p><strong>When to use:</strong> ${escapeHtml(meta.useWhen)}</p>
        <p><strong>Engine effect:</strong> <code>${escapeHtml(meta.engineEffect)}</code></p>
      `;
    }

    function reviewOptionMarkup(selectedValue) {
      const options = [
        ['', 'Choose an option'],
        ['core_skill', 'Core skill'],
        ['useful_support', 'Useful support'],
        ['background_only', 'Background only'],
        ['not_for_me', 'Not for me'],
      ];
      return options.map(([value, label]) => {
        const selected = value === selectedValue ? ' selected' : '';
        return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
      }).join('');
    }

    function suggestionExamplesMarkup(items, emptyLabel) {
      if (!items || !items.length) return `<p>${escapeHtml(emptyLabel)}</p>`;
      return `<ul>${items.map(item => `
        <li>
          <a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(item.title || 'Untitled role')}</a>
          ${item.company ? ` - ${escapeHtml(item.company)}` : ''}
          ${item.search_location ? ` (${escapeHtml(item.search_location)})` : ''}
        </li>
      `).join('')}</ul>`;
    }

    function renderSuggestedTuning(suggestions) {
      const panel = document.getElementById('tuning_suggestions_panel');
      const capabilitySuggestions = suggestions.capability_suggestions || [];
      const ruleSuggestions = suggestions.rule_suggestions || [];
      const summary = suggestions.summary || {};
      if (!capabilitySuggestions.length && !ruleSuggestions.length) {
        panel.innerHTML = '<p>No suggested tuning yet. After a scrape run, repeated useful capability signals and repeat junk-role patterns will show up here for confirmation.</p>';
        return;
      }
      const capabilityHtml = capabilitySuggestions.length ? `
        <div class="tuning-group">
          <h3>Capability signals from viable roles</h3>
          <p class="tuning-group-copy">Repeated skills from kept roles that need a decision before the engine uses them in matching.</p>
          <div class="review-list">
            ${capabilitySuggestions.map(item => `
              <div class="review-card">
                <h3>${escapeHtml(item.skill || 'Capability signal')}</h3>
                <p>Seen in ${escapeHtml(String(item.count || 0))} kept role(s).</p>
                <div class="suggestion-meta"><span class="suggestion-chip">Suggested: ${escapeHtml(item.recommended_label || 'Review')}</span></div>
                <label>How should the app treat this?</label>
                <select class="skill-choice" data-skill="${escapeHtml(item.skill || '')}">${reviewOptionMarkup(item.recommended_choice || '')}</select>
                <details class="review-choice-guide">
                  <summary>What this choice means</summary>
                  <div class="review-choice-guide-body">${renderReviewChoiceGuide(item.recommended_choice || '')}</div>
                </details>
                <details class="review-examples">
                  <summary>Examples from kept roles</summary>
                  <div class="review-examples-body">${suggestionExamplesMarkup(item.examples || [], 'No example roles saved for this signal yet.')}</div>
                </details>
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
          <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.capability_count || capabilitySuggestions.length || 0))}</strong><span>Capability suggestions</span></div>
          <div class="tuning-summary-card"><strong>${escapeHtml(String(summary.rule_count || ruleSuggestions.length || 0))}</strong><span>Rule signals to review</span></div>
        </div>
        ${capabilityHtml}
        ${ruleHtml}
      `;
    }

    async function loadReviewData() {
      const response = await fetch('/api/review-data');
      if (!response.ok) { renderSuggestedTuning({ capability_suggestions: [], rule_suggestions: [], summary: {} }); return; }
      const payload = await response.json();
      renderSuggestedTuning(payload.suggested_tuning || { capability_suggestions: [], rule_suggestions: [], summary: {} });
    }

    function collectProfile() {
      flushChipEditorInputs();
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
        llm_profile_brief_mode: 'auto',
        llm_profile_brief: '',
        capability_profile_rules: collectCapabilityRuleState(),
        target_title_patterns: toLines(document.getElementById('target_title_patterns').value),
        adjacent_title_patterns: toLines(document.getElementById('adjacent_title_patterns').value),
        must_not_require_skills: toLines(document.getElementById('must_not_require_skills').value),
        reject_title_rules: textToRules(document.getElementById('reject_title_rules').value, 'pattern'),
        reject_description_phrase_rules: textToRules(document.getElementById('reject_description_phrase_rules').value, 'phrase'),
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

    async function runSearchNow() {
      const profile = collectProfile();
      await patchProfile(
        { search_settings: profile.search_settings, salary_preferences: profile.salary_preferences },
        'Search settings saved to profile.json.'
      );
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search_settings: profile.search_settings }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Could not start run');
      setRunStatus('running', payload.last_run_at || '');
      ensureRunStatusPolling(true);
      showStatus('Background run started. Return to results when complete.', 'ok');
      return payload;
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

    // ── Event listeners ───────────────────────────────────────

    if (runNowButton) {
      runNowButton.addEventListener('click', async () => {
        const originalLabel = runNowButton.textContent;
        runNowButton.disabled = true;
        runNowButton.textContent = 'Starting...';
        try {
          await runSearchNow();
        } catch (error) {
          showStatus(error.message, 'error');
        } finally {
          runNowButton.disabled = false;
          runNowButton.textContent = originalLabel;
        }
      });
    }

    if (rebuildProfileButton) {
      rebuildProfileButton.addEventListener('click', () => {
        window.location.href = '/start?mode=rebuild';
      });
    }

    document.getElementById('refresh_review_data')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Refreshing...';
      try {
        await loadReviewData();
        showStatus('Suggested tuning refreshed.', 'ok', { autoHideMs: 3000 });
      } catch (error) {
        showStatus(error.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel;
      }
    });

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

    document.getElementById('refresh_review')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Refreshing...';
      try {
        await Promise.all([loadRunStats(), loadReviewData()]);
        showStatus('Review data refreshed.', 'ok', { autoHideMs: 3000 });
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

    document.getElementById('tuning_suggestions_panel').addEventListener('change', (e) => {
      const select = e.target.closest('.skill-choice');
      if (!select) return;
      const card = select.closest('.review-card');
      const guideBody = card?.querySelector('.review-choice-guide-body');
      if (!guideBody) return;
      guideBody.innerHTML = renderReviewChoiceGuide(select.value || '');
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
      btn.textContent = 'Saving\u2026';
      try {
        const result = await applyOneSkipDecision(skill, choice);
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
        btn.textContent = 'Applied';
        if (result && result.profile) fillForm(result.profile);
        await loadReviewData();
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
      btn.textContent = 'Saving\u2026';
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
      if (card) { card.style.opacity = '0.4'; card.style.pointerEvents = 'none'; btn.textContent = 'Dismissed'; }
    });

    document.getElementById('add_capability_rule')?.addEventListener('click', () => {
      capabilityRuleState = [...capabilityRuleState, { name: '', level: 'working', fit: 'supporting', aliases: [] }];
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
      document.getElementById('capability_profile_rules').value = capabilityRulesToText(capabilityRuleState);
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('change', (event) => {
      const modeField = event.target.closest('[data-capability-mode]');
      if (modeField) {
        const card = modeField.closest('[data-capability-index]');
        if (!card) return;
        const index = Number(card.dataset.capabilityIndex);
        capabilityRuleState[index] = applyCapabilityModeToRule(
          capabilityRuleState[index],
          String(modeField.value || '').trim()
        );
        renderCapabilityRuleEditor();
        markDirty();
        return;
      }
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

    document.getElementById('capability_matrix_editor')?.addEventListener('toggle', (event) => {
      const row = event.target.closest('.capability-row');
      if (!row || event.target !== row) return;
      const index = Number(row.dataset.capabilityIndex);
      if (row.open) expandedCapabilityRows.add(index);
      else expandedCapabilityRows.delete(index);
    }, true);

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
      const removeAlias = event.target.closest('[data-remove-capability-alias]');
      if (removeAlias) {
        const ruleIndex = Number(removeAlias.dataset.removeCapabilityAlias);
        const aliasIndex = Number(removeAlias.dataset.aliasIndex);
        const nextAliases = [...(capabilityRuleState[ruleIndex]?.aliases || [])];
        nextAliases.splice(aliasIndex, 1);
        capabilityRuleState[ruleIndex] = { ...capabilityRuleState[ruleIndex], aliases: nextAliases };
        setCapabilityRuleState(capabilityRuleState);
        markDirty();
        return;
      }
      const addAlias = event.target.closest('[data-add-capability-alias]');
      if (!addAlias) return;
      const ruleIndex = Number(addAlias.dataset.addCapabilityAlias);
      const input = document.querySelector(`[data-capability-alias-input="${ruleIndex}"]`);
      const cleaned = normalizeCapabilityAliasValue(input?.value || '');
      if (!cleaned) return;
      const aliases = [...(capabilityRuleState[ruleIndex]?.aliases || [])];
      if (!aliases.includes(cleaned)) aliases.push(cleaned);
      capabilityRuleState[ruleIndex] = { ...capabilityRuleState[ruleIndex], aliases };
      setCapabilityRuleState(capabilityRuleState);
      markDirty();
    });

    document.getElementById('capability_matrix_editor')?.addEventListener('keydown', (event) => {
      const input = event.target.closest('[data-capability-alias-input]');
      if (!input || event.key !== 'Enter') return;
      event.preventDefault();
      const ruleIndex = Number(input.dataset.capabilityAliasInput);
      const cleaned = normalizeCapabilityAliasValue(input.value || '');
      if (!cleaned) return;
      const aliases = [...(capabilityRuleState[ruleIndex]?.aliases || [])];
      if (!aliases.includes(cleaned)) aliases.push(cleaned);
      capabilityRuleState[ruleIndex] = { ...capabilityRuleState[ruleIndex], aliases };
      setCapabilityRuleState(capabilityRuleState);
      markDirty();
    });

    // ── Navigation ────────────────────────────────────────────
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
      if (target) target.click();
    }

    // ── Sliders ───────────────────────────────────────────────
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

    // ── Save Management ───────────────────────────────────────
    const stickySaveBar = document.getElementById('sticky_save_bar');
    const saveAllBtn = document.getElementById('save_all_btn');
    const globalStatus = document.getElementById('global_save_status');

    document.querySelectorAll('input, select, textarea').forEach(el => {
      if (el.id === 'capability_matrix_filter' || el.classList.contains('is-readonly') || el.type === 'hidden') return;
      el.addEventListener('change', markDirty);
      if (el.tagName === 'TEXTAREA' || ['text', 'time', 'number', 'password', 'search'].includes(el.type)) {
        el.addEventListener('input', markDirty);
      }
    });

    document.getElementById('discard_changes_btn')?.addEventListener('click', () => {
      window.location.reload();
    });

    async function saveAll() {
      if (!saveAllBtn) return;
      saveAllBtn.disabled = true;
      saveAllBtn.textContent = 'Saving...';
      showInlineStatus(globalStatus, 'Saving changes...', 'loading');
      try {
        const profile = collectProfile();
        const agentSettings = collectAgentSettings();

        const agentResponse = await fetch('/api/agent-settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(agentSettings),
        });
        const agentPayload = await agentResponse.json().catch(() => ({}));
        if (!agentResponse.ok) {
          throw new Error(agentPayload.error || 'Could not save alert settings.');
        }

        const profileResponse = await fetch('/api/profile', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(profile),
        });
        const profilePayload = await profileResponse.json().catch(() => ({}));
        if (!profileResponse.ok) {
          throw new Error(profilePayload.error || 'Profile save failed after alert settings were saved.');
        }

        fillAgentSettings(agentPayload);
        fillForm(profilePayload);
        initSliders();
        clearDirty();
        showInlineStatus(globalStatus, 'All changes saved.', 'ok');
        showStatus('All settings saved successfully.', 'ok');
      } catch (err) {
        showInlineStatus(globalStatus, err?.message || 'Could not save all settings.', 'error');
        showStatus(err?.message || 'Could not save all settings.', 'error');
      } finally {
        saveAllBtn.disabled = false;
        saveAllBtn.textContent = 'Save All Changes';
      }
    }

    saveAllBtn?.addEventListener('click', saveAll);
    Promise.all([
      loadProfile(),
      loadAgentSettings(),
      loadRunStats(),
      loadReviewData(),
      loadRunStatus(),
    ]).then(() => {
        initSliders();
        suppressDirtyTracking = false;
        clearDirty();
    }).catch(error => showStatus(error.message, 'error'));

  
