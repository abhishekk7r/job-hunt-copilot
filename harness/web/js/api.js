/**
 * api.js - Control Room HTTP Client
 * Zero external dependencies. Communicates with localhost daemon only.
 */

let lastStateEtag = null;

export function getToken() {
  const meta = document.querySelector('meta[name="ctl-token"]');
  return meta ? meta.getAttribute('content') || '' : '';
}

/**
 * Fetches compact system state from /api/state with ETag support.
 * Returns null if 304 Not Modified.
 */
export async function fetchState() {
  const headers = { 'Accept': 'application/json' };
  if (lastStateEtag) {
    headers['If-None-Match'] = lastStateEtag;
  }

  const res = await fetch('/api/state', {
    method: 'GET',
    headers,
    cache: 'no-cache',
  });

  if (res.status === 304) {
    return null; // Not modified
  }

  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    throw new Error(`State fetch failed [${res.status}]: ${errText}`);
  }

  const etag = res.headers.get('ETag');
  if (etag) {
    lastStateEtag = etag;
  }

  return await res.json();
}

/**
 * Reveals an application answer or screening answer by ID or key.
 * Requires X-Token header.
 */
export async function fetchAnswer(id) {
  const token = getToken();
  const res = await fetch(`/api/answers/${encodeURIComponent(id)}`, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
      'X-Token': token,
    },
    cache: 'no-cache',
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Failed to reveal answer' }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }

  return await res.json();
}

/**
 * Fetches answers list from /api/answers (e.g. status=drafted).
 */
export async function fetchAnswers(status = 'drafted') {
  const token = getToken();
  const url = status ? `/api/answers?status=${encodeURIComponent(status)}` : '/api/answers';
  const res = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
      'X-Token': token,
    },
    cache: 'no-cache',
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Failed to fetch answers' }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }

  return await res.json();
}

/**
 * Dispatches control operations to /ctl/{action}.
 * @param {'toggle'|'kill'|'run_now'|'mark'} action
 * @param {object} payload
 */
export async function postControl(action, payload = {}) {
  const token = getToken();
  const res = await fetch(`/ctl/${action}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Token': token,
    },
    body: JSON.stringify(payload),
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Action ${action} failed [${res.status}]`);
  }

  return data;
}
