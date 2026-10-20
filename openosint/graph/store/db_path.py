# openosint/graph/store/db_path.py
"""
Canonical resolution of the local graph.db path.

Lives next to GraphStore (this package) and imports nothing heavy — only
os/pathlib — so every caller that needs the path (mcp_tools, web_view) imports
it from ONE place. A rename here is a visible break at those import sites,
not silent coupling to a private name in some other module.
"""

from __future__ import annotations

import os
from pathlib import Path

from openosint.paths import home_dir


def default_db_path() -> Path:
    """The graph store path: $OPENOSINT_GRAPH_DB, else $OPENOSINT_HOME/graph.db
    (default ~/.openosint/graph.db).

    Creates the parent directory so a first-run caller can open the store
    immediately.
    """
    override = os.environ.get("OPENOSINT_GRAPH_DB")
    path = Path(override) if override else home_dir() / "graph.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
