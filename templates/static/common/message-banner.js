function normalizeKind(kind) {
  const value = String(kind || '').trim().toLowerCase();
  if (value === 'success' || value === 'warning' || value === 'error' || value === 'loading' || value === 'info') {
    return value;
  }
  return 'info';
}

function normalizeState(message, kind, options = {}) {
  return {
    message: String(message || '').trim(),
    kind: normalizeKind(kind),
    autoHideMs: Number(options.autoHideMs || 0),
  };
}

function sameState(left, right) {
  return Boolean(left) && Boolean(right)
    && left.message === right.message
    && left.kind === right.kind
    && left.autoHideMs === right.autoHideMs;
}

function renderBanner(mount, state) {
  if (!mount) {
    return;
  }
  if (!state || !state.message) {
    mount.hidden = true;
    mount.textContent = '';
    mount.className = 'jh-message-banner';
    mount.removeAttribute('role');
    mount.removeAttribute('aria-live');
    return;
  }

  mount.hidden = false;
  mount.className = `jh-message-banner is-visible is-${state.kind}`;
  mount.textContent = state.message;
  mount.setAttribute('role', state.kind === 'error' ? 'alert' : 'status');
  mount.setAttribute('aria-live', state.kind === 'error' ? 'assertive' : 'polite');
}

export function createController(mount) {
  let currentState = null;
  let hideTimer = null;

  function clearTimer() {
    if (hideTimer) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  return {
    show(message, kind, options = {}) {
      const nextState = normalizeState(message, kind, options);
      if (!nextState.message) {
        this.hide();
        return;
      }
      if (sameState(currentState, nextState)) {
        return;
      }
      clearTimer();
      currentState = nextState;
      renderBanner(mount, currentState);
      if (currentState.autoHideMs > 0) {
        hideTimer = window.setTimeout(() => {
          this.hide();
        }, currentState.autoHideMs);
      }
    },

    hide() {
      clearTimer();
      currentState = null;
      renderBanner(mount, null);
    },

    getState() {
      return currentState ? { ...currentState } : null;
    },
  };
}
