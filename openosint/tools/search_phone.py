# openosint/tools/search_phone.py
"""
Phone number intelligence module.

Wraps the 'phoneinfoga' binary to gather carrier, country, and line type data
for a target phone number. Returns a formatted string; never raises.
"""

from __future__ import annotations

import logging

from openosint.proxy import get_subprocess_env
from openosint.tool_policy import requires_active
from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.utils import run_subprocess

logger = logging.getLogger(__name__)

_BINARY = "phoneinfoga"
_DEFAULT_TIMEOUT = 60
_INSTALL_HINT = "Download from: https://github.com/sundowndev/phoneinfoga/releases"


async def _run_phoneinfoga(phone: str, timeout_seconds: int) -> str:
    """Execute phoneinfoga against phone and return raw stdout."""
    result = await run_subprocess(
        binary=_BINARY,
        args=["scan", "-n", phone],
        timeout_seconds=timeout_seconds,
        install_hint=_INSTALL_HINT,
        env=get_subprocess_env(),
    )
    if not result.stdout:
        raise ToolExecutionError(
            f"phoneinfoga produced no output for '{phone}'. stderr: {result.stderr}"
        )
    return result.stdout


def _format_phone_results(raw: str, phone: str) -> str:
    """Return a structured string suitable for CLI display and LLM consumption."""
    if not raw:
        return f"No data found for phone number '{phone}'."
    return f"Phone intelligence for '{phone}':\n\n{raw}"


@requires_active("search_phone")
async def run_phone_osint(
    phone: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Gather intelligence on phone using phoneinfoga.

    The phone number should be in E.164 format (e.g. +14155552671).
    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    phone:
        Target phone number in E.164 format.
    timeout_seconds:
        Maximum execution time for the phoneinfoga subprocess.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting phone scan for: %s", phone)
    try:
        raw = await _run_phoneinfoga(phone, timeout_seconds)
        result = _format_phone_results(raw, phone)
        logger.info("Phone scan complete for: %s", phone)
        return result
    except OSINTError as exc:
        logger.warning("Phone scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during phone scan.")
        return f"Internal error: {exc}"
