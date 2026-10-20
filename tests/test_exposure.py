"""Exposure report tests. Every network seam is mocked: no real DNS, TLS or HTTP."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl

import pytest

from openosint.exposure import (
    email_check,
    headers_check,
    registration_check,
    runner,
    scoring,
)
from openosint.exposure.models import CheckResult
from openosint.exposure.render import render
from openosint.exposure.scoring import SEVERITY_BY_ID, assess, finding
from tests.exposure_helpers import (  # noqa: F401
    GOOD_DMARC,
    GOOD_HEADERS,
    GOOD_SPF,
    NOW,
    ids,
    make_cert,
    rdap_body,
    report,
    verify_error,
)

# --- scoring ---------------------------------------------------------------

REAL_PROBE_DKIM = email_check._probe_dkim  # captured at import, before any fixture stubs it


def test_perfect_domain_gets_a(world):
    rep = report()
    assert rep.grade == "A"
    assert rep.score == 100
    assert {c.name: c.status for c in rep.checks} == {
        "email": "ok", "registration": "ok", "tls": "ok", "http_headers": "ok",
    }
    assert ids(rep) <= {"domain_age"}


def test_single_critical_caps_grade_at_d_even_with_high_score(world):
    world["txt"]["example.com"] = ["v=spf1 +all"]
    rep = report()
    assert "spf_plus_all" in ids(rep)
    assert rep.score == 60  # one critical = -40
    assert rep.grade == "D"


def test_critical_ceiling_applies_over_numeric_score(monkeypatch):
    crit = finding("tls_cert_expired", "tls", "t", "e", "r")
    ok = lambda n, f=(): CheckResult(n, "ok", "passive", findings=f)  # noqa: E731
    assert assess((ok("email"), ok("tls", (crit,)))) == (60, "D", False)  # 60 is already a D
    # Soften the critical weight so the numeric score (85 = B) is better than D: ceiling must bite.
    monkeypatch.setitem(scoring.SCORING_WEIGHTS["severity_penalty"], "critical", 15)
    assert assess((ok("email"), ok("tls", (crit,)))) == (85, "D", True)


def test_http_headers_penalty_is_capped(world):
    world["headers"] = {}  # 4 lows (x4 x0.5 = 8) + info -> under cap; force more via direct assess
    many = tuple(finding("hsts_missing", "http_headers", "t", "e", "r") for _ in range(10))
    ok = lambda n, f=(): CheckResult(n, "ok", "passive", findings=f)  # noqa: E731
    score, grade, _ = assess((ok("email"), ok("tls"), ok("http_headers", many)))
    assert score == 90  # 10 x (4 x 0.5) = 20 uncapped; cap is 10
    assert grade == "A"


def test_registration_penalty_is_capped():
    many = tuple(finding("domain_expires_lt_30d", "registration", "t", "e", "r") for _ in range(5))
    ok = lambda n, f=(): CheckResult(n, "ok", "passive", findings=f)  # noqa: E731
    score, _, _ = assess((ok("email"), ok("tls"), ok("registration", many)))
    assert score == 80  # 5 x (20 x 0.75) = 75 uncapped; cap is 20


def test_severity_table_matches_review():
    assert SEVERITY_BY_ID["spf_plus_all"] == "critical"
    assert SEVERITY_BY_ID["tls_unreachable_443"] == "info"
    assert SEVERITY_BY_ID["domain_age"] == "info"
    assert SEVERITY_BY_ID["dnssec_not_enabled"] == "low"
    assert SEVERITY_BY_ID["referrer_policy_missing"] == "info"
    assert len(SEVERITY_BY_ID) == 33  # 29 + 3 lookalike ids + dkim_unverified


# --- coverage rule ---------------------------------------------------------


def test_incomplete_grade_when_tls_errors(world):
    world["tls"]["example.com"] = socket.gaierror("Name or service not known")
    rep = report()
    tls = next(c for c in rep.checks if c.name == "tls")
    assert tls.status == "error"
    assert rep.grade == "incomplete"
    assert rep.score is not None and rep.score_is_partial
    assert "tls" in rep.excluded_checks


def test_incomplete_grade_when_email_errors(world, monkeypatch):
    def boom(name):
        raise TimeoutError("dns timeout")

    monkeypatch.setattr(email_check, "_txt", boom)
    rep = report()
    assert rep.grade == "incomplete"
    assert "email" in rep.excluded_checks


def test_registration_error_still_graded_but_listed_as_excluded(world, monkeypatch):
    def boom(domain, bootstrap):
        raise RuntimeError("rdap exploded")

    monkeypatch.setattr(registration_check, "_rdap", boom)
    rep = report()
    reg = next(c for c in rep.checks if c.name == "registration")
    assert reg.status == "error" and "rdap exploded" in reg.detail and "RuntimeError" not in reg.reason
    assert rep.grade == "A" and not rep.score_is_partial
    assert rep.excluded_checks == ("registration",)


def test_headers_error_still_graded(world, monkeypatch):
    def boom(url):
        raise OSError("connection reset")

    monkeypatch.setattr(headers_check, "_get", boom)
    rep = report()
    assert rep.grade == "A" and rep.excluded_checks == ("http_headers",)


def test_no_completed_check_gives_no_score():
    errs = tuple(CheckResult(n, "error", "passive", reason="x") for n in ("email", "tls"))
    assert assess(errs)[:2] == (None, "incomplete")


# --- email -----------------------------------------------------------------


def test_missing_dmarc(world):
    world["txt"].pop("_dmarc.example.com")
    rep = report()
    assert "dmarc_missing" in ids(rep)
    assert rep.score == 80  # high = -20


def test_dmarc_policy_pct_and_rua(world):
    world["txt"]["_dmarc.example.com"] = ["v=DMARC1; p=none; pct=50"]
    assert {"dmarc_policy_none", "dmarc_pct_below_100", "dmarc_no_rua"} <= ids(report())


def test_spf_variants(world):
    for spf, expected in [
        ("v=spf1 ~all", "spf_softfail"),
        ("v=spf1 ?all", "spf_neutral"),
        ("v=spf1 +all", "spf_plus_all"),
        ("v=spf1 all", "spf_plus_all"),
    ]:
        world["txt"]["example.com"] = [spf]
        assert expected in ids(report()), spf
    world["txt"]["example.com"] = []
    assert "spf_missing" in ids(report())


def test_spf_too_many_lookups(world):
    world["txt"]["example.com"] = ["v=spf1 " + " ".join(f"include:i{n}.test" for n in range(11)) + " -all"]
    assert "spf_too_many_lookups" in ids(report())


def test_mx_missing_and_dkim_inconclusive_are_info_only(world):
    world["mx"] = []
    world["dkim"] = ([], False)
    rep = report()
    assert {"mx_missing", "dkim_not_found_common_selectors"} <= ids(rep)
    dkim = next(f for f in rep.findings if f.id == "dkim_not_found_common_selectors")
    assert "best-effort, not conclusive" in dkim.title
    assert rep.grade == "A"


def test_dkim_probe_runs_without_active_tools(world, monkeypatch):
    monkeypatch.delenv("OPENOSINT_ALLOW_ACTIVE", raising=False)
    world["dkim"] = ([], False)
    rep = report()
    assert "dkim_not_found_common_selectors" in ids(rep)
    assert rep.grade == "A"  # info only, never scored


def test_titan1_only_domain_does_not_get_dkim_not_found(world, monkeypatch):
    import dns.rdata
    import dns.resolver

    from openosint.exposure import email_check

    key = dns.rdata.from_text("IN", "TXT", '"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3"')

    def resolve(name, rtype, timeout=5.0, dns_config=None):
        if name == "titan1._domainkey.example.com":
            return [key]
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(email_check, "_resolve", resolve)
    monkeypatch.setattr(email_check, "_probe_dkim", REAL_PROBE_DKIM)  # the fixture stubs it; this test wants the real one
    rep = report()
    assert "dkim_not_found_common_selectors" not in ids(rep)


# --- TLS -------------------------------------------------------------------


def test_expired_cert(world):
    world["tls"]["example.com"] = verify_error(10)
    world["tls_unverified"]["example.com"] = (make_cert(days_left=-5), "TLSv1.3")
    rep = report()
    f = next(f for f in rep.findings if f.id == "tls_cert_expired")
    assert f.severity == "critical" and "example.com" in f.evidence and "Test CA" in f.evidence
    assert rep.grade == "D"
    assert not ids(rep) & {"tls_cert_expires_lt_14d", "tls_cert_expires_lt_30d"}


def test_negative_days_never_produce_expiry_window_findings(world):
    world["tls"]["example.com"] = (make_cert(days_left=-3), "TLSv1.3")  # verified path, already expired
    got = ids(report())
    assert "tls_cert_expired" in got and not got & {"tls_cert_expires_lt_14d", "tls_cert_expires_lt_30d"}


def test_expired_domain_gets_only_domain_expired(world):
    world["rdap"] = rdap_body(days_to_expiry=-3)
    got = ids(report())
    assert "domain_expired" in got and not got & {"domain_expires_lt_30d", "domain_expires_lt_60d"}


def test_hostname_mismatch_and_bad_chain(world):
    world["tls"]["example.com"] = verify_error(62)
    world["tls_unverified"]["example.com"] = (make_cert(), "TLSv1.3")
    world["tls"]["www.example.com"] = verify_error(20)
    world["tls_unverified"]["www.example.com"] = (make_cert(), "TLSv1.3")
    assert {"tls_hostname_mismatch", "tls_cert_invalid_chain"} <= ids(report())


def test_cert_expiry_thresholds(world):
    world["tls"]["example.com"] = (make_cert(days_left=10), "TLSv1.3")
    world["tls"]["www.example.com"] = (make_cert(days_left=25), "TLSv1.3")
    assert {"tls_cert_expires_lt_14d", "tls_cert_expires_lt_30d"} <= ids(report())


def test_old_tls_version(world):
    world["tls"]["example.com"] = (make_cert(), "TLSv1.1")
    assert "tls_version_below_1_2" in ids(report())


def test_handshake_failure_is_a_finding_not_an_error(world):
    world["tls"]["example.com"] = ssl.SSLError("UNSUPPORTED_PROTOCOL")  # server speaks only legacy TLS
    world["tls"]["www.example.com"] = ssl.SSLError("UNSUPPORTED_PROTOCOL")
    rep = report()
    assert next(c for c in rep.checks if c.name == "tls").status == "ok"
    f = next(f for f in rep.findings if f.id == "tls_handshake_failed")
    assert f.severity == "high" and "example.com" in f.evidence
    assert rep.grade == "D" and rep.score == 60  # two highs, graded rather than "incomplete"


def test_unreachable_443_is_info_and_not_an_error(world):
    world["tls"]["example.com"] = ConnectionRefusedError()
    world["tls"]["www.example.com"] = ConnectionRefusedError()
    rep = report()
    assert "tls_unreachable_443" in ids(rep)
    assert next(c for c in rep.checks if c.name == "tls").status == "ok"


def test_missing_www_is_skipped_not_error(world):
    world["tls"]["www.example.com"] = socket.gaierror("no such host")
    rep = report()
    tls = next(c for c in rep.checks if c.name == "tls")
    assert tls.status == "ok" and any("www" in n for n in tls.notes)
    assert rep.grade == "A"


# --- registration ----------------------------------------------------------


def test_rdap_failure_is_error_not_pass(world, monkeypatch):
    def boom():
        raise ConnectionError("iana down")

    monkeypatch.setattr(registration_check, "_bootstrap", boom)
    reg = next(c for c in report().checks if c.name == "registration")
    assert reg.status == "error" and "iana down" in reg.detail and reg.findings == ()


def test_tld_without_rdap_is_skipped(world):
    world["bootstrap"] = {"com": ["https://rdap.example/"]}  # .it is not in the IANA bootstrap
    rep = report("example.it")
    reg = next(c for c in rep.checks if c.name == "registration")
    assert reg.status == "skipped" and reg.reason == "no RDAP service for TLD"


def test_registration_findings(world):
    world["rdap"] = rdap_body(days_to_expiry=20, signed=False)
    assert {"domain_expires_lt_30d", "dnssec_not_enabled", "domain_age"} <= ids(report())
    world["rdap"] = rdap_body(days_to_expiry=45)
    assert "domain_expires_lt_60d" in ids(report())


# --- headers ---------------------------------------------------------------


def test_missing_headers(world):
    world["headers"] = {}
    rep = report()
    assert {
        "hsts_missing", "csp_missing", "x_content_type_options_missing",
        "frame_protection_missing", "referrer_policy_missing",
    } <= ids(rep)
    assert rep.score == 100 - 4 * 4 * 0.5  # four lows at x0.5, under the cap of 10


def test_frame_ancestors_satisfies_frame_protection(world):
    assert "frame_protection_missing" not in ids(report())
    world["headers"]["Content-Security-Policy"] = "default-src 'self'"
    assert "frame_protection_missing" in ids(report())
    world["headers"]["X-Frame-Options"] = "DENY"
    assert "frame_protection_missing" not in ids(report())


def test_user_agent_identifies_openosint():
    assert "OpenOSINT" in headers_check.USER_AGENT


# --- output ----------------------------------------------------------------


def test_json_shape_and_noise(world):
    data = json.loads(json.dumps(report().to_dict()))
    assert {"domain", "checked_at", "duration_ms", "grade", "score", "checks", "findings"} <= data.keys()
    assert data["checks"]["tls"]["noise"] == "touches target"
    assert data["checks"]["email"]["noise"] == "passive"
    assert data["checked_at"].endswith("+00:00")


def test_terminal_output_mentions_score_separation_and_exclusions(world, monkeypatch):
    monkeypatch.setattr(registration_check, "_rdap", lambda d, b: (_ for _ in ()).throw(RuntimeError("x")))
    text = render(report())
    assert "separate from the cap-based email grade" in text
    assert "registration" in text and "excluded" in text.lower()


def test_normalize_domain():
    assert runner.normalize_domain(" https://WWW.Example.com/path ") == "www.example.com"
    with pytest.raises(ValueError):
        runner.normalize_domain("not a domain")


# --- manual-test fixes -------------------------------------------------------


def test_headers_skipped_when_tls_verification_fails(world, monkeypatch):
    import requests

    def bad_cert(url):
        raise requests.exceptions.SSLError("HTTPSConnectionPool: certificate verify failed: certificate has expired")

    monkeypatch.setattr(headers_check, "_get", bad_cert)
    h = next(c for c in report().checks if c.name == "http_headers")
    assert h.status == "skipped" and h.reason == "TLS verification failed (see TLS findings)"
    assert h.reason_code == "tls_verification_failed"


def test_headers_other_ssl_error_is_still_an_error(world, monkeypatch):
    import requests

    def other(url):
        raise requests.exceptions.SSLError("handshake failure")

    monkeypatch.setattr(headers_check, "_get", other)
    assert next(c for c in report().checks if c.name == "http_headers").status == "error"


def test_terminal_reason_is_short_and_detail_only_in_json(world, monkeypatch):
    def boom(domain, bootstrap):
        raise ConnectionError("HTTPSConnectionPool(host='rdap.example', port=443): Max retries exceeded " + "x" * 200)

    monkeypatch.setattr(registration_check, "_rdap", boom)
    rep = report()
    reg = next(c for c in rep.checks if c.name == "registration")
    assert reg.reason == "connection failed" and len(reg.reason) <= 80
    text = render(rep)
    assert "ConnectionError" not in text and "Max retries" not in text
    assert "Max retries" in rep.to_dict()["checks"]["registration"]["detail"]
    assert runner.short_reason(RuntimeError("x")) == "unexpected error (details in --json)"
    assert len(runner.short_reason(runner.CheckError("y" * 300))) == 80


def test_no_mx_changes_spf_and_dmarc_recommendations(world):
    world["mx"] = []
    world["txt"] = {}
    rep = report()
    spf = next(f for f in rep.findings if f.id == "spf_missing")
    dmarc = next(f for f in rep.findings if f.id == "dmarc_missing")
    assert spf.severity == "high" and dmarc.severity == "high"  # severities unchanged
    assert 'v=spf1 -all' in spf.recommendation and "p=reject" in dmarc.recommendation


def test_json_stdout_is_only_the_json_document(world, capsys):
    from openosint import cli

    asyncio.run(cli._handle_exposure("example.com", json_output=True))
    out, err = capsys.readouterr()
    assert json.loads(out)["domain"] == "example.com"
    assert "Exposure report" in err


def test_cli_banner_lines_go_to_stderr():
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "openosint.cli", "--json", "exposure", "not a domain"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.stdout == "" and proc.returncode == 2 and "not a valid domain" in proc.stderr


# --- registrable domain (Public Suffix List) -----------------------------------


def test_registrable_domain_uses_public_suffix_list():
    from openosint.exposure.domains import registrable_domain

    assert registrable_domain("expired.badssl.com") == "badssl.com"
    assert registrable_domain("a.b.co.uk") == "b.co.uk"
    assert registrable_domain("nic.it") == "nic.it"
    with pytest.raises(ValueError):
        registrable_domain("localhost")


def test_tldextract_makes_no_network_access_and_writes_no_cache(monkeypatch, tmp_path):
    import requests

    from openosint.exposure import domains

    attempts: list[str] = []

    def forbidden(*a, **k):
        attempts.append("network")  # tldextract swallows fetch errors, so raising alone would not fail the test
        raise AssertionError("tldextract attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setenv("TLDEXTRACT_CACHE", str(tmp_path / "cache"))
    extractor = domains._build()  # fresh instance: would fetch/cache here if misconfigured
    assert extractor("expired.badssl.com").top_domain_under_public_suffix == "badssl.com"
    assert attempts == []
    assert not (tmp_path / "cache").exists()


def test_rdap_queries_registrable_domain_and_report_shows_both(world):
    world["tls"]["expired.example.com"] = (make_cert(hosts=("expired.example.com",)), "TLSv1.3")
    world["txt"]["expired.example.com"] = [GOOD_SPF]
    rep = report("expired.example.com")
    assert world["rdap_queried"] == ["example.com"]
    assert (rep.domain, rep.registrable_domain) == ("expired.example.com", "example.com")
    assert "registrable domain example.com" in next(f for f in rep.findings if f.id == "domain_age").evidence
    assert "Registrable domain: example.com" in render(rep)
    assert rep.to_dict()["registrable_domain"] == "example.com"


def test_dmarc_falls_back_to_organizational_domain_and_says_so(world):
    world["tls"]["sub.example.com"] = (make_cert(hosts=("sub.example.com",)), "TLSv1.3")
    world["txt"]["sub.example.com"] = [GOOD_SPF]
    world["txt"]["_dmarc.example.com"] = ["v=DMARC1; p=none"]  # nothing at _dmarc.sub.example.com
    rep = report("sub.example.com")
    f = next(f for f in rep.findings if f.id == "dmarc_policy_none")
    assert "found at _dmarc.example.com" in f.evidence


def test_dmarc_host_record_wins_over_organizational_domain(world):
    world["tls"]["sub.example.com"] = (make_cert(hosts=("sub.example.com",)), "TLSv1.3")
    world["txt"]["sub.example.com"] = [GOOD_SPF]
    world["txt"]["_dmarc.sub.example.com"] = ["v=DMARC1; p=none; rua=mailto:a@example.com"]
    f = next(f for f in report("sub.example.com").findings if f.id == "dmarc_policy_none")
    assert "found at _dmarc.sub.example.com" in f.evidence


def test_dmarc_missing_evidence_lists_both_names_checked(world):
    world["tls"]["sub.example.com"] = (make_cert(hosts=("sub.example.com",)), "TLSv1.3")
    world["txt"] = {"sub.example.com": [GOOD_SPF]}
    f = next(f for f in report("sub.example.com").findings if f.id == "dmarc_missing")
    assert "_dmarc.sub.example.com" in f.evidence and "_dmarc.example.com" in f.evidence


def test_unregistered_domain_aborts_with_exit_code_2(world, monkeypatch):
    from openosint import cli
    from openosint.exposure.models import DomainNotRegistered
    from openosint.tools.search_rdap import RDAPNotFound

    def not_found(domain, bootstrap):
        raise RDAPNotFound(f"Domain '{domain}' is not registered (RDAP 404).")

    monkeypatch.setattr(registration_check, "_rdap", not_found)
    with pytest.raises(DomainNotRegistered):
        report()
    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(cli._handle_exposure("example.com", json_output=True))
    assert exit_info.value.code == 2


def test_www_checked_only_for_apex_input(world):
    report("example.com")
    assert world["tls_hosts"].count("www.example.com") >= 1
    world["tls_hosts"].clear()
    world["tls"]["app.example.com"] = (make_cert(hosts=("app.example.com",)), "TLSv1.3")
    world["txt"]["app.example.com"] = [GOOD_SPF]
    report("app.example.com")
    assert set(world["tls_hosts"]) == {"app.example.com"}


# --- evidence is plain text ------------------------------------------------


def _texts(rep) -> list[str]:
    out = [f.evidence for f in rep.findings] + [n for c in rep.checks for n in c.notes]
    out += [render(rep)]
    return out


@pytest.mark.parametrize("rdap_secure", [{"delegationSigned": False}, {}, None])
def test_evidence_never_contains_a_dict_or_list_repr(world, rdap_secure):
    # Arrange: break as much as possible so most evidence strings are produced
    w = world
    w["rdap"] = {**rdap_body(), "secureDNS": rdap_secure}
    w["txt"] = {}
    w["mx"] = []
    w["headers"] = {}
    # Act
    rep = report()
    # Assert
    assert "dnssec_not_enabled" in ids(rep)
    for text in _texts(rep):
        assert "{'" not in text and "['" not in text, text


def test_dnssec_evidence_is_human_readable(world):
    world["rdap"] = {**rdap_body(), "secureDNS": {"delegationSigned": False}}
    ev = {f.id: f.evidence for f in report().findings}["dnssec_not_enabled"]
    assert ev == "DNSSEC: not signed"
    world["rdap"] = {**rdap_body(), "secureDNS": None}
    ev = {f.id: f.evidence for f in report().findings}["dnssec_not_enabled"]
    assert ev == "DNSSEC: not reported by the registry"
