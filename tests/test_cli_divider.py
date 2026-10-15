"""Divider width follows the terminal width (issue #35)."""
from __future__ import annotations

from openosint import cli


def test_divider_defaults_to_60_when_terminal_is_wide(monkeypatch):
    monkeypatch.setenv("COLUMNS", "120")
    assert cli._divider_width() == 60
    assert cli._divider() == "=" * 60


def test_divider_shrinks_to_narrow_terminal(monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    assert cli._divider_width() == 40
    assert cli._divider() == "=" * 40


def test_divider_has_minimum_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", "5")
    assert cli._divider_width() == 20
