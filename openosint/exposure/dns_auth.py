"""Authoritative DNS reads for the scored lookups inside the target's zone.

Narrow on purpose (not a resolver): ask the zone's own nameservers (at most MAX_NS_IPS, stable order),
accept only authoritative answers, fall back to the recursive path when none can answer. Everything
outside the zone (SPF includes on third parties, CNAME targets elsewhere) stays recursive.
"""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Callable
from dataclasses import dataclass

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.resolver

AUTH_TIMEOUT = 3.0  # per nameserver, UDP and TCP alike
DISCOVERY_TIMEOUT = 4.0  # recursive NS / A lookups used to find the zone's nameservers
MAX_NS_IPS = 4
MAX_CNAME_HOPS = 8
SRC_AUTHORITATIVE, SRC_FALLBACK = "authoritative", "recursive_fallback"
Recursive = Callable[[str, str, float], object]  # (name, rtype, timeout) -> answers; raises dns exceptions

def parse_ip(value: str) -> str:
    """The canonical IP literal, or ValueError."""
    return str(ipaddress.ip_address(value.strip()))


@dataclass(frozen=True)
class DnsConfig:
    """Per-run DNS settings, created once in run_exposure and passed down; nothing is process-wide."""

    resolver_ip: str | None = None  # recursive path only; None = the system resolver

    @classmethod
    def of(cls, resolver_ip: str | None) -> DnsConfig:
        """ValueError for a non-IP."""
        return cls(parse_ip(resolver_ip) if resolver_ip else None)


def recursive_resolver(timeout: float, dns_config: DnsConfig = DnsConfig()) -> dns.resolver.Resolver:  # noqa: B008 - frozen
    """A fresh resolver (never shared between threads); timeout and lifetime are always set together."""
    r = dns.resolver.Resolver()
    if dns_config.resolver_ip:
        r.nameservers = [dns_config.resolver_ip]
    r.timeout = r.lifetime = timeout
    return r


@dataclass(frozen=True)
class Lookup:
    name: str
    rtype: str
    dns_source: str  # authoritative | recursive_fallback
    ns_ip: str | None = None  # JSON only, never in the report


def in_zone(name: str, zone: str) -> bool:
    n = name.rstrip(".").lower()
    return n == zone or n.endswith("." + zone)


def _ask(ip: str, name: str, rtype: str) -> dns.message.Message:
    query = dns.message.make_query(name, rtype)
    response = dns.query.udp(query, ip, timeout=AUTH_TIMEOUT)
    if response.flags & dns.flags.TC:
        response = dns.query.tcp(query, ip, timeout=AUTH_TIMEOUT)
    return response


def _find(response: dns.message.Message, name: dns.name.Name, rdtype: int):
    """The answer-section RRset for (name, rdtype), or None. A plain scan: no reliance on message indexes."""
    return next((r for r in response.answer if r.name == name and r.rdtype == rdtype and r.rdclass == dns.rdataclass.IN), None)


def _extract(response: dns.message.Message, name: str, rdtype: int):
    """(rrset | None, cname target | None): the answer, or the CNAME that leads away from this response."""
    start = qname = dns.name.from_text(name)
    for _ in range(MAX_CNAME_HOPS):
        if (found := _find(response, qname, rdtype)) is not None:
            return found, None
        cname = _find(response, qname, dns.rdatatype.CNAME)
        if cname is None:
            return None, (qname.to_text().rstrip(".") if qname != start else None)
        qname = cname[0].target
    return None, qname.to_text().rstrip(".")


class AuthZone:
    """Resolves names for one registrable domain; thread-safe. Records where each lookup was answered."""

    def __init__(self, zone: str, recursive: Recursive) -> None:
        self.zone = zone.rstrip(".").lower()
        self._recursive = recursive
        self._lock = threading.Lock()
        self._ips: tuple[str, ...] | None = None
        self._down = False  # every nameserver failed once: skip straight to the fallback afterwards
        self._seen: dict[tuple[str, str], Lookup] = {}

    @property
    def lookups(self) -> tuple[Lookup, ...]:
        with self._lock:
            return tuple(self._seen[k] for k in sorted(self._seen))

    def _record(self, name: str, rtype: str, source: str, ip: str | None) -> None:
        with self._lock:
            self._seen[(name, rtype)] = Lookup(name, rtype, source, ip)

    def _nameserver_ips(self) -> tuple[str, ...]:
        with self._lock:
            if self._ips is None:
                self._ips = self._discover()
            return self._ips

    def _discover(self) -> tuple[str, ...]:
        """NS hosts of the zone (recursive, one retry), their IPv4 addresses, first MAX_NS_IPS in stable order."""
        hosts: list[str] = []
        for _ in range(2):
            try:
                hosts = sorted({str(r.target).rstrip(".").lower() for r in self._recursive(self.zone, "NS", DISCOVERY_TIMEOUT)})
                break
            except (dns.exception.DNSException, OSError):
                continue
        ips: list[str] = []
        for host in hosts:
            try:
                ips += sorted({r.address for r in self._recursive(host, "A", DISCOVERY_TIMEOUT)})
            except (dns.exception.DNSException, OSError):
                continue
        return tuple(ips[:MAX_NS_IPS])

    def resolve(self, name: str, rtype: str, timeout: float):
        """Answers like dns.resolver (NXDOMAIN / NoAnswer raised); `timeout` only applies to the recursive path."""
        if not in_zone(name, self.zone):
            return self._recursive(name, rtype, timeout)
        for ip in () if self._down else self._nameserver_ips():
            try:
                response = _ask(ip, name, rtype)
            except (dns.exception.DNSException, OSError):
                continue  # timeout, malformed, refused connection: next nameserver
            authoritative = bool(response.flags & dns.flags.AA)
            if authoritative and response.rcode() in (dns.rcode.NOERROR, dns.rcode.NXDOMAIN):
                return self._answer(response, name, rtype, ip, timeout)
        self._down = True
        self._record(name, rtype, SRC_FALLBACK, None)
        return self._recursive(name, rtype, timeout)

    def _answer(self, response: dns.message.Message, name: str, rtype: str, ip: str, timeout: float):
        self._record(name, rtype, SRC_AUTHORITATIVE, ip)
        if response.rcode() == dns.rcode.NXDOMAIN:
            raise dns.resolver.NXDOMAIN(qnames=[dns.name.from_text(name)], responses={dns.name.from_text(name): response})
        rrset, target = _extract(response, name, dns.rdatatype.from_text(rtype))
        if rrset is not None:
            return rrset
        if target is not None:  # a CNAME leading elsewhere: out of the zone it goes recursive
            return self.resolve(target, rtype, timeout)
        raise dns.resolver.NoAnswer(response=response)
