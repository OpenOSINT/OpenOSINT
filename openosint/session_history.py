# openosint/session_history.py
"""
Persistent session history for OpenOSINT.

Sessions are stored as JSON files in $OPENOSINT_HOME/history/ (default ~/.openosint/history/).
At most 50 sessions are retained; oldest are deleted automatically.
Sensitive data (raw tool output, API keys) is never stored — only metadata.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openosint.paths import home_dir

logger = logging.getLogger(__name__)

HISTORY_DIR = home_dir() / "history"
MAX_SESSIONS = 50


@dataclass
class SessionRecord:
    timestamp: str
    duration_seconds: int
    prompts: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    report_path: str = ""


def _ensure_dir() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def save_session(record: SessionRecord) -> Path:
    """Save a session record to disk, pruning oldest files if over MAX_SESSIONS."""
    _ensure_dir()
    safe_ts = record.timestamp.replace(":", "-")
    path = HISTORY_DIR / f"{safe_ts}_session.json"
    path.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")

    all_files = sorted(HISTORY_DIR.glob("*_session.json"))
    while len(all_files) > MAX_SESSIONS:
        try:
            all_files[0].unlink()
        except Exception:
            logger.debug("Failed to prune old session file.", exc_info=True)
        all_files = all_files[1:]

    return path


def load_sessions(limit: int | None = None) -> list[dict[str, Any]]:
    """Return sessions sorted newest-first, optionally capped to `limit`."""
    if not HISTORY_DIR.exists():
        return []
    files = sorted(HISTORY_DIR.glob("*_session.json"), reverse=True)
    if limit is not None:
        files = files[:limit]
    sessions: list[dict[str, Any]] = []
    for session_file in files:
        try:
            sessions.append(json.loads(session_file.read_text(encoding="utf-8")))
        except Exception:
            logger.debug("Failed to read session file: %s", session_file, exc_info=True)
    return sessions


def count_sessions() -> int:
    """Return the number of saved sessions without loading their content."""
    if not HISTORY_DIR.exists():
        return 0
    return sum(1 for _ in HISTORY_DIR.glob("*_session.json"))


def clear_sessions() -> int:
    """Delete all session files. Returns the number deleted."""
    if not HISTORY_DIR.exists():
        return 0
    files = list(HISTORY_DIR.glob("*_session.json"))
    for session_file in files:
        try:
            session_file.unlink()
        except Exception:
            logger.debug("Failed to delete session file: %s", session_file, exc_info=True)
    return len(files)


# ---------------------------------------------------------------------------
# Rich display helpers (shared by REPL and CLI)
# ---------------------------------------------------------------------------


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s"


def _fmt_targets(targets: list[str]) -> str:
    if not targets:
        return "—"
    if len(targets) <= 2:
        return ", ".join(targets)
    return f"{targets[0]}, +{len(targets) - 1} more"


def _fmt_tools(tools: list[str]) -> str:
    return ", ".join(tools) if tools else "—"


def display_history_table(sessions: list[dict[str, Any]], console: Any) -> None:
    """Render a list of sessions as a Rich table."""
    from rich import box
    from rich.table import Table

    if not sessions:
        console.print("  [dim]No sessions saved yet.[/]\n")
        return

    table = Table(
        box=box.SIMPLE_HEAD,
        border_style="#1e293b",
        header_style="bold #00ff88",
        show_header=True,
    )
    table.add_column("#", style="dim", justify="right")
    table.add_column("Date", style="#f1f5f9")
    table.add_column("Duration", style="dim", justify="right")
    table.add_column("Targets", style="#94a3b8")
    table.add_column("Tools Used", style="#94a3b8")
    table.add_column("Report", style="dim")

    for i, session in enumerate(sessions, 1):
        table.add_row(
            str(i),
            session.get("timestamp", "")[:16],
            _fmt_duration(session.get("duration_seconds", 0)),
            _fmt_targets(session.get("targets", [])),
            _fmt_tools(session.get("tools_used", [])),
            "yes" if session.get("report_path") else "—",
        )

    console.print()
    console.print(table)
    console.print()


def display_session_detail(session: dict[str, Any], index: int, console: Any) -> None:
    """Render full session details as a Rich panel, then print report if it exists."""
    from rich.panel import Panel

    prompts = session.get("prompts", [])
    targets = session.get("targets", [])
    tools = session.get("tools_used", [])
    report = session.get("report_path", "")

    lines = [
        f"[bold]Date:[/]      {session.get('timestamp', '')}",
        f"[bold]Duration:[/]  {_fmt_duration(session.get('duration_seconds', 0))}",
        "[bold]Prompts:[/]",
        *[f"  • {p}" for p in prompts],
        f"[bold]Targets:[/]   {', '.join(targets) or '—'}",
        f"[bold]Tools:[/]     {', '.join(tools) or '—'}",
        f"[bold]Report:[/]    {report or '—'}",
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title=f"[bold]Session #{index}[/]",
            border_style="#00ff88",
            padding=(0, 2),
        )
    )

    if report:
        rp = Path(report)
        if rp.exists():
            from rich.markdown import Markdown

            console.print(
                Panel(
                    Markdown(rp.read_text(encoding="utf-8")),
                    title="[bold]Report[/]",
                    border_style="#1e293b",
                    padding=(1, 2),
                )
            )

    console.print()
