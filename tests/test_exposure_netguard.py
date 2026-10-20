"""public_only: the SSRF guard for the TLS and HTTP-header checks. All offline (loopback sockets only)."""

from __future__ import annotations

import asyncio
import datetime as dt
import socket
import ssl
import threading

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from openosint.exposure import headers_check, netguard, runner, tls_check
from openosint.exposure.dns_auth import DnsConfig
from openosint.exposure.models import STATUS_SKIPPED
from tests.exposure_helpers import make_cert

PUBLIC_A, PUBLIC_B = "93.184.216.34", "8.8.8.8"

BLOCKED = [
    "127.0.0.1", "127.255.255.255", "::1", "::ffff:127.0.0.1",
    "10.0.0.1", "172.16.5.4", "192.168.1.1", "::ffff:10.0.0.1", "::ffff:192.168.0.1",
    "169.254.169.254", "169.254.0.1", "::ffff:169.254.169.254", "fe80::1", "fe80::1%eth0",
    "100.64.0.1", "100.127.255.254", "::ffff:100.64.0.1",
    "0.0.0.0", "0.1.2.3", "::", "::ffff:0.0.0.0",
    "224.0.0.1", "239.255.255.255", "ff02::1", "::ffff:224.0.0.1",
    "240.0.0.1", "255.255.255.255",
    "fc00::1", "fd12:3456::1",
    "64:ff9b::7f00:1", "2002:7f00:1::1",
]
PUBLIC = [PUBLIC_A, PUBLIC_B, "2606:4700:4700::1111", "::ffff:8.8.8.8"]


def answers(addresses: list[str]):
    return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]


def resolver(table: dict[str, list[list[str]]], calls: list[str] | None = None):
    """A getaddrinfo stand-in. table[host] is a list of answers, one per call (the last one repeats)."""
    seen: dict[str, int] = {}

    def fake(host, port, *args, **kwargs):
        if calls is not None:
            calls.append(host)
        n = seen.get(host, 0)
        seen[host] = n + 1
        sequence = table[host]
        return answers(sequence[min(n, len(sequence) - 1)])

    return fake


@pytest.fixture
def dns(monkeypatch):
    def install(table: dict[str, list[str]], calls=None):
        """table[host] is one answer list; wrap it as 'the same answer on every call'."""
        monkeypatch.setattr(netguard, "_getaddrinfo", resolver({h: [a] for h, a in table.items()}, calls))

    return install


@pytest.mark.parametrize("address", BLOCKED)
def test_blocked_ranges_are_not_public(address, dns):
    assert not netguard.is_public(address)
    dns({"t.example": [address]})
    with pytest.raises(netguard.NonPublicTarget):
        netguard.pin("t.example")


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_are_allowed(address, dns):
    assert netguard.is_public(address)
    dns({"t.example": [address]})
    assert netguard.pin("t.example") == address


def test_mixed_public_and_private_answers_are_refused(dns):
    dns({"t.example": [PUBLIC_A, "10.0.0.5"]})
    with pytest.raises(netguard.NonPublicTarget):
        netguard.pin("t.example")


def test_ipv4_is_preferred_over_ipv6(dns):
    dns({"t.example": ["2606:4700:4700::1111", PUBLIC_A]})
    assert netguard.pin("t.example") == PUBLIC_A


@pytest.mark.parametrize("name", ["tls", "http_headers"])
def test_refusal_is_a_skipped_check_with_a_catalog_reason(name, dns):
    dns({"example.com": ["127.0.0.1"], "www.example.com": ["127.0.0.1"]})
    result = runner._guarded(name, "example.com", "example.com", DnsConfig(), True)
    assert result.status == STATUS_SKIPPED
    assert result.reason == "target resolves to a non-public address"
    assert result.reason_code == "non_public_target"


def test_non_public_www_is_a_note_not_a_failure(dns, monkeypatch):
    dns({"example.com": [PUBLIC_A], "www.example.com": ["10.0.0.9"]})
    monkeypatch.setattr(tls_check, "_connect", lambda host, verify, ip=None: (make_cert(), "TLSv1.3"))
    result = tls_check.run("example.com", "example.com", public_only=True)
    assert result.status == "ok" and result.note_codes == ("non_public_target",)


def test_dns_rebinding_connects_only_to_the_first_vetted_ip(monkeypatch):
    calls: list[str] = []
    # Every host answers public the first time and private afterwards.
    table = {"example.com": [[PUBLIC_A], ["127.0.0.1"]], "www.example.com": [[PUBLIC_B], ["127.0.0.1"]]}
    monkeypatch.setattr(netguard, "_getaddrinfo", resolver(table, calls))
    connects = []

    def connect(host, verify, ip=None):
        connects.append((host, ip))
        return make_cert(), "TLSv1.3"

    monkeypatch.setattr(tls_check, "_connect", connect)
    result = tls_check.run("example.com", "example.com", public_only=True)
    assert result.status == "ok"
    assert sorted(calls) == ["example.com", "www.example.com"]  # resolved once per host
    assert set(connects) == {("example.com", PUBLIC_A), ("www.example.com", PUBLIC_B)}


# --- certificate verification stays on ------------------------------------------------------


def _self_signed(tmp_path, name: str):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_file, key_file


def _tls_server(cert_file, key_file) -> tuple[int, threading.Thread]:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file, key_file)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)

    def serve():
        try:
            conn, _ = server.accept()
            with ctx.wrap_socket(conn, server_side=True):
                pass
        except (OSError, ssl.SSLError):
            pass  # the client may abort the handshake on purpose
        finally:
            server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server.getsockname()[1], thread


def _trust_only(monkeypatch, cert_file):
    real = ssl.create_default_context
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: real(cafile=str(cert_file)))


def test_connect_dials_the_ip_and_verifies_the_hostname(tmp_path, monkeypatch):
    cert_file, key_file = _self_signed(tmp_path, "example.com")
    port, thread = _tls_server(cert_file, key_file)
    monkeypatch.setattr(tls_check, "PORT", port)
    _trust_only(monkeypatch, cert_file)
    # "example.com" is never resolved: the socket goes to 127.0.0.1, verification is against the name.
    der, version = tls_check._connect("example.com", True, ip="127.0.0.1")
    thread.join(5)
    assert der and version.startswith("TLS")


def test_connect_fails_on_hostname_mismatch_even_with_a_pinned_ip(tmp_path, monkeypatch):
    cert_file, key_file = _self_signed(tmp_path, "other.example")  # trusted, but for another name
    port, thread = _tls_server(cert_file, key_file)
    monkeypatch.setattr(tls_check, "PORT", port)
    _trust_only(monkeypatch, cert_file)
    with pytest.raises(ssl.SSLCertVerificationError) as excinfo:
        tls_check._connect("example.com", True, ip="127.0.0.1")
    thread.join(5)
    assert excinfo.value.verify_code == tls_check._VERIFY_HOSTNAME


def test_header_fetch_pins_the_ip_and_verifies_against_the_hop_hostname(monkeypatch):
    seen = {}

    class FakePool:
        def __init__(self, host, port, **kwargs):
            seen["pool"] = (host, port, kwargs)

        def urlopen(self, method, path, **kwargs):
            seen["request"] = (method, path, kwargs)

            class Response:
                status, headers = 200, {"X-Test": "1"}

                def close(self):
                    pass

            return Response()

        def close(self):
            pass

    monkeypatch.setattr(headers_check, "HTTPSConnectionPool", FakePool)
    assert headers_check._fetch(PUBLIC_A, "example.com", "/a?b=1") == (200, {"X-Test": "1"})
    host, port, kwargs = seen["pool"]
    assert (host, port) == (PUBLIC_A, 443)
    assert kwargs["cert_reqs"] == "CERT_REQUIRED"
    assert kwargs["assert_hostname"] == kwargs["server_hostname"] == "example.com"
    method, path, request = seen["request"]
    assert (method, path) == ("GET", "/a?b=1")
    assert request["headers"]["Host"] == "example.com" and request["redirect"] is False


# --- redirects ------------------------------------------------------------------------------


@pytest.fixture
def fetches(monkeypatch):
    """Scripted responses per (host, path); records every fetch as (ip, host, path)."""
    script: dict[tuple[str, str], tuple[int, dict]] = {}
    log: list[tuple[str, str, str]] = []

    def fetch(ip, host, path):
        log.append((ip, host, path))
        return script[(host, path)]

    monkeypatch.setattr(headers_check, "_fetch", fetch)
    return script, log


def test_redirect_to_http_is_blocked(dns, fetches):
    script, log = fetches
    dns({"example.com": [PUBLIC_A]})
    script[("example.com", "/")] = (301, {"Location": "http://example.com/"})
    with pytest.raises(netguard.RedirectBlocked):
        headers_check._get_public("https://example.com/")
    assert len(log) == 1


def test_redirect_to_another_port_is_blocked(dns, fetches):
    script, _ = fetches
    dns({"example.com": [PUBLIC_A]})
    script[("example.com", "/")] = (302, {"Location": "https://example.com:8443/"})
    with pytest.raises(netguard.RedirectBlocked):
        headers_check._get_public("https://example.com/")


def test_redirect_to_an_internal_host_is_blocked_before_connecting(dns, fetches):
    script, log = fetches
    dns({"example.com": [PUBLIC_A], "intranet.example": ["10.0.0.5"]})
    script[("example.com", "/")] = (302, {"Location": "https://intranet.example/admin"})
    with pytest.raises(netguard.NonPublicTarget):
        headers_check._get_public("https://example.com/")
    assert log == [(PUBLIC_A, "example.com", "/")]  # the internal host was never contacted


def test_redirect_to_another_public_host_is_vetted_pinned_and_followed(dns, fetches):
    script, log = fetches
    dns({"example.com": [PUBLIC_A], "www.other.example": [PUBLIC_B]})
    script[("example.com", "/")] = (301, {"location": "https://www.other.example/home"})
    script[("www.other.example", "/home")] = (302, {"Location": "/landing?x=1"})
    script[("www.other.example", "/landing?x=1")] = (200, {"Strict-Transport-Security": "max-age=1"})
    assert headers_check._get_public("https://example.com/") == {"Strict-Transport-Security": "max-age=1"}
    assert log == [
        (PUBLIC_A, "example.com", "/"),
        (PUBLIC_B, "www.other.example", "/home"),
        (PUBLIC_B, "www.other.example", "/landing?x=1"),
    ]


def test_more_than_three_redirects_fail_like_requests_does(dns, fetches):
    script, log = fetches
    dns({"example.com": [PUBLIC_A]})
    for i in range(6):
        script[("example.com", "/" if i == 0 else f"/{i}")] = (302, {"Location": f"/{i + 1}"})
    with pytest.raises(requests.TooManyRedirects):
        headers_check._get_public("https://example.com/")
    assert len(log) == headers_check.MAX_REDIRECTS + 1


def test_redirect_blocked_is_a_skipped_check(dns, fetches):
    script, _ = fetches
    dns({"example.com": [PUBLIC_A]})
    script[("example.com", "/")] = (301, {"Location": "http://example.com/"})
    result = runner._guarded("http_headers", "example.com", "example.com", DnsConfig(), True)
    assert (result.status, result.reason_code) == (STATUS_SKIPPED, "redirect_blocked")


# --- default behaviour ----------------------------------------------------------------------


def test_default_does_not_use_the_guard(world, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("netguard must not run without public_only")

    monkeypatch.setattr(netguard, "_getaddrinfo", forbidden)
    rep = asyncio.run(runner.run_exposure("example.com"))
    assert rep.grade == "A" and not rep.excluded_checks
    assert world["tls_hosts"]  # the unguarded TLS path ran


def test_public_only_flag_reaches_the_cli():
    from openosint.cli import _build_parser

    parser = _build_parser()
    assert parser.parse_args(["exposure", "example.com"]).public_only is False
    assert parser.parse_args(["exposure", "example.com", "--public-only"]).public_only is True
