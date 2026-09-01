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
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

from openosint.tools.exceptions import ToolNotFoundError, ToolTimeoutError

logger = logging.getLogger(__name__)


class SubprocessResult(NamedTuple):
    """Result of a completed external subprocess call."""

    stdout: str
    stderr: str
    return_code: int


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
    # Prepend the venv/uv-tool bin dir so co-installed tools are found even
    # when the venv is not activated and its bin is absent from the user's PATH.
    venv_bin = str(Path(sys.executable).parent)
    search_path = os.pathsep.join([venv_bin, os.environ.get("PATH", "")])
    resolved = shutil.which(binary, path=search_path)
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


def get_ssl_context() -> "ssl.SSLContext":
    """Return an SSL context suitable for aiohttp on this host.

    aiohttp's default context rejects servers that transmit their own root in
    the chain — including api.github.com and crt.sh, which fail with
    "self-signed certificate in certificate chain" / "unable to get local
    issuer certificate" even though the root is present in certifi. The
    requests-based tools are unaffected, so this only matters for the aiohttp
    callers.

    VERIFY_X509_PARTIAL_CHAIN lets OpenSSL treat any trusted cert in the chain
    as an anchor rather than demanding a complete path to a self-signed root it
    already knows, which is what curl and httpx effectively do.
    """
    import ssl

    import certifi

    context = ssl.create_default_context(cafile=certifi.where())
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context
