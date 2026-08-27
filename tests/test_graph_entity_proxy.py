# tests/test_graph_entity_proxy.py
"""Tests for openosint.graph.entity_proxy — Statement rows -> FtM EntityProxy.

No Python 3.11 / nomenklatura guard needed here: this module only needs
followthemoney (the `graph` extra) — see its module docstring for why it
lives outside the nomenklatura-gated openosint.graph.dedup package.
"""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from followthemoney.statement import Statement  # noqa: E402

from openosint.graph.entity_proxy import build_entity_proxy  # noqa: E402

_NOW_ISO = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc).isoformat()


def _stmt(entity_id: str, prop: str, schema: str, value: str) -> Statement:
    return Statement(
        entity_id=entity_id,
        prop=prop,
        schema=schema,
        value=value,
        dataset="openosint:test",
        first_seen=_NOW_ISO,
        last_seen=_NOW_ISO,
    )


class TestBuildEntityProxy:
    def test_builds_a_proxy_with_the_right_schema_and_id(self):
        stmts = [_stmt("id-1", "name", "Person", "Jane Doe")]
        proxy = build_entity_proxy("id-1", stmts)
        assert proxy.schema.name == "Person"
        assert proxy.id == "id-1"

    def test_all_statement_properties_are_present_on_the_proxy(self):
        stmts = [
            _stmt("id-1", "name", "Person", "Jane Doe"),
            _stmt("id-1", "email", "Person", "jane@example.com"),
        ]
        proxy = build_entity_proxy("id-1", stmts)
        assert "Jane Doe" in proxy.get("name")
        assert "jane@example.com" in proxy.get("email")

    def test_empty_statements_raises(self):
        with pytest.raises(ValueError):
            build_entity_proxy("id-1", [])

    def test_conflicting_schemas_raises(self):
        stmts = [
            _stmt("id-1", "name", "Person", "Jane Doe"),
            _stmt("id-1", "name", "Organization", "Jane Doe LLC"),
        ]
        with pytest.raises(ValueError):
            build_entity_proxy("id-1", stmts)
