"""Streamable HTTP transport for the same MCP server used over stdio."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import stat
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


def _validate_token(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("MCP bearer token is empty")
    if len(value) > 4096 or any(not 33 <= ord(char) <= 126 for char in value):
        raise ValueError("MCP bearer token must be a single printable ASCII token")
    return value


def read_http_token(*, token_file: str | None = None, token_env: str | None = None) -> str | None:
    """Read one startup credential; an explicitly selected source never falls back.

    File takes priority over environment. No credential value is included in an
    error, and no token is accepted on the command line.
    """
    path = token_file
    if path is None and token_env is None:
        path = os.environ.get("OPENOSINT_MCP_TOKEN_FILE")
    if path is not None:
        try:
            secret = Path(path)
            info = secret.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("MCP bearer token file must be a regular file")
            if os.name == "posix" and info.st_mode & 0o077:
                raise ValueError("MCP bearer token file must have owner-only permissions (0600)")
            # Bound accidental reads of large files; a token can be at most 4 KiB.
            with secret.open(encoding="ascii") as stream:
                value = stream.read(4098)
            if len(value) == 4098:
                raise ValueError("MCP bearer token file is too large")
        except (OSError, UnicodeError):
            raise ValueError("Cannot read MCP bearer token file") from None
        return _validate_token(value)
    name = token_env if token_env is not None else "OPENOSINT_MCP_TOKEN"
    value = os.environ.get(name)
    if value is None and token_env is None:
        return None
    if not value:
        raise ValueError("MCP bearer token environment variable is empty or unset")
    return _validate_token(value)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _MCPRoute:
    def __init__(self, manager: StreamableHTTPSessionManager, token: str | None):
        self.manager = manager
        self.expected = hashlib.sha256(token.encode("ascii")).digest() if token else None

    async def __call__(self, scope, receive, send):
        async def no_store(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"cache-control", b"no-store"))
            await send(message)

        if self.expected is not None:
            values = Request(scope).headers.getlist("authorization")
            authorized = False
            if len(values) == 1:
                scheme, separator, supplied = values[0].partition(" ")
                if separator and scheme.lower() == "bearer" and supplied:
                    digest = hashlib.sha256(supplied.encode("latin-1")).digest()
                    authorized = hmac.compare_digest(self.expected, digest)
            if not authorized:
                response = Response(
                    "Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, no_store)
                return
        await self.manager.handle_request(scope, receive, no_store)


def create_http_app(server, *, host="127.0.0.1", token=None, allowed_hosts=()) -> Starlette:
    """Create a single-process, stateless listener with an explicit Host allowlist."""
    if token is not None:
        token = _validate_token(token)
    if not _is_loopback(host) and not token:
        raise ValueError("A non-loopback MCP HTTP listener requires a bearer token")

    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"]
    if host not in ("0.0.0.0", "::", ""):
        authority = f"[{host}]" if ":" in host else host
        hosts.extend([authority, f"{authority}:*"])
    hosts.extend(allowed_hosts)
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            # Machine clients do not send Origin. Browser-originated requests
            # are rejected; this listener does not provide a CORS interface.
            allowed_origins=[],
        ),
    )

    @asynccontextmanager
    async def lifespan(application):
        async with manager.run():
            yield

    async def health(request):
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp", _MCPRoute(manager, token), methods=["GET", "POST", "DELETE"]),
        ],
        lifespan=lifespan,
    )
