/**
 * Browser BYOK loop: passive filtering + per-request tool-call cap.
 *  - tools with enabled:false are not offered to the model
 *  - a disabled tool the model asks for anyway is never sent to /api/run
 *  - the loop stops with an explicit max_tool_calls event at the cap
 *
 * Run: node tests/test_agent_loop_tool_cap.mjs
 */
globalThis.window = globalThis.window || {};
import { register } from 'node:module';
register('./_static_resolver_loader.mjs', import.meta.url);
const { runAgentLoop } = await import('/static/agent-loop.js');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else { console.error(`  ✗ ${label}`); failed++; }
}

const CATALOG = [
  { name: 'search_ip', description: 'ip', tool_type: 'A', enabled: true, required_keys: [] },
  { name: 'search_username', description: 'user', tool_type: 'A', enabled: false, noise: 'noisy',
    unavailable_reason: 'Disabled in passive mode (noisy).', required_keys: [] },
];
const MAX = 2;
const runCalls = [];
const offeredToolNames = [];
let modelCalls = 0;

globalThis.fetch = async (url, opts) => {
  const u = String(url);
  if (u.includes('/api/tools')) return { ok: true, json: async () => CATALOG };
  if (u.includes('/api/policy')) return { ok: true, json: async () => ({ max_tool_calls: MAX }) };
  if (u.includes('/api/run/')) {
    runCalls.push(u);
    return { ok: true, json: async () => ({ status: 'ok', output: 'ok', elapsed: 0.1 }) };
  }
  if (u.includes('api.anthropic.com')) {
    modelCalls++;
    const body = JSON.parse(opts.body);
    if (modelCalls === 1) offeredToolNames.push(...(body.tools || []).map(t => t.name));
    // Round 1 asks for the disabled tool; every later round keeps asking for search_ip forever.
    const name = modelCalls === 1 ? 'search_username' : 'search_ip';
    return { ok: true, json: async () => ({
      stop_reason: 'tool_use',
      content: [{ type: 'tool_use', id: `t${modelCalls}`, name, input: { input: 'x' } }],
    }) };
  }
  throw new Error(`Unstubbed fetch: ${u}`);
};

const events = [];
await runAgentLoop('investigate', [], { provider: 'anthropic', apiKey: 'k', model: 'm' }, {}, e => events.push(e));

console.log('\nBYOK loop — passive filtering and tool-call cap');
assert(offeredToolNames.join() === 'search_ip', 'disabled tool is not offered to the model');
assert(!runCalls.some(u => u.includes('search_username')), 'disabled tool is never sent to /api/run');
const disabled = events.find(e => e.type === 'tool_result' && e.tool === 'search_username');
assert(disabled && disabled.output.includes('disabled_in_passive_mode'), 'disabled tool returns a structured result');
const cap = events.find(e => e.type === 'max_tool_calls');
assert(!!cap && cap.limit === MAX, 'loop ends with an explicit max_tool_calls event at the cap');
assert(runCalls.length === MAX - 1, 'only calls within the cap ran (disabled attempt counts toward it)');
assert(modelCalls <= MAX + 2, 'loop is bounded, not infinite');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
