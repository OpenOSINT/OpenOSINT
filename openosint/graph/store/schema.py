# openosint/graph/store/schema.py
"""
SQLite DDL for the append-only graph store.

Five tables, three different lifecycles:

statements / provenance / bridge_links — pure append-only. Rows are never
UPDATEd. `statements` is keyed by FtM's own content-derived Statement.id, so
re-observing an identical fact is a no-op INSERT ... ON CONFLICT DO NOTHING;
`provenance` has no such natural key — every observation gets its own
surrogate-keyed row, which is exactly how the same statement can carry N
independent ProvenanceRecords (see openosint/graph/provenance.py).

resolutions — append-only. Each row proposes a link between the two entities
in entity_id/canonical_id; despite the column name, canonical_id is NOT
authoritative about which side is "the" canonical one — that is always
COMPUTED at query time as the connected component's max() id (see
GraphStore.canonical_for / requirement A's cluster-semantics correction), the
same way nomenklatura's Resolver.get_canonical() works. A row is treated as
an UNDIRECTED edge between its two entity ids: for a given unordered pair,
only the temporally-latest row for that exact pair is "active"; the edge only
exists in the live graph if that latest judgement is 'positive'. Undoing a
merge means inserting a NEW row for the SAME PAIR with a non-positive
judgement — not a self-referencing row — so it actually flips that pair's
latest-row lookup. revokes_resolution_id is audit metadata (which row this
one intends to revoke), not itself load-bearing for the computation.
Modeled on nomenklatura's Edge/Judgement vocabulary (source/target/judgement/
score/user) without importing nomenklatura itself yet — the graph-dedup extra
(Phase 3) is where that dependency actually gets used, gated to Python >=3.11.

erasures — the one documented exception (requirement B). A GDPR-style
erasure is the only hard DELETE this store ever performs, and it always
leaves exactly one tombstone row behind recording that it happened, when,
and under what request id. CORRECTION: earlier drafts of this table also
stored subject_entity_id and a free-text reason — both removed. entity_id_for()
is a deterministic, unsalted hash: a surviving entity_id anywhere (including
in the tombstone) lets anyone who already holds a candidate identifier
recompute the hash and confirm whether that subject was ever in the store.
That confirmation is itself personal data under GDPR. The tombstone now keeps
only the erasure event and per-table counts — nothing that can be recomputed
back into "was X here".

No migration path is provided for the erasures/resolutions column changes
below — this module has not shipped in any release, so there is no on-disk
data to migrate.
"""

from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS statements (
    id              TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    prop            TEXT NOT NULL,
    schema          TEXT NOT NULL,
    value           TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    origin          TEXT,
    lang            TEXT,
    original_value  TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    external        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_statements_entity_id ON statements(entity_id);
CREATE INDEX IF NOT EXISTS idx_statements_prop ON statements(prop);
CREATE INDEX IF NOT EXISTS idx_statements_dataset ON statements(dataset);
CREATE INDEX IF NOT EXISTS idx_statements_value ON statements(value);
CREATE INDEX IF NOT EXISTS idx_statements_schema ON statements(schema);

CREATE TABLE IF NOT EXISTS provenance (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id         TEXT NOT NULL REFERENCES statements(id),
    run_id               TEXT NOT NULL,
    collection_method    TEXT NOT NULL,
    extractor_confidence REAL NOT NULL,
    collected_at         TEXT NOT NULL,
    breach_name          TEXT
);
CREATE INDEX IF NOT EXISTS idx_provenance_statement_id ON provenance(statement_id);
CREATE INDEX IF NOT EXISTS idx_provenance_run_id ON provenance(run_id);

CREATE TABLE IF NOT EXISTS bridge_links (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ftm_entity_id           TEXT NOT NULL,
    graph_entity_type       TEXT NOT NULL,
    graph_entity_normalized TEXT NOT NULL,
    relation                TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    UNIQUE(ftm_entity_id, graph_entity_type, graph_entity_normalized, relation)
);
CREATE INDEX IF NOT EXISTS idx_bridge_links_ftm_entity_id ON bridge_links(ftm_entity_id);

CREATE TABLE IF NOT EXISTS resolutions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id              TEXT NOT NULL,
    canonical_id           TEXT NOT NULL,
    judgement              TEXT NOT NULL
                                CHECK (judgement IN ('positive', 'negative', 'unsure', 'no_judgement')),
    score                  REAL,
    decided_by              TEXT NOT NULL CHECK (decided_by IN ('human', 'auto')),
    decided_by_detail      TEXT,
    decided_at             TEXT NOT NULL,
    revokes_resolution_id  INTEGER REFERENCES resolutions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_resolutions_entity_id ON resolutions(entity_id);
CREATE INDEX IF NOT EXISTS idx_resolutions_canonical_id ON resolutions(canonical_id);

CREATE TABLE IF NOT EXISTS erasures (
    request_id                TEXT PRIMARY KEY,
    requested_at               TEXT NOT NULL,
    erased_statement_count    INTEGER NOT NULL,
    erased_provenance_count   INTEGER NOT NULL,
    erased_bridge_count       INTEGER NOT NULL,
    erased_resolution_count   INTEGER NOT NULL
);
"""
