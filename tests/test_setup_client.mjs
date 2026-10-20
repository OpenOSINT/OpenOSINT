/**
 * Unit tests for the key form's pure helpers. Run: node tests/test_setup_client.mjs
 * (tests/test_js_modules.py runs this in CI.)
 */
import { groupFields, buildSetupBody, setupHeaders, describeSetupResult, summarizeTools } from '../openosint/web/static/setup-client.js';

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else      { console.error(`  ✗ ${label}`); failed++; }
}

const FIELDS = [
  { key: 'ANTHROPIC_API_KEY', group: 'ai' },
  { key: 'SHODAN_API_KEY', group: 'tools' },
  { key: 'GITHUB_TOKEN', group: 'tools', optional: true },
];

console.log('groupFields');
const groups = groupFields(FIELDS);
assert(groups.map((g) => g.id).join() === 'ai,tools,optional', 'AI provider first, then tool keys, then optional');
assert(groups[1].fields.length === 1 && groups[1].fields[0].key === 'SHODAN_API_KEY', 'optional keys are not mixed into tool keys');
assert(groupFields([]).length === 0 && groupFields(undefined).length === 0, 'empty / missing field list yields no groups');

console.log('buildSetupBody');
// Regression: saveApiKeys iterated an undefined `this.apiKeys` and threw before any request was sent.
assert(JSON.stringify(buildSetupBody(FIELDS, { SHODAN_API_KEY: '  abc  ' })) === '{"SHODAN_API_KEY":"abc"}', 'trims and includes filled fields');
assert(Object.keys(buildSetupBody(FIELDS, { SHODAN_API_KEY: '   ', GITHUB_TOKEN: '' })).length === 0, 'skips blank values');
assert(!('EVIL' in buildSetupBody(FIELDS, { EVIL: 'x', SHODAN_API_KEY: 'a' })), 'ignores keys the server did not list');
assert(Object.keys(buildSetupBody(undefined, { A: '1' })).length === 0, 'does not throw without a field list');

console.log('setupHeaders');
assert(!('X-Setup-Token' in setupHeaders('')) && !('X-Setup-Token' in setupHeaders(undefined)), 'no token header when none entered');
assert(setupHeaders(' tok ')['X-Setup-Token'] === 'tok', 'sends the trimmed token');

console.log('describeSetupResult');
assert(describeSetupResult(200, { applied: ['A'], saved_to: '/h/config.env' }).message === 'Saved A to /h/config.env.', 'success names keys and file');
const forbidden = describeSetupResult(403, { message: 'Setup is only allowed from localhost…' });
assert(!forbidden.ok && forbidden.message.startsWith('Setup is only allowed'), 'a 403 shows the server message, not a generic failure');
assert(describeSetupResult(500, null).message === 'Save failed (HTTP 500).', 'falls back to the status code');
const shadow = describeSetupResult(200, { applied: [], shadowed_by_environment: ['A'] });
assert(!shadow.ok && shadow.message.includes('environment variable'), 'a key overridden by the environment is reported, not called success');
assert(describeSetupResult(200, { applied: ['A'], rejected: ['B'] }).message.includes('Not accepted: B'), 'rejected keys are listed');
assert(!JSON.stringify(describeSetupResult(200, { applied: ['A'], value: 'sekret' })).includes('sekret'), 'never echoes a value');

console.log('summarizeTools');
const s = summarizeTools([
  { name: 'search_ip', available: true, required_keys: [] },
  { name: 'search_shodan', available: false, required_keys: ['SHODAN_API_KEY'] },
  { name: 'search_email', available: false, required_keys: [] },
]);
assert(s.working.join() === 'search_ip' && s.needKey.join() === 'search_shodan' && s.needInstall.join() === 'search_email', 'splits working / needs key / needs install');
assert(summarizeTools(undefined).working.length === 0, 'tolerates a missing list');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
