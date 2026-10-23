"""Tests for the dedicated MiniMax provider configuration."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock

import httpx
import openai
import pytest


class TestMiniMaxAgentConfiguration:
    def test_default_configuration_uses_global_flash(self):
        from openosint.agent import MINIMAX_BASE_URLS, MINIMAX_MODELS, MiniMaxAgent

        agent = MiniMaxAgent()

        assert agent.model == MINIMAX_MODELS[0]
        assert agent.region == "global"
        assert agent.base_url == MINIMAX_BASE_URLS["global"]

    def test_cn_region_uses_cn_endpoint_and_selected_model(self):
        from openosint.agent import MINIMAX_BASE_URLS, MINIMAX_MODELS, MiniMaxAgent

        agent = MiniMaxAgent(model=MINIMAX_MODELS[1], region="cn")

        assert agent.model == MINIMAX_MODELS[1]
        assert agent.region == "cn"
        assert agent.base_url == MINIMAX_BASE_URLS["cn"]

    def test_api_key_uses_minimax_environment_variable(self, monkeypatch):
        from openosint.agent import MiniMaxAgent

        monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
        monkeypatch.setenv("OPENAI_API_KEY", "generic-key-should-not-win")

        agent = MiniMaxAgent()

        assert agent.api_key == "test-minimax-key"

    def test_unknown_region_is_rejected(self):
        from openosint.agent import MiniMaxAgent

        with pytest.raises(ValueError, match="Unsupported MiniMax region"):
            MiniMaxAgent(region="unknown")


class TestMiniMaxCliConfiguration:
    def test_provider_and_defaults_are_available(self):
        from openosint.agent import MINIMAX_BASE_URLS, MINIMAX_MODELS
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(["--provider", "minimax"])

        assert args.provider == "minimax"
        assert args.minimax_model == MINIMAX_MODELS[0]
        assert args.minimax_region == "global"
        assert tuple(MINIMAX_BASE_URLS) == ("global", "cn")

    def test_model_region_and_key_flags_are_forwarded(self):
        from openosint.agent import MINIMAX_MODELS
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(
            [
                "--provider",
                "minimax",
                "--minimax-model",
                MINIMAX_MODELS[1],
                "--minimax-region",
                "cn",
                "--minimax-api-key",
                "test-key",
            ]
        )

        assert args.minimax_model == MINIMAX_MODELS[1]
        assert args.minimax_region == "cn"
        assert args.minimax_api_key == "test-key"

    def test_environment_defaults_are_used(self, monkeypatch):
        from openosint.agent import MINIMAX_MODELS
        from openosint.cli import _build_parser

        monkeypatch.setenv("MINIMAX_MODEL", MINIMAX_MODELS[1])
        monkeypatch.setenv("MINIMAX_REGION", "cn")

        args = _build_parser().parse_args([])

        assert args.minimax_model == MINIMAX_MODELS[1]
        assert args.minimax_region == "cn"


class TestMiniMaxReplWiring:
    def test_repl_constructs_minimax_agent_with_selected_configuration(self):
        from openosint.agent import MINIMAX_BASE_URLS, MINIMAX_MODELS, MiniMaxAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="minimax",
            minimax_model=MINIMAX_MODELS[1],
            minimax_region="cn",
            minimax_api_key="test-key",
        )

        assert isinstance(repl._agent, MiniMaxAgent)
        assert repl._agent.model == MINIMAX_MODELS[1]
        assert repl._agent.region == "cn"
        assert repl._agent.base_url == MINIMAX_BASE_URLS["cn"]
        assert repl._display_model == MINIMAX_MODELS[1]


def test_recommended_models_and_help():
    from openosint.agent import MINIMAX_MODELS
    from openosint.cli import _build_parser

    assert MINIMAX_MODELS == ("MiniMax-M3.1-Flash", "MiniMax-M3")
    help_text = _build_parser().format_help()
    assert "default: MiniMax-M3.1-Flash" in help_text
    assert "MiniMax-M2.7" not in help_text


@pytest.mark.parametrize("region", ["global", "cn"])
@pytest.mark.parametrize("source", ["flag", "environment"])
@pytest.mark.parametrize(
    "model", [None, "MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "custom-model"]
)
async def test_cli_repl_serialized_request(monkeypatch, region, source, model):
    from openosint.agent import MINIMAX_BASE_URLS
    from openosint.cli import _async_main
    from openosint.repl import OpenOSINTRepl

    monkeypatch.delenv("MINIMAX_MODEL", raising=False)
    monkeypatch.delenv("MINIMAX_REGION", raising=False)
    arguments = ["--provider", "minimax", "--minimax-region", region]
    if model is not None:
        if source == "flag":
            arguments.extend(["--minimax-model", model])
        else:
            monkeypatch.setenv("MINIMAX_MODEL", model)
    arguments.extend(["--minimax-api-key", "test-key"])
    monkeypatch.setattr(sys, "argv", ["openosint", *arguments])
    requests = []
    responses = []

    async def run_once(repl):
        responses.append(await repl._agent.run("Inspect example.com"))

    monkeypatch.setattr(OpenOSINTRepl, "run", run_once)

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "done"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        client = openai.AsyncOpenAI(
            base_url=MINIMAX_BASE_URLS[region], api_key="test-key", http_client=transport
        )

        def make_client(**kwargs):
            assert kwargs == {"base_url": MINIMAX_BASE_URLS[region], "api_key": "test-key"}
            return client

        monkeypatch.setattr(openai, "AsyncOpenAI", make_client)
        await _async_main()

    assert responses[0].error == ""
    assert responses[0].content == "done"
    assert len(requests) == 1
    assert str(requests[0].url) == MINIMAX_BASE_URLS[region] + "/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["model"] == (model or "MiniMax-M3.1-Flash")
    assert payload["messages"][-1] == {"role": "user", "content": "Inspect example.com"}
    assert payload["tools"]
    assert payload["tool_choice"] == "auto"
    assert payload["max_tokens"] == 4096
    # Omission uses adaptive thinking and the API's default effort without invalid overrides.
    for field in ("thinking", "reasoning_effort", "reasoning_split", "service_tier"):
        assert field not in payload


async def test_serialized_tool_and_reasoning_history_survives_followup(monkeypatch):
    from openosint import agent as agent_module

    tool_message = {
        "role": "assistant",
        "content": "<think>Inspect the supplied target.</think>",
        "reasoning_content": "Check its DNS records.",
        "tool_calls": [
            {
                "id": "call_dns",
                "type": "function",
                "function": {"name": "search_dns", "arguments": '{"domain":"example.com"}'},
            }
        ],
    }
    final_message = {
        "role": "assistant",
        "content": "DNS checked.",
        "reasoning_content": "Use the returned records.",
    }
    responses = [tool_message, final_message, {"role": "assistant", "content": "Followup."}]
    payloads = []

    def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": responses.pop(0)}]})

    execute = AsyncMock(return_value="DNS fixture result")
    monkeypatch.setattr(agent_module, "_execute_tool", execute)
    agent = agent_module.MiniMaxAgent(api_key="test-key")
    media_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Saved context"},
            {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
            {"type": "video_url", "video_url": {"url": "mm_file://fixture"}},
        ],
    }
    agent.history.append(media_message)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        client = openai.AsyncOpenAI(
            base_url=agent.base_url, api_key="test-key", http_client=transport
        )
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: client)
        assert (await agent.run("Inspect example.com")).error == ""
        assert (await agent.run("Continue")).error == ""

    execute.assert_awaited_once_with("search_dns", {"domain": "example.com"}, None)
    for payload in payloads[1:]:
        assert tool_message in payload["messages"]
        assert {
            "role": "tool",
            "tool_call_id": "call_dns",
            "content": "DNS fixture result",
        } in payload["messages"]
    assert final_message in payloads[2]["messages"]
    assert all(media_message in payload["messages"] for payload in payloads)
    assert tool_message in agent.history
    agent.clear_history()
    assert agent.history == []
