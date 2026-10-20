/**
 * Verifies the client-side BYOK path strips the geojson fence from the
 * Anthropic tool_result content block before it's resent on the round
 * after a search_gdelt_geo call — this is the array that goes to
 * api.anthropic.com on a user's own key, growing every round.
 *
 * Run: node tests/test_agent_loop_geojson_strip.mjs
 *
 * Stubs globalThis.fetch to intercept all three endpoints runAgentLoop
 * hits (/api/tools, /api/run/search_gdelt_geo, api.anthropic.com/v1/messages)
 * and captures the actual serialized body of the SECOND Anthropic call.
 */

globalThis.window = globalThis.window || {};

// agent-loop.js imports its siblings via browser-root-relative "/static/..."
// paths (correct for the served app) — register a resolver hook so Node can
// follow them here too, without changing production import style.
import { register } from 'node:module';
register('./_static_resolver_loader.mjs', import.meta.url);

const { runAgentLoop } = await import('/static/agent-loop.js');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else       { console.error(`  ✗ ${label}`); failed++; }
}

const GDELT_OUTPUT =
  "GDELT geo results for 'ukraine war' (last 60min): 1 location(s)\n\n" +
  '[+] Kyiv, Ukraine (50.45, 30.52) — 4 mention(s)\n\n' +
  '```geojson\n' +
  JSON.stringify({
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: { name: 'Kyiv, Ukraine' }, geometry: { type: 'Point', coordinates: [30.52, 50.45] } }],
  }) +
  '\n```';

const TOOL_CATALOG = [{
  name: 'search_gdelt_geo',
  description: 'GDELT geo search',
  tool_type: 'A',
  required_keys: [],
  parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] },
}];

const anthropicCalls = [];
let anthropicCallCount = 0;

globalThis.fetch = async (url, opts) => {
  const u = String(url);

  if (u.includes('/api/tools')) {
    return { ok: true, json: async () => TOOL_CATALOG };
  }

  if (u.includes('/api/run/search_gdelt_geo')) {
    return { ok: true, json: async () => ({ status: 'ok', output: GDELT_OUTPUT, elapsed: 1.2 }) };
  }

  if (u.includes('api.anthropic.com')) {
    anthropicCallCount++;
    const body = JSON.parse(opts.body);
    anthropicCalls.push(body);

    if (anthropicCallCount === 1) {
      // Round 1: model calls search_gdelt_geo.
      return {
        ok: true,
        json: async () => ({
          stop_reason: 'tool_use',
          content: [{ type: 'tool_use', id: 'toolu_1', name: 'search_gdelt_geo', input: { query: 'ukraine war' } }],
        }),
      };
    }
    // Round 2: model ends the turn.
    return {
      ok: true,
      json: async () => ({
        stop_reason: 'end_turn',
        content: [{ type: 'text', text: 'Found news coverage near Kyiv.' }],
      }),
    };
  }

  throw new Error(`Unstubbed fetch: ${u}`);
};

const events = [];
await runAgentLoop(
  "what's happening near Kyiv?",
  [],
  { provider: 'anthropic', apiKey: 'sk-ant-fake', model: 'claude-sonnet-4-6' },
  {},
  (evt) => events.push(evt),
);

console.log('\nClient-side BYOK path — geojson fence stripped before round 2');
assert(anthropicCallCount === 2, 'exactly 2 calls to api.anthropic.com (round 1 + round 2)');

// The SECOND call's body is the actual outbound request for the round
// AFTER the tool call — this is what must be shown.
const secondBody = anthropicCalls[1];
const serialized = JSON.stringify(secondBody);

assert(!serialized.includes('```geojson'), 'no geojson fence in round-2 request body');
assert(!serialized.includes('"coordinates"'), 'no raw coordinates in round-2 request body');
assert(serialized.includes('[1 geo point(s) → globe]'), 'marker present in round-2 request body');
assert(serialized.includes('Kyiv, Ukraine (50.45, 30.52)'), 'sanity: real gdelt summary text made it through (tool actually ran)');

// The browser-facing SSE event must still carry the FULL FeatureCollection
// — only the provider-bound copy gets stripped.
const toolResultEvent = events.find(e => e.type === 'tool_result' && e.tool === 'search_gdelt_geo');
assert(!!toolResultEvent, 'tool_result event was emitted');
assert(toolResultEvent.output.includes('```geojson'), 'onEvent tool_result.output keeps the full geojson fence intact');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
