# tests/test_graph_store_schema.py
"""Tests for GraphStore's connection setup: WAL, foreign keys, table presence."""

from __future__ import annotations

import sqlite3

from openosint.graph.store import GraphStore


class TestGraphStoreSetup:
    def test_foreign_keys_are_enabled(self):
        store = GraphStore(":memory:")
        (fk,) = store._conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk == 1
        store.close()

    def test_wal_mode_is_enabled_for_a_real_file(self, tmp_path):
        db_path = tmp_path / "graph.sqlite3"
        store = GraphStore(db_path)
        (mode,) = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert mode.lower() == "wal"
        store.close()

    def test_all_five_tables_exist(self):
        store = GraphStore(":memory:")
        rows = store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        names = {r["name"] for r in rows}
        assert {"statements", "provenance", "bridge_links", "resolutions", "erasures"} <= names
        store.close()

    def test_context_manager_closes_connection(self):
        with GraphStore(":memory:") as store:
            store._conn.execute("SELECT 1")
        try:
            store._conn.execute("SELECT 1")
            raise AssertionError("connection should be closed")
        except sqlite3.ProgrammingError:
            pass

    def test_reopening_an_existing_db_file_does_not_error(self, tmp_path):
        db_path = tmp_path / "graph.sqlite3"
        GraphStore(db_path).close()
        GraphStore(db_path).close()  # CREATE TABLE IF NOT EXISTS must not raise the second time
