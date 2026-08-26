# Graph module demos

Two demos, one fictional scenario. Both are rendered from committed,
deterministic scripts — script-as-code, not screen recordings — and both walk
the same story seeded by [`seed_demo.py`](seed_demo.py): provenance-carrying
statements from two datasets → `run_crossref` same_as candidate with score and
feature explanation → human review (`unsure`, nothing auto-merged) → human
accept → one canonical entity.

| Demo | Source | Output | Shown in |
|---|---|---|---|
| Web UI | [`web_demo.py`](web_demo.py) (Playwright) | `graph-web-demo.gif` / `.webm` | README top, [site](../docs/index.html) |
| Terminal | [`graph_demo.tape`](graph_demo.tape) (VHS) | `graph-demo.gif` / `.webm` | [docs/graph.md](../docs/graph.md) |

The web demo shows the graph explorer and review queue UI: the dashed same_as
edge, per-statement provenance in the side panel, the side-by-side review card
(matching values green, differing amber), and the in-place merge on accept.
The terminal demo shows the same loop from the CLI, plus the `.ftm` export
that passes `ftm validate`.

## Regenerating the web UI demo

```bash
pip install -e ".[graph,graph-dedup,web]"   # into .venv
pip install playwright && playwright install chromium
python demo/web_demo.py                      # needs ffmpeg on PATH
cp demo/graph-web-demo.webm docs/assets/graph-web-demo.webm
```

The script seeds a throwaway store in a temp directory (your real
`~/.openosint/graph.db` is never touched), serves it on localhost, drives the
UI with a visible injected cursor, and converts the recording with two-pass
palette ffmpeg. Layout is deterministic: Math.random is replaced with a seeded
PRNG before every Cytoscape init.

## Regenerating the terminal demo

```bash
brew install vhs   # pulls ttyd + ffmpeg
pip install -e ".[graph,graph-dedup]"   # into .venv — the tape uses .venv/bin
vhs demo/graph_demo.tape
```

Both outputs are deterministic: timestamps, run ids, and the store path are
frozen in `seed_demo.py`, entity ids and the LogicV2 score are
content-derived, and the store is rebuilt from scratch on every run. The
score/explanation can only change if the installed nomenklatura version does.

## Why the demos seed at the statement layer (known gap)

The scenario is seeded directly with the Phase-1 primitives (`entity_id_for`
+ `Statement` + `make_provenance`), not by running two tools through their
`map_*` mappers. That is not just because the data is synthetic — no real
scan currently reaches the crossref screen shown here. `run_crossref` only
compares same-schema entities (`same_schema_pairs` in
`openosint/graph/dedup/candidates.py`), and LogicV2 scores on names, but no
two current mappers emit a name-carrying entity of the same schema into two
different datasets: `map_github` emits UserAccount/Person/Organization,
`map_whois` emits the registrant as LegalEntity, and `map_breach` emits a
LegalEntity with no name at all.

The demos therefore seed both observations as `Organization` — the GitHub
company field exactly as `map_github` would emit it, and the WHOIS
registrant org as `Organization` instead of today's `LegalEntity`. It
becomes reproducible end-to-end once mapper coverage closes the gap: e.g.
emitting `map_whois`'s registrant org as `Organization` (aligning it with
`map_github`'s company entity), or scoring across the FtM LegalEntity
hierarchy in candidate generation. Until then, treat this as a known,
deliberate gap — the store, crossref, review, and export behavior shown is
all real; only the ingestion path is idealized.

## The demo data is fictional and must stay that way

The graph store persists personal data, and these GIFs are permanent and
indexed once published. Every value in the scenario is synthetic:
"Aurora Dynamics Research" is invented, and `.example` is an IANA-reserved
TLD that can never resolve. `seed_demo.py` is the single source of truth for
the scenario — never add scenario data anywhere else, never substitute a real
name, email, domain, username, or organization — not the maintainers', not
the project's own accounts — and never make a demo touch the live network.
