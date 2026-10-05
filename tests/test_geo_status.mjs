/** Run: node tests/test_geo_status.mjs (run in CI by tests/test_js_modules.py) */
import { gdeltServiceStatus } from '../openosint/web/static/geo-extractor.js';

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else      { console.error(`  ✗ ${label}`); failed++; }
}

const DOWN = 'Scan error: GDELT GEO service unavailable, try again later.\n[service_unavailable] search_gdelt_geo\nReason: HTTP 404';
assert(gdeltServiceStatus('search_gdelt_geo', DOWN) === true, 'the unavailable result turns the notice on');
assert(gdeltServiceStatus('search_gdelt_geo', 'No geolocated coverage found for x') === false, 'a normal result turns it off');
assert(gdeltServiceStatus('search_gdelt_geo', undefined) === false, 'missing output is not "unavailable"');
assert(gdeltServiceStatus('search_ip', DOWN) === null, 'other tools leave the notice alone');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
