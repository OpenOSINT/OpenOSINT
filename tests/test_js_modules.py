"""Runs the Node unit tests for the web UI's pure JS helpers, and guards index.html wiring."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
INDEX = (ROOT / "openosint" / "web" / "index.html").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("script", ["test_setup_client.mjs", "test_geo_status.mjs"])
def test_node_unit_tests_pass(script):
    result = subprocess.run(
        ["node", str(ROOT / "tests" / script)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _method_body(name: str) -> str:
    match = re.search(rf"\n    (?:async )?{name}\(.*?\) \{{\n(.*?)\n    \}},\n", INDEX, re.S)
    assert match, f"{name} not found in index.html"
    return match.group(1)


def test_save_form_never_references_an_undeclared_apikeys_state():
    # Regression: saveApiKeys looped over `this.apiKeys`, which was never defined, so
    # "Save to server" threw before sending anything and showed no message.
    assert "this.apiKeys" not in INDEX
    assert "serverApiKeys" not in INDEX


def test_every_this_property_the_save_flow_reads_is_declared_state():
    declared = set(re.findall(r"^    (\w+):", INDEX, re.M)) | set(re.findall(r"^    (?:async )?(?:get )?(\w+)\(", INDEX, re.M))
    for method in ("saveApiKeys", "saveFirstRunKey", "_postSetup", "fetchSetupStatus", "dismissFirstRun"):
        used = set(re.findall(r"this\.(\w+)", _method_body(method)))
        assert used <= declared, f"{method} uses undeclared state: {used - declared}"


def test_forbidden_message_from_the_server_is_rendered_for_docker_users():
    assert 'x-text="setupStatus?.forbidden_message"' in INDEX
    assert "OPENOSINT_SETUP_TOKEN" in INDEX and 'x-model="setupToken"' in INDEX


def test_setup_client_module_is_loaded_by_the_page():
    assert "import * as setupClient from '/static/setup-client.js'" in INDEX
    assert "window._setupClient" in INDEX


def test_first_run_panel_is_dismissible_and_mentions_ollama():
    assert 'data-testid="first-run"' in INDEX
    assert "dismissFirstRun()" in INDEX
    assert "ollama.com" in INDEX


def test_globe_shows_a_notice_when_the_news_service_is_down():
    assert 'data-testid="news-unavailable"' in INDEX
    assert 'x-show="newsUnavailable"' in INDEX
    assert "gdeltServiceStatus(tool, output)" in INDEX
    assert "newsUnavailable: false" in INDEX
