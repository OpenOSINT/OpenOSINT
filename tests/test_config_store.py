"""Data-directory settings: storage, permissions, precedence, legacy migration."""

from __future__ import annotations

import os
import stat
import sys

import pytest
from dotenv import dotenv_values

import openosint.env as env_module
from openosint import config_store


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
        ['has "quotes"', "back\\slash", "with # hash", "  inner  spaces ", "ünïcode-日本", "a=b=c", "$HOME"],
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
        config_store.write_config({"PREC_BOTH": "config", "PREC_REAL": "config", "PREC_ONLY_CONFIG": "config"})
        monkeypatch.setenv("PREC_REAL", "real")
        for name in ("PREC_BOTH", "PREC_ONLY_LEGACY", "PREC_ONLY_CONFIG"):
            monkeypatch.delenv(name, raising=False)

        env_module.load_env()

        assert os.environ["PREC_REAL"] == "real"
        assert os.environ["PREC_BOTH"] == "config"
        assert os.environ["PREC_ONLY_CONFIG"] == "config"
        assert os.environ["PREC_ONLY_LEGACY"] == "legacy"
        for name in ("PREC_BOTH", "PREC_ONLY_LEGACY", "PREC_ONLY_CONFIG"):
            monkeypatch.delenv(name, raising=False)

    def test_value_source_reports_where_each_value_came_from(self, tmp_path, monkeypatch, home, fresh_env):
        cwd = self._loaded(tmp_path, monkeypatch, home)
        (cwd / ".env").write_text("SRC_LEGACY=1\n")
        config_store.write_config({"SRC_CONFIG": "1"})
        monkeypatch.setenv("SRC_REAL", "1")
        for name in ("SRC_CONFIG", "SRC_LEGACY"):
            monkeypatch.delenv(name, raising=False)

        env_module.load_env()

        assert env_module.value_source("SRC_REAL") == "environment"
        assert env_module.value_source("SRC_CONFIG") == "config"
        assert env_module.value_source("SRC_LEGACY") == "legacy"
        assert env_module.value_source("SRC_NOTHING") is None
        for name in ("SRC_CONFIG", "SRC_LEGACY"):
            monkeypatch.delenv(name, raising=False)

    def test_a_saved_value_survives_a_restart(self, tmp_path, monkeypatch, home, fresh_env):
        self._loaded(tmp_path, monkeypatch, home)
        config_store.write_config({"RESTART_KEY": "persisted"})
        monkeypatch.delenv("RESTART_KEY", raising=False)  # a new process starts without it

        env_module.load_env()

        assert os.environ["RESTART_KEY"] == "persisted"
        monkeypatch.delenv("RESTART_KEY", raising=False)


class TestLegacyMigration:
    @pytest.fixture
    def package_root(self, tmp_path, monkeypatch, fresh_env):
        root = tmp_path / "site-packages"
        (root / "openosint").mkdir(parents=True)
        monkeypatch.setattr(env_module, "__file__", str(root / "openosint" / "env.py"))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)  # no .env here -> the package-root file is the one loaded
        return root

    def test_package_root_env_is_copied_once_with_a_notice(self, package_root, home, capsys, monkeypatch):
        legacy = package_root / ".env"
        legacy.write_text("SHODAN_API_KEY=legacy-secret\nUNRELATED_VAR=keep-out\nHIBP_API_KEY=\n")
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

        env_module.load_env()

        assert config_store.read_config() == {"SHODAN_API_KEY": "legacy-secret"}
        assert legacy.read_text().startswith("SHODAN_API_KEY=legacy-secret")  # left untouched
        err = capsys.readouterr().err
        assert "Copied 1 saved setting(s) (SHODAN_API_KEY)" in err
        assert "legacy-secret" not in err
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

    def test_second_start_does_not_migrate_again(self, package_root, home, capsys, monkeypatch):
        (package_root / ".env").write_text("SHODAN_API_KEY=first\n")
        env_module.load_env()
        capsys.readouterr()
        (package_root / ".env").write_text("SHODAN_API_KEY=changed-later\n")
        monkeypatch.setattr(env_module, "_load_attempted", False)
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

        env_module.load_env()

        assert config_store.read_config() == {"SHODAN_API_KEY": "first"}
        assert "Copied" not in capsys.readouterr().err
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

    def test_existing_config_is_never_overwritten(self, package_root, home, monkeypatch):
        config_store.write_config({"SHODAN_API_KEY": "from-ui"})
        (package_root / ".env").write_text("SHODAN_API_KEY=legacy\nHIBP_API_KEY=legacy-too\n")
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

        env_module.load_env()

        assert config_store.read_config() == {"SHODAN_API_KEY": "from-ui"}
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)
        monkeypatch.delenv("HIBP_API_KEY", raising=False)

    def test_no_migration_when_a_cwd_env_is_the_one_loaded(self, package_root, home, tmp_path, monkeypatch):
        (package_root / ".env").write_text("SHODAN_API_KEY=package\n")
        work = tmp_path / "work"
        work.mkdir()
        (work / ".env").write_text("SHODAN_API_KEY=cwd\n")
        monkeypatch.chdir(work)
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

        env_module.load_env()

        assert not (home / "config.env").exists()
        assert os.environ["SHODAN_API_KEY"] == "cwd"
        monkeypatch.delenv("SHODAN_API_KEY", raising=False)

    def test_legacy_without_known_keys_creates_nothing(self, package_root, home, monkeypatch):
        (package_root / ".env").write_text("RATE_LIMIT_MAX=5\n")
        monkeypatch.delenv("RATE_LIMIT_MAX", raising=False)

        env_module.load_env()

        assert not (home / "config.env").exists()
        monkeypatch.delenv("RATE_LIMIT_MAX", raising=False)

    def test_oversized_legacy_file_is_not_migrated(self, package_root, home):
        (package_root / ".env").write_text("SHODAN_API_KEY=x\n" + "#" * (config_store._MAX_LEGACY_BYTES + 1))

        assert config_store.migrate_legacy_env(package_root / ".env", frozenset({"SHODAN_API_KEY"})) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
def test_is_user_only_detects_a_world_readable_file(tmp_path):
    path = tmp_path / "f"
    path.write_text("x")
    path.chmod(0o644)

    assert config_store.is_user_only(path) is False
