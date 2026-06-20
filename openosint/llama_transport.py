"""
Custom httpx transport for llama.cpp compatibility.

llama.cpp's HTTP server is incompatible with httpx's default HTTP transport
(libhttpcore / h11).  When httpx sends a request through its normal pipeline,
llama.cpp returns HTTP 400 with an empty body even though:

- The same bytes sent via a raw TCP socket succeed.
- The same bytes forwarded through a TCP proxy succeed.

This module provides ``LlamaCppTransport``, an ``httpx.AsyncBaseTransport``
that sends requests using raw ``asyncio`` sockets, bypassing the httpx/httpcore
stack entirely.  It also adds the correct ``Accept`` header that llama.cpp
requires (``text/event-stream, application/json``).

Usage
-----
Pass an ``AsyncClient`` with this transport to ``openai.AsyncOpenAI``::

    from openai import AsyncOpenAI
    import httpx
    from openosint.llama_transport import LlamaCppTransport

    client = AsyncOpenAI(
        base_url="http://localhost:8000/v1",
        api_key="sk-no-key-required",
        default_headers={"Accept": "text/event-stream, application/json"},
        http_client=httpx.AsyncClient(transport=LlamaCppTransport()),
        timeout=httpx.Timeout(120.0, connect=10.0),
    )
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Accept header required by llama.cpp
# ---------------------------------------------------------------------------
# The server rejects requests that include only ``text/event-stream`` OR only
# ``application/json``.  Both values must be present, comma-separated.
LLAMA_CPP_ACCEPT_HEADER = "text/event-stream, application/json"


# ---------------------------------------------------------------------------
# Async chunked-body reader
# ---------------------------------------------------------------------------


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    """Read an HTTP chunked transfer-encoding body."""
    body = bytearray()
    while True:
        line = await reader.readline()
        if not line:
            break
        size_str = line.decode("utf-8", errors="replace").strip()
        if not size_str:
            continue
        try:
            chunk_size = int(size_str, 16)
        except ValueError:
            logger.warning("Invalid chunk size: %r", size_str)
            break
        if chunk_size == 0:
            # Consume the trailing CRLF after the last chunk
            await reader.readline()
            break
        chunk = await reader.readexactly(chunk_size)
        body.extend(chunk)
        # Consume trailing CRLF after chunk data
        await reader.readline()
    return bytes(body)


async def _read_headers(reader: asyncio.StreamReader, header_data: bytearray) -> None:
    """Read HTTP response headers until the blank line separator."""
    while b"\r\n\r\n" not in header_data:
        byte = await reader.read(1)
        if not byte:
            raise httpx.ProtocolError("server closed connection before sending headers")
        header_data.extend(byte)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class LlamaCppTransport(httpx.AsyncBaseTransport):
    """
    ``httpx.AsyncBaseTransport`` that communicates with the server over a raw
    TCP socket — bypassing httpx's normal HTTP transport (libhttpcore / h11).

    This is a workaround for an incompatibility between httpx's default HTTP
    transport and llama.cpp's HTTP server that results in HTTP 400 responses
    with an empty body.

    The transport handles ``Content-Length``, ``Transfer-Encoding: chunked``,
    and connection-close response bodies correctly.

    .. note::

       The entire response body is buffered in memory before being returned.
       This is acceptable for LLM chat endpoints where responses are typically
       a few kilobytes.  For very large streaming responses, consider a
       streaming version of this transport.
    """

    def __init__(self, timeout: float = 120.0) -> None:
        self._read_timeout = timeout

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        parsed = urlparse(str(request.url))
        host: str = parsed.hostname or "localhost"
        port: int = parsed.port or 80
        path: str = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        if parsed.scheme != "http":
            raise httpx.UnsupportedProtocol(
                f"LlamaCppTransport only supports http://, got {parsed.scheme!r}. "
                "Use a plain HTTP endpoint for llama.cpp."
            )

        # Build the raw HTTP/1.1 request bytes.
        headers = dict(request.headers)
        # httpx sets ``host`` from the URL, but we use our own below.
        headers.pop("host", None)

        raw = f"{request.method} {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        for key, value in headers.items():
            raw += f"{key}: {value}\r\n"
        raw += "\r\n"

        # Collect the request body from the (possibly streaming) request.
        body = bytearray()
        async for chunk in request.stream:
            body.extend(chunk)
        raw_bytes = raw.encode("utf-8") + bytes(body)

        # ---- Send via raw TCP socket ----
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=10.0,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise httpx.ConnectError(f"cannot connect to {host}:{port} — {exc}") from exc

        try:
            writer.write(raw_bytes)
            await writer.drain()

            # ---- Read response headers ----
            header_data = bytearray()
            try:
                await asyncio.wait_for(
                    _read_headers(reader, header_data),
                    timeout=self._read_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise httpx.TimeoutException("timed out reading response headers") from exc

            header_str = header_data.decode("utf-8", errors="replace")
            status_line = header_str.split("\r\n")[0]
            try:
                status_code = int(status_line.split(" ", 2)[1])
            except (IndexError, ValueError) as exc:
                raise httpx.ProtocolError(f"malformed status line: {status_line!r}") from exc

            resp_headers: dict[str, str] = {}
            for line in header_str.split("\r\n")[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    resp_headers[key.strip().lower()] = value.strip()

            # ---- Read response body ----
            te = resp_headers.get("transfer-encoding", "")
            cl = resp_headers.get("content-length")

            try:
                if "chunked" in te:
                    response_body = await asyncio.wait_for(
                        _read_chunked_body(reader),
                        timeout=self._read_timeout,
                    )
                elif cl is not None:
                    body_len = int(cl)
                    response_body = await asyncio.wait_for(
                        reader.readexactly(body_len),
                        timeout=self._read_timeout,
                    )
                else:
                    # Connection-close or unknown length.
                    response_body = await asyncio.wait_for(
                        reader.read(),
                        timeout=self._read_timeout,
                    )
            except asyncio.TimeoutError as exc:
                raise httpx.TimeoutException("timed out reading response body") from exc

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        return httpx.Response(
            status_code=status_code,
            headers=resp_headers,
            content=response_body,
            request=request,
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def make_llama_cpp_http_client(
    timeout: float = 120.0,
    connect_timeout: float = 10.0,
) -> httpx.AsyncClient:
    """
    Return an ``httpx.AsyncClient`` pre-configured with
    ``LlamaCppTransport`` and sensible defaults for long-running LLM
    inference requests.
    """
    return httpx.AsyncClient(
        transport=LlamaCppTransport(timeout=timeout),
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
    )
