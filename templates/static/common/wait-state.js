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
    progress: String(source.progress || '').trim(),
    subcopy: String(source.subcopy || '').trim(),
  };
}

function splitProgressText(progress) {
  const text = String(progress || '').trim();
  if (!text) {
    return { step: '', activityItems: [], elapsed: '' };
  }
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length > 1) {
    let elapsed = '';
    const lastLine = lines[lines.length - 1] || '';
    const elapsedMatch = lastLine.match(/^elapsed\s+(.+)$/i);
    if (elapsedMatch) {
      elapsed = String(elapsedMatch[1] || '').trim();
      lines.pop();
    }
    return {
      step: String(lines[0] || '').trim(),
      activityItems: lines.slice(1),
      elapsed,
    };
  }
  const segments = text.split(/\s+\|\s+/).map((segment) => segment.trim()).filter(Boolean);
  if (!segments.length) {
    return { step: '', activityItems: [], elapsed: '' };
  }
  let elapsed = '';
  const lastSegment = segments[segments.length - 1] || '';
  const elapsedMatch = lastSegment.match(/^elapsed\s+(.+)$/i);
  if (elapsedMatch) {
    elapsed = String(elapsedMatch[1] || '').trim();
    segments.pop();
  }
  return {
    step: String(segments[0] || '').trim(),
    activityItems: segments.slice(1),
    elapsed,
  };
}

function sameState(left, right) {
  return Boolean(left) && Boolean(right)
    && left.title === right.title
    && left.copy === right.copy
    && left.progress === right.progress
    && left.subcopy === right.subcopy;
}

function shouldRenderSearchWhy(state) {
  return String(state?.title || '').trim() === SEARCH_RUNNING_TITLE;
}

function renderSearchWhyMarkup() {
  return `
    <details class="wait-state__explainer">
      <summary class="wait-state__explainer-summary">${escapeHtml(SEARCH_WAIT_WHY_LABEL)}</summary>
      <div class="wait-state__explainer-body">
        <p class="wait-state__explainer-copy">${escapeHtml(SEARCH_WAIT_WHY_INTRO)}</p>
        <ul class="wait-state__explainer-list">
          <li>${escapeHtml(SEARCH_WAIT_WHY_BROWSER)}</li>
          <li>${escapeHtml(SEARCH_WAIT_WHY_PACING)}</li>
          <li>${escapeHtml(SEARCH_WAIT_WHY_DETAILS)}</li>
          <li>${escapeHtml(SEARCH_WAIT_WHY_SCORING)}</li>
          <li>${escapeHtml(SEARCH_WAIT_WHY_JOB_RUN)}</li>
        </ul>
      </div>
    </details>
  `;
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
  const progress = splitProgressText(normalized.progress);
  const activityItems = progress.activityItems.slice().reverse();
  const progressMarkup = progress.step || progress.activityItems.length || progress.elapsed
    ? `
        <div class="wait-state__progress">
          ${progress.step ? `
            <p class="wait-state__status wait-state__status--progress">
              <span class="wait-state__status-label">${escapeHtml(SEARCH_PROGRESS_PREFIX)}</span>
              <span class="wait-state__status-value">${escapeHtml(progress.step)}</span>
            </p>
          ` : ''}
          ${activityItems.length ? `
            <div class="wait-state__activity">
              <ul class="wait-state__activity-list">
                ${activityItems.map((item) => `<li class="wait-state__activity-item">${escapeHtml(item)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
          ${progress.elapsed ? `
            <p class="wait-state__status wait-state__status--elapsed">
              <span class="wait-state__status-label">${escapeHtml(SEARCH_ELAPSED_PREFIX)}</span>
              <span class="wait-state__status-value">${escapeHtml(progress.elapsed)}</span>
            </p>
          ` : ''}
        </div>
      `
    : '';
  mount.hidden = false;
  document.body.classList.add('job-hunter-wait-active');
  mount.innerHTML = `
    <div class="job-hunter-wait-backdrop" aria-hidden="true"></div>
    <div class="job-hunter-wait-shell">
      <div class="wait-state" role="status" aria-live="polite">
        <span class="wait-state__spinner" aria-hidden="true"></span>
        <p class="wait-state__title">${escapeHtml(normalized.title)}</p>
        ${normalized.copy ? `<p class="wait-state__copy">${escapeHtml(normalized.copy)}</p>` : ''}
        ${progressMarkup}
        ${shouldRenderSearchWhy(normalized) ? renderSearchWhyMarkup() : ''}
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
export const SEARCH_WAIT_WHY_LABEL = String(SHARED_UI_LABELS.search_wait_why_label || '').trim();
export const SEARCH_WAIT_WHY_INTRO = String(SHARED_UI_LABELS.search_wait_why_intro || '').trim();
export const SEARCH_WAIT_WHY_BROWSER = String(SHARED_UI_LABELS.search_wait_why_browser || '').trim();
export const SEARCH_WAIT_WHY_PACING = String(SHARED_UI_LABELS.search_wait_why_pacing || '').trim();
export const SEARCH_WAIT_WHY_DETAILS = String(SHARED_UI_LABELS.search_wait_why_details || '').trim();
export const SEARCH_WAIT_WHY_SCORING = String(SHARED_UI_LABELS.search_wait_why_scoring || '').trim();
export const SEARCH_WAIT_WHY_JOB_RUN = String(SHARED_UI_LABELS.search_wait_why_job_run || '').trim();
export const SEARCH_RUNNING_TITLE = String(SHARED_UI_LABELS.search_running_title || '').trim();
export const SEARCH_RUNNING_COPY = String(SHARED_UI_LABELS.search_running_copy || '').trim();
export const SEARCH_STARTING_TITLE = String(SHARED_UI_LABELS.search_starting_title || '').trim();
export const SEARCH_STARTING_COPY = String(SHARED_UI_LABELS.search_starting_copy || '').trim();
export const SEARCH_REFRESHING_TITLE = String(SHARED_UI_LABELS.search_refreshing_title || '').trim();
export const SEARCH_REFRESHING_COPY = String(SHARED_UI_LABELS.search_refreshing_copy || '').trim();
export const SEARCH_PROGRESS_PREFIX = String(SHARED_UI_LABELS.search_progress_prefix || '').trim();
export const SEARCH_ELAPSED_PREFIX = String(SHARED_UI_LABELS.search_elapsed_prefix || '').trim();
export const SEARCH_RUNNING_SUBCOPY = String(SHARED_UI_LABELS.search_running_subcopy || '').trim();
export const SEARCH_STARTING_SUBCOPY = String(SHARED_UI_LABELS.search_starting_subcopy || '').trim();
if (!SEARCH_WAIT_COPY || !SEARCH_WAIT_WHY_LABEL || !SEARCH_WAIT_WHY_INTRO || !SEARCH_WAIT_WHY_BROWSER || !SEARCH_WAIT_WHY_PACING || !SEARCH_WAIT_WHY_DETAILS || !SEARCH_WAIT_WHY_SCORING || !SEARCH_WAIT_WHY_JOB_RUN || !SEARCH_RUNNING_TITLE || !SEARCH_RUNNING_COPY || !SEARCH_STARTING_TITLE || !SEARCH_STARTING_COPY || !SEARCH_REFRESHING_TITLE || !SEARCH_REFRESHING_COPY || !SEARCH_PROGRESS_PREFIX || !SEARCH_ELAPSED_PREFIX || !SEARCH_RUNNING_SUBCOPY || !SEARCH_STARTING_SUBCOPY) {
  throw new Error('Missing shared UI labels for workspace wait copy.');
}
export const RUN_COMPLETE_REDIRECT_DELAY_MS = 600;
