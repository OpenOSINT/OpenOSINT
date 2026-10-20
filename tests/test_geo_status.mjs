/** Run: node tests/test_geo_status.mjs (run in CI by tests/test_js_modules.py) */
import { gdeltServiceStatus, newsCoverage, coverageLabel } from '../openosint/web/static/geo-extractor.js';

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

const fenced = (c) => 'GDELT geolocated news\n\n```geojson\n' + JSON.stringify({ type: 'FeatureCollection', features: [], coverage: c }) + '\n```';
const FIRST = newsCoverage('search_gdelt_geo', fenced({ minutes: 15, requested: 360, loading: true, stale_minutes: 0 }));
assert(FIRST && FIRST.minutes === 15 && FIRST.requested === 360 && FIRST.loading === true, 'coverage is read from the fenced FeatureCollection');
assert(coverageLabel(FIRST) === 'News: last 15 min — older articles still loading', 'a short first window says it is still loading');
assert(coverageLabel(newsCoverage('search_gdelt_geo', fenced({ minutes: 360, requested: 360, loading: false, stale_minutes: 0 }))) === 'News: last 6 h', 'a full window is just the span');
assert(coverageLabel(newsCoverage('search_gdelt_geo', fenced({ minutes: 75, requested: 75, loading: false, stale_minutes: 40 }))) === 'News: last 1 h 15 min — feed 40 min behind', 'a stale feed is flagged');
assert(newsCoverage('search_ip', fenced({ minutes: 15 })) === null, 'other tools have no coverage');
assert(newsCoverage('search_gdelt_geo', 'No geolocated coverage found for x') === null, 'a result without a fence has no coverage');
assert(newsCoverage('search_gdelt_geo', DOWN) === null, 'the unavailable result has no coverage');
assert(newsCoverage('search_gdelt_geo', '```geojson\n{not json\n```') === null, 'malformed fence does not throw');
const HOSTILE = newsCoverage('search_gdelt_geo', fenced({ minutes: '<img src=x onerror=1>', requested: 5 }));
assert(HOSTILE === null, 'non-numeric coverage is rejected');
const SNEAKY = newsCoverage('search_gdelt_geo', fenced({ minutes: 20, requested: '<b>x</b>', loading: '<b>yes</b>', stale_minutes: '<i>1</i>' }));
assert(SNEAKY.requested === 20 && SNEAKY.loading === false && SNEAKY.staleMinutes === 0, 'string values are coerced to numbers/booleans');
assert(coverageLabel(null) === '', 'no coverage → no label');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
