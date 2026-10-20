"""Domain registration via RDAP: age, expiry, registrar, DNSSEC. Queries the registry, not the target."""

from __future__ import annotations

from datetime import datetime, timezone

from openosint.exposure.models import (
    STATUS_OK,
    CheckResult,
    CheckSkipped,
    DomainNotRegistered,
    Passed,
    data,
)
from openosint.exposure.scoring import ev, finding
from openosint.tool_policy import Noise
from openosint.tools.search_rdap import (
    RDAPNotFound,
    fetch_rdap_bootstrap,
    fetch_rdap_data,
    parse_rdap_domain,
)

CAT = "registration"
TIMEOUT = 10
DAYS_PER_YEAR = 365.25


def _bootstrap() -> dict:
    return fetch_rdap_bootstrap(TIMEOUT)


def _rdap(domain: str, bootstrap: dict) -> dict:
    return fetch_rdap_data(domain, bootstrap, TIMEOUT)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def run(host: str, registrable: str) -> CheckResult:
    domain = registrable  # RDAP only knows registrable domains
    bootstrap = _bootstrap()
    if domain.rsplit(".", 1)[-1] not in bootstrap:  # e.g. .it: no RDAP service, not a failure
        raise CheckSkipped("no RDAP service for TLD", "no_rdap_for_tld")
    try:
        raw = _rdap(domain, bootstrap)
    except RDAPNotFound as exc:
        raise DomainNotRegistered(f"{domain} is not registered (RDAP 404); no meaningful report.") from exc
    info = parse_rdap_domain(raw)
    now = datetime.now(timezone.utc)
    findings, passed = [], []
    registrar = info["registrar"]

    created, expires = _parse_date(info["createdDate"]), _parse_date(info["expiresDate"])
    if created:
        years = (now - created).days / DAYS_PER_YEAR
        findings.append(finding("domain_age", CAT, f"Domain registered {years:.1f} years ago",
                                f"registrable domain {domain} (input {host}); created {created.date()}; registrar {info['registrar'] or 'unknown'}",
                                "No action needed; age is context only."))
        passed.append(Passed("domain_registered_on", data(date=created.date(), age_months=int(years * 12))))
    if expires:
        days = (expires - now).days
        evidence = f"expires {expires.date()} ({days} days left); registrar {info['registrar'] or 'unknown'}"
        expiry_ev = ev("domain_expiry", date=expires.date(), days=days, registrar=registrar)
        if days < 0:
            findings.append(finding("domain_expired", CAT, "Domain registration has expired", evidence,
                                    "Renew the domain immediately; it may be released or hijacked.", ev=expiry_ev))
        elif days < 30:
            findings.append(finding("domain_expires_lt_30d", CAT, "Domain expires in under 30 days", evidence,
                                    "Renew the domain now and enable auto-renewal.", days, ev=expiry_ev))
        elif days < 60:
            findings.append(finding("domain_expires_lt_60d", CAT, "Domain expires in under 60 days", evidence,
                                    "Renew the domain and enable auto-renewal.", days, ev=expiry_ev))
        else:
            passed.append(Passed("domain_registered", data(registrar=registrar, date=expires.date(), days=days)))
    secure = raw.get("secureDNS") or {}
    if not secure.get("delegationSigned"):
        findings.append(finding("dnssec_not_enabled", CAT, "DNSSEC is not enabled",
                                "DNSSEC: not signed" if secure else "DNSSEC: not reported by the registry",
                                "Enable DNSSEC at the registrar if the DNS provider supports it.",
                                ev=ev("dnssec_unsigned" if secure else "dnssec_not_reported")))
    else:
        passed.append(Passed("dnssec_signed"))
    return CheckResult("registration", STATUS_OK, Noise.PASSIVE.value, findings=tuple(findings), passed=tuple(passed))
