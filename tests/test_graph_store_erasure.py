# tests/test_graph_store_erasure.py
"""Tests for GraphStore.erase() — requirement B, the one exception to append-only.

Three layers of proof, weakest to strongest:
  1. SQL queries against the live connection (logical deletion only).
  2. entity_id_for() recomputed from the erased VALUES, checked against every
     table/column — proves no derived id (a confirmation oracle) survives.
  3. Raw bytes of the .db and -wal files opened in binary mode — the only
     test that proves anything about physical, not just logical, erasure.
"""

from __future__ import annotations

from datetime import datetime, timezone

from openosint.correlation import EntityType, make_entity
from openosint.graph.identity import entity_id_for
from openosint.graph.mapping import map_breach, map_github
from openosint.graph.store import GraphStore
from openosint.graph.store.resolutions import make_resolution

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_GITHUB_SEED = make_entity(EntityType.USERNAME, "octocat", 1.0)
_GITHUB_RAW = "[GitHub] Login: octocat\n[GitHub] Name: The Octocat\n"
_BREACH_SEED = make_entity(EntityType.EMAIL, "jane@example.com", 1.0)
_BREACH_RAW = (
    "Found in 2 breach(es) for 'jane@example.com':\n\n"
    "[+] Adobe (2013-10-04) — leaked: Emails\n"
    "[+] LinkedIn (2012-05-05) — leaked: Emails\n"
)


def _all_table_names(store):
    rows = store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return [r["name"] for r in rows]


def _scan_all_rows_for(store, needle: str) -> list[str]:
    """Return "table.column" for every cell across every table that equals *needle*."""
    hits = []
    for table in _all_table_names(store):
        rows = store._conn.execute(f"SELECT * FROM {table}").fetchall()
        for row in rows:
            for key in row.keys():
                if row[key] == needle:
                    hits.append(f"{table}.{key}")
    return hits


class TestErasureCascade:
    def test_erasing_a_useraccount_removes_its_statements_provenance_and_bridge(self):
        store = GraphStore(":memory:")
        result = map_github(_GITHUB_RAW, _GITHUB_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        account_id = entity_id_for("UserAccount", "github", "octocat")

        tombstone = store.erase(account_id, request_id="req-1")

        assert tombstone.erased_statement_count > 0
        assert tombstone.erased_bridge_count == 1
        assert store.get_statements_by_entity(account_id) == []
        row = store._conn.execute(
            "SELECT COUNT(*) AS n FROM bridge_links WHERE ftm_entity_id = ?", (account_id,)
        ).fetchone()
        assert row["n"] == 0
        store.close()

    def test_erasure_cascades_to_all_provenance_of_the_erased_entitys_statements(self):
        store = GraphStore(":memory:")
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        owner_id = result.statements[0].entity_id
        stmt_id = result.statements[0].id

        tombstone = store.erase(owner_id, request_id="req-2")

        assert tombstone.erased_provenance_count == 2  # both breach observations
        assert store.get_provenance(stmt_id) == []
        store.close()

    def test_erasure_cascades_to_resolutions_on_either_side(self):
        store = GraphStore(":memory:")
        store.append_resolution(
            make_resolution(
                entity_id="victim",
                canonical_id="hub",
                judgement="positive",
                decided_by="auto",
                decided_at=_NOW,
                score=0.9,
            )
        )
        tombstone = store.erase("victim", request_id="req-3")
        assert tombstone.erased_resolution_count == 1
        assert store.resolution_history(entity_id="victim") == []
        store.close()

    def test_one_erasure_request_id_produces_exactly_one_tombstone(self):
        store = GraphStore(":memory:")
        store.erase("entity-x", request_id="req-4")
        rows = store._conn.execute("SELECT COUNT(*) AS n FROM erasures").fetchone()
        assert rows["n"] == 1
        store.close()

    def test_erasing_one_entity_also_removes_other_entities_dangling_references_to_it(self):
        """Fix 1: a surviving VALUE reference elsewhere is a residual, not just entity_id=X rows."""
        store = GraphStore(":memory:")
        result = map_github(_GITHUB_RAW, _GITHUB_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        person_id = entity_id_for("Person", "github", "octocat")
        account_id = entity_id_for("UserAccount", "github", "octocat")

        store.erase(person_id, request_id="req-erase-person")

        # UserAccount.owner = person_id must be gone even though the account itself was not erased
        remaining = store.get_statements_by_entity(account_id)
        assert not any(s.prop == "owner" for s in remaining)
        assert any(s.prop == "username" for s in remaining)  # the account's own data survives
        store.close()


class TestErasureTombstoneCarriesNoDerivedId:
    """Fix 1: the tombstone (and every other table) must never hold entity_id_for()'s output."""

    def test_tombstone_has_no_entity_id_column_at_all(self):
        store = GraphStore(":memory:")
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        owner_id = result.statements[0].entity_id

        store.erase(owner_id, request_id="req-5")

        row = store._conn.execute(
            "SELECT * FROM erasures WHERE request_id = ?", ("req-5",)
        ).fetchone()
        assert set(row.keys()) == {
            "request_id",
            "requested_at",
            "erased_statement_count",
            "erased_provenance_count",
            "erased_bridge_count",
            "erased_resolution_count",
        }
        store.close()


class TestErasureUnreconstructable:
    """The required end-to-end proof: recompute entity_id_for() from every erased value
    and confirm that id appears in NO table or column anywhere in the store."""

    def test_recomputed_entity_id_for_erased_email_appears_nowhere(self):
        store = GraphStore(":memory:")
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        owner_id = result.statements[0].entity_id

        # An attacker who suspects "jane@example.com" was in the store recomputes
        # the exact same id this system would have used.
        recomputed = entity_id_for("LegalEntity", "email-owner", _BREACH_SEED.normalized)
        assert recomputed == owner_id  # confirms this IS the confirmation-oracle scenario

        store.erase(owner_id, request_id="req-6")

        assert _scan_all_rows_for(store, recomputed) == []
        store.close()

    def test_recomputed_entity_id_for_erased_github_identity_appears_nowhere(self):
        store = GraphStore(":memory:")
        result = map_github(_GITHUB_RAW, _GITHUB_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        person_id = entity_id_for("Person", "github", "octocat")
        account_id = entity_id_for("UserAccount", "github", "octocat")

        store.erase(person_id, request_id="req-7")
        store.erase(account_id, request_id="req-8")

        assert _scan_all_rows_for(store, person_id) == []
        assert _scan_all_rows_for(store, account_id) == []
        store.close()

    def test_erased_email_and_breach_names_do_not_appear_as_literal_text_anywhere(self):
        store = GraphStore(":memory:")
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        owner_id = result.statements[0].entity_id

        store.erase(owner_id, request_id="req-9")

        for needle in (_BREACH_SEED.value, "Adobe", "LinkedIn"):
            assert _scan_all_rows_for(store, needle) == [], f"{needle!r} survived erasure"
        store.close()


class TestErasurePhysicalBytes:
    """Fix 2: SQL-level proof is not enough — DELETE leaves bytes in freed pages, the WAL,
    and the -shm file. Only reading the raw file bytes proves anything."""

    def test_erased_email_and_breach_names_are_absent_from_the_raw_db_file_bytes(self, tmp_path):
        db_path = tmp_path / "graph.sqlite3"
        store = GraphStore(db_path)
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        owner_id = result.statements[0].entity_id

        store.erase(owner_id, request_id="req-bytes-1")
        store.close()

        raw = db_path.read_bytes()
        for needle in (_BREACH_SEED.value.encode(), b"Adobe", b"LinkedIn"):
            assert needle not in raw, f"{needle!r} still present in raw .db bytes"

    def test_wal_file_does_not_retain_erased_bytes_either(self, tmp_path):
        db_path = tmp_path / "graph.sqlite3"
        store = GraphStore(db_path)
        result = map_breach(_BREACH_RAW, _BREACH_SEED, run_id="run-1", collected_at=_NOW)
        store.append(result)
        owner_id = result.statements[0].entity_id

        store.erase(owner_id, request_id="req-bytes-2")
        store.close()

        wal_path = db_path.with_name(db_path.name + "-wal")
        if wal_path.exists():
            wal_bytes = wal_path.read_bytes()
            for needle in (_BREACH_SEED.value.encode(), b"Adobe", b"LinkedIn"):
                assert needle not in wal_bytes, f"{needle!r} still present in -wal bytes"

    def test_secure_delete_is_restored_to_its_prior_value_after_erase(self, tmp_path):
        """erase() must not leave the connection permanently in secure_delete mode."""
        db_path = tmp_path / "graph.sqlite3"
        store = GraphStore(db_path)
        before = store._conn.execute("PRAGMA secure_delete").fetchone()[0]
        store.erase("entity-x", request_id="req-bytes-3")
        after = store._conn.execute("PRAGMA secure_delete").fetchone()[0]
        assert after == before
        store.close()
