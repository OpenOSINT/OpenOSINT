# openosint/utils.py
"""
Shared utility functions for OpenOSINT tool modules.

run_subprocess() centralises the asyncio subprocess execution pattern
(binary check → create_subprocess_exec → wait_for → kill on timeout)
that all binary-based OSINT tool wrappers share.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

from openosint.tools.exceptions import ToolNotFoundError, ToolTimeoutError

logger = logging.getLogger(__name__)


# Self-promotion and credit lines that wrapped CLIs print after their results. They are not
# findings: left in, they reach the model and the user as if the tool had reported them.
_PROMO_LINE_RE = re.compile(
    r"go deeper than a username"  # sherlock
    r"|try osintsearch"  # sherlock
    r"|^twitter\s*:\s*@palenath"  # holehe
    r"|^github\s*:\s*https://github\.com/megadose/holehe"  # holehe
    r"|^for btc donations"  # holehe
    r"|coded by ahmed aboul-ela",  # sublist3r banner
    re.IGNORECASE,
)


def strip_promo_footer(raw: str) -> str:
    """Drop third-party promotion/credit lines from a wrapped tool's stdout."""
    kept = [line for line in raw.splitlines() if not _PROMO_LINE_RE.search(line.strip())]
    return "\n".join(kept).strip()


class SubprocessResult(NamedTuple):
    """Result of a completed external subprocess call."""

    stdout: str
    stderr: str
    return_code: int


def find_binary(binary: str) -> str | None:
    """Resolve *binary* the way tools run it: this interpreter's bin dir, then PATH.

    The interpreter's own bin dir comes first so console scripts installed next
    to OpenOSINT (a venv, or the environment `uvx` builds) are found without
    being on the user's PATH.
    """
    venv_bin = str(Path(sys.executable).parent)
    return shutil.which(binary, path=os.pathsep.join([venv_bin, os.environ.get("PATH", "")]))


async def run_subprocess(
    binary: str,
    args: list[str],
    timeout_seconds: int,
    install_hint: str = "",
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """
    Execute an external binary asynchronously and return its output.

    Parameters
    ----------
    binary:
        Executable name discoverable via PATH.
    args:
        Arguments forwarded to the binary.
    timeout_seconds:
        Hard wall-clock limit; process is killed on expiry.
    install_hint:
        Short installation message appended to ToolNotFoundError.
    env:
        Environment for the child process. None (default) inherits the
        current process environment unchanged.

    Raises
    ------
    ToolNotFoundError
        When the binary is absent from PATH.
    ToolTimeoutError
        When the process exceeds timeout_seconds.
    """
    resolved = find_binary(binary)
    if not resolved:
        detail = f" {install_hint}" if install_hint else ""
        raise ToolNotFoundError(f"'{binary}' is not installed or not in PATH.{detail}")
    binary = resolved

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        raw_stdout, raw_stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=float(timeout_seconds),
        )
        return SubprocessResult(
            stdout=raw_stdout.decode("utf-8", errors="replace").strip(),
            stderr=raw_stderr.decode("utf-8", errors="replace").strip(),
            return_code=process.returncode or 0,
        )
    except asyncio.TimeoutError:
        _kill_process(process)
        raise ToolTimeoutError(f"'{binary}' scan timed out after {timeout_seconds}s.")


def _kill_process(process: asyncio.subprocess.Process | None) -> None:
    """Terminate a subprocess, ignoring errors if it already exited."""
    if process is None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        pass
