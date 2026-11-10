"""Agent Skill + Claude Code plugin packaging: manifests, frontmatter, CLI references."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest
import yaml

from openosint.cli import _build_parser
from openosint.tool_policy import TOOL_POLICY

ROOT = Path(__file__).resolve().parent.parent
SKILL_FILES = sorted((ROOT / "skills").glob("*/SKILL.md"))
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _pyproject_version() -> str:
    # Regex, not tomllib: tomllib is 3.11+ and the package supports 3.10.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match, "version not found in pyproject.toml"
    return match.group(1)


VERSION = _pyproject_version()
CLI_PREFIX = f"uvx --from openosint=={VERSION} openosint "


def _load_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _split(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert match, f"{path}: missing frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


def _help_text() -> str:
    parser = _build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    return "\n".join([parser.format_help()] + [p.format_help() for p in sub.choices.values()])


def test_skills_exist() -> None:
    assert {p.parent.name for p in SKILL_FILES} >= {"osint", "exposure"}


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_frontmatter_is_valid(path: Path) -> None:
    meta, body = _split(path)
    assert meta["name"] == path.parent.name
    assert len(meta["name"]) <= 64 and NAME_RE.match(meta["name"])
    assert 0 < len(meta["description"]) <= 1024
    assert len(meta.get("compatibility", "")) <= 500
    assert len(body.splitlines()) <= 150


def test_osint_description_targets_recon() -> None:
    meta, _ = _split(ROOT / "skills/osint/SKILL.md")
    desc = meta["description"].lower()
    for word in ("domain", "ip", "organization", "exposure"):
        assert word in desc


def test_plugin_manifest() -> None:
    plugin = _load_json(".claude-plugin/plugin.json")
    assert plugin["name"] == "openosint"
    assert plugin["version"]


def test_marketplace_manifest() -> None:
    market = _load_json(".claude-plugin/marketplace.json")
    assert market["name"] and market["owner"]["name"]
    plugin = _load_json(".claude-plugin/plugin.json")
    entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
    assert entry["source"] == "./"


def test_mcp_server_is_passive() -> None:
    server = _load_json(".mcp.json")["mcpServers"]["openosint"]
    assert server["command"] == "uvx"
    assert server["args"] == ["--from", f"openosint=={VERSION}", "openosint-mcp"]
    assert "--allow-active" not in server["args"]


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_cli_commands_and_flags_exist(path: Path) -> None:
    _, body = _split(path)
    parser = _build_parser()
    lines = [
        ln.strip()
        for block in re.findall(r"```bash\n(.*?)```", body, re.S)
        for ln in block.splitlines()
    ]
    commands = [c for c in lines if c.startswith(CLI_PREFIX)]
    assert commands, f"{path}: no CLI example"
    for cmd in commands:
        argv = shlex.split(cmd[len(CLI_PREFIX) :])
        argv = [{"DOMAIN": "example.com", "PATH.html": "r.html"}.get(a, a) for a in argv]
        parser.parse_args(argv)  # SystemExit on an unknown command or flag
        assert "--allow-active" not in argv


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_inline_flags_exist(path: Path) -> None:
    """Flags named in prose (`--checks`, `--report`...) must exist somewhere in the CLI."""
    _, body = _split(path)
    known = set(re.findall(r"--[a-z][a-z-]+", _help_text()))
    for flag in set(re.findall(r"`(--[a-z][a-z-]+)", body)):
        if flag != "--allow-active":  # mentioned only to forbid it
            assert flag in known, f"{path}: unknown flag {flag}"


@pytest.mark.parametrize("path", sorted((ROOT / "skills").rglob("*.md")), ids=lambda p: p.name)
def test_mentioned_mcp_tools_exist(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for tool in set(re.findall(r"`((?:search|generate)_[a-z0-9_]+)`", text)):
        assert tool in TOOL_POLICY, f"{path.name}: unknown tool {tool}"


def test_osint_skill_uses_every_keyless_cli_command() -> None:
    _, body = _split(ROOT / "skills/osint/SKILL.md")
    for command in ("exposure", "dns", "rdap", "whois", "dorks", "gdelt", "ip"):
        assert f"{CLI_PREFIX}--json {command} " in body, command


def test_plugin_version_matches_pyproject() -> None:
    plugin = _load_json(".claude-plugin/plugin.json")
    assert plugin["version"] == VERSION, (
        "bump .claude-plugin/plugin.json together with pyproject.toml (see RELEASING.md)"
    )


def test_every_uvx_pin_matches_pyproject() -> None:
    """Skills and .mcp.json must pin the release they document, never an unpinned (possibly older) build."""
    files = [ROOT / ".mcp.json", *sorted((ROOT / "skills").rglob("*.md"))]
    seen = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pin in re.findall(r"--from[\"',\s]+(openosint\S*?)[\"',\s]", text):
            seen += 1
            assert pin == f"openosint=={VERSION}", (
                f"{path.name}: {pin!r}, expected openosint=={VERSION}"
            )
    assert seen >= 3
