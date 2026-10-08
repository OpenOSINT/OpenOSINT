/**
 * Regression: news/findings that arrive before the globe exists (or while its
 * style is still loading) must show up once it is ready, and new results must
 * bring the camera to them. Uses a fake MapLibre; real WebGL needs a browser.
 *
 * Run: node tests/test_globe_buffering.mjs (run in CI by tests/test_js_modules.py)
 */
globalThis.document = { querySelector: () => null, createElement: () => ({}), head: { appendChild() {} } };

class FakeMap {
  static last = null;
  constructor(opts) {
    this.opts = opts; this.sources = {}; this.handlers = {}; this.isLoaded = false;
    this.camera = []; this.visible = false;
    FakeMap.last = this;
  }
  loaded() { return this.isLoaded; }
  on(ev, a, b) { (this.handlers[ev] ||= []).push(b || a); }
  addControl() {}
  resize() {}
  getCanvas() { return { addEventListener() {}, style: {} }; }
  getContainer() { return { offsetParent: this.visible ? {} : null }; }
  getSource(id) { return this.isLoaded ? this.sources[id] : undefined; }
  fitBounds(b, o) { this.camera.push(['fitBounds', b, o]); }
  easeTo(o) { this.camera.push(['easeTo', o]); }
  fireLoad() {
    for (const id of Object.keys(this.opts.style.sources)) {
      const src = { data: this.opts.style.sources[id].data, setData(d) { this.data = d; } };
      this.sources[id] = src;
    }
    this.isLoaded = true;
    (this.handlers.load || []).forEach((h) => h());
  }
}
globalThis.window = { maplibregl: { Map: FakeMap, AttributionControl: class {}, NavigationControl: class {} } };

const g = await import('../openosint/web/static/globe-renderer.js');
const { mergeNewsFeatures } = await import('../openosint/web/static/geo-extractor.js');

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else      { console.error(`  ✗ ${label}`); failed++; }
}
const pt = (name, lon, lat) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties: { name } });
const fc = (...features) => ({ type: 'FeatureCollection', features });

console.log('\ndata arrives before the globe exists');
const early = [pt('Paris', 2.35, 48.85), pt('Tokyo', 139.7, 35.7)];
g.setNewsFeatureCollection(fc(...early));
g.addFinding(pt('8.8.8.8', -122, 37));
g.fitToFeatures(early);
await g.onEnterGlobe({});
const map = FakeMap.last;
assert(map.opts.style.sources['gdelt-news'].data.features.length === 2, 'news buffered before init is in the initial style');
assert(map.opts.style.sources['agent-findings'].data.features.length === 1, 'findings buffered before init are in the initial style');

console.log('\ndata arrives while the style is still loading');
const mid = [pt('Sydney', 151.2, -33.9)];
g.setNewsFeatureCollection(fc(...early, ...mid));
g.addFinding(pt('1.1.1.1', 151, -33));
map.fireLoad();
assert(map.sources['gdelt-news'].data.features.length === 3, 'news that arrived mid-load reaches the source on load');
assert(map.sources['agent-findings'].data.features.length === 2, 'findings that arrived mid-load reach the source on load');

console.log('\ncamera follows new results');
assert(map.camera.length === 0, 'no camera move while the GLOBE pane is hidden');
map.visible = true;
await g.onEnterGlobe({});
assert(map.camera.length === 1 && map.camera[0][0] === 'easeTo', 'opening GLOBE rotates to the results (spread-out set centres, not bounds)');
await g.onEnterGlobe({});
assert(map.camera.length === 1, 'the pending move is applied once');
g.fitToFeatures([pt('Rome', 12.5, 41.9), pt('Paris', 2.35, 48.85)]);
assert(map.camera.length === 2 && map.camera[1][0] === 'fitBounds', 'results arriving while GLOBE is visible are fitted immediately');
assert(g.planFit([]) === null && g.planFit([{}]) === null, 'nothing valid to show → no plan');

console.log('\nmergeNewsFeatures');
const a = [pt('Paris', 2.35, 48.85), pt('Rome', 12.5, 41.9)];
const merged = mergeNewsFeatures(a, [pt('Rome', 12.5, 41.9), pt('Oslo', 10.7, 59.9)]);
assert(merged.map((f) => f.properties.name).join() === 'Paris,Rome,Oslo', 'results from several searches accumulate, one entry per place');
assert(mergeNewsFeatures(a, [pt('Rome', 12.5, 41.9)]).length === 2, 'a repeated place is not duplicated');
assert(mergeNewsFeatures(a, [], 1).map((f) => f.properties.name).join() === 'Rome', 'the cap drops the oldest places first');
assert(a.length === 2, 'inputs are not mutated');

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
