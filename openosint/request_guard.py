"""Host-header and browser-origin checks for the web server (pure ASGI middleware).

Two independent checks, both decided from request headers alone:

* Host: on a loopback bind only 127.0.0.1, localhost and ::1 (on the configured
  port) are served, plus names listed in OPENOSINT_ALLOWED_HOSTS. On any other
  bind the check runs only when OPENOSINT_ALLOWED_HOSTS is set.
* Origin: every /api/* request except /api/health is rejected when a browser
  marks it cross-site or same-site (Sec-Fetch-Site), or when its Origin is not
  the request's own origin. Requests carrying neither header (curl, scripts,
  SDKs) are not browser traffic and pass. Always on, on every bind.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# Read-only, carries no secrets and is used for liveness probes.
_UNGUARDED_API_PATHS = frozenset({"/api/health"})

_HOSTNAME_RE = re.compile(r"^[a-z0-9.-]+$")
_IPV6_RE = re.compile(r"^[0-9a-f:.]+$")
_SAME_ORIGIN_SITES = frozenset({"same-origin", "none"})
_MAX_PORT = 65535


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def parse_host(value: str) -> tuple[str, int | None] | None:
    """Split a Host header into (lowercase name, port); None if malformed."""
    value = value.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        name, rest = value[1:end], value[end + 1 :]
        if rest and not rest.startswith(":"):
            return None
        port_text, name_ok = rest[1:], bool(_IPV6_RE.match(name))
    else:
        if value.count(":") > 1:
            return None
        name, _, port_text = value.partition(":")
        name_ok = bool(_HOSTNAME_RE.match(name))
    if not name_ok:
        return None
    if not port_text:
        return name, None
    if not port_text.isdigit() or not 0 < int(port_text) <= _MAX_PORT:
        return None
    return name, int(port_text)


def _allowed_origins() -> set[str]:
    """Extra origins a browser may call from: explicit settings only.

    DEMO_ALLOWED_ORIGINS counts only when set, never its localhost:3000/8000
    default, so an unrelated dev server on those ports gains no access.
    """
    configured = _csv_env("OPENOSINT_ALLOWED_ORIGINS") + _csv_env("DEMO_ALLOWED_ORIGINS")
    return {o.rstrip("/").lower() for o in configured}


def origin_is_rejected(origin: str, fetch_site: str, host_header: str) -> bool:
    """True when a browser-sent request must not be served."""
    origin = origin.strip()
    fetch_site = fetch_site.strip().lower()
    origin_trusted = bool(origin) and origin.rstrip("/").lower() in _allowed_origins()
    if origin_trusted:
        return False
    if fetch_site and fetch_site not in _SAME_ORIGIN_SITES:
        return True
    if not origin:
        return False
    # Host:port only — behind a TLS-terminating proxy the scheme differs.
    origin_host = urlsplit(origin).netloc.lower()
    return not origin_host or origin_host != host_header.strip().lower()


class RequestGuardMiddleware:
    def __init__(self, app, *, loopback_bind: bool, port: int | None = None):
        self.app = app
        self.loopback_bind = loopback_bind
        self.port = port

    def _host_allowed(self, host_header: str | None) -> bool:
        allowlist = [p for p in map(parse_host, _csv_env("OPENOSINT_ALLOWED_HOSTS")) if p]
        if not self.loopback_bind and not allowlist:
            return True
        parsed = parse_host(host_header) if host_header is not None else None
        if parsed is None:
            return False
        name, port = parsed
        if name in LOOPBACK_NAMES and (port is None or self.port is None or port == self.port):
            return True
        return any(name == a_name and a_port in (None, port) for a_name, a_port in allowlist)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = scope["headers"]
        hosts = [v.decode("latin-1") for k, v in raw if k == b"host"]
        host_header = hosts[0] if len(hosts) == 1 else None  # duplicate Host is malformed

        if not self._host_allowed(host_header):
            await self._reject(
                scope, receive, send, "Host not allowed. Add it to OPENOSINT_ALLOWED_HOSTS."
            )
            return

        path = scope["path"]
        if path.startswith("/api/") and path not in _UNGUARDED_API_PATHS:
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in raw}
            if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
                # A CORS preflight has no effect of its own; the CORS layer answers it
                # and the request that follows is what gets checked here.
                await self.app(scope, receive, send)
                return
            if origin_is_rejected(
                headers.get("origin", ""), headers.get("sec-fetch-site", ""), host_header or ""
            ):
                await self._reject(scope, receive, send, "Cross-site request rejected.")
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope, receive, send, message: str) -> None:
        response = JSONResponse({"status": "error", "message": message}, status_code=403)
        await response(scope, receive, send)
