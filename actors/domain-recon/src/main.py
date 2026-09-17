"""OpenOSINT Domain Recon — Apify Actor.

Given one or more domains, reports DNS records, SPF/DMARC/DKIM email-security
posture (graded A-F), RDAP registration data (registrar/dates/nameservers/
status only — no registrant PII), and generated dork URLs. Monetized via
Apify pay-per-event: one charge per domain that produces a report, except a
confirmed-nonexistent domain (see domainExists below), which is reported but
not charged.

Uses RDAP (RFC 7482/9083) rather than legacy WHOIS: RDAP is structured JSON
(nothing prints a terms-of-service banner to stdout the way some WHOIS
servers' plain-text output does), and gTLD RDAP is required by ICANN policy
to redact registrant PII by default.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from apify import Actor

from openosint.tools.exceptions import OSINTError
from openosint.tools.generate_dorks import build_dork_urls
from openosint.tools.search_dns import analyze_email_security, collect_dns_records
from openosint.tools.search_rdap import fetch_rdap_bootstrap, fetch_rdap_data, parse_rdap_domain

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


async def build_domain_report(domain: str, rdap_bootstrap: dict | None) -> dict:
    """
    Build one domain report, degrading gracefully per data source.

    DNS and RDAP are fetched independently — an RDAP failure (unregistered
    domain, RDAP server down) does not prevent the DNS/email-security
    section of the report, and vice versa. Dork URL generation never fails.
    """
    warnings: list[str] = []
    domain_exists: bool | None = None
    report: dict = {
        "domain": domain,
        "domainExists": None,
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
        "dkimWildcard": False,
        "mailProfile": None,
        "emailSecurityGrade": None,
        "emailSecurityIssues": [],
        "rdapRegistrar": None,
        "rdapCreatedDate": None,
        "rdapExpiresDate": None,
        "rdapNameServers": [],
        "rdapStatus": [],
    }

    try:
        rs = await collect_dns_records(domain)
        domain_exists = bool(rs.ns) or bool(rs.soa)
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
            dkimWildcard=security["dkimWildcard"],
            mailProfile=security["mailProfile"],
            emailSecurityGrade=security["grade"],
            emailSecurityIssues=security["issues"],
        )
    except OSINTError as exc:
        if "does not exist" in str(exc):
            domain_exists = False
        warnings.append(f"DNS lookup failed: {type(exc).__name__}: {exc!r}")

    if rdap_bootstrap is None:
        warnings.append("RDAP lookup skipped: bootstrap registry unavailable this run.")
    else:
        try:
            rdap_data = await asyncio.to_thread(fetch_rdap_data, domain, rdap_bootstrap)
            parsed = parse_rdap_domain(rdap_data)
            report.update(
                rdapRegistrar=parsed["registrar"],
                rdapCreatedDate=parsed["createdDate"],
                rdapExpiresDate=parsed["expiresDate"],
                rdapNameServers=parsed["nameServers"],
                rdapStatus=parsed["status"],
            )
        except OSINTError as exc:
            if domain_exists is None and "not registered" in str(exc):
                domain_exists = False
            warnings.append(f"RDAP lookup failed: {type(exc).__name__}: {exc!r}")

    report["domainExists"] = domain_exists
    report["dorkUrls"] = build_dork_urls(domain)
    report["warnings"] = warnings
    return report


async def build_report_with_retry(domain: str, rdap_bootstrap: dict | None) -> dict | None:
    """Build a domain report, retrying transient failures with backoff.

    Returns None only if the whole pipeline (DNS + RDAP both unreachable)
    fails on every attempt — a single failing domain must not fail the run.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            report = await asyncio.wait_for(
                build_domain_report(domain, rdap_bootstrap), timeout=_PER_DOMAIN_TIMEOUT_SECONDS
            )
            # Both data sources failed — treat as a transient failure worth retrying,
            # unless we've already positively confirmed the domain doesn't exist
            # (retrying won't change that, and it's still a genuine finding).
            if len(report["warnings"]) >= 2 and report["domainExists"] is not False and attempt < _MAX_ATTEMPTS - 1:
                Actor.log.warning(f"{domain}: both DNS and RDAP failed on attempt {attempt + 1}; retrying")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            return report
        except asyncio.TimeoutError as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                Actor.log.warning(f"{domain}: attempt {attempt + 1} timed out; retrying")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    Actor.log.warning(
        f"{domain}: report failed after {_MAX_ATTEMPTS} attempt(s): "
        f"{type(last_exc).__name__ if last_exc else 'unknown'}: {last_exc!r}"
    )
    return None


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        raw_domains = actor_input.get("domains") or []

        if not raw_domains:
            await Actor.fail(status_message="No domains provided in input.")
            return

        valid_domains, rejected_domains = validate_domains(raw_domains)

        if rejected_domains:
            Actor.log.warning(
                f"Skipping {len(rejected_domains)} malformed domain(s): {', '.join(rejected_domains)}"
            )

        if not valid_domains:
            await Actor.fail(status_message="No valid domains left after validation.")
            return

        if len(valid_domains) > MAX_DOMAINS_PER_RUN:
            await Actor.fail(
                status_message=(
                    f"{len(valid_domains)} valid domain(s) provided, but the limit is "
                    f"{MAX_DOMAINS_PER_RUN} per run. Split this into multiple runs."
                )
            )
            return

        try:
            rdap_bootstrap = await asyncio.to_thread(fetch_rdap_bootstrap)
        except OSINTError as exc:
            Actor.log.warning(f"RDAP bootstrap registry unavailable — reports will be DNS-only: {exc!r}")
            rdap_bootstrap = None

        Actor.log.info(f"Scanning {len(valid_domains)} domain(s).")

        total_reported = 0
        nonexistent_count = 0
        failed_domains: list[str] = []
        limit_reached = False

        for domain in valid_domains:
            if limit_reached:
                break

            report = await build_report_with_retry(domain, rdap_bootstrap)
            if report is None:
                failed_domains.append(domain)
                continue

            report["checkedAt"] = datetime.now(timezone.utc).isoformat()

            if report["domainExists"] is False:
                # A confirmed-nonexistent domain is still a real finding worth
                # reporting, but not something to charge for.
                await Actor.push_data(report)
                nonexistent_count += 1
            else:
                charge_result = await Actor.push_data(report, charged_event_name=EVENT_DOMAIN_REPORT)
                total_reported += 1
                if charge_result.event_charge_limit_reached:
                    Actor.log.info("Charge limit reached — stopping.")
                    limit_reached = True

            if report["warnings"]:
                Actor.log.warning(f"{domain}: partial report — {'; '.join(report['warnings'])}")

        if total_reported == 0 and nonexistent_count == 0:
            await Actor.fail(
                status_message=f"All {len(valid_domains)} domain(s) failed to produce a report."
            )
            return

        status = (
            f"{total_reported} domain report(s) produced, {nonexistent_count} confirmed nonexistent "
            f"(not charged), out of {len(valid_domains)} domain(s) requested"
        )
        if failed_domains:
            status += f"; {len(failed_domains)} failed: {', '.join(failed_domains)}"
        Actor.log.info(status)
        await Actor.set_status_message(status, is_terminal=not limit_reached)
