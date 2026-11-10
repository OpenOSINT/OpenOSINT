"""`openosint config import`: explicit, confirmed copy of a legacy .env into config.env.

Prints setting NAMES only, never values. Nothing here runs on startup and the MCP
server never calls it; a non-interactive caller must pass --yes.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from openosint import config_store
from openosint.settings_catalog import SAVEABLE_NAMES

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_USAGE = 2
_YES = ("y", "yes")


def _fail(message: str) -> int:
    print(f"[!] {message}", file=sys.stderr)
    return EXIT_USAGE


def _confirmed(ask: Callable[[str], str], prompt: str) -> bool:
    return ask(prompt).strip().lower() in _YES


def handle_exposed_directory(
    assume_yes: bool, interactive: bool, ask: Callable[[str], str]
) -> None:
    """Warn when ~/.openosint is group/world accessible; tighten only after an explicit yes."""
    if not config_store.config_dir_exposed():
        return
    directory = config_store.config_path().parent
    print(
        f"[!] {directory} is readable by other users. Files inside stay user-only, "
        f"but run `chmod 700 {directory}` to hide the directory too.",
        file=sys.stderr,
    )
    if assume_yes or not interactive:
        return
    if _confirmed(ask, f"Set {directory} to 700 now? [y/N] "):
        os.chmod(directory, 0o700)
        print(f"[*] {directory} is now user-only.")


def run_config_import(
    source: Path | None,
    only: Sequence[str] | None,
    assume_yes: bool,
    *,
    interactive: bool,
    ask: Callable[[str], str] = input,
) -> int:
    """Return a process exit code: 0 done/nothing to do, 1 declined, 2 usage error."""
    if source is None:
        return _fail("No .env was found to import. Pass one with --from PATH.")
    if not source.is_file():
        return _fail(f"{source} does not exist or is not a file.")

    candidates = config_store.legacy_candidates(source, SAVEABLE_NAMES)
    unknown = sorted(set(only or ()) - set(candidates))
    if unknown:
        return _fail(f"Not importable from {source}: {', '.join(unknown)}.")

    names = sorted(candidates if only is None else set(only))
    existing = config_store.read_config()
    to_copy = [n for n in names if n not in existing]
    skipped = [n for n in names if n in existing]
    if skipped:
        print(f"Skipped (already in {config_store.config_path()}): {', '.join(skipped)}")
    if not to_copy:
        print("Nothing to import.")
        return EXIT_OK

    destination = config_store.config_path()
    print(
        f"Will copy {len(to_copy)} setting(s) from {source} to {destination}: {', '.join(to_copy)}"
    )
    if not assume_yes:
        if not interactive:
            return _fail("Refusing to copy secrets without confirmation; re-run with --yes.")
        if not _confirmed(ask, "Copy these settings? [y/N] "):
            print("Nothing copied.")
            return EXIT_ABORTED

    handle_exposed_directory(assume_yes, interactive, ask)
    imported, _ = config_store.import_legacy_env(source, SAVEABLE_NAMES, only=to_copy)
    print(
        f"Imported {len(imported)} setting(s). {source} was left in place; delete it when you are ready."
    )
    return EXIT_OK
