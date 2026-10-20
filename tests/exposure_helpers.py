"""Shared helpers for the exposure tests (the `world` fixture lives in conftest.py)."""

from __future__ import annotations

import asyncio
import datetime as dt
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from openosint.exposure import runner

NOW = dt.datetime.now(dt.timezone.utc)
GOOD_SPF = "v=spf1 include:_spf.google.com -all"
GOOD_DMARC = "v=DMARC1; p=reject; pct=100; rua=mailto:dmarc@example.com"
GOOD_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def make_cert(days_left: int = 200, hosts=("example.com", "www.example.com")) -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(NOW - dt.timedelta(days=400))
        .not_valid_after(NOW + dt.timedelta(days=days_left))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in hosts]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.DER)


def verify_error(code: int) -> ssl.SSLCertVerificationError:
    exc = ssl.SSLCertVerificationError(1, "verify failed")
    exc.verify_code = code
    return exc


def rdap_body(days_to_expiry: int = 400, signed: bool = True) -> dict:
    return {
        "events": [
            {"eventAction": "registration", "eventDate": (NOW - dt.timedelta(days=3650)).isoformat()},
            {"eventAction": "expiration", "eventDate": (NOW + dt.timedelta(days=days_to_expiry)).isoformat()},
        ],
        "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Test Registrar"]]]}],
        "secureDNS": {"delegationSigned": signed},
    }


def report(domain="example.com"):
    return asyncio.run(runner.run_exposure(domain))


def ids(rep) -> set[str]:
    return {f.id for f in rep.findings}
