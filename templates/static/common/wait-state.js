function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function requireLabel(labels, key, groupName) {
  const value = String(labels?.[key] || '').trim();
  if (!value) {
    throw new Error(`Missing ${groupName}.${key}`);
  }
  return value;
}

const SHARED_UI_LABELS = window.__JOB_HUNTER_SHARED_UI_LABELS__ || {};
const SEARCH_SOURCE_LABELS = window.__JOB_HUNTER_SEARCH_SOURCE_LABELS__ || {};

export const WORKSPACE_PATH = '/workspace';
export const SEARCH_WAIT_COPY = requireLabel(SHARED_UI_LABELS, 'search_wait_copy', 'shared_ui_labels');
export const SEARCH_WAIT_WHY_LABEL = requireLabel(SHARED_UI_LABELS, 'search_wait_why_label', 'shared_ui_labels');
export const SEARCH_WAIT_WHY_COPY = requireLabel(SHARED_UI_LABELS, 'search_wait_why_copy', 'shared_ui_labels');
export const SEARCH_RUNNING_TITLE = requireLabel(SHARED_UI_LABELS, 'search_running_title', 'shared_ui_labels');
export const SEARCH_RUNNING_COPY = requireLabel(SHARED_UI_LABELS, 'search_running_copy', 'shared_ui_labels');
export const SEARCH_STARTING_TITLE = requireLabel(SHARED_UI_LABELS, 'search_starting_title', 'shared_ui_labels');
export const SEARCH_STARTING_COPY = requireLabel(SHARED_UI_LABELS, 'search_starting_copy', 'shared_ui_labels');
export const SEARCH_REFRESHING_TITLE = requireLabel(SHARED_UI_LABELS, 'search_refreshing_title', 'shared_ui_labels');
export const SEARCH_REFRESHING_COPY = requireLabel(SHARED_UI_LABELS, 'search_refreshing_copy', 'shared_ui_labels');
export const SEARCH_RUNNING_SUBCOPY = requireLabel(SHARED_UI_LABELS, 'search_running_subcopy', 'shared_ui_labels');
export const SEARCH_STARTING_SUBCOPY = requireLabel(SHARED_UI_LABELS, 'search_starting_subcopy', 'shared_ui_labels');
export const SEARCH_STOP_LABEL = requireLabel(SHARED_UI_LABELS, 'search_stop_label', 'shared_ui_labels');
export const SEARCH_STOPPING_TITLE = requireLabel(SHARED_UI_LABELS, 'search_stopping_title', 'shared_ui_labels');
export const SEARCH_STOPPING_COPY = requireLabel(SHARED_UI_LABELS, 'search_stopping_copy', 'shared_ui_labels');
export const SEARCH_STOPPING_SUBCOPY = requireLabel(SHARED_UI_LABELS, 'search_stopping_subcopy', 'shared_ui_labels');
const SEARCH_ELAPSED_SUFFIX = requireLabel(SHARED_UI_LABELS, 'search_elapsed_suffix', 'shared_ui_labels');
const SEARCH_PROGRESS_ARIA_SUFFIX = requireLabel(SHARED_UI_LABELS, 'search_progress_aria_suffix', 'shared_ui_labels');
export const RUN_COMPLETE_REDIRECT_DELAY_MS = 600;

const SOURCE_BADGES = Object.freeze({
  linkedin: Object.freeze({
    label: requireLabel(SEARCH_SOURCE_LABELS, 'linkedin_display_label', 'search_source_labels'),
    shortLabel: requireLabel(SEARCH_SOURCE_LABELS, 'linkedin_badge_label', 'search_source_labels'),
    modifier: 'linkedin',
  }),
  seek: Object.freeze({
    label: requireLabel(SEARCH_SOURCE_LABELS, 'seek_display_label', 'search_source_labels'),
    shortLabel: requireLabel(SEARCH_SOURCE_LABELS, 'seek_badge_label', 'search_source_labels'),
    modifier: 'seek',
  }),
  apsjobs: Object.freeze({
    label: requireLabel(SEARCH_SOURCE_LABELS, 'apsjobs_display_label', 'search_source_labels'),
    shortLabel: requireLabel(SEARCH_SOURCE_LABELS, 'apsjobs_badge_label', 'search_source_labels'),
    modifier: 'apsjobs',
  }),
  generic: Object.freeze({
    label: requireLabel(SEARCH_SOURCE_LABELS, 'generic_display_label', 'search_source_labels'),
    shortLabel: '',
    modifier: 'generic',
  }),
});

function normalizeOptionalInteger(value, fieldName) {
  if (value === null || value === undefined) {
    return null;
  }
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`Invalid progress_detail.${fieldName}`);
  }
  return value;
}

export function normalizeProgressDetail(value) {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid progress_detail payload');
  }

  const stage = String(value.stage || '').trim();
  if (!stage) {
    throw new Error('Missing progress_detail.stage');
  }

  const rawSource = value.source === null || value.source === undefined
    ? 'generic'
    : String(value.source).trim();
  if (!Object.prototype.hasOwnProperty.call(SOURCE_BADGES, rawSource)) {
    throw new Error(`Unknown progress_detail.source: ${rawSource}`);
  }

  const current = normalizeOptionalInteger(value.current, 'current');
  const total = normalizeOptionalInteger(value.total, 'total');
  const itemCurrent = normalizeOptionalInteger(value.item_current, 'item_current');
  const itemTotal = normalizeOptionalInteger(value.item_total, 'item_total');

  if ((current === null) !== (total === null)) {
    throw new Error('progress_detail.current and total must be supplied together');
  }
  if (current !== null && total !== null && current > total) {
    throw new Error('progress_detail.current must not exceed total');
  }
  if ((itemCurrent === null) !== (itemTotal === null)) {
    throw new Error('progress_detail.item_current and item_total must be supplied together');
  }
  if (itemCurrent !== null && itemTotal !== null && itemCurrent > itemTotal) {
    throw new Error('progress_detail.item_current must not exceed item_total');
  }

  const determinate = value.determinate === true;
  if (determinate && (current === null || total === null || total <= 0)) {
    throw new Error('Determinate progress requires a valid current/total pair');
  }

  return {
    stage,
    source: rawSource,
    headline: String(value.headline || '').trim(),
    detail: String(value.detail || '').trim(),
    current,
    total,
    itemCurrent,
    itemTotal,
    determinate,
  };
}

function normalizeState(state) {
  const source = state && typeof state === 'object' ? state : {};
  const title = String(source.title || '').trim();
  if (!title) {
    throw new Error('Wait state requires a title');
  }
  return {
    title,
    copy: String(source.copy || '').trim(),
    progress: String(source.progress || '').trim(),
    progressDetail: normalizeProgressDetail(source.progressDetail),
    elapsedText: String(source.elapsedText || '').trim(),
    subcopy: String(source.subcopy || '').trim(),
    allowStop: Boolean(source.allowStop),
  };
}

function sameProgressDetail(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function sameState(left, right) {
  return Boolean(left) && Boolean(right)
    && left.title === right.title
    && left.copy === right.copy
    && left.progress === right.progress
    && sameProgressDetail(left.progressDetail, right.progressDetail)
    && left.elapsedText === right.elapsedText
    && left.subcopy === right.subcopy
    && left.allowStop === right.allowStop;
}

function shouldRenderSearchWhy(state) {
  return state.title === SEARCH_RUNNING_TITLE;
}

function genericProcessIconMarkup() {
  return `
    <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
      <circle cx="10" cy="10" r="5"></circle>
      <path d="m14 14 5 5"></path>
    </svg>
  `;
}

export function renderSourceBadge(source) {
  const key = source || 'generic';
  const badge = SOURCE_BADGES[key];
  if (!badge) {
    throw new Error(`Unknown progress source: ${key}`);
  }
  const content = badge.shortLabel ? escapeHtml(badge.shortLabel) : genericProcessIconMarkup();
  return `
    <span class="source-status-badge source-status-badge--${badge.modifier}" aria-hidden="true">
      ${content}
    </span>
  `;
}

export function renderProgressBar(progressDetail) {
  if (!progressDetail) {
    return '';
  }
  const headline = progressDetail.headline || SOURCE_BADGES[progressDetail.source].label;
  const ariaLabel = `${headline} ${SEARCH_PROGRESS_ARIA_SUFFIX}`;
  if (!progressDetail.determinate) {
    return `
      <div
        class="jh-progress jh-progress--indeterminate"
        role="progressbar"
        aria-label="${escapeHtml(ariaLabel)}"
      ></div>
    `;
  }

  const percentage = Math.min(100, Math.max(0, (progressDetail.current / progressDetail.total) * 100));
  return `
    <div
      class="jh-progress"
      role="progressbar"
      aria-label="${escapeHtml(ariaLabel)}"
      aria-valuemin="0"
      aria-valuemax="${progressDetail.total}"
      aria-valuenow="${progressDetail.current}"
    >
      <span class="jh-progress__bar" style="--progress-value: ${percentage.toFixed(2)}%"></span>
    </div>
  `;
}

function legacyProgressCopy(progress) {
  const lines = String(progress || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return {
    headline: lines[0] || '',
    detail: lines.slice(1).join(' · '),
  };
}

function renderProgressMarkup(state) {
  const progressDetail = state.progressDetail;
  // Text-only messages are a bounded fallback for verification/error states; the
  // browser never infers source, counts, elapsed time, or percentage from them.
  const legacy = progressDetail ? { headline: '', detail: '' } : legacyProgressCopy(state.progress);
  const source = progressDetail?.source || 'generic';
  const headline = progressDetail?.headline || legacy.headline;
  const detail = progressDetail?.detail || legacy.detail;
  if (!headline && !detail && !state.elapsedText) {
    return '';
  }

  const sourceMarkup = headline || detail
    ? `
      <div class="search-progress-source">
        ${renderSourceBadge(source)}
        <div class="search-progress-source__copy">
          ${headline ? `<p class="search-progress-source__title">${escapeHtml(headline)}</p>` : ''}
          ${detail ? `<p class="search-progress-source__detail">${escapeHtml(detail)}</p>` : ''}
        </div>
      </div>
    `
    : '';

  return `
    <div class="wait-state__progress">
      ${sourceMarkup}
      ${renderProgressBar(progressDetail)}
      ${state.elapsedText ? `<p class="search-progress-elapsed">${escapeHtml(state.elapsedText)} ${escapeHtml(SEARCH_ELAPSED_SUFFIX)}</p>` : ''}
    </div>
  `;
}

function renderSearchWhyMarkup() {
  return `
    <details class="wait-state__explainer">
      <summary>${escapeHtml(SEARCH_WAIT_WHY_LABEL)}</summary>
      <div class="wait-state__explainer-body">
        <p class="wait-state__explainer-copy">${escapeHtml(SEARCH_WAIT_WHY_COPY)}</p>
      </div>
    </details>
  `;
}

export function renderWaitState(mount, state) {
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
  const progressMarkup = renderProgressMarkup(normalized);
  const wasExplainerOpen = Boolean(mount.querySelector('.wait-state__explainer')?.open);
  mount.hidden = false;
  document.body.classList.add('job-hunter-wait-active');
  mount.innerHTML = `
    <div class="job-hunter-wait-backdrop" aria-hidden="true"></div>
    <div class="job-hunter-wait-shell">
      <section class="wait-state" role="dialog" aria-modal="true" aria-labelledby="job_hunter_wait_title">
        <span class="wait-state__spinner" aria-hidden="true"></span>
        <p class="wait-state__title" id="job_hunter_wait_title">${escapeHtml(normalized.title)}</p>
        ${normalized.copy ? `<p class="wait-state__copy">${escapeHtml(normalized.copy)}</p>` : ''}
        ${progressMarkup ? `<div class="wait-state__live" role="status" aria-live="polite" aria-atomic="true">${progressMarkup}</div>` : ''}
        ${shouldRenderSearchWhy(normalized) ? renderSearchWhyMarkup() : ''}
        ${normalized.subcopy ? `<p class="wait-state__subcopy">${escapeHtml(normalized.subcopy)}</p>` : ''}
        ${normalized.allowStop ? `
          <div class="wait-state__actions">
            <button class="btn btn-secondary" id="ws_stop_search_btn" type="button">${escapeHtml(SEARCH_STOP_LABEL)}</button>
          </div>
        ` : ''}
      </section>
    </div>
  `;
  if (wasExplainerOpen) {
    const explainer = mount.querySelector('.wait-state__explainer');
    if (explainer) {
      explainer.open = true;
    }
  }
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
      return currentState
        ? { ...currentState, progressDetail: currentState.progressDetail ? { ...currentState.progressDetail } : null }
        : null;
    },
  };
}
