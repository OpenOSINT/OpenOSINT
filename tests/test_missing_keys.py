"""Every credentialed tool answers a missing key with one clear, structured message.

Never an exception, never an empty result: the text names what is missing, links
to where to get it and says where to put it.
"""

from __future__ import annotations

import os

import pytest

import openosint.web_server as ws
from openosint.config_store import config_path
from openosint.settings_catalog import SETTINGS, missing_keys_message, public_catalog

KEYED_TOOLS = [(m["name"], m["requires_env"]) for m in ws._TOOL_CATALOG if m["requires_env"]]


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for setting in SETTINGS:
        monkeypatch.delenv(setting.key, raising=False)


def test_the_sweep_covers_every_credentialed_tool():
    assert len(KEYED_TOOLS) == 9


@pytest.mark.parametrize(("tool", "required"), KEYED_TOOLS)
async def test_missing_keys_give_a_structured_human_readable_result(tool, required):
    result = await ws._RUNNERS[tool]("example.com" if tool != "search_breach" else "a@example.com", 5, {})

    assert isinstance(result, str) and result.strip()
    lines = result.splitlines()
    assert lines[0].startswith("Scan error: ") and tool in lines[0]
    assert lines[1] == f"[key_required] {', '.join(required)}"
    assert any(line.startswith("Get one: https://") for line in lines)
    assert str(config_path()) in result
    for name in required:
        assert name in result


@pytest.mark.parametrize(("tool", "required"), KEYED_TOOLS)
async def test_supplying_only_some_keys_still_names_what_is_missing(tool, required, monkeypatch):
    if len(required) < 2:
        pytest.skip("single-credential tool")
    monkeypatch.setenv(required[0], "present")

    result = await ws._RUNNERS[tool]("example.com", 5, {})

    assert f"[key_required] {', '.join(required[1:])}" in result
    assert required[0] not in result.splitlines()[1]
    monkeypatch.delenv(required[0], raising=False)


def test_message_for_an_unknown_variable_still_reads_sensibly():
    text = missing_keys_message("some_tool", ["SOME_NEW_KEY"])

    assert "some_tool cannot run: SOME_NEW_KEY not set." in text
    assert "[key_required] SOME_NEW_KEY" in text


def test_catalog_matches_the_tool_catalog_requirements():
    needed = {name for _tool, names in KEYED_TOOLS for name in names}
    listed = {s.key for s in SETTINGS}

    assert needed <= listed
    assert {"IPINFO_TOKEN", "GITHUB_TOKEN"} <= listed  # optional keys are still offered


def test_catalog_form_lists_the_ai_provider_first_and_every_key_has_a_link():
    fields = public_catalog()

    assert fields[0]["key"] == "ANTHROPIC_API_KEY"
    assert all(f["url"].startswith("https://") for f in fields if f["url"])
    assert all(f["url"] for f in fields if f["key"] not in {"OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY"})
    assert len(fields) == 16


def test_sponsor_and_referral_links_carry_utm_parameters():
    urls = {s.key: s.url for s in SETTINGS}

    assert "utm_source=openosint" in urls["IP2LOCATION_API_KEY"]
    assert "utm_source=" in urls["BRIGHTDATA_API_KEY"]


async def test_web_pre_check_still_reports_key_required_json(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    app = ws.create_app(host="127.0.0.1", port=8080)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8080") as c:
        resp = await c.post("/api/run/search_shodan", json={"input": "8.8.8.8"})

    body = resp.json()
    assert body["key_required"] is True
    assert body["missing_keys"] == ["SHODAN_API_KEY"]
    assert os.environ.get("SHODAN_API_KEY") is None
