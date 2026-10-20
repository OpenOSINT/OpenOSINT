"""Where OpenOSINT keeps its persistent data (graph.db, session history)."""

from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    """$OPENOSINT_HOME if set, else ~/.openosint. Not created here."""
    override = os.environ.get("OPENOSINT_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".openosint"
