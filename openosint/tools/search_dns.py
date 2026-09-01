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


class _RecordSet(NamedTuple):
    a: list[str]
    aaaa: list[str]
    mx: list[str]
    ns: list[str]
    txt: list[str]
    cname: list[str]
    soa: list[str]
    dmarc: list[str]
    dkim_found: list[str]
    failed: frozenset[str]


def _query(
    resolver: dns.resolver.Resolver,
    domain: str,
    rdtype: str,
    failed: set[str] | None = None,
    key: str | None = None,
) -> list[str]:
    """Resolve one record type.

    An empty list means "this record type does not exist" ONLY when the server
    actually said so (NXDOMAIN/NoAnswer). A lookup that failed for any other
    reason is registered in `failed` so callers can distinguish "absent" from
    "unknown" — reporting a failed lookup as an absent record produces
    confident, wrong findings.
    """
    marker = key or rdtype

    try:
        # Call signature deliberately unchanged from the plain UDP path; the
        # tcp= kwarg is only introduced on retry so resolver doubles that take
        # just (qname, rdtype) still work.
        return [str(r) for r in resolver.resolve(domain, rdtype)]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
        # A large TXT set can exceed the UDP payload some local resolvers will
        # return, which surfaces as a timeout rather than truncation. Retry
        # over TCP before concluding anything.
        try:
            return [str(r) for r in resolver.resolve(domain, rdtype, tcp=True)]
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except Exception:
            if failed is not None:
                failed.add(marker)
            return []
    except Exception:
        if failed is not None:
            failed.add(marker)
        return []


def _probe_dkim(
    resolver: dns.resolver.Resolver, domain: str, failed: set[str] | None = None
) -> list[str]:
    found = []
    errors = 0
    for selector in _DKIM_SELECTORS:
        try:
            answers = resolver.resolve(f"{selector}._domainkey.{domain}", "TXT")
            for r in answers:
                txt = str(r).strip('"')
                if any(tag in txt for tag in ("v=DKIM1", "k=rsa", "p=")):
                    found.append(f"{selector}: {txt[:80]}")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            continue  # this selector genuinely isn't published
        except Exception:
            errors += 1
    # Every probe erroring out is a resolver problem, not an absence of DKIM.
    if not found and errors == len(_DKIM_SELECTORS) and failed is not None:
        failed.add("DKIM")
    return found


def _analyze_spf(
    txt_records: list[str], lookup_failed: bool = False
) -> tuple[str | None, list[str]]:
    """Return (spf_record_or_None, list_of_warnings)."""
    spf = next(
        (r.strip('"') for r in txt_records if "v=spf1" in r.lower()),
        None,
    )
    if spf is None:
        if lookup_failed:
            return None, [
                "[?] SPF undetermined — the TXT lookup failed. This is NOT evidence "
                "that the domain lacks SPF; re-run against a different resolver."
            ]
        return None, ["[!] No SPF record found — anyone can spoof email from this domain."]
    warnings = [
        f"[!] SPF uses {m} — emails may not be rejected by receivers."
        for m in _WEAK_SPF_MECHANISMS
        if m in spf
    ]
    return spf, warnings


def _parse_dmarc_tags(record: str) -> dict[str, str]:
    """Split a DMARC record into its tag=value pairs, lowercased."""
    tags: dict[str, str] = {}
    for part in record.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            tags[key.strip().lower()] = value.strip().lower()
    return tags


def _analyze_dmarc(dmarc_records: list[str], lookup_failed: bool = False) -> list[str]:
    if not dmarc_records:
        if lookup_failed:
            return ["[?] DMARC undetermined — the _dmarc TXT lookup failed."]
        return ["[!] No DMARC policy found — no enforcement of SPF/DKIM failures."]

    # Tag-parsed, not substring-matched: 'sp=none' contains 'p=none', so a
    # naive `"p=none" in record` check reports a p=reject domain as p=none —
    # inverting the finding from strongest policy to weakest.
    tags = _parse_dmarc_tags(dmarc_records[0].strip('"'))
    policy = tags.get("p", "")
    subdomain_policy = tags.get("sp")

    findings: list[str] = []
    if policy == "none":
        findings.append("[!] DMARC policy is p=none — monitoring only, no email rejection.")
    elif policy == "quarantine":
        findings.append("[~] DMARC policy is p=quarantine — suspicious mail goes to spam, not rejected.")
    elif policy == "reject":
        findings.append("[+] DMARC policy is p=reject — strongest enforcement.")
    elif policy:
        findings.append(f"[?] DMARC policy is p={policy} — unrecognised value.")
    else:
        findings.append("[!] DMARC record present but has no p= policy tag — treated as no policy.")

    if subdomain_policy == "none" and policy in ("quarantine", "reject"):
        findings.append(
            f"[~] DMARC sp=none — subdomains are unprotected despite p={policy}; "
            "a lookalike subdomain can still be spoofed."
        )
    return findings


def _build_output(domain: str, rs: _RecordSet) -> str:
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

    spf, spf_warnings = _analyze_spf(rs.txt, "TXT" in rs.failed)
    if spf:
        lines.append(f"[DNS] SPF: {spf[:120]}")
    lines.extend(spf_warnings)

    other_txt = [r for r in rs.txt if "v=spf1" not in r.lower()]
    if other_txt:
        lines.append("[DNS] TXT (other):")
        for rec in other_txt[:5]:
            lines.append(f"  • {rec[:100]}")

    dmarc_warnings = _analyze_dmarc(rs.dmarc, "DMARC" in rs.failed)
    if rs.dmarc:
        lines.append(f"[DNS] DMARC: {rs.dmarc[0][:120]}")
    lines.extend(dmarc_warnings)

    if rs.dkim_found:
        lines.append("[DNS] DKIM selectors found:")
        for rec in rs.dkim_found:
            lines.append(f"  • {rec}")
    elif "DKIM" in rs.failed:
        lines.append("[?] DKIM undetermined — selector probes failed to resolve.")
    else:
        lines.append("[!] No DKIM records found for common selectors.")

    if rs.failed:
        lines.append(
            f"[?] Lookups that FAILED (result unknown, not absent): {', '.join(sorted(rs.failed))}"
        )

    return "\n".join(lines)


async def run_dns_osint(domain: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> str:
    """Enumerate DNS records and highlight email security misconfigurations."""
    domain = domain.strip().lower().rstrip(".")
    if not domain:
        return "Error: domain cannot be empty."

    resolver = dns.resolver.Resolver()
    resolver.timeout = min(timeout_seconds, 5)
    resolver.lifetime = float(timeout_seconds)

    try:
        # NXDOMAIN probe
        try:
            resolver.resolve(domain, "A")
        except dns.resolver.NXDOMAIN:
            return f"Domain '{domain}' does not exist."
        except dns.exception.Timeout:
            raise
        except Exception:
            pass

        loop = asyncio.get_running_loop()

        def _collect() -> _RecordSet:
            failed: set[str] = set()
            return _RecordSet(
                a=_query(resolver, domain, "A", failed),
                aaaa=_query(resolver, domain, "AAAA", failed),
                mx=_query(resolver, domain, "MX", failed),
                ns=_query(resolver, domain, "NS", failed),
                txt=_query(resolver, domain, "TXT", failed),
                cname=_query(resolver, domain, "CNAME", failed),
                soa=_query(resolver, domain, "SOA", failed),
                dmarc=_query(resolver, f"_dmarc.{domain}", "TXT", failed, key="DMARC"),
                dkim_found=_probe_dkim(resolver, domain, failed),
                failed=frozenset(failed),
            )

        rs = await loop.run_in_executor(None, _collect)
        return _build_output(domain, rs)

    except dns.exception.Timeout:
        return f"Scan error: DNS query timed out after {timeout_seconds}s."
    except Exception as exc:
        logger.exception("Unexpected error during DNS lookup.")
        return f"Internal error: {exc}"
