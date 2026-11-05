/**
 * Unit tests for provider adapters — no network, mock fetch.
 * Run: node tests/test_adapters.mjs
 */

import { createAdapter } from '../openosint/web/static/adapters.js';

let passed = 0;
let failed = 0;

function assert(condition, label) {
  if (condition) {
    console.log(`  ✓ ${label}`);
    passed++;
  } else {
    console.error(`  ✗ ${label}`);
    failed++;
  }
}

const SAMPLE_TOOLS = [
  {
    name: 'search_ip',
    description: 'Geolocate an IP',
    input_schema: {
      type: 'object',
      properties: { input: { type: 'string' } },
      required: ['input'],
    },
  },
];

function mockFetch(responseBody) {
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => responseBody,
  });
}

// ---------------------------------------------------------------------------
// Anthropic adapter
// ---------------------------------------------------------------------------

console.log('\nAnthropicAdapter');

{
  const TOOL_USE_ID = 'toolu_01XYZ';
  const rawContent = [
    { type: 'tool_use', id: TOOL_USE_ID, name: 'search_ip', input: { input: '8.8.8.8' } },
  ];
  mockFetch({ stop_reason: 'tool_use', content: rawContent });

  const adapter = createAdapter('anthropic', { apiKey: 'sk-ant-test', model: 'claude-sonnet-4-6' });
  const result = await adapter.chat([], SAMPLE_TOOLS);

  assert(result.stopReason === 'tool_use', 'stopReason is tool_use');
  assert(result.toolCalls.length === 1, 'one tool call returned');
  assert(result.toolCalls[0].name === 'search_ip', 'tool name normalized');
  assert(result.toolCalls[0].input.input === '8.8.8.8', 'tool input preserved');
  assert(result.toolCalls[0].id === TOOL_USE_ID, 'tool id preserved');

  const msgs = [{ role: 'user', content: 'test' }];
  const call = { ...result.toolCalls[0], _rawContent: rawContent };
  const next = adapter.appendToolResult(msgs, call, 'IP result text');

  assert(msgs.length === 1, 'original messages not mutated');
  assert(next.length === 3, 'appends assistant + user turns');
  assert(next[1].role === 'assistant', 'assistant turn added');
  assert(next[2].role === 'user', 'user turn added for tool_result');
  assert(next[2].content[0].type === 'tool_result', 'tool_result content block');
  assert(next[2].content[0].tool_use_id === TOOL_USE_ID, 'tool_use_id matches');
  assert(next[2].content[0].content === 'IP result text', 'result content correct');

  const parallelContent = [
    { type: 'tool_use', id: 'toolu_a', name: 'search_ip', input: { input: '8.8.8.8' } },
    { type: 'tool_use', id: 'toolu_b', name: 'search_ip', input: { input: '1.1.1.1' } },
  ];
  const parallelResponse = { _rawContent: parallelContent, toolCalls: parallelContent.map(block => ({
    id: block.id, name: block.name, input: block.input, _rawContent: parallelContent,
  })) };
  const parallel = adapter.appendToolResults(msgs, parallelResponse, [
    { call: parallelResponse.toolCalls[0], content: 'first' },
    { call: parallelResponse.toolCalls[1], content: 'second', isError: true },
  ]);
  assert(parallel.filter(message => message.role === 'assistant').length === 1, 'parallel calls append one assistant turn');
  assert(parallel[2].content.length === 2, 'parallel calls append all tool results together');
  assert(parallel[2].content[1].is_error === true, 'tool errors use is_error');
}

// ---------------------------------------------------------------------------
// OpenAI-compat adapter
// ---------------------------------------------------------------------------

console.log('\nOpenAIAdapter');

{
  const CALL_ID = 'call_abc123';
  const rawCalls = [
    {
      id: CALL_ID,
      type: 'function',
      function: { name: 'search_ip', arguments: JSON.stringify({ input: '1.1.1.1' }) },
    },
  ];
  mockFetch({ choices: [{ message: { content: null, tool_calls: rawCalls } }] });

  const adapter = createAdapter('openai', {
    apiKey: 'sk-test',
    baseUrl: 'http://localhost:4000/v1',
    model: 'gpt-4o-mini',
  });
  const result = await adapter.chat([], SAMPLE_TOOLS);

  assert(result.stopReason === 'tool_use', 'stopReason is tool_use');
  assert(result.toolCalls.length === 1, 'one tool call returned');
  assert(result.toolCalls[0].name === 'search_ip', 'tool name normalized');
  assert(result.toolCalls[0].input.input === '1.1.1.1', 'tool input parsed from JSON string');
  assert(result.toolCalls[0].id === CALL_ID, 'tool id preserved');

  const msgs = [{ role: 'user', content: 'test' }];
  const call = { ...result.toolCalls[0], _rawCalls: rawCalls };
  const next = adapter.appendToolResult(msgs, call, 'Cloudflare DNS');

  assert(msgs.length === 1, 'original messages not mutated');
  assert(next.length === 3, 'appends assistant + tool turns');
  assert(next[1].role === 'assistant', 'assistant turn added');
  assert(next[2].role === 'tool', 'tool role for result');
  assert(next[2].tool_call_id === CALL_ID, 'tool_call_id matches');
  assert(next[2].content === 'Cloudflare DNS', 'result content correct');
}

// CORS guard for api.openai.com
{
  const adapter = createAdapter('openai', {
    apiKey: 'sk-test',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4o',
  });
  let threw = false;
  let errMsg = '';
  try { await adapter.chat([], SAMPLE_TOOLS); } catch (e) { threw = true; errMsg = e.message; }
  assert(threw, 'throws on api.openai.com');
  assert(errMsg.includes('CORS'), 'error message mentions CORS');
}

// ---------------------------------------------------------------------------
// Ollama adapter
// ---------------------------------------------------------------------------

console.log('\nOllamaAdapter');

{
  mockFetch({
    message: {
      content: '',
      tool_calls: [
        { function: { name: 'search_ip', arguments: { input: '9.9.9.9' } } },
      ],
    },
  });

  const adapter = createAdapter('ollama', { baseUrl: 'http://localhost:11434', model: 'llama3.2' });
  const result = await adapter.chat([], SAMPLE_TOOLS);

  assert(result.stopReason === 'tool_use', 'stopReason is tool_use');
  assert(result.toolCalls.length === 1, 'one tool call returned');
  assert(result.toolCalls[0].name === 'search_ip', 'tool name normalized');
  assert(result.toolCalls[0].input.input === '9.9.9.9', 'tool input preserved');

  const msgs = [{ role: 'user', content: 'test' }];
  const call = result.toolCalls[0];
  const next = adapter.appendToolResult(msgs, call, 'Quad9 DNS');

  assert(msgs.length === 1, 'original messages not mutated');
  assert(next.length === 3, 'appends assistant + tool turns');
  assert(next[1].role === 'assistant', 'assistant turn added');
  assert(next[2].role === 'tool', 'tool role for result');
  assert(next[2].content === 'Quad9 DNS', 'result content correct');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed + failed} assertions — ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
