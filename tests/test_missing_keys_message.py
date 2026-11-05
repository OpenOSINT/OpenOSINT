"""The missing-key message: Bright Data setup steps, surface-aware 'where to put it', one list for scrape_url."""

from __future__ import annotations

import json

import pytest

from openosint import brightdata
from openosint.brightdata_response import TOKEN_URL
from openosint.settings_catalog import SETTINGS, config_path, missing_keys_message
from openosint.tool_policy import humanize

ALL_BD = ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for setting in SETTINGS:
        monkeypatch.delenv(setting.key, raising=False)
    monkeypatch.delenv(brightdata.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(brightdata, "_surface", "cli")


class TestBrightDataSetupSteps:
    def test_a_new_user_gets_every_step_for_the_serp_tools(self):
        message = missing_keys_message("search_dorks_live", ALL_BD)

        assert "1. Sign up or log in" in message
        assert (
            f"2. Copy your API token from {TOKEN_URL}" in message
            and "BRIGHTDATA_API_KEY" in message
        )
        assert "3. Create a SERP API zone" in message and "BRIGHTDATA_SERP_ZONE" in message
        assert "Web Unlocker" not in message and "BRIGHTDATA_UNLOCKER_ZONE" not in message

    def test_scrape_url_gets_the_web_unlocker_zone_step(self):
        message = missing_keys_message(
            "scrape_url", ["BRIGHTDATA_API_KEY", "BRIGHTDATA_UNLOCKER_ZONE"]
        )

        assert "3. Create a Web Unlocker zone" in message and "BRIGHTDATA_UNLOCKER_ZONE" in message
        assert "SERP" not in message.split("[key_required]")[1].split("Get one")[0]
        assert "BRIGHTDATA_SERP_ZONE" not in message

    def test_a_user_who_only_lacks_the_zone_is_not_told_to_sign_up(self):
        message = missing_keys_message("search_footprint", ["BRIGHTDATA_SERP_ZONE"])

        assert "Sign up" not in message and "API token" not in message
        assert (
            "get.brightdata.com" not in message and "commission" not in message
        )  # they already have an account
        assert "1. Create a SERP API zone" in message and "BRIGHTDATA_SERP_ZONE" in message

    def test_the_zone_guidance_is_no_longer_lost_to_url_deduplication(self):
        message = missing_keys_message("search_dorks_live", ALL_BD)

        assert "create the zone" in message.lower() or "Create a SERP API zone" in message

    def test_only_documented_facts_and_no_time_promises(self):
        message = missing_keys_message("search_dorks_live", ALL_BD).lower()

        assert "no credit card" in message
        assert "minutes" not in message and "instantly" not in message

    def test_the_disclosure_is_on_the_same_line_as_the_link(self):
        message = missing_keys_message("search_dorks_live", ALL_BD)
        get_one = next(line for line in message.splitlines() if line.startswith("Get one:"))

        assert "openosint-signup" in get_one and "commission" in get_one

    def test_opt_out_keeps_the_steps_and_drops_tracking_and_the_commission_claim(self, monkeypatch):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")

        message = missing_keys_message("search_dorks_live", ALL_BD)

        assert "get.brightdata.com" not in message and "utm_" not in message and "commission" not in message
        assert "Get one: https://brightdata.com" in message
        assert TOKEN_URL in message and "3. Create a SERP API zone" in message

    def test_other_tools_are_unchanged(self):
        message = missing_keys_message("search_shodan", ["SHODAN_API_KEY"])

        assert "Bright Data" not in message and "Sign up" not in message
        assert message.splitlines()[1] == "[key_required] SHODAN_API_KEY"


class TestWhereToPutIt:
    def _add_it(self, message: str) -> str:
        return next(line for line in message.splitlines() if line.startswith("Add it:"))

    def test_cli_points_at_the_environment_and_the_config_file(self):
        line = self._add_it(missing_keys_message("search_dorks_live", ALL_BD))

        assert "environment" in line and str(config_path()) in line and "web UI" not in line

    def test_mcp_mentions_the_client_env_block_and_a_restart(self):
        brightdata.set_surface("mcp")

        line = self._add_it(missing_keys_message("search_dorks_live", ALL_BD))

        assert '"env"' in line and "restart" in line.lower() and str(config_path()) in line

    @pytest.mark.parametrize("surface", ["webui", "webui-remote", "demo"])
    def test_web_surfaces_lead_with_the_settings_page(self, surface):
        brightdata.set_surface(surface)

        line = self._add_it(missing_keys_message("search_dorks_live", ALL_BD))

        assert "web UI" in line and "Settings" in line and str(config_path()) in line

    def test_every_surface_names_the_variables(self):
        for surface in ("cli", "mcp", "webui"):
            brightdata.set_surface(surface)
            line = self._add_it(missing_keys_message("search_dorks_live", ALL_BD))
            assert "BRIGHTDATA_API_KEY" in line and "BRIGHTDATA_SERP_ZONE" in line


class TestScrapeUrlShowsOneList:
    async def test_passive_mode_and_missing_keys_are_reported_together(self, monkeypatch):
        from openosint.tools.scrape_url import run_scrape_url_osint

        monkeypatch.delenv("OPENOSINT_ALLOW_ACTIVE", raising=False)

        result = await run_scrape_url_osint("https://example.com")

        data = json.loads(result)  # still the structured passive-mode result
        assert data["status"] == "disabled_in_passive_mode" and data["tool"] == "scrape_url"
        assert (
            "BRIGHTDATA_UNLOCKER_ZONE" in data["also_needed"] and TOKEN_URL in data["also_needed"]
        )
        text = humanize(result)
        assert "[passive mode]" in text and "--allow-active" in text
        assert "BRIGHTDATA_API_KEY" in text and "3. Create a Web Unlocker zone" in text
        assert text.index("[passive mode]") < text.index("BRIGHTDATA_API_KEY")

    async def test_passive_mode_alone_is_unchanged_when_the_keys_are_set(self, monkeypatch):
        from openosint.tools.scrape_url import run_scrape_url_osint

        monkeypatch.delenv("OPENOSINT_ALLOW_ACTIVE", raising=False)
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "fake")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "z")

        data = json.loads(await run_scrape_url_osint("https://example.com"))

        assert data["status"] == "disabled_in_passive_mode" and "also_needed" not in data
        assert "also_needed" not in humanize(json.dumps(data))

    async def test_with_active_mode_on_the_normal_missing_key_message_appears(self, monkeypatch):
        from openosint.tools.scrape_url import run_scrape_url_osint

        monkeypatch.setenv("OPENOSINT_ALLOW_ACTIVE", "1")

        result = await run_scrape_url_osint("https://example.com")

        assert (
            result.startswith("Scan error: scrape_url cannot run:") and "[key_required]" in result
        )

    def test_other_disabled_tools_keep_their_exact_output(self):
        from openosint.tool_policy import disabled_result

        assert "also_needed" not in json.loads(disabled_result("search_username"))


class TestCliGateShowsTheSameList:
    """The CLI refuses by command name before the tool runs: it must show both walls too."""

    def _run(self, tmp_path, **extra_env):
        import os
        import subprocess
        import sys

        fake_env = tmp_path / "empty.env"
        fake_env.write_text("")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "OPENOSINT_HOME": str(tmp_path / "home"),
            "OPENOSINT_ENV_FILE": str(fake_env),
            **extra_env,
        }
        return subprocess.run(
            [sys.executable, "-m", "openosint.cli", "scrape", "https://example.com"],
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )

    def test_passive_refusal_lists_the_missing_bright_data_setup(self, tmp_path):
        result = self._run(tmp_path)

        assert result.returncode == 2
        assert "[passive mode]" in result.stderr and "--allow-active" in result.stderr
        assert (
            "BRIGHTDATA_UNLOCKER_ZONE" in result.stderr
            and "3. Create a Web Unlocker zone" in result.stderr
        )

    def test_passive_refusal_is_unchanged_when_the_settings_exist(self, tmp_path):
        result = self._run(tmp_path, BRIGHTDATA_API_KEY="fake", BRIGHTDATA_UNLOCKER_ZONE="z")

        assert result.returncode == 2 and "[passive mode]" in result.stderr
        assert "Set up Bright Data" not in result.stderr
