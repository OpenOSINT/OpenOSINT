/*
 * graph-store.js — renders the local FtM entity graph store in Cytoscape.
 *
 * Reads window.cytoscape (vendored UMD global, loaded before this file). Talks
 * only to this server's local /api/graph/* routes — no third-party calls.
 *
 * Visual encoding is load-bearing and must never imply certainty we don't have:
 *   - node color+shape encode FtM schema (Person/LegalEntity/Organization/UserAccount)
 *   - CONFIRMED statement edges are SOLID
 *   - same_as candidates (judgement 'unsure') are DASHED and labeled with the
 *     score, so they read as unverified machine hypotheses, not facts
 *   - accepted (positive) merges group into a visible cluster box; rejected
 *     (negative) same_as edges get a distinct 'rejected' style — never silent
 *   - Bridge nodes point into the raw infra graph; they are desaturated, a
 *     different shape, and NOT inspectable as entities.
 */
"use strict";

const CSS = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// FtM schema -> {color, shape}. Unknown schemas fall back to a neutral gray dot.
const SCHEMA = {
  Person:       { color: CSS("--person"), shape: "ellipse" },
  Organization: { color: CSS("--org"),    shape: "hexagon" },
  LegalEntity:  { color: CSS("--legal"),  shape: "round-rectangle" },
  UserAccount:  { color: CSS("--user"),   shape: "diamond" },
};
const DEFAULT_SCHEMA = { color: "#8b949e", shape: "ellipse" };
const BRIDGE = { color: CSS("--bridge"), shape: "rectangle" };

function schemaStyle(s) { return SCHEMA[s] || DEFAULT_SCHEMA; }

let cy = null;
const $ = (id) => document.getElementById(id);

function setStatus(msg) { $("status").textContent = msg || ""; }

function baseStyle() {
  return [
    { selector: "node[!isBridge]", style: {
        "background-color": "data(color)", "shape": "data(shape)",
        "label": "data(label)", "color": CSS("--text"), "font-size": 10,
        "text-valign": "bottom", "text-margin-y": 3, "text-max-width": 120,
        "text-wrap": "ellipsis", "width": 26, "height": 26,
        "border-width": 2, "border-color": "#0d1117",
    }},
    { selector: "node[?isRoot]", style: {
        "border-width": 3, "border-color": CSS("--accent"), "width": 34, "height": 34,
    }},
    { selector: "node[?isBridge]", style: {   // pointer into infra graph, NOT an entity
        "background-color": BRIDGE.color, "background-opacity": 0.35, "shape": BRIDGE.shape,
        "label": "data(label)", "color": CSS("--muted"), "font-size": 9,
        "border-width": 1, "border-color": BRIDGE.color, "border-style": "dashed",
        "text-valign": "bottom", "text-margin-y": 2, "width": 20, "height": 14,
    }},
    { selector: "node.cluster", style: {         // canonical cluster box (nodes stay visible)
        "background-color": CSS("--pos"), "background-opacity": 0.06,
        "border-width": 1, "border-color": CSS("--pos"), "border-style": "dashed",
        "shape": "round-rectangle", "label": "data(label)", "font-size": 9,
        "color": CSS("--pos"), "text-valign": "top", "text-margin-y": -2, "padding": 14,
    }},
    // Confirmed statement relationships: SOLID.
    { selector: "edge[kind='statement']", style: {
        "width": 1.5, "line-color": "#8b949e", "curve-style": "bezier",
        "target-arrow-color": "#8b949e", "target-arrow-shape": "triangle", "arrow-scale": 0.8,
        "label": "data(type)", "font-size": 8, "color": CSS("--muted"),
        "text-rotation": "autorotate", "text-background-color": CSS("--bg"),
        "text-background-opacity": 0.7, "text-background-padding": 1,
    }},
    // same_as hypothesis, still unverified: DASHED + score label. Visually loud.
    { selector: "edge[kind='same_as'][judgement='unsure']", style: {
        "width": 2, "line-color": CSS("--unsure"), "line-style": "dashed",
        "curve-style": "bezier", "target-arrow-shape": "none",
        "label": "data(scoreLabel)", "font-size": 9, "color": CSS("--unsure"),
        "text-background-color": CSS("--bg"), "text-background-opacity": 0.8,
        "text-background-padding": 2,
    }},
    // Accepted merge: solid, positive color.
    { selector: "edge[kind='same_as'][judgement='positive']", style: {
        "width": 2.5, "line-color": CSS("--pos"), "curve-style": "bezier",
        "target-arrow-shape": "none", "label": "same_as ✓", "font-size": 8, "color": CSS("--pos"),
    }},
    // Rejected: visible 'rejected' state, never silent disappearance.
    { selector: "edge[kind='same_as'][judgement='negative']", style: {
        "width": 1.5, "line-color": CSS("--neg"), "line-style": "dotted", "opacity": 0.55,
        "curve-style": "bezier", "target-arrow-shape": "none",
        "label": "rejected", "font-size": 8, "color": CSS("--neg"),
    }},
    { selector: "edge[kind='bridge']", style: {
        "width": 1, "line-color": BRIDGE.color, "line-style": "dotted", "opacity": 0.6,
        "curve-style": "bezier", "target-arrow-shape": "none",
    }},
    { selector: ":selected", style: { "border-color": CSS("--accent"), "line-color": CSS("--accent") } },
  ];
}

function toElements(data) {
  const nodes = [];
  const edges = [];

  // Cluster parents: a canonical id shared by >=2 rendered (non-bridge) nodes
  // becomes a visible group box; members keep their own node inside it.
  const byCanonical = {};
  for (const n of data.nodes) {
    if (n.data.is_bridge) continue;
    (byCanonical[n.data.canonical_id] ||= []).push(n.data.id);
  }
  const clusterParent = {};
  for (const [cid, members] of Object.entries(byCanonical)) {
    if (members.length < 2) continue;
    const pid = "cluster:" + cid;
    nodes.push({ data: { id: pid, label: "cluster" }, classes: "cluster" });
    for (const m of members) clusterParent[m] = pid;
  }

  for (const n of data.nodes) {
    const d = n.data;
    const st = d.is_bridge ? BRIDGE : schemaStyle(d.schema);
    nodes.push({ data: {
      id: d.id, label: d.label || d.id.slice(0, 8), schema: d.schema,
      color: st.color, shape: st.shape, isRoot: !!d.is_root, isBridge: !!d.is_bridge,
      canonical_id: d.canonical_id, datasets: d.datasets || [],
      parent: clusterParent[d.id],
    }});
  }

  for (const e of data.edges) {
    const d = e.data;
    edges.push({ data: {
      id: d.id, source: d.source, target: d.target, kind: d.kind,
      type: d.type || "", judgement: d.judgement || "",
      resolution_id: d.resolution_id,
      scoreLabel: d.score != null ? Number(d.score).toFixed(2) : "?",
    }});
  }
  return [...nodes, ...edges];
}

function render(data) {
  const empty = data.meta.empty || data.nodes.length === 0;
  $("empty").classList.toggle("show", empty);

  const cap = $("cap");
  if (data.meta.truncated) {
    cap.style.display = "block";
    cap.textContent = `Showing ${data.meta.rendered_count} of ${data.meta.node_count} nodes (cap ${data.meta.node_cap}). Narrow with a lower depth or a dataset filter.`;
  } else if (data.meta.fanout_truncated) {
    cap.style.display = "block";
    cap.textContent = "Some high-degree nodes exceeded the fan-out cap; a few neighbors are omitted.";
  } else {
    cap.style.display = "none";
  }

  if (cy) cy.destroy();
  cy = window.cytoscape({
    container: $("cy"),
    elements: toElements(data),
    style: baseStyle(),
    layout: { name: "cose", animate: false, padding: 30, nodeRepulsion: 6000, idealEdgeLength: 90 },
    wheelSensitivity: 0.2,
  });

  cy.on("tap", "node", (evt) => {
    const d = evt.target.data();
    if (d.id.startsWith("cluster:")) return;
    if (d.isBridge) return showBridge(d);
    showEntity(d.id);
  });
  cy.on("tap", "edge[kind='same_as']", (evt) => onSameAsEdge(evt.target.data()));
  cy.on("tap", (evt) => { if (evt.target === cy) closeSide(); });
}

// ---- side panel -----------------------------------------------------------

function closeSide() { $("side").classList.remove("open"); }

function openSide(html) { const s = $("side"); s.innerHTML = html; s.classList.add("open"); }

function showBridge(d) {
  openSide(`<button class="close" onclick="document.getElementById('side').classList.remove('open')">✕</button>
    <h2>${esc(d.label)}</h2>
    <span class="schema-chip" style="background:${BRIDGE.color}">BRIDGE</span>
    <p style="color:var(--muted);font-size:12px;line-height:1.5">
      This is a <b>pointer into the raw infrastructure graph</b> (IP, domain, hash),
      not a FollowTheMoney entity. It has no statements or provenance of its own and
      is not inspectable as an entity here.</p>`);
}

async function showEntity(entityId) {
  openSide('<p style="color:var(--muted)">Loading…</p>');
  let detail;
  try {
    const r = await fetch("/api/graph/entity?entity_id=" + encodeURIComponent(entityId));
    if (r.status === 404) return openSide(`<p style="color:var(--muted)">Entity not found.</p>`);
    if (!r.ok) return openSide(`<p style="color:var(--neg)">Error ${r.status}.</p>`);
    detail = await r.json();
  } catch (e) {
    return openSide(`<p style="color:var(--neg)">Request failed.</p>`);
  }

  const st = schemaStyle(detail.schema);
  const cluster = (detail.cluster && detail.cluster.length > 1)
    ? `<p style="font-size:12px;color:var(--pos)">In a canonical cluster of ${detail.cluster.length} entities (accepted merges).</p>` : "";
  const stmts = detail.statements.map(renderStmt).join("");
  openSide(`
    <button class="close" onclick="document.getElementById('side').classList.remove('open')">✕</button>
    <h2>${esc(detail.label)}</h2>
    <span class="schema-chip" style="background:${st.color}">${esc(detail.schema)}</span>
    <div class="id">${esc(detail.entity_id)}</div>
    ${cluster}
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px">Asserted by: ${detail.datasets.map(esc).join(", ") || "—"}</div>
    ${stmts}`);
}

function renderStmt(s) {
  const prov = s.provenance.map((p) => {
    const conf = typeof p.extractor_confidence === "number" ? p.extractor_confidence : null;
    const bar = conf != null
      ? `<span class="conf-bar" style="width:${Math.round(conf * 40)}px"></span> ${conf.toFixed(2)}` : "—";
    return `<div class="prov">
      <b>${esc(p.collection_method)}</b> · confidence ${bar}<br>
      run <span style="font-family:var(--mono)">${esc(p.run_id)}</span>
      ${p.breach_name ? "· breach " + esc(p.breach_name) : ""}
      · ${esc((p.collected_at || "").slice(0, 10))}
    </div>`;
  }).join("");
  return `<div class="stmt">
    <div class="prop">${esc(s.prop)} <span style="color:var(--muted)">· ${esc(s.dataset)}</span></div>
    <div class="val">${esc(s.value)}</div>
    ${s.origin ? `<div style="font-size:11px;color:var(--muted)">origin: ${esc(s.origin)}</div>` : ""}
    ${prov || '<div class="prov">no provenance recorded</div>'}
  </div>`;
}

// Phase C wires this to jump to the pair's review card. For now, surface the pair.
function onSameAsEdge(d) {
  openSide(`<button class="close" onclick="document.getElementById('side').classList.remove('open')">✕</button>
    <h2>same_as candidate</h2>
    <span class="schema-chip" style="background:${CSS("--unsure")}">${esc(d.judgement || "unsure")}</span>
    <div class="id">${esc(d.source)}<br>↕ ${d.scoreLabel}<br>${esc(d.target)}</div>
    <p style="color:var(--muted);font-size:12px">The review queue UI (accept / reject) lands in the next phase; this edge will jump to its review card.</p>`);
  window._pendingReviewPair = { entity_id: d.source, canonical_id: d.target, resolution_id: d.resolution_id };
}

// ---- helpers --------------------------------------------------------------

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function load() {
  const entity = $("entity").value.trim();
  if (!entity) { setStatus("enter an entity id"); return; }
  const params = new URLSearchParams({ entity_id: entity, depth: $("depth").value });
  if ($("cross").checked) params.set("cross_layer", "true");
  const ds = $("dataset").value.trim();
  if (ds) params.set("dataset", ds);

  setStatus("loading…");
  closeSide();
  try {
    const r = await fetch("/api/graph/subgraph?" + params.toString());
    if (r.status === 503) { setStatus("graph extra not installed"); showGraphUnavailable(); return; }
    if (r.status === 400) { setStatus("invalid entity id"); return; }
    if (!r.ok) { setStatus("error " + r.status); return; }
    const data = await r.json();
    render(data);
    setStatus(`${data.meta.rendered_count} nodes · depth ${data.meta.depth}`);
    const u = new URL(location); u.searchParams.set("entity_id", entity); history.replaceState(null, "", u);
  } catch (e) {
    setStatus("request failed");
  }
}

function showGraphUnavailable() {
  $("empty").classList.add("show");
  $("empty").querySelector(".card").innerHTML =
    "<h3>Graph module unavailable</h3><p>Install the optional extra: <code>pip install 'openosint[graph]'</code>, then reload.</p>";
}

function drawLegend() {
  const rows = [
    ["Person", SCHEMA.Person.color], ["Organization", SCHEMA.Organization.color],
    ["LegalEntity", SCHEMA.LegalEntity.color], ["UserAccount", SCHEMA.UserAccount.color],
    ["Bridge (infra)", BRIDGE.color],
  ].map(([l, c]) => `<div class="row"><span class="sw" style="background:${c}"></span>${l}</div>`).join("");
  const lines = [
    ["confirmed", "#8b949e", "solid"], ["same_as (unsure)", CSS("--unsure"), "dashed"],
    ["accepted", CSS("--pos"), "solid"], ["rejected", CSS("--neg"), "dotted"],
  ].map(([l, c, s]) => `<div class="row"><span class="ln" style="border-top-color:${c};border-top-style:${s}"></span>${l}</div>`).join("");
  $("legend").innerHTML = rows + '<div style="height:6px"></div>' + lines;
}

$("load").addEventListener("click", load);
$("entity").addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
$("relayout").addEventListener("click", () => cy && cy.layout({ name: "cose", animate: true }).run());
$("png").addEventListener("click", () => {
  if (!cy) return;
  const a = document.createElement("a");
  a.href = cy.png({ full: true, bg: CSS("--bg"), scale: 2 });
  a.download = "graph.png"; a.click();
});

drawLegend();
const initial = new URLSearchParams(location.search).get("entity_id");
if (initial) { $("entity").value = initial; load(); }
else $("empty").classList.add("show");
