const sharedUiLabels = window.__JOB_HUNTER_SHARED_UI_LABELS__;

if (!sharedUiLabels) {
  throw new Error('Missing shared UI labels.');
}

const removeItemLabelTemplate = String(sharedUiLabels.remove_item_label || '').trim();
const removeItemFallbackLabel = String(sharedUiLabels.remove_item_fallback_label || '').trim();

if (!removeItemLabelTemplate || !removeItemFallbackLabel) {
  throw new Error('Missing shared remove-item labels.');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatRemoveItemLabel(itemName) {
  const name = String(itemName || '').replace(/\s+/g, ' ').trim();
  if (!name) return removeItemFallbackLabel;
  return removeItemLabelTemplate.replace('{name}', name);
}

function renderDataAttributes(dataAttributes) {
  return Object.entries(dataAttributes || {}).map(([name, value]) => {
    if (!/^data-[a-z0-9-]+$/.test(name)) {
      throw new Error(`Invalid data attribute for shared action button: ${name}`);
    }
    return ` ${name}="${escapeHtml(value)}"`;
  }).join('');
}

function renderTrashActionButton({ itemName = '', dataAttributes = {}, disabled = false } = {}) {
  const label = formatRemoveItemLabel(itemName);
  return `<button class="jh-icon-button jh-icon-button--destructive jh-icon-button--trash" type="button"${renderDataAttributes(dataAttributes)}${disabled ? ' disabled' : ''} aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M9 3.5h6l1 1.5H19v2H5v-2h3l1-1.5Zm-1 5h8l-.6 9.3A2 2 0 0 1 13.4 20H10.6a2 2 0 0 1-1.99-1.7L8 8.5Zm2 2v6m4-6v6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path>
    </svg>
  </button>`;
}

export { formatRemoveItemLabel, renderTrashActionButton };
