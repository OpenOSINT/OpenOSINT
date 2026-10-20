"""OPENOSINT_PUBLISHED_BIND: a container operator's declaration that the published
port is loopback-only. Exact matching; it can only lift the bind-address restriction
on a non-loopback real bind, never anything else."""

import pytest

import openosint.web_server as ws


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
    monkeypatch.delenv("OPENOSINT_PUBLISHED_BIND", raising=False)


@pytest.mark.parametrize(
    "declared", ["127.0.0.1", "localhost", "::1", "  127.0.0.1  ", "\tlocalhost\n"]
)
def test_exact_loopback_declaration_lifts_restriction_on_wildcard_bind(monkeypatch, declared):
    monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", declared)
    assert ws._compute_demo_mode("0.0.0.0") is False


@pytest.mark.parametrize(
    "declared",
    [
        None,  # unset
        "",
        "   ",
        "0.0.0.0",
        "::",
        "192.168.1.5",
        "127.0.0.2",  # loopback range but not an exact match
        "127.0.0.1:8080",
        "127.0.0.1,0.0.0.0",
        "LOCALHOST",  # exact, case-sensitive
        "localhost.",
        "127.1",
        "[::1]",
        "true",
        "1",
    ],
)
def test_anything_else_keeps_the_restriction(monkeypatch, declared):
    if declared is not None:
        monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", declared)
    assert ws._compute_demo_mode("0.0.0.0") is True


def test_declaration_does_not_lift_restriction_for_an_undetermined_bind(monkeypatch):
    monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", "127.0.0.1")
    assert ws._compute_demo_mode(None) is True


def test_declaration_applies_to_an_explicit_external_bind_too(monkeypatch):
    monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", "127.0.0.1")
    assert ws._compute_demo_mode("203.0.113.5") is False


def test_demo_mode_env_still_forces_restriction_after_declaration(monkeypatch):
    monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", "127.0.0.1")
    monkeypatch.setenv("OPENOSINT_DEMO_MODE", "true")
    assert ws._compute_demo_mode("0.0.0.0") is True


def test_banner_announces_lifted_restriction(monkeypatch, capsys):
    monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", "127.0.0.1")
    ws._print_banner("0.0.0.0", 8080)
    out = capsys.readouterr().out
    assert "OPENOSINT_PUBLISHED_BIND=127.0.0.1" in out
    assert "restriction lifted" in out


@pytest.mark.parametrize("declared", [None, "0.0.0.0", ""])
def test_banner_is_silent_without_a_valid_declaration(monkeypatch, capsys, declared):
    if declared is not None:
        monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", declared)
    ws._print_banner("0.0.0.0", 8080)
    assert "OPENOSINT_PUBLISHED_BIND" not in capsys.readouterr().out


def test_banner_is_silent_on_a_loopback_bind(monkeypatch, capsys):
    monkeypatch.setenv("OPENOSINT_PUBLISHED_BIND", "127.0.0.1")
    ws._print_banner("127.0.0.1", 8080)
    assert "OPENOSINT_PUBLISHED_BIND" not in capsys.readouterr().out
