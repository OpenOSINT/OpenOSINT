"""Tests for openosint/llama_transport.py"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from openosint.llama_transport import (
    LlamaCppTransport,
    _read_chunked_body,
    make_llama_cpp_http_client,
)


@pytest.mark.asyncio
class TestReadChunkedBody:
    """Unit tests for _read_chunked_body."""

    async def test_normal_chunk(self):
        reader = _asyncio_reader(b"5\r\nhello\r\n0\r\n\r\n")
        body = await _read_chunked_body(reader)
        assert body == b"hello"

    async def test_empty_body(self):
        reader = _asyncio_reader(b"0\r\n\r\n")
        body = await _read_chunked_body(reader)
        assert body == b""

    async def test_two_chunks(self):
        data = b"3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n"
        reader = _asyncio_reader(data)
        body = await _read_chunked_body(reader)
        assert body == b"abcde"

    async def test_malformed_chunk_size(self):
        """Should log a warning and return what was accumulated."""
        reader = _asyncio_reader(b"ZZ\r\n")
        body = await _read_chunked_body(reader)
        assert body == b""

    async def test_no_trailing_newline_on_final(self):
        """Data ends without the final 0\\r\\n\\r\\n terminator."""
        reader = _asyncio_reader(b"4\r\ntest\r\n")
        body = await _read_chunked_body(reader)
        assert body == b"test"


@pytest.mark.asyncio
class TestLlamaCppTransport:
    """Mock-socket tests for handle_async_request."""

    async def test_content_length_response(self):
        request = _fake_request("GET", "http://localhost/v1/models")
        transport = LlamaCppTransport()

        with _patch_socket(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"):
            response = await transport.handle_async_request(request)

        assert response.status_code == 200
        assert response.content == b"hello"

    async def test_chunked_response(self):
        request = _fake_request("POST", "http://localhost/v1/chat/completions")
        transport = LlamaCppTransport()
        chunked_body = b"5\r\nhello\r\n0\r\n\r\n"
        raw = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"\r\n" + chunked_body
        )

        with _patch_socket(raw):
            response = await transport.handle_async_request(request)

        assert response.status_code == 200
        assert response.content == b"hello"

    async def test_https_is_accepted(self):
        """LlamaCppTransport must accept https:// URLs (now supports SSL)."""
        request = _fake_request("GET", "https://example.com/v1/models")
        transport = LlamaCppTransport()
        # Should NOT raise UnsupportedProtocol (HTTPS is now supported)
        try:
            await transport.handle_async_request(request)
        except httpx.UnsupportedProtocol:
            pytest.fail("HTTPS should be supported now")
        except (httpx.ConnectError, OSError):
            pass  # Expected — real SSL connection will fail in test env


@pytest.mark.asyncio
class TestMakeClient:
    async def test_factory_returns_client(self):
        client = make_llama_cpp_http_client()
        assert isinstance(client, httpx.AsyncClient)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asyncio_reader(data: bytes) -> asyncio.StreamReader:
    """Create an asyncio.StreamReader pre-populated with data."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


def _fake_request(method: str, url: str) -> httpx.Request:
    """Build a minimal httpx.Request for testing."""
    return httpx.Request(method=method, url=url)


@contextmanager
def _patch_socket(raw_response: bytes):
    """Patch asyncio.open_connection to return a pre-loaded reader/writer."""
    reader = asyncio.StreamReader()
    reader.feed_data(raw_response)
    reader.feed_eof()

    async def fake_connection(host, port, **kw):
        return reader, _FakeWriter()

    with patch("asyncio.open_connection", side_effect=fake_connection):
        yield


class _FakeWriter:
    """Minimal writer stub that tracks written bytes."""

    def __init__(self):
        self.written = b""

    def write(self, data):
        self.written += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def is_closing(self):
        return False
