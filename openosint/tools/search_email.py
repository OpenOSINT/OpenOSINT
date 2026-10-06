# openosint/tools/search_email.py
"""
Email OSINT module.

Wraps the 'holehe' binary to enumerate online services registered against a
target email address. Returns a formatted string; never raises on failure.
"""

from __future__ import annotations

import logging

from openosint.proxy import get_subprocess_env
from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.utils import run_subprocess

logger = logging.getLogger(__name__)

_BINARY = "holehe"
_DEFAULT_TIMEOUT = 120
_INSTALL_HINT = "Install it with: uv tool install holehe (or: pip install holehe)"


async def _run_holehe(email: str, timeout_seconds: int) -> str:
    """Execute holehe against email and return raw stdout."""
    result = await run_subprocess(
        binary=_BINARY,
        args=[email, "--only-used"],
        timeout_seconds=timeout_seconds,
        install_hint=_INSTALL_HINT,
        env=get_subprocess_env(),
    )
    if result.return_code != 0:
        raise ToolExecutionError(f"holehe exited with code {result.return_code}: {result.stderr}")
    return result.stdout


def _format_email_results(raw: str, email: str) -> str:
    """Return a structured string suitable for CLI display and LLM consumption."""
    if not raw:
        return f"No registered services found for {email}."
    return f"OSINT results for '{email}':\n\n{raw}"


async def run_email_osint(
    email: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Run an email OSINT scan and return a formatted result string.

    Calls holehe to enumerate online services registered against the target
    email. Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    email:
        Target email address.
    timeout_seconds:
        Maximum execution time for the holehe subprocess.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting email OSINT scan for: %s", email)
    try:
        raw = await _run_holehe(email, timeout_seconds)
        result = _format_email_results(raw, email)
        logger.info("Email scan complete for: %s", email)
        return result
    except OSINTError as exc:
        logger.warning("Email scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error during email scan.")
        return f"Internal error: {exc}"
