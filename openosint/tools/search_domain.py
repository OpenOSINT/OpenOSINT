# openosint/tools/search_domain.py
"""
Domain enumeration module.

Discovers subdomains of a target domain from two independent sources:

  * crt.sh — Certificate Transparency log search. Primary source: free, needs
    no API key, and covers any host that has ever been issued a public TLS
    certificate.
  * sublist3r — legacy secondary source. Upstream is unmaintained and most of
    its passive backends (DNSdumpster, VirusTotal, Netcraft) now fail or block,
    so it frequently contributes nothing. Kept because it costs nothing to run
    alongside and occasionally still resolves a host CT does not cover.

Both sources are queried concurrently and their results merged. Per-source
status is always reported so a silent backend failure is never mistaken for
"this domain has no subdomains".

Returns a formatted string; never raises on failure.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from openosint.proxy import (
    get_aiohttp_connector,
    get_aiohttp_proxy,
    get_subprocess_env,
)
from openosint.tools.exceptions import OSINTError
from openosint.utils import get_ssl_context, run_subprocess

logger = logging.getLogger(__name__)

_BINARY = "sublist3r"
_DEFAULT_TIMEOUT = 120
_INSTALL_HINT = "Install it with: pip install sublist3r"

_CRTSH_URL = "https://crt.sh/"
_CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"
_CT_TIMEOUT = 60
_CRTSH_ATTEMPTS = 3
_CRTSH_BACKOFF = 2.0


def _normalise(name: str, domain: str) -> str | None:
    """Lowercase and validate a candidate host, or None if out of scope.

    Wildcards keep their '*.' prefix rather than being stripped — collapsing
    '*.example.com' to 'example.com' would misreport a wildcard certificate as
    the apex record.
    """
    host = name.strip().lower().rstrip(".")
    if not host:
        return None
    suffix = domain.lower().rstrip(".")
    if host == suffix or host == f"*.{suffix}" or host.endswith(f".{suffix}"):
        return host
    return None


def _collect(names: object, domain: str, into: set[str]) -> None:
    """Scope-check an iterable of candidate hostnames into the result set."""
    if not isinstance(names, list):
        return
    for candidate in names:
        if isinstance(candidate, str):
            host = _normalise(candidate, domain)
            if host:
                into.add(host)


async def _get_json(session: aiohttp.ClientSession, url: str, params: dict) -> object:
    async with session.get(
        url, params=params, proxy=get_aiohttp_proxy(), ssl=get_ssl_context()
    ) as resp:
        resp.raise_for_status()
        # crt.sh has served JSON under a text/html content type; don't let
        # aiohttp's strict content-type check reject a valid body.
        return await resp.json(content_type=None)


async def _fetch_crtsh(session: aiohttp.ClientSession, domain: str) -> set[str]:
    """Query crt.sh, retrying its frequent transient 502s."""
    last: Exception | None = None
    for attempt in range(_CRTSH_ATTEMPTS):
        try:
            payload = await _get_json(
                session, _CRTSH_URL, {"q": f"%.{domain}", "output": "json"}
            )
            break
        except aiohttp.ClientResponseError as exc:
            # crt.sh 502s under load routinely and intermittently 404s a valid
            # query; a genuine empty result is a 200 with [], never a 404, so
            # both are transient. Any other 4xx is a real client error.
            if exc.status < 500 and exc.status != 404:
                raise
            last = exc
            logger.debug("crt.sh attempt %d failed: %s", attempt + 1, exc)
            await asyncio.sleep(_CRTSH_BACKOFF * (attempt + 1))
    else:
        raise OSINTError(f"crt.sh unreachable after {_CRTSH_ATTEMPTS} attempts: {last}")

    if not isinstance(payload, list):
        raise OSINTError("crt.sh returned an unexpected payload shape")

    found: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        # A single cert's name_value holds every SAN, newline-separated — and
        # those SANs routinely include unrelated domains sharing the cert, so
        # each one must be scope-checked individually.
        raw = f"{entry.get('name_value', '')}\n{entry.get('common_name', '')}"
        _collect(raw.splitlines(), domain, found)
    return found


async def _fetch_certspotter(session: aiohttp.ClientSession, domain: str) -> set[str]:
    """Fallback CT source for when crt.sh is down. Unauthenticated, rate-limited."""
    payload = await _get_json(
        session,
        _CERTSPOTTER_URL,
        {
            "domain": domain,
            "include_subdomains": "true",
            "expand": "dns_names",
        },
    )
    if not isinstance(payload, list):
        raise OSINTError("certspotter returned an unexpected payload shape")

    found: set[str] = set()
    for entry in payload:
        if isinstance(entry, dict):
            _collect(entry.get("dns_names"), domain, found)
    return found


async def _fetch_ct(domain: str, timeout_seconds: int) -> tuple[str, set[str]]:
    """Return (source_name, hosts) from Certificate Transparency logs.

    Tries crt.sh first and falls back to certspotter. Raises only if both fail.
    """
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    connector = get_aiohttp_connector()
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            return "crt.sh", await _fetch_crtsh(session, domain)
        except Exception as crtsh_exc:
            logger.warning("crt.sh failed for %s, trying certspotter: %s", domain, crtsh_exc)
            try:
                return "certspotter", await _fetch_certspotter(session, domain)
            except Exception as cs_exc:
                raise OSINTError(
                    f"crt.sh: {crtsh_exc} | certspotter: {cs_exc}"
                ) from cs_exc


async def _run_sublist3r(domain: str, timeout_seconds: int) -> set[str]:
    """Execute sublist3r against domain. Raises on missing binary or timeout."""
    result = await run_subprocess(
        binary=_BINARY,
        args=["-d", domain, "-n"],
        timeout_seconds=timeout_seconds,
        install_hint=_INSTALL_HINT,
        env=get_subprocess_env(),
    )
    found: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("["):
            continue
        host = _normalise(line, domain)
        if host:
            found.add(host)
    return found


def _describe(outcome: object) -> str:
    """Render one source's contribution for the status footer."""
    if isinstance(outcome, BaseException):
        return f"unavailable ({outcome})"
    if isinstance(outcome, set):
        return str(len(outcome))
    return str(outcome)


def _format_domain_results(
    domain: str,
    ct: tuple[str, set[str]] | BaseException,
    sublist3r: set[str] | BaseException,
) -> str:
    hosts: set[str] = set()

    if isinstance(ct, BaseException):
        ct_label = f"CT logs: {_describe(ct)}"
    else:
        ct_source, ct_hosts = ct
        hosts |= ct_hosts
        ct_label = f"{ct_source}: {len(ct_hosts)}"

    if not isinstance(sublist3r, BaseException):
        hosts |= sublist3r

    footer = f"Sources: {ct_label}, {_BINARY}: {_describe(sublist3r)}"
    if not hosts:
        return f"No subdomains found for '{domain}'.\n\n{footer}"

    listing = "\n".join(f"[+] {host}" for host in sorted(hosts))
    return f"Subdomains found for '{domain}' ({len(hosts)}):\n\n{listing}\n\n{footer}"


async def run_domain_osint(
    domain: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Enumerate subdomains of domain from Certificate Transparency and sublist3r.

    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    domain:
        Target domain (e.g. example.com).
    timeout_seconds:
        Maximum execution time for the sublist3r subprocess. The CT lookup is
        capped separately; the two sources run concurrently, so total wall time
        is the slower of the pair rather than their sum.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting domain enumeration for: %s", domain)
    try:
        ct, sublist3r = await asyncio.gather(
            _fetch_ct(domain, min(timeout_seconds, _CT_TIMEOUT)),
            _run_sublist3r(domain, timeout_seconds),
            return_exceptions=True,
        )
        if isinstance(ct, BaseException):
            logger.warning("CT lookup failed for %s: %s", domain, ct)
        if isinstance(sublist3r, BaseException):
            logger.warning("sublist3r failed for %s: %s", domain, sublist3r)

        result = _format_domain_results(domain, ct, sublist3r)
        logger.info("Domain enumeration complete for: %s", domain)
        return result
    except OSINTError as exc:
        logger.warning("Domain scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during domain scan.")
        return f"Internal error: {exc}"
