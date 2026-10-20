/**
 * Unit tests for decideClickAction() — the pure decision logic behind the
 * globe's click handlers. queryRenderedFeatures itself stays untestable in
 * Node (needs a real paint pipeline); this is everything downstream of it.
 *
 * Run: node tests/test_globe_click_decision.mjs
 */

import { decideClickAction } from '../openosint/web/static/globe-renderer.js';

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else       { console.error(`  ✗ ${label}`); failed++; }
}

function point(props = {}) {
  return { type: 'Feature', properties: props, geometry: { type: 'Point', coordinates: [10, 20] } };
}

console.log('\ndecideClickAction');

// Unclustered gdelt-news point → pivot.
{
  const f = point({ name: 'Kyiv, Ukraine', html: '<a href="https://example.com">x</a>' });
  const result = decideClickAction([f], 'gdelt-news-points');
  assert(result.action === 'pivot', 'unclustered gdelt-news point → pivot');
  assert(result.feature === f, 'pivot result carries the original feature');
}

// Cluster feature → expand-cluster, never pivot.
{
  const f = point({ cluster: true, cluster_id: 42, point_count: 7 });
  const result = decideClickAction([f], 'gdelt-news-clusters');
  assert(result.action === 'expand-cluster', 'cluster feature → expand-cluster');
  assert(result.clusterId === 42, 'expand-cluster result carries the cluster id');
  assert(result.action !== 'pivot', 'cluster feature never produces pivot');
}

// agent-findings point → pivot.
{
  const f = point({ tool: 'search_ip', target: '8.8.8.8', name: '8.8.8.8' });
  const result = decideClickAction([f], 'agent-findings-points');
  assert(result.action === 'pivot', 'agent-findings point → pivot');
}

// Empty feature array → ignore.
{
  const result = decideClickAction([], 'gdelt-news-points');
  assert(result.action === 'ignore', 'empty feature array → ignore');
}
{
  const result = decideClickAction(undefined, 'gdelt-news-points');
  assert(result.action === 'ignore', 'undefined feature array → ignore');
}

// Cluster feature that ALSO has a label-shaped property → still
// expand-cluster. Guards against "assume the first feature is a point".
{
  const f = point({ cluster: true, cluster_id: 7, name: 'Copied label', html: '<a href="https://evil.example">x</a>' });
  const result = decideClickAction([f], 'gdelt-news-clusters');
  assert(result.action === 'expand-cluster', 'cluster feature with a label property still → expand-cluster, not pivot');
}

// Cluster layer id but a malformed feature missing cluster_id → ignore,
// not a crash and not a false pivot.
{
  const f = point({ cluster: true }); // no cluster_id
  const result = decideClickAction([f], 'gdelt-news-clusters');
  assert(result.action === 'ignore', 'cluster-layer feature without cluster_id → ignore (not pivot, not a crash)');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
