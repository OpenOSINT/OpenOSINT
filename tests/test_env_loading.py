# tests/test_env_loading.py
"""
Tests for openosint.env, the shared .env loader used by every entry point,
and the ANTHROPIC_MODEL / OPENOSINT_MODEL precedence it enables in agent.py.

Only two tests here use a subprocess — TestCliPicksUpDotenvFromCwd and
TestJsonStdoutStaysClean — because each proves something about a real
process's stdout/stderr streams that an in-process call can't: a fresh
non-editable-style install actually reading .env from a real cwd, and a
--json command's stdout staying pure JSON once the .env banner exists at
all. openosint.env.load_env() memoizes its result for the life of a
process, so a monkeypatched in-process call would only prove the
resolution *logic* is right, not process-lifecycle/stream behavior. Every
other test resets openosint.env's module-level cache via monkeypatch and
calls load_env()/missing_var_message() directly, which is faster and
doesn't need a subprocess since it's exercising pure resolution logic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

_PYTHON = sys.executable


def _reset_env_module_state(monkeypatch):
    import openosint.env as env_module

    monkeypatch.setattr(env_module, "_loaded_path", None)
    monkeypatch.setattr(env_module, "_load_attempted", False)


class TestCliPicksUpDotenvFromCwd:
    """The one subprocess test — see module docstring for why."""

    def test_cli_picks_up_dotenv_from_cwd(self, tmp_path):
        (tmp_path / ".env").write_text("BRIGHTDATA_API_KEY=dummy-cwd-key\n")

        probe = (
            "import json, os\n"
            "import openosint.cli\n"
            "print(json.dumps({'BRIGHTDATA_API_KEY': os.environ.get('BRIGHTDATA_API_KEY')}))\n"
        )
        result = subprocess.run(
            [_PYTHON, "-c", probe],
            cwd=str(tmp_path),
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        last_line = result.stdout.strip().splitlines()[-1]
        assert json.loads(last_line)["BRIGHTDATA_API_KEY"] == "dummy-cwd-key"


class TestLoadEnvPrecedence:
    def test_real_env_var_beats_dotenv_value(self, tmp_path, monkeypatch):
        _reset_env_module_state(monkeypatch)
        (tmp_path / ".env").write_text("MARKER_X=from-file\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MARKER_X", "from-real-env")
        monkeypatch.delenv("OPENOSINT_ENV_FILE", raising=False)

        from openosint.env import load_env

        load_env()

        assert os.environ["MARKER_X"] == "from-real-env"

    def test_openosint_env_file_is_used(self, tmp_path, monkeypatch):
        _reset_env_module_state(monkeypatch)
        custom = tmp_path / "custom.env"
        custom.write_text("MARKER_Y=from-explicit-file\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("OPENOSINT_ENV_FILE", str(custom))
        monkeypatch.delenv("MARKER_Y", raising=False)

        from openosint.env import load_env

        loaded_path = load_env()

        assert loaded_path == custom
        assert os.environ["MARKER_Y"] == "from-explicit-file"


class TestMissingVarMessage:
    def test_mentions_no_dotenv_found_when_none_exists(self, tmp_path, monkeypatch):
        _reset_env_module_state(monkeypatch)
        elsewhere = tmp_path / "no-env-here"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.delenv("OPENOSINT_ENV_FILE", raising=False)

        import openosint.env as env_module

        # This test runs against an editable/source checkout, where
        # env_module.__file__ resolves inside the real repo — the
        # repo-root fallback would otherwise find *this repo's own*
        # .env and defeat the "nothing found" scenario a real pip
        # install (no repo root at all) is meant to exercise.
        fake_pkg_dir = tmp_path / "no-repo-root" / "openosint"
        monkeypatch.setattr(env_module, "__file__", str(fake_pkg_dir / "env.py"))

        message = env_module.missing_var_message("BRIGHTDATA_API_KEY")

        assert "BRIGHTDATA_API_KEY" in message
        assert "no .env found" in message
        assert str(elsewhere) in message
        assert "OPENOSINT_ENV_FILE" in message


class TestAnthropicModelPrecedence:
    def _reset_warning_flag(self, monkeypatch):
        import openosint.agent as agent_module

        monkeypatch.setattr(agent_module, "_warned_openosint_model_deprecated", False)

    def test_anthropic_model_beats_openosint_model(self, monkeypatch):
        self._reset_warning_flag(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-anthropic-model")
        monkeypatch.setenv("OPENOSINT_MODEL", "claude-legacy-model")

        from openosint.agent import default_anthropic_model

        assert default_anthropic_model() == "claude-anthropic-model"

    def test_openosint_model_alone_still_works_and_warns(self, monkeypatch, caplog):
        self._reset_warning_flag(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.setenv("OPENOSINT_MODEL", "claude-legacy-model")

        from openosint.agent import default_anthropic_model

        with caplog.at_level("WARNING", logger="openosint.agent"):
            result = default_anthropic_model()

        assert result == "claude-legacy-model"
        assert any("deprecated" in record.message.lower() for record in caplog.records)

    def test_openosint_model_warning_fires_once(self, monkeypatch, caplog):
        self._reset_warning_flag(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.setenv("OPENOSINT_MODEL", "claude-legacy-model")

        from openosint.agent import default_anthropic_model

        with caplog.at_level("WARNING", logger="openosint.agent"):
            default_anthropic_model()
            default_anthropic_model()

        deprecation_warnings = [r for r in caplog.records if "deprecated" in r.message.lower()]
        assert len(deprecation_warnings) == 1

    def test_neither_set_returns_constant(self, monkeypatch):
        self._reset_warning_flag(monkeypatch)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("OPENOSINT_MODEL", raising=False)

        from openosint.agent import DEFAULT_ANTHROPIC_MODEL, default_anthropic_model

        assert default_anthropic_model() == DEFAULT_ANTHROPIC_MODEL


class TestCliWebPreferCwdOverRepoRoot:
    """CLI/web (prefer_package_root=False, the default) must prefer the cwd
    .env over a repo-root one — the opposite of the MCP server's priority
    (see tests/test_mcp_server_dotenv.py::TestRepoRootAndCwdFallback)."""

    def test_cwd_env_wins_over_repo_root_env(self, tmp_path, monkeypatch):
        _reset_env_module_state(monkeypatch)
        import openosint.env as env_module

        fake_pkg_dir = tmp_path / "pkgroot" / "openosint"
        fake_pkg_dir.mkdir(parents=True)
        (tmp_path / "pkgroot" / ".env").write_text("MARKER_Z=repo-root-value\n")
        monkeypatch.setattr(env_module, "__file__", str(fake_pkg_dir / "env.py"))

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / ".env").write_text("MARKER_Z=cwd-value\n")
        monkeypatch.chdir(work_dir)
        monkeypatch.delenv("OPENOSINT_ENV_FILE", raising=False)
        monkeypatch.delenv("MARKER_Z", raising=False)

        env_module.load_env(prefer_package_root=False)

        assert os.environ["MARKER_Z"] == "cwd-value"


class TestJsonStdoutStaysClean:
    """A .env-loaded banner must never land in --json's stdout — it's a
    subprocess test because it proves something about the real stdout/
    stderr streams a mocked call can't."""

    def test_json_output_is_valid_json_with_dotenv_loaded(self, tmp_path):
        # A var BrightData doesn't read — proves .env is genuinely loaded
        # (the banner fires) while keeping this call network-free: with no
        # BRIGHTDATA_API_KEY set, run_dorks_live_osint returns the
        # missing-key message with no network call.
        (tmp_path / ".env").write_text("UNRELATED_MARKER=loaded\n")

        result = subprocess.run(
            [_PYTHON, "-m", "openosint.cli", "--json", "search-dorks-live", "example.com"],
            cwd=str(tmp_path),
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)  # raises if anything but JSON is on stdout
        assert payload["tool"] == "search_dorks_live"
        assert "BRIGHTDATA_API_KEY" in "\n".join(payload["results"])
        assert "[*] Loaded .env:" in result.stderr


class TestMissingEnvFileExitsCleanly:
    """A missing $OPENOSINT_ENV_FILE must exit(2) with one readable line on
    stderr — never a traceback — for every entry point.

    The earlier version of this test (`returncode != 0`, only checking that
    "does not exist" appeared somewhere in stderr) passed even when cli.py's
    guard raised NameError on `sys` before `import sys` had run: a NameError
    exits with a non-zero code and its traceback still contains the
    FileNotFoundError's "does not exist" text (from
    "During handling of the above exception..."), so both weak assertions
    were satisfied by the crash itself. `returncode == 2` and the explicit
    "Traceback" absence check below are what actually catch that class of
    regression.
    """

    _ENTRY_POINTS = {
        "cli": [_PYTHON, "-m", "openosint.cli", "--help"],
        "mcp_server": [_PYTHON, "-m", "openosint.mcp_server"],
        "web_server_import": [_PYTHON, "-c", "import openosint.web_server"],
    }

    @pytest.mark.parametrize("entry_point", sorted(_ENTRY_POINTS))
    def test_missing_env_file_exits_2_with_no_traceback(self, tmp_path, entry_point):
        missing = tmp_path / "does-not-exist.env"

        result = subprocess.run(
            self._ENTRY_POINTS[entry_point],
            cwd=str(tmp_path),
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
                "OPENOSINT_ENV_FILE": str(missing),
            },
            input="",
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 2, result.stderr
        assert result.stdout == ""
        assert "does not exist" in result.stderr
        assert str(missing) in result.stderr
        assert "Traceback" not in result.stderr


class TestLoadEnvOrExit:
    def test_returns_load_env_result_when_file_is_valid(self, tmp_path, monkeypatch):
        _reset_env_module_state(monkeypatch)
        custom = tmp_path / "custom.env"
        custom.write_text("MARKER_Z=ok\n")
        monkeypatch.setenv("OPENOSINT_ENV_FILE", str(custom))

        from openosint.env import load_env_or_exit

        assert load_env_or_exit() == custom

    def test_missing_file_prints_bang_line_and_exits_2(self, tmp_path, monkeypatch, capsys):
        _reset_env_module_state(monkeypatch)
        missing = tmp_path / "does-not-exist.env"
        monkeypatch.setenv("OPENOSINT_ENV_FILE", str(missing))

        from openosint.env import load_env_or_exit

        with pytest.raises(SystemExit) as exc_info:
            load_env_or_exit()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("[!] ")
        assert str(missing) in captured.err
