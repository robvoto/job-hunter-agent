(function() {
    // This template is served two ways: injected into the live /workspace page
    // (same-origin, authenticated session cookie + CSRF token available), and
    // written to disk as a standalone workspace_results.html snapshot that a
    // user can double-click and open directly (file:// origin). A file:// page
    // has no session cookie and any cross-origin fetch to the API gets blocked
    // by CORS before it reaches the server -- previously this rewrote API calls
    // to hit http://127.0.0.1:8765 directly, which still failed CORS (no
    // Access-Control-Allow-Origin for a "null" file:// origin) and surfaced as
    // an opaque "Failed to fetch" with no trace in the server logs. Static
    // exports are now read-only: writes are blocked client-side with a message
    // pointing at the live workspace instead of being attempted at all.
    const API_BASE_URL = '';
    const REVIEW_API_URL = `${API_BASE_URL}/api/review`;
    const JOB_HISTORY_API_URL = `${API_BASE_URL}/api/job-history`;
    const WORKSPACE_CONTEXT = window.__JOB_HUNTER_WORKSPACE__ || {};
    const IS_STATIC_EXPORT = window.location.protocol === 'file:';
    const LIVE_WORKSPACE_URL = String(WORKSPACE_CONTEXT.liveWorkspaceUrl || '').trim();
    const STATIC_EXPORT_MESSAGE = LIVE_WORKSPACE_URL
      ? `This is a saved copy of your workspace and can't save changes. Open the live workspace to apply, hide, or block jobs: ${LIVE_WORKSPACE_URL}`
      : "This is a saved copy of your workspace and can't save changes. Open Job Hunter in your browser to apply, hide, or block jobs.";

    function blockStaticExportWrite(statusEl) {
      if (!IS_STATIC_EXPORT) {
        return false;
      }
      if (statusEl) {
        statusEl.textContent = STATIC_EXPORT_MESSAGE;
      } else {
        window.alert(STATIC_EXPORT_MESSAGE);
      }
      return true;
    }

    function showStaticExportBanner() {
      if (!IS_STATIC_EXPORT) {
        return;
      }
      const main = document.querySelector('.page') || document.body;
      if (!main || document.getElementById('static_export_banner')) {
        return;
      }
      const banner = document.createElement('div');
      banner.id = 'static_export_banner';
      banner.className = 'workspace-status-message';
      banner.setAttribute('role', 'status');
      banner.textContent = STATIC_EXPORT_MESSAGE;
      main.insertBefore(banner, main.firstChild);
    }
    const WORKSPACE_RUN_ID = String(WORKSPACE_CONTEXT.runId || '').trim() || 'workspace';
    const WORKSPACE_FILTERS_KEY = `jobHunter.workspace.filters.${WORKSPACE_RUN_ID}`;
    const WORKSPACE_PAGINATION_KEY = `jobHunter.workspace.pagination.${WORKSPACE_RUN_ID}`;
    const RESULTS_HELPER_DISMISSED_KEY = 'jobHunter.workspace.resultsHelperDismissed';
    const REJECTION_FIRST_USE_KEY = 'jobHunter.workspace.rejectionFirstUseSeen';
    const sortSelect = document.getElementById('sort_select');
    const pageSizeSelect = document.getElementById('page_size_select');
    const scopeFilter = document.getElementById('scope_filter');
    const postedFilter = document.getElementById('posted_filter');
    const workTypeFilter = document.getElementById('work_type_filter');
    const workModeFilter = document.getElementById('work_mode_filter');
    const sectorFilter = document.getElementById('sector_filter');
    const scoreFilter = document.getElementById('score_filter');
    const quickFilterButtons = Array.from(document.querySelectorAll('[data-quick-filter]'));
    const moreFiltersButton = document.getElementById('workspace_more_filters');
    const moreFiltersContent = document.getElementById('workspace_more_filter_content');
    const sourceFilterButtons = Array.from(document.querySelectorAll('[data-source-filter]'));
    const DEFAULT_SCORE_FILTER_VALUE = WORKSPACE_CONTEXT.defaultScoreFilterValue || 55;
    const resetFiltersButton = document.getElementById('reset_workspace_filters');
    const resultsHelper = document.getElementById('results_helper');
    const dismissResultsHelperButton = document.getElementById('dismiss_results_helper');
    const workspaceTabs = Array.from(document.querySelectorAll('[data-workspace-target]'));
    const workspacePanels = Array.from(document.querySelectorAll('[data-workspace-panel]'));
    const paginationState = {};

    function showResultsHelperIfNeeded() {
      if (!resultsHelper) {
        return;
      }
      try {
        if (window.localStorage.getItem(RESULTS_HELPER_DISMISSED_KEY) === '1') {
          return;
        }
      } catch (error) {
      }
      resultsHelper.hidden = false;
    }

    function dismissResultsHelper() {
      if (resultsHelper) {
        resultsHelper.hidden = true;
      }
      try {
        window.localStorage.setItem(RESULTS_HELPER_DISMISSED_KEY, '1');
      } catch (error) {
      }
    }

    function updateRejectionFirstUseNote(exampleTerm = '') {
      const note = document.getElementById('rejection-first-use');
      const body = document.getElementById('rejection-first-use-body');
      if (!note || !body) {
        return;
      }
      const example = String(exampleTerm || '').trim() || 'payroll';
      body.textContent = `Example: if you save "${example}", future jobs are filtered only when ${example} looks required, not when it is just preferred. To block any mention, use global description blockers in Settings.`;
      note.hidden = false;
      note.open = true;
      try {
        if (window.localStorage.getItem(REJECTION_FIRST_USE_KEY) === '1') {
          note.open = false;
          return;
        }
        window.localStorage.setItem(REJECTION_FIRST_USE_KEY, '1');
      } catch (error) {
      }
    }

    function getActiveWorkspace() {
      return workspaceTabs.find(tab => tab.classList.contains('is-active'))?.dataset.workspaceTarget || 'potential';
    }

    function setActiveWorkspace(workspace, updateHash = true, resetPages = true) {
      const allowed = new Set(['potential', 'applied', 'hidden']);
      const nextWorkspace = allowed.has(workspace) ? workspace : 'potential';

      for (const tab of workspaceTabs) {
        tab.classList.toggle('is-active', (tab.dataset.workspaceTarget || '') === nextWorkspace);
      }
      for (const panel of workspacePanels) {
        const panelWorkspace = panel.dataset.workspacePanel || 'potential';
        if (panelWorkspace === nextWorkspace) {
          panel.removeAttribute('hidden');
        } else {
          panel.setAttribute('hidden', '');
        }
      }

      if (updateHash) {
        const targetHash = nextWorkspace === 'potential' ? '#potential' : `#${nextWorkspace}`;
        if (window.location.hash !== targetHash) {
          window.history.replaceState(null, '', targetHash);
        }
      }

      if (resetPages) {
        resetPagination();
      }
      applyWorkspaceControls();
    }

    function saveWorkspaceFilters() {
      const filters = {
        sort: sortSelect?.value,
        pageSize: pageSizeSelect?.value,
        scope: scopeFilter?.value,
        posted: postedFilter?.value,
        workType: workTypeFilter?.value,
        workMode: workModeFilter?.value,
        sector: sectorFilter?.value,
        score: scoreFilter?.value,
        quick: Object.fromEntries(quickFilterButtons.map(button => [button.dataset.quickFilter, button.getAttribute('aria-pressed') === 'true'])),
        sources: sourceFilterButtons.filter(button => button.dataset.sourceFilter !== 'all' && button.getAttribute('aria-pressed') === 'true').map(button => button.dataset.sourceFilter),
      };
      try {
        window.localStorage.setItem(WORKSPACE_FILTERS_KEY, JSON.stringify(filters));
      } catch (e) {}
    }

    function setSelectValueIfAvailable(select, value) {
      if (!select || value === undefined || value === null || value === '') {
        return;
      }
      const normalized = String(value);
      if (Array.from(select.options).some(option => option.value === normalized)) {
        select.value = normalized;
      }
    }

    function loadWorkspaceFilters() {
      try {
        const saved = window.localStorage.getItem(WORKSPACE_FILTERS_KEY);
        if (!saved) return;
        const filters = JSON.parse(saved);
        
        setSelectValueIfAvailable(sortSelect, filters.sort);
        setSelectValueIfAvailable(pageSizeSelect, filters.pageSize);
        setSelectValueIfAvailable(scopeFilter, filters.scope);
        setSelectValueIfAvailable(postedFilter, filters.posted);
        setSelectValueIfAvailable(workTypeFilter, filters.workType);
        setSelectValueIfAvailable(workModeFilter, filters.workMode);
        setSelectValueIfAvailable(sectorFilter, filters.sector);
        setSelectValueIfAvailable(scoreFilter, filters.score);
        if (Array.isArray(filters.sources) && filters.sources.length) {
          for (const button of sourceFilterButtons) {
            const source = button.dataset.sourceFilter;
            button.setAttribute('aria-pressed', source !== 'all' && filters.sources.includes(source) ? 'true' : 'false');
          }
          sourceFilterButtons.find(button => button.dataset.sourceFilter === 'all')?.setAttribute('aria-pressed', 'false');
        }
        if (filters.quick && typeof filters.quick === 'object') {
          for (const button of quickFilterButtons) {
            button.setAttribute('aria-pressed', filters.quick[button.dataset.quickFilter] ? 'true' : 'false');
          }
        }
      } catch (e) {}
    }

    function saveWorkspacePagination() {
      try {
        window.localStorage.setItem(WORKSPACE_PAGINATION_KEY, JSON.stringify(paginationState));
      } catch (e) {}
    }

    function loadWorkspacePagination() {
      try {
        const saved = window.localStorage.getItem(WORKSPACE_PAGINATION_KEY);
        if (!saved) return;
        const parsed = JSON.parse(saved);
        if (!parsed || typeof parsed !== 'object') {
          return;
        }
        for (const [key, value] of Object.entries(parsed)) {
          const page = Number(value);
          if (Number.isFinite(page) && page >= 1) {
            paginationState[key] = page;
          }
        }
      } catch (e) {}
    }

    function resetWorkspaceFiltersToDefaults() {
      if (sortSelect) sortSelect.value = 'fit';
      if (pageSizeSelect) pageSizeSelect.value = '12';
      if (scopeFilter) scopeFilter.value = 'all';
      if (postedFilter) postedFilter.value = 'all';
      if (workTypeFilter) workTypeFilter.value = 'all';
      if (workModeFilter) workModeFilter.value = 'all';
      if (sectorFilter) sectorFilter.value = 'all';
      if (scoreFilter) {
        setSelectValueIfAvailable(scoreFilter, DEFAULT_SCORE_FILTER_VALUE);
      }
      for (const button of quickFilterButtons) {
        button.setAttribute('aria-pressed', 'false');
      }
      for (const button of sourceFilterButtons) {
        button.setAttribute('aria-pressed', button.dataset.sourceFilter === 'all' ? 'true' : 'false');
      }
      try {
        window.localStorage.removeItem(WORKSPACE_FILTERS_KEY);
        window.localStorage.removeItem(WORKSPACE_PAGINATION_KEY);
      } catch (e) {}
      resetPagination();
      applyWorkspaceControls();
    }

    function getVisibleCards() {
      return Array.from(document.querySelectorAll('.job-card'));
    }

    function resetPagination() {
      for (const key of Object.keys(paginationState)) {
        paginationState[key] = 1;
      }
      saveWorkspacePagination();
    }

    function applySectionPagination(section) {
      const grid = section.querySelector('.job-grid');
      const sectionId = section.dataset.sectionId || 'matches';
      const cards = grid ? Array.from(grid.querySelectorAll('.job-card')) : [];
      const matchingCards = cards.filter(card => card.dataset.matchesFilters !== '0');
      const pageSize = Number(pageSizeSelect?.value || 12);
      const totalPages = matchingCards.length ? Math.ceil(matchingCards.length / pageSize) : 0;

      if (!paginationState[sectionId]) {
        paginationState[sectionId] = 1;
      }
      paginationState[sectionId] = totalPages
        ? Math.min(Math.max(paginationState[sectionId], 1), totalPages)
        : 1;

      const currentPage = paginationState[sectionId];
      const startIndex = (currentPage - 1) * pageSize;
      const endIndex = startIndex + pageSize;

      cards.forEach(card => {
        card.hidden = true;
      });
      matchingCards.slice(startIndex, endIndex).forEach(card => {
        card.hidden = false;
      });

      const emptyState = section.querySelector('.empty-state');
      if (emptyState) {
        emptyState.hidden = matchingCards.length !== 0;
      }

      section.querySelectorAll('.pagination-page-label').forEach(pageLabel => {
        pageLabel.hidden = matchingCards.length === 0;
        pageLabel.textContent = matchingCards.length ? `Page ${currentPage} of ${totalPages}` : '';
      });

      section.querySelectorAll('.pagination-match-count').forEach(matchCountLabel => {
        matchCountLabel.textContent = `${matchingCards.length} matches`;
      });

      section.querySelectorAll('[data-page-direction="prev"]').forEach(prevButton => {
        prevButton.hidden = matchingCards.length === 0;
        prevButton.disabled = currentPage <= 1 || matchingCards.length === 0;
      });
      section.querySelectorAll('[data-page-direction="next"]').forEach(nextButton => {
        nextButton.hidden = matchingCards.length === 0;
        nextButton.disabled = currentPage >= totalPages || matchingCards.length === 0;
      });
      section.querySelectorAll('.results-pagination-footer').forEach(footer => {
        footer.hidden = totalPages <= 1;
      });
      saveWorkspacePagination();
    }

    function cardMatchesPotentialFilters(card, filters) {
      const cardScope = card.dataset.recordKind || 'current';
      if (!['current', 'saved'].includes(cardScope)) return false;
      if (card.dataset.reviewDismissed === '1') return false;

      const viewed = card.dataset.viewed === '1';
      const cardWorkType = (card.dataset.workType || '').toLowerCase();
      const cardWorkMode = (card.dataset.workMode || '').toLowerCase();
      const cardSector = (card.dataset.roleSector || 'unknown').toLowerCase();
      const cardScore = Number(card.dataset.fitScore || 0);
      const postedAge = Number(card.dataset.postedAge || 9999);
      const cardSource = (card.dataset.source || '').toLowerCase();
      const cardPostingChannel = (card.dataset.postingChannel || 'unknown').toLowerCase();
      const cardApplyMethod = (card.dataset.applyMethod || 'unknown').toLowerCase();

      if (filters.scopeMode === 'current' && cardScope !== 'current') return false;
      if (filters.scopeMode === 'saved' && cardScope !== 'saved') return false;
      if (filters.scopeMode === 'unseen' && viewed) return false;
      if (filters.scopeMode === 'viewed' && !viewed) return false;
      if (filters.postedLimit !== 'all' && postedAge > Number(filters.postedLimit)) return false;
      if (filters.workTypeValues && !filters.workTypeValues.includes(cardWorkType)) return false;
      if (filters.workMode !== 'all' && cardWorkMode !== filters.workMode) return false;
      if (filters.sector === 'public' && cardSector !== 'public') return false;
      if (filters.sector === 'private' && cardSector === 'public') return false;
      if (filters.scoreMode !== 'all' && cardScore < Number(filters.scoreMode)) return false;
      if (filters.quickNew && viewed) return false;
      if (filters.quickDirect && cardPostingChannel !== 'direct_employer') return false;
      if (filters.sources?.length && !filters.sources.includes(cardSource)) return false;
      if (filters.quickEasy && !['easy_apply', 'quick_apply'].includes(cardApplyMethod)) return false;
      return true;
    }

    function updatePotentialTabCount(filters) {
      const potentialTab = workspaceTabs.find(tab => tab.dataset.workspaceTarget === 'potential');
      const baseLabel = potentialTab?.dataset.tabLabel;
      if (!potentialTab || !baseLabel) return;

      const potentialPanel = document.querySelector('.workspace-panel[data-workspace-panel="potential"]');
      const cards = potentialPanel ? Array.from(potentialPanel.querySelectorAll('.job-card')) : [];
      const count = cards.filter(card => cardMatchesPotentialFilters(card, filters)).length;
      workspaceTabs
        .filter(tab => tab.dataset.workspaceTarget === 'potential')
        .forEach(tab => {
          tab.textContent = `${tab.dataset.tabLabel || baseLabel} (${count})`;
        });

      for (const workspace of ['applied', 'hidden']) {
        const panel = document.querySelector(`.workspace-panel[data-workspace-panel="${workspace}"]`);
        const workspaceCount = panel ? panel.querySelectorAll('.job-card').length : 0;
        workspaceTabs
          .filter(tab => tab.dataset.workspaceTarget === workspace)
          .forEach(tab => {
            const label = tab.dataset.tabLabel || workspace;
            tab.textContent = `${label} (${workspaceCount})`;
          });
      }
    }

    function ensureWorkspaceGrid(panel) {
      if (!panel) {
        return null;
      }
      const existingGrid = panel.querySelector('.job-grid');
      if (existingGrid) {
        return existingGrid;
      }
      const section = panel.querySelector('section.section');
      if (!section) {
        return null;
      }
      section.querySelector('.empty-state')?.remove();
      const grid = document.createElement('div');
      grid.className = 'job-grid';
      const body = section.querySelector('.results-section-body');
      (body || section).appendChild(grid);
      return grid;
    }

    function copyReviewButtonData(sourceButton, targetButton) {
      if (!sourceButton || !targetButton) {
        return;
      }
      for (const attribute of Array.from(sourceButton.attributes)) {
        if (!attribute.name.startsWith('data-') || attribute.name === 'data-review-action') {
          continue;
        }
        targetButton.setAttribute(attribute.name, attribute.value);
      }
    }

    function moveCardAfterReview(card, action) {
      const destination = {
        applied: 'applied',
        unapply: 'potential',
        hidden: 'hidden',
        unhide: 'potential',
      }[action];
      if (!destination || !card) {
        return;
      }

      if (!card.dataset.reviewOriginalRecordKind) {
        card.dataset.reviewOriginalRecordKind = card.dataset.recordKind || 'current';
      }
      card.dataset.recordKind = destination === 'potential'
        ? card.dataset.reviewOriginalRecordKind
        : destination;
      card.removeAttribute('data-review-dismissed');
      card.classList.remove('is-reviewed');

      const targetPanel = document.querySelector(
        `.workspace-panel[data-workspace-panel="${destination}"]`,
      );
      const targetGrid = ensureWorkspaceGrid(targetPanel);
      if (!targetGrid) {
        return;
      }

      const sourceActions = card.querySelector('.job-actions');
      const targetActions = targetPanel.querySelector('.job-actions');
      if (sourceActions && targetActions) {
        const replacementActions = targetActions.cloneNode(true);
        const sourceButton = sourceActions.querySelector('.review-button');
        replacementActions.querySelectorAll('.review-button').forEach(button => {
          copyReviewButtonData(sourceButton, button);
        });
        sourceActions.replaceWith(replacementActions);
      }

      targetGrid.appendChild(card);
      applyWorkspaceControls();
    }

    function applyWorkspaceControls() {
      const sortMode = sortSelect?.value || 'fit';
      const workType = workTypeFilter?.value || 'all';
      const filters = {
        scopeMode: scopeFilter?.value || 'all',
        postedLimit: postedFilter?.value || 'all',
        workTypeValues: workType !== 'all' ? workType.split('|') : null,
        workMode: workModeFilter?.value || 'all',
        sector: sectorFilter?.value || 'all',
        scoreMode: scoreFilter?.value || 'all',
        quickNew: document.querySelector('[data-quick-filter="new"]')?.getAttribute('aria-pressed') === 'true',
        quickDirect: document.querySelector('[data-quick-filter="direct"]')?.getAttribute('aria-pressed') === 'true',
        sources: sourceFilterButtons.filter(button => button.dataset.sourceFilter !== 'all' && button.getAttribute('aria-pressed') === 'true').map(button => button.dataset.sourceFilter),
        quickEasy: document.querySelector('[data-quick-filter="easy"]')?.getAttribute('aria-pressed') === 'true',
      };
      const activeWorkspace = getActiveWorkspace();

      for (const card of getVisibleCards()) {
        const cardScope = card.dataset.recordKind || 'current';

        let visible = true;
        if (card.dataset.reviewDismissed === '1') visible = false;
        if (activeWorkspace === 'potential') {
          visible = cardMatchesPotentialFilters(card, filters);
        } else if (activeWorkspace === 'applied') {
          if (cardScope !== 'applied') visible = false;
        } else if (activeWorkspace === 'hidden') {
          if (cardScope !== 'hidden') visible = false;
        }

        card.dataset.matchesFilters = visible ? '1' : '0';
      }

      updatePotentialTabCount(filters);

      for (const grid of Array.from(document.querySelectorAll('.job-grid'))) {
        const cards = Array.from(grid.querySelectorAll('.job-card'));
        const originalOrder = [...cards];
        cards.sort((a, b) => {
          if (sortMode === 'newest') {
            return Number(a.dataset.postedAge || 9999) - Number(b.dataset.postedAge || 9999);
          }
          if (sortMode === 'salary') {
            return Number(b.dataset.salarySort || 0) - Number(a.dataset.salarySort || 0);
          }
          if (sortMode === 'unseen') {
            const viewedDiff = Number(a.dataset.viewed || 0) - Number(b.dataset.viewed || 0);
            if (viewedDiff !== 0) return viewedDiff;
          }
          const fitDiff = Number(b.dataset.fitScore || 0) - Number(a.dataset.fitScore || 0);
          if (fitDiff !== 0) return fitDiff;
          return Number(a.dataset.postedAge || 9999) - Number(b.dataset.postedAge || 9999);
        });
        for (const card of cards) {
          grid.appendChild(card);
        }
        let orderChanged = false;
        for (let i = 0; i < cards.length; i++) {
          if (cards[i] !== originalOrder[i]) {
            orderChanged = true;
            break;
          }
        }
        if (orderChanged) {
          for (const card of cards) {
            grid.appendChild(card);
          }
        }
      }

      for (const section of Array.from(document.querySelectorAll('.job-section'))) {
        applySectionPagination(section);
      }
    }

    function focusRelatedCard(action) {
      const targetId = String(action.dataset.relatedCardTarget || '').trim();
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target) {
        return false;
      }

      const targetPanel = target.closest('[data-workspace-panel]');
      const targetWorkspace = targetPanel?.dataset.workspacePanel || '';
      if (targetWorkspace && targetWorkspace !== getActiveWorkspace()) {
        setActiveWorkspace(targetWorkspace, true, false);
      }

      // Pagination and filters can hide a valid destination; reveal only the
      // requested card so the action always lands on the matching workspace item.
      target.hidden = false;
      target.classList.remove('is-related-target');
      void target.offsetWidth;
      target.classList.add('is-related-target');
      const hadTabIndex = target.hasAttribute('tabindex');
      if (!hadTabIndex) {
        target.setAttribute('tabindex', '-1');
      }
      target.focus({ preventScroll: true });
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      window.setTimeout(() => {
        target.classList.remove('is-related-target');
        if (!hadTabIndex) {
          target.removeAttribute('tabindex');
        }
      }, 1800);
      return true;
    }

    function markCardViewed(link) {
      const card = link.closest('.job-card');
      if (!card) return;
      card.dataset.viewed = '1';
      const badges = card.querySelector('.job-badges');
      const newBadge = badges?.querySelector('.badge-new');
      if (newBadge) {
        newBadge.remove();
      }
      if (!card.querySelector('.badge-viewed')) {
        if (badges) {
          badges.insertAdjacentHTML('beforeend', WORKSPACE_CONTEXT.viewedBadgeHtml || '');
        }
      }
    }

    async function hydrateViewedState() {
      try {
        const response = await jobHunterFetch(JOB_HISTORY_API_URL, { method: 'GET' });
        if (!response.ok) {
          return;
        }
        const payload = await response.json().catch(() => ({}));
        const jobs = payload?.jobs || {};
        for (const card of getVisibleCards()) {
          const link = card.querySelector('.job-link');
          const jobKey = link?.dataset.jobKey || '';
          if (!jobKey || !jobs[jobKey] || Number(jobs[jobKey].times_viewed || 0) <= 0) {
            continue;
          }
          card.dataset.viewed = '1';
          const badges = card.querySelector('.job-badges');
          const newBadge = badges?.querySelector('.badge-new');
          if (newBadge) {
            newBadge.remove();
          }
          if (!card.querySelector('.badge-viewed') && badges) {
            badges.insertAdjacentHTML('beforeend', WORKSPACE_CONTEXT.viewedBadgeHtml || '');
          }
        }
        applyWorkspaceControls();
      } catch (error) {
      }
    }

    function sendViewedBeacon(link) {
      if (IS_STATIC_EXPORT) {
        return;
      }
      const payload = JSON.stringify({
        action: 'viewed',
        job_key: link.dataset.jobKey || '',
        url: link.dataset.jobUrl || '',
        title: link.dataset.jobTitle || '',
      });

      try {
        const blob = new Blob([payload], { type: 'application/json' });
        navigator.sendBeacon(REVIEW_API_URL, blob);
      } catch (error) {
      }
    }

    function hideBlockConfirm(card) {
      const confirm = card?.querySelector('[data-block-confirm]');
      if (confirm) {
        confirm.hidden = true;
      }
      const trigger = card?.querySelector('.title-block-btn');
      if (trigger) {
        trigger.hidden = false;
        trigger.classList.remove('is-active');
        trigger.setAttribute('aria-expanded', 'false');
      }
      const blockStatus = card?.querySelector('.block-status');
      if (blockStatus) blockStatus.textContent = '';
    }

    function escapeRegExp(value) {
      return String(value || '').replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
    }

    function dismissCardsByTitlePhrase(phrase) {
      const normalized = String(phrase || '').trim().toLowerCase();
      if (!normalized) {
        return;
      }
      const tokens = normalized.split(/\s+/).filter(Boolean);
      if (!tokens.length) {
        return;
      }
      const matcher = new RegExp(`\\\\b${tokens.map(token => escapeRegExp(token)).join('\\\\s+')}\\\\b`, 'i');
      for (const card of getVisibleCards()) {
        const scope = card.dataset.recordKind || 'current';
        if (!['current', 'saved'].includes(scope)) {
          continue;
        }
        if (matcher.test(card.dataset.titleSearch || '')) {
          card.dataset.reviewDismissed = '1';
          card.classList.add('is-reviewed');
        }
      }
      applyWorkspaceControls();
    }

    function openBlockConfirm(button) {
      const card = button.closest('.job-card');
      if (!card) return;
      const confirm = card.querySelector('[data-block-confirm]');
      const blockStatus = card.querySelector('.block-status');
      for (const panel of Array.from(document.querySelectorAll('[data-block-confirm]'))) {
        if (panel === confirm) {
          continue;
        }
        hideBlockConfirm(panel.closest('.job-card'));
      }
      for (const s of Array.from(document.querySelectorAll('.block-status'))) {
        if (s !== blockStatus) s.textContent = '';
      }
      if (!confirm) return;

      const checksContainer = confirm.querySelector('[data-block-phrase-checks]');
      const manualInput = confirm.querySelector('[data-block-manual-input]');
      const manualRow = confirm.querySelector('.block-manual-row');
      const impactEl = confirm.querySelector('[data-block-impact]');
      const confirmButton = confirm.querySelector('[data-confirm-block]');

      if (confirmButton) {
        confirmButton.dataset.jobKey = button.dataset.jobKey || '';
        confirmButton.dataset.jobUrl = button.dataset.jobUrl || '';
        confirmButton.dataset.jobTitle = button.dataset.jobTitle || '';
        confirmButton.dataset.jobCompany = button.dataset.jobCompany || '';
        confirmButton.dataset.jobTeaser = button.dataset.jobTeaser || '';
      }

      if (checksContainer) {
        checksContainer.innerHTML = '';
      }
      if (manualRow) manualRow.hidden = false;

      function getSelectedPhrases() {
        const manual = (manualInput ? manualInput.value : '').split(',')
          .map(p => p.trim()).filter(Boolean);
        return [...new Set(manual)];
      }

      async function updateImpact() {
        const selected = getSelectedPhrases();
        if (confirmButton) confirmButton.disabled = !selected.length;
        if (!impactEl) return;
        if (!selected.length) { impactEl.textContent = ''; return; }
        impactEl.textContent = 'Checking impact\u2026';
        try {
          const resp = await jobHunterFetch(`${API_BASE_URL}/api/title-block-preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phrases: selected }),
          });
          if (!resp.ok) { impactEl.textContent = ''; return; }
          const data = await resp.json();
          const total = data.total || 0;
          impactEl.textContent = total > 0
            ? `Would hide ${total} visible job${total === 1 ? '' : 's'} matching these patterns.`
            : 'No current visible jobs match these patterns.';
        } catch(e) { impactEl.textContent = ''; }
      }

      if (manualInput) {
        manualInput.oninput = updateImpact;
      }
      button.hidden = true;
      button.classList.add('is-active');
      button.setAttribute('aria-expanded', 'true');
      manualInput?.focus();

      updateImpact();
      if (blockStatus) blockStatus.textContent = '';
      confirm.hidden = false;
    }

    function reviewSavingMessage(action) {
      if (action === 'applied') return 'Saving as applied...';
      if (action === 'unapply') return 'Removing from applied jobs...';
      if (action === 'hidden') return 'Hiding this job...';
      if (action === 'unhide') return 'Removing from hidden jobs...';
      if (action === 'not_for_me') return 'Saving Not For Me feedback...';
      if (action === 'block_similar') return 'Saving title block...';
      return 'Saving review action...';
    }

    function reviewSuccessMessage(action, payload) {
      if (payload?.message) {
        return payload.message;
      }
      if (action === 'applied') return 'Saved to Applied jobs. It will be hidden in future runs.';
      if (action === 'unapply') return 'Removed from Applied jobs. It can appear again in future runs.';
      if (action === 'hidden') return 'Hidden. This role moved to Hidden jobs and can be unhidden later.';
      if (action === 'unhide') return 'Removed from Hidden jobs. It can appear again in future runs.';
      if (action === 'not_for_me') return 'Saved as Not For Me. We will learn from this without blocking similar titles yet.';
      if (action === 'block_similar') return 'Saved. Similar jobs will be blocked by title in future runs.';
      return 'Review action saved.';
    }

    function confirmPossibleRepostBeforeApply(button) {
      if (button.dataset.reviewAction !== 'applied' || button.dataset.similarAppliedWarning !== '1') {
        return true;
      }
      const priorTitle = button.dataset.similarAppliedTitle || button.dataset.jobTitle || 'this role';
      const priorCompany = button.dataset.similarAppliedCompany || button.dataset.jobCompany || '';
      const priorSource = button.dataset.similarAppliedSource || 'another source';
      const companyLabel = priorCompany ? ` at ${priorCompany}` : '';
      return window.confirm(
        `You already marked a very similar role as applied: "${priorTitle}"${companyLabel} from ${priorSource}.\n\nContinue marking this one as applied?`
      );
    }

    async function saveReviewAction(button, extraPayload = {}, options = {}) {
      const card = button.closest('.job-card');
      const status = card?.querySelector('.review-status');
      const action = button.dataset.reviewAction || extraPayload.action || '';
      const requestPayload = {
        action,
        job_key: button.dataset.jobKey || '',
        url: button.dataset.jobUrl || '',
        title: button.dataset.jobTitle || '',
        company: button.dataset.jobCompany || '',
        teaser: button.dataset.jobTeaser || '',
        ...extraPayload,
      };

      if (!status) {
        return;
      }

      if (blockStaticExportWrite(status)) {
        return;
      }

      const buttons = card.querySelectorAll('button');
      buttons.forEach(item => item.disabled = true);
      status.textContent = reviewSavingMessage(action);

      try {
        const response = await jobHunterFetch(REVIEW_API_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestPayload)
        });

        if (response.status === 401) {
          status.textContent = 'Your session has expired. Reload the page and sign in again to continue.';
          buttons.forEach(item => item.disabled = false);
          return;
        }

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || 'Could not save review action');
        }

        hideBlockConfirm(card);
        card.classList.add('is-reviewed');
        status.textContent = options.successMessage || reviewSuccessMessage(action, payload);
        if (payload?.reload_workspace && !payload?.workspace_refresh_async) {
          saveWorkspaceFilters();
          saveWorkspacePagination();
          window.location.reload();
          return;
        }
        if (['applied', 'unapply', 'hidden', 'unhide'].includes(action)) {
          moveCardAfterReview(card, action);
          return;
        }
        window.setTimeout(() => {
          card.dataset.reviewDismissed = '1';
          applyWorkspaceControls();
          if (action === 'block_similar') {
            const phrasesToDismiss = payload.block_phrases || (requestPayload.block_phrases) ||
              [(payload.block_phrase || requestPayload.block_phrase || '')];
            phrasesToDismiss.filter(Boolean).forEach(p => dismissCardsByTitlePhrase(p));
          }
        }, 700);
      } catch (error) {
        buttons.forEach(item => item.disabled = false);
        if (error instanceof TypeError) {
          // fetch() only throws TypeError for network-level failures (server
          // unreachable, offline, CORS block) -- it never throws for HTTP
          // error statuses, those are handled above. Surface the real cause
          // instead of the browser's opaque "Failed to fetch".
          status.textContent = 'Could not reach the Job Hunter server. Check that it is running, then reload this page and try again.';
        } else {
          status.textContent = error.message || 'Could not save review action.';
        }
      }
    }

    document.addEventListener('click', async event => {
      const resetFilters = event.target.closest('#reset_workspace_filters');
      if (resetFilters) {
        resetWorkspaceFiltersToDefaults();
        return;
      }

      const toggle = event.target.closest('[data-toggle-target]');
      if (toggle) {
        const target = document.getElementById(toggle.dataset.toggleTarget || '');
        if (!target) {
          return;
        }
        const isHidden = target.hasAttribute('hidden');
        if (isHidden) {
          target.removeAttribute('hidden');
          toggle.textContent = toggle.textContent.replace('Show', 'Hide');
        } else {
          target.setAttribute('hidden', '');
          toggle.textContent = toggle.textContent.replace('Hide', 'Show');
        }
        return;
      }

      const pageButton = event.target.closest('[data-page-direction]');
      if (pageButton) {
        const section = pageButton.closest('.job-section');
        if (!section) {
          return;
        }
        const sectionId = section.dataset.sectionId || 'matches';
        const delta = pageButton.dataset.pageDirection === 'next' ? 1 : -1;
        paginationState[sectionId] = (paginationState[sectionId] || 1) + delta;
        const usedFooterPagination = Boolean(pageButton.closest('.results-pagination-footer'));
        applySectionPagination(section);
        if (usedFooterPagination) {
          const firstVisibleCard = section.querySelector('.job-card:not([hidden])');
          if (firstVisibleCard) {
            firstVisibleCard.scrollIntoView({ block: 'start' });
          }
        }
        return;
      }

      const relatedCardAction = event.target.closest('[data-related-card-target]');
      if (relatedCardAction) {
        if (focusRelatedCard(relatedCardAction)) {
          event.preventDefault();
        }
        return;
      }

      const link = event.target.closest('.job-link');
      if (link) {
        markCardViewed(link);
        sendViewedBeacon(link);
        return;
      }

      const dismissHelper = event.target.closest('#dismiss_results_helper');
      if (dismissHelper) {
        dismissResultsHelper();
        return;
      }

      const cancelBlock = event.target.closest('[data-cancel-block]');
      if (cancelBlock) {
        const card = cancelBlock.closest('.job-card');
        hideBlockConfirm(card);
        return;
      }

      const confirmBlock = event.target.closest('[data-confirm-block]');
      if (confirmBlock) {
        const blockCard = confirmBlock.closest('.job-card');
        const blockConfirmEl = blockCard?.querySelector('[data-block-confirm]');
        const manualInput = blockConfirmEl?.querySelector('[data-block-manual-input]');
        const manual = (manualInput ? manualInput.value : '').split(',')
          .map(p => p.trim()).filter(Boolean);
        const blockPhrases = [...new Set(manual)].filter(Boolean);
        await saveReviewAction(confirmBlock, {
          action: 'block_similar',
          block_phrases: blockPhrases,
          block_phrase: blockPhrases[0] || '',
        });
        return;
      }

      const titleBlockBtn = event.target.closest('.title-block-btn');
      if (titleBlockBtn) {
        openBlockConfirm(titleBlockBtn);
        return;
      }

      const button = event.target.closest('.review-button');
      if (!button) {
        const workspaceTab = event.target.closest('[data-workspace-target]');
        if (!workspaceTab) {
          return;
        }
        setActiveWorkspace(workspaceTab.dataset.workspaceTarget || 'potential');
        return;
      }
      hideBlockConfirm(button.closest('.job-card'));
      if (button.dataset.reviewAction === 'not_for_me') {
        openRejectionPanel(button);
      } else {
        if (!confirmPossibleRepostBeforeApply(button)) {
          const card = button.closest('.job-card');
          const status = card?.querySelector('.review-status');
          if (status) {
            status.textContent = 'Apply cancelled. This role looks very similar to one already marked as applied.';
          }
          return;
        }
        saveReviewAction(button);
      }
    });

    for (const control of [sortSelect, pageSizeSelect, scopeFilter, postedFilter, workTypeFilter, workModeFilter, sectorFilter, scoreFilter]) {
      control?.addEventListener('change', () => {
        resetPagination();
        saveWorkspaceFilters();
        applyWorkspaceControls();
      });
    }
    for (const button of quickFilterButtons) {
      button.addEventListener('click', () => {
        button.setAttribute('aria-pressed', button.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
        resetPagination();
        saveWorkspaceFilters();
        applyWorkspaceControls();
      });
    }
    for (const button of sourceFilterButtons) {
      button.addEventListener('click', () => {
        const source = button.dataset.sourceFilter;
        if (source === 'all') {
          for (const candidate of sourceFilterButtons) {
            candidate.setAttribute('aria-pressed', candidate.dataset.sourceFilter === 'all' ? 'true' : 'false');
          }
        } else {
          button.setAttribute('aria-pressed', button.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
          const selected = sourceFilterButtons.filter(candidate => candidate.dataset.sourceFilter !== 'all' && candidate.getAttribute('aria-pressed') === 'true');
          sourceFilterButtons.find(candidate => candidate.dataset.sourceFilter === 'all')?.setAttribute('aria-pressed', selected.length ? 'false' : 'true');
        }
        resetPagination();
        saveWorkspaceFilters();
        applyWorkspaceControls();
      });
    }
    moreFiltersButton?.addEventListener('click', () => {
      const expanded = moreFiltersButton.getAttribute('aria-expanded') === 'true';
      moreFiltersButton.setAttribute('aria-expanded', expanded ? 'false' : 'true');
      moreFiltersContent?.classList.toggle('is-open', !expanded);
    });

    showStaticExportBanner();
    loadWorkspaceFilters();
    loadWorkspacePagination();
    setActiveWorkspace((window.location.hash || '#potential').replace('#', ''), false, false);
    showResultsHelperIfNeeded();
    hydrateViewedState();
    // Rejection-learning panel
    let _rejectionPendingButton = null;
    let _rejectionCustomTerms = [];
    let _rejectionStage = 'select';
    let _rejectionSavedBlockers = [];
    let _rejectionTitleSuggestions = [];
    let _rejectionDescriptionSuggestions = [];
    let _rejectionApprovalTokens = {};

    const _rejVisibleSuggestionCategories = new Set([
      'other',
    ]);

    function _rejEscapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[ch]));
    }

    function _rejRemoveItemLabel(value) {
      const template = String(WORKSPACE_CONTEXT.labels?.removeItemLabel || '').trim();
      if (!template) throw new Error('Missing shared remove-item label.');
      return template.replace('{name}', String(value || '').trim());
    }

    function _rejResetPanelChrome() {
      _rejectionStage = 'select';
      _rejectionSavedBlockers = [];
      _rejectionTitleSuggestions = [];
      _rejectionDescriptionSuggestions = [];
      _rejectionApprovalTokens = {};
      document.getElementById('rejection-btn-save').textContent = 'Save & Continue';
      document.getElementById('rejection-btn-save').disabled = true;
      document.getElementById('rejection-btn-skip').textContent = 'Continue Without Extra Blocks';
      document.getElementById('rejection-btn-skip').setAttribute('hidden', '');
      document.getElementById('rejection-btn-cancel').removeAttribute('hidden');
      document.querySelector('.rejection-other')?.removeAttribute('hidden');
      const headerCopy = document.querySelector('#rejection-panel .rejection-panel-header p');
      if (headerCopy) {
        headerCopy.textContent = 'Choose required terms you do not want the app to accept again.';
      }
      const firstUseNote = document.getElementById('rejection-first-use');
      if (firstUseNote) {
        firstUseNote.hidden = false;
        firstUseNote.open = false;
      }
    }

    function openRejectionPanel(button) {
      _rejectionPendingButton = button;
      _rejectionCustomTerms = [];
      _rejResetPanelChrome();
      const jobTitle = button.dataset.jobTitle || 'this role';
      document.getElementById('rejection-panel-title').textContent =
        `Why isn\u2019t "${jobTitle}" a fit for you?`;
      const body = document.getElementById('rejection-panel-body');
      body.className = 'rejection-panel-body is-loading';
      body.textContent = WORKSPACE_CONTEXT.labels.rejectionLoadingSuggestions;
      document.getElementById('rejection-custom-list').innerHTML = '';
      document.getElementById('rejection-other-preview').innerHTML = '';
      document.getElementById('rejection-other-input').value = '';
      document.getElementById('rejection-panel').removeAttribute('hidden');
      document.getElementById('rejection-overlay').removeAttribute('hidden');
      const jobKey = button.dataset.jobKey || '';
      jobHunterFetch(`${API_BASE_URL}/api/rejection-suggestions?job_id=${encodeURIComponent(jobKey)}`)
        .then(r => r.json())
        .catch(() => ({}))
        .then(data => {
          _rejectionApprovalTokens = (data && typeof data.approval_tokens === 'object' && data.approval_tokens) ? data.approval_tokens : {};
          _rejRenderSuggestions(data);
        });
    }

    function _rejSuggestionItems(groups) {
      const items = [];
      const seen = new Set();
      for (const [cat, terms] of Object.entries(groups || {})) {
        if (!_rejVisibleSuggestionCategories.has(cat)) continue;
        for (const raw of terms || []) {
          const value = String(raw || '').trim();
          const key = value.toLowerCase();
          if (!value || seen.has(key)) continue;
          seen.add(key);
          items.push({ value, category: cat });
        }
      }
      return items.slice(0, 12);
    }

    function _rejCollectSelectedBlockers() {
      const selected = Array.from(
        document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-value]:checked')
      ).map(cb => String(cb.dataset.value || '').trim()).filter(Boolean);
      const custom = _rejectionCustomTerms.map(item => String(item.value || '').trim()).filter(Boolean);
      const pendingInput = String(document.getElementById('rejection-other-input')?.value || '').trim();
      return [...new Set([...selected, ...custom, ...(pendingInput ? [pendingInput] : [])])];
    }

    function _rejRenderSuggestions(groups) {
      const body = document.getElementById('rejection-panel-body');
      body.className = 'rejection-panel-body';
      const items = _rejSuggestionItems(groups);
      updateRejectionFirstUseNote(items[0]?.value || '');
      if (items.length === 0) {
        body.innerHTML = '<p style="color:var(--muted);font-size:0.85rem;">No strong required terms found. Add one below if this role clearly depends on something you want to avoid.</p>';
        return;
      }
      const chips = items.map(item => {
        const escapedValue = _rejEscapeHtml(item.value);
        const escapedCat = _rejEscapeHtml(item.category);
        return `<div class="rejection-chip">` +
          `<label><input class="jh-checkbox" type="checkbox" data-value="${escapedValue}" data-cat="${escapedCat}" /> ${escapedValue}</label>` +
          `</div>`;
      }).join('');
      body.innerHTML =
        `<div class="rejection-group">` +
        `<div class="rejection-group-label">Suggested required terms</div>` +
        `<div class="rejection-chips">${chips}</div>` +
        `</div>`;
      body.querySelectorAll('input[type=checkbox]').forEach(cb => {
        cb.addEventListener('change', _rejUpdateSaveBtn);
      });
    }

    function _rejRenderBlockFollowup(payload) {
      _rejectionStage = 'block_followup';
      _rejectionTitleSuggestions = Array.isArray(payload?.title_block_suggestions) ? payload.title_block_suggestions : [];
      _rejectionDescriptionSuggestions = Array.isArray(payload?.description_block_suggestions) ? payload.description_block_suggestions : [];
      document.querySelector('.rejection-other')?.setAttribute('hidden', '');
      document.getElementById('rejection-btn-save').textContent = 'Apply Extra Blocks';
      document.getElementById('rejection-btn-skip').textContent = 'Continue Without Extra Blocks';
      document.getElementById('rejection-btn-skip').removeAttribute('hidden');
      document.getElementById('rejection-btn-cancel').setAttribute('hidden', '');
      const headerCopy = document.querySelector('#rejection-panel .rejection-panel-header p');
      if (headerCopy) {
        headerCopy.textContent = 'Optional next step. Only add extra blocks when they are safe to reject without more context.';
      }
      const firstUseNote = document.getElementById('rejection-first-use');
      if (firstUseNote) {
        firstUseNote.hidden = true;
      }
      const body = document.getElementById('rejection-panel-body');
      body.className = 'rejection-panel-body';
      const selectedBlockers = Array.isArray(_rejectionSavedBlockers) ? _rejectionSavedBlockers : [];
      const selectedBlockerKeys = new Set(selectedBlockers.map(item => String(item || '').trim().toLowerCase()).filter(Boolean));
      const directDescriptionCards = selectedBlockers.map(blocker => {
        const phrase = _rejEscapeHtml(String(blocker || '').trim());
        if (!phrase) return '';
        return `
          <div class="rejection-group">
            <div class="rejection-chip" style="display:flex;align-items:flex-start;width:100%;border-radius:14px;padding:10px 12px;">
              <label style="display:flex;gap:8px;align-items:flex-start;width:100%;cursor:pointer;">
                <input class="jh-checkbox" type="checkbox" data-direct-description-followup="1" data-phrase="${phrase}" />
                <span>
                  <strong>${phrase}</strong><br>
                  <span style="color:var(--muted);font-size:0.8rem;">Reject any future job that mentions this exact phrase anywhere in the description.</span>
                </span>
              </label>
            </div>
          </div>
        `;
      }).join('');
      const filteredDescriptionSuggestions = _rejectionDescriptionSuggestions.filter(item => {
        const key = String(item?.phrase || '').trim().toLowerCase();
        return key && !selectedBlockerKeys.has(key);
      });
      const descriptionCards = _rejectionDescriptionSuggestions.map(item => {
        const phrase = _rejEscapeHtml(item.phrase || '');
        const rejectedCount = Number(item.matched_rejected_count || 0);
        const rejectedExamples = Array.isArray(item.sample_rejected_titles) ? item.sample_rejected_titles : [];
        const examplesHtml = rejectedExamples.length
          ? `<ul>${rejectedExamples.map(example => `<li>${_rejEscapeHtml(example.title || 'Untitled role')}${example.company ? ` - ${_rejEscapeHtml(example.company)}` : ''}</li>`).join('')}</ul>`
          : '<p>No sample roles saved yet.</p>';
        return `
          <div class="rejection-group">
            <div class="rejection-chip" style="display:flex;align-items:flex-start;width:100%;border-radius:14px;padding:10px 12px;">
              <label style="display:flex;gap:8px;align-items:flex-start;width:100%;cursor:pointer;">
                <input class="jh-checkbox" type="checkbox" data-description-followup="1" data-phrase="${phrase}" />
                <span>
                  <strong>${phrase}</strong><br>
                  <span style="color:var(--muted);font-size:0.8rem;">Matched ${rejectedCount} rejected description${rejectedCount === 1 ? '' : 's'} and no kept roles.</span>
                </span>
              </label>
            </div>
            <div style="margin:6px 0 0 26px;color:var(--muted);font-size:0.82rem;">
              <strong style="color:var(--text-primary);font-size:0.82rem;">Examples</strong>
              ${examplesHtml}
            </div>
          </div>
        `;
      }).join('');
      const titleCards = _rejectionTitleSuggestions.map(item => {
        const phrase = _rejEscapeHtml(item.phrase || '');
        const rejectedCount = Number(item.matched_rejected_count || 0);
        const rejectedExamples = Array.isArray(item.sample_rejected_titles) ? item.sample_rejected_titles : [];
        const examplesHtml = rejectedExamples.length
          ? `<ul>${rejectedExamples.map(example => `<li>${_rejEscapeHtml(example.title || 'Untitled role')}${example.company ? ` - ${_rejEscapeHtml(example.company)}` : ''}</li>`).join('')}</ul>`
          : '<p>No sample titles saved yet.</p>';
        return `
          <div class="rejection-group">
            <div class="rejection-chip" style="display:flex;align-items:flex-start;width:100%;border-radius:14px;padding:10px 12px;">
              <label style="display:flex;gap:8px;align-items:flex-start;width:100%;cursor:pointer;">
                <input class="jh-checkbox" type="checkbox" data-title-followup="1" data-phrase="${phrase}" />
                <span>
                  <strong>${phrase}</strong><br>
                  <span style="color:var(--muted);font-size:0.8rem;">Matched ${rejectedCount} rejected title${rejectedCount === 1 ? '' : 's'} and no kept titles.</span>
                </span>
              </label>
            </div>
            <div style="margin:6px 0 0 26px;color:var(--muted);font-size:0.82rem;">
              <strong style="color:var(--text-primary);font-size:0.82rem;">Examples</strong>
              ${examplesHtml}
            </div>
          </div>
        `;
      }).join('');
      const sections = [];
      if (directDescriptionCards) {
        sections.push(
          `<div class="rejection-group">` +
          `<div class="rejection-group-label">Always reject exact phrase</div>` +
          `<p style="margin:0 0 10px;color:var(--muted);font-size:0.84rem;">Use this only when any mention should reject the job, even if the term is not framed as a requirement.</p>` +
          `${directDescriptionCards}` +
          `</div>`
        );
      }
      if (descriptionCards) {
        sections.push(
          `<div class="rejection-group">` +
          `<div class="rejection-group-label">Optional hard description blocks</div>` +
          `<p style="margin:0 0 10px;color:var(--muted);font-size:0.84rem;">These phrases only appeared in rejected descriptions, so they can be blocked anywhere in future job descriptions.</p>` +
          `${descriptionCards}` +
          `</div>`
        );
      }
      if (titleCards) {
        sections.push(
          `<div class="rejection-group">` +
          `<div class="rejection-group-label">Optional title blocks</div>` +
          `<p style="margin:0 0 10px;color:var(--muted);font-size:0.84rem;">These terms also look strong enough to block at the title level before the app reads the description.</p>` +
          `${titleCards}` +
          `</div>`
        );
      }
      body.innerHTML = sections.join('');
      body.querySelectorAll('input[type=checkbox][data-title-followup], input[type=checkbox][data-description-followup], input[type=checkbox][data-direct-description-followup]').forEach(cb => {
        cb.addEventListener('change', _rejUpdateSaveBtn);
      });
      _rejUpdateSaveBtn();
    }

    function _rejUpdateSaveBtn() {
      if (_rejectionStage === 'block_followup') {
        const anyChecked = document.querySelector('#rejection-panel-body input[type=checkbox][data-title-followup]:checked, #rejection-panel-body input[type=checkbox][data-description-followup]:checked, #rejection-panel-body input[type=checkbox][data-direct-description-followup]:checked');
        document.getElementById('rejection-btn-save').disabled = !anyChecked;
        return;
      }
      const anyChecked = document.querySelector('#rejection-panel-body input[type=checkbox][data-value]:checked');
      document.getElementById('rejection-btn-save').disabled =
        !anyChecked && _rejectionCustomTerms.length === 0;
    }

    function closeRejectionPanel() {
      document.getElementById('rejection-panel').setAttribute('hidden', '');
      document.getElementById('rejection-overlay').setAttribute('hidden', '');
      _rejectionPendingButton = null;
      _rejectionCustomTerms = [];
      _rejResetPanelChrome();
    }

    async function _rejPersistRequiredBlockers(blockers, titleBlockPhrases = [], descriptionBlockPhrases = []) {
      const button = _rejectionPendingButton;
      const approvedSuggestionTokens = {};
      blockers.forEach((blocker) => {
        const key = String(blocker || '').trim().toLowerCase();
        if (key && _rejectionApprovalTokens[key]) {
          approvedSuggestionTokens[key] = _rejectionApprovalTokens[key];
        }
      });
      const response = await jobHunterFetch(`${API_BASE_URL}/api/rejection-feedback/required-blockers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: button?.dataset.jobKey || '',
          job_title: button?.dataset.jobTitle || '',
          url: button?.dataset.jobUrl || '',
          company: button?.dataset.jobCompany || '',
          teaser: button?.dataset.jobTeaser || '',
          blockers,
          title_block_phrases: titleBlockPhrases,
          description_block_phrases: descriptionBlockPhrases,
          approved_suggestion_tokens: approvedSuggestionTokens,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Could not save blockers');
      }
      return payload;
    }

    async function _rejCompleteReview(result, titleBlockPhrases = [], descriptionBlockPhrases = []) {
      const button = _rejectionPendingButton;
      const successMessage = result?.message || 'Saved blocker feedback.';
      closeRejectionPanel();
      titleBlockPhrases.filter(Boolean).forEach(phrase => dismissCardsByTitlePhrase(phrase));
      if (button) {
        await saveReviewAction(button, {}, { successMessage });
      }
    }

    async function _rejSaveAndContinue() {
      const saveButton = document.getElementById('rejection-btn-save');
      if (blockStaticExportWrite()) {
        return;
      }
      const originalLabel = saveButton.textContent;
      saveButton.disabled = true;
      saveButton.textContent = _rejectionStage === 'block_followup' ? 'Saving...' : 'Saving blockers...';
      try {
        if (_rejectionStage === 'block_followup') {
          const selectedTitlePhrases = Array.from(
            document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-title-followup]:checked')
          ).map(cb => String(cb.dataset.phrase || '').trim()).filter(Boolean);
          const selectedDescriptionPhrases = Array.from(
            document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-direct-description-followup]:checked')
          ).map(cb => String(cb.dataset.phrase || '').trim()).filter(Boolean);
          const suggestedDescriptionPhrases = Array.from(
            document.querySelectorAll('#rejection-panel-body input[type=checkbox][data-description-followup]:checked')
          ).map(cb => String(cb.dataset.phrase || '').trim()).filter(Boolean);
          const allDescriptionPhrases = [...new Set([...selectedDescriptionPhrases, ...suggestedDescriptionPhrases])];
          const result = await _rejPersistRequiredBlockers(
            _rejectionSavedBlockers,
            selectedTitlePhrases,
            allDescriptionPhrases,
          );
          await _rejCompleteReview(
            result,
            result?.applied_title_block_phrases || selectedTitlePhrases,
            result?.applied_description_block_phrases || allDescriptionPhrases,
          );
          return;
        }

        const blockers = _rejCollectSelectedBlockers();
        if (!blockers.length) {
          return;
        }
        _rejectionSavedBlockers = blockers;
        const result = await _rejPersistRequiredBlockers(blockers);
        const hasFollowups =
          blockers.length > 0 ||
          (Array.isArray(result?.title_block_suggestions) && result.title_block_suggestions.length) ||
          (Array.isArray(result?.description_block_suggestions) && result.description_block_suggestions.length);
        if (hasFollowups) {
          _rejRenderBlockFollowup(result);
          return;
        }
        await _rejCompleteReview(result);
      } catch (error) {
        saveButton.disabled = false;
        saveButton.textContent = originalLabel;
        const body = document.getElementById('rejection-panel-body');
        if (body && !body.classList.contains('is-loading')) {
          body.insertAdjacentHTML(
            'afterbegin',
            `<p style="margin:0 0 10px;color:#b91c1c;font-size:0.84rem;">${_rejEscapeHtml(error.message || 'Could not save blockers.')}</p>`
          );
        }
        return;
      }
      saveButton.textContent = originalLabel;
    }

    function _rejRenderCustomChips() {
      const list = document.getElementById('rejection-custom-list');
      list.innerHTML = _rejectionCustomTerms.map((t, i) => {
        const value = _rejEscapeHtml(t.value);
        const removeLabel = _rejEscapeHtml(_rejRemoveItemLabel(t.value));
        return `<span class="rejection-custom-chip">${value}` +
          `<button type="button" data-idx="${i}" aria-label="${removeLabel}" title="${removeLabel}">&times;</button></span>`;
      }).join('');
      list.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
          _rejectionCustomTerms.splice(+btn.dataset.idx, 1);
          _rejRenderCustomChips();
          _rejUpdateSaveBtn();
        });
      });
    }

    document.getElementById('rejection-other-add').addEventListener('click', () => {
      if (_rejectionStage !== 'select') return;
      const input = document.getElementById('rejection-other-input');
      const previewEl = document.getElementById('rejection-other-preview');
      const addButton = document.getElementById('rejection-other-add');
      const val = input.value.trim();
      if (!val || val.length < 2) return;
      const jobKey = _rejectionPendingButton?.dataset.jobKey || '';
      addButton.disabled = true;
      jobHunterFetch(
        `${API_BASE_URL}/api/rejection-feedback/custom-blocker-preview?job_id=${encodeURIComponent(jobKey)}&term=${encodeURIComponent(val)}`
      )
        .then(r => r.json())
        .catch(() => ({ ok: false, preview_html: '' }))
        .then(data => {
          addButton.disabled = false;
          previewEl.innerHTML = (data && data.preview_html) ? data.preview_html : '';
          if (data && data.ok) {
            _rejectionCustomTerms.push({ value: data.canonical_requirement, category: 'other' });
            input.value = '';
            _rejRenderCustomChips();
            _rejUpdateSaveBtn();
          }
        });
    });

    document.getElementById('rejection-other-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') document.getElementById('rejection-other-add').click();
    });

    document.getElementById('rejection-btn-save').addEventListener('click', _rejSaveAndContinue);

    document.getElementById('rejection-btn-skip').addEventListener('click', () => {
      if (_rejectionStage === 'block_followup') {
        _rejCompleteReview({
          message: 'Saved blocker feedback without adding extra blocks.',
        }).catch(() => {});
      }
    });

    document.getElementById('rejection-btn-cancel').addEventListener('click', () => {
      const card = _rejectionPendingButton?.closest('.job-card');
      if (card) { card.querySelectorAll('button').forEach(b => b.disabled = false); }
      closeRejectionPanel();
    });

    document.getElementById('rejection-overlay').addEventListener('click', () => {
      document.getElementById('rejection-btn-cancel').click();
    });
    // end rejection-learning panel

    // Profile-learning actions live on safe atomic requirement rows and share
    // the existing profile-gap API/storage semantics.
    document.addEventListener('click', function(event) {
      const btn = event.target.closest('.gap-btn');
      if (!btn) return;
      const action = String(btn.dataset.action || '').trim();
      const capabilityName = String(btn.dataset.capabilityName || '').trim();
      const jobCard = btn.closest('.job-card');
      const cardJobKeyEl = jobCard ? jobCard.querySelector('[data-job-key]') : null;
      const jobKey = String(
        (cardJobKeyEl ? cardJobKeyEl.dataset.jobKey : '')
        || ''
      ).trim();
      if (!capabilityName || !action) return;

      function showRowStatus(message) {
        let statusEl = btn.parentElement ? btn.parentElement.querySelector('.review-status') : null;
        if (!statusEl) {
          statusEl = document.createElement('span');
          statusEl.className = 'review-status';
          btn.insertAdjacentElement('afterend', statusEl);
        }
        statusEl.textContent = message;
      }

      function replaceRowActionsWithBadge(message, allBtns) {
        const badge = document.createElement('span');
        badge.className = 'jh-badge';
        badge.textContent = message;
        allBtns.forEach(function(otherBtn) {
          if (otherBtn !== btn) otherBtn.remove();
        });
        btn.replaceWith(badge);
      }

      if (!jobKey) return;
      if (blockStaticExportWrite()) return;

      const allBtns = btn.parentElement
        ? Array.from(btn.parentElement.querySelectorAll('.gap-btn'))
        : [btn];
      allBtns.forEach(function(b) { b.disabled = true; });

      jobHunterFetch(`${API_BASE_URL}/api/profile-gap`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_key: jobKey, capability_name: capabilityName, action: action }),
      }).then(function(resp) {
        return resp.json().catch(function() { return {}; }).then(function(data) {
          if (!resp.ok || data.error) {
            allBtns.forEach(function(b) { b.disabled = false; });
            showRowStatus(data.error || WORKSPACE_CONTEXT.labels.profileGapErrorLabel);
            return;
          }
          const savedLabel = action === 'confirm_do_not_have'
            ? WORKSPACE_CONTEXT.labels.profileGapNotHaveSavedLabel
            : WORKSPACE_CONTEXT.labels.profileGapAddedLabel;
          replaceRowActionsWithBadge(savedLabel, allBtns);
        });
      }).catch(function() {
        allBtns.forEach(function(b) { b.disabled = false; });
        showRowStatus(WORKSPACE_CONTEXT.labels.profileGapErrorLabel);
      });
    });
})();
