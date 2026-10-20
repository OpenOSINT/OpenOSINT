"""OPENOSINT_HOME resolution and its precedence against OPENOSINT_GRAPH_DB."""

from pathlib import Path

import pytest

from openosint.paths import home_dir


def test_home_dir_defaults_to_dot_openosint_in_user_home(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENOSINT_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert home_dir() == tmp_path / ".openosint"


def test_home_dir_honours_openosint_home(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "data"))

    assert home_dir() == tmp_path / "data"


def test_home_dir_ignores_blank_openosint_home(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENOSINT_HOME", "   ")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert home_dir() == tmp_path / ".openosint"


def test_graph_db_lives_under_openosint_home(monkeypatch, tmp_path):
    pytest.importorskip("followthemoney", reason="requires the 'graph' extra")
    from openosint.graph.store.db_path import default_db_path

    monkeypatch.delenv("OPENOSINT_GRAPH_DB", raising=False)
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "data"))

    assert default_db_path() == tmp_path / "data" / "graph.db"
    assert (tmp_path / "data").is_dir()


def test_graph_db_override_wins_over_openosint_home(monkeypatch, tmp_path):
    pytest.importorskip("followthemoney", reason="requires the 'graph' extra")
    from openosint.graph.store.db_path import default_db_path

    explicit = tmp_path / "elsewhere" / "g.db"
    monkeypatch.setenv("OPENOSINT_GRAPH_DB", str(explicit))
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "data"))

    assert default_db_path() == explicit
