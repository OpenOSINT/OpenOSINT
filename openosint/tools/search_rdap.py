"""RDAP (Registration Data Access Protocol) domain lookup module.

RFC 7482/9083 replacement for legacy WHOIS. Returns structured data only —
registrar, registration/expiry dates, name servers, and status codes — never
registrant contact details. Used instead of WHOIS by the domain-recon Actor
because RDAP responses are machine-readable JSON (no banner text printed to
stdout) and gTLD RDAP is required by ICANN policy to redact registrant PII
by default, avoiding the redistribution restrictions some WHOIS servers'
terms impose on their plain-text output.

Kept separate from search_whois.py: RDAP and WHOIS are different protocols
with different response shapes, so there's no meaningful logic to share.
"""

from __future__ import annotations

import logging
import time

import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_IANA_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_BOOTSTRAP_CACHE_TTL_SECONDS = 3600
_DEFAULT_TIMEOUT = 10

# ponytail: process-local dict, single-worker assumption — same tradeoff as
# search_gdelt_geo.py's cache. Fine for one Actor run; revisit if this ever
# runs behind multiple long-lived worker processes.
_bootstrap_cache: dict[str, tuple[float, dict[str, list[str]]]] = {}


def fetch_rdap_bootstrap(timeout_seconds: int = _DEFAULT_TIMEOUT) -> dict[str, list[str]]:
    """
    Fetch (or return cached) the IANA RDAP bootstrap registry: {tld: [rdap_base_urls]}.

    Call once per batch of domains and reuse the result — this is a single
    JSON file covering every TLD, not something to refetch per domain.

    Raises
    ------
    OSINTError
        On network failure or timeout.
    ToolExecutionError
        On a non-200 status or a malformed response body.
    """
    cached = _bootstrap_cache.get("data")
    if cached and time.monotonic() - cached[0] < _BOOTSTRAP_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        response = requests.get(_IANA_BOOTSTRAP_URL, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise OSINTError(f"Failed to fetch IANA RDAP bootstrap registry: {exc}") from exc

    if response.status_code != 200:
        raise ToolExecutionError(f"IANA RDAP bootstrap registry returned HTTP {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise ToolExecutionError("IANA RDAP bootstrap registry returned malformed JSON.") from exc

    mapping: dict[str, list[str]] = {}
    for entry in data.get("services", []):
        if len(entry) < 2:
            continue
        tlds, urls = entry[0], entry[1]
        for tld in tlds:
            mapping[tld.lower()] = urls

    _bootstrap_cache["data"] = (time.monotonic(), mapping)
    return mapping


def _rdap_base_urls_for_domain(domain: str, bootstrap: dict[str, list[str]]) -> list[str]:
    tld = domain.rsplit(".", 1)[-1].lower()
    urls = bootstrap.get(tld)
    if not urls:
        raise OSINTError(f"No RDAP server found for TLD '.{tld}' in the IANA bootstrap registry.")
    return urls


def fetch_rdap_data(domain: str, bootstrap: dict[str, list[str]], timeout_seconds: int = _DEFAULT_TIMEOUT) -> dict:
    """
    Query RDAP for domain, returning the raw RDAP JSON response.

    Raises
    ------
    OSINTError
        When the domain isn't registered (RDAP 404) or its TLD has no known
        RDAP server.
    ToolExecutionError
        On other HTTP failures or a malformed response body from every
        candidate RDAP server for this TLD.
    """
    base_urls = _rdap_base_urls_for_domain(domain, bootstrap)

    last_exc: Exception = ToolExecutionError(f"RDAP lookup failed for '{domain}'.")
    for base_url in base_urls:
        url = f"{base_url.rstrip('/')}/domain/{domain}"
        try:
            response = requests.get(url, timeout=timeout_seconds, headers={"Accept": "application/rdap+json"})
        except requests.RequestException as exc:
            last_exc = OSINTError(f"Network error querying RDAP for '{domain}': {exc}")
            continue

        if response.status_code == 404:
            raise OSINTError(f"Domain '{domain}' is not registered (RDAP 404).")
        if response.status_code != 200:
            last_exc = ToolExecutionError(f"RDAP server returned HTTP {response.status_code} for '{domain}'.")
            continue

        try:
            return response.json()
        except ValueError:
            last_exc = ToolExecutionError(f"RDAP server returned malformed JSON for '{domain}'.")
            continue

    raise last_exc


def _extract_registrar(rdap_data: dict) -> str | None:
    for entity in rdap_data.get("entities", []):
        if "registrar" not in entity.get("roles", []):
            continue
        vcard = entity.get("vcardArray")
        if vcard and len(vcard) > 1:
            for field in vcard[1]:
                if field[0] == "fn" and len(field) > 3:
                    return field[3]
        if entity.get("handle"):
            return entity["handle"]
    return None


def _extract_event_date(rdap_data: dict, action: str) -> str | None:
    for event in rdap_data.get("events", []):
        if event.get("eventAction") == action:
            return event.get("eventDate")
    return None


def parse_rdap_domain(rdap_data: dict) -> dict:
    """
    Extract only registrar, created/expiry dates, name servers, and status
    from a raw RDAP response. No registrant/contact fields are read at all —
    not filtered out after the fact, simply never extracted.
    """
    return {
        "registrar": _extract_registrar(rdap_data),
        "createdDate": _extract_event_date(rdap_data, "registration"),
        "expiresDate": _extract_event_date(rdap_data, "expiration"),
        "nameServers": sorted(
            {ns.get("ldhName", "").lower() for ns in rdap_data.get("nameservers", []) if ns.get("ldhName")}
        ),
        "status": rdap_data.get("status", []),
    }
