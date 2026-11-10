"""Bright Data referral links: one UTM scheme, an opt-out, and a disclosure wherever a link appears."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from openosint import brightdata
from openosint.settings_catalog import missing_keys_message, public_catalog

ROOT = Path(__file__).resolve().parent.parent
REFERRAL_IDS = {
    "main": "984ni58s2oad",
    "signup": "openosint-signup",
    "serp": "jx2wfi",
    "unlocker": "openosint-unlocker",
}
REFERRAL_ID = REFERRAL_IDS["main"]
REFERRAL_URL_RE = re.compile(r"https://get\.brightdata\.com/[A-Za-z0-9_-]+[^\s)\"'<>`]*")


@pytest.fixture(autouse=True)
def _default_surface(monkeypatch):
    monkeypatch.delenv(brightdata.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(brightdata, "_surface", "cli")


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


class TestReferralLink:
    def test_default_link_follows_the_scheme(self):
        url = brightdata.referral_link()

        assert url.startswith(f"https://get.brightdata.com/{REFERRAL_ID}?")
        assert _query(url) == {
            "sid1": "cli",
            "sid2": "setup",
            "utm_source": "openosint",
            "utm_medium": "cli",
            "utm_campaign": "setup",
        }

    def test_content_is_added_as_utm_and_sid3(self):
        query = _query(brightdata.referral_link("setup", content="scrape_url"))

        assert query["utm_content"] == query["sid3"] == "scrape_url"

    @pytest.mark.parametrize(
        ("kwargs", "dest"),
        [
            ({"dest": "signup"}, "signup"),
            ({"content": "search_dorks_live"}, "serp"),
            ({"content": "search_footprint"}, "serp"),
            ({"content": "scrape_url"}, "unlocker"),
            ({"content": "search_ip"}, "main"),
            ({}, "main"),
        ],
    )
    def test_each_placement_routes_to_its_link(self, kwargs, dest):
        url = brightdata.referral_link("setup", **kwargs)

        assert url.startswith(f"https://get.brightdata.com/{REFERRAL_IDS[dest]}?")

    def test_unknown_destination_is_rejected(self):
        with pytest.raises(ValueError, match="destination"):
            brightdata.referral_link("setup", dest="blog")

    @pytest.mark.parametrize("surface", brightdata.SURFACES)
    def test_medium_follows_the_surface_set_at_startup(self, surface):
        brightdata.set_surface(surface)

        assert _query(brightdata.referral_link())["utm_medium"] == surface
        assert brightdata.current_surface() == surface

    def test_unknown_surface_or_campaign_is_rejected(self):
        with pytest.raises(ValueError, match="surface"):
            brightdata.set_surface("twitter")
        with pytest.raises(ValueError, match="campaign"):
            brightdata.referral_link("sale")

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_opt_out_returns_a_plain_link_without_tracking(self, monkeypatch, value):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, value)

        assert brightdata.referral_link("setup", content="scrape_url") == "https://brightdata.com"
        assert brightdata.disclosure() == ""
        assert brightdata.disclosure_suffix() == ""

    @pytest.mark.parametrize("value", ["", "0", "false", "no"])
    def test_other_values_leave_links_on(self, monkeypatch, value):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, value)

        assert REFERRAL_ID in brightdata.referral_link()
        assert "commission" in brightdata.disclosure()

    def test_static_link_ignores_surface_and_opt_out(self, monkeypatch):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")
        brightdata.set_surface("mcp")

        url = brightdata.static_link("docs", "docs", content="search_footprint")

        assert _query(url) == {
            "sid1": "docs",
            "sid2": "docs",
            "sid3": "search_footprint",
            "utm_source": "openosint",
            "utm_medium": "docs",
            "utm_campaign": "docs",
            "utm_content": "search_footprint",
        }

    def test_resolve_fills_placeholders_and_drops_the_disclosure_on_opt_out(self, monkeypatch):
        text = f"Get one: {brightdata.LINK_PLACEHOLDER} - free tier. {brightdata.DISCLOSURE_PLACEHOLDER}"

        assert REFERRAL_IDS["signup"] in brightdata.resolve(text)
        assert "commission" in brightdata.resolve(text)
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")
        assert brightdata.resolve(text).startswith("Get one: https://brightdata.com - free tier.")
        assert "commission" not in brightdata.resolve(text)


class TestInProductMessages:
    def test_missing_key_message_uses_the_current_surface_and_discloses(self):
        brightdata.set_surface("mcp")

        message = missing_keys_message(
            "scrape_url", ["BRIGHTDATA_API_KEY", "BRIGHTDATA_UNLOCKER_ZONE"]
        )

        assert "utm_medium=mcp" in message and "sid1=mcp" in message
        assert "utm_source=openosint" in message
        assert REFERRAL_IDS["signup"] in message
        assert "commission" in message

    def test_opt_out_removes_tracking_and_the_commission_claim_but_keeps_the_instructions(
        self, monkeypatch
    ):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")

        message = missing_keys_message(
            "scrape_url", ["BRIGHTDATA_API_KEY", "BRIGHTDATA_UNLOCKER_ZONE"]
        )

        assert "get.brightdata.com" not in message and "utm_" not in message
        assert "sid1" not in message and "commission" not in message
        assert "BRIGHTDATA_API_KEY" in message and "Get one: https://brightdata.com" in message

    def test_web_catalog_resolves_links_and_notes(self, monkeypatch):
        brightdata.set_surface("webui")
        entry = next(e for e in public_catalog() if e["key"] == "BRIGHTDATA_SERP_ZONE")
        assert "sid1=webui" in entry["url"] and "commission" in entry["note"]

        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")
        entry = next(e for e in public_catalog() if e["key"] == "BRIGHTDATA_API_KEY")
        assert entry["url"] == "https://brightdata.com" and "commission" not in entry["note"]

    def test_invalid_key_errors_point_at_the_token_page_not_the_referral_link(self, monkeypatch):
        """The user already has an account: a signup link there would only be a sales push."""
        from openosint.brightdata_response import TOKEN_URL
        from openosint.tools import scrape_url, search_footprint

        class Resp:
            status_code = 401
            text = "Invalid token"
            headers: dict = {}

        monkeypatch.setattr(scrape_url.requests, "post", lambda *a, **k: Resp())
        monkeypatch.setattr(search_footprint.requests, "post", lambda *a, **k: Resp())

        for call in (
            lambda: scrape_url._fetch_unlocker("https://e.com", "k", "z", 5),
            lambda: search_footprint._fetch_serp("https://e.com", "k", "z", 5),
        ):
            with pytest.raises(Exception) as err:
                call()
            message = str(err.value)
            assert TOKEN_URL in message
            assert "get.brightdata.com" not in message and "commission" not in message


class TestEntryPointsSetTheSurface:
    def test_mcp_main_sets_mcp(self, monkeypatch):
        from openosint import mcp_server

        async def _noop():
            return None

        monkeypatch.setattr(mcp_server, "_serve", _noop)
        mcp_server.main([])

        assert brightdata.current_surface() == "mcp"

    DEMO_HOSTS = "demo.openosint.tech,openosint-demo-8f67039da343.herokuapp.com"

    @pytest.mark.parametrize(
        ("host", "allowed_hosts", "force_demo", "surface"),
        [
            ("127.0.0.1", "", False, "webui"),
            ("127.0.0.1", "", True, "webui"),  # rehearsing demo restrictions locally is still local
            ("0.0.0.0", "", False, "webui-remote"),  # any other network-exposed server
            ("0.0.0.0", "intranet.example.com", False, "webui-remote"),
            ("0.0.0.0", DEMO_HOSTS, False, "demo"),  # only the configured public demo host
            ("0.0.0.0", "DEMO.openosint.tech:443", False, "demo"),
            ("127.0.0.1", DEMO_HOSTS, False, "webui"),
        ],
    )
    def test_web_app_sets_webui_webui_remote_or_demo(
        self, monkeypatch, host, allowed_hosts, force_demo, surface
    ):
        from openosint import web_server

        monkeypatch.setenv("OPENOSINT_ALLOWED_HOSTS", allowed_hosts)
        monkeypatch.setenv("OPENOSINT_DEMO_MODE", "1" if force_demo else "")
        web_server.create_app(host=host)

        assert brightdata.current_surface() == surface

    def test_an_undetermined_bind_address_is_remote_not_local(self, monkeypatch):
        from openosint import web_server

        monkeypatch.setenv("OPENOSINT_ALLOWED_HOSTS", "")
        web_server.create_app(host=None)

        assert brightdata.current_surface() == "webui-remote"


class TestRepositoryFiles:
    """Every shipped file that carries the referral link follows the scheme and discloses it."""

    def _files(self):
        paths = [ROOT / "README.md", ROOT / ".env.example", ROOT / "llms.txt"]
        paths += sorted((ROOT / "site" / "content").rglob("*.*"))
        paths += sorted((ROOT / "docs").rglob("*.html")) + [ROOT / "docs" / "llms.txt"]
        return [p for p in paths if p.is_file() and "get.brightdata.com" in p.read_text(encoding="utf-8")]

    def test_the_known_placements_are_found(self):
        names = {p.relative_to(ROOT).as_posix() for p in self._files()}

        assert {"README.md", ".env.example", "llms.txt", "docs/tools/index.html"} <= names

    def test_every_link_uses_the_scheme(self):
        for path in self._files():
            for raw in REFERRAL_URL_RE.findall(path.read_text(encoding="utf-8")):
                query = _query(raw.replace("&amp;", "&"))
                where = f"{path.relative_to(ROOT)}: {raw}"
                assert urlsplit(raw).path.lstrip("/") in REFERRAL_IDS.values(), where
                assert query.get("sid1") == query.get("utm_medium"), where
                assert query.get("sid2") == query.get("utm_campaign"), where
                assert query.get("utm_source") == "openosint", where
                assert query.get("utm_medium") in brightdata.SURFACES, where
                assert query.get("utm_campaign") in brightdata.CAMPAIGNS, where

    def test_every_file_with_a_link_discloses_it(self):
        for path in self._files():
            text = path.read_text(encoding="utf-8").lower()
            assert "commission" in text or "affiliate" in text, (
                f"{path.relative_to(ROOT)} has no disclosure"
            )

    def test_the_tools_page_and_llms_txt_disclose_next_to_the_links(self):
        for rel in ("docs/tools/index.html", "llms.txt"):
            assert "commission" in (ROOT / rel).read_text(encoding="utf-8").lower(), rel

    def test_the_stale_web_unlocker_sample_is_gone(self):
        page = (ROOT / "site" / "content" / "partials" / "tools-detail.html").read_text(
            encoding="utf-8"
        )

        assert "Remote status" not in page
        assert "[Web Unlocker] URL: https://example.com" in page
