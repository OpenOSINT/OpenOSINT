"""`openosint config import`: explicit, confirmed, names-only copy of a legacy .env."""

from __future__ import annotations

import os
import stat

import pytest

from openosint import config_store
from openosint.config_cli import run_config_import

LEGACY_TEXT = "SHODAN_API_KEY=legacy-secret\nHIBP_API_KEY=other-secret\nUNRELATED=1\n"


@pytest.fixture(autouse=True)
def _clean_settings():
    from openosint.settings_catalog import SETTINGS

    saved = dict(os.environ)
    for setting in SETTINGS:
        os.environ.pop(setting.key, None)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("OPENOSINT_HOME", str(path))
    return path


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / ".env"
    path.write_text(LEGACY_TEXT)
    return path


def _run(source, *, only=None, yes=False, interactive=False, answers=()):
    replies = iter(answers)
    return run_config_import(
        source, only, yes, interactive=interactive, ask=lambda _prompt: next(replies)
    )


def test_refuses_without_yes_when_not_interactive(legacy, home, capsys):
    code = _run(legacy)

    assert code == 2
    assert not home.exists()
    assert "--yes" in capsys.readouterr().err


def test_yes_copies_and_reports_names_never_values(legacy, home, capsys):
    code = _run(legacy, yes=True)

    out = capsys.readouterr().out
    assert code == 0
    assert config_store.read_config() == {
        "SHODAN_API_KEY": "legacy-secret",
        "HIBP_API_KEY": "other-secret",
    }
    assert "SHODAN_API_KEY" in out and "HIBP_API_KEY" in out
    assert "legacy-secret" not in out and "other-secret" not in out
    assert legacy.read_text() == LEGACY_TEXT  # untouched


def test_interactive_yes_confirms_and_copies(legacy, home):
    assert _run(legacy, interactive=True, answers=["y"]) == 0
    assert "SHODAN_API_KEY" in config_store.read_config()


def test_interactive_no_aborts_and_writes_nothing(legacy, home):
    assert _run(legacy, interactive=True, answers=["n"]) == 1
    assert not home.exists()


def test_only_limits_the_copy(legacy, home):
    assert _run(legacy, only=["HIBP_API_KEY"], yes=True) == 0
    assert config_store.read_config() == {"HIBP_API_KEY": "other-secret"}


def test_only_with_an_unknown_name_is_rejected(legacy, home, capsys):
    assert _run(legacy, only=["NOPE_KEY"], yes=True) == 2
    assert not home.exists()
    assert "NOPE_KEY" in capsys.readouterr().err


def test_missing_source_file_is_an_error(tmp_path, home, capsys):
    assert _run(tmp_path / "missing.env", yes=True) == 2
    assert "missing.env" in capsys.readouterr().err


def test_no_source_found_is_an_error(home, capsys):
    assert _run(None, yes=True) == 2
    assert "--from" in capsys.readouterr().err


def test_existing_config_values_are_skipped_and_reported(legacy, home, capsys):
    config_store.write_config({"SHODAN_API_KEY": "from-ui"})

    assert _run(legacy, yes=True) == 0

    assert config_store.read_config()["SHODAN_API_KEY"] == "from-ui"
    assert "skipped" in capsys.readouterr().out.lower()


def test_nothing_to_import_exits_cleanly(tmp_path, home, capsys):
    empty = tmp_path / ".env"
    empty.write_text("UNRELATED=1\n")

    assert _run(empty, yes=True) == 0
    assert "nothing to import" in capsys.readouterr().out.lower()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
class TestExposedDirectory:
    @pytest.fixture
    def exposed(self, home):
        home.mkdir()
        home.chmod(0o755)
        return home

    def test_yes_warns_but_never_changes_the_mode(self, legacy, exposed, capsys):
        _run(legacy, yes=True)

        assert stat.S_IMODE(exposed.stat().st_mode) == 0o755
        assert "chmod 700" in capsys.readouterr().err

    def test_interactive_can_tighten_after_asking(self, legacy, exposed):
        _run(legacy, interactive=True, answers=["y", "y"])  # confirm copy, then confirm chmod

        assert stat.S_IMODE(exposed.stat().st_mode) == 0o700

    def test_interactive_decline_leaves_the_mode(self, legacy, exposed):
        _run(legacy, interactive=True, answers=["y", "n"])

        assert stat.S_IMODE(exposed.stat().st_mode) == 0o755


def test_cli_subcommand_is_wired_end_to_end(tmp_path):
    """Runs the real entry point: unit tests alone missed an unbound parser name once."""
    import subprocess
    import sys

    fake_env = tmp_path / "fake.env"
    fake_env.write_text("SHODAN_API_KEY=FAKE-not-a-real-key\n")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "OPENOSINT_HOME": str(tmp_path / "home"),
        "OPENOSINT_ENV_FILE": str(fake_env),
    }

    result = subprocess.run(
        [sys.executable, "-m", "openosint.cli", "config", "import", "--yes"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Imported 1 setting(s)" in result.stdout
    assert "FAKE-not-a-real-key" not in result.stdout + result.stderr
    assert (tmp_path / "home" / "config.env").is_file()
