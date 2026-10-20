#!/usr/bin/env node
/**
 * record-globe.mjs — Playwright demo recorder for the OpenOSINT GLOBE view.
 *
 * Storyboard: chat prompt -> tool call -> switch to GLOBE mid-stream so
 * points are seen landing -> rotate/zoom -> click an unclustered point ->
 * pivot panel -> Investigate -> back to chat (query prefilled + sent) ->
 * GRAPH view shows the pivoted entity.
 *
 * Two scenarios share this same script (set OPENOSINT_DEMO_SCENARIO):
 *   "gdelt-news"     (default) — search_gdelt_geo, the gdelt-news layer,
 *                       clustering. Requires api.gdeltproject.org to be
 *                       reachable.
 *   "ip-geolocation" — search_ip / search_ip2location, the agent-findings
 *                       layer (no clustering, one point). Use this when
 *                       GDELT is down — verified end-to-end against a real
 *                       Ollama (llama3.2) agent turn.
 *
 * Canonical target: 127.0.0.1 only (local `openosint web`) — the tile proxy
 * is warm-cached locally with no shared rate limit. Never demo.openosint.tech.
 *
 * Usage:
 *   node scripts/record-demo/record-globe.mjs           # full recording (requires OPENOSINT_DEMO_KEY unless ollama)
 *   node scripts/record-demo/record-globe.mjs --check    # toolchain check only, no key needed
 *
 * Environment:
 *   OPENOSINT_DEMO_KEY    (required unless OPENOSINT_PROVIDER=ollama) — Anthropic API key, read once, never logged
 *   OPENOSINT_DEMO_URL    (optional) — override base URL (default http://127.0.0.1:8080; must be localhost)
 *   OPENOSINT_PROVIDER    (optional) — "anthropic" (default) or "ollama" (keyless, local model)
 *   OPENOSINT_MODEL       (optional) — model id (default "claude-sonnet-4-6", or "llama3.2" for ollama)
 *   OPENOSINT_OLLAMA_HOST (optional) — default "http://localhost:11434"
 *   OPENOSINT_DEMO_SCENARIO (optional) — "gdelt-news" (default) or "ip-geolocation"
 *
 * Outputs:
 *   scripts/record-demo/out/globe-raw.webm — raw Playwright recording
 */

import { chromium } from 'playwright';
import { mkdirSync, readdirSync, renameSync, statSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR   = resolve(__dirname, 'out');

const BASE_URL     = process.env.OPENOSINT_DEMO_URL ?? 'http://127.0.0.1:8080';
const PROVIDER     = process.env.OPENOSINT_PROVIDER ?? 'anthropic';
const MODEL        = process.env.OPENOSINT_MODEL ?? (PROVIDER === 'ollama' ? 'llama3.2' : 'claude-sonnet-4-6');
const OLLAMA_HOST  = process.env.OPENOSINT_OLLAMA_HOST ?? 'http://localhost:11434';
const SCENARIO     = process.env.OPENOSINT_DEMO_SCENARIO ?? 'gdelt-news';

const SCENARIOS = {
  'gdelt-news': {
    prompt: 'Show me real-time geolocated news coverage of global conflict and unrest happening right now',
    toolNames: ['search_gdelt_geo'],
    featureCountKey: 'news',
    pointLayer: 'gdelt-news-points',
    getFeaturesFn: 'getNewsFeatures',
    graphNodePrefix: 'geo:gdelt-news:',
    flyZoom: 8.5, // just above clusterMaxZoom(8) — guarantees an unclustered point
  },
  'ip-geolocation': {
    prompt: 'Investigate the IP 8.8.8.8 for geolocation and threat intelligence',
    toolNames: ['search_ip', 'search_ip2location'],
    featureCountKey: 'findings',
    pointLayer: 'agent-findings-points',
    getFeaturesFn: 'getFindingsFeatures',
    graphNodePrefix: 'geo:agent-findings:',
    flyZoom: 5, // single point, no clustering — a moderate zoom is enough to isolate it
  },
};

const scenario = SCENARIOS[SCENARIO];
if (!scenario) {
  console.error(`ERROR: unknown OPENOSINT_DEMO_SCENARIO="${SCENARIO}". Valid: ${Object.keys(SCENARIOS).join(', ')}`);
  process.exit(1);
}

const DEMO_PROMPT = scenario.prompt;

// "Browser zoom" for the recording. CSS `zoom` on documentElement was tried
// first and rejected: this page is `h-screen` + `overflow:hidden`, so content
// scaled past 100vh just clips — verified with a real screenshot, the input
// bar vanished off the bottom edge entirely. The layout-correct equivalent of
// zoom is a smaller BROWSER viewport (100vh shrinks with it, so the flex
// column still fits by construction — no clipping) with recordVideo upscaling
// back to the unchanged 1280x720 output size.
const PAGE_ZOOM        = parseFloat(process.env.OPENOSINT_DEMO_ZOOM ?? '1.25');
const RECORD_SIZE       = { width: 1280, height: 720 }; // final GIF/MP4 dimensions — unchanged
const BROWSER_VIEWPORT  = { width: Math.round(RECORD_SIZE.width / PAGE_ZOOM), height: Math.round(RECORD_SIZE.height / PAGE_ZOOM) };
const OPENING_PRECLICK_MS     = 150;  // beat 1 must not read as dead air on an empty chat screen
const TYPE_DELAY_MS           = 22;   // per-character — beat 1 (type + send) lands close to ~2s total
const OPENING_PRESEND_MS      = 200;  // short pause before clicking send, not the general beat pause
const BEAT_PAUSE_MS          = 500;   // pause before each click so a viewer can follow (everything after beat 1)
const PIVOT_PANEL_HOLD_MS    = 1_000; // longer hold on the pivot panel specifically — it has text to read
const TOOL_VISIBLE_TIMEOUT_MS = 60_000; // model decision + tool_start
const MAP_READY_TIMEOUT_MS    = 20_000; // WebGL load + first paint
const FEATURES_TIMEOUT_MS     = 45_000; // tool round trip
const FLY_ZOOM        = scenario.flyZoom;
const FLY_DURATION_MS = 4_000;
const GRAPH_SETTLE_MS = 1_700; // matches record.mjs's layout-debounce math

// ---------------------------------------------------------------------------
// --check mode
// ---------------------------------------------------------------------------
if (process.argv.includes('--check')) {
  try { await import('playwright'); console.log('[✓] playwright available'); }
  catch { console.error('[✗] playwright missing — cd scripts/record-demo && npm install'); process.exit(1); }
  console.log('[✓] Toolchain check passed — run without --check to record');
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------
if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(BASE_URL)) {
  console.error(`ERROR: refusing to record against a non-local URL: ${BASE_URL}`);
  console.error('Record against a local `openosint web` instance only — never demo.openosint.tech.');
  process.exit(1);
}

const _key = process.env.OPENOSINT_DEMO_KEY ?? '';
if (PROVIDER !== 'ollama' && !_key) {
  console.error(`ERROR: OPENOSINT_DEMO_KEY is not set (required for provider="${PROVIDER}").`);
  console.error('Export an API key, or set OPENOSINT_PROVIDER=ollama to run keyless against a local model.');
  process.exit(1);
}

mkdirSync(OUT_DIR, { recursive: true });
const WEBM_PATH = resolve(OUT_DIR, 'globe-raw.webm');

console.log(`[*] Scenario: ${SCENARIO}`);
console.log(`[*] Target:   ${BASE_URL}`);
console.log(`[*] Provider: ${PROVIDER} (${MODEL})`);
console.log(`[*] Browser viewport: ${BROWSER_VIEWPORT.width}×${BROWSER_VIEWPORT.height} @2x (zoom ${PAGE_ZOOM}x) — encode-globe.sh scales to ${RECORD_SIZE.width}×${RECORD_SIZE.height}`);
console.log(`[*] Raw webm: ${WEBM_PATH}`);

// ---------------------------------------------------------------------------
// Small helper: move the mouse in visible steps rather than teleporting.
// ---------------------------------------------------------------------------
let _cursor = { x: BROWSER_VIEWPORT.width / 2, y: BROWSER_VIEWPORT.height / 2 };
async function glideMouse(page, toX, toY, durationMs = 400, steps = 12) {
  const fromX = _cursor.x, fromY = _cursor.y;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    await page.mouse.move(fromX + (toX - fromX) * t, fromY + (toY - fromY) * t);
    await page.waitForTimeout(durationMs / steps);
  }
  _cursor = { x: toX, y: toY };
}

// ---------------------------------------------------------------------------
// Launch — headed Chromium, real WebGL rendering required for the globe.
// ---------------------------------------------------------------------------
const browser = await chromium.launch({ headless: false });

const context = await browser.newContext({
  viewport: BROWSER_VIEWPORT,
  deviceScaleFactor: 2,
  // Capture at the browser's own (smaller, reflowed) size — recordVideo.size
  // larger than the actual viewport does NOT upscale, it letterboxes with
  // padding (verified: a real capture showed grey padding filling the right
  // and bottom of the frame). Final 1280x720 output is produced by
  // encode-globe.sh's ffmpeg scale filters instead.
  recordVideo: { dir: OUT_DIR, size: BROWSER_VIEWPORT },
});

// Key lands in sessionStorage only, injected before first navigation — never
// on screen, never logged. Gate/notice are pre-acknowledged so the recording
// opens straight on the chat view (they're not part of the storyboard).
context.addInitScript(({ provider, apiKey, model, ollamaHost }) => {
  const baseUrl = provider === 'ollama' ? ollamaHost : '';
  window.sessionStorage.setItem('openosint_byok', JSON.stringify({ provider, apiKey, baseUrl, model }));
  window.localStorage.setItem('openosint-ack', '1');
  window.localStorage.setItem('openosint-notice', '1');
}, { provider: PROVIDER, apiKey: _key, model: MODEL, ollamaHost: OLLAMA_HOST });

// Recording-only synthetic cursor — Chromium's own OS cursor is never
// composited into Playwright's recordVideo output, so without this a viewer
// sees UI elements activate with no visible pointer. pointer-events:none so
// it never intercepts the real click underneath it. Not shipped — this only
// exists in the recorder's injected script, never in product code.
context.addInitScript(() => {
  const install = () => {
    const cursor = document.createElement('div');
    cursor.id = '__rec_cursor__';
    Object.assign(cursor.style, {
      position: 'fixed', zIndex: '2147483647', width: '14px', height: '14px',
      borderRadius: '50%', background: '#3fb950', border: '2px solid #0d1117',
      pointerEvents: 'none', display: 'none', left: '0px', top: '0px',
      transform: 'translate(-50%, -50%)', boxShadow: '0 0 4px rgba(0,0,0,0.6)',
    });
    document.documentElement.appendChild(cursor);
    window.addEventListener('mousemove', (e) => {
      cursor.style.display = 'block';
      cursor.style.left = `${e.clientX}px`;
      cursor.style.top = `${e.clientY}px`;
    }, { capture: true });
  };
  if (document.readyState !== 'loading') install();
  else document.addEventListener('DOMContentLoaded', install);
});

const page = await context.newPage();
await page.bringToFront();

console.log('[*] Navigating…');
await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });

const visibility = await page.evaluate(() => document.visibilityState);
if (visibility !== 'visible') {
  throw new Error(`ABORT: document.visibilityState is "${visibility}", not "visible" — the tab is not the active foreground tab. A background tab throttles requestAnimationFrame to zero and MapLibre will not paint.`);
}

await page.waitForFunction(() => window._agentLoopReady === true, { timeout: 15_000 });
console.log('[+] Agent loop ready, tab confirmed visible');
await page.waitForTimeout(150); // minimal settle — a GitHub visitor decides whether to keep watching right here

// Ollama's BYOK path is gated behind a real CORS reachability test (not just
// the presence of a baseUrl) — call the app's own testOllama() rather than
// faking the flag, and never by opening the Settings panel on camera.
if (PROVIDER === 'ollama') {
  const reachable = await page.evaluate(async () => {
    const data = window.Alpine.$data(document.getElementById('main-app'));
    await data.testOllama();
    return data.ollamaTestOk;
  });
  if (!reachable) {
    throw new Error(`ABORT: Ollama at ${OLLAMA_HOST} is not reachable from the page origin. Check OLLAMA_ORIGINS includes ${BASE_URL} and the daemon is running.`);
  }
  console.log('[+] Ollama reachable (CORS test passed)');
}

// ---------------------------------------------------------------------------
// Beat 1 — type the prompt character by character, then send. Tightened
// deliberately: this is the moment a GitHub visitor decides whether to keep
// watching, so it uses its own short pauses, not the general BEAT_PAUSE_MS.
// ---------------------------------------------------------------------------
const input = page.locator('#chat-input');
await input.click();
await page.waitForTimeout(OPENING_PRECLICK_MS);
await input.pressSequentially(DEMO_PROMPT, { delay: TYPE_DELAY_MS });
await page.waitForTimeout(OPENING_PRESEND_MS);
// Not input.press('Enter') — Alpine's @keydown.enter.exact.prevent does not
// reliably fire right after pressSequentially() (verified: the textarea just
// gets a literal newline and sendMessage() never runs). Click the send
// button instead — same visible beat, and it's a proven, direct trigger.
await page.locator('#chat-input + button').click();
console.log(`[*] Sent: "${DEMO_PROMPT}"`);

// ---------------------------------------------------------------------------
// Beat 2 — wait for the tool call to appear (running), then switch to GLOBE
// mid-stream so points are seen landing, not already there.
// ---------------------------------------------------------------------------
console.log(`[*] Waiting for a tool call (${scenario.toolNames.join(' / ')})…`);
{
  const chatArea = page.locator('#chat-area');
  let waiter = chatArea.getByText(scenario.toolNames[0], { exact: true });
  for (const name of scenario.toolNames.slice(1)) {
    waiter = waiter.or(chatArea.getByText(name, { exact: true }));
  }
  await waiter.first().waitFor({ timeout: TOOL_VISIBLE_TIMEOUT_MS });
}
console.log('[+] Tool call visible — switching to GLOBE mid-stream');
await page.waitForTimeout(BEAT_PAUSE_MS);

const globeTab = page.locator('nav button:has-text("Globe")');
const globeTabBox = await globeTab.boundingBox();
await glideMouse(page, globeTabBox.x + globeTabBox.width / 2, globeTabBox.y + globeTabBox.height / 2);
await globeTab.click();

// ---------------------------------------------------------------------------
// Confirm the globe actually painted — real map.loaded() + at least one
// render event, never trust a fixed sleep for WebGL init timing.
// ---------------------------------------------------------------------------
await page.waitForFunction(() => window._globeFns?.isGlobeReady?.() === true, { timeout: MAP_READY_TIMEOUT_MS });
console.log('[+] Globe loaded and painting');

const basemapDown = await page.evaluate(() => document.body.innerText.includes('Basemap imagery unavailable'));
if (basemapDown) {
  throw new Error('ABORT: basemap tiles failed to load (5+ consecutive tile failures) — refusing to record a black sphere. Check the local tile proxy.');
}

// ---------------------------------------------------------------------------
// Beat 3 — wait for points to land, then a slow rotate + zoom in.
// ---------------------------------------------------------------------------
console.log('[*] Waiting for points to land on the globe…');
await page.waitForFunction(
  (key) => (window._globeFns?.getFeatureCounts?.()?.[key] ?? 0) > 0,
  scenario.featureCountKey,
  { timeout: FEATURES_TIMEOUT_MS },
).catch(() => { throw new Error(`ABORT: no points landed within the timeout (${scenario.featureCountKey}). Not faking data.`); });
const landedCount = await page.evaluate((key) => window._globeFns.getFeatureCounts()[key], scenario.featureCountKey);
console.log(`[+] ${landedCount} point(s) landed`);
await page.waitForTimeout(800);

const targetFeature = await page.evaluate((fnName) => {
  const features = window._globeFns[fnName]();
  return features[Math.floor(features.length / 2)]?.geometry?.coordinates ?? null;
}, scenario.getFeaturesFn);
if (!targetFeature) throw new Error('ABORT: could not pick a target feature to fly to.');

console.log('[*] Rotating and zooming into a point…');
await page.evaluate(
  ({ center, zoom, duration }) => window._globeFns.flyTo({ center, zoom, bearing: 45, pitch: 20, duration }),
  { center: targetFeature, zoom: FLY_ZOOM, duration: FLY_DURATION_MS },
);
await page.waitForTimeout(300);

// ---------------------------------------------------------------------------
// Beat 4 — click a single point; the pivot panel opens.
// ---------------------------------------------------------------------------
const point = await page.evaluate((layerId) => {
  const p = window._globeFns.pickRenderedPoint(layerId);
  if (!p) return null;
  const rect = document.getElementById('globe-container').getBoundingClientRect();
  return { x: rect.left + p.x, y: rect.top + p.y };
}, scenario.pointLayer);
if (!point) throw new Error('ABORT: no point rendered after zooming in — cannot demonstrate the click-to-pivot flow.');

console.log('[*] Clicking point…');
await glideMouse(page, point.x, point.y);
await page.waitForTimeout(BEAT_PAUSE_MS);
await page.mouse.click(point.x, point.y);

await page.locator('[x-show="globePivotFeature"] button:has-text("Investigate")').waitFor({ timeout: 5_000 });
console.log('[+] Pivot panel open');
await page.waitForTimeout(PIVOT_PANEL_HOLD_MS); // longer hold — a viewer needs to read the panel, not just see it flash

const investigateBtn = page.locator('[x-show="globePivotFeature"] button:has-text("Investigate")');
const investigateBox = await investigateBtn.boundingBox();
await glideMouse(page, investigateBox.x + investigateBox.width / 2, investigateBox.y + investigateBox.height / 2);
await investigateBtn.click();

// ---------------------------------------------------------------------------
// Beat 5 — jumps back to chat, query prefilled + sent, follow-up run starts.
// ---------------------------------------------------------------------------
console.log('[*] Pivoted — follow-up investigation running…');
await page.waitForTimeout(4_000);

// ---------------------------------------------------------------------------
// Beat 6 — switch to GRAPH: the pivoted entity is there.
// ---------------------------------------------------------------------------
const graphTab = page.locator('nav button:has-text("Graph")');
const graphTabBox = await graphTab.boundingBox();
await glideMouse(page, graphTabBox.x + graphTabBox.width / 2, graphTabBox.y + graphTabBox.height / 2);
await page.waitForTimeout(BEAT_PAUSE_MS);
await graphTab.click();
await page.waitForTimeout(GRAPH_SETTLE_MS);

const graphHasGeoNode = await page.evaluate(
  (prefix) => window._graphFns.exportJson().nodes.some(n => n.id.startsWith(prefix)),
  scenario.graphNodePrefix,
);
console.log(graphHasGeoNode ? '[+] Pivoted entity confirmed in graph' : '[!] Pivoted entity not found in graph — recording continues regardless');

await page.waitForTimeout(4_000);

// ---------------------------------------------------------------------------
// Close context — Playwright finalises the .webm file on context.close()
// ---------------------------------------------------------------------------
const rawVideoPath = await page.video()?.path();
await context.close();
await browser.close();

const resolvedPath = rawVideoPath ?? (() => {
  const webms = readdirSync(OUT_DIR)
    .filter(f => f.endsWith('.webm'))
    .sort((a, b) => statSync(resolve(OUT_DIR, b)).mtimeMs - statSync(resolve(OUT_DIR, a)).mtimeMs);
  return webms.length ? resolve(OUT_DIR, webms[0]) : null;
})();

if (!resolvedPath) {
  console.error('ERROR: No .webm found in', OUT_DIR);
  process.exit(1);
}
if (resolvedPath !== WEBM_PATH) renameSync(resolvedPath, WEBM_PATH);

console.log(`[+] Raw video: ${WEBM_PATH}`);
console.log('[+] Recording complete — run encode-globe.sh to produce the GIF/MP4');
