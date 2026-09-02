/**
 * Unit tests for url-safety.js.
 * Run: node tests/test_url_safety.mjs
 *
 * Guards the globe pivot panel's href, extracted from GDELT's third-party
 * html blurb — a javascript:/data: URI there is a click-triggered XSS.
 */

import { safeHttpUrl } from '../openosint/web/static/url-safety.js';

let passed = 0, failed = 0;

function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else       { console.error(`  ✗ ${label}`); failed++; }
}

console.log('\nsafeHttpUrl — malicious/invalid input rejected (returns \'\')');
assert(safeHttpUrl('javascript:alert(1)') === '', 'javascript: scheme rejected');
assert(safeHttpUrl('data:text/html,<script>alert(1)</script>') === '', 'data: scheme rejected');
assert(safeHttpUrl('//evil.com') === '', 'protocol-relative URL rejected');
assert(safeHttpUrl('not a url at all') === '', 'malformed garbage rejected');
assert(safeHttpUrl('') === '', 'empty string rejected');
assert(safeHttpUrl(null) === '', 'null rejected');
assert(safeHttpUrl(undefined) === '', 'undefined rejected');
assert(safeHttpUrl('vbscript:msgbox(1)') === '', 'vbscript: scheme rejected');
assert(safeHttpUrl('file:///etc/passwd') === '', 'file: scheme rejected');

console.log('\nsafeHttpUrl — valid http(s) URLs pass through');
assert(safeHttpUrl('https://example.com/article') === 'https://example.com/article', 'https URL accepted');
assert(safeHttpUrl('http://example.com/article') === 'http://example.com/article', 'http URL accepted');
assert(safeHttpUrl('https://example.com/a?b=c#d') === 'https://example.com/a?b=c#d', 'https URL with query/hash accepted');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
