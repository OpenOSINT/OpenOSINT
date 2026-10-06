"""Graph store, subgraph view and neighbours work with PyICU unavailable.

Runs in a subprocess with `icu` blocked, which is exactly what `uvx openosint web`
looks like on a machine that cannot build PyICU. Needs no extra, so it runs in
every CI job.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

_SCRIPT = textwrap.dedent(
    """
    import sys
    sys.modules["icu"] = None  # import icu -> ImportError, as on a machine without libicu

    from datetime import datetime, timezone
    from openosint.graph import ftm_compat
    assert not ftm_compat.HAS_FTM, "followthemoney must not import without icu"

    from openosint.correlation import EntityType, make_entity
    from openosint.graph.identity import entity_id_for
    from openosint.graph.mapping import map_github
    from openosint.graph.store import GraphStore
    from openosint.graph.web_view import build_subgraph

    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    raw = "[GitHub] Login: octocat\\n[GitHub] Name: The Octocat\\n[GitHub] Company: @GitHub\\n"
    store = GraphStore(":memory:")
    store.append(map_github(raw, make_entity(EntityType.USERNAME, "octocat", 1.0),
                            run_id="r1", collected_at=now))
    account = entity_id_for("UserAccount", "github", "octocat")
    assert store.get_statements_by_entity(account)
    graph = build_subgraph(store, entity_id=account, depth=2, cross_layer=False, dataset=None)
    assert graph["nodes"], graph
    try:
        import openosint.graph.entity_proxy  # noqa: F401
    except ImportError:
        print("OK")
    else:
        raise SystemExit("entity_proxy imported without followthemoney")
    """
)


def test_graph_store_and_subgraph_work_without_followthemoney():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("OK")
