/**
 * @file csrf.js
 * @description Sets window.jobHunterFetch — a fetch wrapper that automatically injects
 *   the CSRF token header on state-changing requests. Loaded as a plain (non-module)
 *   script so it runs synchronously and the global is available before any deferred
 *   module scripts execute.
 *
 *   NOT YET an ES module: converting it requires adding explicit imports to every
 *   module file that currently uses jobHunterFetch as a global (settings-page.js,
 *   onboarding-flow.js, signal-registry.js, settings-review-panel.js, and others).
 *   Migrate those consumers first, then convert this file and remove the window assignment.
 *
 * @author hernanvoto
 * @created 2026-05-27
 */
(() => {
  if (window.__JOB_HUNTER_CSRF_HELPER__) {
    return;
  }

  window.__JOB_HUNTER_CSRF_HELPER__ = true;

  const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

  function getToken() {
    const token = window.__JOB_HUNTER_CSRF_TOKEN__;
    return typeof token === 'string' ? token.trim() : '';
  }

  function getMethod(input, init) {
    const candidate = init?.method || input?.method || 'GET';
    return String(candidate).toUpperCase();
  }

  function mergeHeaders(initHeaders, inputHeaders, token, method) {
    const headers = new Headers(initHeaders || inputHeaders || {});
    if (!SAFE_METHODS.has(method) && token) {
      headers.set('X-CSRF-Token', token);
    }
    return headers;
  }

  window.jobHunterFetch = function jobHunterFetch(input, init = {}) {
    const method = getMethod(input, init);
    const token = getToken();
    const headers = mergeHeaders(init.headers, input && input.headers, token, method);
    return fetch(input, { ...init, method, headers });
  };
})();
