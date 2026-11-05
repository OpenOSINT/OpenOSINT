"""User-level settings file in the data directory: $OPENOSINT_HOME/config.env.

Keys and settings saved from the web UI live here, never inside the installed
package (a pip/uvx install's site-packages is replaced on upgrade and may be
read-only). The file is dotenv-formatted, written atomically and, where the OS
supports it, readable by the current user only (0600, in a 0700 directory when
we create it).

Precedence, highest first (see openosint/env.py, which applies it):
  1. real environment variables
  2. this file
  3. legacy .env locations (OPENOSINT_ENV_FILE, ./.env upward, package root)

A legacy .env is read in place and is never copied here implicitly; copying is
the explicit `openosint config import` command (openosint/config_cli.py).

Values are never logged or returned by anything in this module.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from dotenv import dotenv_values

from openosint.paths import home_dir

CONFIG_FILENAME = "config.env"
_MAX_LEGACY_BYTES = 64 * 1024
_FILE_MODE = 0o600
_DIR_MODE = 0o700


def config_path() -> Path:
    return home_dir() / CONFIG_FILENAME


def read_config() -> dict[str, str]:
    path = config_path()
    if not path.is_file():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def validate_pair(key: str, value: str) -> None:
    """Raise ValueError for a key/value that cannot be stored safely."""
    if not key or not all(ch.isalnum() or ch == "_" for ch in key) or key[0].isdigit():
        raise ValueError(f"invalid setting name: {key!r}")
    if _has_control_chars(value):
        raise ValueError(f"{key}: value contains control characters")


def write_config(updates: Mapping[str, str]) -> dict[str, str]:
    """Merge *updates* into the config file and return the new full contents.

    Atomic (temp file + rename in the same directory) so a crash never leaves a
    half-written file, and created user-only from the start so the secrets are
    never briefly world-readable.
    """
    for key, value in updates.items():
        validate_pair(key, value)

    merged = {**read_config(), **updates}
    path = config_path()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=_DIR_MODE)

    body = "".join(f"{k}={_quote(v)}\n" for k, v in merged.items())
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            _restrict(tmp_name)
            handle.write(body)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    _restrict(path)
    return merged


def _restrict(path: str | Path) -> None:
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass  # e.g. Windows / FAT: no POSIX modes, nothing more we can do


def is_user_only(path: Path) -> bool | None:
    """True/False on POSIX; None where permissions cannot be checked (Windows)."""
    if os.name != "posix":
        return None
    return (path.stat().st_mode & 0o077) == 0


def config_dir_exposed() -> bool:
    """True when the data directory exists and group/other can enter or list it (POSIX)."""
    directory = config_path().parent
    if os.name != "posix" or not directory.is_dir():
        return False
    return (directory.stat().st_mode & 0o077) != 0


def legacy_candidates(legacy: Path, importable_keys: frozenset[str]) -> dict[str, str]:
    """Known, non-blank, control-character-free settings in a legacy .env. Read-only."""
    try:
        if not legacy.is_file() or legacy.stat().st_size > _MAX_LEGACY_BYTES:
            return {}
        values = dotenv_values(legacy)
    except OSError:
        return {}
    return {
        k: v.strip()
        for k, v in values.items()
        if k in importable_keys and v and v.strip() and not _has_control_chars(v)
    }


def import_legacy_env(
    legacy: Path,
    importable_keys: frozenset[str],
    only: Sequence[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Copy settings from *legacy* into the config file; the caller has already confirmed.

    Values already in the config file are never overwritten. The legacy file is left
    untouched. Returns (imported names, skipped names), both sorted; names only.
    """
    picked = legacy_candidates(legacy, importable_keys)
    if only is not None:
        picked = {k: v for k, v in picked.items() if k in set(only)}
    existing = read_config()
    skipped = sorted(k for k in picked if k in existing)
    fresh = {k: v for k, v in picked.items() if k not in existing}
    if fresh:
        write_config(fresh)
    return sorted(fresh), skipped


def shadowed_keys(config_values: Mapping[str, str], legacy_values: Mapping[str, str]) -> list[str]:
    """Names set to different non-blank values in both files (config.env wins)."""
    return sorted(
        k
        for k, v in legacy_values.items()
        if v and v.strip() and (config_values.get(k) or "").strip() not in ("", v.strip())
    )
