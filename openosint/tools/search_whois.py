# openosint/tools/search_whois.py
"""
WHOIS module.

Queries WHOIS registration data for a target domain using python-whois.
The synchronous whois call is run in a thread executor with an asyncio
timeout so it cannot block the event loop indefinitely.
Returns a formatted string; never raises on failure.
"""

from __future__ import annotations

import asyncio
import logging

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15


def _fetch_whois_data(domain: str) -> object:
    """
    Perform a synchronous WHOIS lookup for domain.

    Intended to run inside a thread executor.

    Raises
    ------
    OSINTError
        When python-whois is not installed.
    ToolExecutionError
        When the WHOIS query itself fails.
    """
    try:
        import whois  # type: ignore
    except ImportError as exc:
        raise OSINTError("python-whois is not installed. Run: pip install python-whois") from exc

    try:
        return whois.whois(domain)
    except Exception as exc:
        raise ToolExecutionError(f"WHOIS query failed for '{domain}': {exc}") from exc


def _format_whois_results(data: object, domain: str) -> str:
    """Return a structured string describing WHOIS registration data."""
    fields = {
        "Domain": getattr(data, "domain_name", None),
        "Registrar": getattr(data, "registrar", None),
        "Created": getattr(data, "creation_date", None),
        "Expires": getattr(data, "expiration_date", None),
        "Updated": getattr(data, "updated_date", None),
        "Name Servers": getattr(data, "name_servers", None),
        "Emails": getattr(data, "emails", None),
        "Name": getattr(data, "name", None),
        "Org": getattr(data, "org", None),
        "Country": getattr(data, "country", None),
    }

    lines = [f"WHOIS results for '{domain}':\n"]
    for key, val in fields.items():
        if not val:
            continue
        if isinstance(val, list):
            val = val[0] if len(val) == 1 else ", ".join(str(v) for v in val[:3])
        lines.append(f"[+] {key}: {val}")

    return "\n".join(lines) if len(lines) > 1 else f"No WHOIS data found for '{domain}'."


async def run_whois_osint(
    domain: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Run a WHOIS lookup on domain.

    Executes the synchronous python-whois call in a thread executor, wrapped
    in asyncio.wait_for so the event loop is never blocked indefinitely.

    Parameters
    ----------
    domain:
        Target domain (e.g. example.com).
    timeout_seconds:
        Maximum time to wait for the WHOIS response.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting WHOIS lookup for: %s", domain)
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_whois_data, domain),
            timeout=float(timeout_seconds),
        )
        result = _format_whois_results(data, domain)
        logger.info("WHOIS lookup complete for: %s", domain)
        return result
    except asyncio.TimeoutError:
        logger.warning("WHOIS lookup timed out for: %s", domain)
        return f"Scan error: WHOIS lookup timed out after {timeout_seconds}s."
    except OSINTError as exc:
        logger.warning("WHOIS lookup failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during WHOIS lookup.")
        return f"Internal error: {exc}"
