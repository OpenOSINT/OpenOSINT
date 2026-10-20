/**
 * graph-renderer.js — Cytoscape wrapper for the Entity Correlation Graph.
 *
 * Reads window.cytoscape (UMD global loaded before this ES module).
 * fcose layout plugin must also be loaded before this module; if it didn't
 * register, falls back to the built-in 'cose' layout automatically.
 *
 * Exports:
 *   initGraph(containerEl)              — lazy, idempotent
 *   addToGraph({ nodes, edges })        — dedupes by id, debounces layout
 *   clearGraph()
 *   resizeGraph()                       — call when container becomes visible
 *   exportPng()                         — returns base64 data URI or null
 *   exportJson()                        — returns { nodes, edges }
 *
 * Pivot:  set window._graphPivotCallback = (nodeId, nodeData) => {}
 *         before or after initGraph — it is checked at tap time.
 */

const MAX_NODES = 300;
const LAYOUT_DEBOUNCE_MS = 400;

// Node type → fill color (dark-mode palette)
const _TYPE_COLOR = {
  target:         '#d29922',
  email:          '#c084fc',
  username:       '#f97316',
  domain:         '#3fb950',
  subdomain:      '#86efac',
  ip:             '#58a6ff',
  phone:          '#34d399',
  org:            '#94a3b8',
  social_account: '#fb923c',
  breach:         '#f85149',
  paste:          '#fbbf24',
  asn:            '#a78bfa',
};
const _DEFAULT_COLOR = '#8b949e';

function _colorFor(type) {
  return _TYPE_COLOR[type] || _DEFAULT_COLOR;
}

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

let _cy          = null;
let _layoutTimer = null;
let _nodeCount   = 0;
let _capFired    = false;
let _layoutName  = null; // cached after first detection

// ---------------------------------------------------------------------------
// fcose detection — check once after cy is initialised (amendment 4)
// ---------------------------------------------------------------------------

function _detectLayoutName() {
  if (_layoutName) return _layoutName;
  try {
    // Creating a layout object without .run() is safe; throws if name unknown.
    _cy.layout({ name: 'fcose' });
    _layoutName = 'fcose';
  } catch {
    _layoutName = 'cose';
  }
  return _layoutName;
}

// ---------------------------------------------------------------------------
// Layout — debounced (amendment 5): one layout.run() per batch of addToGraph calls
// ---------------------------------------------------------------------------

function _scheduleLayout() {
  clearTimeout(_layoutTimer);
  _layoutTimer = setTimeout(() => {
    if (!_cy || _cy.nodes().length === 0) return;
    const name = _detectLayoutName();
    const opts = name === 'fcose'
      ? { name: 'fcose', animate: true, animationDuration: 300, randomize: false, quality: 'default', nodeDimensionsIncludeLabels: true, padding: 24 }
      : { name: 'cose',  animate: true, animationDuration: 300, randomize: false, padding: 24 };
    _cy.layout(opts).run();
  }, LAYOUT_DEBOUNCE_MS);
}

// ---------------------------------------------------------------------------
// Cytoscape stylesheet
// ---------------------------------------------------------------------------

const _STYLESHEET = [
  {
    selector: 'node',
    style: {
      'label':            'data(label)',
      'text-valign':      'bottom',
      'text-halign':      'center',
      'font-size':        '9px',
      'font-family':      "'JetBrains Mono', 'Fira Code', monospace",
      'color':            '#8b949e',
      'background-color': 'data(color)',
      'width':            '26px',
      'height':           '26px',
      'border-width':     '1.5px',
      'border-color':     '#30363d',
      'text-max-width':   '80px',
      'text-wrap':        'ellipsis',
      'text-margin-y':    '3px',
    },
  },
  {
    // Root / target node — larger, gold border
    selector: 'node[?isRoot]',
    style: {
      'width':          '40px',
      'height':         '40px',
      'border-width':   '3px',
      'border-color':   '#d29922',
      'font-size':      '10px',
      'font-weight':    'bold',
      'color':          '#e6edf3',
    },
  },
  {
    selector: 'node:selected',
    style: {
      'border-width': '3px',
      'border-color': '#58a6ff',
      'color':        '#e6edf3',
    },
  },
  {
    selector: 'edge',
    style: {
      'label':                'data(label)',
      'font-size':            '7px',
      'font-family':          "'JetBrains Mono', monospace",
      'color':                '#484f58',
      'line-color':           '#30363d',
      'target-arrow-color':   '#30363d',
      'target-arrow-shape':   'triangle',
      'curve-style':          'bezier',
      'width':                '1px',
      'arrow-scale':          '0.7',
      'text-rotation':        'autorotate',
      'text-margin-y':        '-6px',
    },
  },
  {
    selector: 'edge:selected',
    style: {
      'line-color':         '#58a6ff',
      'target-arrow-color': '#58a6ff',
    },
  },
];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function initGraph(containerEl) {
  if (_cy) return; // idempotent
  const cytoscape = window.cytoscape;
  if (typeof cytoscape !== 'function') {
    console.error('[ECG] window.cytoscape not available — check CDN load order');
    return;
  }
  _cy = cytoscape({
    container: containerEl,
    style:     _STYLESHEET,
    layout:    { name: 'preset' },
    minZoom:   0.15,
    maxZoom:   4,
    wheelSensitivity: 0.3,
  });

  // Pivot on node tap
  _cy.on('tap', 'node', evt => {
    const cb = window._graphPivotCallback;
    if (typeof cb === 'function') {
      cb(evt.target.id(), evt.target.data());
    }
  });
}

/**
 * Merge nodes and edges into the graph.
 * Nodes inserted first; edges whose endpoints are absent are skipped silently
 * (amendment 3 — handles out-of-order tool arrivals without Cytoscape errors).
 */
export function addToGraph({ nodes = [], edges = [] }) {
  if (!_cy) return;

  // --- Insert nodes first ---
  const nodesToAdd = [];
  for (const n of nodes) {
    if (!n?.id) continue;
    if (_cy.getElementById(n.id).length > 0) continue; // dedupe by id

    if (_nodeCount >= MAX_NODES) {
      if (!_capFired) {
        _capFired = true;
        document.dispatchEvent(new CustomEvent('graph-node-cap', { detail: { max: MAX_NODES } }));
      }
      continue;
    }

    nodesToAdd.push({
      group: 'nodes',
      data: {
        id:     n.id,
        label:  String(n.label || n.id).slice(0, 48),
        type:   n.type   || 'unknown',
        color:  _colorFor(n.type),
        isRoot: !!(n.data?.isRoot),
        ...n.data,
      },
    });
    _nodeCount++;
  }
  if (nodesToAdd.length) _cy.add(nodesToAdd);

  // --- Then edges — skip if either endpoint is absent ---
  const edgesToAdd = [];
  for (const e of edges) {
    if (!e?.source || !e?.target) continue;
    if (_cy.getElementById(e.source).length === 0) continue;
    if (_cy.getElementById(e.target).length === 0) continue;

    const edgeId = `edge:${e.source}|${e.target}|${e.label || ''}`;
    if (_cy.getElementById(edgeId).length > 0) continue; // dedupe

    edgesToAdd.push({
      group: 'edges',
      data: { id: edgeId, source: e.source, target: e.target, label: e.label || '' },
    });
  }
  if (edgesToAdd.length) _cy.add(edgesToAdd);

  if (nodesToAdd.length || edgesToAdd.length) _scheduleLayout();
}

export function clearGraph() {
  if (!_cy) return;
  clearTimeout(_layoutTimer);
  _cy.elements().remove();
  _nodeCount = 0;
  _capFired  = false;
}

/** Call after the graph panel becomes visible to fix blank-canvas on hidden
 * panels. addToGraph()'s layout/fit typically runs while #graph-container is
 * still display:none (the investigation happens on the Chat view) — fit()
 * against a zero-size viewport degenerates, pinning nodes near the origin.
 * resize() alone doesn't recompute that; re-fit here so entering GRAPH
 * always shows a properly framed graph, not a clump in the corner. */
export function resizeGraph() {
  if (!_cy) return;
  _cy.resize();
  if (_cy.nodes().length > 0) _cy.fit(undefined, 24);
}

/** Returns a base64 PNG data URI, or null on failure. */
export function exportPng() {
  if (!_cy) return null;
  try {
    return _cy.png({ output: 'base64uri', scale: 2, bg: '#0d1117' });
  } catch {
    return null;
  }
}

/**
 * Returns the rendered center {x, y} of a node in Cytoscape canvas coordinates
 * (CSS pixels from the top-left of the graph container, zoom/pan applied).
 * Add the container's getBoundingClientRect() offset to get viewport coordinates.
 * Returns null if the graph is uninitialised or the node id is not found.
 */
export function getNodeRenderedBBox(id) {
  if (!_cy) return null;
  const el = _cy.getElementById(id);
  if (!el || el.length === 0) return null;
  const pos = el.renderedPosition();
  return { x: pos.x, y: pos.y };
}

/** Returns a plain { nodes, edges } object for JSON export or download. */
export function exportJson() {
  if (!_cy) return { nodes: [], edges: [] };
  return {
    nodes: _cy.nodes().map(n => ({
      id:    n.id(),
      type:  n.data('type'),
      label: n.data('label'),
      data:  n.data(),
    })),
    edges: _cy.edges().map(e => ({
      source: e.data('source'),
      target: e.data('target'),
      label:  e.data('label'),
    })),
  };
}
