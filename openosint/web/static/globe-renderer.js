/**
 * globe-renderer.js — MapLibre wrapper for the investigation globe.
 *
 * Mirrors graph-renderer.js's shape: reads window.maplibregl (UMD global,
 * lazy-loaded on first GLOBE-view entry — see loadMapLibre() and the loader
 * in index.html), exposes a small imperative API, and never tears down the
 * WebGL context once created.
 *
 * Findings/news are kept in module-level accumulators (not read back off the
 * MapLibre source) so addFinding()/setNewsFeatureCollection() work even
 * before the globe has ever been mounted — an agent run can stream findings
 * onto the globe before the user has clicked GLOBE at all.
 *
 * Exports:
 *   loadMapLibre()                — lazy-loads the vendored JS/CSS once
 *   initGlobe(containerEl)        — lazy, idempotent
 *   resizeGlobe()                 — call when the pane becomes visible
 *   addFinding(feature)           — push one GeoJSON Point onto agent-findings
 *   clearFindings()
 *   setNewsFeatureCollection(fc)  — replace the gdelt-news source wholesale
 *   onBoxSelect(cb)                — cb(bbox) fires after a shift-drag box-select
 *   onPointClick(cb)               — cb(feature, sourceId) fires on point tap
 */

const TILE_URL = '/api/tiles/{z}/{x}/{y}';
const MAPLIBRE_JS = '/static/vendor/maplibre/maplibre-gl.min.js';
const MAPLIBRE_CSS = '/static/vendor/maplibre/maplibre-gl.min.css';

let _map = null;
let _hasRendered = false;
let _loadPromise = null;
let _boxSelectCallback = null;
let _pointClickCallback = null;
let _basemapUnavailableCallback = null;
let _tileFailStreak = 0;
const TILE_FAIL_THRESHOLD = 5;

function _emptyFC() {
  return { type: 'FeatureCollection', features: [] };
}

let _findingsFC = _emptyFC();
let _newsFC = _emptyFC();

// ---------------------------------------------------------------------------
// Lazy asset loading — nothing here runs until initGlobe() is first called.
// ---------------------------------------------------------------------------

function _loadCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  document.head.appendChild(link);
}

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

/** Loads the vendored MapLibre JS + CSS exactly once. Safe to call repeatedly. */
export function loadMapLibre() {
  if (_loadPromise) return _loadPromise;
  _loadCss(MAPLIBRE_CSS);
  _loadPromise = window.maplibregl ? Promise.resolve() : _loadScript(MAPLIBRE_JS);
  return _loadPromise;
}

// ---------------------------------------------------------------------------
// Map style
// ---------------------------------------------------------------------------

function _style() {
  return {
    version: 8,
    projection: { type: 'globe' },
    sources: {
      basemap: {
        type: 'raster',
        tiles: [TILE_URL],
        tileSize: 256,
        // Hard cost ceiling — tile count grows as 4^z. z7 is plenty for
        // situational awareness; MapLibre over-zooms z7 tiles past this.
        // The server enforces the same ceiling (see _TILE_MAX_ZOOM).
        maxzoom: 7,
        attribution:
          'Imagery &copy; <a href="https://s2maps.eu" target="_blank" rel="noopener">EOX IT Services GmbH</a> (Contains modified Copernicus Sentinel data 2020, s2cloudless) &middot; News: <a href="https://www.gdeltproject.org" target="_blank" rel="noopener">GDELT</a>',
      },
      'agent-findings': { type: 'geojson', data: _findingsFC },
      'gdelt-news': {
        type: 'geojson',
        data: _newsFC,
        cluster: true,
        clusterRadius: 40,
        clusterMaxZoom: 8,
      },
    },
    layers: [
      { id: 'basemap', type: 'raster', source: 'basemap' },
      {
        id: 'gdelt-news-clusters',
        type: 'circle',
        source: 'gdelt-news',
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': '#58a6ff',
          'circle-opacity': 0.55,
          'circle-radius': ['step', ['get', 'point_count'], 12, 10, 18, 50, 26],
          'circle-stroke-width': 1,
          'circle-stroke-color': '#0d1117',
        },
      },
      {
        id: 'gdelt-news-points',
        type: 'circle',
        source: 'gdelt-news',
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-color': '#58a6ff',
          'circle-opacity': 0.75,
          'circle-radius': ['interpolate', ['linear'], ['coalesce', ['get', 'count'], 1], 1, 4, 20, 10],
          'circle-stroke-width': 1,
          'circle-stroke-color': '#0d1117',
        },
      },
      {
        id: 'agent-findings-points',
        type: 'circle',
        source: 'agent-findings',
        paint: {
          'circle-color': '#3fb950',
          'circle-opacity': 0.85,
          'circle-radius': 6,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#0d1117',
        },
      },
    ],
    sky: {
      'sky-color': '#0d1117',
      'sky-horizon-blend': 0.5,
      'horizon-color': '#161b22',
      'horizon-fog-blend': 0.5,
      'fog-color': '#161b22',
      'fog-ground-blend': 0.5,
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 1, 7, 0],
    },
    light: { anchor: 'viewport', color: '#e6edf3', intensity: 0.3 },
  };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Lazy-loads MapLibre (if needed) and creates the map. Idempotent. */
export async function initGlobe(containerEl) {
  if (_map) return _map;
  await loadMapLibre();
  const maplibregl = window.maplibregl;
  if (!maplibregl) {
    console.error('[Globe] window.maplibregl not available — check vendor script load');
    return null;
  }

  _map = new maplibregl.Map({
    container: containerEl,
    style: _style(),
    center: [0, 20],
    zoom: 1.5,
    attributionControl: false,
  });
  _map.addControl(new maplibregl.AttributionControl({ compact: true }));
  _map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

  // 'load' can fire before this listener attaches (e.g. an inline style
  // with cached tiles resolves almost immediately) — check loaded() first
  // rather than trusting the event to always be in the future.
  const onMapReady = () => {
    _map.resize();
    _wireBoxSelect();
    _wirePointClicks();
    _wireTileFailureTracking();
    _map.on('render', () => { _hasRendered = true; });
  };
  if (_map.loaded()) onMapReady();
  else _map.on('load', onMapReady);

  return _map;
}

/** Call after the globe pane becomes visible (fixes a blank canvas from
 * resizing while the container was display:none). */
export function resizeGlobe() {
  if (_map) _map.resize();
}

/** Rail-button entry point: lazy-inits on first call, just resizes after
 * that — the one function the GLOBE nav button needs to call. */
export async function onEnterGlobe(containerEl) {
  if (!containerEl) return;
  await initGlobe(containerEl);
  resizeGlobe();
}

/** Merge one GeoJSON Point Feature into the agent-findings source. */
export function addFinding(feature) {
  if (!feature?.geometry?.coordinates) return;
  _findingsFC.features.push(feature);
  const source = _map?.getSource('agent-findings');
  if (source) source.setData(_findingsFC);
}

export function clearFindings() {
  _findingsFC = _emptyFC();
  const source = _map?.getSource('agent-findings');
  if (source) source.setData(_findingsFC);
}

/** Replace the gdelt-news source with a fresh FeatureCollection (from a
 * search_gdelt_geo tool result). */
export function setNewsFeatureCollection(fc) {
  if (!fc?.features) return;
  _newsFC = fc;
  const source = _map?.getSource('gdelt-news');
  if (source) source.setData(_newsFC);
}

/** cb(bbox) where bbox = [minLon, minLat, maxLon, maxLat]. */
export function onBoxSelect(cb) {
  _boxSelectCallback = cb;
}

/** cb(feature, sourceId) fired when a point in either data layer is tapped. */
export function onPointClick(cb) {
  _pointClickCallback = cb;
}

/** cb(unavailable: boolean) — fires true after TILE_FAIL_THRESHOLD consecutive
 * basemap tile failures, and false again once a tile succeeds. GDELT/finding
 * points must stay usable even when the basemap can't load. */
export function onBasemapUnavailable(cb) {
  _basemapUnavailableCallback = cb;
}

// ---------------------------------------------------------------------------
// Debug / e2e helpers — narrow, purpose-built accessors used by
// scripts/record-demo to confirm real WebGL paint, move the camera, and
// locate a point to click. None of these hand back the MapLibre instance
// itself — each does exactly the one thing the recorder needs. Not used by
// the app UI itself.
// ---------------------------------------------------------------------------

/** True once the map has both finished its initial load AND painted at
 * least one frame — the two conditions a recorder needs before it can
 * trust the canvas isn't still black or SwiftShader-stalled. */
export function isGlobeReady() {
  return !!(_map && _map.loaded() && _hasRendered);
}

/** Current feature counts held in each source (independent of what's rendered). */
export function getFeatureCounts() {
  return { news: _newsFC.features.length, findings: _findingsFC.features.length };
}

/** All raw gdelt-news features currently loaded (not just the ones on screen). */
export function getNewsFeatures() {
  return _newsFC.features;
}

/** All raw agent-findings features currently loaded (not just the ones on screen). */
export function getFindingsFeatures() {
  return _findingsFC.features;
}

/** First rendered point on the given layer, with its container-relative
 * pixel position (mirrors graph-renderer's getNodeRenderedBBox), or null if
 * none is currently rendered. layerId defaults to the unclustered GDELT
 * news layer; pass 'agent-findings-points' for the other data layer. */
export function pickRenderedPoint(layerId = 'gdelt-news-points') {
  if (!_map) return null;
  const features = _map.queryRenderedFeatures(undefined, { layers: [layerId] });
  if (!features.length) return null;
  const [lon, lat] = features[0].geometry.coordinates;
  const { x, y } = _map.project([lon, lat]);
  return { lon, lat, x, y };
}

/** Eases the camera to a target and resolves once the move settles. Never
 * hands back the Map instance — callers get the one operation they need. */
export function flyTo({ center, zoom, bearing = 0, pitch = 0, duration = 2000 } = {}) {
  if (!_map || !center) return Promise.resolve();
  return new Promise((resolve) => {
    _map.once('moveend', resolve);
    _map.easeTo({ center, zoom, bearing, pitch, duration });
  });
}

// ---------------------------------------------------------------------------
// Interaction wiring — called once from the map's 'load' event.
// ---------------------------------------------------------------------------

/** Tracks consecutive basemap tile failures. A black sphere with no
 * explanation reads as our bug — past TILE_FAIL_THRESHOLD, tell the user;
 * GDELT/finding points stay usable underneath regardless. */
function _wireTileFailureTracking() {
  _map.on('error', (e) => {
    if (e.sourceId && e.sourceId !== 'basemap') return;
    _tileFailStreak++;
    if (_tileFailStreak === TILE_FAIL_THRESHOLD && typeof _basemapUnavailableCallback === 'function') {
      _basemapUnavailableCallback(true);
    }
  });
  _map.on('sourcedata', (e) => {
    if (e.sourceId !== 'basemap' || !e.isSourceLoaded) return;
    if (_tileFailStreak >= TILE_FAIL_THRESHOLD && typeof _basemapUnavailableCallback === 'function') {
      _basemapUnavailableCallback(false);
    }
    _tileFailStreak = 0;
  });
}

const _CLUSTER_LAYER = 'gdelt-news-clusters';
const _CLICK_LAYERS = ['agent-findings-points', 'gdelt-news-points', _CLUSTER_LAYER];

/**
 * Pure decision logic for a globe click: takes the features MapLibre's
 * queryRenderedFeatures already resolved plus the layer id it matched, and
 * returns a plain action descriptor. Touches nothing — no map, no DOM —
 * so it's fully testable without a paint pipeline; queryRenderedFeatures
 * itself is the only part that still needs a real browser.
 *
 * The decision is made from layerId, never inferred from the feature's own
 * properties — a cluster feature can carry a name/label-shaped property
 * too (supercluster copies some source properties onto cluster points),
 * and that must never be mistaken for an unclustered point.
 *
 * Returns one of:
 *   { action: 'pivot', feature }
 *   { action: 'expand-cluster', clusterId, feature }
 *   { action: 'ignore' }
 */
export function decideClickAction(features, layerId) {
  const feature = features?.[0];
  if (!feature) return { action: 'ignore' };

  if (layerId === _CLUSTER_LAYER) {
    const clusterId = feature.properties?.cluster_id;
    if (clusterId == null) return { action: 'ignore' };
    return { action: 'expand-cluster', clusterId, feature };
  }

  return { action: 'pivot', feature };
}

function _executeClickAction(decision, layerId) {
  if (decision.action === 'pivot') {
    if (typeof _pointClickCallback !== 'function') return;
    const sourceId = layerId.startsWith('agent-findings') ? 'agent-findings' : 'gdelt-news';
    _pointClickCallback(decision.feature, sourceId);
  } else if (decision.action === 'expand-cluster') {
    const source = _map.getSource('gdelt-news');
    source.getClusterExpansionZoom(decision.clusterId, (err, zoom) => {
      if (err) return;
      _map.easeTo({ center: decision.feature.geometry.coordinates, zoom });
    });
  }
  // 'ignore' → no-op
}

function _wirePointClicks() {
  for (const layerId of _CLICK_LAYERS) {
    _map.on('click', layerId, (evt) => {
      _executeClickAction(decideClickAction(evt.features, layerId), layerId);
    });
    _map.on('mouseenter', layerId, () => { _map.getCanvas().style.cursor = 'pointer'; });
    _map.on('mouseleave', layerId, () => { _map.getCanvas().style.cursor = ''; });
  }
}

/** Shift+drag box-select. MapLibre has no built-in box-select interaction,
 * so this hooks the canvas directly: capture the pixel rect on drag, then
 * unproject its two corners to a geographic bbox on mouseup. */
function _wireBoxSelect() {
  const canvas = _map.getCanvas();
  let start = null; // {x, y} canvas-local pixels
  let box = null;

  const localPoint = (e) => {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const onMouseDown = (e) => {
    if (!e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    _map.dragPan.disable();
    start = localPoint(e);
    box = document.createElement('div');
    box.style.cssText =
      'position:absolute;border:1.5px dashed #58a6ff;background:rgba(88,166,255,0.12);pointer-events:none;z-index:5;';
    canvas.parentElement.appendChild(box);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  const onMouseMove = (e) => {
    if (!start || !box) return;
    const cur = localPoint(e);
    box.style.left = `${Math.min(start.x, cur.x)}px`;
    box.style.top = `${Math.min(start.y, cur.y)}px`;
    box.style.width = `${Math.abs(cur.x - start.x)}px`;
    box.style.height = `${Math.abs(cur.y - start.y)}px`;
  };

  const onMouseUp = (e) => {
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    _map.dragPan.enable();
    if (box) { box.remove(); box = null; }
    if (!start) return;

    const startPoint = start;
    const endPoint = localPoint(e);
    start = null;
    if (Math.hypot(endPoint.x - startPoint.x, endPoint.y - startPoint.y) < 4) return; // click, not a drag

    const c1 = _map.unproject([startPoint.x, startPoint.y]);
    const c2 = _map.unproject([endPoint.x, endPoint.y]);
    const bbox = [
      Math.min(c1.lng, c2.lng),
      Math.min(c1.lat, c2.lat),
      Math.max(c1.lng, c2.lng),
      Math.max(c1.lat, c2.lat),
    ];
    if (typeof _boxSelectCallback === 'function') _boxSelectCallback(bbox);
  };

  canvas.addEventListener('mousedown', onMouseDown);
}
