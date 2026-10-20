"""Email security: MX, SPF, DMARC and best-effort DKIM. DNS only."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from secrets import token_hex

import dns.exception
import dns.resolver

from openosint.exposure import dns_auth
from openosint.exposure.dns_auth import SRC_FALLBACK, AuthZone, DnsConfig
from openosint.exposure.models import STATUS_OK, CheckError, CheckResult, Passed, data
from openosint.exposure.scoring import ev, finding
from openosint.tool_policy import Noise
from openosint.tools.search_dns import DKIM_SELECTORS, is_valid_dkim_record

CAT = "email"
# Explicit resolver limits (timeout and lifetime are always set together, in dns_auth.recursive_resolver only).
DNS_TIMEOUT = 5.0  # main lookups: MX, SPF, DMARC
RETRY_TIMEOUT = 4.0  # the single retry after a timeout or SERVFAIL
DKIM_PROBE_TIMEOUT = 2.0  # first pass over the DKIM selectors
DKIM_MAX_WORKERS = 4  # concurrent DKIM queries; gentle on the zone's nameservers
DKIM_RETRY_BUDGET = 12.0  # seconds for the sequential DKIM retries; the rest stay unknown
SPF_MAX_LOOKUPS = 10  # RFC 7208 4.6.4
# A domain that receives no mail can still be used to send spoofed mail.
NO_MAIL_SPF_FIX = 'This domain has no MX: publish "v=spf1 -all" so nobody can send mail as it.'
NO_MAIL_DMARC_FIX = "This domain has no MX: publish a DMARC record with p=reject so spoofed mail is rejected."
_LOOKUP_MECHS = ("include", "a", "mx", "ptr", "exists")
# A timeout or SERVFAIL (dnspython: NoNameservers) says nothing about the record: never "absent".
_TRANSIENT = (dns.exception.Timeout, dns.resolver.NoNameservers)
_ABSENT = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)


def _resolver(timeout: float = DNS_TIMEOUT, dns_config: DnsConfig = DnsConfig()) -> dns.resolver.Resolver:  # noqa: B008 - frozen
    return dns_auth.recursive_resolver(timeout, dns_config)


def _resolve(name: str, rtype: str, timeout: float = DNS_TIMEOUT, dns_config: DnsConfig = DnsConfig()):  # noqa: B008 - frozen
    """The recursive primitive (honours --resolver); also what the authoritative path falls back to."""
    return _resolver(timeout, dns_config).resolve(name, rtype)


def _lookup(zone: AuthZone, name: str, rtype: str):
    """Authoritative for names in the zone, recursive otherwise; one retry after a timeout/SERVFAIL.

    Still failing raises CheckError naming the lookup, e.g. "timeout: MX example.com".
    NXDOMAIN and NoAnswer propagate untouched: they are answers.
    """
    try:
        return zone.resolve(name, rtype, DNS_TIMEOUT)
    except _TRANSIENT:
        pass
    try:
        return zone.resolve(name, rtype, RETRY_TIMEOUT)
    except dns.exception.Timeout as exc:
        raise CheckError(f"timeout: {rtype} {name}", "timeout") from exc
    except dns.resolver.NoNameservers as exc:
        raise CheckError(f"server error: {rtype} {name}", "dns_error") from exc


def _txt(name: str, zone: AuthZone) -> list[str]:
    """TXT strings for name, [] if none. A failure after the retry raises CheckError (check -> error)."""
    try:
        answers = _lookup(zone, name, "TXT")
    except _ABSENT:
        return []
    return ["".join(s.decode("utf-8", "replace") for s in r.strings) for r in answers]


def _mx(domain: str, zone: AuthZone) -> list[str]:
    try:
        return [f"{r.preference} {r.exchange}" for r in _lookup(zone, domain, "MX")]
    except dns.resolver.NoAnswer:
        return []
    except dns.resolver.NXDOMAIN as exc:
        raise CheckError(f"{domain} does not exist (NXDOMAIN)", "name_not_resolved") from exc


def _dkim_lookup(selector: str, domain: str, timeout: float, zone: AuthZone) -> list[str] | None:
    """TXT strings at the selector; [] = absent (NXDOMAIN/NoAnswer); None = unknown (timeout, SERVFAIL, other)."""
    try:
        # A CNAME to the provider (Proton, Fastmail) leaves the zone and is followed recursively.
        return [str(r).strip('"') for r in zone.resolve(f"{selector}._domainkey.{domain}", "TXT", timeout)]
    except _ABSENT:
        return []
    except (dns.exception.DNSException, OSError):
        return None


def _probe_dkim(domain: str, zone: AuthZone) -> tuple[list[str], bool, list[str]]:
    """(found "selector: key" strings, wildcard detected, selectors still unknown after one retry)."""
    names = [f"zzprobe{token_hex(6)}", *DKIM_SELECTORS]
    with ThreadPoolExecutor(max_workers=DKIM_MAX_WORKERS) as pool:
        results = list(pool.map(lambda n: _dkim_lookup(n, domain, DKIM_PROBE_TIMEOUT, zone), names))
    if any(is_valid_dkim_record(t) for t in results[0] or []):
        return [], True, []  # every name answers: matches would be meaningless
    answers = dict(zip(DKIM_SELECTORS, results[1:]))
    deadline = time.monotonic() + DKIM_RETRY_BUDGET
    for selector in (s for s, r in answers.items() if r is None):  # sequential, longer timeout
        if time.monotonic() < deadline:
            answers[selector] = _dkim_lookup(selector, domain, RETRY_TIMEOUT, zone)
    found = [f"{s}: {t[:80]}" for s, txts in answers.items() for t in txts or [] if is_valid_dkim_record(t)]
    return found, False, [s for s, r in answers.items() if r is None]


def _spf_records(name: str, zone: AuthZone) -> list[str]:
    return [r for r in _txt(name, zone) if r.lower().startswith("v=spf1")]


def count_spf_lookups(spf: str, zone: AuthZone, depth: int = 0, unverified: list[str] | None = None) -> int:
    """DNS-lookup terms in an SPF record, following include/redirect (depth-limited).

    An include that cannot be fetched (after the retry) is appended to `unverified` and not followed:
    the count is then only a lower bound.
    """
    count = 0
    for term in spf.split()[1:]:
        t = term.lstrip("+-~?").lower()
        mech = t.split(":", 1)[0].split("/", 1)[0].split("=", 1)[0]
        if mech not in _LOOKUP_MECHS and mech != "redirect":
            continue
        count += 1
        if mech in ("include", "redirect") and depth < SPF_MAX_LOOKUPS:
            target = t.split(":", 1)[-1] if ":" in t else t.split("=", 1)[-1]
            try:
                sub = _spf_records(target, zone)
            except CheckError:
                if unverified is not None and target not in unverified:
                    unverified.append(target)
                continue
            if sub:
                count += count_spf_lookups(sub[0], zone, depth + 1, unverified)
        if count > SPF_MAX_LOOKUPS:
            break
    return count


def _spf_findings(domain: str, has_mail: bool, zone: AuthZone) -> tuple[list, list, list[str]]:
    """(findings, passed, include hosts whose lookup count could not be verified)."""
    records = _spf_records(domain, zone)
    if not records:
        return [finding("spf_missing", CAT, "No SPF record", f"no v=spf1 TXT record at {domain}",
                        "Publish an SPF record listing the servers allowed to send mail for the domain."
                        if has_mail else NO_MAIL_SPF_FIX, ev=ev("spf_missing", host=domain))], [], []
    spf, out = records[0], []
    terms = spf.lower().split()
    qualifier = next((t[0] if t[0] in "+-~?" else "+" for t in terms if t.lstrip("+-~?") == "all"), None)
    if qualifier == "+":
        out.append(finding("spf_plus_all", CAT, "SPF allows any sender (+all)", spf,
                           "Replace +all with -all (or ~all while testing) so only listed senders pass."))
    elif qualifier == "~":
        out.append(finding("spf_softfail", CAT, "SPF soft-fail (~all)", spf,
                           "Move from ~all to -all once all legitimate senders are listed."))
    elif qualifier == "?":
        out.append(finding("spf_neutral", CAT, "SPF neutral (?all) gives no protection", spf,
                           "Replace ?all with -all so spoofed mail is rejected."))
    unverified: list[str] = []
    lookups = count_spf_lookups(spf, zone, unverified=unverified)
    if lookups > SPF_MAX_LOOKUPS:  # a lower bound is enough to be sure it is too many
        out.append(finding("spf_too_many_lookups", CAT, f"SPF needs more than {SPF_MAX_LOOKUPS} DNS lookups",
                           f"{lookups}{'+' if lookups > SPF_MAX_LOOKUPS else ''} lookups in: {spf}",
                           "Flatten or trim include: entries; receivers treat >10 lookups as a permanent error.",
                           ev=ev("spf_lookups", n=f"{lookups}+", record=spf)))
    if unverified and lookups <= SPF_MAX_LOOKUPS:  # the count may be higher: say so instead of passing it
        return out, [Passed("spf_present_lookups_unverified", data(hosts=", ".join(unverified)))], unverified
    return out, [Passed("spf_present", data(record=spf))], unverified


def _dmarc_findings(host: str, registrable: str, has_mail: bool, zone: AuthZone) -> tuple[list, list]:
    """DMARC at _dmarc.<host>, else the organizational domain (RFC 7489 6.6.3)."""
    checked = [host] if host == registrable else [host, registrable]
    for name in checked:
        records = [r for r in _txt(f"_dmarc.{name}", zone) if r.lower().startswith("v=dmarc1")]
        if records:
            source = f"_dmarc.{name}"
            break
    else:
        return [finding("dmarc_missing", CAT, "No DMARC record",
                        "no v=DMARC1 TXT at " + " or ".join(f"_dmarc.{n}" for n in checked),
                        "Publish a DMARC record, starting with p=none and a rua= address, then move to reject."
                        if has_mail else NO_MAIL_DMARC_FIX,
                        ev=ev("dmarc_missing", where=" / ".join(f"_dmarc.{n}" for n in checked)))], []
    raw = f"{records[0]} (found at {source})"
    found_ev = ev("found_at", record=records[0], source=source)
    records_text = records[0]
    tags = {k.strip().lower(): v.strip() for k, _, v in (p.partition("=") for p in records_text.split(";")) if k.strip()}
    out = []
    if tags.get("p", "none").lower() == "none":
        out.append(finding("dmarc_policy_none", CAT, "DMARC policy is p=none (monitoring only)", raw,
                           "Move to p=quarantine, then p=reject, once reports show legitimate mail passes.", ev=found_ev))
    pct = tags.get("pct")
    if pct is not None and pct.isdigit() and int(pct) < 100:
        out.append(finding("dmarc_pct_below_100", CAT, f"DMARC applies to only {pct}% of mail", raw,
                           "Raise pct to 100 so the policy covers all mail.", ev=found_ev))
    if "rua" not in tags:
        out.append(finding("dmarc_no_rua", CAT, "DMARC has no aggregate report address", raw,
                           "Add rua=mailto:... so you receive reports on who sends mail as your domain.", ev=found_ev))
    return out, [Passed("dmarc_present", data(policy=tags.get("p", "none").lower(), source=source))]


def run(domain: str, registrable: str, dns_config: DnsConfig = DnsConfig()) -> CheckResult:  # noqa: B008 - frozen
    zone = AuthZone(registrable, lambda name, rtype, timeout: _resolve(name, rtype, timeout, dns_config))  # late-bound: patchable
    mx = _mx(domain, zone)
    findings, passed, notes, note_codes = [], [], [], []
    if not mx:
        findings.append(finding("mx_missing", CAT, "No MX record", "no MX records",
                                "If the domain should receive mail, add MX records; otherwise publish a null MX.",
                                ev=ev("mx_missing")))
    else:
        passed.append(Passed("mx_present", data(n=len(mx))))
    spf_findings, spf_passed, unverified = _spf_findings(domain, has_mail=bool(mx), zone=zone)
    dmarc_findings, dmarc_passed = _dmarc_findings(domain, registrable, has_mail=bool(mx), zone=zone)
    findings += spf_findings + dmarc_findings
    passed += spf_passed + dmarc_passed
    if unverified:  # SPF include lookup failed twice: only the lookup-count evaluation is unverified
        notes.append(f"SPF lookup count not verified: no answer for include {', '.join(unverified)}")
        note_codes.append("timeout")
    # Always probed here (DNS-only, info-only, never scored); search_dns keeps its own active-tools gate.
    found, wildcard, unknown = _probe_dkim(domain, zone)
    if found:
        selectors = ", ".join(dict.fromkeys(r.split(":", 1)[0] for r in found))
        passed.append(Passed("dkim_found", data(selectors=selectors)))
    elif unknown and not wildcard:  # a timeout is not proof of absence
        names = ", ".join(unknown)
        findings.append(finding(
            "dkim_unverified", CAT, "DKIM could not be fully checked (some selectors did not answer)",
            f"no answer from: {names}", "Run the check again; if it persists, confirm DKIM signing is enabled.",
            ev=ev("dkim_unverified", selectors=names)))
    else:
        why = "wildcard DKIM DNS answers every selector" if wildcard else "none of the common selectors answered"
        findings.append(finding(
            "dkim_not_found_common_selectors", CAT, "DKIM not found on common selectors (best-effort, not conclusive)",
            why, "Confirm DKIM signing is enabled; a custom selector would not be found by this check.",
            ev=ev("dkim_wildcard" if wildcard else "dkim_none")))
    fallback = [f"{lk.rtype} {lk.name}" for lk in zone.lookups if lk.dns_source == SRC_FALLBACK]
    if fallback:  # the zone's own nameservers did not answer: say so, the values came from a resolver cache
        shown = ", ".join(fallback[:3]) + (f" (+{len(fallback) - 3} more)" if len(fallback) > 3 else "")
        notes.append(f"DNS read via recursive fallback (zone nameservers did not answer): {shown}")
        note_codes.append("recursive_fallback")
    return CheckResult("email", STATUS_OK, Noise.PASSIVE.value, findings=tuple(findings), passed=tuple(passed),
                       notes=tuple(notes), note_codes=tuple(note_codes), dns_lookups=zone.lookups)
