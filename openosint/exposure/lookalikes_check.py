"""Lookalike detection: DNS lookups only. Never connects to a candidate (no HTTP, TLS, port or WHOIS)."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from functools import partial

import dns.exception
import dns.resolver

from openosint.exposure import dns_auth
from openosint.exposure.dns_auth import DnsConfig
from openosint.exposure.lookalikes_gen import MAX_CANDIDATES, Candidate, generate
from openosint.exposure.models import STATUS_OK, Finding, Lookalike, LookalikeScan
from openosint.exposure.scoring import finding

CAT = "lookalikes"
MAX_WORKERS = 8  # first pass and retry pass alike: home routers choke on bigger bursts
QUERY_TIMEOUT = 2.0  # seconds per lookup
DEADLINE = 25.0  # seconds for the whole step; unfinished candidates become "unknown"
EVIDENCE_CAP = 20  # domains listed in a finding's evidence; the full list is in --json
RECORD_TYPES = ("NS", "A", "AAAA", "MX")  # NS first: its NXDOMAIN ends the candidate


def defang(domain: str) -> str:
    return domain.replace(".", "[.]")


def _query(name: str, rtype: str, dns_config: DnsConfig) -> list[str]:
    """Answers as text; [] for NOERROR without data. NXDOMAIN raises; timeouts/SERVFAIL propagate."""
    resolver = dns_auth.recursive_resolver(QUERY_TIMEOUT, dns_config)
    try:
        return [r.to_text() for r in resolver.resolve(name, rtype)]
    except dns.resolver.NoAnswer:
        return []


def _is_real_mx(record: str) -> bool:
    return record.split()[-1] != "."  # "0 ." is the null MX (RFC 7505): the domain accepts no mail


def probe(domain: str, dns_config: DnsConfig = DnsConfig()) -> tuple[str, bool, bool]:  # noqa: B008 - frozen
    """(state, has_mx, has_a) with state registered | not_registered | unknown.

    Only an NXDOMAIN gives not_registered: a timeout, SERVFAIL or an empty NOERROR never does.
    """
    answers: dict[str, list[str]] = {}
    for rtype in RECORD_TYPES:
        try:
            answers[rtype] = _query(domain, rtype, dns_config)
        except dns.resolver.NXDOMAIN:
            return "not_registered", False, False  # stop: no point asking the other types
        except (dns.exception.DNSException, OSError):
            if rtype == "NS":
                break  # no clear first answer: do not guess
    has_mx = any(_is_real_mx(r) for r in answers.get("MX", []))
    has_a = bool(answers.get("A") or answers.get("AAAA"))
    if any(answers.values()):
        return "registered", has_mx, has_a
    return "unknown", False, False  # nothing answered and no NXDOMAIN: not proof of absence


def _is_wildcard(suffix: str, dns_config: DnsConfig) -> bool:
    """True when the TLD answers for a random, certainly unregistered label."""
    return probe(f"wc{secrets.token_hex(8)}.{suffix}", dns_config)[0] == "registered"


def _result(c: Candidate, state: str, has_mx: bool = False, has_a: bool = False, reason: str | None = None) -> Lookalike:
    return Lookalike(c.domain, c.technique, state, has_mx, has_a, reason)


def _check(c: Candidate, wildcard: frozenset[str], dns_config: DnsConfig) -> Lookalike:
    if c.domain.partition(".")[2] in wildcard:
        return _result(c, "unknown", reason="wildcard_tld")
    state, has_mx, has_a = probe(c.domain, dns_config)
    return _result(c, state, has_mx, has_a, "dns_error" if state == "unknown" else None)


def _collect(c: Candidate, future) -> Lookalike:
    """A finished lookup, or "unknown" when it never ran (deadline) or crashed (dns_error)."""
    if future.cancelled() or not future.done():
        return _result(c, "unknown", reason="deadline")
    if future.exception() is not None:
        return _result(c, "unknown", reason="dns_error")
    return future.result()


def _evidence(domains: list[str]) -> str:
    shown = ", ".join(defang(d) for d in domains[:EVIDENCE_CAP])
    more = f" (+{len(domains) - EVIDENCE_CAP} more, full list in --json)" if len(domains) > EVIDENCE_CAP else ""
    return f"{len(domains)} domain(s): {shown}{more}"


def build_findings(results: tuple[Lookalike, ...]) -> tuple[Finding, ...]:
    registered = [r for r in results if r.state == "registered"]
    with_mx = sorted(r.domain for r in registered if r.has_mx)
    no_mx = sorted(r.domain for r in registered if not r.has_mx)
    found: list[Finding] = []
    if with_mx:
        found.append(finding("lookalike_with_mx", CAT, "Registered domains that look like yours can receive email",
                             _evidence(with_mx), "Warn staff and accounts payable; verify any payment change by phone; consider registering the closest variants."))
    if no_mx:
        found.append(finding("lookalike_registered", CAT, "Registered domains that look like yours (no email service seen)",
                             _evidence(no_mx), "Keep an eye on them and consider registering the closest variants."))
    if not registered and any(r.state == "not_registered" for r in results):
        found.append(finding("lookalikes_none_found", CAT, "No registered lookalike found among the variants checked",
                             f"{len(results)} variants checked", "No action needed."))
    return tuple(found)


def _pool_map(fn: Callable, items: Iterable, timeout: float) -> dict:
    """Submit fn(item) for every item to a fresh pool and wait up to `timeout`; item -> Future (some may be pending)."""
    # ponytail: threads cannot be killed; stragglers end by themselves after QUERY_TIMEOUT per lookup.
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = {i: pool.submit(fn, i) for i in items}
        wait(futures.values(), timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return futures


def _is_retryable(r: Lookalike) -> bool:
    return r.state == "unknown" and r.unknown_reason != "wildcard_tld"


def scan(registrable: str, dns_config: DnsConfig = DnsConfig(), limit: int = MAX_CANDIDATES, deadline: float = DEADLINE) -> LookalikeScan:  # noqa: B008
    """Generate and resolve lookalikes. Always returns within about `deadline` seconds.

    Every candidate that comes back "unknown" gets one more try (same pool size) if time remains.
    """
    started = time.monotonic()

    def left() -> float:
        return max(0.0, deadline - (time.monotonic() - started))

    candidates, skipped = generate(registrable, limit)
    suffixes = sorted({c.domain.partition(".")[2] for c in candidates})
    probes = _pool_map(partial(_is_wildcard, dns_config=dns_config), suffixes, left())
    wildcard = frozenset(s for s, f in probes.items() if f.done() and not f.cancelled() and f.exception() is None and f.result())
    check = partial(_check, wildcard=wildcard, dns_config=dns_config)
    results = {c: _collect(c, f) for c, f in _pool_map(check, candidates, left()).items()}
    retry = [c for c, r in results.items() if _is_retryable(r)]
    if retry and left() > 0:
        for c, f in _pool_map(check, retry, left()).items():
            second = _collect(c, f)
            if second.state != "unknown":
                results[c] = second
    final = tuple(results[c] for c in candidates)
    return LookalikeScan(STATUS_OK, len(candidates) + skipped, skipped, final, build_findings(final))
