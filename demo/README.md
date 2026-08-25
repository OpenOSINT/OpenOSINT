# Graph module demo

`graph-demo.gif` (README) and `graph-demo.webm` (site) are rendered from
[`graph_demo.tape`](graph_demo.tape) with [Charmbracelet VHS](https://github.com/charmbracelet/vhs)
— tape-as-code, not a screen recording. The tape seeds a throwaway SQLite
store off-screen via [`seed_demo.py`](seed_demo.py), then walks the graph
module's core loop on screen: provenance-carrying statements from two
datasets → `run_crossref` same_as candidate with score and feature
explanation → human review queue (`unsure`, nothing auto-merged) → human
accept → one canonical entity → `.ftm` export that passes `ftm validate`.

## Regenerating

```bash
brew install vhs   # pulls ttyd + ffmpeg
pip install -e ".[graph,graph-dedup]"   # into .venv — the tape uses .venv/bin
vhs demo/graph_demo.tape
```

The output is deterministic: timestamps, run ids, and the store path are
frozen in `seed_demo.py`, entity ids and the LogicV2 score are
content-derived, and the store is rebuilt from scratch on every run. The
score/explanation can only change if the installed nomenklatura version does.

After re-rendering, copy the webm for the site:

```bash
cp demo/graph-demo.webm docs/assets/graph-demo.webm
```

## Why the demo seeds at the statement layer (known gap)

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

The demo therefore seeds both observations as `Organization` — the GitHub
company field exactly as `map_github` would emit it, and the WHOIS
registrant org as `Organization` instead of today's `LegalEntity`. It
becomes reproducible end-to-end once mapper coverage closes the gap: e.g.
emitting `map_whois`'s registrant org as `Organization` (aligning it with
`map_github`'s company entity), or scoring across the FtM LegalEntity
hierarchy in candidate generation. Until then, treat this as a known,
deliberate gap — the store, crossref, review, and export behavior shown is
all real; only the ingestion path is idealized.

## The demo data is fictional and must stay that way

The graph store persists personal data, and this GIF is permanent and
indexed once published. Every value in the scenario is synthetic:
"Aurora Dynamics Research" is invented, and `.example` is an IANA-reserved
TLD that can never resolve. Never substitute a real name, email, domain,
username, or organization — not the maintainers', not the project's own
accounts — and never make the demo touch the live network.
