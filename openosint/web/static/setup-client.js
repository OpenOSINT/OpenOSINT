// Pure helpers for the "Save keys to server" form: no DOM, no fetch, so they can be
// unit-tested in Node (tests/test_setup_client.mjs). index.html does the I/O.

const GROUP_TITLES = {
  ai: 'AI provider',
  tools: 'Tool keys',
  optional: 'Optional — higher rate limits',
};

// Fields come from GET /api/setup/status (the server's settings catalog), so the form
// can never drift from what /api/setup accepts.
export function groupFields(fields) {
  const bucket = (f) => (f.group === 'ai' ? 'ai' : f.optional ? 'optional' : 'tools');
  return ['ai', 'tools', 'optional']
    .map((id) => ({ id, title: GROUP_TITLES[id], fields: (fields || []).filter((f) => bucket(f) === id) }))
    .filter((g) => g.fields.length > 0);
}

// Only keys the server listed, only non-empty values, trimmed.
export function buildSetupBody(fields, values) {
  const body = {};
  for (const f of fields || []) {
    const v = String((values || {})[f.key] ?? '').trim();
    if (v) body[f.key] = v;
  }
  return body;
}

export function setupHeaders(token) {
  const headers = { 'Content-Type': 'application/json' };
  const t = String(token || '').trim();
  if (t) headers['X-Setup-Token'] = t;
  return headers;
}

// Turns the server's answer into one message for the user. Never includes a value.
export function describeSetupResult(status, data) {
  const d = data && typeof data === 'object' ? data : {};
  if (status < 200 || status >= 300) {
    return { ok: false, message: d.message || `Save failed (HTTP ${status}).` };
  }
  const applied = d.applied || [];
  const shadowed = d.shadowed_by_environment || [];
  const rejected = d.rejected || [];
  const parts = [];
  if (applied.length) parts.push(`Saved ${applied.join(', ')}${d.saved_to ? ` to ${d.saved_to}` : ''}.`);
  if (shadowed.length) {
    parts.push(
      `${shadowed.join(', ')} saved but not active: a real environment variable of the same name ` +
        'takes precedence. Unset it and restart.'
    );
  }
  if (rejected.length) parts.push(`Not accepted: ${rejected.join(', ')}.`);
  if (!parts.length) return { ok: false, message: 'Nothing to save.' };
  return { ok: applied.length > 0, message: parts.join(' ') };
}

// What the first-run panel tells the user, derived from GET /api/tools.
export function summarizeTools(tools) {
  const list = Array.isArray(tools) ? tools : [];
  const needsKey = (t) => (t.required_keys || []).length > 0;
  return {
    working: list.filter((t) => t.available && !needsKey(t)).map((t) => t.name),
    needKey: list.filter(needsKey).map((t) => t.name),
    needInstall: list.filter((t) => !t.available && !needsKey(t)).map((t) => t.name),
  };
}
