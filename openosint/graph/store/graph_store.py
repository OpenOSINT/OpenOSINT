# openosint/graph/store/graph_store.py
"""
The append-only SQLite store. All real I/O for the graph package lives here.

Synchronous by design: sqlite3 is stdlib-synchronous, a single local file is
fast enough that there is nothing to gain from an async wrapper at this
layer, and a synchronous class is far simpler to test. A future async caller
(Phase 4's MCP tools) wraps calls in asyncio.to_thread(), exactly the pattern
openosint/tools/search_whois.py already uses for its own blocking WHOIS call.

Five methods matter most:
  append()            — Phase 1 EmissionResult -> statements/provenance/bridge_links.
  append_resolution()  / canonical_for() / resolution_history() — requirement A.
  erase()              — requirement B, the one hard-delete path.
  neighbors()           — depth-N BFS, cycle-guarded, fan-out capped, cross_layer aware.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from followthemoney.statement import Statement
from followthemoney.statement.util import get_prop_type

from openosint.correlation import EntityType
from openosint.graph.bridge import BridgeLink
from openosint.graph.mapping import EmissionResult
from openosint.graph.provenance import ProvenanceRecord
from openosint.graph.store.neighbors import NeighborCandidate, NeighborResult
from openosint.graph.store.resolutions import Resolution
from openosint.graph.store.schema import SCHEMA_SQL
from openosint.graph.store.tombstone import ErasureTombstone, make_tombstone

_MAX_DEPTH_CEILING = 5
_DEFAULT_FANOUT_CAP = 50


class GraphStore:
    """Append-only SQLite store for FtM statements, provenance, bridge links, and resolutions."""

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Append (Phase 1 EmissionResult -> store)
    # ------------------------------------------------------------------

    def append(self, result: EmissionResult) -> None:
        """Append one map_* EmissionResult in a single transaction.

        Statements and bridge_links use INSERT OR IGNORE — content-derived
        ids/UNIQUE constraints mean re-appending identical facts is a safe
        no-op, never an UPDATE. Provenance always inserts a new row: it has
        no natural key, and every call is a genuinely new observation.
        """
        with self._conn:
            for stmt in result.statements:
                self._conn.execute(
                    """INSERT INTO statements
                       (id, entity_id, prop, schema, value, dataset, origin, lang,
                        original_value, first_seen, last_seen, external)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO NOTHING""",
                    (
                        stmt.id,
                        stmt.entity_id,
                        stmt.prop,
                        stmt.schema,
                        stmt.value,
                        stmt.dataset,
                        stmt.origin,
                        stmt.lang,
                        stmt.original_value,
                        stmt.first_seen,
                        stmt.last_seen,
                        int(stmt.external),
                    ),
                )
            for rec in result.provenance:
                self._conn.execute(
                    """INSERT INTO provenance
                       (statement_id, run_id, collection_method, extractor_confidence,
                        collected_at, breach_name)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        rec.statement_id,
                        rec.run_id,
                        rec.collection_method,
                        rec.extractor_confidence,
                        rec.collected_at.isoformat(),
                        rec.breach_name,
                    ),
                )
            for link in result.bridge_links:
                self._conn.execute(
                    """INSERT INTO bridge_links
                       (ftm_entity_id, graph_entity_type, graph_entity_normalized, relation,
                        created_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(ftm_entity_id, graph_entity_type, graph_entity_normalized, relation)
                       DO NOTHING""",
                    (
                        link.ftm_entity_id,
                        link.graph_entity_type.value,
                        link.graph_entity_normalized,
                        link.relation,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    # ------------------------------------------------------------------
    # Queries: by entity, by schema, provenance
    # ------------------------------------------------------------------

    def get_statements_by_entity(self, entity_id: str) -> list[Statement]:
        """All statements about *entity_id*, in insertion order."""
        rows = self._conn.execute(
            "SELECT * FROM statements WHERE entity_id = ? ORDER BY rowid", (entity_id,)
        ).fetchall()
        return [self._row_to_statement(r) for r in rows]

    def get_statements_by_schema(self, schema: str) -> list[Statement]:
        """All statements whose entity is of FtM schema *schema*."""
        rows = self._conn.execute(
            "SELECT * FROM statements WHERE schema = ? ORDER BY entity_id, rowid", (schema,)
        ).fetchall()
        return [self._row_to_statement(r) for r in rows]

    def get_provenance(self, statement_id: str) -> list[ProvenanceRecord]:
        """Every observation of *statement_id*, oldest first — the sidecar's full history."""
        rows = self._conn.execute(
            """SELECT run_id, collection_method, extractor_confidence, collected_at, breach_name
               FROM provenance WHERE statement_id = ? ORDER BY collected_at, id""",
            (statement_id,),
        ).fetchall()
        return [
            ProvenanceRecord(
                statement_id=statement_id,
                run_id=r["run_id"],
                collection_method=r["collection_method"],
                extractor_confidence=r["extractor_confidence"],
                collected_at=datetime.fromisoformat(r["collected_at"]),
                breach_name=r["breach_name"],
            )
            for r in rows
        ]

    @staticmethod
    def _row_to_statement(row: sqlite3.Row) -> Statement:
        return Statement(
            entity_id=row["entity_id"],
            prop=row["prop"],
            schema=row["schema"],
            value=row["value"],
            dataset=row["dataset"],
            origin=row["origin"],
            lang=row["lang"],
            original_value=row["original_value"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            external=bool(row["external"]),
            id=row["id"],
        )

    # ------------------------------------------------------------------
    # Resolutions — requirement A
    # ------------------------------------------------------------------

    def append_resolution(self, resolution: Resolution) -> int:
        """Append one merge-decision row. Returns its new row id."""
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO resolutions
                   (entity_id, canonical_id, judgement, score, decided_by, decided_by_detail,
                    decided_at, revokes_resolution_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resolution.entity_id,
                    resolution.canonical_id,
                    resolution.judgement,
                    resolution.score,
                    resolution.decided_by,
                    resolution.decided_by_detail,
                    resolution.decided_at.isoformat(),
                    resolution.revokes_resolution_id,
                ),
            )
        return int(cur.lastrowid)

    def resolution_history(
        self, *, entity_id: str | None = None, canonical_id: str | None = None
    ) -> list[Resolution]:
        """Full append-only history for one entity_id and/or canonical_id, oldest first.

        This is the "reconstruct the full history of why it was merged" query
        — every row ever appended, including revoked ones. Pass canonical_id
        alone to see everything ever merged into that canonical entity.
        """
        clauses, params = [], []
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if canonical_id is not None:
            clauses.append("canonical_id = ?")
            params.append(canonical_id)
        where = f"WHERE {' OR '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM resolutions {where} ORDER BY decided_at, id", params
        ).fetchall()
        return [self._row_to_resolution(r) for r in rows]

    def has_resolution(self, entity_id: str, canonical_id: str) -> bool:
        """Whether this unordered pair has ANY resolution row, of any judgement.

        Used by Phase 3's crossref pass to avoid re-suggesting a pair that a
        human already decided on (positive or negative) or that a prior
        crossref run already suggested (unsure) — nomenklatura's own xref()
        does the equivalent check (Resolver.check_candidate) before scoring.
        """
        row = self._conn.execute(
            "SELECT 1 FROM resolutions WHERE (entity_id = ? AND canonical_id = ?) "
            "OR (entity_id = ? AND canonical_id = ?) LIMIT 1",
            (entity_id, canonical_id, canonical_id, entity_id),
        ).fetchone()
        return row is not None

    def _active_pair_edges(self) -> dict[str, set[str]]:
        """Adjacency map of currently-active (latest-judgement='positive') resolution pairs.

        A resolution row is an UNDIRECTED edge between its entity_id and
        canonical_id. Multiple rows can exist for the same unordered pair
        over time (a merge, then a revocation, maybe a re-merge); only the
        temporally-latest row for each exact pair determines whether that
        edge is currently part of the live graph. This is a full-table scan
        rebuilt on every call — simple and correct at the scale a same_as
        review queue is expected to reach. If resolutions ever grows large
        enough for this to matter, an incremental Union-Find replaces it;
        nothing about the public API below would need to change.
        """
        rows = self._conn.execute(
            "SELECT entity_id, canonical_id, judgement, decided_at, id FROM resolutions "
            "ORDER BY decided_at, id"
        ).fetchall()
        latest_for_pair: dict[frozenset[str], str] = {}
        for r in rows:
            pair = frozenset((r["entity_id"], r["canonical_id"]))
            latest_for_pair[pair] = r["judgement"]  # later rows overwrite earlier in this dict
        adjacency: dict[str, set[str]] = {}
        for pair, judgement in latest_for_pair.items():
            if judgement != "positive":
                continue
            a, b = tuple(pair)
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
        return adjacency

    def connected_component(self, entity_id: str) -> set[str]:
        """The full set of entities transitively linked to *entity_id* via active positive edges.

        Includes *entity_id* itself. A<->B and B<->C (two separate rows, no
        direct A<->C row) still puts A, B, and C in one component — this is
        the fix for treating resolutions as isolated pairs instead of a graph.
        """
        adjacency = self._active_pair_edges()
        if entity_id not in adjacency:
            return {entity_id}
        visited = {entity_id}
        queue = [entity_id]
        while queue:
            node = queue.pop()
            for neighbor in adjacency.get(node, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    def canonical_for(self, entity_id: str) -> str:
        """The CURRENT effective canonical id for *entity_id* — always computed, never stored.

        Computed as max() of entity_id's full connected component over
        active positive resolutions (nomenklatura's Resolver.get_canonical()
        does the same thing: max() of the connected set). Revoking any edge
        in the component can shrink or split it; the next call simply
        recomputes from whatever edges are active now — there is nothing to
        "undo" beyond appending the revocation row itself.
        """
        return max(self.connected_component(entity_id))

    def members_of_canonical(self, canonical_id: str) -> list[str]:
        """Every entity_id in *canonical_id*'s cluster, sorted — but only if it IS the cluster's canonical.

        Returns [] if *canonical_id* is not currently the max() of its own
        component (i.e. it is not actually canonical right now — some other
        member outranks it, or the component has changed). Call
        canonical_for(x) first if you have an arbitrary member and want its
        cluster regardless of which id is canonical.
        """
        component = self.connected_component(canonical_id)
        if max(component) != canonical_id:
            return []
        return sorted(component)

    @staticmethod
    def _row_to_resolution(row: sqlite3.Row) -> Resolution:
        return Resolution(
            entity_id=row["entity_id"],
            canonical_id=row["canonical_id"],
            judgement=row["judgement"],
            decided_by=row["decided_by"],
            decided_at=datetime.fromisoformat(row["decided_at"]),
            score=row["score"],
            decided_by_detail=row["decided_by_detail"],
            revokes_resolution_id=row["revokes_resolution_id"],
            id=row["id"],
        )

    # ------------------------------------------------------------------
    # Erasure — requirement B, the one documented exception
    # ------------------------------------------------------------------

    def erase(self, entity_id: str, *, request_id: str) -> ErasureTombstone:
        """Hard-delete every trace of *entity_id* and append one tombstone.

        SLOW. This is deliberately not a hot-path operation: it enables
        SQLite's secure_delete (pages get overwritten with zeros as they are
        freed, not left as recoverable garbage), forces a full WAL checkpoint
        with TRUNCATE (flushes and discards WAL history that could otherwise
        retain the erased bytes), and runs VACUUM (rebuilds the ENTIRE
        database file, copying only live rows). VACUUM alone is O(database
        size), not O(erased rows) — call this from a background job or an
        explicit admin action, never inline in a request path.

        Scope: erases exactly the one entity_id given — both its own
        statements (entity_id = X) and any OTHER entity's statement that
        references X as a value (e.g. someone else's UserAccount.owner = X),
        since a surviving reference to X elsewhere is exactly the kind of
        residual this method exists to remove. It does NOT discover and
        cascade-erase other, differently-keyed entities that happen to
        relate to the same real-world subject (e.g. their separate Person vs
        UserAccount vs breach-derived LegalEntity ids) — identifying every
        entity_id belonging to one subject is the caller's job (a future
        Phase 4 erasure-request tool), not something this method infers.

        CORRECTION: earlier versions of this method, and the tombstone it
        produced, kept subject_entity_id. entity_id_for() is a deterministic,
        unsalted hash of a structured identifier — a surviving copy of it
        ANYWHERE (including the tombstone) lets anyone holding a candidate
        identifier recompute the same hash and confirm whether that subject
        was in the store. That confirmation is itself personal data. Nothing
        derived from *entity_id* is written anywhere by this method now,
        including into the tombstone it returns.
        """
        original_secure_delete = self._conn.execute("PRAGMA secure_delete").fetchone()[0]
        self._conn.execute("PRAGMA secure_delete = ON")
        try:
            with self._conn:
                stmt_ids = [
                    r["id"]
                    for r in self._conn.execute(
                        "SELECT id FROM statements WHERE entity_id = ? OR value = ?",
                        (entity_id, entity_id),
                    ).fetchall()
                ]

                provenance_count = 0
                for sid in stmt_ids:
                    cur = self._conn.execute(
                        "DELETE FROM provenance WHERE statement_id = ?", (sid,)
                    )
                    provenance_count += cur.rowcount

                # entity_id's own statements AND any other entity's statement that
                # references entity_id as a value (fix 1: residual-reference removal).
                statement_count = self._conn.execute(
                    "DELETE FROM statements WHERE entity_id = ? OR value = ?",
                    (entity_id, entity_id),
                ).rowcount

                bridge_count = self._conn.execute(
                    "DELETE FROM bridge_links WHERE ftm_entity_id = ?", (entity_id,)
                ).rowcount

                resolution_count = self._conn.execute(
                    "DELETE FROM resolutions WHERE entity_id = ? OR canonical_id = ?",
                    (entity_id, entity_id),
                ).rowcount

                tombstone = make_tombstone(
                    request_id=request_id,
                    requested_at=datetime.now(timezone.utc),
                    erased_statement_count=statement_count,
                    erased_provenance_count=provenance_count,
                    erased_bridge_count=bridge_count,
                    erased_resolution_count=resolution_count,
                )
                self._conn.execute(
                    """INSERT INTO erasures
                       (request_id, requested_at, erased_statement_count,
                        erased_provenance_count, erased_bridge_count, erased_resolution_count)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        tombstone.request_id,
                        tombstone.requested_at.isoformat(),
                        tombstone.erased_statement_count,
                        tombstone.erased_provenance_count,
                        tombstone.erased_bridge_count,
                        tombstone.erased_resolution_count,
                    ),
                )
            # The delete transaction above must be committed (the `with` block
            # exited) before VACUUM: SQLite refuses VACUUM while a transaction
            # is open. wal_checkpoint(TRUNCATE) flushes all WAL frames into the
            # main file AND discards the WAL file's own on-disk history: a
            # plain checkpoint leaves old frames sitting in the WAL file even
            # after they're superseded.
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
        finally:
            self._conn.execute(f"PRAGMA secure_delete = {int(original_secure_delete)}")
        return tombstone

    # ------------------------------------------------------------------
    # Neighbors — depth-N BFS, cycle-guarded, fan-out capped, cross_layer aware
    # ------------------------------------------------------------------

    def neighbors(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        cross_layer: bool = False,
        fanout_cap: int = _DEFAULT_FANOUT_CAP,
    ) -> NeighborResult:
        """BFS out to *depth* hops from *entity_id*.

        depth is hard-capped at _MAX_DEPTH_CEILING regardless of what the
        caller asks for. The visited set IS the cycle guard — a node already
        seen is never re-enqueued, so a cycle (A -> B -> A) simply terminates
        instead of looping. fanout_cap bounds how many neighbors a single
        high-degree node contributes per hop; exceeding it sets
        NeighborResult.truncated = True rather than raising.
        """
        depth = max(0, min(depth, _MAX_DEPTH_CEILING))
        visited: set[str] = {entity_id}
        frontier: set[str] = {entity_id}
        edges: list[tuple[str, str, str]] = []
        truncated = False

        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in sorted(frontier):
                candidates = self._entity_typed_out(node) + self._entity_typed_in(node)
                if len(candidates) > fanout_cap:
                    truncated = True
                for cand in candidates[:fanout_cap]:
                    if cand.direction == "outgoing":
                        edges.append((node, cand.entity_id, cand.prop))
                    else:
                        edges.append((cand.entity_id, node, cand.prop))
                    if cand.entity_id not in visited:
                        visited.add(cand.entity_id)
                        next_frontier.add(cand.entity_id)
            frontier = next_frontier
            if not frontier:
                break

        bridge_links: tuple[BridgeLink, ...] = ()
        if cross_layer:
            bridge_links = self._bridge_links_for(visited)

        return NeighborResult(
            entities=tuple(sorted(visited - {entity_id})),
            edges=tuple(edges),
            bridge_links=bridge_links,
            truncated=truncated,
        )

    def _entity_typed_out(self, entity_id: str) -> list[NeighborCandidate]:
        rows = self._conn.execute(
            "SELECT DISTINCT prop, schema, value FROM statements WHERE entity_id = ? ORDER BY value",
            (entity_id,),
        ).fetchall()
        return [
            NeighborCandidate(entity_id=r["value"], prop=r["prop"], direction="outgoing")
            for r in rows
            if get_prop_type(r["schema"], r["prop"]) == "entity"
        ]

    def _entity_typed_in(self, entity_id: str) -> list[NeighborCandidate]:
        rows = self._conn.execute(
            """SELECT DISTINCT entity_id AS src, prop, schema FROM statements
               WHERE value = ? ORDER BY src""",
            (entity_id,),
        ).fetchall()
        return [
            NeighborCandidate(entity_id=r["src"], prop=r["prop"], direction="incoming")
            for r in rows
            if get_prop_type(r["schema"], r["prop"]) == "entity"
        ]

    def _bridge_links_for(self, entity_ids: Iterable[str]) -> tuple[BridgeLink, ...]:
        ids = list(entity_ids)
        if not ids:
            return ()
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"""SELECT ftm_entity_id, graph_entity_type, graph_entity_normalized, relation
                FROM bridge_links WHERE ftm_entity_id IN ({placeholders})
                ORDER BY ftm_entity_id""",
            ids,
        ).fetchall()
        return tuple(
            BridgeLink(
                ftm_entity_id=r["ftm_entity_id"],
                graph_entity_type=EntityType(r["graph_entity_type"]),
                graph_entity_normalized=r["graph_entity_normalized"],
                relation=r["relation"],
            )
            for r in rows
        )
