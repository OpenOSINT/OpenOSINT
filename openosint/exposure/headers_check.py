"""HTTP security headers on https://DOMAIN/: one GET, at most 3 redirects."""

from __future__ import annotations

import ssl
from urllib.parse import urljoin, urlsplit

import certifi
import requests
import urllib3
from urllib3 import HTTPSConnectionPool

from openosint import __version__
from openosint.exposure import netguard
from openosint.exposure.models import STATUS_OK, CheckResult, CheckSkipped, Passed, data
from openosint.exposure.scoring import ev, finding
from openosint.proxy import get_requests_proxies
from openosint.tool_policy import Noise

CAT = "http_headers"
TIMEOUT = 10
MAX_REDIRECTS = 3
USER_AGENT = f"OpenOSINT-exposure/{__version__} (+https://github.com/OpenOSINT/OpenOSINT)"


# finding id -> header shown in the "present" list when that finding did not fire
PRESENT_NAMES = (
    ("hsts_missing", "Strict-Transport-Security"),
    ("csp_missing", "Content-Security-Policy"),
    ("x_content_type_options_missing", "X-Content-Type-Options"),
    ("frame_protection_missing", "X-Frame-Options / frame-ancestors"),
    ("referrer_policy_missing", "Referrer-Policy"),
)


def _is_cert_failure(exc: BaseException) -> bool:
    seen = exc
    while seen is not None:
        if isinstance(seen, ssl.SSLCertVerificationError):
            return True
        seen = seen.__cause__ or seen.__context__
    text = str(exc).lower()
    return "certificate verify failed" in text or "hostname mismatch" in text


def _get(url: str) -> dict:
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    resp = session.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, proxies=get_requests_proxies())
    return dict(resp.headers)


REDIRECT_STATUSES = (301, 302, 303, 307, 308)


def _fetch(ip: str, host: str, path: str) -> tuple[int, dict]:
    """One GET to the vetted `ip`; Host, SNI and certificate verification use `host`. No redirects."""
    pool = HTTPSConnectionPool(
        ip, 443, server_hostname=host, assert_hostname=host, cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
        timeout=TIMEOUT, retries=False,
    )
    try:
        resp = pool.urlopen("GET", path, headers={"Host": host, "User-Agent": USER_AGENT}, redirect=False,
                            retries=False, preload_content=False)
        try:
            return resp.status, dict(resp.headers)
        finally:
            resp.close()
    finally:
        pool.close()


def _get_public(url: str) -> dict:
    """public_only: redirects followed by hand (https on 443 only), every hop resolved, vetted and pinned.

    Environment proxies are not used: a proxy would resolve the name itself and bypass the pin.
    """
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        try:
            port = parts.port or 443
        except ValueError:
            port = -1
        if parts.scheme != "https" or port != 443 or not parts.hostname:
            raise netguard.RedirectBlocked
        host = parts.hostname
        ip = netguard.pin(host)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            status, headers = _fetch(ip, host, path)
        except urllib3.exceptions.SSLError as exc:
            raise requests.exceptions.SSLError(str(exc)) from exc
        except urllib3.exceptions.TimeoutError as exc:
            raise requests.Timeout(str(exc)) from exc
        except urllib3.exceptions.HTTPError as exc:
            raise requests.ConnectionError(str(exc)) from exc
        location = next((v for k, v in headers.items() if k.lower() == "location"), None)
        if status not in REDIRECT_STATUSES or not location:
            return headers
        url = urljoin(url, location)
    raise requests.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects")


def run(domain: str, registrable: str, public_only: bool = False) -> CheckResult:
    try:
        response_headers = (_get_public if public_only else _get)(f"https://{domain}/")
    except requests.exceptions.SSLError as exc:
        if _is_cert_failure(exc):  # never retried unverified: the TLS check already reports it
            raise CheckSkipped("TLS verification failed (see TLS findings)", "tls_verification_failed") from exc
        raise
    h = {k.lower(): v for k, v in response_headers.items()}
    csp = h.get("content-security-policy", "")
    missing = []  # (id, title, recommendation)
    if "strict-transport-security" not in h:
        missing.append(("hsts_missing", "Strict-Transport-Security header missing",
                        "Send Strict-Transport-Security with a max-age of at least 6 months."))
    if not csp:
        missing.append(("csp_missing", "Content-Security-Policy header missing",
                        "Add a Content-Security-Policy that restricts script and frame sources."))
    if h.get("x-content-type-options", "").lower() != "nosniff":
        missing.append(("x_content_type_options_missing", "X-Content-Type-Options: nosniff missing",
                        "Send X-Content-Type-Options: nosniff."))
    if "x-frame-options" not in h and "frame-ancestors" not in csp.lower():
        missing.append(("frame_protection_missing", "No clickjacking protection (X-Frame-Options / frame-ancestors)",
                        "Send X-Frame-Options: DENY or a CSP frame-ancestors directive."))
    if "referrer-policy" not in h:
        missing.append(("referrer_policy_missing", "Referrer-Policy header missing",
                        "Send Referrer-Policy: strict-origin-when-cross-origin or stricter."))
    findings = tuple(finding(i, CAT, t, "header not present in response", r, ev=ev("header_absent")) for i, t, r in missing)
    absent = {i for i, _, _ in missing}
    present = tuple(name for fid, name in PRESENT_NAMES if fid not in absent)
    passed = (Passed("headers_present", data(headers=", ".join(present))),) if present else ()
    return CheckResult("http_headers", STATUS_OK, Noise.TOUCHES_TARGET.value, findings=findings, passed=passed)
