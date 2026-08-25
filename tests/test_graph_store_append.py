# tests/test_graph_store_append.py
"""Tests for GraphStore.append() — statement idempotency vs. provenance growth."""

from __future__ import annotations

from datetime import datetime, timezone

from openosint.correlation import EntityType, make_entity
from openosint.graph.mapping import map_breach, map_github
from openosint.graph.store import GraphStore

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_GITHUB_SEED = make_entity(EntityType.USERNAME, "octocat", 1.0)
_GITHUB_RAW = "[GitHub] Login: octocat\n[GitHub] Name: The Octocat\n"
_BREACH_SEED = make_entity(EntityType.EMAIL, "jane@example.com", 1.0)
_BREACH_RAW = (
    "Found in 2 breach(es) for 'jane@example.com':\n\n"
    "[+] Adobe (2013-10-04) — leaked: Emails\n"
    "[+] LinkedIn (2012-05-05) — leaked: Emails\n"
)


class TestAppendIdempotency:
    def test_statements_are_not_duplicated_on_repeat_append(self):
        store = GraphStore(":memory:")
        result = map_github(_GITHUB_RAW, _GITHUB_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        store.append(result)  # same content, same run — must not duplicate the statement row
        rows = store._conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()
        assert rows["n"] == len(result.statements)
        store.close()

    def test_provenance_grows_on_every_append_even_with_identical_content(self):
        store = GraphStore(":memory:")
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        store.append(result)
        prov = store.get_provenance(result.statements[0].id)
        assert len(prov) == 4  # 2 breaches x 2 appends — every observation kept
        store.close()

    def test_bridge_links_are_not_duplicated_on_repeat_append(self):
        store = GraphStore(":memory:")
        result = map_github(_GITHUB_RAW, _GITHUB_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        store.append(result)
        rows = store._conn.execute("SELECT COUNT(*) AS n FROM bridge_links").fetchone()
        assert rows["n"] == len(result.bridge_links)
        store.close()

    def test_empty_emission_result_is_a_safe_no_op(self):
        store = GraphStore(":memory:")
        empty = map_github("", _GITHUB_SEED, run_id="run-1", collected_at=_NOW)
        store.append(empty)  # must not raise
        rows = store._conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()
        assert rows["n"] == 0
        store.close()
