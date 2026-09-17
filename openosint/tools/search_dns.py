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
import re
import secrets
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
    dkim_wildcard: bool = False


_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}

# Documented rubric behind compute_email_security_grade() below — kept as a
# single source of truth; actors/domain-recon/README.md carries a copy of
# this same table for end users and must be kept in sync with it by hand.
GRADING_RUBRIC = """
Email-security grade (A-F). Starting grade is A; each issue below caps the
grade at its listed ceiling, and the WORST ceiling wins (rank A < B < C < D < F).

SPF
  - No SPF record at all                          -> caps at F
  - SPF present but weak (+all or ~all)           -> caps at C
  - SPF present and strict (-all)                 -> no cap

DMARC
  - No DMARC record at all                        -> caps at D
  - DMARC p=none (monitor only, no enforcement)   -> caps at C
  - DMARC p=quarantine (suspicious mail spammed)  -> caps at B
  - DMARC p=reject (enforced)                     -> no cap

DKIM — skipped entirely for a confirmed non-mail domain (mailProfile
"no-mail": RFC 7505 null MX, or no MX record at all, combined with an SPF
record that is "-all" with no mechanism authorizing any sender). Such a
domain cannot send mail, so it has nothing for DKIM to sign.
  - DKIM answers ANY selector (wildcard DNS)      -> caps at C (unverifiable)
  - No DKIM record for any common selector        -> caps at C
  - A real DKIM record found for at least one selector -> no cap

A domain reaches grade A only when every check that applies to it (DKIM is
skipped for "no-mail" domains) passes with no cap.
"""


def _query(resolver: dns.resolver.Resolver, domain: str, rdtype: str) -> list[str]:
    try:
        return [str(r) for r in resolver.resolve(domain, rdtype)]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return []
    except dns.exception.Timeout:
        return []
    except Exception:
        return []


_EMPTY_DKIM_KEY_RE = re.compile(r"p=\s*(;|$)")


def _is_valid_dkim_record(txt: str) -> bool:
    """
    A DKIM-looking TXT record with an empty p= tag is a revoked/placeholder
    key (RFC 6376 4.1: "if the value is empty, this key is revoked"), not a
    real one — it must not count as DKIM being configured.
    """
    if not any(tag in txt for tag in ("v=DKIM1", "k=rsa", "p=")):
        return False
    return not _EMPTY_DKIM_KEY_RE.search(txt)


def _probe_dkim(resolver: dns.resolver.Resolver, domain: str) -> tuple[list[str], bool]:
    """
    Probe common DKIM selectors, returning (selectors_found, wildcard_detected).

    Some domains answer *any* _domainkey subdomain with a DKIM-looking TXT
    record (wildcard DNS, or a catch-all/parking page) — confirmed via
    `dig TXT <random>._domainkey.<domain>`. When that's the case, every
    "common selector" would falsely look present, so this probes one random
    selector first: if it answers, real selector matches are meaningless and
    none are reported.
    """
    probe_selector = f"zzprobe{secrets.token_hex(6)}"
    try:
        answers = resolver.resolve(f"{probe_selector}._domainkey.{domain}", "TXT")
        if any(_is_valid_dkim_record(str(r).strip('"')) for r in answers):
            return [], True
    except Exception:
        pass

    found = []
    for selector in _DKIM_SELECTORS:
        try:
            answers = resolver.resolve(f"{selector}._domainkey.{domain}", "TXT")
            for r in answers:
                txt = str(r).strip('"')
                if _is_valid_dkim_record(txt):
                    found.append(f"{selector}: {txt[:80]}")
        except Exception:
            pass
    return found, False


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


_SPF_AUTHORIZING_MECHANISMS = {"a", "mx", "ip4", "ip6", "include", "exists", "ptr"}


def _is_null_mx(mx_records: list[str]) -> bool:
    """RFC 7505: a single MX record '0 .' declares the domain sends/receives no mail."""
    if len(mx_records) != 1:
        return False
    parts = mx_records[0].split()
    return len(parts) == 2 and parts[0] == "0" and parts[1] == "."


def _spf_authorizes_senders(spf: str) -> bool:
    """True if spf has any mechanism (a/mx/ip4/ip6/include/exists/ptr) that could authorize a sender."""
    for token in spf.split()[1:]:  # drop the leading "v=spf1"
        mechanism = token.lstrip("+-~?").split(":", 1)[0].split("/", 1)[0].lower()
        if mechanism in _SPF_AUTHORIZING_MECHANISMS:
            return True
    return False


def compute_mail_profile(rs: RecordSet, spf: str | None) -> str:
    """
    Classify a domain as "no-mail", "sending", or "unknown".

    "no-mail": RFC 7505 null MX (or no MX at all) combined with an SPF
    record that is strict ("-all") and authorizes no sender — this domain
    provably neither sends nor receives mail, so it has no need for DKIM.
    "sending": a real (non-null) MX record is present.
    "unknown": neither signal is conclusive — graded as if mail could flow,
    so DKIM absence still caps the grade.
    """
    if rs.mx and not _is_null_mx(rs.mx):
        return "sending"
    is_null_or_no_mx = not rs.mx or _is_null_mx(rs.mx)
    if is_null_or_no_mx and spf and "-all" in spf and not _spf_authorizes_senders(spf):
        return "no-mail"
    return "unknown"


def analyze_email_security(rs: RecordSet) -> dict:
    """
    Analyze SPF/DMARC/DKIM posture for a RecordSet and grade it A-F.

    Returns a dict with spf, dmarc (raw record strings, or None), the list of
    DKIM selectors found, the `mailProfile` classification, an overall
    `grade`, and the `issues` behind it.
    """
    spf, spf_warnings = _analyze_spf(rs.txt)
    dmarc_warnings = _analyze_dmarc(rs.dmarc)
    mail_profile = compute_mail_profile(rs, spf)
    grade, issues = compute_email_security_grade(rs, spf_warnings, dmarc_warnings, mail_profile=mail_profile)
    return {
        "spf": spf,
        "dmarc": rs.dmarc[0].strip('"') if rs.dmarc else None,
        "dkimSelectorsFound": rs.dkim_found,
        "dkimWildcard": rs.dkim_wildcard,
        "mailProfile": mail_profile,
        "grade": grade,
        "issues": issues,
    }


def compute_email_security_grade(
    rs: RecordSet,
    spf_warnings: list[str],
    dmarc_warnings: list[str],
    mail_profile: str = "unknown",
) -> tuple[str, list[str]]:
    """
    Return a simple A-F email-security grade plus the list of issues behind it.

    See GRADING_RUBRIC above for the full rubric. Heuristic, not a substitute
    for a full email security audit: missing SPF or DMARC caps the grade
    hardest, a weak/monitoring-only policy caps it less, and missing DKIM
    caps it moderately — except for a confirmed "no-mail" domain
    (mail_profile == "no-mail"), which is graded on SPF+DMARC alone since it
    has no need for DKIM.
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

    if mail_profile != "no-mail":
        if rs.dkim_wildcard:
            issues.append(
                "DKIM cannot be verified — this domain's DNS answers any selector "
                "(wildcard), so real key presence is unknown."
            )
            _cap("C")
        elif not rs.dkim_found:
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
        dkim_found, dkim_wildcard = _probe_dkim(resolver, domain)
        return RecordSet(
            a=_query(resolver, domain, "A"),
            aaaa=_query(resolver, domain, "AAAA"),
            mx=_query(resolver, domain, "MX"),
            ns=_query(resolver, domain, "NS"),
            txt=_query(resolver, domain, "TXT"),
            cname=_query(resolver, domain, "CNAME"),
            soa=_query(resolver, domain, "SOA"),
            dmarc=_query(resolver, f"_dmarc.{domain}", "TXT"),
            dkim_found=dkim_found,
            dkim_wildcard=dkim_wildcard,
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

    if rs.dkim_wildcard:
        lines.append("[!] DKIM cannot be verified — this domain answers ANY selector (wildcard DNS).")
    elif rs.dkim_found:
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
