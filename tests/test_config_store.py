"""Data-directory settings: storage, permissions, precedence, explicit legacy import."""

from __future__ import annotations

import os
import stat
import sys

import pytest
from dotenv import dotenv_values

import openosint.env as env_module
from openosint import config_store
from openosint.settings_catalog import SETTINGS


@pytest.fixture(autouse=True)
def _restore_environ():
    """load_env() writes os.environ directly, which monkeypatch cannot undo."""
    saved = dict(os.environ)
    for setting in SETTINGS:
        os.environ.pop(setting.key, None)  # a developer's real shell keys must not leak in
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("OPENOSINT_HOME", str(path))
    return path


@pytest.fixture
def fresh_env(monkeypatch):
    monkeypatch.setattr(env_module, "_loaded_path", None)
    monkeypatch.setattr(env_module, "_load_attempted", False)
    monkeypatch.setattr(env_module, "_origins", {})
    monkeypatch.delenv("OPENOSINT_ENV_FILE", raising=False)


class TestWriteConfig:
    def test_creates_file_and_directory(self, home):
        config_store.write_config({"SHODAN_API_KEY": "abc"})

        assert (home / "config.env").is_file()
        assert config_store.read_config() == {"SHODAN_API_KEY": "abc"}

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_file_and_new_directory_are_user_only(self, home):
        config_store.write_config({"SHODAN_API_KEY": "abc"})

        assert stat.S_IMODE((home / "config.env").stat().st_mode) == 0o600
        assert stat.S_IMODE(home.stat().st_mode) == 0o700
        assert config_store.is_user_only(home / "config.env") is True

    def test_merges_with_existing_values(self, home):
        config_store.write_config({"A_KEY": "1"})
        merged = config_store.write_config({"B_KEY": "2", "A_KEY": "3"})

        assert merged == {"A_KEY": "3", "B_KEY": "2"}
        assert config_store.read_config() == merged

    @pytest.mark.parametrize(
        "value",
        [
            'has "quotes"',
            "back\\slash",
            "with # hash",
            "  inner  spaces ",
            "ünïcode-日本",
            "a=b=c",
            "$HOME",
        ],
    )
    def test_awkward_values_round_trip(self, home, value):
        config_store.write_config({"SOME_KEY": value})

        assert dotenv_values(home / "config.env")["SOME_KEY"] == value

    @pytest.mark.parametrize("value", ["line1\nline2", "nul\x00byte", "cr\rvalue"])
    def test_control_characters_are_rejected(self, home, value):
        with pytest.raises(ValueError, match="control characters"):
            config_store.write_config({"SOME_KEY": value})
        assert not (home / "config.env").exists()

    @pytest.mark.parametrize("name", ["", "has space", "1LEADING", "BAD-NAME", "A=B"])
    def test_invalid_names_are_rejected(self, home, name):
        with pytest.raises(ValueError, match="invalid setting name"):
            config_store.write_config({name: "x"})

    def test_failed_write_leaves_existing_file_intact(self, home, monkeypatch):
        config_store.write_config({"KEEP": "me"})

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(config_store.os, "replace", boom)
        with pytest.raises(OSError):
            config_store.write_config({"NEW": "x"})

        assert config_store.read_config() == {"KEEP": "me"}
        assert [p.name for p in home.iterdir()] == ["config.env"]


class TestPrecedence:
    def _loaded(self, tmp_path, monkeypatch, home):
        cwd = tmp_path / "work"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        # Keep the repo's own .env out of the "package root" fallback.
        monkeypatch.setattr(env_module, "__file__", str(tmp_path / "pkg" / "openosint" / "env.py"))
        return cwd

    def test_real_env_beats_config_beats_legacy(self, tmp_path, monkeypatch, home, fresh_env):
        cwd = self._loaded(tmp_path, monkeypatch, home)
        (cwd / ".env").write_text("PREC_BOTH=legacy\nPREC_REAL=legacy\nPREC_ONLY_LEGACY=legacy\n")
        config_store.write_config(
            {"PREC_BOTH": "config", "PREC_REAL": "config", "PREC_ONLY_CONFIG": "config"}
        )
        monkeypatch.setenv("PREC_REAL", "real")

        env_module.load_env()

        assert os.environ["PREC_REAL"] == "real"
        assert os.environ["PREC_BOTH"] == "config"
        assert os.environ["PREC_ONLY_CONFIG"] == "config"
        assert os.environ["PREC_ONLY_LEGACY"] == "legacy"

    def test_value_source_reports_where_each_value_came_from(
        self, tmp_path, monkeypatch, home, fresh_env
    ):
        cwd = self._loaded(tmp_path, monkeypatch, home)
        (cwd / ".env").write_text("SRC_LEGACY=1\n")
        config_store.write_config({"SRC_CONFIG": "1"})
        monkeypatch.setenv("SRC_REAL", "1")

        env_module.load_env()

        assert env_module.value_source("SRC_REAL") == "environment"
        assert env_module.value_source("SRC_CONFIG") == "config"
        assert env_module.value_source("SRC_LEGACY") == "legacy"
        assert env_module.value_source("SRC_NOTHING") is None

    def test_a_saved_value_survives_a_restart(self, tmp_path, monkeypatch, home, fresh_env):
        self._loaded(tmp_path, monkeypatch, home)
        config_store.write_config({"RESTART_KEY": "persisted"})
        os.environ.pop("RESTART_KEY", None)  # a new process starts without it

        env_module.load_env()

        assert os.environ["RESTART_KEY"] == "persisted"


class TestLegacyEnvIsNeverCopiedImplicitly:
    @pytest.fixture
    def package_root(self, tmp_path, monkeypatch, fresh_env):
        root = tmp_path / "site-packages"
        (root / "openosint").mkdir(parents=True)
        monkeypatch.setattr(env_module, "__file__", str(root / "openosint" / "env.py"))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)  # no .env here -> the package-root file is the one loaded
        return root

    def test_load_env_writes_nothing_but_still_uses_the_legacy_file(self, package_root, home):
        (package_root / ".env").write_text("SHODAN_API_KEY=legacy-secret\n")

        env_module.load_env()

        assert not home.exists()
        assert os.environ["SHODAN_API_KEY"] == "legacy-secret"

    def test_hint_gives_count_and_command_and_never_a_value(self, package_root, home, capsys):
        (package_root / ".env").write_text(
            "SHODAN_API_KEY=legacy-secret\nHIBP_API_KEY=other-secret\n"
        )

        env_module.load_env()

        err = capsys.readouterr().err
        assert "2 setting(s)" in err
        assert "openosint config import" in err
        assert "not copied" in err.lower()
        assert "legacy-secret" not in err and "other-secret" not in err

    def test_no_hint_once_a_config_file_exists(self, package_root, home, capsys):
        config_store.write_config({"GITHUB_TOKEN": "x"})
        (package_root / ".env").write_text("SHODAN_API_KEY=legacy\n")

        env_module.load_env()

        assert "config import" not in capsys.readouterr().err

    def test_no_hint_when_a_cwd_env_is_the_one_loaded(
        self, package_root, home, tmp_path, monkeypatch, capsys
    ):
        (package_root / ".env").write_text("SHODAN_API_KEY=package\n")
        work = tmp_path / "work"
        work.mkdir()
        (work / ".env").write_text("SHODAN_API_KEY=cwd\n")
        monkeypatch.chdir(work)

        env_module.load_env()

        assert "config import" not in capsys.readouterr().err
        assert not home.exists()

    def test_no_hint_without_known_settings(self, package_root, home, capsys):
        (package_root / ".env").write_text("RATE_LIMIT_MAX=5\n")

        env_module.load_env()

        assert "config import" not in capsys.readouterr().err


class TestShadowWarning:
    @pytest.fixture
    def cwd(self, tmp_path, monkeypatch, home, fresh_env):
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
        monkeypatch.setattr(env_module, "__file__", str(tmp_path / "pkg" / "openosint" / "env.py"))
        return work

    def test_names_the_winning_file_the_losing_file_and_only_differing_keys(
        self, cwd, home, capsys
    ):
        (cwd / ".env").write_text("SHODAN_API_KEY=old-value\nHIBP_API_KEY=same\n")
        config_store.write_config({"SHODAN_API_KEY": "new-value", "HIBP_API_KEY": "same"})

        env_module.load_env()

        err = capsys.readouterr().err
        assert "SHODAN_API_KEY" in err
        assert "HIBP_API_KEY" not in err.split("overrides")[-1]
        assert str(home / "config.env") in err
        assert str(cwd / ".env") in err
        assert "overrides" in err
        assert "old-value" not in err and "new-value" not in err
        assert os.environ["SHODAN_API_KEY"] == "new-value"

    def test_no_warning_when_a_real_environment_variable_decides(
        self, cwd, home, capsys, monkeypatch
    ):
        (cwd / ".env").write_text("SHODAN_API_KEY=old\n")
        config_store.write_config({"SHODAN_API_KEY": "new"})
        monkeypatch.setenv("SHODAN_API_KEY", "from-shell")

        env_module.load_env()

        assert "overrides" not in capsys.readouterr().err

    def test_no_warning_when_only_one_file_defines_the_key(self, cwd, home, capsys):
        (cwd / ".env").write_text("SHODAN_API_KEY=old\n")
        config_store.write_config({"HIBP_API_KEY": "new"})

        env_module.load_env()

        assert "overrides" not in capsys.readouterr().err


class TestLegacyCandidatesAndImport:
    KEYS = frozenset({"SHODAN_API_KEY", "HIBP_API_KEY", "GITHUB_TOKEN"})

    def test_candidates_keep_only_known_nonblank_safe_values(self, tmp_path):
        legacy = tmp_path / ".env"
        legacy.write_text("SHODAN_API_KEY= spaced \nHIBP_API_KEY=\nUNRELATED=1\nGITHUB_TOKEN=ok\n")

        assert config_store.legacy_candidates(legacy, self.KEYS) == {
            "SHODAN_API_KEY": "spaced",
            "GITHUB_TOKEN": "ok",
        }

    def test_candidates_empty_for_missing_or_oversized_file(self, tmp_path):
        big = tmp_path / ".env"
        big.write_text("SHODAN_API_KEY=x\n" + "#" * (config_store._MAX_LEGACY_BYTES + 1))

        assert config_store.legacy_candidates(big, self.KEYS) == {}
        assert config_store.legacy_candidates(tmp_path / "nope", self.KEYS) == {}

    def test_import_copies_and_never_overwrites_existing_config_values(self, tmp_path, home):
        legacy = tmp_path / ".env"
        legacy.write_text("SHODAN_API_KEY=legacy\nHIBP_API_KEY=legacy-too\n")
        config_store.write_config({"SHODAN_API_KEY": "from-ui"})

        imported, skipped = config_store.import_legacy_env(legacy, self.KEYS)

        assert imported == ["HIBP_API_KEY"]
        assert skipped == ["SHODAN_API_KEY"]
        assert config_store.read_config() == {
            "SHODAN_API_KEY": "from-ui",
            "HIBP_API_KEY": "legacy-too",
        }
        assert legacy.read_text().startswith("SHODAN_API_KEY=legacy")  # left untouched

    def test_import_only_filter(self, tmp_path, home):
        legacy = tmp_path / ".env"
        legacy.write_text("SHODAN_API_KEY=a\nHIBP_API_KEY=b\n")

        imported, _ = config_store.import_legacy_env(legacy, self.KEYS, only=["HIBP_API_KEY"])

        assert imported == ["HIBP_API_KEY"]
        assert config_store.read_config() == {"HIBP_API_KEY": "b"}

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_imported_file_is_user_only(self, tmp_path, home):
        legacy = tmp_path / ".env"
        legacy.write_text("SHODAN_API_KEY=a\n")

        config_store.import_legacy_env(legacy, self.KEYS)

        assert stat.S_IMODE((home / "config.env").stat().st_mode) == 0o600

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_exposed_directory_detection(self, home):
        home.mkdir(mode=0o755)
        home.chmod(0o755)
        assert config_store.config_dir_exposed() is True
        home.chmod(0o700)
        assert config_store.config_dir_exposed() is False

    def test_missing_directory_is_not_reported_exposed(self, home):
        assert config_store.config_dir_exposed() is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
def test_is_user_only_detects_a_world_readable_file(tmp_path):
    path = tmp_path / "f"
    path.write_text("x")
    path.chmod(0o644)

    assert config_store.is_user_only(path) is False
