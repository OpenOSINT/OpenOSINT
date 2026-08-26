# tests/test_graph_dedup_guard.py
"""Tests for openosint.graph.dedup_guard — runs on any Python version, no nomenklatura needed."""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")


from openosint.graph.dedup_guard import MIN_PYTHON, check_python_version  # noqa: E402


class TestCheckPythonVersion:
    def test_below_minimum_raises_with_clear_message(self):
        with pytest.raises(ImportError) as exc_info:
            check_python_version((3, 10))
        message = str(exc_info.value)
        assert "3.11" in message
        assert "graph-dedup" in message
        assert "3.10" in message  # names the interpreter's actual version too

    def test_well_below_minimum_also_raises(self):
        with pytest.raises(ImportError):
            check_python_version((3, 8))

    def test_at_minimum_does_not_raise(self):
        check_python_version(MIN_PYTHON)  # must not raise

    def test_above_minimum_does_not_raise(self):
        check_python_version((3, 12))  # must not raise

    def test_error_names_the_pip_install_extra(self):
        with pytest.raises(ImportError, match=r"pip install 'openosint\[graph-dedup\]'"):
            check_python_version((3, 9))
