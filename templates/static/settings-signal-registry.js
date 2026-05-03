    let _srData = null;
    let _srLoaded = false;
    let _srSearch = '';
    let _srSort = 'recently_updated';
    let _srCategories = [];
    const _srBusyKeys = new Set();
    const _srInlineStatus = {};

    function srSignalKey(signal) {
      return String(signal.normalized_key || signal.signal || '').trim().toLowerCase();
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

    function srCategoryLabel(category) {
      const entry = srCategoryOptions().find(item => item.key === category);
      return entry?.label || category.replace(/_/g, ' ');
    }

    function srTimestampValue(signal) {
      const history = Array.isArray(signal?.history) ? signal.history : [];
      const latest = history.length ? history[history.length - 1] : null;
      const raw = String(latest?.timestamp || '').trim();
      const parsed = raw ? Date.parse(raw) : NaN;
      return Number.isNaN(parsed) ? 0 : parsed;
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
      return all.filter(signal => srMatchesSearch(signal)).sort((left, right) => {
        if (_srSort === 'name_az') {
          return String(left.signal || '').localeCompare(String(right.signal || ''));
        }
        return srTimestampValue(right) - srTimestampValue(left)
          || String(left.signal || '').localeCompare(String(right.signal || ''));
      });
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
        const resp = await fetch('/api/signal-registry', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Could not save');
        const signals = Array.isArray(_srData?.signals) ? _srData.signals : [];
        const index = signals.findIndex(signal => srSignalKey(signal) === key);
        if (index >= 0 && data.signal) {
          signals[index] = data.signal;
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
      const categoryOptions = srCategoryOptions();
      const visible = srFilteredSignals();
      const cardsHtml = visible.length === 0
        ? '<p class="help signal-empty">No signals match the current view.</p>'
        : visible.map(signal => {
            const key = srSignalKey(signal);
            const aliases = srSignalAliases(signal);
            const category = srSignalCategory(signal);
            const source = srSignalSource(signal);
            const knowledge = srSignalKnowledge(signal);
            const context = srSignalContext(signal);
            const evidence = srSignalEvidence(signal);
            const inlineState = srInlineState(key);
            const isBusy = _srBusyKeys.has(key);
            const history = Array.isArray(signal.history) ? signal.history : [];
            const addedAt = history.find(entry => String(entry?.action || '').toLowerCase() === 'added') || history[0] || null;
            const timestamp = String(addedAt?.timestamp || '').trim();            
            const statusText = inlineState?.text || '';
            const detailLines = [];
            if (source) detailLines.push(`Source: ${source}`);
            if (knowledge) detailLines.push(`Knowledge match: ${knowledge}`);
            if (srSignalNeedsReview(signal)) detailLines.push('Needs review');
            if (timestamp) detailLines.push(`First seen: ${new Date(timestamp).toLocaleString()}`);
            if (context.length) {
              detailLines.push(`Context: ${context.join(' | ')}`);
            }
            if (evidence.length) {
              detailLines.push(`Evidence: ${evidence.join(' | ')}`);
            }
            return `
<article class="signal-row" data-sr-key="${escapeHtml(key)}">
  <div class="signal-row-top">
    <div class="signal-row-headline">
      <div class="signal-row-title">
        <h3>${escapeHtml(signal.signal || 'Unnamed signal')}</h3>
        <details class="signal-context-drawer">
          <summary title="Signal context" aria-label="Signal context">(i)</summary>
          <div class="signal-context-panel">
            ${detailLines.length
              ? detailLines.map(line => `<p>${escapeHtml(line)}</p>`).join('')
              : '<p>No extra context recorded yet.</p>'}
          </div>
        </details>
      </div>
      ${aliases.length ? `<p class="signal-row-meta">Seen as: ${escapeHtml(aliases.join(', '))}</p>` : ''}
    </div>
    <div class="signal-row-actions">
      <select class="signal-category-select" data-sr-key="${escapeHtml(key)}"${isBusy ? ' disabled' : ''}>
        <option value="">Choose category</option>
        ${categoryOptions.map(option => `<option value="${escapeHtml(option.key)}"${category === option.key ? ' selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}
      </select>
      <button class="signal-action-btn signal-approve" type="button" data-sr-key="${escapeHtml(key)}"${isBusy || !category ? ' disabled' : ''} title="Approve" aria-label="Approve">âœ“</button>
      <button class="signal-action-btn signal-remove" type="button" data-sr-key="${escapeHtml(key)}"${isBusy ? ' disabled' : ''} title="Remove" aria-label="Remove">Ã—</button>
    </div>
  </div>
  <div class="signal-row-footer">
    <span class="signal-inline-status${inlineState ? ` is-${escapeHtml(inlineState.kind)}` : ''}">${escapeHtml(statusText)}</span>
  </div>
</article>`;
          }).join('');

      panel.innerHTML = `
<div class="sr-hero">
  <p class="sr-hero-copy">Review extracted signals, then approve or remove each item.</p>
</div>
<div class="sr-toolbar">
  <input id="sr_search" class="sr-search" type="search" value="${escapeHtml(_srSearch)}" placeholder="Search signals">
  <select id="sr_sort" class="sr-select">
    <option value="recently_updated"${_srSort === 'recently_updated' ? ' selected' : ''}>Recently updated</option>
    <option value="name_az"${_srSort === 'name_az' ? ' selected' : ''}>A-Z</option>
  </select>
</div>
<div class="sr-list">${cardsHtml}</div>`;

      panel.querySelector('#sr_search')?.addEventListener('input', event => {
        const cursor = typeof event.target.selectionStart === 'number'
          ? event.target.selectionStart
          : String(event.target.value || '').length;
        _srSearch = String(event.target.value || '').trim().toLowerCase();
        renderSignalRegistry();
        const nextInput = panel.querySelector('#sr_search');
        if (nextInput) {
          nextInput.focus();
          nextInput.setSelectionRange(cursor, cursor);
        }
      });

      panel.querySelector('#sr_sort')?.addEventListener('change', event => {
        _srSort = String(event.target.value || 'recently_updated');
        renderSignalRegistry();
      });

      panel.querySelectorAll('.signal-category-select').forEach(select => {
        select.addEventListener('change', async () => {
          const key = select.dataset.srKey || '';
          await srPatchSignal(key, { key, category: String(select.value || '').trim() }, 'Category saved');
        });
      });

      panel.querySelectorAll('.signal-approve').forEach(button => {
        button.addEventListener('click', async () => {
          const key = button.dataset.srKey || '';
          const signal = all.find(item => srSignalKey(item) === key);
          if (!signal) return;
          const category = srSignalCategory(signal);
          await srPatchSignal(key, { key, action: 'approve', category }, 'Approved');
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
      panel.innerHTML = '<p class="help">Loading learning inbox...</p>';
      try {
        const resp = await fetch('/api/signal-registry');
        if (!resp.ok) throw new Error('Could not load signal registry');
        _srData = await resp.json();
        renderSignalRegistry();
      } catch (err) {
        _srLoaded = false;
        panel.innerHTML = `<p class="help" style="color:var(--accent);">${err.message} - click Learning again to retry.</p>`;
      }
    }
    document.querySelector('.nav-item[data-section="section-signals"]')?.addEventListener('click', () => {
      if (!_srLoaded) {
        _srLoaded = true;
        loadSignalRegistry();
      }
    });

