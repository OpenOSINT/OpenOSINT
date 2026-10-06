"""The UI pages are served as UTF-8 regardless of the platform's default encoding.

Regression: `Path.read_text()` with no encoding decodes with the locale codepage on
Windows (cp1252). index.html contains characters whose UTF-8 bytes include bytes cp1252
leaves undefined (e.g. U+25CF), so GET / returned 500 on Windows.
"""

from __future__ import annotations

import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

import openosint.web_server as ws


def test_the_page_really_is_undecodable_as_cp1252():
    raw = (ws._WEB_DIR / "index.html").read_bytes()

    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1252")


@pytest.mark.parametrize("path", ["/", "/graph"])
async def test_pages_serve_as_utf8_under_a_cp1252_locale(monkeypatch, path):
    original = pathlib.Path.read_text

    def windows_read_text(self, encoding=None, errors=None):
        return original(self, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(pathlib.Path, "read_text", windows_read_text)
    app = ws.create_app(host="127.0.0.1", port=8080)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8080") as c:
        resp = await c.get(path)

    assert resp.status_code == 200
    assert "ã" not in resp.text and "â" not in resp.text  # no mojibake
    if path == "/":
        assert "●" in resp.text
