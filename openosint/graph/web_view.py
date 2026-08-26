# openosint/graph/web_view.py
"""
Read-only, Cytoscape-shaped views over a GraphStore for the local web UI.

Kept out of web_server.py so that importing followthemoney (via GraphStore)
only happens when a graph route is actually hit — web_server.py imports this
module lazily, inside the handler, wrapped in try/except ImportError, exactly
the way mcp_server.py gates openosint.graph.mcp_tools. That is what lets the
rest of the web UI keep working when the `graph` extra isn't installed.

Nothing here makes a network call. It reads the local SQLite store through
GraphStore's existing public methods (neighbors(), get_statements_by_entity(),
canonical_for(), resolution_history()) and nothing else — the traversal,
depth cap, cycle guard and fan-out cap all live in GraphStore.neighbors(); we
never re-implement them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from followthemoney.statement import Statement

from openosint.graph.store.db_path import default_db_path
from openosint.graph.store.graph_store import _MAX_DEPTH_CEILING, GraphStore

MAX_DEPTH = _MAX_DEPTH_CEILING
NODE_RENDER_CAP = 300

# entity ids are FtM make_entity_id hashes (hex) or namespaced FtM ids; never
# free text. Reject anything with whitespace, quotes, or path/SQL punctuation.
_ENTITY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

# Which prop to show as a node's display name, best-first.
_NAME_PROPS = ("name", "username", "email", "domain", "phone", "handle")


def is_valid_entity_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ENTITY_ID_RE.match(value))


def open_default_store() -> GraphStore:
    """Open the same local graph.db the MCP tools use (OPENOSINT_GRAPH_DB or ~/.openosint)."""
    return GraphStore(default_db_path())


def latest_resolution_for_pair(store: GraphStore, a: str, b: str):
    """The temporally-latest resolution row for the unordered pair {a, b}, or None.

    Used by the decide endpoint to make an identical repeat decision a no-op —
    the pair's current state is whatever this latest row says.
    """
    return _latest_resolution_by_pair(store).get(frozenset((a, b)))


def _display_name(statements: Sequence[Statement], fallback: str) -> str:
    by_prop: dict[str, str] = {}
    for stmt in statements:
        by_prop.setdefault(stmt.prop, stmt.value)
    for prop in _NAME_PROPS:
        if by_prop.get(prop):
            return by_prop[prop]
    if statements:
        return statements[0].value
    return fallback


def _latest_resolution_by_pair(store: GraphStore) -> dict:
    """Latest resolution row per unordered pair.

    ponytail: full-table scan rebuilt per request — same shape and scale as
    GraphStore._active_pair_edges(); swap for incremental state only if the
    review queue ever outgrows a single analyst's attention.
    """
    latest: dict[frozenset, object] = {}
    for res in store.resolution_history():  # no filter -> every row, oldest first
        latest[frozenset((res.entity_id, res.canonical_id))] = res
    return latest


def _cap_keeping_pairs_together(
    eligible: set[str], resolution_edges: Sequence, *, root: str, node_cap: int
) -> set[str]:
    """Select up to node_cap nodes without ever splitting a same_as candidate pair.

    same_as-connected nodes form atomic units (a pair, or a longer chain): a
    unit is kept whole or excluded whole, so the cap never leaves a dashed edge
    dangling into a dropped node or silently drops one half of a review pair.
    The root's whole unit is always kept so the root stays visible even when its
    own unit exceeds the cap.
    """
    parent = {n: n for n in eligible}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for res in resolution_edges:
        a, b = res.entity_id, res.canonical_id
        if a in parent and b in parent:
            parent[find(a)] = find(b)

    components: dict[str, set[str]] = {}
    for n in eligible:
        components.setdefault(find(n), set()).add(n)

    units = list(components.values())
    root_unit = next((u for u in units if root in u), None)
    ordered = ([root_unit] if root_unit else []) + sorted(
        (u for u in units if u is not root_unit), key=min
    )

    selected: set[str] = set()
    for i, unit in enumerate(ordered):
        if i == 0 and root_unit is not None:
            selected |= unit  # root's unit is non-negotiable
            continue
        if len(selected) + len(unit) <= node_cap:
            selected |= unit  # take whole units only; never orphan a pair
    return selected


def build_subgraph(
    store: GraphStore,
    *,
    entity_id: str,
    depth: int = 1,
    cross_layer: bool = False,
    dataset: str | None = None,
    node_cap: int = NODE_RENDER_CAP,
) -> dict:
    """Assemble a Cytoscape-shaped subgraph around *entity_id*.

    Nodes carry schema, display name, canonical id and the datasets that
    asserted them. Edges are either confirmed statement relationships
    (kind="statement") or same_as resolution hypotheses (kind="same_as",
    with judgement/score/resolution_id). Cross-layer bridge links, when
    requested, are surfaced as bridge nodes/edges.
    """
    depth = max(0, min(int(depth), MAX_DEPTH))
    result = store.neighbors(entity_id, depth=depth, cross_layer=cross_layer)

    node_ids: set[str] = {entity_id, *result.entities}

    # Pull in same_as-linked candidates so an unverified hypothesis is visible
    # even when the two entities share no confirmed statement edge.
    pairs = _latest_resolution_by_pair(store)
    resolution_edges = []
    for _pair, res in pairs.items():
        if res.judgement not in ("unsure", "positive", "negative"):
            continue
        a, b = res.entity_id, res.canonical_id
        if a in node_ids or b in node_ids:
            node_ids.add(a)
            node_ids.add(b)
            resolution_edges.append(res)

    stmts_by_node = {nid: store.get_statements_by_entity(nid) for nid in node_ids}

    # Drop nodes with no statements (never observed here, or erased): there is
    # nothing to render or attribute. dataset filter, when set, keeps only
    # nodes whose FtM entity carries at least one statement from that dataset.
    def _keep(nid: str) -> bool:
        stmts = stmts_by_node.get(nid, [])
        if not stmts:
            return False
        if dataset is not None and not any(s.dataset == dataset for s in stmts):
            return False
        return True

    kept_eligible = {nid for nid in node_ids if _keep(nid)}

    total = len(kept_eligible)
    truncated = total > node_cap
    if truncated:
        kept_ids = _cap_keeping_pairs_together(
            kept_eligible, resolution_edges, root=entity_id, node_cap=node_cap
        )
    else:
        kept_ids = kept_eligible

    nodes = []
    for nid in sorted(kept_ids):
        stmts = stmts_by_node[nid]
        datasets = sorted({s.dataset for s in stmts})
        nodes.append(
            {
                "data": {
                    "id": nid,
                    "schema": stmts[0].schema,
                    "label": _display_name(stmts, nid[:10]),
                    "canonical_id": store.canonical_for(nid),
                    "datasets": datasets,
                    "statement_count": len(stmts),
                    "is_root": nid == entity_id,
                }
            }
        )

    edges = []
    seen_edge = set()
    for source, target, prop in result.edges:
        if source not in kept_ids or target not in kept_ids:
            continue
        key = ("st", source, target, prop)
        if key in seen_edge:
            continue
        seen_edge.add(key)
        edges.append(
            {
                "data": {
                    "id": f"st-{len(edges)}",
                    "source": source,
                    "target": target,
                    "type": prop,
                    "kind": "statement",
                }
            }
        )

    for res in resolution_edges:
        if res.entity_id not in kept_ids or res.canonical_id not in kept_ids:
            continue
        edges.append(
            {
                "data": {
                    "id": f"res-{res.id}",
                    "source": res.entity_id,
                    "target": res.canonical_id,
                    "kind": "same_as",
                    "judgement": res.judgement,
                    "score": res.score,
                    "resolution_id": res.id,
                }
            }
        )

    if cross_layer:
        for link in result.bridge_links:
            if link.ftm_entity_id not in kept_ids:
                continue
            bid = f"bridge:{link.graph_entity_type.value}:{link.graph_entity_normalized}"
            nodes.append(
                {
                    "data": {
                        "id": bid,
                        "schema": "Bridge",
                        "label": link.graph_entity_normalized,
                        "canonical_id": bid,
                        "datasets": [],
                        "statement_count": 0,
                        "is_bridge": True,
                    }
                }
            )
            edges.append(
                {
                    "data": {
                        "id": f"br-{len(edges)}",
                        "source": link.ftm_entity_id,
                        "target": bid,
                        "type": link.relation,
                        "kind": "bridge",
                    }
                }
            )

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "root": entity_id,
            "depth": depth,
            "node_count": total,
            "rendered_count": len([n for n in nodes if not n["data"].get("is_bridge")]),
            "node_cap": node_cap,
            "truncated": truncated,
            "fanout_truncated": result.truncated,
            "empty": total == 0,
        },
    }
