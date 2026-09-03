"""Tests for the dedicated MiniMax provider configuration."""

from __future__ import annotations

import pytest


class TestMiniMaxAgentConfiguration:
    def test_default_configuration_uses_global_m3(self):
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
