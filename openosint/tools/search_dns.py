# openosint/tools/search_dns.py
"""
DNS intelligence module.

Performs comprehensive DNS record enumeration (A, AAAA, MX, NS, TXT, CNAME, SOA)
using dnspython. Highlights email security misconfigurations: absent or permissive
SPF policy, missing or unenforced DMARC, and absent DKIM across common selectors.
No external API or credentials required.
"""

from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

import dns.exception
import dns.resolver

from openosint.tools.exceptions import OSINTError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10
_DKIM_SELECTORS = [
    "default",
    "google",
    "mail",
    "dkim",
    "s1",
    "s2",
    "selector1",
    "selector2",
    "k1",
]
# +all allows any sender (dangerous); ~all is a soft-fail (weak)
_WEAK_SPF_MECHANISMS = ("+all", "~all")


class RecordSet(NamedTuple):
    a: list[str]
    aaaa: list[str]
    mx: list[str]
    ns: list[str]
    txt: list[str]
    cname: list[str]
    soa: list[str]
    dmarc: list[str]
    dkim_found: list[str]


_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}


def _query(resolver: dns.resolver.Resolver, domain: str, rdtype: str) -> list[str]:
    try:
        return [str(r) for r in resolver.resolve(domain, rdtype)]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return []
    except dns.exception.Timeout:
        return []
    except Exception:
        return []


def _probe_dkim(resolver: dns.resolver.Resolver, domain: str) -> list[str]:
    found = []
    for selector in _DKIM_SELECTORS:
        try:
            answers = resolver.resolve(f"{selector}._domainkey.{domain}", "TXT")
            for r in answers:
                txt = str(r).strip('"')
                if any(tag in txt for tag in ("v=DKIM1", "k=rsa", "p=")):
                    found.append(f"{selector}: {txt[:80]}")
        except Exception:
            pass
    return found


def _analyze_spf(txt_records: list[str]) -> tuple[str | None, list[str]]:
    """Return (spf_record_or_None, list_of_warnings)."""
    spf = next(
        (r.strip('"') for r in txt_records if "v=spf1" in r.lower()),
        None,
    )
    if spf is None:
        return None, ["[!] No SPF record found — anyone can spoof email from this domain."]
    warnings = [
        f"[!] SPF uses {m} — emails may not be rejected by receivers."
        for m in _WEAK_SPF_MECHANISMS
        if m in spf
    ]
    return spf, warnings


def _analyze_dmarc(dmarc_records: list[str]) -> list[str]:
    if not dmarc_records:
        return ["[!] No DMARC policy found — no enforcement of SPF/DKIM failures."]
    dmarc = dmarc_records[0].strip('"')
    if "p=none" in dmarc:
        return ["[!] DMARC policy is p=none — monitoring only, no email rejection."]
    if "p=quarantine" in dmarc:
        return ["[~] DMARC policy is p=quarantine — suspicious mail goes to spam, not rejected."]
    return []


def compute_email_security_grade(rs: RecordSet, spf_warnings: list[str], dmarc_warnings: list[str]) -> tuple[str, list[str]]:
    """
    Return a simple A-F email-security grade plus the list of issues behind it.

    Heuristic, not a substitute for a full email security audit: missing SPF
    or DMARC caps the grade hardest, a weak/monitoring-only policy caps it
    less, and missing DKIM caps it moderately.
    """
    issues: list[str] = []
    grade = "A"

    def _cap(to: str) -> None:
        nonlocal grade
        if _GRADE_RANK[to] > _GRADE_RANK[grade]:
            grade = to

    has_spf = any("v=spf1" in r.lower() for r in rs.txt)
    if not has_spf:
        issues.append("No SPF record — anyone can spoof email from this domain.")
        _cap("F")
    elif spf_warnings:
        issues.append("SPF policy is weak (+all/~all) — spoofed mail may not be rejected by receivers.")
        _cap("C")

    if not rs.dmarc:
        issues.append("No DMARC policy — SPF/DKIM failures are not enforced.")
        _cap("D")
    else:
        dmarc = rs.dmarc[0].strip('"')
        if "p=none" in dmarc:
            issues.append("DMARC policy is p=none — monitoring only, no rejection.")
            _cap("C")
        elif "p=quarantine" in dmarc:
            issues.append("DMARC policy is p=quarantine — suspicious mail is quarantined, not rejected.")
            _cap("B")

    if not rs.dkim_found:
        issues.append("No DKIM record found for common selectors.")
        _cap("C")

    return grade, issues


async def collect_dns_records(domain: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> RecordSet:
    """
    Collect DNS records for domain as structured data.

    Raises
    ------
    OSINTError
        When domain is empty, doesn't exist, or the query times out.
    """
    domain = domain.strip().lower().rstrip(".")
    if not domain:
        raise OSINTError("domain cannot be empty.")

    resolver = dns.resolver.Resolver()
    resolver.timeout = min(timeout_seconds, 5)
    resolver.lifetime = float(timeout_seconds)

    try:
        resolver.resolve(domain, "A")
    except dns.resolver.NXDOMAIN as exc:
        raise OSINTError(f"Domain '{domain}' does not exist.") from exc
    except dns.exception.Timeout as exc:
        raise OSINTError(f"DNS query timed out after {timeout_seconds}s.") from exc
    except Exception:
        pass

    loop = asyncio.get_running_loop()

    def _collect() -> RecordSet:
        return RecordSet(
            a=_query(resolver, domain, "A"),
            aaaa=_query(resolver, domain, "AAAA"),
            mx=_query(resolver, domain, "MX"),
            ns=_query(resolver, domain, "NS"),
            txt=_query(resolver, domain, "TXT"),
            cname=_query(resolver, domain, "CNAME"),
            soa=_query(resolver, domain, "SOA"),
            dmarc=_query(resolver, f"_dmarc.{domain}", "TXT"),
            dkim_found=_probe_dkim(resolver, domain),
        )

    try:
        return await loop.run_in_executor(None, _collect)
    except dns.exception.Timeout as exc:
        raise OSINTError(f"DNS query timed out after {timeout_seconds}s.") from exc


def _build_output(domain: str, rs: RecordSet) -> str:
    lines: list[str] = [f"[DNS] Domain: {domain}"]

    for label, records in (
        ("A", rs.a),
        ("AAAA", rs.aaaa),
        ("CNAME", rs.cname),
        ("NS", rs.ns),
    ):
        if records:
            lines.append(f"[DNS] {label}: {', '.join(records)}")

    if rs.soa:
        lines.append(f"[DNS] SOA: {rs.soa[0]}")

    if rs.mx:
        lines.append("[DNS] MX records:")
        for rec in rs.mx:
            lines.append(f"  • {rec}")

    spf, spf_warnings = _analyze_spf(rs.txt)
    if spf:
        lines.append(f"[DNS] SPF: {spf[:120]}")
    lines.extend(spf_warnings)

    other_txt = [r for r in rs.txt if "v=spf1" not in r.lower()]
    if other_txt:
        lines.append("[DNS] TXT (other):")
        for rec in other_txt[:5]:
            lines.append(f"  • {rec[:100]}")

    dmarc_warnings = _analyze_dmarc(rs.dmarc)
    if rs.dmarc:
        lines.append(f"[DNS] DMARC: {rs.dmarc[0][:120]}")
    lines.extend(dmarc_warnings)

    if rs.dkim_found:
        lines.append("[DNS] DKIM selectors found:")
        for rec in rs.dkim_found:
            lines.append(f"  • {rec}")
    else:
        lines.append("[!] No DKIM records found for common selectors.")

    return "\n".join(lines)


async def run_dns_osint(domain: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> str:
    """Enumerate DNS records and highlight email security misconfigurations."""
    try:
        rs = await collect_dns_records(domain, timeout_seconds)
        return _build_output(domain.strip().lower().rstrip("."), rs)
    except OSINTError as exc:
        message = str(exc)
        if "does not exist" in message or "cannot be empty" in message:
            return message
        return f"Scan error: {message}"
    except Exception as exc:
        logger.exception("Unexpected error during DNS lookup.")
        return f"Internal error: {exc}"
