# tests/test_cli_openai.py
"""
Unit tests for the OpenAI-compatible CLI arguments (openosint/cli.py) and
the resulting OpenOSINTRepl / OpenAICompatibleAgent wiring (openosint/repl.py).

No subprocess or live endpoint required — all tests operate at the
argument-parsing and object-construction level.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# _build_parser — argument parsing
# ---------------------------------------------------------------------------


class TestBuildParserOpenaiArgs:
    """--provider openai and its companion flags are accepted and stored correctly."""

    def test_provider_openai_accepted(self):
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(["--provider", "openai"])
        assert args.provider == "openai"

    def test_openai_base_url_flag(self):
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(
            ["--provider", "openai", "--openai-base-url", "http://localhost:4000/v1"]
        )
        assert args.openai_base_url == "http://localhost:4000/v1"

    def test_openai_model_flag(self):
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(
            ["--provider", "openai", "--openai-model", "llama3.3-70b"]
        )
        assert args.openai_model == "llama3.3-70b"

    def test_openai_api_key_flag(self):
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(
            ["--provider", "openai", "--openai-api-key", "sk-test-123"]
        )
        assert args.openai_api_key == "sk-test-123"

    def test_openai_api_key_defaults_to_none(self):
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(["--provider", "openai"])
        assert args.openai_api_key is None

    def test_provider_choices_include_all_three(self):
        from openosint.cli import _build_parser

        for provider in ("anthropic", "ollama", "openai"):
            args = _build_parser().parse_args(["--provider", provider])
            assert args.provider == provider

    def test_openai_base_url_default_is_localhost(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        from openosint.cli import _build_parser

        args = _build_parser().parse_args([])
        assert args.openai_base_url == "http://localhost:8080/v1"

    def test_openai_model_default_is_gpt4o_mini(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        from openosint.cli import _build_parser

        args = _build_parser().parse_args([])
        assert args.openai_model == "gpt-4o-mini"


class TestBuildParserOpenaiEnvFallbacks:
    """Env vars OPENAI_BASE_URL and OPENAI_MODEL are used as parser defaults."""

    def test_openai_base_url_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://env-server/v1")
        from openosint.cli import _build_parser

        args = _build_parser().parse_args([])
        assert args.openai_base_url == "http://env-server/v1"

    def test_openai_model_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "my-env-model")
        from openosint.cli import _build_parser

        args = _build_parser().parse_args([])
        assert args.openai_model == "my-env-model"

    def test_explicit_flag_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://env-server/v1")
        from openosint.cli import _build_parser

        args = _build_parser().parse_args(["--openai-base-url", "http://flag-server/v1"])
        assert args.openai_base_url == "http://flag-server/v1"


# ---------------------------------------------------------------------------
# OpenOSINTRepl — provider="openai" routes to OpenAICompatibleAgent
# ---------------------------------------------------------------------------


class TestReplOpenaiProviderWiring:
    """OpenOSINTRepl(provider='openai') must construct an OpenAICompatibleAgent."""

    def test_openai_provider_creates_openai_agent(self):
        from openosint.agent import OpenAICompatibleAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="openai",
            openai_base_url="http://localhost:4000/v1",
            openai_model="custom-model",
        )
        assert isinstance(repl._agent, OpenAICompatibleAgent)

    def test_openai_agent_receives_base_url(self):
        from openosint.agent import OpenAICompatibleAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="openai",
            openai_base_url="http://my-server/v1",
            openai_model="gpt-4o-mini",
        )
        assert isinstance(repl._agent, OpenAICompatibleAgent)
        assert repl._agent.base_url == "http://my-server/v1"

    def test_openai_agent_receives_model(self):
        from openosint.agent import OpenAICompatibleAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="openai",
            openai_base_url="http://localhost/v1",
            openai_model="llama3.3-70b",
        )
        assert isinstance(repl._agent, OpenAICompatibleAgent)
        assert repl._agent.model == "llama3.3-70b"

    def test_openai_agent_receives_explicit_api_key(self):
        from openosint.agent import OpenAICompatibleAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="openai",
            openai_base_url="http://localhost/v1",
            openai_model="gpt-4o-mini",
            openai_api_key="sk-explicit-key",
        )
        assert isinstance(repl._agent, OpenAICompatibleAgent)
        assert "sk-explicit-key" in repl._agent.api_key

    def test_openai_display_model_matches_model_name(self):
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="openai",
            openai_base_url="http://localhost/v1",
            openai_model="my-display-model",
        )
        assert repl._display_model == "my-display-model"

    def test_anthropic_provider_creates_anthropic_agent(self):
        from openosint.agent import OpenAICompatibleAgent, OpenOSINTAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(provider="anthropic")
        assert isinstance(repl._agent, OpenOSINTAgent)
        assert not isinstance(repl._agent, OpenAICompatibleAgent)

    def test_ollama_provider_does_not_create_openai_agent(self):
        from openosint.agent import OllamaAgent, OpenAICompatibleAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(provider="ollama")
        assert isinstance(repl._agent, OllamaAgent)
        assert not isinstance(repl._agent, OpenAICompatibleAgent)

    def test_no_api_key_uses_non_empty_sentinel(self, monkeypatch):
        """When no key is provided the agent falls back to a sentinel string."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from openosint.agent import OpenAICompatibleAgent
        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            provider="openai",
            openai_base_url="http://localhost/v1",
            openai_model="gpt-4o-mini",
            openai_api_key=None,
        )
        assert isinstance(repl._agent, OpenAICompatibleAgent)
        assert repl._agent.api_key  # non-empty sentinel is set


# ---------------------------------------------------------------------------
# Local provider tests
# ---------------------------------------------------------------------------


class TestLocalProvider:
    """Tests for --provider local with --base and --key arguments."""

    def test_provider_local_parses_base_and_key(self):
        """Argument parser should accept --provider local --base URL --key KEY."""
        from openosint.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "--provider", "local",
            "--base", "http://localhost:3001/v1",
            "--key", "freellmapi-test-key",
        ])
        assert args.provider == "local"
        assert args.base == "http://localhost:3001/v1"
        assert args.key == "freellmapi-test-key"

    def test_provider_local_accepts_base_without_key(self):
        """--base should work without --key."""
        from openosint.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "--provider", "local",
            "--base", "http://localhost:3001/v1",
        ])
        assert args.provider == "local"
        assert args.base == "http://localhost:3001/v1"
        assert args.key is None

    def test_provider_openai_still_works(self):
        """Existing --provider openai with --openai-base-url must still work."""
        from openosint.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "--provider", "openai",
            "--openai-base-url", "http://localhost:8080/v1",
        ])
        assert args.provider == "openai"
        assert args.openai_base_url == "http://localhost:8080/v1"

    def test_local_is_valid_choice(self):
        """--provider must accept 'local' as a valid choice."""
        from openosint.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--provider", "local"])
        assert args.provider == "local"

    def test_default_provider_is_still_anthropic(self):
        """Without --provider, default should remain 'anthropic'."""
        from openosint.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([])
        assert args.provider == "anthropic"
