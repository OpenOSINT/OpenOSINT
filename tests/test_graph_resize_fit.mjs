/**
 * Unit tests for resizeGraph()'s fit-on-resize behavior.
 *
 * addToGraph()'s layout/fit runs while #graph-container is typically still
 * display:none (the investigation happens on the Chat view) — fit() against
 * a zero-size viewport degenerates, pinning nodes near the origin. resize()
 * alone doesn't recompute that; resizeGraph() must also re-fit.
 *
 * A fake `cytoscape` factory stands in for the real library — enough of its
 * API surface for initGraph()/addToGraph()/resizeGraph() to run, with call
 * counts to assert against. No real paint pipeline needed.
 *
 * Run: node tests/test_graph_resize_fit.mjs
 */

function fakeCytoscape() {
  const nodesById = new Map();
  const calls = { resize: 0, fit: 0 };
  return {
    _calls: calls,
    on() {},
    getElementById(id) {
      return { length: nodesById.has(id) ? 1 : 0 };
    },
    add(elements) {
      for (const el of elements) {
        if (el.group === 'nodes') nodesById.set(el.data.id, el);
      }
    },
    layout() {
      return { run() {} };
    },
    resize() {
      calls.resize++;
    },
    fit() {
      calls.fit++;
    },
    nodes() {
      return { length: nodesById.size };
    },
    elements() {
      return { remove: () => nodesById.clear() };
    },
  };
}

globalThis.window = { cytoscape: () => fakeInstance };
let fakeInstance;

const { initGraph, addToGraph, resizeGraph } = await import(
  '../openosint/web/static/graph-renderer.js'
);

let passed = 0, failed = 0;
function assert(cond, label) {
  if (cond) { console.log(`  ✓ ${label}`); passed++; }
  else       { console.error(`  ✗ ${label}`); failed++; }
}

console.log('\nresizeGraph');

fakeInstance = fakeCytoscape();
initGraph({});

// No-op with no nodes yet — must not throw calling .fit() on an empty graph.
resizeGraph();
assert(fakeInstance._calls.resize === 1, 'resize() is always called');
assert(fakeInstance._calls.fit === 0, 'fit() is skipped when the graph has no nodes yet');

addToGraph({ nodes: [{ id: 'ip:8.8.8.8', type: 'ip', label: '8.8.8.8' }] });

resizeGraph();
assert(fakeInstance._calls.resize === 2, 'resize() is called again on a second entry');
assert(fakeInstance._calls.fit === 1, 'fit() re-runs once nodes exist — the fix for the corner-clump bug');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
