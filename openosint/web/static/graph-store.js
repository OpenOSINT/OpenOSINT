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

// Clicking a dashed same_as edge jumps to that pair's review card.
function onSameAsEdge(d) {
  if (d.judgement === "unsure") {
    enterReview({ resolution_id: d.resolution_id, a: d.source, b: d.target });
  } else {
    // Already decided (accepted/rejected): no pending card to show.
    showEntity(d.source);
  }
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

// ===========================================================================
// Review queue — human accept/reject of same_as candidates.
// Every accept asserts two records are the same real entity. The UI is built
// so that never feels automatic: one pair at a time, evidence side by side,
// no bulk actions, and honest labeling of what the score is.
// ===========================================================================

const review = { queue: [], index: 0, busy: false, last: null };

async function refreshReviewCount() {
  try {
    const r = await fetch("/api/graph/review/candidates");
    if (!r.ok) return;
    const data = await r.json();
    $("reviewCount").textContent = data.candidates.length;
  } catch (e) { /* leave stale count */ }
}

async function enterReview(focusPair) {
  $("side").classList.remove("open");
  $("review").classList.add("open");
  $("rv-body").innerHTML = '<p class="rv-empty">Loading…</p>';
  $("rv-foot").classList.remove("show");
  let data;
  try {
    const r = await fetch("/api/graph/review/candidates");
    if (r.status === 503) return renderReviewUnavailable();
    if (!r.ok) { $("rv-body").innerHTML = `<p class="rv-empty">Error ${r.status}.</p>`; return; }
    data = await r.json();
  } catch (e) { $("rv-body").innerHTML = '<p class="rv-empty">Request failed.</p>'; return; }

  review.queue = data.candidates;
  $("reviewCount").textContent = review.queue.length;
  review.index = 0;
  if (focusPair) {
    const i = review.queue.findIndex(
      (c) => c.resolution_id === focusPair.resolution_id ||
             pairEq(c, focusPair.a, focusPair.b));
    if (i >= 0) review.index = i;
  }
  renderCard();
}

function pairEq(c, a, b) {
  return (c.entity_id_a === a && c.entity_id_b === b) ||
         (c.entity_id_a === b && c.entity_id_b === a);
}

function renderReviewUnavailable() {
  $("rv-body").innerHTML =
    "<div class='rv-empty'><h3>Graph module unavailable</h3><p>Install the optional extra: <code>pip install 'openosint[graph]'</code>.</p></div>";
  $("rv-foot").classList.remove("show");
}

function renderEmptyQueue() {
  $("rv-foot").classList.remove("show");
  $("rv-body").innerHTML = `<div class="rv-empty">
    <h3>No candidates pending</h3>
    <p>Nothing is waiting for review. Same_as candidates appear here when a
       cross-reference pass finds two entities that <em>might</em> be the same and
       is not sure — they are never merged automatically.</p>
    <p>They get created by running the dedup cross-reference over the graph store
       (the <code>graph_dedup_crossref</code> path / MCP tool). Until then, this
       queue stays empty.</p></div>`;
}

async function renderCard() {
  if (review.index >= review.queue.length) return renderEmptyQueue();
  const c = review.queue[review.index];
  $("rv-pos").textContent = `${review.index + 1} of ${review.queue.length}`;

  // Fetch both entities' full detail (statements + provenance) for the compare.
  $("rv-body").innerHTML = '<p class="rv-empty">Loading pair…</p>';
  let da, db;
  try {
    [da, db] = await Promise.all([fetchEntity(c.entity_id_a), fetchEntity(c.entity_id_b)]);
  } catch (e) { $("rv-body").innerHTML = '<p class="rv-empty">Could not load entities.</p>'; return; }

  const algo = c.algorithm_name ? `${esc(c.algorithm_name)}${c.algorithm_version ? " v" + esc(c.algorithm_version) : ""}` : "the dedup rules";
  const scoreTxt = c.score != null ? Number(c.score).toFixed(2) : "?";
  const html = `
    <div class="score-row">
      <span class="score">${scoreTxt}</span>
      <span class="schema-chip" style="background:${schemaStyle(c.schema).color}">${esc(c.schema)}</span>
    </div>
    <div class="score-hint">Rule-based match score from ${algo} — <b>not</b> a probability.
      It means the rules judged these fairly similar, not that they are ${Math.round((c.score||0)*100)}% likely the same.
      You are asserting a real-world identity; decide on the evidence below.</div>
    ${renderFeatures(c.explanation_text)}
    ${renderCompare(da, db)}`;
  $("rv-body").innerHTML = html;
  $("rv-foot").classList.add("show");
  setDecideDisabled(false);
}

async function fetchEntity(id) {
  const r = await fetch("/api/graph/entity?entity_id=" + encodeURIComponent(id));
  if (!r.ok) throw new Error("entity " + r.status);
  return r.json();
}

// Turn the server's "name_literal=0.82 ('John Doe' vs 'Jon Doe'); ..." string
// into readable rows. Never shows raw JSON. Falls back to the raw text.
function renderFeatures(text) {
  if (!text || text === "No feature explanation recorded.")
    return `<div class="feat"><h4>Why suggested</h4><div class="frow"><span class="fname">No feature explanation recorded.</span></div></div>`;
  const rows = text.split(";").map((part) => {
    const m = part.trim().match(/^([\w.]+)\s*=\s*([\d.?]+)\s*(?:\((.*)\))?$/);
    if (!m) return `<div class="frow"><span class="fname">${esc(part.trim())}</span></div>`;
    const name = m[1].replace(/_/g, " ");
    const score = m[2];
    const vals = m[3] ? m[3].replace(/'/g, "").replace(/\s+vs\s+/, " ↔ ") : "";
    return `<div class="frow"><span class="fname">${esc(name)}</span>
      <span class="fval">${esc(vals)}</span><span class="fscore">${esc(score)}</span></div>`;
  }).join("");
  return `<div class="feat"><h4>Why suggested — which comparator fired</h4>${rows}</div>`;
}

// Prop -> [{value, dataset, method, conf}] from an entity detail payload.
function sideProps(detail) {
  const out = {};
  for (const s of detail.statements) {
    const top = (s.provenance || [])[0] || {};
    (out[s.prop] ||= []).push({
      value: s.value, dataset: s.dataset,
      method: top.collection_method, conf: top.extractor_confidence,
    });
  }
  return out;
}

const _PROP_ORDER = ["name", "username", "email", "domain", "phone", "country", "nationality"];

function renderCompare(da, db) {
  const pa = sideProps(da), pb = sideProps(db);
  const props = Array.from(new Set([...Object.keys(pa), ...Object.keys(pb)]));
  props.sort((x, y) => {
    const ix = _PROP_ORDER.indexOf(x), iy = _PROP_ORDER.indexOf(y);
    if (ix !== -1 || iy !== -1) return (ix === -1 ? 99 : ix) - (iy === -1 ? 99 : iy);
    return x.localeCompare(y);
  });

  let grid = `<div class="cmp">
    <div class="col-head">${esc(da.label)}<span class="cid">${esc(da.entity_id)}</span></div>
    <div class="col-head">${esc(db.label)}<span class="cid">${esc(db.entity_id)}</span></div>`;
  for (const prop of props) {
    const av = pa[prop] || [], bv = pb[prop] || [];
    const aset = new Set(av.map((x) => x.value)), bset = new Set(bv.map((x) => x.value));
    grid += `<div class="prop-label">${esc(prop)}</div>`;
    grid += cell(av, bset);
    grid += cell(bv, aset);
  }
  grid += `</div>`;
  return grid;
}

function cell(values, otherSet) {
  if (!values.length) return `<div class="cell absent">—</div>`;
  const inner = values.map((v) => {
    const matched = otherSet.has(v.value);
    const tag = matched ? '<span class="match-tag">match</span>' : '<span class="diff-tag">differs</span>';
    const prov = `${esc(v.dataset || "")}${v.method ? " · " + esc(v.method) : ""}${v.conf != null ? " (" + Number(v.conf).toFixed(2) + ")" : ""}`;
    return `${tag}<div>${esc(v.value)}</div><div class="prov">${prov}</div>`;
  }).join('<hr style="border:none;border-top:1px dashed var(--border-50);margin:5px 0">');
  const anyMatch = values.some((v) => otherSet.has(v.value));
  const anyDiff = values.some((v) => !otherSet.has(v.value));
  const cls = anyMatch && !anyDiff ? "match" : (anyDiff && !anyMatch ? "diff" : "");
  return `<div class="cell ${cls}">${inner}</div>`;
}

function setDecideDisabled(state) {
  review.busy = state;
  for (const id of ["rv-accept", "rv-reject", "rv-skip"]) $(id).disabled = state;
}

async function decide(decision) {
  if (review.busy || review.index >= review.queue.length) return;
  const c = review.queue[review.index];
  setDecideDisabled(true);              // guard 5: no double-fire during request
  clearUndo();
  let res;
  try {
    res = await postDecide(c.entity_id_a, c.entity_id_b, decision);
  } catch (e) {
    return showDecideError("Request failed — decision NOT recorded. Try again.");
  }
  if (!res.ok) {
    return showDecideError(`Server error ${res.status} — decision NOT recorded.`);
  }
  // Only on confirmed success: drop from queue, refresh graph, offer undo, advance.
  review.last = { a: c.entity_id_a, b: c.entity_id_b, decision };
  review.queue.splice(review.index, 1);
  $("reviewCount").textContent = review.queue.length;
  setDecideDisabled(false);             // request done — clear busy so Undo can fire
  await reloadGraphInPlace();
  showUndo(decision);
  renderCard();                         // stays on same index = next pending pair
}

async function postDecide(a, b, decision) {
  const r = await fetch("/api/graph/review/decide", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity_id: a, canonical_id: b, decision }),
  });
  return { ok: r.ok, status: r.status };
}

function skip() {
  if (review.busy) return;
  clearUndo();
  review.index += 1;                    // leave pending, move on
  renderCard();
}

async function undo() {
  if (!review.last || review.busy) return;
  const { a, b, decision } = review.last;
  // Revocation reuses the decide endpoint: append the opposite judgement (a new
  // row, never a mutation) so an accidental merge is reversed / a reject undone.
  const opposite = decision === "accept" ? "reject" : "accept";
  const bar = $("rv-undo");
  bar.querySelector("button").disabled = true;
  let res;
  try { res = await postDecide(a, b, opposite); }
  catch (e) { bar.classList.add("err"); bar.querySelector(".msg").textContent = "Undo failed."; return; }
  if (!res.ok) { bar.classList.add("err"); bar.querySelector(".msg").textContent = "Undo failed."; return; }
  review.last = null;
  await reloadGraphInPlace();
  bar.innerHTML = `<span class="msg">Reversed — appended a ${opposite === "reject" ? "reject" : "accept"} row (nothing deleted).</span>`;
  setTimeout(clearUndo, 4000);
}

function showUndo(decision) {
  const bar = $("rv-undo");
  bar.classList.remove("err");
  bar.style.display = "flex";
  bar.innerHTML = `<span class="msg">${decision === "accept" ? "Accepted ✓" : "Rejected"} — recorded.</span>
    <button id="rv-undo-btn">Undo<span class="kbd">U</span></button>`;
  $("rv-undo-btn").addEventListener("click", undo);
}

function clearUndo() { const b = $("rv-undo"); b.style.display = "none"; b.classList.remove("err"); b.innerHTML = ""; }

function showDecideError(msg) {
  const bar = $("rv-undo");
  bar.style.display = "flex";
  bar.classList.add("err");
  bar.innerHTML = `<span class="msg">${esc(msg)}</span>`;
  setDecideDisabled(false);             // re-enable so they can retry — do NOT advance
}

async function reloadGraphInPlace() {
  if (cy && $("entity").value.trim()) { await load(); }
}

function exitReview() { $("review").classList.remove("open"); clearUndo(); }

// Show the current pair's two entities in the graph, rooted at side A.
function showPairInGraph(e) {
  e && e.preventDefault();
  if (review.index >= review.queue.length) return;
  const c = review.queue[review.index];
  $("entity").value = c.entity_id_a;
  load();
}

$("reviewBtn").addEventListener("click", () => enterReview());
$("rv-close").addEventListener("click", exitReview);
$("rv-accept").addEventListener("click", () => decide("accept"));
$("rv-reject").addEventListener("click", () => decide("reject"));
$("rv-skip").addEventListener("click", skip);
$("rv-showgraph").addEventListener("click", showPairInGraph);

// Keyboard: only while the review panel is open and not typing in an input.
document.addEventListener("keydown", (e) => {
  if (!$("review").classList.contains("open")) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test((e.target.tagName || ""))) return;
  const k = e.key.toLowerCase();
  if (k === "a") { e.preventDefault(); decide("accept"); }
  else if (k === "r") { e.preventDefault(); decide("reject"); }
  else if (k === "s") { e.preventDefault(); skip(); }
  else if (k === "u") { e.preventDefault(); undo(); }
  else if (k === "escape") exitReview();
});

drawLegend();
refreshReviewCount();
const initial = new URLSearchParams(location.search).get("entity_id");
if (initial) { $("entity").value = initial; load(); }
else $("empty").classList.add("show");
