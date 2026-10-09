# openosint/tools/search_domain.py
"""
Domain enumeration module.

Wraps the 'sublist3r' binary to discover subdomains of a target domain.
Returns a formatted string; never raises on failure.
"""

from __future__ import annotations

import logging

from openosint.proxy import get_subprocess_env
from openosint.tool_policy import requires_active
from openosint.tools.exceptions import OSINTError
from openosint.utils import run_subprocess

logger = logging.getLogger(__name__)

_BINARY = "sublist3r"
_DEFAULT_TIMEOUT = 120
_INSTALL_HINT = "Install it with: uv tool install sublist3r (or: pip install sublist3r)"


async def _run_sublist3r(domain: str, timeout_seconds: int) -> str:
    """Execute sublist3r against domain and return raw stdout."""
    result = await run_subprocess(
        binary=_BINARY,
        args=["-d", domain, "-n"],
        timeout_seconds=timeout_seconds,
        install_hint=_INSTALL_HINT,
        env=get_subprocess_env(),
    )
    return result.stdout


def _format_domain_results(raw: str, domain: str) -> str:
    """Return a structured string suitable for CLI display and LLM consumption."""
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and domain in line and not line.startswith("[")
    ]
    if not lines:
        return f"No subdomains found for '{domain}'."
    return f"Subdomains found for '{domain}':\n\n" + "\n".join(
        f"[+] {subdomain}" for subdomain in lines
    )


@requires_active("search_domain")
async def run_domain_osint(
    domain: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Enumerate subdomains of domain using sublist3r.

    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    domain:
        Target domain (e.g. example.com).
    timeout_seconds:
        Maximum execution time for the sublist3r subprocess.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting domain enumeration for: %s", domain)
    try:
        raw = await _run_sublist3r(domain, timeout_seconds)
        result = _format_domain_results(raw, domain)
        logger.info("Domain enumeration complete for: %s", domain)
        return result
    except OSINTError as exc:
        logger.warning("Domain scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during domain scan.")
        return f"Internal error: {exc}"
