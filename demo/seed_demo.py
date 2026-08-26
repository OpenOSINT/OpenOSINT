#!/usr/bin/env python3
"""Seed and drive the graph-module demo recorded by demo/graph_demo.tape.

SYNTHETIC DATA ONLY — this rule is load-bearing. The graph store persists
personal data, and the rendered GIF is permanent and indexed. Every value in
this scenario is fictional: "Aurora Dynamics Research" does not exist, and
`.example` is an IANA-reserved TLD that can never resolve. Never replace any
of it with a real name, email, domain, or username, and never make this
script touch the network.

The demo must render identically on every run, so everything time-like is
frozen: one fixed collected_at timestamp, fixed run ids, a fixed store path.
Entity ids and the LogicV2 score are content-derived, hence stable too.

Usage: seed_demo.py {seed|entities|crossref|review|accept|export}
`seed` builds a fresh throwaway SQLite store (run off-screen by the tape);
the other subcommands are the five on-screen steps, in order.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from followthemoney.statement import Statement

from openosint.graph.identity import entity_id_for
from openosint.graph.mapping import EmissionResult
from openosint.graph.provenance import make_provenance
from openosint.graph.store import GraphStore

DEMO_DIR = Path(os.environ.get("OPENOSINT_DEMO_DIR", "/tmp/osint-graph-demo"))
DB_PATH = DEMO_DIR / "graph.db"
FTM_PATH = DEMO_DIR / "aurora.ftm"

# Frozen clock: the tape must produce the same frames on every render.
COLLECTED_AT = datetime(2026, 1, 14, 9, 30, 0, tzinfo=timezone.utc)
RUN_GITHUB = "gh-2026-0114"
RUN_WHOIS = "whois-2026-0114"
RUN_CROSSREF = "crossref-2026-0114"
REVIEWER = "analyst-demo"

# The two fictional observations of the same fictional organization.
ORG_A_ID = entity_id_for("Organization", "github-company", "aurora dynamics research")
ORG_B_ID = entity_id_for("Organization", "whois-registrant", "aurora-dynamics.example")

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
CYAN, GREEN, YELLOW, MAGENTA = "\033[36m", "\033[32m", "\033[33m", "\033[35m"


def short(entity_id: str) -> str:
    return entity_id[:8]


def open_store() -> GraphStore:
    if not DB_PATH.exists():
        sys.exit("demo store missing — run `seed_demo.py seed` first")
    return GraphStore(DB_PATH)


def cmd_seed() -> None:
    """Build the throwaway store from scratch. Runs off-screen, before Show."""
    shutil.rmtree(DEMO_DIR, ignore_errors=True)
    DEMO_DIR.mkdir(parents=True)
    iso = COLLECTED_AT.isoformat()

    def statements(entity_id: str, dataset: str, props: list[tuple[str, str]]) -> list[Statement]:
        return [
            Statement(entity_id=entity_id, prop=prop, schema="Organization", value=value,
                      dataset=dataset, first_seen=iso, last_seen=iso)
            for prop, value in props
        ]

    stmts_a = statements(ORG_A_ID, "openosint:github",
                         [("name", "Aurora Dynamics Research"),
                          ("website", "https://aurora-dynamics.example")])
    stmts_b = statements(ORG_B_ID, "openosint:whois",
                         [("name", "Aurora Dynamics Research B.V."),
                          ("email", "registry@aurora-dynamics.example"),
                          ("website", "https://aurora-dynamics.example")])
    provenance = [
        make_provenance(statement_id=s.id, run_id=RUN_GITHUB,
                        collection_method="map_github:company",
                        extractor_confidence=0.70, collected_at=COLLECTED_AT)
        for s in stmts_a
    ] + [
        make_provenance(statement_id=s.id, run_id=RUN_WHOIS,
                        # The website is the queried domain itself; the rest
                        # comes off the registrant record.
                        collection_method=("map_whois:domain" if s.prop == "website"
                                           else "map_whois:name_org"),
                        extractor_confidence=0.80, collected_at=COLLECTED_AT)
        for s in stmts_b
    ]
    with GraphStore(DB_PATH) as store:
        store.append(EmissionResult(statements=tuple(stmts_a + stmts_b),
                                    provenance=tuple(provenance), bridge_links=()))


def cmd_entities() -> None:
    print(f"{BOLD}Graph store — 2 entities from 2 independent runs{RESET} "
          f"{DIM}(synthetic demo data){RESET}\n")
    with open_store() as store:
        for entity_id in (ORG_A_ID, ORG_B_ID):
            stmts = store.get_statements_by_entity(entity_id)
            name = next(s.value for s in stmts if s.prop == "name")
            prov = store.get_provenance(stmts[0].id)[0]
            print(f"  {CYAN}Organization {short(entity_id)}{RESET}  {BOLD}“{name}”{RESET}")
            print(f"    {DIM}dataset={RESET}{YELLOW}{stmts[0].dataset}{RESET}"
                  f"  {DIM}run={prov.run_id}  {prov.collection_method}"
                  f"  conf={prov.extractor_confidence:.2f}{RESET}")
            for s in stmts:
                if s.prop != "name":
                    print(f"    {DIM}{s.prop}: {s.value}{RESET}")
            print()


def cmd_crossref() -> None:
    from nomenklatura.matching import LogicV2

    from openosint.graph.dedup.crossref import run_crossref
    from openosint.graph.dedup.scoring import algorithm_identity

    algo = algorithm_identity(LogicV2)
    with open_store() as store:
        candidates = run_crossref(store, run_id=RUN_CROSSREF, decided_at=COLLECTED_AT)
        print(f"{BOLD}run_crossref{RESET} — scored all same-schema pairs "
              f"{DIM}({algo['name']}, nomenklatura {algo['version']}){RESET}\n")
        for cand in candidates:
            print(f"  {MAGENTA}same_as candidate{RESET}  "
                  f"{short(cand.entity_id_a)} ≈ {short(cand.entity_id_b)}"
                  f"   {BOLD}score {cand.score:.3f}{RESET}")
            feature = cand.explanation["name_match"]
            print(f"    name_match: {DIM}'{feature['query']}' vs '{feature['candidate']}'{RESET}")
            for chunk in str(feature["detail"]).replace("] [", "]\n[").splitlines():
                for line in textwrap.wrap(chunk, width=76):
                    print(f"      {DIM}{line}{RESET}")
        print(f"\n  → {YELLOW}judgement='unsure'{RESET} recorded — "
              f"{BOLD}auto-merge is forbidden{RESET}; a human decides.")


def cmd_review() -> None:
    from openosint.graph.review import list_review_candidates

    with open_store() as store:
        pending = list_review_candidates(store)
        print(f"{BOLD}Human review queue{RESET} — {len(pending)} pending candidate(s), "
              f"{YELLOW}judgement='unsure'{RESET}\n")
        for cand in pending:
            score = f"{cand.score:.3f}" if cand.score is not None else "?"
            print(f"  [{cand.resolution_id}] {cand.schema}  score {score}")
            for entity_id, props in ((cand.entity_id_a, cand.entity_a_properties),
                                     (cand.entity_id_b, cand.entity_b_properties)):
                dataset = store.get_statements_by_entity(entity_id)[0].dataset
                print(f"    {short(entity_id)}  “{props['name'][0]}”  {DIM}({dataset}){RESET}")
        print(f"\n  canonical_for({short(ORG_A_ID)})={short(store.canonical_for(ORG_A_ID))}"
              f"   canonical_for({short(ORG_B_ID)})={short(store.canonical_for(ORG_B_ID))}")
        print(f"  → still two separate entities. {BOLD}NOTHING auto-merged.{RESET}")


def cmd_accept() -> None:
    from openosint.graph.review import decide_review_candidate

    with open_store() as store:
        decide_review_candidate(store, entity_id=ORG_A_ID, canonical_id=ORG_B_ID,
                                judgement="positive", decided_at=COLLECTED_AT,
                                reviewer_id=REVIEWER)
        print(f"{BOLD}Recorded human accept{RESET} — judgement='positive' "
              f"{DIM}(by=human, reviewer={REVIEWER}){RESET}\n")
        print(f"  canonical_for({short(ORG_A_ID)})={short(store.canonical_for(ORG_A_ID))}"
              f"   canonical_for({short(ORG_B_ID)})={short(store.canonical_for(ORG_B_ID))}")
        print(f"  → {GREEN}{BOLD}one canonical entity ✓{RESET}")


def cmd_export() -> None:
    from openosint.graph.export import export_entities

    with open_store() as store:
        count = 0
        with open(FTM_PATH, "w", encoding="utf-8") as outfile:
            for entity in export_entities(store):
                outfile.write(json.dumps(entity, sort_keys=True) + "\n")
                count += 1
    print(f"{BOLD}graph_export{RESET} — wrote {count} FtM entities → {FTM_PATH}")


COMMANDS = {
    "seed": cmd_seed,
    "entities": cmd_entities,
    "crossref": cmd_crossref,
    "review": cmd_review,
    "accept": cmd_accept,
    "export": cmd_export,
}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: seed_demo.py {{{'|'.join(COMMANDS)}}}")
    COMMANDS[sys.argv[1]]()
