function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function normalizeState(state) {
  const source = state && typeof state === 'object' ? state : {};
  return {
    title: String(source.title || 'Working').trim() || 'Working',
    copy: String(source.copy || '').trim(),
    subcopy: String(source.subcopy || '').trim(),
  };
}

function sameState(left, right) {
  return Boolean(left) && Boolean(right)
    && left.title === right.title
    && left.copy === right.copy
    && left.subcopy === right.subcopy;
}

function renderWaitState(mount, state) {
  if (!mount) {
    return;
  }
  if (!state) {
    mount.innerHTML = '';
    mount.hidden = true;
    document.body.classList.remove('job-hunter-wait-active');
    return;
  }
  const normalized = normalizeState(state);
  mount.hidden = false;
  document.body.classList.add('job-hunter-wait-active');
  mount.innerHTML = `
    <div class="job-hunter-wait-backdrop" aria-hidden="true"></div>
    <div class="job-hunter-wait-shell">
      <div class="wait-state" role="status" aria-live="polite">
        <span class="wait-state__spinner" aria-hidden="true"></span>
        <p class="wait-state__title">${escapeHtml(normalized.title)}</p>
        ${normalized.copy ? `<p class="wait-state__copy">${escapeHtml(normalized.copy)}</p>` : ''}
        ${normalized.subcopy ? `<p class="wait-state__subcopy">${escapeHtml(normalized.subcopy)}</p>` : ''}
      </div>
    </div>
  `;
}

export function createController(mount) {
  let currentState = null;
  return {
    show(state) {
      const nextState = normalizeState(state);
      if (sameState(currentState, nextState)) {
        return;
      }
      currentState = nextState;
      renderWaitState(mount, currentState);
    },
    update(patch) {
      if (!currentState) {
        return;
      }
      const next = patch && typeof patch === 'object' ? patch : {};
      const nextState = normalizeState({ ...currentState, ...next });
      if (sameState(currentState, nextState)) {
        return;
      }
      currentState = nextState;
      renderWaitState(mount, currentState);
    },
    hide() {
      currentState = null;
      renderWaitState(mount, null);
    },
    getState() {
      return currentState ? { ...currentState } : null;
    },
  };
}

export const WORKSPACE_PATH = '/workspace';
const SHARED_UI_LABELS = window.__JOB_HUNTER_SHARED_UI_LABELS__ || {};
export const SEARCH_WAIT_COPY = String(SHARED_UI_LABELS.search_wait_copy || '').trim();
export const SEARCH_RUNNING_TITLE = String(SHARED_UI_LABELS.search_running_title || '').trim();
export const SEARCH_RUNNING_COPY = String(SHARED_UI_LABELS.search_running_copy || '').trim();
export const SEARCH_STARTING_TITLE = String(SHARED_UI_LABELS.search_starting_title || '').trim();
export const SEARCH_STARTING_COPY = String(SHARED_UI_LABELS.search_starting_copy || '').trim();
export const SEARCH_REFRESHING_TITLE = String(SHARED_UI_LABELS.search_refreshing_title || '').trim();
export const SEARCH_REFRESHING_COPY = String(SHARED_UI_LABELS.search_refreshing_copy || '').trim();
export const SEARCH_RUNNING_SUBCOPY = String(SHARED_UI_LABELS.search_running_subcopy || '').trim();
export const SEARCH_STARTING_SUBCOPY = String(SHARED_UI_LABELS.search_starting_subcopy || '').trim();
if (!SEARCH_WAIT_COPY || !SEARCH_RUNNING_TITLE || !SEARCH_RUNNING_COPY || !SEARCH_STARTING_TITLE || !SEARCH_STARTING_COPY || !SEARCH_REFRESHING_TITLE || !SEARCH_REFRESHING_COPY || !SEARCH_RUNNING_SUBCOPY || !SEARCH_STARTING_SUBCOPY) {
  throw new Error('Missing shared UI labels for workspace wait copy.');
}
export const RUN_COMPLETE_REDIRECT_DELAY_MS = 600;
