"""Authoritative DNS path. No network: dns.query.udp/tcp and the recursive resolver are mocked."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rcode
import dns.rdata
import dns.resolver
import dns.rrset
import pytest

from openosint.exposure import dns_auth, email_check, runner
from openosint.exposure.dns_auth import SRC_AUTHORITATIVE, SRC_FALLBACK, AuthZone
from openosint.exposure.report import render_html
from tests.exposure_helpers import GOOD_DMARC, GOOD_SPF, report

KEY = '"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3"'
NS1, NS2 = "192.0.2.1", "192.0.2.2"


def rd(rtype: str, text: str):
    return dns.rdata.from_text("IN", rtype, text)


def reply(name, rtype, answers=(), *, aa=True, rcode=dns.rcode.NOERROR, tc=False, cname=None):
    response = dns.message.make_response(dns.message.make_query(name, rtype))
    response.set_rcode(rcode)
    if aa:
        response.flags |= dns.flags.AA
    if tc:
        response.flags |= dns.flags.TC
    if cname:
        response.answer.append(dns.rrset.from_text(name + ".", 300, "IN", "CNAME", cname))
    elif answers:
        response.answer.append(dns.rrset.from_text(name + ".", 300, "IN", rtype, *answers))
    return response


class World:
    """Fake network: `servers[ip](name, rtype)` returns a Message or raises; `recursive` is the resolver cache."""

    def __init__(self, monkeypatch, ns_ips=(NS1, NS2)):
        self.udp_calls, self.tcp_calls, self.recursive_calls = [], [], []
        self.servers = {ip: lambda name, rtype: reply(name, rtype, rcode=dns.rcode.NXDOMAIN) for ip in ns_ips}
        self.recursive = {
            ("example.com", "NS"): [rd("NS", f"ns{i + 1}.example.net.") for i in range(len(ns_ips))],
            **{(f"ns{i + 1}.example.net", "A"): [rd("A", ip)] for i, ip in enumerate(ns_ips)},
        }
        self.lock = threading.Lock()
        monkeypatch.setattr(dns.query, "udp", lambda q, ip, timeout: self._ask(self.udp_calls, q, ip))
        monkeypatch.setattr(dns.query, "tcp", lambda q, ip, timeout: self._ask(self.tcp_calls, q, ip))

    def _ask(self, log, query, ip):
        question = query.question[0]
        with self.lock:
            log.append((ip, question.name.to_text().rstrip("."), dns.rdatatype.to_text(question.rdtype)))
        return self.servers[ip](question.name.to_text().rstrip("."), dns.rdatatype.to_text(question.rdtype))

    def resolve(self, name, rtype, timeout):
        self.recursive_calls.append((name, rtype))
        out = self.recursive.get((name, rtype))
        if out is None:
            raise dns.resolver.NXDOMAIN()
        if isinstance(out, type) and issubclass(out, BaseException):
            raise out()
        return out

    def zone(self) -> AuthZone:
        return AuthZone("example.com", self.resolve)

    def serve(self, table: dict):
        """Authoritative content on every server: (name, type) -> list of rdata text; missing = NXDOMAIN."""
        def server(name, rtype):
            if (name, rtype) in table:
                return reply(name, rtype, table[(name, rtype)])
            return reply(name, rtype, rcode=dns.rcode.NXDOMAIN)
        for ip in self.servers:
            self.servers[ip] = server


@pytest.fixture
def world_dns(monkeypatch):
    return World(monkeypatch)


# --- AuthZone ------------------------------------------------------------------


def test_authoritative_answer_is_used_and_recorded(world_dns):
    world_dns.serve({("example.com", "MX"): ["10 mail.example.com."]})
    zone = world_dns.zone()
    assert [str(r.exchange) for r in zone.resolve("example.com", "MX", 5.0)] == ["mail.example.com."]
    assert [(lk.dns_source, lk.ns_ip) for lk in zone.lookups] == [(SRC_AUTHORITATIVE, NS1)]
    assert ("example.com", "MX") not in world_dns.recursive_calls


def test_non_aa_answer_is_ignored_and_the_next_ns_is_tried(world_dns):
    answers = {NS1: reply("example.com", "MX", ["10 stale.example.com."], aa=False), NS2: reply("example.com", "MX", ["10 fresh.example.com."])}
    world_dns.servers = {ip: (lambda name, rtype, r=r: r) for ip, r in answers.items()}
    zone = world_dns.zone()
    assert [str(r.exchange) for r in zone.resolve("example.com", "MX", 5.0)] == ["fresh.example.com."]
    assert zone.lookups[0].ns_ip == NS2 and [c[0] for c in world_dns.udp_calls] == [NS1, NS2]


@pytest.mark.parametrize("bad", ["timeout", "refused", "servfail"])
def test_failing_first_ns_falls_through_to_the_second(world_dns, bad):
    good = reply("example.com", "MX", ["10 m.example.com."])

    def first(name, rtype):
        if bad == "timeout":
            raise dns.exception.Timeout()
        return reply(name, rtype, rcode=dns.rcode.REFUSED if bad == "refused" else dns.rcode.SERVFAIL)

    world_dns.servers[NS1] = first
    world_dns.servers[NS2] = lambda name, rtype: good
    zone = world_dns.zone()
    assert len(zone.resolve("example.com", "MX", 5.0)) == 1 and zone.lookups[0].ns_ip == NS2


def test_all_ns_failing_falls_back_to_recursive_and_is_recorded(world_dns):
    for ip in world_dns.servers:
        world_dns.servers[ip] = lambda name, rtype: (_ for _ in ()).throw(dns.exception.Timeout())
    world_dns.recursive[("example.com", "MX")] = [rd("MX", "10 cached.example.com.")]
    zone = world_dns.zone()
    assert [str(r.exchange) for r in zone.resolve("example.com", "MX", 5.0)] == ["cached.example.com."]
    assert [(lk.dns_source, lk.ns_ip) for lk in zone.lookups] == [(SRC_FALLBACK, None)]
    before = len(world_dns.udp_calls)
    zone.resolve("example.com", "MX", 5.0)
    assert len(world_dns.udp_calls) == before  # the nameservers are not hammered again once they all failed


def test_truncated_udp_answer_is_retried_over_tcp(world_dns):
    full = reply("example.com", "TXT", ['"v=spf1 -all"'])
    world_dns.servers[NS1] = lambda name, rtype: full if world_dns.tcp_calls else reply(name, rtype, tc=True)
    zone = world_dns.zone()
    assert len(zone.resolve("example.com", "TXT", 5.0)) == 1
    assert world_dns.udp_calls == [(NS1, "example.com", "TXT")] and world_dns.tcp_calls == [(NS1, "example.com", "TXT")]


def test_at_most_four_nameserver_ips_in_stable_order(monkeypatch):
    ips = [f"192.0.2.{n}" for n in range(1, 7)]
    w = World(monkeypatch, ips)
    for ip in ips:
        w.servers[ip] = lambda name, rtype: (_ for _ in ()).throw(dns.exception.Timeout())
    with pytest.raises(dns.resolver.NXDOMAIN):  # every nameserver failed: the (empty) recursive fallback answers
        w.zone().resolve("example.com", "MX", 5.0)
    assert [c[0] for c in w.udp_calls] == ips[:4]


def test_cname_out_of_zone_is_followed_via_the_recursive_path(world_dns):
    world_dns.servers[NS1] = lambda name, rtype: reply(name, rtype, cname="k1.provider.net.")
    world_dns.recursive[("k1.provider.net", "TXT")] = [rd("TXT", KEY)]
    zone = world_dns.zone()
    assert len(zone.resolve("sel._domainkey.example.com", "TXT", 5.0)) == 1
    assert ("k1.provider.net", "TXT") in world_dns.recursive_calls
    assert zone.lookups[0].dns_source == SRC_AUTHORITATIVE


def test_names_outside_the_zone_never_touch_the_zone_nameservers(world_dns):
    world_dns.recursive[("_spf2.titan.email", "TXT")] = [rd("TXT", '"v=spf1 -all"')]
    zone = world_dns.zone()
    assert len(zone.resolve("_spf2.titan.email", "TXT", 5.0)) == 1
    assert world_dns.udp_calls == [] and zone.lookups == ()
    assert not dns_auth.in_zone("notexample.com", "example.com") and dns_auth.in_zone("a.b.example.com", "example.com")


def test_authoritative_nxdomain_and_nodata_are_answers(world_dns):
    world_dns.servers[NS1] = lambda name, rtype: reply(name, rtype, rcode=dns.rcode.NXDOMAIN) if name.startswith("gone") else reply(name, rtype)
    zone = world_dns.zone()
    with pytest.raises(dns.resolver.NXDOMAIN):
        zone.resolve("gone.example.com", "TXT", 5.0)
    with pytest.raises(dns.resolver.NoAnswer):  # NOERROR + AA + no records = NODATA
        zone.resolve("example.com", "MX", 5.0)
    assert {lk.dns_source for lk in zone.lookups} == {SRC_AUTHORITATIVE} and world_dns.recursive_calls.count(("gone.example.com", "TXT")) == 0


# --- through the email check -------------------------------------------------------------------


def mail_zone(w: World, dmarc=GOOD_DMARC, **extra):
    table = {
        ("example.com", "MX"): ["10 mail.example.com."],
        ("example.com", "TXT"): [f'"{GOOD_SPF}"'],
        ("_dmarc.example.com", "TXT"): [f'"{dmarc}"'],
        ("google._domainkey.example.com", "TXT"): [KEY],
        **extra,
    }
    w.serve(table)
    w.recursive[("_spf.google.com", "TXT")] = [rd("TXT", '"v=spf1 -all"')]
    return table


@pytest.fixture
def mail(monkeypatch, world_dns):
    monkeypatch.setattr(email_check, "_resolve", lambda name, rtype, timeout=5.0, dns_config=None: world_dns.resolve(name, rtype, timeout))
    return world_dns


def test_fresh_authoritative_record_beats_stale_recursive(mail):
    mail_zone(mail)  # authoritative: DMARC with rua
    mail.recursive[("_dmarc.example.com", "TXT")] = [rd("TXT", '"v=DMARC1; p=none;"')]  # stale cache: no rua
    result = email_check.run("example.com", "example.com")
    assert result.status == "ok" and "dmarc_no_rua" not in {f.id for f in result.findings}
    assert ("_dmarc.example.com", "TXT") not in mail.recursive_calls
    sources = {(lk.name, lk.rtype): (lk.dns_source, lk.ns_ip) for lk in result.dns_lookups}
    assert sources[("_dmarc.example.com", "TXT")] == (SRC_AUTHORITATIVE, NS1) and result.notes == ()


def test_authoritative_nxdomain_for_dmarc_is_dmarc_missing_not_error(mail):
    table = mail_zone(mail)
    del table[("_dmarc.example.com", "TXT")]
    mail.serve(table)
    result = email_check.run("example.com", "example.com")
    assert result.status == "ok" and "dmarc_missing" in {f.id for f in result.findings}


def test_all_ns_failing_uses_recursive_and_the_evidence_says_so(mail):
    mail_zone(mail)
    for ip in mail.servers:
        mail.servers[ip] = lambda name, rtype: (_ for _ in ()).throw(dns.exception.Timeout())
    mail.recursive.update({
        ("example.com", "MX"): [rd("MX", "10 mail.example.com.")],
        ("example.com", "TXT"): [rd("TXT", f'"{GOOD_SPF}"')],
        ("_dmarc.example.com", "TXT"): [rd("TXT", f'"{GOOD_DMARC}"')],
        ("google._domainkey.example.com", "TXT"): [rd("TXT", KEY)],
    })
    result = email_check.run("example.com", "example.com")
    assert result.status == "ok" and "recursive_fallback" in result.note_codes
    assert any("recursive fallback" in n for n in result.notes)
    assert {lk.dns_source for lk in result.dns_lookups} == {SRC_FALLBACK}


def test_dkim_uses_at_most_four_concurrent_queries(mail):
    table = mail_zone(mail)
    current, peak = 0, 0
    lock = threading.Lock()
    base = mail.servers[NS1]

    def slow(name, rtype):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.02)
        with lock:
            current -= 1
        return base(name, rtype)

    for ip in mail.servers:
        mail.servers[ip] = slow
    email_check.run("example.com", "example.com")
    assert email_check.DKIM_MAX_WORKERS == 4 and 1 < peak <= 4
    assert table  # keep the fixture content referenced


def test_json_has_dns_source_and_ns_ip(world):
    from dataclasses import replace

    base = report()
    email = replace(next(c for c in base.checks if c.name == "email"), dns_lookups=(dns_auth.Lookup("example.com", "MX", SRC_AUTHORITATIVE, NS1),))
    rep = replace(base, checks=tuple(email if c.name == "email" else c for c in base.checks))
    assert rep.to_dict()["checks"]["email"]["dns_lookups"] == [{"name": "example.com", "type": "MX", "dns_source": "authoritative", "ns_ip": NS1}]
    assert all(c["dns_lookups"] == [] for k, c in rep.to_dict()["checks"].items() if k != "email")


@pytest.mark.parametrize("lang", ["en", "it"])
def test_report_mentions_fallback_and_hides_nameserver_ips(world, lang):
    from dataclasses import replace

    from openosint.exposure.report.catalog_en import CATALOG as EN
    from openosint.exposure.report.catalog_it import CATALOG as IT

    base = report()
    email = replace(next(c for c in base.checks if c.name == "email"), notes=("DNS read via recursive fallback",),
                    note_codes=("recursive_fallback",), dns_lookups=(dns_auth.Lookup("example.com", "MX", SRC_FALLBACK, None), dns_auth.Lookup("example.com", "TXT", SRC_AUTHORITATIVE, NS1)))
    html = render_html(replace(base, checks=tuple(email if c.name == "email" else c for c in base.checks)), lang)
    cat = {"en": EN, "it": IT}[lang]
    assert cat["reasons"]["recursive_fallback"].replace("'", "&#x27;") in html
    assert NS1 not in html and "recursive_fallback" not in html


def test_method_line_is_in_both_catalogs():
    from openosint.exposure.report.catalog_en import CATALOG as EN
    from openosint.exposure.report.catalog_it import CATALOG as IT

    assert any("letti direttamente dai suoi server DNS" in p for p in IT["ui"]["method_points"])
    assert any("read directly from its own DNS servers" in p for p in EN["ui"]["method_points"])


# --- --resolver -----------------------------------------------------------------------------------------------


def test_resolver_ip_is_validated_and_applied_to_the_recursive_path_only():
    assert dns_auth.parse_ip(" 1.1.1.1 ") == "1.1.1.1" and dns_auth.parse_ip("2606:4700:4700::1111")
    with pytest.raises(ValueError):
        dns_auth.parse_ip("not-an-ip")
    with pytest.raises(ValueError):
        dns_auth.DnsConfig.of("not-an-ip")
    r = dns_auth.recursive_resolver(3.0, dns_auth.DnsConfig.of("1.1.1.1"))
    assert r.nameservers == ["1.1.1.1"] and r.timeout == r.lifetime == 3.0
    assert dns_auth.recursive_resolver(3.0).nameservers != ["1.1.1.1"]  # no state left behind


def test_run_exposure_rejects_a_bad_resolver_before_any_lookup():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(runner.run_exposure("example.com", resolver="999.1.1.1"))


def test_cli_bad_resolver_exits_2_with_a_clean_message():
    out = subprocess.run(
        [sys.executable, "-m", "openosint.cli", "exposure", "example.com", "--resolver", "nope"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 2 and "not an IP address" in out.stderr and "Traceback" not in out.stderr


def test_parallel_runs_with_different_resolvers_each_use_only_their_own(monkeypatch):
    import asyncio
    import threading
    import time

    from openosint.exposure.models import STATUS_OK, CheckResult

    for name in ("registration", "tls", "http_headers"):  # only the email check does recursive DNS
        monkeypatch.setitem(runner.CHECKS, name, (lambda d, r, n=name: CheckResult(n, STATUS_OK, "passive"), "passive"))
    seen: dict[str, set] = {"a-corp.com": set(), "b-corp.com": set()}

    def resolve(self, name, rtype="A", **kwargs):
        time.sleep(0.002)  # let the two runs interleave
        seen[next(z for z in seen if name.endswith(z))].add(tuple(self.nameservers))
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", resolve)
    threads = [
        threading.Thread(target=lambda d=d, ip=ip: asyncio.run(runner.run_exposure(d, resolver=ip)))
        for d, ip in (("a-corp.com", "1.1.1.1"), ("b-corp.com", "8.8.8.8"))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert seen == {"a-corp.com": {("1.1.1.1",)}, "b-corp.com": {("8.8.8.8",)}}
