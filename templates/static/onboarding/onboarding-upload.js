import { escapeHtml } from '../settings/shared/settings-utils.js';

let uploadDeps = null;

export function configureOnboardingUpload(deps) {
  uploadDeps = deps || null;
}

function getDeps() {
  if (!uploadDeps) {
    throw new Error('Onboarding upload helpers are not configured.');
  }
  return uploadDeps;
}

function getRefs() {
  return getDeps().refs;
}

function getPreservedPrimaryCvFile() {
  return getDeps().getPreservedPrimaryCvFile?.() || null;
}

function setPreservedPrimaryCvFile(value) {
  getDeps().setPreservedPrimaryCvFile?.(value);
}

function getDraftBuiltExplicitly() {
  return Boolean(getDeps().getDraftBuiltExplicitly?.());
}

function resetPrimaryCvDropZoneAppearance() {
  const { primaryCvDropZone } = getRefs();
  if (!primaryCvDropZone) return;
  primaryCvDropZone.classList.remove('is-dragover');
}

export function updatePrimaryCvStatus(file) {
  const { primaryCvDropZone, cvDropZoneContent: primaryCvDropZoneContentEl } = getRefs();
  const { primaryCvCopy } = getDeps();
  if (!primaryCvDropZoneContentEl) return;

  if (!file) {
    primaryCvDropZone?.classList.remove('has-file');
    primaryCvDropZoneContentEl.innerHTML = `
      <div class="drop-zone-content-shell">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon upload-icon--empty" aria-hidden="true" focusable="false"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
        <p class="drop-zone-empty-title">${escapeHtml(primaryCvCopy.emptyTitle)}</p>
        <p class="drop-zone-hint drop-zone-empty-hint">${escapeHtml(primaryCvCopy.emptyHint)}</p>
      </div>
    `;
    resetPrimaryCvDropZoneAppearance();
    return;
  }

  primaryCvDropZone?.classList.add('has-file');
  resetPrimaryCvDropZoneAppearance();
  getDeps().hideStatus?.();

  primaryCvDropZoneContentEl.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="upload-icon upload-icon--loaded" aria-hidden="true" focusable="false"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
    <p class="file-loaded-label">File Loaded: ${escapeHtml(file.name)}</p>
    <p class="drop-zone-hint">${escapeHtml(primaryCvCopy.loadedHint)}</p>
  `;
}

export function updateCreateProfileAvailability() {
  const { primaryCvInput, createProfileButton, continueToReview } = getRefs();
  if (!createProfileButton) return;
  createProfileButton.disabled = !primaryCvInput?.files?.[0];
  if (continueToReview) {
    continueToReview.hidden = !getDraftBuiltExplicitly() || !primaryCvInput?.files?.[0];
  }
}

export function restorePrimaryCvSelection(file) {
  const { primaryCvInput } = getRefs();
  if (!primaryCvInput || !file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  primaryCvInput.files = transfer.files;
}

export function validatePrimaryFile(file) {
  if (!file) {
    throw new Error('Choose your detailed CV first.');
  }
  const name = String(file.name || '').toLowerCase();
  if (!name.endsWith('.docx') && !name.endsWith('.pdf') && !name.endsWith('.md') && !name.endsWith('.txt')) {
    throw new Error('Please upload a .docx, .pdf, .md, or .txt CV file.');
  }
}

export function assignPrimaryCvFile(file) {
  const { primaryCvInput } = getRefs();
  if (!primaryCvInput || !file) return;
  restorePrimaryCvSelection(file);
  setPreservedPrimaryCvFile(file);
  updatePrimaryCvStatus(file);
  getDeps().hideStatus?.();
  updateCreateProfileAvailability();
  getDeps().refreshStepNavigation?.();
}

export async function fileToPayload(file, label) {
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

export function handlePrimaryCvDrop(event) {
  const { primaryCvDropZone } = getRefs();
  event.preventDefault();
  event.stopPropagation();
  if (!primaryCvDropZone) return;
  primaryCvDropZone.classList.remove('is-dragover');
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  try {
    validatePrimaryFile(file);
  } catch (error) {
    getDeps().showStatus?.(error.message, 'error');
    updatePrimaryCvStatus(null);
    return;
  }
  assignPrimaryCvFile(file);
  getDeps().hideStatus?.();
}

