# tests/test_graph_mcp_tools.py
"""Tests for openosint.graph.mcp_tools — the async MCP tool wrappers (Phase 4).

Each test points OPENOSINT_GRAPH_DB at a fresh temp file so tests never touch
a real user's ~/.openosint/graph.db and never share state with each other.
"""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from openosint.correlation import EntityType, make_entity  # noqa: E402
from openosint.graph.mapping import map_github  # noqa: E402
from openosint.graph.store import GraphStore  # noqa: E402

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


def _profile(login: str, name: str, email: str) -> str:
    return f"[GitHub] Login: {login}\n[GitHub] Name: {name}\n[GitHub] Email (profile): {email}\n"


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    db_path = tmp_path / "graph.db"
    monkeypatch.setenv("OPENOSINT_GRAPH_DB", str(db_path))
    return db_path


class TestRunGraphExport:
    async def test_reports_when_the_store_is_empty(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_export

        result = await run_graph_export()
        assert "No entities" in result

    async def test_exports_ndjson_lines(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_export

        store = GraphStore(str(graph_db))
        store.append(
            map_github(
                _profile("janedoe1", "Jane Doe", "jane@example.com"),
                make_entity(EntityType.USERNAME, "janedoe1", 1.0),
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        store.close()

        result = await run_graph_export()
        lines = result.splitlines()
        assert len(lines) == 2
        import json

        for line in lines:
            entity = json.loads(line)
            assert {"id", "schema", "properties"} == set(entity)


class TestRunGraphNeighbors:
    async def test_reports_no_neighbors_for_unknown_entity(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_neighbors

        result = await run_graph_neighbors("nonexistent-id")
        assert "No neighbors found" in result

    async def test_reports_edges_with_provenance(self, graph_db):
        from openosint.graph.identity import entity_id_for
        from openosint.graph.mcp_tools import run_graph_neighbors

        store = GraphStore(str(graph_db))
        store.append(
            map_github(
                _profile("janedoe1", "Jane Doe", "jane@example.com"),
                make_entity(EntityType.USERNAME, "janedoe1", 1.0),
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        store.close()

        person_id = entity_id_for("Person", "github", "janedoe1")
        result = await run_graph_neighbors(person_id, depth=1)
        assert "Entities (1)" in result
        assert "map_github:owner" in result
        assert "confidence=" in result


class TestRunGraphReviewCandidates:
    async def test_list_reports_empty_queue(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_review_candidates

        result = await run_graph_review_candidates("list")
        assert result == "No pending review candidates."

    async def test_decide_requires_a_valid_decision(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_review_candidates

        with pytest.raises(ValueError):
            await run_graph_review_candidates(
                "decide", entity_id="a", canonical_id="b", decision="maybe"
            )

    async def test_decide_reject_round_trips_through_a_fresh_store(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_review_candidates

        result = await run_graph_review_candidates(
            "decide", entity_id="a", canonical_id="b", decision="reject", reviewer_id="tommy"
        )
        assert "reject" in result
        assert "a <-> b" in result

        store = GraphStore(str(graph_db))
        assert store.canonical_for("a") == "a"
        store.close()

    async def test_unknown_action_raises(self, graph_db):
        from openosint.graph.mcp_tools import run_graph_review_candidates

        with pytest.raises(ValueError):
            await run_graph_review_candidates("bogus")
