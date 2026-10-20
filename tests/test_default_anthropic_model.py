# tests/test_default_anthropic_model.py
"""
Unit tests for openosint.agent.default_anthropic_model() and its use as the
OpenOSINTAgent model fallback.

Covers the fix for the retired claude-sonnet-4-20250514 default: the model
id must resolve at call time from OPENOSINT_MODEL (falling back to the
DEFAULT_ANTHROPIC_MODEL constant), never as a hardcoded literal baked into
a function signature.
"""

from __future__ import annotations


class TestDefaultAnthropicModel:
    def test_returns_constant_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_MODEL", raising=False)
        from openosint.agent import DEFAULT_ANTHROPIC_MODEL, default_anthropic_model

        assert default_anthropic_model() == DEFAULT_ANTHROPIC_MODEL

    def test_returns_env_value_when_set(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_MODEL", "claude-custom-model")
        from openosint.agent import default_anthropic_model

        assert default_anthropic_model() == "claude-custom-model"


class TestOpenOSINTAgentModelFallback:
    def test_agent_uses_default_when_no_model_passed(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_MODEL", raising=False)
        from openosint.agent import DEFAULT_ANTHROPIC_MODEL, OpenOSINTAgent

        agent = OpenOSINTAgent(api_key="sk-test")
        assert agent.model == DEFAULT_ANTHROPIC_MODEL

    def test_agent_picks_up_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_MODEL", "claude-env-model")
        from openosint.agent import OpenOSINTAgent

        agent = OpenOSINTAgent(api_key="sk-test")
        assert agent.model == "claude-env-model"

    def test_explicit_model_argument_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_MODEL", "claude-env-model")
        from openosint.agent import OpenOSINTAgent

        agent = OpenOSINTAgent(api_key="sk-test", model="claude-explicit-model")
        assert agent.model == "claude-explicit-model"


class TestOpenAICompatibleDefaultBaseUrl:
    def test_default_base_url_is_not_8080(self):
        from openosint.agent import OpenAICompatibleAgent

        agent = OpenAICompatibleAgent()
        assert "8080" not in agent.base_url
        assert agent.base_url == "http://localhost:4000/v1"
