# The FtM entity graph

`openosint.graph` is an **additive** module that converts scan results into
[FollowTheMoney](https://followthemoney.tech/) (FtM) entities with
statement-level provenance, an append-only store, non-destructive same_as
deduplication, and a human review queue. It sits alongside the existing
Entity Correlation Graph (`openosint/correlation.py`, `extractors.py`,
`pivot.py`) without modifying it — nothing about the existing REPL, CLI
subcommands, or agent tool loop changes unless you opt into the `graph` /
`graph-dedup` extras and start writing to a `GraphStore`.

## Why FtM, not a bespoke schema

FollowTheMoney is a standard entity/relationship model used across the OSINT
and anti-corruption tooling ecosystem (OpenSanctions, Aleph, and others). It
ships:

- **A fixed, versioned schema** for `Person`, `LegalEntity`, `Organization`,
  `UserAccount`, `Membership`, and dozens more — instead of inventing and
  maintaining our own.
- **A content-derived statement model.** Every fact is a `Statement`
  (`entity_id`, `prop`, `schema`, `value`, `dataset`, ...) whose `id` is a
  hash of its own content — re-observing the same fact twice is a safe
  no-op, never a duplicate row or a silent overwrite.
- **An export format** (`.ftm` / newline-delimited entity JSON) already
  understood by the rest of that ecosystem, so a graph built here can be fed
  into other FtM-aware tools without a bespoke converter.
- **nomenklatura**, the reference same_as scoring library for this exact
  model, reused rather than reimplemented (see [Cross-reference and the
  review workflow](#cross-reference-and-the-review-workflow) below).

## Identity-only scope, and the bridge to the infra graph

Only **identity-bearing** findings become FtM entities: `Person`,
`LegalEntity`, `Organization`, `UserAccount`, and their `Membership` edges.
Infrastructure — domains, IPs, hashes, ASNs, bare URLs — **never** becomes an
FtM node. It either becomes a property on an identity entity it's evidence
for (a WHOIS-derived `LegalEntity.email`, say), or it stays exactly where it
already lived: the existing `openosint.correlation.EntityGraph`, untouched.

The two graphs are connected by a `BridgeLink` (`openosint/graph/bridge.py`):
a lightweight record of which infra-graph node (`graph_entity_type` +
`graph_entity_normalized`) an FtM entity was `derived_from`. `GraphStore.
neighbors(..., cross_layer=True)` follows these bridge links outward from an
FtM subgraph, surfacing the raw infra nodes that fed it — without ever
promoting them into FtM entities themselves.

Entity ids (`openosint/graph/identity.py`) are deterministic and **only ever
keyed on structured identifiers** — an email address, a `(service,
username)` pair, a domain — **never on a free-text name**. Two different
"John Smith"s discovered by two different tools get two different entity
ids. If names were used as keys, they'd silently pre-merge before any human
or scored review ever ran, which is exactly the auto-merge this whole module
is designed to prevent.

## Three scales, never mixed

Three different numbers can look superficially similar (all floats,
roughly `0`–`1`) but mean entirely different things. Mixing them — averaging,
comparing, or substituting one for another — is a documented failure mode
this codebase actively guards against:

| Scale | Where it lives | What it means |
|---|---|---|
| `extractor_confidence` | `ProvenanceRecord.extractor_confidence` (`provenance.py`) | An **ordinal heuristic** hand-tuned in `openosint/extractors.py` to help `pivot.py`'s BFS decide what's worth chasing. `0.85` means "an extractors.py author judged this fairly trustworthy" — not a probability of anything. |
| `resolutions.score` | `Resolution.score` (`store/resolutions.py`) | A **rule-based composite score** from whichever `ScoringAlgorithm` produced it — by default, nomenklatura's LogicV2 (fixed-weight name/identifier/address comparators). `0.82` means "LogicV2's weighted rules judged this pair fairly similar" — **not** "82% likely to be the same entity." It is not a calibrated probability from a trained classifier. |
| `DEFAULT_CROSSREF_THRESHOLD` | `openosint/graph/dedup/scoring.py` | The line above which a scored pair is worth surfacing to a human at all (currently `0.5`). A judgment call about analyst review-queue load, not a property of the algorithm — lower it if real matches are being missed, raise it if the queue is unmanageably noisy. |

`Resolution.decided_by_detail` records which algorithm (name + installed
package version) produced a given score, so a score written today stays
interpretable after a nomenklatura upgrade or an algorithm swap — see
`dedup.scoring.algorithm_identity()`.

## Cross-reference and the review workflow

Non-destructive dedup, end to end:

```
run_crossref()  →  judgement='unsure', decided_by='auto'
       │
       ▼
graph_review_candidates(action="list")   ← a human looks at score + explanation
       │
       ▼
graph_review_candidates(action="decide", decision="accept" | "reject")
       │
       ├── accept → new row, judgement='positive', decided_by='human'
       │            → the pair now clusters together (canonical_for())
       │
       └── reject → new row, judgement='negative', decided_by='human'
                    → GraphStore.has_resolution() permanently skips this
                      pair on every future crossref run
```

**Nothing in this codebase ever writes `judgement='positive'` except a
human decision.** `run_crossref()` (`openosint/graph/dedup/crossref.py`) only
ever produces `judgement='unsure'` rows — this is enforced at the code level,
not just by convention (see the package's own docstring and
`TestNeverAutoMerge` in `tests/test_graph_dedup_crossref.py`). A `resolutions`
row is an undirected edge between two entity ids; "which entity is
canonical" is always **computed** at query time as `max()` of the connected
component of currently-active positive edges (`GraphStore.canonical_for()`)
— never a stored, mutable fact. Undoing a merge means appending a *new* row
for the same pair with a non-positive judgement, not deleting or rewriting
anything.

A rejected pair is genuinely permanent: `has_resolution()` treats a pair as
"already decided" the moment *any* resolution row exists for it (positive,
negative, or a prior `unsure` suggestion), so `run_crossref()` never
re-scores it, and `graph_review_candidates(action="list")` never shows it
again either.

## The erasure guarantee — and its cost

`GraphStore.erase(entity_id, request_id=...)` is the **one** hard-delete
path in an otherwise append-only store (requirement B). It removes:

- every statement about `entity_id`, *and* every other entity's statement
  that references `entity_id` as a **value** (e.g. someone else's
  `UserAccount.owner`) — a surviving reference elsewhere is exactly the kind
  of residual this method exists to remove;
- every provenance record for those statements;
- every bridge link and resolution row touching `entity_id`.

It leaves exactly one tombstone row behind — but **never the erased
`entity_id` itself**. Entity ids are a deterministic, unsalted hash of a
structured identifier; a surviving copy anywhere (including in the
tombstone) would let anyone holding a candidate identifier recompute the
same hash and confirm whether that subject was ever in the store. That
confirmation is itself personal data under GDPR, so the tombstone stores
only the erasure event and per-table counts.

**Cost:** `erase()` is deliberately not a hot-path operation. It enables
SQLite's `secure_delete` (freed pages get overwritten with zeros, not left
as recoverable garbage), forces a full WAL checkpoint with `TRUNCATE`, and
runs `VACUUM` — which rebuilds the **entire** database file, copying only
live rows. `VACUUM` is O(database size), not O(erased rows). Call it from a
background job or an explicit admin action, never inline in a request path.

Erasure also does **not** cascade to other, differently-keyed entities that
happen to represent the same real-world subject (their separate `Person`
vs. `UserAccount` vs. breach-derived `LegalEntity` ids, say) — identifying
every entity id belonging to one subject is the caller's job.

## The `graph-dedup` extra and the Python 3.11 requirement

| Extra | What it needs | What it gates | Python floor |
|---|---|---|---|
| `graph` | `followthemoney` | mapping, provenance, the SQLite store, `graph_export`, `graph_neighbors` | 3.10+ |
| `graph-dedup` | `nomenklatura` | `run_crossref()`, `graph_review_candidates` scoring output | **3.11+** |

The Python 3.11 floor is **nomenklatura's own requirement**, not a choice
made by this project — `openosint`'s own `requires-python` stays `>=3.10`.
Importing `openosint.graph.dedup` on 3.10 raises a clear `ImportError`
before nomenklatura is even touched (`openosint/graph/dedup_guard.py`); the
three MCP tools registered in `mcp_server.py` degrade to a readable message
under the same conditions rather than crashing the server. `graph_export`
and `graph_neighbors` work on 3.10 with just the `graph` extra installed;
`graph_review_candidates` also works everywhere — it only ever reads
already-computed resolution rows, never imports nomenklatura itself, and
simply reports an empty review queue if `run_crossref()` has never run.

```bash
pip install 'openosint[graph]'         # mapping, store, export, neighbors — 3.10+
pip install 'openosint[graph-dedup]'   # + same_as scoring & review — needs Python 3.11+
```

## Worked end-to-end example

This builds a small graph from two GitHub profiles that share a name and
email, cross-references them, lists the resulting review candidate, and
accepts it. Requires Python 3.11+ and `pip install 'openosint[graph-dedup]'`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install 'openosint[graph-dedup]'
```

```python
# graph_demo.py
from datetime import datetime, timezone

from openosint.correlation import EntityType, make_entity
from openosint.graph.dedup import run_crossref
from openosint.graph.mapping import map_github
from openosint.graph.review import decide_review_candidate, list_review_candidates
from openosint.graph.store import GraphStore

NOW = datetime.now(timezone.utc)


def profile(login, name, email):
    return (
        f"[GitHub] Login: {login}\n"
        f"[GitHub] Name: {name}\n"
        f"[GitHub] Email (profile): {email}\n"
    )


store = GraphStore("graph_demo.db")  # created on first use; ~/.openosint/graph.db
                                      # is the MCP tools' own default path

# Two accounts, same person, discovered under different usernames.
store.append(map_github(
    profile("janedoe1", "Jane Doe", "jane@example.com"),
    make_entity(EntityType.USERNAME, "janedoe1", 1.0),
    run_id="scan-1", collected_at=NOW,
))
store.append(map_github(
    profile("jdoe_dev", "Jane Doe", "jane@example.com"),
    make_entity(EntityType.USERNAME, "jdoe_dev", 1.0),
    run_id="scan-2", collected_at=NOW,
))

# Score every candidate pair; suggest matches as judgement='unsure'.
suggested = run_crossref(store, run_id="crossref-1", decided_at=NOW, min_threshold=0.3)
print(f"{len(suggested)} candidate(s) suggested")

# A human reviews the queue.
for c in list_review_candidates(store):
    print(f"score={c.score:.2f}  {c.entity_a_properties}  vs  {c.entity_b_properties}")
    print(f"why: {c.explanation_text}")

    # Accept it: writes judgement='positive', decided_by='human'.
    decide_review_candidate(
        store,
        entity_id=c.entity_id_a,
        canonical_id=c.entity_id_b,
        judgement="positive",
        decided_at=NOW,
        reviewer_id="analyst@example.com",
    )

# The two Person entities now resolve to one shared canonical id.
print("clustered:", store.canonical_for(c.entity_id_a) == store.canonical_for(c.entity_id_b))
store.close()
```

```bash
python3 graph_demo.py
```

```
1 candidate(s) suggested
score=1.00  {'name': ['Jane Doe']}  vs  {'name': ['Jane Doe']}
why: name_match=1.00 ('Jane Doe' vs 'Jane Doe'); dob_day_disjoint=0.00; dob_year_disjoint=0.00; vessel_imo_mmsi_match=0.00
clustered: True
```

The same store is what the three MCP tools operate on — point
`OPENOSINT_GRAPH_DB` at `graph_demo.db` (or copy it to `~/.openosint/graph.db`,
the default) and call `graph_review_candidates` / `graph_export` /
`graph_neighbors` from any MCP client (e.g. Claude Desktop) to browse the
same data interactively instead of through a script.
