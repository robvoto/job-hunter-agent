import { escapeHtml } from '../shared/settings-utils.js';

    let _srData = null;
    let _srLoaded = false;
    let _srSearch = '';
    let _srSearchDraft = '';
    let _srSearchTimer = null;
    let _srSort = 'recently_updated';
    let _srFilter = 'all';
    let _srCategories = [];
    let _srPatternCategories = [];
    let _srCurrentPage = 1;
    const _srItemsPerPage = 50;
    const _srSearchDebounceMs = 180;
    const _srBusyKeys = new Set();
    const _srInlineStatus = {};

    function srSignalKey(signal) {
      return String(signal.normalized_key || signal.signal || '').trim().toLowerCase();
    }

    function srResizeSignalValueInput(input) {
      if (!input) return;
      input.style.height = 'auto';
      input.style.height = `${input.scrollHeight}px`;
    }

    function srResizeSignalValueInputs() {
      const panel = document.getElementById('signal_registry_panel');
      panel?.querySelectorAll('.signal-value-input').forEach(srResizeSignalValueInput);
    }

    function srSignalCategory(signal) {
      return String(signal?.category || signal?.suggested_category || '').trim();
    }

    function srSignalSource(signal) {
      return String(signal?.source || '').trim();
    }

    function srSignalKnowledge(signal) {
      return String(signal?.knowledge_match || '').trim();
    }

    function srSignalContext(signal) {
      const value = signal?.context;
      const items = Array.isArray(value)
        ? value
        : String(value || '').split(/\r?\n/);
      return items
        .map(item => String(item || '').trim())
        .filter(Boolean);
    }

    function srSignalEvidence(signal) {
      const value = signal?.evidence;
      const items = Array.isArray(value)
        ? value
        : String(value || '').split(/\r?\n/);
      return items
        .map(item => String(item || '').trim())
        .filter(Boolean);
    }

    function srSignalNeedsReview(signal) {
      return Boolean(signal?.needs_review);
    }

    function srSignalAliases(signal) {
      const canonical = String(signal?.signal || '').trim().toLowerCase();
      const values = Array.isArray(signal?.original_texts) ? signal.original_texts : [];
      const deduped = [];
      values.forEach(value => {
        const cleaned = String(value || '').trim();
        if (!cleaned) return;
        const normalized = cleaned.toLowerCase();
        if (normalized === canonical) return;
        if (deduped.some(item => item.toLowerCase() === normalized)) return;
        deduped.push(cleaned);
      });
      return deduped;
    }

    function srCategoryOptions() {
      return Array.isArray(_srCategories) ? _srCategories : [];
    }

    function srCategoryMetadata(category) {
      return srCategoryOptions().find(item => item.key === category) || null;
    }

    /* An LLM suggestion may preselect the visible selector, but approval always submits the human-visible selected value. */
    function srRequirementTypeOptions(category) {
      const meta = srCategoryMetadata(category);
      return Array.isArray(meta?.requirement_type_options) ? meta.requirement_type_options : [];
    }

    function srRequirementTypeValue(signal, options) {
      const suggestedValues = Array.isArray(signal?.suggested_values) ? signal.suggested_values : [];
      const suggested = String(suggestedValues[0] || '').trim().toLowerCase();
      return options.some(option => String(option?.value || '').trim() === suggested) ? suggested : '';
    }

    function srRequirementTypeControlHtml(signal, category, isBusy) {
      const meta = srCategoryMetadata(category);
      const options = srRequirementTypeOptions(category);
      if (!meta || !options.length) return '';
      const selectedValue = srRequirementTypeValue(signal, options);
      return `
    <label class="signal-requirement-type-field">
      <span class="signal-requirement-type-label">${escapeHtml(meta.requirement_type_label || '')}</span>
      <select class="signal-requirement-type-select jh-select" data-sr-key="${escapeHtml(srSignalKey(signal))}"${selectedValue ? '' : ' data-sr-unselected="true"'}${isBusy ? ' disabled' : ''} aria-label="${escapeHtml(meta.requirement_type_label || '')}">
        ${options.map(option => `<option value="${escapeHtml(option.value)}"${String(option.value) === selectedValue ? ' selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}
      </select>
    </label>`;
    }

    function srIsPatternCategory(category) {
      return Array.isArray(_srPatternCategories) && _srPatternCategories.includes(category);
    }

    function srPatternValueValid(category, value) {
      if (!srIsPatternCategory(category)) return true;
      return String(value || '').includes('[*]');
    }

    function srHelpDrawerHtml(summaryLabel, ariaLabel, bodyHtml, drawerClass = '') {
      return `
        <details class="signal-help-drawer ${escapeHtml(drawerClass)}">
          <summary title="${escapeHtml(ariaLabel)}" aria-label="${escapeHtml(ariaLabel)}">${escapeHtml(summaryLabel)}</summary>
          <div class="signal-help-panel">
            ${bodyHtml}
          </div>
        </details>`;
    }

    function srCategoryHelpHtml(categoryKey) {
      const meta = srCategoryMetadata(categoryKey);
      if (!meta) return '';
      const hasWarning = meta.warning && String(meta.warning).trim();
      const examples = Array.isArray(meta.examples) ? meta.examples : [];

      let body = `<div class="sr-category-help">`;

      if (meta.description) {
        body += `<p class="sr-help-description">${escapeHtml(meta.description)}</p>`;
      }

      if (examples.length > 0) {
        body += `<div class="sr-help-examples">
          <strong>Examples:</strong>
          <ul>
            ${examples.map(ex => `<li>${escapeHtml(ex)}</li>`).join('')}
          </ul>
        </div>`;
      }

      if (hasWarning) {
        body += `<div class="sr-help-warning">${escapeHtml(meta.warning)}</div>`;
      }

      body += `</div>`;
      return srHelpDrawerHtml('ii', 'Title meaning', body, 'sr-category-help-drawer');
    }

    function srSignalContextHtml(signal) {
      const aliases = srSignalAliases(signal);
      const source = srSignalSource(signal);
      const knowledge = srSignalKnowledge(signal);
      const context = srSignalContext(signal);
      const evidence = srSignalEvidence(signal);
      const parts = [];
      if (aliases.length) {
        parts.push(`<div class="signal-context-section"><strong>Seen as</strong><ul>${aliases.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul></div>`);
      }
      if (source) {
        parts.push(`<div class="signal-context-section"><strong>Source</strong><p>${escapeHtml(source)}</p></div>`);
      }
      if (knowledge) {
        parts.push(`<div class="signal-context-section"><strong>Match</strong><p>${escapeHtml(knowledge)}</p></div>`);
      }
      if (srSignalNeedsReview(signal)) {
        parts.push(`<div class="signal-context-section"><strong>Status</strong><p>Needs review</p></div>`);
      }
      if (context.length) {
        parts.push(`<div class="signal-context-section"><strong>Context</strong><ul>${context.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul></div>`);
      }
      if (evidence.length) {
        parts.push(`<div class="signal-context-section"><strong>Evidence</strong><ul>${evidence.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul></div>`);
      }
      const body = parts.length
        ? parts.join('')
        : '<div class="signal-context-section"><p>No extra context recorded yet.</p></div>';
      return srHelpDrawerHtml('i', 'Signal context', body, 'signal-context-drawer');
    }

    function srRemoveSignalFromData(key) {
      const signals = Array.isArray(_srData?.signals) ? _srData.signals : [];
      const index = signals.findIndex(signal => srSignalKey(signal) === key);
      if (index >= 0) {
        signals.splice(index, 1);
      }
    }

    function srTimestampValue(signal) {
      const history = Array.isArray(signal?.history) ? signal.history : [];
      const latest = history.length ? history[history.length - 1] : null;
      const raw = String(latest?.timestamp || '').trim();
      const parsed = raw ? Date.parse(raw) : NaN;
      return Number.isNaN(parsed) ? 0 : parsed;
    }

    function srMatchesFilter(signal) {
      if (_srFilter === 'needs_review') {
        return srSignalNeedsReview(signal);
      }
      if (_srFilter === 'uncategorized') {
        return !srSignalCategory(signal);
      }
      return true;
    }

    function srMatchesSearch(signal) {
      if (!_srSearch) return true;
      const searchText = [
        signal.signal || '',
        ...(Array.isArray(signal.original_texts) ? signal.original_texts : []),
        srSignalCategory(signal),
        srSignalSource(signal),
        srSignalKnowledge(signal),
        ...(srSignalContext(signal)),
        ...(srSignalEvidence(signal)),
      ].join(' ').toLowerCase();
      return searchText.includes(_srSearch);
    }

    function srFilteredSignals() {
      const all = Array.isArray(_srData?.signals) ? _srData.signals : [];
      return all.filter(signal => srMatchesFilter(signal) && srMatchesSearch(signal)).sort((left, right) => {
        if (_srSort === 'name_az') {
          return String(left.signal || '').localeCompare(String(right.signal || ''));
        }
        return srTimestampValue(right) - srTimestampValue(left)
          || String(left.signal || '').localeCompare(String(right.signal || ''));
      });
    }

    function srPageCount(totalItems) {
      return Math.max(Math.ceil(totalItems / _srItemsPerPage), 1);
    }

    function srCommitSearch(value) {
      _srSearch = String(value || '').trim().toLowerCase();
      _srCurrentPage = 1;
      renderSignalRegistry();
    }

    function srInlineState(key) {
      return _srInlineStatus[key] || null;
    }

    function srSetInlineState(key, text, kind = 'info', autoClearMs = 0) {
      _srInlineStatus[key] = { text, kind };
      renderSignalRegistry();
      if (autoClearMs > 0) {
        window.setTimeout(() => {
          const current = _srInlineStatus[key];
          if (current && current.text === text && current.kind === kind) {
            delete _srInlineStatus[key];
            renderSignalRegistry();
          }
        }, autoClearMs);
      }
    }

    async function srPatchSignal(key, payload, successText = 'Saved') {
      if (_srBusyKeys.has(key)) return;
      _srBusyKeys.add(key);
      srSetInlineState(key, 'Saving...', 'info');
      try {
        const resp = await jobHunterFetch('/api/signal-registry', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Could not save');
        const signals = Array.isArray(_srData?.signals) ? _srData.signals : [];
        if (payload.action === 'ignore' || payload.action === 'approve') {
          srRemoveSignalFromData(key);
        } else {
          const index = signals.findIndex(signal => srSignalKey(signal) === key);
          if (index >= 0 && data.signal) {
            signals[index] = data.signal;
          }
        }
        srSetInlineState(key, successText, 'ok', 1400);
      } catch (error) {
        srSetInlineState(key, error.message || 'Could not save', 'error');
        showStatus(error.message || 'Could not save signal review.', 'error');
      } finally {
        _srBusyKeys.delete(key);
        renderSignalRegistry();
      }
    }

    function renderSignalRegistry() {
      const panel = document.getElementById('signal_registry_panel');
      if (!panel || !_srData) return;
      const all = Array.isArray(_srData.signals) ? _srData.signals : [];
      _srCategories = Array.isArray(_srData.categories) ? _srData.categories : [];
      _srPatternCategories = Array.isArray(_srData.pattern_categories) ? _srData.pattern_categories : [];
      const categoryOptions = srCategoryOptions();
      const visible = srFilteredSignals();
      const totalPages = srPageCount(visible.length);
      _srCurrentPage = Math.min(Math.max(_srCurrentPage, 1), totalPages);
      const startIndex = (_srCurrentPage - 1) * _srItemsPerPage;
      const endIndex = _srCurrentPage * _srItemsPerPage;
      const visibleRows = visible.slice(startIndex, endIndex);
      const cardsHtml = visibleRows.length === 0
        ? '<p class="help signal-empty">No signals match the current view.</p>'
        : visibleRows.map(signal => {
            const key = srSignalKey(signal);
            const category = srSignalCategory(signal);
            const inlineState = srInlineState(key);
            const isBusy = _srBusyKeys.has(key);
            const statusText = inlineState?.text || '';
            const statusClass = inlineState ? ` is-status-${escapeHtml(inlineState.kind)}` : '';
            const isPatternCat = srIsPatternCategory(category);
            const currentValue = signal.signal || '';
            const patternValid = srPatternValueValid(category, currentValue);
            const requirementTypeOptions = srRequirementTypeOptions(category);
            const requirementType = srRequirementTypeValue(signal, requirementTypeOptions);
            const approveDisabled = isBusy || !category || !patternValid
              || (requirementTypeOptions.length > 0 && !requirementType);
            return `
<article class="signal-row${statusClass}" data-sr-key="${escapeHtml(key)}">
  <div class="signal-row-title">
    <div class="signal-value-field">
      <textarea class="signal-value-input" data-sr-key="${escapeHtml(key)}" rows="2" placeholder="Signal value"${isBusy ? ' disabled' : ''} aria-label="Signal value">${escapeHtml(currentValue)}</textarea>
      ${isPatternCat ? '<span class="signal-pattern-hint">Use [*] as wildcard — e.g. <code>Head of [*]</code></span>' : ''}
    </div>
    ${statusText ? `<span class="signal-inline-status${inlineState ? ` is-${escapeHtml(inlineState.kind)}` : ''}">${escapeHtml(statusText)}</span>` : ''}
    ${srSignalContextHtml(signal)}
  </div>
  <div class="signal-category-wrapper">
    <div class="signal-category-control">
      <select class="signal-category-select jh-select" data-sr-key="${escapeHtml(key)}"${isBusy ? ' disabled' : ''}>
        <option value="">Choose category</option>
        ${categoryOptions.map(option => `<option value="${escapeHtml(option.key)}"${category === option.key ? ' selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}
      </select>
      ${category ? srCategoryHelpHtml(category) : ''}
    </div>
    ${srRequirementTypeControlHtml(signal, category, isBusy)}
  </div>
  <div class="signal-row-actions">
    <button class="signal-action-btn signal-approve" type="button" data-sr-key="${escapeHtml(key)}"${approveDisabled ? ' disabled' : ''} title="Approve" aria-label="Approve">&#10003;</button>
    <button class="signal-action-btn signal-remove" type="button" data-sr-key="${escapeHtml(key)}"${isBusy ? ' disabled' : ''} title="Remove" aria-label="Remove">&#215;</button>
  </div>
</article>`;
          }).join('');
      const pagerHtml = visible.length > _srItemsPerPage
        ? `
<div class="sr-pagination">
  <button class="sr-page-button" type="button" data-sr-page-direction="prev"${_srCurrentPage <= 1 ? ' disabled' : ''}>Previous</button>
  <div class="sr-page-number-group">
    ${Array.from({ length: totalPages }, (_, index) => {
      const page = index + 1;
      return `<button class="sr-page-button sr-page-number${page === _srCurrentPage ? ' is-active' : ''}" type="button" data-sr-page="${page}"${page === _srCurrentPage ? ' aria-current="page"' : ''}>${page}</button>`;
    }).join('')}
  </div>
  <button class="sr-page-button" type="button" data-sr-page-direction="next"${_srCurrentPage >= totalPages ? ' disabled' : ''}>Next</button>
</div>`
        : '';

      panel.innerHTML = `
<div class="sr-hero">
  <p class="sr-hero-copy">Review extracted signals, then approve or remove each item.</p>
</div>
<div class="sr-toolbar">
  <input id="sr_search" class="sr-search" type="search" value="${escapeHtml(_srSearchDraft || _srSearch)}" placeholder="Search signals">
  <select id="sr_sort" class="sr-select jh-select">
    <option value="recently_updated"${_srSort === 'recently_updated' ? ' selected' : ''}>Recently updated</option>
    <option value="name_az"${_srSort === 'name_az' ? ' selected' : ''}>A-Z</option>
  </select>
  <select id="sr_filter" class="sr-select jh-select" aria-label="Filter signals">
    <option value="all"${_srFilter === 'all' ? ' selected' : ''}>All Signals</option>
    <option value="needs_review"${_srFilter === 'needs_review' ? ' selected' : ''}>Needs Review Only</option>
    <option value="uncategorized"${_srFilter === 'uncategorized' ? ' selected' : ''}>Uncategorized Only</option>
  </select>
</div>
<div class="sr-list">${cardsHtml}${pagerHtml}</div>`;

      panel.querySelectorAll('.signal-requirement-type-select[data-sr-unselected="true"]').forEach(select => {
        select.selectedIndex = -1;
      });

      panel.querySelector('#sr_search')?.addEventListener('input', event => {
        const cursor = typeof event.target.selectionStart === 'number'
          ? event.target.selectionStart
          : String(event.target.value || '').length;
        _srSearchDraft = String(event.target.value || '');
        if (_srSearchTimer) {
          window.clearTimeout(_srSearchTimer);
        }
        _srSearchTimer = window.setTimeout(() => {
          _srSearchTimer = null;
          srCommitSearch(_srSearchDraft);
        }, _srSearchDebounceMs);
        window.requestAnimationFrame(() => {
          const nextInput = panel.querySelector('#sr_search');
          if (nextInput) {
            nextInput.focus();
            nextInput.setSelectionRange(cursor, cursor);
          }
        });
      });

      panel.querySelector('#sr_sort')?.addEventListener('change', event => {
        _srSort = String(event.target.value || 'recently_updated');
        _srCurrentPage = 1;
        renderSignalRegistry();
      });

      panel.querySelector('#sr_filter')?.addEventListener('change', event => {
        _srFilter = String(event.target.value || 'all');
        _srCurrentPage = 1;
        renderSignalRegistry();
      });

      panel.querySelectorAll('[data-sr-page], [data-sr-page-direction]').forEach(button => {
        button.addEventListener('click', () => {
          if (button.dataset.srPage) {
            _srCurrentPage = Number(button.dataset.srPage || 1);
          } else if (button.dataset.srPageDirection === 'prev') {
            _srCurrentPage -= 1;
          } else if (button.dataset.srPageDirection === 'next') {
            _srCurrentPage += 1;
          }
          renderSignalRegistry();
        });
      });

      panel.querySelectorAll('.signal-category-select').forEach(select => {
        select.addEventListener('change', async () => {
          const key = select.dataset.srKey || '';
          const newCategory = String(select.value || '').trim();
          const wrapper = select.closest('.signal-category-wrapper');

          // Update help panel dynamically
          if (wrapper) {
            const existingHelp = wrapper.querySelector('.sr-category-help');
            const existingDrawer = wrapper.querySelector('.sr-category-help-drawer');
            if (existingHelp) {
              existingHelp.remove();
            }
            if (existingDrawer) {
              existingDrawer.remove();
            }
            if (newCategory) {
              const helpHtml = srCategoryHelpHtml(newCategory);
              if (helpHtml) {
                select.insertAdjacentHTML('afterend', helpHtml);
              }
            }
          }

          // Update approve button state and pattern hint
          const article = select.closest('.signal-row');
          if (article) {
            const valueInput = article.querySelector('.signal-value-input');
            const currentVal = valueInput ? valueInput.value.trim() : '';
            const approveBtn = article.querySelector('.signal-approve');
            if (approveBtn) {
              const requirementTypeSelect = article.querySelector('.signal-requirement-type-select');
              approveBtn.disabled = !newCategory || !srPatternValueValid(newCategory, currentVal)
                || (srRequirementTypeOptions(newCategory).length > 0 && !requirementTypeSelect?.value);
            }
            // Show/hide pattern hint when category changes
            const existingHint = article.querySelector('.signal-pattern-hint');
            if (existingHint) existingHint.remove();
            if (srIsPatternCategory(newCategory) && valueInput) {
              valueInput.insertAdjacentHTML('afterend', '<span class="signal-pattern-hint">Use [*] as wildcard — e.g. <code>Head of [*]</code></span>');
            }
          }

          await srPatchSignal(key, { key, category: newCategory }, 'Category saved');
        });
      });

      panel.querySelectorAll('.signal-value-input').forEach(input => {
        srResizeSignalValueInput(input);
        input.addEventListener('input', () => {
          srResizeSignalValueInput(input);
          const key = input.dataset.srKey || '';
          const article = input.closest('.signal-row');
          if (!article) return;
          const signal = all.find(item => srSignalKey(item) === key);
          const category = signal ? srSignalCategory(signal) : '';
          const approveBtn = article.querySelector('.signal-approve');
          if (approveBtn) {
            const requirementTypeSelect = article.querySelector('.signal-requirement-type-select');
            approveBtn.disabled = !category || !srPatternValueValid(category, input.value.trim())
              || (srRequirementTypeOptions(category).length > 0 && !requirementTypeSelect?.value);
          }
        });
      });

      panel.querySelectorAll('.signal-requirement-type-select').forEach(select => {
        select.addEventListener('change', () => {
          const article = select.closest('.signal-row');
          if (!article) return;
          const signal = all.find(item => srSignalKey(item) === (select.dataset.srKey || ''));
          const category = signal ? srSignalCategory(signal) : '';
          const valueInput = article.querySelector('.signal-value-input');
          const approveBtn = article.querySelector('.signal-approve');
          if (approveBtn) {
            approveBtn.disabled = !category
              || !srPatternValueValid(category, valueInput?.value.trim() || '')
              || !select.value;
          }
        });
      });

      panel.querySelectorAll('.signal-approve').forEach(button => {
        button.addEventListener('click', async () => {
          const key = button.dataset.srKey || '';
          const signal = all.find(item => srSignalKey(item) === key);
          if (!signal) return;
          const category = srSignalCategory(signal);
          const article = button.closest('.signal-row');
          const valueInput = article ? article.querySelector('.signal-value-input') : null;
          const value = valueInput ? valueInput.value.trim() : (signal.signal || '');
          if (!srPatternValueValid(category, value)) return;
          const requirementTypeOptions = srRequirementTypeOptions(category);
          const requirementTypeSelect = article?.querySelector('.signal-requirement-type-select');
          const classification = requirementTypeSelect?.value.trim() || '';
          if (requirementTypeOptions.length > 0 && !classification) return;
          const payload = { key, action: 'approve', category, value };
          if (requirementTypeOptions.length > 0) {
            payload.classification = classification;
          }
          await srPatchSignal(key, payload, 'Approved');
        });
      });

      panel.querySelectorAll('.signal-remove').forEach(button => {
        button.addEventListener('click', async () => {
          const key = button.dataset.srKey || '';
          await srPatchSignal(key, { key, action: 'ignore' }, 'Ignored');
        });
      });
    }

    async function loadSignalRegistry() {
      const panel = document.getElementById('signal_registry_panel');
      if (!panel) return;
      panel.innerHTML = '<p class="help">Loading signals inbox...</p>';
      try {
        const resp = await jobHunterFetch('/api/signal-registry');
        if (!resp.ok) throw new Error('Could not load signal registry');
        _srData = await resp.json();
        _srSearchDraft = _srSearch;
        renderSignalRegistry();
      } catch (err) {
        _srLoaded = false;
        panel.innerHTML = `<p class="help" style="color:var(--accent);">${err.message} - click Signals again to retry.</p>`;
      }
    }
    function maybeLoadSignalRegistry() {
      if (_srLoaded) return;
      _srLoaded = true;
      loadSignalRegistry();
    }

    let _srInitialized = false;

    export function initSignalRegistry() {
      if (_srInitialized) return;
      _srInitialized = true;
      window.addEventListener('resize', srResizeSignalValueInputs);
      const learningNav = document.querySelector('.nav-item[data-section="section-learning"]');
      learningNav?.addEventListener('click', maybeLoadSignalRegistry);
      if (learningNav?.classList.contains('is-active')) {
        maybeLoadSignalRegistry();
      }
    }

    initSignalRegistry();
