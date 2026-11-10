"""The Bright Data docs page quotes what the code really prints, discloses its referral link, and is linked."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from openosint.brightdata_response import classify
from openosint.tools import scrape_url, search_dorks_live, search_footprint

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "content" / "docs" / "bright-data.md"
BUILT = ROOT / "docs" / "docs" / "bright-data" / "index.html"
PAGE_URL = "openosint.tech/docs/bright-data/"
FAKE = "FAKE-token-not-real-0000"
SERP = {
    "organic": [
        {
            "title": "Example Domain",
            "link": "https://www.example.com/",
            "description": "This domain is for use in illustrative examples in documents.",
        },
        {
            "title": "Example Domain - Example Org",
            "link": "https://www.example.org/about",
            "description": "Another reserved example domain.",
        },
    ]
}


class Resp:
    def __init__(self, status=200, body="", headers=None, data=None):
        self.status_code, self.text, self.headers, self._data = status, body, headers or {}, data

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", FAKE)
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")
    monkeypatch.setenv("OPENOSINT_ALLOW_ACTIVE", "1")


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _serp(*_a, **_k):
    return Resp(200, json.dumps(SERP), data=SERP)


class TestExamplesAreTheRealOutput:
    def test_search_dorks_live(self, page, monkeypatch):
        monkeypatch.setattr(search_dorks_live.requests, "post", _serp)

        out = asyncio.run(search_dorks_live.run_dorks_live_osint("example.com", max_dorks=1))

        assert out.rstrip() in page

    def test_search_footprint(self, page, monkeypatch):
        monkeypatch.setattr(search_footprint.requests, "post", _serp)

        out = asyncio.run(search_footprint.run_footprint_osint("example.com", max_queries=1))

        assert out.rstrip() in page

    def test_scrape_url(self, page, monkeypatch):
        body = "# Example Domain\n\nThis domain is for use in illustrative examples in documents."
        monkeypatch.setattr(scrape_url.requests, "post", lambda *a, **k: Resp(200, body))

        out = asyncio.run(scrape_url.run_scrape_url_osint("https://example.com"))

        assert out in page

    def test_scrape_url_target_status_line(self, page, monkeypatch):
        body = "# Not Found\n\nThe requested page does not exist."
        monkeypatch.setattr(
            scrape_url.requests,
            "post",
            lambda *a, **k: Resp(200, body, {"x-brd-status-code": "404"}),
        )

        out = asyncio.run(scrape_url.run_scrape_url_osint("https://example.com/old-page"))

        assert "[Target returned HTTP 404]" in out and out in page


def _message(response, **kw) -> str:
    args = {
        "api_key": FAKE,
        "zone": "NAME",
        "zone_env": "BRIGHTDATA_SERP_ZONE",
        "product": "SERP API",
    }
    return str(classify(response, **{**args, **kw}))


class TestTroubleshootingQuotesTheCode:
    def test_every_message_is_verbatim(self, page):
        reject_block = {"x-brd-status-code": "403", "x-brd-error-code": "reject_block"}
        messages = [
            _message(Resp(401, "Invalid token")).replace("'Invalid token'", "'...'"),
            _message(Resp(400, 'zone "NAME" not found')),
            _message(Resp(200, "", {"x-brd-error-code": "client_10100"})),
            _message(Resp(502, "Bad Gateway")),
            _message(Resp(200, "", reject_block)),
        ]

        for message in messages:
            assert message in page, message

    def test_the_scrape_url_variant_the_page_describes_exists(self):
        message = _message(
            Resp(400, 'zone "NAME" not found'),
            zone_env="BRIGHTDATA_UNLOCKER_ZONE",
            product="Web Unlocker",
        )

        assert "Web Unlocker zone" in message and "BRIGHTDATA_UNLOCKER_ZONE" in message


class TestDisclosureAndLinks:
    def test_the_disclosure_comes_before_the_first_referral_link(self, page):
        first_link = page.index("%%BRIGHTDATA_LINK_")

        assert "commission" in page[:first_link]

    def test_every_referral_link_is_marked_sponsored(self, page):
        links = re.findall(r"\(%%BRIGHTDATA_LINK_\w+%%\)(\{:[^}]*\})?", page)

        assert links and all("sponsored" in attrs for attrs in links)

    def test_the_built_page_uses_the_docs_scheme(self):
        built = BUILT.read_text(encoding="utf-8")

        link = re.search(r'<a [^>]*href="(https://get\.brightdata\.com/[^"]+)"[^>]*>', built)
        assert link and 'rel="sponsored noopener"' in link.group(0)
        assert "utm_medium=docs" in link.group(1) and "utm_campaign=docs" in link.group(1)
        assert "commission" in built

    def test_the_article_is_a_plain_brightdata_link(self, page):
        assert "](https://brightdata.com/blog/how-tos/openosint-with-bright-data)" in page

    @pytest.mark.parametrize("path", ["README.md", "site/content/tools.html", "llms.txt"])
    def test_the_page_is_linked_from(self, path):
        text = (ROOT / path).read_text(encoding="utf-8")

        assert PAGE_URL in text or "/docs/bright-data/" in text
