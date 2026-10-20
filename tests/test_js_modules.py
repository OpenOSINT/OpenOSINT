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
@pytest.mark.parametrize("script", ["test_setup_client.mjs", "test_geo_status.mjs", "test_globe_buffering.mjs", "test_agent_loop_tool_cap.mjs"])
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


def test_globe_news_badge_and_headline_render_as_text_only():
    assert 'data-testid="news-coverage"' in INDEX
    assert 'x-text="coverageText()"' in INDEX
    # The method must read newsCoverage itself: an x-text that only reaches it through
    # `window._geoFns?.` never subscribes to it when _geoFns is not loaded yet, and stays blank.
    assert "return this.newsCoverage ? window._geoFns?.coverageLabel(this.newsCoverage)" in INDEX
    assert 'x-text="globePivotTitle()"' in INDEX
    assert 'x-text="globePivotDomain()"' in INDEX
    assert "newsCoverage: null" in INDEX
    # Third-party headlines/domains/URLs must never be injected as HTML.
    panel = INDEX[INDEX.index("<!-- Pivot popover") : INDEX.index("</div><!-- end globe pane -->")]
    assert "x-html" not in panel
    assert ":href=\"globePivotUrl()\"" in panel  # URL only via the safe-URL check


def test_box_select_asks_for_everything_in_the_area():
    assert 'use search_gdelt_geo with query "*" and this bbox.' in INDEX


def test_globe_keeps_the_gdelt_credit():
    renderer = (ROOT / "openosint/web/static/globe-renderer.js").read_text()
    assert "https://www.gdeltproject.org" in renderer


# --- Settings flow per mode -------------------------------------------------


def _settings_modal() -> str:
    start = INDEX.index("<!-- SETTINGS MODAL -->")
    return INDEX[start : INDEX.index("<!-- TOP BAR -->")]


def test_local_mode_primary_save_action_calls_api_setup():
    modal = _settings_modal()
    # The primary section is shown in local mode and its button runs the /api/setup save.
    block = modal[modal.index('data-testid="save-to-computer"') : modal.index('data-testid="session-only-toggle"')]
    assert 'x-show="saveToComputer"' in modal
    assert '@click="saveApiKeys()"' in block and 'data-testid="save-to-computer-button"' in block
    assert "Saved on this computer in" in block and "config_path" in block
    assert "never stored on our servers" not in block
    # ... and saveApiKeys really posts to /api/setup (via _postSetup).
    assert "this._postSetup(" in _method_body("saveApiKeys")
    assert "fetch('/api/setup'" in _method_body("_postSetup")


def test_browser_only_keys_are_secondary_in_local_mode_and_unchanged_in_demo():
    modal = _settings_modal()
    assert 'x-show="!saveToComputer || showSessionOnly"' in modal  # demo: always visible
    assert "Use only for this browser session (not saved)" in modal
    # The original browser-only copy is still there for the demo.
    assert "Keys stay in your browser (sessionStorage)" in modal
    # The primary section comes before the browser-only one.
    assert modal.index('data-testid="save-to-computer"') < modal.index('data-testid="browser-only-keys"')


def test_save_to_computer_getter_is_false_for_the_demo_and_restricted_requests():
    body = re.search(r"get saveToComputer\(\) \{\n(.*?)\n    \},", INDEX, re.S).group(1)
    assert "this.serverSideFallback" in body and "setupStatus.restricted" in body


def test_settings_panel_shows_configured_and_shadowed_state_without_values():
    modal = _settings_modal()
    assert 'data-testid="configured-badge"' in modal and 'data-testid="shadowed-badge"' in modal
    assert "an environment variable of the same name overrides it" in modal
    assert "k.value" not in modal


def test_first_run_actions_default_to_saving_on_this_computer():
    start = INDEX.index('data-testid="first-run"')
    panel = INDEX[start : INDEX.index("<!-- messages -->")]
    assert "saveFirstRunKey()" in panel and "saved on this computer" in panel
    # The browser-only routes are explicitly the secondary ones.
    assert "showSessionOnly = true" in panel


def test_setup_getters_track_reactive_state_before_the_module_check():
    # Regression: getters that returned early on a not-yet-loaded module read no reactive
    # state, so Alpine never re-rendered them and the key form stayed empty.
    for name, state in (("setupGroups", "this.setupStatus"), ("toolSummary", "this.tools")):
        body = re.search(rf"get {name}\(\) \{{\n(.*?)\n    \}},", INDEX, re.S).group(1)
        assert body.index(state) < body.index("this.clientReady"), name
    assert "this.clientReady = !!window._setupClient" in INDEX


def test_new_geo_results_badge_the_globe_and_reset_with_the_conversation():
    assert 'data-testid="globe-badge"' in INDEX
    assert "globeUnseen: 0" in INDEX
    assert "mergeNewsFeatures(window._globeFns.getNewsFeatures(), features)" in INDEX
    assert "window._globeFns.fitToFeatures(features)" in INDEX
    assert "this.globeUnseen = 0;" in _method_body("clearConversation")


def test_user_messages_without_parts_do_not_break_the_message_template():
    # User messages have no `parts`; x-show on them still evaluates the expression.
    assert 'x-show="msg.parts?.length === 0"' in INDEX
    assert 'x-show="msg.parts.length === 0"' not in INDEX
