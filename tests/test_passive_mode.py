"""Passive mode by default: classification coverage, filtering on every surface,
the opt-in paths, the demo/restricted lock, and the tool-call cap in each loop.

conftest runs this module with OPENOSINT_ALLOW_ACTIVE unset (the real default).
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import openosint.web_server as ws
from openosint import agent as agent_mod
from openosint import tool_policy as tp
from openosint.tool_policy import TOOL_POLICY, Noise, ToolBudget

NON_PASSIVE = sorted(n for n, p in TOOL_POLICY.items() if not p.is_passive)
PASSIVE_TOOL = "search_ip"


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setenv(tp.ENV_ALLOW_ACTIVE, "1")


def _is_disabled(text: str) -> bool:
    return json.loads(text)["status"] == "disabled_in_passive_mode"


# ---------------------------------------------------------------------------
# Classification coverage: a tool without a label fails CI
# ---------------------------------------------------------------------------


def _registered_tool_names() -> dict[str, set[str]]:
    from cloud import tools as cloud_tools
    from openosint import mcp_server
    from openosint.pivot import _TOOL_ROUTES
    from openosint.playbooks import runner

    return {
        "agent.TOOL_DEFINITIONS": {d["name"] for d in agent_mod.TOOL_DEFINITIONS},
        "agent._TOOL_MAP": set(agent_mod._TOOL_MAP),
        "web._TOOL_CATALOG": {m["name"] for m in ws._TOOL_CATALOG},
        "web._RUNNERS": set(ws._RUNNERS),
        "mcp.list_tools": {t.name for t in mcp_server._all_tools()},
        "cloud.ALLOW_LIST": set(cloud_tools.ALLOW_LIST),
        "pivot._TOOL_ROUTES": {t for routes in _TOOL_ROUTES.values() for t in routes},
        "playbooks.TOOL_MAP": set(runner.TOOL_MAP),
    }


def test_every_registered_tool_has_a_noise_label():
    missing = {
        registry: sorted(names - set(TOOL_POLICY))
        for registry, names in _registered_tool_names().items()
        if names - set(TOOL_POLICY)
    }
    assert not missing, f"tools without an entry in tool_policy.TOOL_POLICY: {missing}"


def test_every_policy_entry_has_a_note():
    assert all(p.note.strip() for p in TOOL_POLICY.values())


def test_every_tool_module_is_known():
    """A new openosint/tools/*.py must be classified by hand before CI passes."""
    import pkgutil

    import openosint.tools as tools_pkg

    labeled_modules = {
        "generate_dorks", "scrape_url", "search_abuseipdb", "search_breach", "search_censys", "search_dns",
        "search_domain", "search_dorks_live", "search_email", "search_footprint", "search_gdelt_geo",
        "search_github", "search_ip", "search_ip2location", "search_paste", "search_phone", "search_rdap",
        "search_shodan", "search_username", "search_virustotal", "search_whois",
        # helpers, not tools
        "exceptions", "gdelt_gkg", "search_gdelt_doc",
    }
    modules = {m.name for m in pkgutil.iter_modules(tools_pkg.__path__)}
    assert modules <= labeled_modules, f"new tool module(s) need a TOOL_POLICY entry: {modules - labeled_modules}"


@pytest.mark.parametrize("name", ["search_username", "search_email", "search_domain", "search_phone", "scrape_url"])
def test_non_passive_tools_are_not_passive(name):
    assert TOOL_POLICY[name].noise in (Noise.NOISY, Noise.TOUCHES_TARGET, Noise.UNVERIFIED)


def test_phone_is_unverified_not_passive():
    assert TOOL_POLICY["search_phone"].noise is Noise.UNVERIFIED


def test_virustotal_url_mode_is_split_out_and_labeled_for_community_visibility():
    assert TOOL_POLICY["search_virustotal"].is_passive
    url_mode = TOOL_POLICY["search_virustotal_url"]
    assert not url_mode.is_passive
    assert "VirusTotal community" in url_mode.note
    assert "VirusTotal community" in TOOL_POLICY["search_virustotal"].active_part


# ---------------------------------------------------------------------------
# Default is passive; the env opt-in
# ---------------------------------------------------------------------------


def test_default_is_passive():
    assert not tp.active_enabled()
    assert all(not tp.is_tool_enabled(n) for n in NON_PASSIVE)
    assert tp.is_tool_enabled(PASSIVE_TOOL)


def test_unknown_tool_is_never_enabled(active):
    assert not tp.is_tool_enabled("brand_new_tool")


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("0", False), ("", False), ("no", False)])
def test_env_opt_in_values(monkeypatch, value, expected):
    monkeypatch.setenv(tp.ENV_ALLOW_ACTIVE, value)
    assert tp.active_enabled() is expected


def test_labels_name_the_noise_level_and_the_opt_in():
    assert "noisy" in tp.label("search_username") and "--allow-active" in tp.label("search_username")
    assert tp.label(PASSIVE_TOOL) == "[passive]"
    assert "may notify the account owner" in TOOL_POLICY["search_email"].note
    assert "your DNS resolver" in TOOL_POLICY["search_dns"].note


def test_filter_definitions_hides_active_tools_and_labels_the_rest(monkeypatch):
    defs = tp.filter_definitions(agent_mod.TOOL_DEFINITIONS)
    names = {d["name"] for d in defs}
    assert not names & set(NON_PASSIVE)
    assert "search_dns" in names
    assert all("[passive" in d["description"] or "[inherits" in d["description"] for d in defs)
    monkeypatch.setenv(tp.ENV_ALLOW_ACTIVE, "1")
    assert set(NON_PASSIVE) & {d["name"] for d in tp.filter_definitions(agent_mod.TOOL_DEFINITIONS)}


# ---------------------------------------------------------------------------
# Tool-level gates (choke point for CLI, web, MCP, cloud, playbooks, pivot)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,module,func,arg",
    [
        ("search_username", "search_username", "run_username_osint", "a"),
        ("search_email", "search_email", "run_email_osint", "a@b.co"),
        ("search_domain", "search_domain", "run_domain_osint", "a.co"),
        ("search_phone", "search_phone", "run_phone_osint", "+14155552671"),
        ("scrape_url", "scrape_url", "run_scrape_url_osint", "http://a.co"),
    ],
)
async def test_run_function_returns_structured_disabled_result(tool, module, func, arg):
    mod = __import__(f"openosint.tools.{module}", fromlist=[func])
    data = json.loads(await getattr(mod, func)(arg))
    assert data["status"] == "disabled_in_passive_mode"
    assert data["tool"] == tool
    assert "--allow-active" in data["how_to_enable"]
    assert data["noise"] == TOOL_POLICY[tool].noise.value


async def test_virustotal_url_is_disabled_but_hash_lookup_is_not(monkeypatch):
    from openosint.tools import search_virustotal as vt

    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "k")
    posted = []
    monkeypatch.setattr(vt, "_lookup_url", AsyncMock(side_effect=lambda *a: posted.append(a)))
    monkeypatch.setattr(vt, "_lookup_hash", lambda *a: "hash-result")

    url_result = await vt.run_virustotal_osint("https://victim.example/login")
    assert json.loads(url_result)["tool"] == "search_virustotal_url"
    assert "community" in json.loads(url_result)["reason"]
    assert posted == []
    assert await vt.run_virustotal_osint("a" * 64) == "hash-result"


def _stub_dns(monkeypatch, probes):
    from openosint.tools import search_dns as dns_tool

    monkeypatch.setattr(dns_tool, "_probe_dkim", lambda *a: probes.append(a) or ([], False))
    monkeypatch.setattr(dns_tool, "_query", lambda *a: [])
    monkeypatch.setattr(dns_tool.dns.resolver.Resolver, "resolve", lambda *a, **k: [])
    return dns_tool


async def test_dns_skips_dkim_probes_in_passive_mode_and_says_so(monkeypatch):
    probes: list = []
    dns_tool = _stub_dns(monkeypatch, probes)
    result = await dns_tool.run_dns_osint("example.com")
    assert probes == []
    assert "DKIM not checked" in result
    assert "No DKIM records found" not in result


async def test_dns_probes_dkim_when_active(monkeypatch, active):
    probes: list = []
    dns_tool = _stub_dns(monkeypatch, probes)
    await dns_tool.run_dns_osint("example.com")
    assert len(probes) == 1


# ---------------------------------------------------------------------------
# Agent: filtered tools, disabled result when requested anyway, call cap
# ---------------------------------------------------------------------------


async def test_agent_execute_tool_refuses_disabled_tool_without_running_it(monkeypatch):
    handler = AsyncMock(return_value="ran")
    monkeypatch.setitem(agent_mod._TOOL_MAP, "search_username", handler)
    out = await agent_mod._execute_tool("search_username", {"username": "x"}, None)
    assert _is_disabled(out)
    handler.assert_not_called()


def _tool_use_response(name="search_ip", n=1):
    blocks = [
        SimpleNamespace(type="tool_use", id=f"id{i}", name=name, input={"ip": "1.1.1.1"}) for i in range(n)
    ]
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


def _anthropic_agent(response):
    agent = agent_mod.OpenOSINTAgent(api_key="k")
    seen_tools = []

    async def create(**kwargs):
        seen_tools.append([t["name"] for t in kwargs["tools"]])
        return response

    agent.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return agent, seen_tools


async def test_anthropic_agent_offers_only_passive_tools(monkeypatch):
    monkeypatch.setitem(agent_mod._TOOL_MAP, PASSIVE_TOOL, AsyncMock(return_value="r"))
    end = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="done")])
    agent, seen = _anthropic_agent(end)
    await agent.run("hi")
    assert PASSIVE_TOOL in seen[0] and not set(seen[0]) & set(NON_PASSIVE)


async def test_anthropic_agent_stops_with_explicit_message_at_the_cap(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "3")
    handler = AsyncMock(return_value="r")
    monkeypatch.setitem(agent_mod._TOOL_MAP, PASSIVE_TOOL, handler)
    agent, _ = _anthropic_agent(_tool_use_response())  # the model asks for a tool forever
    response = await agent.run("hi")
    assert response.limit_reached
    assert handler.await_count == 3
    assert "Tool call limit reached (3" in response.content
    # the refused 4th request is recorded, with the cap message as its result
    assert len(response.tool_calls) == 4
    assert "limit reached" in response.tool_calls[-1].result


async def test_cap_resets_for_each_user_message(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    monkeypatch.setitem(agent_mod._TOOL_MAP, PASSIVE_TOOL, AsyncMock(return_value="r"))
    agent, _ = _anthropic_agent(_tool_use_response())
    first = await agent.run("one")
    second = await agent.run("two")
    assert first.limit_reached and second.limit_reached
    assert len([tc for tc in second.tool_calls if "limit reached" not in tc.result]) == 2


def test_default_cap_is_15_and_bad_values_fall_back(monkeypatch):
    monkeypatch.delenv(tp.ENV_MAX_CALLS, raising=False)
    assert tp.max_tool_calls() == 15
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "garbage")
    assert tp.max_tool_calls() == 15
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "0")
    assert tp.max_tool_calls() == 15


def _install_fake_ollama(monkeypatch, name="search_ip"):
    msg = SimpleNamespace(
        content="",
        tool_calls=[SimpleNamespace(function=SimpleNamespace(name=name, arguments={"ip": "1.1.1.1"}))],
    )
    tools_seen = []

    class FakeClient:
        def __init__(self, host=None):
            pass

        async def chat(self, model, messages, tools):
            tools_seen.append([t["function"]["name"] for t in tools])
            return SimpleNamespace(message=msg)

    monkeypatch.setitem(sys.modules, "ollama", types.SimpleNamespace(AsyncClient=FakeClient))
    return tools_seen


async def test_ollama_agent_cap_and_filtering(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    handler = AsyncMock(return_value="r")
    monkeypatch.setitem(agent_mod._TOOL_MAP, PASSIVE_TOOL, handler)
    tools_seen = _install_fake_ollama(monkeypatch)
    response = await agent_mod.OllamaAgent().run("hi")
    assert response.limit_reached and handler.await_count == 2
    assert not set(tools_seen[0]) & set(NON_PASSIVE)


async def test_ollama_agent_disabled_tool_request_is_refused_and_still_bounded(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    handler = AsyncMock(return_value="r")
    monkeypatch.setitem(agent_mod._TOOL_MAP, "search_username", handler)
    _install_fake_ollama(monkeypatch, name="search_username")
    response = await agent_mod.OllamaAgent().run("hi")
    handler.assert_not_called()
    refused = [tc for tc in response.tool_calls if "limit reached" not in tc.result]
    assert len(refused) == 2 and all(_is_disabled(tc.result) for tc in refused)
    assert response.limit_reached  # refused requests spend the budget: no infinite loop


async def test_openai_agent_cap_and_filtering(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    handler = AsyncMock(return_value="r")
    monkeypatch.setitem(agent_mod._TOOL_MAP, PASSIVE_TOOL, handler)
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name=PASSIVE_TOOL, arguments='{"ip": "1.1.1.1"}'))
    msg = SimpleNamespace(content="", tool_calls=[call])
    tools_seen = []

    class FakeCompletions:
        async def create(self, **kw):
            tools_seen.append([t["function"]["name"] for t in kw["tools"]])
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class FakeOpenAI:
        def __init__(self, **kw):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake = types.SimpleNamespace(
        AsyncOpenAI=FakeOpenAI,
        AuthenticationError=type("A", (Exception,), {}),
        APIConnectionError=type("B", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "openai", fake)
    response = await agent_mod.OpenAICompatibleAgent().run("hi")
    assert response.limit_reached and handler.await_count == 2
    assert not set(tools_seen[0]) & set(NON_PASSIVE)


# ---------------------------------------------------------------------------
# investigate_graph (pivot): passive routes only, spends the shared budget
# ---------------------------------------------------------------------------


def test_pivot_routes_only_passive_tools_by_default(monkeypatch):
    from openosint.pivot import Entity, EntityType, _get_routable_tools

    for key in ("HIBP_API_KEY", "BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"):
        monkeypatch.setenv(key, "x")
    email = Entity(type=EntityType.EMAIL, value="a@b.co", normalized="a@b.co", confidence=1.0)
    assert "search_email" not in _get_routable_tools(email)
    assert "search_breach" in _get_routable_tools(email)
    domain = Entity(type=EntityType.DOMAIN, value="b.co", normalized="b.co", confidence=1.0)
    assert "search_domain" not in _get_routable_tools(domain)
    monkeypatch.setenv(tp.ENV_ALLOW_ACTIVE, "1")
    assert "search_email" in _get_routable_tools(email)


async def test_pivot_spends_the_request_budget(monkeypatch):
    from openosint import pivot

    calls = []

    async def fake_run(tool, entity, timeout):
        calls.append(tool)
        return ""

    monkeypatch.setattr(pivot, "_run_tool_safe", fake_run)
    monkeypatch.setattr(pivot, "_get_routable_tools", lambda e: ["search_ip", "search_shodan", "search_abuseipdb"])
    with tp.use_budget(ToolBudget(limit=2)):
        await pivot.investigate_graph("8.8.8.8", max_tool_calls=50)
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# investigate_multi: one global cap across all targets
# ---------------------------------------------------------------------------


async def test_multi_target_shares_one_budget(monkeypatch, tmp_path):
    from openosint import multi_target

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(tp.ENV_MAX_CALLS_MULTI, "4")
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "15")
    handler = AsyncMock(return_value="r")
    monkeypatch.setitem(agent_mod._TOOL_MAP, PASSIVE_TOOL, handler)

    class FakeAgent(agent_mod.OpenOSINTAgent):
        def __init__(self, api_key=None):
            self.history = []
            self.client = SimpleNamespace(
                messages=SimpleNamespace(create=AsyncMock(return_value=_tool_use_response()))
            )
            self.model = "m"

    monkeypatch.setattr(multi_target, "OpenOSINTAgent", FakeAgent)
    summary = await multi_target.run_multi_target(["a.co", "b.co", "c.co", "d.co", "e.co"], is_pdf_disabled=True)
    assert handler.await_count == 4  # not 5 targets x 15
    assert "Tool call limit reached" in summary


# ---------------------------------------------------------------------------
# MCP: tools/list hides active tools; call returns a structured error; --allow-active
# ---------------------------------------------------------------------------


async def test_mcp_tools_list_hides_non_passive_tools():
    from openosint import mcp_server

    names = {t.name for t in await mcp_server.list_tools()}
    assert not names & set(NON_PASSIVE)
    assert {"search_ip", "search_dns", "search_whois", "investigate_multi"} <= names


async def test_mcp_tools_list_descriptions_carry_labels():
    from openosint import mcp_server

    tools = {t.name: t.description for t in await mcp_server.list_tools()}
    assert tools["search_ip"].count("[passive]") == 1
    assert "DNS resolver" in tools["search_dns"] and "DKIM" in tools["search_dns"]


async def test_mcp_call_of_hidden_tool_returns_structured_error():
    from openosint import mcp_server

    result = await mcp_server.call_tool("search_username", {"username": "x"})
    assert result.isError
    assert json.loads(result.content[0].text)["status"] == "disabled_in_passive_mode"


async def test_mcp_lists_active_tools_with_noise_labels_when_opted_in(active):
    from openosint import mcp_server

    tools = {t.name: t.description for t in await mcp_server.list_tools()}
    assert set(NON_PASSIVE) & set(tools) >= {"search_username", "search_email", "search_domain", "scrape_url"}
    assert "[noisy" in tools["search_username"]
    assert "may notify the account owner" in tools["search_email"]


def test_mcp_allow_active_flag_sets_the_opt_in(monkeypatch):
    from openosint import mcp_server

    async def noop():
        return None

    monkeypatch.setattr(mcp_server, "_serve", noop)
    mcp_server.main([])
    assert not tp.env_allows_active()
    mcp_server.main(["--allow-active"])
    assert tp.env_allows_active()
    monkeypatch.delenv(tp.ENV_ALLOW_ACTIVE)


# ---------------------------------------------------------------------------
# CLI: flag, direct subcommands
# ---------------------------------------------------------------------------


async def test_cli_direct_subcommand_is_refused_in_passive_mode(monkeypatch, capsys):
    from openosint import cli

    monkeypatch.setattr(sys, "argv", ["openosint", "username", "someone"])
    called = AsyncMock()
    monkeypatch.setattr(cli, "run_username_osint", called)
    with pytest.raises(SystemExit) as exc:
        await cli._async_main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--allow-active" in err and "search_username" in err
    called.assert_not_called()


async def test_cli_allow_active_flag_enables_direct_subcommand(monkeypatch, capsys):
    from openosint import cli

    monkeypatch.setattr(sys, "argv", ["openosint", "--allow-active", "scrape", "http://x.example"])
    monkeypatch.setattr(cli, "run_scrape_url_osint", AsyncMock(return_value="page"))
    await cli._async_main()
    assert "page" in capsys.readouterr().out
    assert tp.env_allows_active()
    monkeypatch.delenv(tp.ENV_ALLOW_ACTIVE)


async def test_playbook_skips_disabled_steps_with_an_explanation():
    from openosint.playbooks.runner import StepState, _run_step

    state, _ = await _run_step("search_username", "x")
    assert state is StepState.DISABLED


# ---------------------------------------------------------------------------
# Cloud gateway: same gate, active off by default, never billed
# ---------------------------------------------------------------------------


async def test_cloud_dispatch_refuses_active_tool_as_a_non_billable_error():
    from cloud import tools as cloud_tools

    result = await cloud_tools.dispatch("search_domain", "example.com")
    assert result["results"][0].startswith("Scan error")
    assert "passive mode" in result["results"][0]


async def test_cloud_mcp_listing_hides_active_tools(monkeypatch):
    from cloud.routes import mcp_gateway

    names = {t.name for t in await mcp_gateway._mcp.list_tools()}
    assert "search_domain" not in names and "search_ip" in names
    monkeypatch.setenv(tp.ENV_ALLOW_ACTIVE, "1")
    assert "search_domain" in {t.name for t in await mcp_gateway._mcp.list_tools()}


# ---------------------------------------------------------------------------
# Web: tool list, /api/run, /api/policy toggle, and the public-demo lock
# ---------------------------------------------------------------------------


def _client(host="127.0.0.1", peer=None):
    app = ws.create_app(host=host, port=8080)
    transport = ASGITransport(app=app, client=peer) if peer else ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://127.0.0.1:8080")


async def test_web_tool_list_labels_and_disables_active_tools():
    async with _client() as c:
        tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
    assert tools["search_username"]["enabled"] is False
    assert tools["search_username"]["available"] is False
    assert "passive mode" in tools["search_username"]["unavailable_reason"]
    assert tools["search_username"]["noise"] == "noisy"
    assert tools["search_ip"]["enabled"] is True and "[passive]" in tools["search_ip"]["description"]


async def test_web_run_and_stream_reject_active_tools_in_passive_mode():
    async with _client() as c:
        run = await c.post("/api/run/search_username", json={"input": "x"})
        stream = await c.get("/api/stream/search_username", params={"input": "x"})
    assert run.status_code == 403
    assert run.json()["status"] == "disabled_in_passive_mode"
    assert "disabled_in_passive_mode" in stream.text


async def test_web_policy_endpoint_reports_cap_and_active_tools():
    async with _client() as c:
        policy = (await c.get("/api/policy")).json()
    assert policy["allow_active"] is False and policy["max_tool_calls"] == 15
    assert {t["name"] for t in policy["active_tools"]} == set(NON_PASSIVE)


async def test_web_settings_toggle_enables_then_disables_active_tools(monkeypatch):
    monkeypatch.setattr(ws, "value_source", lambda key: None)
    async with _client() as c:
        on = await c.post("/api/policy", json={"allow_active": True})
        assert on.status_code == 200 and on.json()["allow_active"] is True
        tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
        assert tools["search_username"]["enabled"] is True
        off = await c.post("/api/policy", json={"allow_active": False})
        assert off.json()["allow_active"] is False
        assert (await c.get("/api/policy")).json()["allow_active"] is False
    monkeypatch.delenv(tp.ENV_ALLOW_ACTIVE, raising=False)


async def test_web_policy_toggle_rejects_non_boolean_body():
    async with _client() as c:
        assert (await c.post("/api/policy", json={"allow_active": "yes"})).status_code == 400


# -- public demo / restricted requests: active can NEVER be enabled -----------------


@pytest.fixture
def operator_enabled_active(monkeypatch):
    """Worst case: the operator set the env var AND tries a toggle/headers."""
    monkeypatch.setenv(tp.ENV_ALLOW_ACTIVE, "1")


async def test_demo_mode_bind_never_enables_active_tools(operator_enabled_active):
    async with _client(host="0.0.0.0") as c:
        tools = {t["name"]: t for t in (await c.get("/api/tools")).json()}
        policy = (await c.get("/api/policy")).json()
        run = await c.post("/api/run/search_username", json={"input": "x"})
        toggle = await c.post("/api/policy", json={"allow_active": True})
    assert all(not tools[n]["enabled"] for n in NON_PASSIVE if n in tools)
    assert policy["allow_active"] is False and policy["restricted"] is True and policy["can_change"] is False
    assert run.status_code == 403
    assert toggle.status_code == 403


async def test_forced_demo_env_never_enables_active_tools(monkeypatch, operator_enabled_active):
    monkeypatch.setenv("OPENOSINT_DEMO_MODE", "true")
    async with _client() as c:  # even on a loopback bind
        policy = (await c.get("/api/policy")).json()
        run = await c.post("/api/run/scrape_url", json={"input": "http://x.example"})
    assert policy["allow_active"] is False
    assert run.status_code == 403


@pytest.mark.parametrize("headers", [{"X-Forwarded-For": "203.0.113.9"}, {"CF-Connecting-IP": "203.0.113.9"}])
async def test_forwarded_requests_are_restricted_and_cannot_use_active_tools(operator_enabled_active, headers):
    async with _client() as c:
        policy = (await c.get("/api/policy", headers=headers)).json()
        run = await c.post("/api/run/search_username", json={"input": "x"}, headers=headers)
    assert policy["restricted"] is True and policy["allow_active"] is False
    assert run.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [{"X-OpenOSINT-Allow-Active": "1"}, {"X-Allow-Active": "true"}, {"X-OPENOSINT-ALLOW-ACTIVE": "1", "Authorization": "Bearer x"}],
)
async def test_allow_active_headers_are_ignored_in_passive_mode(headers):
    """No header is a way in: with the env unset, the same request stays disabled."""
    async with _client() as c:
        policy = (await c.get("/api/policy", headers=headers)).json()
        run = await c.post("/api/run/search_username", json={"input": "x"}, headers=headers)
    assert policy["allow_active"] is False
    assert run.status_code == 403


async def test_restricted_request_cannot_toggle_even_with_a_setup_token(monkeypatch, operator_enabled_active):
    monkeypatch.setenv("OPENOSINT_SETUP_TOKEN", "tok")
    async with _client(host="0.0.0.0") as c:
        resp = await c.post("/api/policy", json={"allow_active": True}, headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 403


async def test_chat_tool_runner_is_locked_when_forced_passive(operator_enabled_active):
    with tp.forced_passive():
        out = await ws._run_tool("search_username", "x")
    assert _is_disabled(out)
    assert "not available on this public" in json.loads(out)["how_to_enable"]


def test_forced_passive_beats_the_environment(operator_enabled_active):
    assert tp.active_enabled()
    with tp.forced_passive():
        assert not tp.active_enabled()
        assert not any(tp.is_tool_enabled(n) for n in NON_PASSIVE)
    assert tp.active_enabled()


# -- web chat loops: cap + filtering ---------------------------------------------------


async def _collect(gen):
    return [e async for e in gen]


class _FakeResp:
    status_code = 200
    text = ""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _fake_httpx(payloads_seen, make_response):
    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            payloads_seen.append(json)
            return _FakeResp(make_response())

    return types.SimpleNamespace(AsyncClient=FakeClient)


async def test_web_ollama_loop_is_capped_and_filtered(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    runner = AsyncMock(return_value="r")
    monkeypatch.setitem(ws._RUNNERS, PASSIVE_TOOL, lambda v, t: runner(v, t))
    seen: list = []
    tool_call = {"function": {"name": PASSIVE_TOOL, "arguments": {"input": "1.1.1.1"}}}
    monkeypatch.setattr(
        ws, "_httpx", _fake_httpx(seen, lambda: {"message": {"content": "", "tool_calls": [tool_call]}})
    )
    events = await _collect(ws._stream_ollama([{"role": "user", "content": "go"}], "http://o", "m"))
    assert runner.await_count == 2
    assert events[-1]["type"] == "error" and "Tool call limit reached (2" in events[-1]["message"]
    assert not {t["function"]["name"] for t in seen[0]["tools"]} & set(NON_PASSIVE)


async def test_web_openai_loop_is_capped_and_filtered(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    runner = AsyncMock(return_value="r")
    monkeypatch.setitem(ws._RUNNERS, PASSIVE_TOOL, lambda v, t: runner(v, t))
    seen: list = []
    tool_call = {"id": "c", "function": {"name": PASSIVE_TOOL, "arguments": '{"input": "1.1.1.1"}'}}
    monkeypatch.setattr(
        ws,
        "_httpx",
        _fake_httpx(seen, lambda: {"choices": [{"message": {"content": "", "tool_calls": [tool_call]}}]}),
    )
    events = await _collect(ws._stream_openai([{"role": "user", "content": "go"}], "http://o/v1", "", "m"))
    assert runner.await_count == 2
    assert events[-1]["type"] == "error" and "Tool call limit reached (2" in events[-1]["message"]
    assert not {t["function"]["name"] for t in seen[0]["tools"]} & set(NON_PASSIVE)


async def test_web_claude_loop_is_capped_and_filtered(monkeypatch):
    monkeypatch.setenv(tp.ENV_MAX_CALLS, "2")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    runner = AsyncMock(return_value="r")
    monkeypatch.setitem(ws._RUNNERS, PASSIVE_TOOL, lambda v, t: runner(v, t))
    tools_seen: list = []

    class FakeStream:
        def __init__(self, kwargs):
            tools_seen.append([t["name"] for t in kwargs["tools"]])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            async def gen():
                yield SimpleNamespace(
                    type="content_block_start",
                    content_block=SimpleNamespace(type="tool_use", id="t", name=PASSIVE_TOOL),
                )
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="input_json_delta", partial_json='{"input": "1.1.1.1"}'),
                )
                yield SimpleNamespace(type="content_block_stop")

            return gen()

        async def get_final_message(self):
            return SimpleNamespace(stop_reason="tool_use")

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = SimpleNamespace(stream=lambda **kw: FakeStream(kw))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=FakeAnthropic))
    events = await _collect(ws._stream_claude([{"role": "user", "content": "go"}]))
    assert runner.await_count == 2
    assert events[-1]["type"] == "error" and "Tool call limit reached (2" in events[-1]["message"]
    assert not set(tools_seen[0]) & set(NON_PASSIVE)

