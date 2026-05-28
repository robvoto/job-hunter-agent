/**
 * @file console-bridge.js
 * @description Debug-mode only. Patches window.console to forward log output to the server
 *   via /api/debug/browser-log for unified server-side visibility. Also captures unhandled
 *   errors and promise rejections. No-ops entirely when not in debug mode.
 * @author hernanvoto
 * @created 2026-05-27
 */

// Modules are evaluated once per page — no double-registration guard needed.

const debugMode = window.__JOB_HUNTER_DEBUG_MODE__ === true;
if (!debugMode) {
  // Nothing to do outside debug mode.
} else {
  const endpoint = '/api/debug/browser-log';
  const nativeConsole = {};
  const methods = ['log', 'info', 'warn', 'error', 'debug'];

  for (const method of methods) {
    nativeConsole[method] = typeof console[method] === 'function'
      ? console[method].bind(console)
      : console.log.bind(console);
  }

  // Human-readable explanations for known rejection reason codes surfaced in browser errors.
  const REJECTION_DESCRIPTIONS = {
    'DESC_ROLE_PROOF_MISSING': 'Validation check: The job requires a seniority level or domain experience not clearly found in your profile.',
    'DESC_CAPABILITY_LOW': 'Validation check: Job requires capabilities that are not strongly represented in your profile.',
    'TITLE_BAD_KEYWORD': 'Title filter: The job title contains a phrase you have explicitly blocked.',
    'TITLE_NOT_TARGET': 'Title filter: The job title does not match any of your primary or secondary target patterns.',
  };

  nativeConsole.error = typeof console.error === 'function'
    ? console.error.bind(console)
    : console.log.bind(console);

  function truncate(value, limit = 2000) {
    const text = String(value ?? '');
    for (const [code, desc] of Object.entries(REJECTION_DESCRIPTIONS)) {
      const marker = `[${code}]`;
      if (text.includes(marker)) {
        const parts = text.split(marker);
        const rejectedContent = parts.length > 1 ? parts[1].trim() : '';
        const detail = rejectedContent ? ` - Found: "${rejectedContent}"` : '';
        return `${text} (NOTE: This is a Validation Rejection, not a system error. ${desc}${detail})`;
      }
    }
    if (text.includes('max_llm_chars_limits')) {
      return `${text} (System Info: These are your configured character limits for AI prompts, not an error.)`;
    }
    return text.length <= limit ? text : `${text.slice(0, limit)}...`;
  }

  function expandUrl(text) {
    if (typeof text !== 'string') return text;
    const isSeek = text.includes('seek.com.au/jobs');
    const isLinkedIn = text.includes('linkedin.com/jobs');
    if (!isSeek && !isLinkedIn) return text;
    try {
      const urlMatch = text.match(/https?:\/\/[^\s]+/);
      if (!urlMatch) return text;
      const url = new URL(urlMatch[0]);
      const source = isSeek ? 'SEEK' : 'LinkedIn';
      let breakdown = `\n\n[${source} URL Breakdown]\nBase: ${url.origin}${url.pathname}\nParams:\n`;
      url.searchParams.forEach((v, k) => {
        breakdown += `  • ${k.padEnd(16)}: ${v}\n`;
      });
      return text + breakdown;
    } catch {
      return text;
    }
  }

  function describeValue(value) {
    if (value instanceof Error) {
      return truncate(value.stack || `${value.name}: ${value.message}`);
    }
    if (typeof value === 'string') {
      return truncate(expandUrl(value));
    }
    if (typeof value === 'function') {
      return truncate(`[Function ${value.name || 'anonymous'}]`);
    }
    if (typeof value === 'bigint') {
      return `${value}n`;
    }
    if (value === null || value === undefined) {
      return String(value);
    }
    try {
      const seen = new WeakSet();
      const text = JSON.stringify(value, (key, nestedValue) => {
        if (nestedValue instanceof Error) {
          return { name: nestedValue.name, message: nestedValue.message, stack: nestedValue.stack };
        }
        if (typeof nestedValue === 'function') {
          return `[Function ${nestedValue.name || 'anonymous'}]`;
        }
        if (typeof nestedValue === 'bigint') {
          return `${nestedValue}n`;
        }
        if (nestedValue && typeof nestedValue === 'object') {
          if (seen.has(nestedValue)) return '[Circular]';
          seen.add(nestedValue);
        }
        return nestedValue;
      }, 2);
      return truncate(text === undefined ? String(value) : text);
    } catch {
      return truncate(String(value));
    }
  }

  function postLog(payload) {
    const body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon) {
        const sent = navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }));
        if (sent) return;
      }
    } catch {
      // Fall back to fetch below.
    }
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {});
  }

  function emit(level, args, extra = {}) {
    const formattedArgs = args.map(describeValue);
    postLog({
      level,
      message: formattedArgs.join(' ').trim(),
      args: formattedArgs,
      href: window.location.href,
      title: document.title || '',
      timestamp: new Date().toISOString(),
      ...extra,
    });
  }

  for (const method of methods) {
    console[method] = (...args) => {
      const displayArgs = args.map(arg => (typeof arg === 'string' ? expandUrl(arg) : arg));
      nativeConsole[method](...displayArgs);
      emit(method, args);
    };
  }

  window.addEventListener('error', (event) => {
    const error = event.error instanceof Error
      ? event.error
      : new Error(event.message || 'Unhandled browser error');
    nativeConsole.error(error);
    emit('error', [error], {
      kind: 'window.error',
      source: event.filename || '',
      line: event.lineno || null,
      column: event.colno || null,
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason instanceof Error
      ? event.reason
      : new Error(typeof event.reason === 'string' ? event.reason : 'Unhandled promise rejection');
    nativeConsole.error(reason);
    emit('error', [reason], { kind: 'unhandledrejection' });
  });
}
