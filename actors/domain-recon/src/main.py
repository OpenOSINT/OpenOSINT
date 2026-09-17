"""OpenOSINT Domain Recon — Apify Actor.

Given one or more domains, reports DNS records, SPF/DMARC/DKIM email-security
posture (graded A-F), WHOIS registration data (registrar/dates/nameservers
only — no registrant PII), and generated dork URLs. Monetized via Apify
pay-per-event: one charge per domain that produces a report.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from apify import Actor

from openosint.tools.exceptions import OSINTError
from openosint.tools.generate_dorks import build_dork_urls
from openosint.tools.search_dns import analyze_email_security, collect_dns_records
from openosint.tools.search_whois import fetch_whois_data

# Event name — this MUST match exactly what you configure in the Apify
# Console under Publication > Monetization.
EVENT_DOMAIN_REPORT = "domain-report"

MAX_DOMAINS_PER_RUN = 50
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_PER_DOMAIN_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 5


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower().rstrip(".")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def validate_domains(raw: list) -> tuple[list[str], list[str]]:
    """Dedupe and split raw input into (valid, rejected) domains."""
    deduped = _dedupe_preserve_order([str(d) for d in raw])
    valid, rejected = [], []
    for domain in deduped:
        if _DOMAIN_RE.match(domain):
            valid.append(domain)
        else:
            rejected.append(domain)
    return valid, rejected


def _iso(value) -> str | None:
    """Serialize a python-whois date field (datetime, list of datetime, or None) to ISO 8601."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


async def build_domain_report(domain: str) -> dict:
    """
    Build one domain report, degrading gracefully per data source.

    DNS and WHOIS are fetched independently — a WHOIS failure (unregistered
    domain, WHOIS server down) does not prevent the DNS/email-security
    section of the report, and vice versa. Dork URL generation never fails.
    """
    warnings: list[str] = []
    report: dict = {
        "domain": domain,
        "dnsA": [],
        "dnsAaaa": [],
        "dnsMx": [],
        "dnsNs": [],
        "dnsTxt": [],
        "dnsCname": [],
        "dnsSoa": [],
        "spfRecord": None,
        "dmarcRecord": None,
        "dkimSelectorsFound": [],
        "emailSecurityGrade": None,
        "emailSecurityIssues": [],
        "whoisRegistrar": None,
        "whoisCreatedDate": None,
        "whoisExpiresDate": None,
        "whoisNameServers": [],
    }

    try:
        rs = await collect_dns_records(domain)
        report.update(
            dnsA=rs.a,
            dnsAaaa=rs.aaaa,
            dnsMx=rs.mx,
            dnsNs=rs.ns,
            dnsTxt=rs.txt,
            dnsCname=rs.cname,
            dnsSoa=rs.soa,
        )
        security = analyze_email_security(rs)
        report.update(
            spfRecord=security["spf"],
            dmarcRecord=security["dmarc"],
            dkimSelectorsFound=security["dkimSelectorsFound"],
            emailSecurityGrade=security["grade"],
            emailSecurityIssues=security["issues"],
        )
    except OSINTError as exc:
        warnings.append(f"DNS lookup failed: {exc}")

    try:
        whois_data = await asyncio.to_thread(fetch_whois_data, domain)
        report.update(
            whoisRegistrar=getattr(whois_data, "registrar", None),
            whoisCreatedDate=_iso(getattr(whois_data, "creation_date", None)),
            whoisExpiresDate=_iso(getattr(whois_data, "expiration_date", None)),
            whoisNameServers=_as_list(getattr(whois_data, "name_servers", None)),
        )
    except OSINTError as exc:
        warnings.append(f"WHOIS lookup failed: {exc}")

    report["dorkUrls"] = build_dork_urls(domain)
    report["warnings"] = warnings
    return report


async def build_report_with_retry(domain: str) -> dict | None:
    """Build a domain report, retrying transient failures with backoff.

    Returns None only if the whole pipeline (DNS + WHOIS both unreachable)
    fails on every attempt — a single failing domain must not fail the run.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            report = await asyncio.wait_for(
                build_domain_report(domain), timeout=_PER_DOMAIN_TIMEOUT_SECONDS
            )
            # Both data sources failed — treat as a transient failure worth retrying.
            if len(report["warnings"]) >= 2 and attempt < _MAX_ATTEMPTS - 1:
                Actor.log.warning(f"{domain}: both DNS and WHOIS failed on attempt {attempt + 1}; retrying")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            return report
        except asyncio.TimeoutError as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                Actor.log.warning(f"{domain}: attempt {attempt + 1} timed out; retrying")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    Actor.log.warning(f"{domain}: report failed after {_MAX_ATTEMPTS} attempt(s): {last_exc}")
    return None


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        raw_domains = actor_input.get("domains") or []

        if not raw_domains:
            Actor.log.error("No domains provided in input.")
            return

        valid_domains, rejected_domains = validate_domains(raw_domains)

        if rejected_domains:
            Actor.log.warning(
                f"Skipping {len(rejected_domains)} malformed domain(s): {', '.join(rejected_domains)}"
            )

        if not valid_domains:
            Actor.log.error("No valid domains left after validation.")
            return

        if len(valid_domains) > MAX_DOMAINS_PER_RUN:
            Actor.log.error(
                f"{len(valid_domains)} valid domain(s) provided, but the limit is "
                f"{MAX_DOMAINS_PER_RUN} per run. Split this into multiple runs."
            )
            return

        Actor.log.info(f"Scanning {len(valid_domains)} domain(s).")

        total_reported = 0
        limit_reached = False

        for domain in valid_domains:
            if limit_reached:
                break

            report = await build_report_with_retry(domain)
            if report is None:
                continue

            report["checkedAt"] = datetime.now(timezone.utc).isoformat()
            charge_result = await Actor.push_data(report, charged_event_name=EVENT_DOMAIN_REPORT)
            total_reported += 1

            if report["warnings"]:
                Actor.log.warning(f"{domain}: partial report — {'; '.join(report['warnings'])}")

            if charge_result.event_charge_limit_reached:
                Actor.log.info("Charge limit reached — stopping.")
                limit_reached = True

        status = f"{total_reported} domain report(s) produced out of {len(valid_domains)} domain(s) requested"
        Actor.log.info(status)
        await Actor.set_status_message(status, is_terminal=not limit_reached)
