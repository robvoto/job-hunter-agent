(() => {
  if (window.__JOB_HUNTER_CONSOLE_BRIDGE__) {
    return;
  }

  const debugMode = window.__JOB_HUNTER_DEBUG_MODE__ === true;
  if (!debugMode) {
    return;
  }

  window.__JOB_HUNTER_CONSOLE_BRIDGE__ = true;

  const endpoint = '/api/debug/browser-log';
  const nativeConsole = {};
  const methods = ['log', 'info', 'warn', 'error', 'debug'];

  for (const method of methods) {
    nativeConsole[method] = typeof console[method] === 'function'
      ? console[method].bind(console)
      : console.log.bind(console);
  }

  nativeConsole.error = typeof console.error === 'function'
    ? console.error.bind(console)
    : console.log.bind(console);

  function truncate(value, limit = 2000) {
    const text = String(value ?? '');
    return text.length <= limit ? text : `${text.slice(0, limit)}...`;
  }

  function describeValue(value) {
    if (value instanceof Error) {
      return truncate(value.stack || `${value.name}: ${value.message}`);
    }
    if (typeof value === 'string') {
      return truncate(value);
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
          return {
            name: nestedValue.name,
            message: nestedValue.message,
            stack: nestedValue.stack,
          };
        }
        if (typeof nestedValue === 'function') {
          return `[Function ${nestedValue.name || 'anonymous'}]`;
        }
        if (typeof nestedValue === 'bigint') {
          return `${nestedValue}n`;
        }
        if (nestedValue && typeof nestedValue === 'object') {
          if (seen.has(nestedValue)) {
            return '[Circular]';
          }
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
        const sent = navigator.sendBeacon(
          endpoint,
          new Blob([body], { type: 'application/json' })
        );
        if (sent) {
          return;
        }
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
    const payload = {
      level,
      message: formattedArgs.join(' ').trim(),
      args: formattedArgs,
      href: window.location.href,
      title: document.title || '',
      timestamp: new Date().toISOString(),
      ...extra,
    };
    postLog(payload);
  }

  for (const method of methods) {
    console[method] = (...args) => {
      nativeConsole[method](...args);
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
    emit('error', [reason], {
      kind: 'unhandledrejection',
    });
  });
})();
