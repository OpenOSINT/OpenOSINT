"""search_rdap: the formatted tool wrapper around the RDAP helpers (no network)."""

from __future__ import annotations

import pytest

from openosint.tools import search_rdap
from openosint.tools.exceptions import OSINTError, ToolExecutionError

INFO = {
    "registrar": "Example Registrar",
    "createdDate": "1995-08-14T04:00:00Z",
    "expiresDate": "2027-08-13T04:00:00Z",
    "nameServers": ["a.ns.example", "b.ns.example"],
    "status": ["client delete prohibited"],
}


@pytest.fixture
def lookup(monkeypatch):
    calls = []

    def fake(domain, timeout):
        calls.append(domain)
        return INFO

    monkeypatch.setattr(search_rdap, "_lookup", fake)
    return calls


async def test_formats_registration_data(lookup):
    result = await search_rdap.run_rdap_osint("example.com")

    assert "[+] Registrar: Example Registrar" in result
    assert "[+] Name servers: a.ns.example, b.ns.example" in result
    assert "[+] Expires: 2027-08-13T04:00:00Z" in result
    assert "RDAP omits registrant contact details" in result


@pytest.mark.parametrize("raw", ["https://Example.com/path?x=1", "  EXAMPLE.COM.  ", "http://example.com/"])
async def test_normalizes_urls_and_case(lookup, raw):
    await search_rdap.run_rdap_osint(raw)

    assert lookup == ["example.com"]


@pytest.mark.parametrize("bad", ["", "not a domain", "localhost", "1.2.3.4", "a..b", "-bad-.com"])
async def test_rejects_invalid_input_without_a_network_call(lookup, bad):
    result = await search_rdap.run_rdap_osint(bad)

    assert result.startswith("Invalid domain")
    assert lookup == []


@pytest.mark.parametrize("error", [OSINTError("not registered (RDAP 404)"), ToolExecutionError("HTTP 500")])
async def test_tool_errors_become_scan_errors(monkeypatch, error):
    def boom(*_a):
        raise error

    monkeypatch.setattr(search_rdap, "_lookup", boom)

    assert (await search_rdap.run_rdap_osint("example.com")).startswith("Scan error: ")


async def test_unexpected_errors_never_raise(monkeypatch):
    def boom(*_a):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(search_rdap, "_lookup", boom)

    assert (await search_rdap.run_rdap_osint("example.com")).startswith("Internal error:")


async def test_missing_fields_read_as_not_listed(monkeypatch):
    monkeypatch.setattr(
        search_rdap,
        "_lookup",
        lambda *_a: {"registrar": None, "createdDate": None, "expiresDate": None, "nameServers": [], "status": []},
    )

    result = await search_rdap.run_rdap_osint("example.com")

    assert "Registrar: not listed" in result and "Name servers: none listed" in result


def test_is_registered_everywhere_the_other_tools_are():
    import openosint.agent as agent
    import openosint.mcp_server as mcp
    import openosint.web_server as ws

    assert any(tool["name"] == "search_rdap" for tool in agent.TOOL_DEFINITIONS)
    assert "search_rdap" in mcp._HANDLERS
    assert "search_rdap" in ws._RUNNERS
    assert any(m["name"] == "search_rdap" and not m["requires_env"] for m in ws._TOOL_CATALOG)
    assert "search_rdap" in ws._KEYLESS_TOOLS
