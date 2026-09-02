/**
 * Browser-side OSINT agent loop.
 *
 * runAgentLoop(message, history, adapterSettings, toolKeys, onEvent, signal?)
 *
 * adapterSettings: { provider, apiKey, baseUrl, model }
 * toolKeys:        { [ENV_VAR_NAME]: "value", ... }  — tool API keys from sessionStorage
 * onEvent:         function({ type, ... }) — same shape as the server SSE events:
 *   { type: 'text',           content }
 *   { type: 'tool_start',     tool, input }
 *   { type: 'tool_result',    tool, output, elapsed, isDemo }
 *   { type: 'tool_demo_badge',tool }
 *   { type: 'key_required',   tool, missing_keys, how_to_get }
 *   { type: 'max_rounds' }
 *   { type: 'error',          message }
 *   { type: 'done' }
 * signal:          optional AbortSignal for cancellation
 */

import { createAdapter } from '/static/adapters.js';
import { splitGeojsonFence } from '/static/geo-extractor.js';

const MAX_ROUNDS = 8;
const TOOL_TIMEOUT_MS = 120_000;

// ---------------------------------------------------------------------------
// Tool catalog cache (fetched once per page load)
// ---------------------------------------------------------------------------

let _toolCatalog = null;

async function _fetchToolCatalog() {
  if (_toolCatalog) return _toolCatalog;
  const base = (window.OPENOSINT_CONFIG?.proxyBaseUrl || '').replace(/\/$/, '');
  const resp = await fetch(`${base}/api/tools`);
  if (!resp.ok) throw new Error(`Failed to fetch tool catalog: HTTP ${resp.status}`);
  _toolCatalog = await resp.json();
  return _toolCatalog;
}

// ---------------------------------------------------------------------------
// Type-B demo stubs — obviously fake, static, clearly labeled
// ---------------------------------------------------------------------------

const _TYPE_B_DEMO = {
  search_email: `[DEMO DATA — install holehe: pip install holehe]
[+] github.com     — demo@example.com registered (sample)
[+] spotify.com    — demo@example.com registered (sample)
[-] twitter.com    — not found (sample)
[*] Holehe scan complete — 2 of 3 checked (SAMPLE OUTPUT — not a real result)`,

  search_username: `[DEMO DATA — install sherlock: pip install sherlock-project]
[+] GitHub         https://github.com/demouser (sample)
[+] Reddit         https://reddit.com/u/demouser (sample)
[-] Instagram      not found (sample)
[*] Sherlock scan complete — 2 of 3 platforms (SAMPLE OUTPUT — not a real result)`,

  search_domain: `[DEMO DATA — install sublist3r: pip install sublist3r]
[+] www.example.com     (sample subdomain)
[+] mail.example.com    (sample subdomain)
[+] api.example.com     (sample subdomain)
[*] Sublist3r found 3 subdomains (SAMPLE OUTPUT — not a real result)`,

  search_phone: `[DEMO DATA — install phoneinfoga: github.com/sundowndev/phoneinfoga/releases]
[+] Number:    +14155550100 (sample)
[+] Country:   US
[+] Carrier:   Sample Carrier LLC (sample)
[+] Line type: mobile (sample)
[*] PhoneInfoga scan complete (SAMPLE OUTPUT — not a real result)`,
};

function _getDemoOutput(toolName) {
  return (
    _TYPE_B_DEMO[toolName] ||
    `[DEMO DATA — this tool requires a local binary]\n` +
    `[*] See README for install instructions (SAMPLE OUTPUT — not a real result)`
  );
}

// ---------------------------------------------------------------------------
// Build tool definitions in Anthropic input_schema shape (adapters convert internally)
// ---------------------------------------------------------------------------

function _buildToolDefs(catalog) {
  return catalog.map(t => ({
    name: t.name,
    description: t.description,
    input_schema: t.parameters || {
      type: 'object',
      properties: { input: { type: 'string', description: t.input_label || 'Target' } },
      required: ['input'],
    },
  }));
}

// ---------------------------------------------------------------------------
// Key filtering — send only the required keys for each tool, never the LLM key
// ---------------------------------------------------------------------------

function _keysForTool(tool, allToolKeys) {
  const required = tool.required_keys || [];
  if (!required.length) return {};
  const out = {};
  for (const k of required) {
    if (allToolKeys[k]) out[k] = allToolKeys[k];
  }
  return out;
}

// ---------------------------------------------------------------------------
// Type-A proxy call with per-tool AbortController
// ---------------------------------------------------------------------------

async function _callTypeA(tool, inputValue, toolKeys, outerSignal) {
  const base = (window.OPENOSINT_CONFIG?.proxyBaseUrl || '').replace(/\/$/, '');
  const apiKeys = _keysForTool(tool, toolKeys);

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TOOL_TIMEOUT_MS);
  if (outerSignal) {
    outerSignal.addEventListener('abort', () => ac.abort(), { once: true });
  }

  const t0 = performance.now();
  let resp;
  try {
    resp = await fetch(`${base}/api/run/${tool.name}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ input: inputValue, timeout: 120, api_keys: apiKeys }),
      signal: ac.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (err.name === 'AbortError') return { output: 'Tool call timed out or was cancelled.', isError: true };
    return { output: `Network error calling ${tool.name}: ${err.message}`, isError: true };
  } finally {
    clearTimeout(timer);
  }

  const elapsed = ((performance.now() - t0) / 1000).toFixed(2);

  if (resp.status === 429) {
    return { output: 'Rate limit exceeded — please wait before retrying.', isError: true, elapsed };
  }

  let data;
  try { data = await resp.json(); } catch {
    return { output: `Malformed response from proxy (HTTP ${resp.status})`, isError: true, elapsed };
  }

  if (data.key_required) {
    return { keyRequired: true, missingKeys: data.missing_keys || [], howToGet: data.how_to_get || {}, elapsed };
  }

  if (data.status === 'error') {
    return { output: data.output || data.error || 'Tool returned an error.', isError: true, elapsed };
  }

  return { output: data.output || '', elapsed: data.elapsed ?? elapsed };
}

// ---------------------------------------------------------------------------
// Main exported function
// ---------------------------------------------------------------------------

export async function runAgentLoop(message, history, adapterSettings, toolKeys, onEvent, outerSignal) {
  let catalog;
  try {
    catalog = await _fetchToolCatalog();
  } catch (err) {
    onEvent({ type: 'error', message: `Cannot load tool catalog: ${err.message}` });
    return;
  }

  const toolDefs = _buildToolDefs(catalog);
  const toolMap = Object.fromEntries(catalog.map(t => [t.name, t]));

  let adapter;
  try {
    adapter = createAdapter(adapterSettings.provider, adapterSettings);
  } catch (err) {
    onEvent({ type: 'error', message: err.message });
    return;
  }

  // Build initial message list from history + new user message.
  let messages = [];
  for (const h of history) {
    if ((h.role === 'user' || h.role === 'assistant') && h.content) {
      messages.push({ role: h.role, content: h.content });
    }
  }
  messages.push({ role: 'user', content: message });

  let rounds = 0;

  while (true) {
    rounds++;
    if (rounds > MAX_ROUNDS) {
      onEvent({ type: 'max_rounds' });
      return;
    }

    let response;
    try {
      response = await adapter.chat(messages, toolDefs, outerSignal);
    } catch (err) {
      if (err.name === 'AbortError') { onEvent({ type: 'done' }); return; }
      onEvent({ type: 'error', message: err.message });
      return;
    }

    if (response.text) {
      onEvent({ type: 'text', content: response.text });
    }

    if (!response.toolCalls?.length) {
      onEvent({ type: 'done' });
      return;
    }

    for (const call of response.toolCalls) {
      const tool = toolMap[call.name];
      const inputValue =
        call.input?.input ||
        Object.values(call.input || {}).find(v => typeof v === 'string') ||
        '';

      // tool_start fires immediately — triggers spinner in the UI.
      onEvent({ type: 'tool_start', tool: call.name, input: String(inputValue) });

      let resultText;

      if (!tool || tool.tool_type === 'B') {
        // Type-B: return demo stub, never call the backend.
        resultText = _getDemoOutput(call.name);
        onEvent({ type: 'tool_result', tool: call.name, output: resultText, elapsed: 0, isDemo: true });
        onEvent({ type: 'tool_demo_badge', tool: call.name });
      } else {
        // Type-A: proxy call.
        const result = await _callTypeA(tool, inputValue, toolKeys, outerSignal);

        if (result.keyRequired) {
          onEvent({
            type: 'key_required',
            tool: call.name,
            missing_keys: result.missingKeys,
            how_to_get: result.howToGet,
          });
          return;
        }

        resultText = result.output || '';
        onEvent({
          type: 'tool_result',
          tool: call.name,
          output: resultText,
          elapsed: result.elapsed ?? 0,
          isError: result.isError || false,
        });
      }

      // Feed the result back into the conversation (provider-specific
      // format). Strip any geojson fence first — the provider gets resent
      // this whole message list on every subsequent round; the browser
      // already got the full resultText via the tool_result event above.
      const [modelText] = splitGeojsonFence(resultText);
      messages = adapter.appendToolResult(messages, call, modelText);
    }
  }
}
