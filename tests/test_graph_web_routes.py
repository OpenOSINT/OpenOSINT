# tests/test_graph_web_routes.py
"""
Endpoint tests for the local graph visualization routes added to web_server.py.

Covers (per the Phase A spec):
  - GET /api/graph/subgraph: depth cap, cycle safety, fan-out cap, invalid
    entity id rejected, dataset filter, empty store, node cap, same_as edges.
  - GET /api/graph/review/candidates: pending queue with parsed explanation.
  - POST /api/graph/review/decide: appends a decided_by='human' resolution and
    is EQUIVALENT to the MCP graph_review_candidates 'decide' path.
  - No graph route makes any outbound network call.
  - Graph routes degrade to 503 when the `graph` extra is unavailable, and
    unrelated routes keep working.

All state is a throwaway SQLite file pointed at by OPENOSINT_GRAPH_DB — the
same knob the MCP tools read — so the web and MCP paths hit the same store.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from followthemoney.statement import Statement
from httpx import ASGITransport, AsyncClient

from openosint.graph.mapping import EmissionResult
from openosint.graph.store import GraphStore
from openosint.graph.store.resolutions import make_resolution

_DATASET = "openosint:test"
_OTHER_DATASET = "openosint:github"
_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_NOW_ISO = _NOW.isoformat()


def _stmt(entity_id: str, prop: str, schema: str, value: str, dataset: str = _DATASET) -> Statement:
    return Statement(
        entity_id=entity_id,
        prop=prop,
        schema=schema,
        value=value,
        dataset=dataset,
        first_seen=_NOW_ISO,
        last_seen=_NOW_ISO,
    )


def _append(store: GraphStore, *statements: Statement) -> None:
    store.append(EmissionResult(statements=tuple(statements), provenance=(), bridge_links=()))


def _edge(store: GraphStore, source: str, target: str) -> None:
    """UserAccount.owner is an entity-typed prop — a real graph edge source->target."""
    _append(store, _stmt(source, "owner", "UserAccount", target))


def _pending_pair(store: GraphStore, a: str, b: str, score: float) -> int:
    detail = json.dumps(
        {
            "run_id": "run-xyz",
            "algorithm": {"name": "LogicV2", "version": "1.0"},
            "features": {
                "name_literal": {"score": score, "query": "John Doe", "candidate": "Jon Doe"}
            },
        },
        sort_keys=True,
    )
    res = make_resolution(
        entity_id=a,
        canonical_id=b,
        judgement="unsure",
        decided_by="auto",
        decided_at=_NOW,
        score=score,
        decided_by_detail=detail,
    )
    return store.append_resolution(res)


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    """A temp graph.db wired into OPENOSINT_GRAPH_DB; returns its path."""
    db_path = tmp_path / "graph.db"
    monkeypatch.setenv("OPENOSINT_GRAPH_DB", str(db_path))
    return db_path


@pytest_asyncio.fixture
async def client():
    from openosint.web_server import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/graph/subgraph
# ---------------------------------------------------------------------------


class TestSubgraph:
    async def test_returns_cytoscape_shaped_nodes_and_edges(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "John Doe"))
        _edge(store, "account-1", "person-1")  # account-1 --owner--> person-1
        _append(store, _stmt("account-1", "username", "UserAccount", "jdoe"))
        store.close()

        resp = await client.get("/api/graph/subgraph", params={"entity_id": "person-1", "depth": 1})
        assert resp.status_code == 200
        body = resp.json()
        ids = {n["data"]["id"] for n in body["nodes"]}
        assert ids == {"person-1", "account-1"}
        person = next(n for n in body["nodes"] if n["data"]["id"] == "person-1")
        assert person["data"]["schema"] == "Person"
        assert person["data"]["label"] == "John Doe"
        assert person["data"]["datasets"] == [_DATASET]  # provenance summary
        assert any(
            e["data"]["kind"] == "statement" and e["data"]["type"] == "owner"
            for e in body["edges"]
        )

    async def test_depth_cap_is_enforced(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "Root"))
        store.close()
        resp = await client.get(
            "/api/graph/subgraph", params={"entity_id": "person-1", "depth": 999}
        )
        assert resp.status_code == 200
        assert resp.json()["meta"]["depth"] == 5  # _MAX_DEPTH_CEILING

    async def test_cycle_is_safe(self, client, graph_db):
        store = GraphStore(graph_db)
        _edge(store, "node-a", "node-b")
        _edge(store, "node-b", "node-a")
        store.close()
        resp = await client.get("/api/graph/subgraph", params={"entity_id": "node-a", "depth": 5})
        assert resp.status_code == 200
        ids = {n["data"]["id"] for n in resp.json()["nodes"]}
        assert ids == {"node-a", "node-b"}

    async def test_fanout_cap_is_reported(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("hub", "name", "Person", "Hub"))
        for i in range(60):  # > _DEFAULT_FANOUT_CAP (50)
            _edge(store, f"account-{i}", "hub")
        store.close()
        resp = await client.get("/api/graph/subgraph", params={"entity_id": "hub", "depth": 1})
        assert resp.status_code == 200
        assert resp.json()["meta"]["fanout_truncated"] is True

    async def test_invalid_entity_id_is_rejected(self, client, graph_db):
        resp = await client.get(
            "/api/graph/subgraph", params={"entity_id": "'; DROP TABLE statements; --"}
        )
        assert resp.status_code == 400

    async def test_empty_entity_id_is_rejected(self, client, graph_db):
        resp = await client.get("/api/graph/subgraph", params={"entity_id": ""})
        assert resp.status_code == 400

    async def test_dataset_filter(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "Root", dataset=_DATASET))
        _edge(store, "account-gh", "person-1")  # owner edge (in _DATASET)
        _append(store, _stmt("account-gh", "username", "UserAccount", "gh", dataset=_OTHER_DATASET))
        store.close()

        resp = await client.get(
            "/api/graph/subgraph",
            params={"entity_id": "person-1", "depth": 1, "dataset": _OTHER_DATASET},
        )
        assert resp.status_code == 200
        ids = {n["data"]["id"] for n in resp.json()["nodes"]}
        # person-1 has no statement in _OTHER_DATASET; account-gh does.
        assert ids == {"account-gh"}

    async def test_empty_store_reports_empty(self, client, graph_db):
        resp = await client.get("/api/graph/subgraph", params={"entity_id": "nobody-here"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["nodes"] == []
        assert body["meta"]["empty"] is True

    async def test_node_cap_truncates_and_reports(self, graph_db):
        # Exercise the cap directly (cheaper than seeding NODE_RENDER_CAP nodes).
        from openosint.graph.web_view import build_subgraph

        store = GraphStore(graph_db)
        _append(store, _stmt("hub", "name", "Person", "Hub"))
        for i in range(10):
            _edge(store, f"acct-{i}", "hub")
        try:
            result = build_subgraph(store, entity_id="hub", depth=1, node_cap=3)
        finally:
            store.close()
        assert result["meta"]["node_count"] == 11
        assert result["meta"]["truncated"] is True
        assert result["meta"]["rendered_count"] == 3
        assert any(n["data"]["id"] == "hub" for n in result["nodes"])  # root kept

    async def test_node_cap_never_orphans_a_same_as_pair(self, graph_db):
        """At the cap boundary a candidate pair is kept together, never half-dropped."""
        from openosint.graph.web_view import build_subgraph

        store = GraphStore(graph_db)
        # root p-root and its same_as partner p-pair (both must survive the cap).
        _append(store, _stmt("p-root", "name", "Person", "Root"))
        _append(store, _stmt("p-pair", "name", "Person", "Maybe-Root"))
        _pending_pair(store, "p-root", "p-pair", 0.7)
        # Six filler neighbors that sort BEFORE 'p-pair' — a naive slice would
        # keep fillers and drop p-pair, orphaning the pair.
        for i in range(6):
            _edge(store, f"f-{i}", "p-root")  # f-i --owner--> p-root
        try:
            result = build_subgraph(store, entity_id="p-root", depth=1, node_cap=3)
        finally:
            store.close()

        ids = {n["data"]["id"] for n in result["nodes"]}
        assert {"p-root", "p-pair"} <= ids  # pair kept together
        same_as = [e for e in result["edges"] if e["data"]["kind"] == "same_as"]
        assert len(same_as) == 1  # edge intact, not dangling
        assert result["meta"]["truncated"] is True

    async def test_unsure_same_as_edge_is_surfaced_with_score(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "John Doe"))
        _append(store, _stmt("person-2", "name", "Person", "Jon Doe"))
        rid = _pending_pair(store, "person-1", "person-2", 0.82)
        store.close()

        resp = await client.get("/api/graph/subgraph", params={"entity_id": "person-1", "depth": 1})
        assert resp.status_code == 200
        same_as = [e["data"] for e in resp.json()["edges"] if e["data"]["kind"] == "same_as"]
        assert len(same_as) == 1
        assert same_as[0]["judgement"] == "unsure"
        assert same_as[0]["score"] == 0.82
        assert same_as[0]["resolution_id"] == rid


# ---------------------------------------------------------------------------
# GET /api/graph/review/candidates
# ---------------------------------------------------------------------------


class TestReviewCandidates:
    async def test_lists_pending_with_readable_explanation(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "John Doe"))
        _append(store, _stmt("person-2", "name", "Person", "Jon Doe"))
        _pending_pair(store, "person-1", "person-2", 0.82)
        store.close()

        resp = await client.get("/api/graph/review/candidates")
        assert resp.status_code == 200
        candidates = resp.json()["candidates"]
        assert len(candidates) == 1
        c = candidates[0]
        assert c["score"] == 0.82
        assert "name_literal" in c["explanation_text"]  # parsed, not raw JSON
        assert c["entity_a_properties"]["name"] == ["John Doe"]

    async def test_empty_queue(self, client, graph_db):
        resp = await client.get("/api/graph/review/candidates")
        assert resp.status_code == 200
        assert resp.json()["candidates"] == []


# ---------------------------------------------------------------------------
# POST /api/graph/review/decide
# ---------------------------------------------------------------------------


class TestReviewDecide:
    async def test_accept_appends_human_positive_resolution(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "John Doe"))
        _append(store, _stmt("person-2", "name", "Person", "Jon Doe"))
        _pending_pair(store, "person-1", "person-2", 0.82)
        store.close()

        resp = await client.post(
            "/api/graph/review/decide",
            json={"entity_id": "person-1", "canonical_id": "person-2", "decision": "accept"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["judgement"] == "positive"
        assert set(body["cluster"]) == {"person-1", "person-2"}  # accepted -> one cluster

        store = GraphStore(graph_db)
        latest = store.resolution_history(entity_id="person-1")[-1]
        store.close()
        assert latest.decided_by == "human"
        assert latest.judgement == "positive"
        assert latest.score is None  # a verdict, not a re-score

    async def test_reject_records_negative_and_drops_from_queue(self, client, graph_db):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "John Doe"))
        _append(store, _stmt("person-2", "name", "Person", "Jon Doe"))
        _pending_pair(store, "person-1", "person-2", 0.4)
        store.close()

        resp = await client.post(
            "/api/graph/review/decide",
            json={"entity_id": "person-1", "canonical_id": "person-2", "decision": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["judgement"] == "negative"

        store = GraphStore(graph_db)
        assert store.pending_resolutions() == []  # rejected pair leaves the queue
        store.close()

    async def test_identical_decision_is_idempotent(self, client, graph_db):
        """A double-click (same pair, same judgement) appends no second row."""
        store = GraphStore(graph_db)
        _append(store, _stmt("p-1", "name", "Person", "John Doe"))
        _append(store, _stmt("p-2", "name", "Person", "Jon Doe"))
        _pending_pair(store, "p-1", "p-2", 0.82)  # 1 auto row
        store.close()

        body = {"entity_id": "p-1", "canonical_id": "p-2", "decision": "accept"}
        r1 = await client.post("/api/graph/review/decide", json=body)
        r2 = await client.post("/api/graph/review/decide", json=body)
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["idempotent"] is False
        assert r2.json()["idempotent"] is True
        assert r2.json()["resolution_id"] == r1.json()["resolution_id"]  # same row returned

        store = GraphStore(graph_db)
        rows = store.resolution_history(entity_id="p-1", canonical_id="p-2")
        store.close()
        # 1 seeded auto 'unsure' + exactly 1 human 'positive' — no duplicate.
        assert [r.judgement for r in rows] == ["unsure", "positive"]

    async def test_revocation_appends_new_row_and_splits_cluster(self, client, graph_db):
        """Reversing a positive merge appends a row (no mutation) and splits the cluster."""
        store = GraphStore(graph_db)
        for eid, name in (("p-1", "A"), ("p-2", "B"), ("p-3", "C")):
            _append(store, _stmt(eid, "name", "Person", name))
        _pending_pair(store, "p-1", "p-2", 0.8)
        _pending_pair(store, "p-2", "p-3", 0.8)
        store.close()

        # Accept both -> one cluster {p-1, p-2, p-3}.
        for a, b in (("p-1", "p-2"), ("p-2", "p-3")):
            resp = await client.post(
                "/api/graph/review/decide",
                json={"entity_id": a, "canonical_id": b, "decision": "accept"},
            )
            assert resp.status_code == 200
        assert set(resp.json()["cluster"]) == {"p-1", "p-2", "p-3"}

        store = GraphStore(graph_db)
        before = store.resolution_history()  # snapshot every row
        store.close()

        # Revoke p-2 <-> p-3 by rejecting it (a new non-positive row for the pair).
        resp = await client.post(
            "/api/graph/review/decide",
            json={"entity_id": "p-2", "canonical_id": "p-3", "decision": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["idempotent"] is False

        store = GraphStore(graph_db)
        after = store.resolution_history()
        # A NEW row was appended; every prior row is untouched (append-only).
        assert len(after) == len(before) + 1
        assert [(r.id, r.judgement) for r in after[: len(before)]] == [
            (r.id, r.judgement) for r in before
        ]
        # Cluster split: {p-1, p-2} and {p-3} standalone.
        assert store.canonical_for("p-1") == "p-2"
        assert store.canonical_for("p-3") == "p-3"
        store.close()

    async def test_invalid_decision_rejected(self, client, graph_db):
        resp = await client.post(
            "/api/graph/review/decide",
            json={"entity_id": "person-1", "canonical_id": "person-2", "decision": "maybe"},
        )
        assert resp.status_code == 400

    async def test_web_decide_equivalent_to_mcp_decide(self, tmp_path, monkeypatch):
        """The web endpoint and the MCP tool must produce the same resolutions row."""
        from openosint.web_server import create_app

        def _seed(db_path) -> None:
            store = GraphStore(db_path)
            _append(store, _stmt("person-1", "name", "Person", "John Doe"))
            _append(store, _stmt("person-2", "name", "Person", "Jon Doe"))
            _pending_pair(store, "person-1", "person-2", 0.82)
            store.close()

        def _decided_tuple(db_path):
            store = GraphStore(db_path)
            row = store.resolution_history(entity_id="person-1")[-1]
            store.close()
            return (row.entity_id, row.canonical_id, row.judgement, row.decided_by, row.score)

        # --- web path ---
        web_db = tmp_path / "web.db"
        _seed(web_db)
        monkeypatch.setenv("OPENOSINT_GRAPH_DB", str(web_db))
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/graph/review/decide",
                json={"entity_id": "person-1", "canonical_id": "person-2", "decision": "accept"},
            )
        assert resp.status_code == 200

        # --- MCP path ---
        mcp_db = tmp_path / "mcp.db"
        _seed(mcp_db)
        monkeypatch.setenv("OPENOSINT_GRAPH_DB", str(mcp_db))
        from openosint.graph.mcp_tools import run_graph_review_candidates

        await run_graph_review_candidates(
            "decide", entity_id="person-1", canonical_id="person-2", decision="accept"
        )

        assert _decided_tuple(web_db) == _decided_tuple(mcp_db)


# ---------------------------------------------------------------------------
# No outbound network + graceful degradation
# ---------------------------------------------------------------------------


class TestNoNetworkAndDegradation:
    async def test_graph_routes_make_no_outbound_network_call(self, client, graph_db, monkeypatch):
        store = GraphStore(graph_db)
        _append(store, _stmt("person-1", "name", "Person", "John Doe"))
        _append(store, _stmt("person-2", "name", "Person", "Jon Doe"))
        _pending_pair(store, "person-1", "person-2", 0.82)
        store.close()

        def _boom(*a, **k):
            raise AssertionError("graph route attempted an outbound network call")

        import socket as _socket

        monkeypatch.setattr(_socket.socket, "connect", _boom, raising=False)
        monkeypatch.setattr(_socket, "create_connection", _boom, raising=False)
        monkeypatch.setattr(_socket, "getaddrinfo", _boom, raising=False)
        import openosint.web_server as ws

        monkeypatch.setattr(ws._requests, "get", _boom, raising=False)
        monkeypatch.setattr(ws._requests, "post", _boom, raising=False)
        if ws._httpx is not None:
            monkeypatch.setattr(ws._httpx, "AsyncClient", _boom, raising=False)

        r1 = await client.get("/api/graph/subgraph", params={"entity_id": "person-1"})
        r2 = await client.get("/api/graph/review/candidates")
        r3 = await client.post(
            "/api/graph/review/decide",
            json={"entity_id": "person-1", "canonical_id": "person-2", "decision": "reject"},
        )
        assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 200)

    async def test_graph_routes_degrade_when_extra_missing(self, client, graph_db, monkeypatch):
        # Force the lazy `from openosint.graph.web_view import ...` to raise ImportError.
        monkeypatch.setitem(sys.modules, "openosint.graph.web_view", None)
        resp = await client.get("/api/graph/subgraph", params={"entity_id": "person-1"})
        assert resp.status_code == 503
        assert resp.json()["graph_available"] is False
        # An unrelated route still works.
        assert (await client.get("/api/health")).status_code == 200
