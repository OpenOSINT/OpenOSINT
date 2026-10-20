"""Timeout/SERVFAIL handling in the email check and lookalike ordering. DNS is replaced by a script."""

from __future__ import annotations

import asyncio

import dns.exception
import dns.rdata
import dns.resolver
import pytest

from openosint.exposure import email_check, runner
from openosint.exposure.dns_auth import DnsConfig
from openosint.exposure.models import CheckError
from openosint.exposure.scoring import assess
from tests.exposure_helpers import GOOD_DMARC, GOOD_SPF, ids, report

NX = dns.resolver.NXDOMAIN
NOANSWER = dns.resolver.NoAnswer
TIMEOUT = dns.resolver.LifetimeTimeout
SERVFAIL = dns.resolver.NoNameservers
KEY = '"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3"'


def rd(rtype: str, text: str):
    return dns.rdata.from_text("IN", rtype, text)


def good_dns() -> dict:
    """(name, type) -> outcomes consumed one per call (the last repeats). Missing names are NXDOMAIN."""
    return {
        ("example.com", "MX"): [[rd("MX", "10 mail.example.com.")]],
        ("example.com", "TXT"): [[rd("TXT", f'"{GOOD_SPF}"')]],
        ("_dmarc.example.com", "TXT"): [[rd("TXT", f'"{GOOD_DMARC}"')]],
        ("google._domainkey.example.com", "TXT"): [[rd("TXT", KEY)]],
        ("_spf.google.com", "TXT"): [[rd("TXT", '"v=spf1 -all"')]],
    }


@pytest.fixture
def dns_script(monkeypatch):
    script, calls = good_dns(), []

    def resolve(name, rtype, timeout=email_check.DNS_TIMEOUT, dns_config=None):
        calls.append((name, rtype, timeout))
        outcomes = script.get((name, rtype))
        if outcomes is None:
            raise NX()
        out = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(out, type) and issubclass(out, BaseException):
            raise out()
        return out

    monkeypatch.setattr(email_check, "_resolve", resolve)
    return script, calls


def make_zone():
    return email_check.AuthZone("example.com", lambda n, t, to: email_check._resolve(n, t, to))


def run():
    return email_check.run("example.com", "example.com")


# --- DKIM: only NXDOMAIN / NoAnswer mean absent ---------------------------------


@pytest.mark.parametrize(("outcome", "expected"), [(NX, []), (NOANSWER, []), (TIMEOUT, None), (SERVFAIL, None)])
def test_dkim_lookup_absent_vs_unknown(dns_script, outcome, expected):
    dns_script[0][("k1._domainkey.example.com", "TXT")] = [outcome]
    assert email_check._dkim_lookup("k1", "example.com", 2.0, make_zone()) == expected


def test_titan1_timeout_then_answer_gives_no_dkim_finding(dns_script):
    script, calls = dns_script
    del script[("google._domainkey.example.com", "TXT")]
    script[("titan1._domainkey.example.com", "TXT")] = [TIMEOUT, [rd("TXT", KEY)]]
    result = run()
    assert not {"dkim_unverified", "dkim_not_found_common_selectors"} & {f.id for f in result.findings}
    assert any(p.id == "dkim_found" for p in result.passed)
    assert [c[2] for c in calls if c[0].startswith("titan1")] == [email_check.DKIM_PROBE_TIMEOUT, email_check.RETRY_TIMEOUT]


def test_titan1_timeout_twice_is_unverified_info_and_does_not_lower_the_score(dns_script):
    script, _ = dns_script
    del script[("google._domainkey.example.com", "TXT")]
    script[("titan1._domainkey.example.com", "TXT")] = [TIMEOUT]
    unverified = run()
    f = next(f for f in unverified.findings if f.id == "dkim_unverified")
    assert f.severity == "info" and "titan1" in f.evidence
    assert "dkim_not_found_common_selectors" not in {f.id for f in unverified.findings}
    script[("google._domainkey.example.com", "TXT")] = [[rd("TXT", KEY)]]
    assert assess((unverified,))[0] == assess((run(),))[0]


def test_all_selectors_nxdomain_is_still_not_found(dns_script):
    del dns_script[0][("google._domainkey.example.com", "TXT")]
    result = run()
    assert "dkim_not_found_common_selectors" in {f.id for f in result.findings}
    assert "dkim_unverified" not in {f.id for f in result.findings}


def test_valid_key_wins_over_unknown_selectors(dns_script):
    dns_script[0][("titan1._domainkey.example.com", "TXT")] = [TIMEOUT]
    assert any(p.id == "dkim_found" for p in run().passed) and "dkim_unverified" not in {f.id for f in run().findings}


# --- main lookups: one retry, then error naming the lookup ------------------------------


def test_dmarc_timeout_then_answer_is_ok(dns_script):
    script, calls = dns_script
    script[("_dmarc.example.com", "TXT")] = [TIMEOUT, [rd("TXT", f'"{GOOD_DMARC}"')]]
    result = run()
    assert result.status == "ok" and any(p.id == "dmarc_present" for p in result.passed)
    assert [c[2] for c in calls if c[0] == "_dmarc.example.com"] == [email_check.DNS_TIMEOUT, email_check.RETRY_TIMEOUT]


def test_dmarc_timeout_twice_is_error_naming_the_lookup(dns_script):
    dns_script[0][("_dmarc.example.com", "TXT")] = [TIMEOUT]
    with pytest.raises(CheckError, match=r"timeout: TXT _dmarc\.example\.com") as exc:
        run()
    assert exc.value.code == "timeout"
    check = runner._guarded("email", "example.com", "example.com", DnsConfig())
    assert check.status == "error" and check.reason == "timeout: TXT _dmarc.example.com" and len(check.reason) < 80


@pytest.mark.parametrize(("rtype", "name"), [("MX", "example.com"), ("TXT", "example.com")])
def test_mx_and_apex_spf_failure_after_retry_is_error(dns_script, rtype, name):
    dns_script[0][(name, rtype)] = [TIMEOUT]
    with pytest.raises(CheckError, match=f"timeout: {rtype} {name}"):
        run()


def test_servfail_on_a_main_lookup_is_a_dns_error_after_one_retry(dns_script):
    script, calls = dns_script
    script[("example.com", "MX")] = [SERVFAIL]
    with pytest.raises(CheckError) as exc:
        run()
    assert exc.value.code == "dns_error" and "MX example.com" in str(exc.value)
    assert len([c for c in calls if c[1] == "MX"]) == 2


def test_nxdomain_is_an_answer_not_retried(dns_script):
    script, calls = dns_script
    del script[("_dmarc.example.com", "TXT")]
    assert "dmarc_missing" in {f.id for f in run().findings}
    assert len([c for c in calls if c[0] == "_dmarc.example.com"]) == 1


# --- SPF include failure: only the lookup count is unverified --------------------------------------------


def test_failed_spf_include_keeps_the_check_ok_and_marks_only_the_count(dns_script):
    script, calls = dns_script
    script[("example.com", "TXT")] = [[rd("TXT", '"v=spf1 include:_spf2.titan.email -all"')]]
    script[("_spf2.titan.email", "TXT")] = [TIMEOUT]
    result = run()
    assert result.status == "ok"
    passed = {p.id: dict(p.data) for p in result.passed}
    assert passed["spf_present_lookups_unverified"] == {"hosts": "_spf2.titan.email"}
    assert {"mx_present", "dmarc_present", "dkim_found"} <= set(passed) and "spf_present" not in passed
    assert any("_spf2.titan.email" in n for n in result.notes)
    assert [c[2] for c in calls if c[0] == "_spf2.titan.email"] == [email_check.DNS_TIMEOUT, email_check.RETRY_TIMEOUT]


def test_failed_spf_include_does_not_make_the_grade_incomplete(world, monkeypatch):
    world["txt"]["example.com"] = ["v=spf1 include:_spf2.titan.email -all"]

    def txt(name, zone=None):
        if name == "_spf2.titan.email":
            raise CheckError("timeout: TXT _spf2.titan.email", "timeout")  # what _txt raises after its retry
        return world["txt"].get(name, [])

    monkeypatch.setattr(email_check, "_txt", txt)
    rep = report()
    assert rep.grade == "A" and rep.excluded_checks == () and "spf_missing" not in ids(rep)


def test_too_many_lookups_is_still_reported_with_a_failed_include(dns_script):
    script, _ = dns_script
    includes = " ".join(f"include:i{n}.test" for n in range(11))
    script[("example.com", "TXT")] = [[rd("TXT", f'"v=spf1 {includes} -all"')]]
    script[("i3.test", "TXT")] = [TIMEOUT]
    result = run()
    assert "spf_too_many_lookups" in {f.id for f in result.findings} and result.status == "ok"


# --- resolver configuration ---------------------------------------------------------------------------------------


def test_timeout_and_lifetime_are_set_together_and_resolvers_are_not_shared():
    r = email_check._resolver(3.0)
    assert r.timeout == r.lifetime == 3.0
    assert email_check._resolver().timeout == email_check.DNS_TIMEOUT == 5.0 and email_check.RETRY_TIMEOUT == 4.0
    assert email_check._resolver() is not email_check._resolver()


# --- lookalikes run after the scored checks --------------------------------------------------------------------------------


def test_lookalikes_start_only_after_all_scored_checks_returned(world, monkeypatch):
    import time

    events = []

    def slow(name, fn):
        def wrapped(domain, registrable, *extra):
            time.sleep(0.05)
            out = fn(domain, registrable, *extra)
            events.append(("done", name))
            return out
        return wrapped

    for name, (fn, noise) in dict(runner.CHECKS).items():
        monkeypatch.setitem(runner.CHECKS, name, (slow(name, fn), noise))
    monkeypatch.setattr(runner.lookalikes_check, "scan", lambda registrable, dns_config=None: events.append(("scan", "")) or empty_scan())
    asyncio.run(runner.run_exposure("example.com", lookalikes=True))
    names = [e[0] for e in events]
    assert names.count("done") == len(runner.CHECKS) and names[-1] == "scan"


def empty_scan():
    from openosint.exposure.models import LookalikeScan

    return LookalikeScan("ok", 0, 0)
