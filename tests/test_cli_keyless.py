"""CLI subcommands whois / rdap / gdelt / dorks: JSON envelope, passive policy, no real network."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, patch

import pytest

from openosint import cli

ENVELOPE = {"tool", "target", "timestamp", "results", "error"}
# command, target, patched runner (as imported in cli), expected tool name, fake output
CASES = [
    ("whois", "example.com", "run_whois_osint", "search_whois", "[WHOIS] Registrar: Test"),
    ("rdap", "example.com", "run_rdap_osint", "search_rdap", "[+] Registrar: Test"),
    ("ip", "8.8.8.8", "run_ip_osint", "search_ip", "[IP] ASN: AS15169 Google LLC"),
    ("gdelt", "acme corp", "run_gdelt_geo_osint", "search_gdelt_geo", "Headline one"),
    (
        "dorks",
        "example.com",
        "run_dork_osint",
        "generate_dorks",
        "https://www.google.com/search?q=x",
    ),
]


def _run(argv: list[str]) -> None:
    with patch.object(sys, "argv", ["openosint", *argv]):
        cli.main()


@pytest.mark.parametrize(("command", "target", "runner", "tool", "output"), CASES)
def test_json_envelope_matches_dns(capsys, command, target, runner, tool, output) -> None:
    mock = AsyncMock(return_value=output)
    with patch.object(cli, runner, mock):
        _run(["--json", command, target])

    data = json.loads(capsys.readouterr().out)
    assert set(data) == ENVELOPE
    assert data["tool"] == tool
    assert data["target"] == target
    assert data["results"] == [output]
    mock.assert_awaited_once()


@pytest.mark.parametrize(("command", "target", "runner", "tool", "output"), CASES)
def test_text_output_prints_result(capsys, command, target, runner, tool, output) -> None:
    with patch.object(cli, runner, AsyncMock(return_value=output)):
        _run([command, target])
    assert output in capsys.readouterr().out


def test_gdelt_drops_raw_geojson(capsys) -> None:
    fenced = 'Found 1 point.\n```geojson\n{"type": "FeatureCollection", "features": []}\n```\n'
    with patch.object(cli, "run_gdelt_geo_osint", AsyncMock(return_value=fenced)):
        _run(["--json", "gdelt", "acme"])
    assert "FeatureCollection" not in capsys.readouterr().out


@pytest.mark.parametrize(("command", "target", "runner", "tool", "output"), CASES)
def test_refused_when_policy_disables_tool(capsys, command, target, runner, tool, output) -> None:
    mock = AsyncMock(return_value=output)
    with (
        patch.object(cli, runner, mock),
        patch.object(cli, "is_tool_enabled", return_value=False),
        pytest.raises(SystemExit) as exc,
    ):
        _run([command, target])
    assert exc.value.code == 2
    mock.assert_not_awaited()


@pytest.mark.parametrize(("command", "tool"), [(c[0], c[3]) for c in CASES])
def test_commands_map_to_passive_tools(command, tool) -> None:
    from openosint.tool_policy import TOOL_POLICY

    assert cli._COMMAND_TOOLS[command] == tool
    assert TOOL_POLICY[tool].is_passive
