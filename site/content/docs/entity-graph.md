---
title: "Entity graph"
label: "Entity graph"
seo_title: "OpenOSINT entity graph: chat graph and optional graph store"
description: "Two graph features: the chat's in-browser graph tab, and an optional FollowTheMoney store with provenance, a review queue and MCP tools. What each does."
group: Reference
order: 9
---
OpenOSINT has two separate graph features. Do not confuse them.

## The Graph tab in the web UI

The Graph view in the [web UI](/docs/web-ui/) draws the entities (domains, profiles, emails) found during the current chat. It is built in your browser from the tool results and is not saved anywhere.

## The optional graph store

A second, additive module keeps a durable graph on your disk, modelled with [FollowTheMoney](https://followthemoney.tech/):

- statement-level provenance for every fact;
- an append-only store;
- non-destructive same-entity suggestions and a human review queue. Nothing is merged automatically.

It works in a plain `uvx openosint web` install, with no compiler and no extra:

| Surface | What it gives you |
|---|---|
| `/graph` page and `/api/graph/*` routes | Browse the store in the local web UI |
| `graph_neighbors` MCP tool | Entities linked to a given entity |
| `graph_review_candidates` MCP tool | Same-entity suggestions waiting for a decision |

Two things need an extra. `graph_export` and `.ftm` export need `pip install "openosint[graph]"`, which builds PyICU. Same-entity scoring needs `openosint[graph-dedup]` on Python 3.11 or newer.

The database is `graph.db` in the data directory (`~/.openosint/`), or the path in `OPENOSINT_GRAPH_DB`. It starts empty. Neither the web UI nor the agent writes to it; you fill it through the Python API. The [graph guide on GitHub](https://github.com/OpenOSINT/OpenOSINT/blob/main/docs/graph.md) has the full API and a worked example.

## Personal data

The store holds real data on your disk, such as names, emails and probable links between identities. You are its controller: decide what goes in, how long it stays and who can read it. `GraphStore.erase()` removes every statement about an entity, with its provenance and links. The store is local; OpenOSINT never sends it anywhere.
