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
