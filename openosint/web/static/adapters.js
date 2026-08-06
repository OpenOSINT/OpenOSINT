/**
 * Provider adapter layer — normalized interface over Anthropic, OpenAI-compat, and Ollama.
 *
 * Each adapter exposes:
 *   chat(messages, tools, signal?)
 *     → Promise<{ text: string|null, toolCalls: [{id, name, input}], stopReason: string }>
 *
 *   appendToolResult(messages, call, content)
 *     → new messages array (immutable — never mutates original)
 *
 * Tool definitions passed to chat() always use the Anthropic input_schema shape
 * ({name, description, input_schema}). Adapters internally convert to their own format.
 */

// ---------------------------------------------------------------------------
// Anthropic adapter
// ---------------------------------------------------------------------------

class AnthropicAdapter {
  constructor({ apiKey, model }) {
    this.apiKey = apiKey;
    this.model = model || 'claude-sonnet-4-6';
  }

  async chat(messages, tools, signal) {
    const body = {
      model: this.model,
      max_tokens: 4096,
      system: _SYSTEM_PROMPT,
      tools,
      messages,
    };

    let resp;
    try {
      resp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-api-key': this.apiKey,
          'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true',
        },
        body: JSON.stringify(body),
        signal,
      });
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      throw new Error(`Anthropic API unreachable: ${err.message}`);
    }

    if (!resp.ok) {
      let msg = `Anthropic API error ${resp.status}`;
      try { const d = await resp.json(); msg += ': ' + (d.error?.message || JSON.stringify(d)); } catch {}
      throw new Error(msg);
    }

    const data = await resp.json();
    const text = (data.content || []).filter(b => b.type === 'text').map(b => b.text).join('') || null;
    const toolCalls = (data.content || [])
      .filter(b => b.type === 'tool_use')
      .map(b => ({ id: b.id, name: b.name, input: b.input || {}, _rawContent: data.content }));

    return { text, toolCalls, stopReason: data.stop_reason || 'end_turn', _rawContent: data.content };
  }

  appendToolResult(messages, call, content) {
    const assistantContent = call._rawContent || [{ type: 'tool_use', id: call.id, name: call.name, input: call.input }];
    return [
      ...messages,
      { role: 'assistant', content: assistantContent },
      { role: 'user', content: [{ type: 'tool_result', tool_use_id: call.id, content }] },
    ];
  }
}

// ---------------------------------------------------------------------------
// OpenAI-compatible adapter (OpenRouter, OrcaRouter, vLLM, LiteLLM, llama.cpp, etc.)
// ---------------------------------------------------------------------------

class OpenAIAdapter {
  constructor({ apiKey, baseUrl, model }) {
    this.apiKey = apiKey || '';
    this.baseUrl = (baseUrl || '').replace(/\/$/, '');
    this.model = model || 'gpt-4o-mini';
  }

  _toOpenAITools(tools) {
    return tools.map(t => ({
      type: 'function',
      function: { name: t.name, description: t.description, parameters: t.input_schema },
    }));
  }

  async chat(messages, tools, signal) {
    if (!this.baseUrl) throw new Error('OpenAI-compat: Base URL is required.');

    // api.openai.com blocks browser CORS preflights — surface a clear error early.
    if (/api\.openai\.com/i.test(this.baseUrl)) {
      throw new Error(
        "OpenAI's production API (api.openai.com) blocks direct browser requests via CORS. " +
        'Use OpenRouter (https://openrouter.ai/api/v1), OrcaRouter (https://api.orcarouter.ai/v1), or a local endpoint instead.'
      );
    }

    const headers = { 'content-type': 'application/json', 'x-title': 'OpenOSINT' };
    if (this.apiKey) headers['authorization'] = `Bearer ${this.apiKey}`;

    const body = {
      model: this.model,
      messages,
      tools: this._toOpenAITools(tools),
      tool_choice: 'auto',
      stream: false,
    };

    let resp;
    try {
      resp = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal,
      });
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      throw new Error(`OpenAI-compat endpoint unreachable: ${err.message}`);
    }

    if (!resp.ok) {
      let msg = `OpenAI-compat error ${resp.status}`;
      try { const d = await resp.json(); msg += ': ' + (d.error?.message || JSON.stringify(d)); } catch {}
      throw new Error(msg);
    }

    const data = await resp.json();
    const choices = data.choices || [];
    if (!choices.length) throw new Error('OpenAI-compat returned no choices: ' + JSON.stringify(data).slice(0, 200));

    const msg = choices[0].message || {};
    const text = msg.content || null;
    const rawCalls = msg.tool_calls || [];
    const toolCalls = rawCalls.map(tc => {
      let input = tc.function?.arguments || {};
      if (typeof input === 'string') { try { input = JSON.parse(input); } catch { input = { input }; } }
      return { id: tc.id || String(Math.random()), name: tc.function?.name || '', input, _rawCalls: rawCalls };
    });

    return { text, toolCalls, stopReason: toolCalls.length ? 'tool_use' : 'end_turn' };
  }

  appendToolResult(messages, call, content) {
    const rawCalls = call._rawCalls || [{
      id: call.id,
      type: 'function',
      function: { name: call.name, arguments: JSON.stringify(call.input) },
    }];
    const lastMsg = messages.at(-1);
    // Append to existing assistant tool_calls turn if already there, else create it.
    if (lastMsg?.role === 'assistant' && lastMsg.tool_calls?.length) {
      return [...messages, { role: 'tool', tool_call_id: call.id, content }];
    }
    return [
      ...messages,
      { role: 'assistant', content: null, tool_calls: rawCalls },
      { role: 'tool', tool_call_id: call.id, content },
    ];
  }
}

// ---------------------------------------------------------------------------
// Ollama adapter
// ---------------------------------------------------------------------------

class OllamaAdapter {
  constructor({ baseUrl, model }) {
    this.baseUrl = (baseUrl || 'http://localhost:11434').replace(/\/$/, '');
    this.model = model || 'llama3.2';
  }

  _toOllamaTools(tools) {
    return tools.map(t => ({
      type: 'function',
      function: { name: t.name, description: t.description, parameters: t.input_schema },
    }));
  }

  async chat(messages, tools, signal) {
    const body = {
      model: this.model,
      messages,
      tools: this._toOllamaTools(tools),
      stream: false,
    };

    let resp;
    try {
      resp = await fetch(`${this.baseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      });
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      const isCors = err.message.includes('Failed to fetch') || err.message.includes('NetworkError');
      const hint = isCors
        ? ` Ollama may be blocking this origin — start with: OLLAMA_ORIGINS="${window.location.origin}" ollama serve`
        : '';
      throw new Error(`Ollama unreachable: ${err.message}.${hint}`);
    }

    if (!resp.ok) {
      let msg = `Ollama error ${resp.status}`;
      try { const d = await resp.json(); msg += ': ' + (d.error || JSON.stringify(d)); } catch {}
      throw new Error(msg);
    }

    const data = await resp.json();
    const msg = data.message || {};
    const text = msg.content || null;
    const rawCalls = msg.tool_calls || [];
    const toolCalls = rawCalls.map((tc, i) => {
      let input = tc.function?.arguments || {};
      if (typeof input === 'string') { try { input = JSON.parse(input); } catch { input = { input }; } }
      return { id: `ollama-${i}`, name: tc.function?.name || '', input };
    });

    return { text, toolCalls, stopReason: toolCalls.length ? 'tool_use' : 'end_turn' };
  }

  appendToolResult(messages, call, content) {
    const lastMsg = messages.at(-1);
    if (lastMsg?.role === 'assistant') {
      return [...messages, { role: 'tool', content }];
    }
    return [
      ...messages,
      { role: 'assistant', content: '', tool_calls: [{ function: { name: call.name, arguments: call.input } }] },
      { role: 'tool', content },
    ];
  }
}

// ---------------------------------------------------------------------------
// Shared system prompt
// ---------------------------------------------------------------------------

const _SYSTEM_PROMPT =
  'You are OpenOSINT, an AI-powered OSINT investigation assistant. ' +
  'When the user asks you to investigate a target, use the available tools to gather intelligence. ' +
  'Summarize findings clearly and highlight anything suspicious or notable. ' +
  'Always clarify what tools you used and what each result means.';

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * createAdapter(provider, options) → Adapter instance
 * provider: 'anthropic' | 'openai' | 'ollama'
 */
export function createAdapter(provider, options = {}) {
  switch (provider) {
    case 'anthropic': return new AnthropicAdapter(options);
    case 'openai':    return new OpenAIAdapter(options);
    case 'ollama':    return new OllamaAdapter(options);
    default:          throw new Error(`Unknown provider: ${provider}`);
  }
}

export { AnthropicAdapter, OpenAIAdapter, OllamaAdapter };
