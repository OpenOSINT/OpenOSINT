"""The site generator and checker: generated docs/ must match site/, and the checks must catch breakage."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("jinja2")  # dev extra: pip install -e ".[dev]"
pytest.importorskip("markdown")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402
import check_site  # noqa: E402


def _version() -> str:
    return re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def test_generated_docs_match_a_fresh_build():
    assert build_site.differences(build_site.build()) == []


def test_site_checks_pass_on_the_committed_site():
    assert check_site.run_checks() == []


def test_docs_show_the_current_version():
    for page in ("docs/index.html", "docs/install/index.html"):
        assert f"Version {_version()}" in (ROOT / "docs" / page).read_text(encoding="utf-8")


def test_sitemap_lists_docs_pages_and_no_redirect_stubs():
    locs = re.findall(r"<loc>([^<]+)</loc>", (ROOT / "docs" / "sitemap.xml").read_text(encoding="utf-8"))
    assert "https://openosint.tech/docs/install/" in locs
    assert "https://openosint.tech/learn/" not in locs
    assert "https://openosint.tech/404.html" not in locs


def test_llms_txt_lists_every_docs_page():
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    urls = {f"https://openosint.tech{url}" for url in re.findall(r'href="(/docs/[^"#]*)"', (ROOT / "docs" / "docs" / "index.html").read_text(encoding="utf-8"))}
    assert urls and all(url in llms for url in urls), sorted(u for u in urls if u not in llms)
    assert (ROOT / "docs" / "llms.txt").read_text(encoding="utf-8") == llms


def test_documented_env_vars_exist_in_the_code():
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "openosint").rglob("*.py"))
    documented = set()
    for page in (ROOT / "docs" / "docs").rglob("index.html"):
        documented |= set(re.findall(r"\b(?:OPENOSINT|ANTHROPIC|OPENAI)_[A-Z0-9_]+\b", page.read_text(encoding="utf-8")))
    missing = sorted(name for name in documented if name not in source)
    assert not missing, f"documented but not in the code: {missing}"


def test_every_setting_in_the_catalog_is_documented():
    from openosint.settings_catalog import SETTINGS

    page = (ROOT / "docs" / "docs" / "configuration" / "index.html").read_text(encoding="utf-8")
    assert [s.key for s in SETTINGS if s.key not in page] == []


def _icons(root: Path) -> None:
    for name in ("favicon.ico", "favicon.svg", "apple-touch-icon.png"):
        _write(root, name, "x")
    _write(root, "site.webmanifest", '{"icons": [{"src": "/icon-192.png"}]}')


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


BEACON = (
    '<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" '
    'data-cf-beacon=\'{"token": "t"}\'></script>'
)
GOOD_HEAD = (
    '<!DOCTYPE html><html lang="en"><head><title>Page</title><meta name="description" content="A page.">'
    '<link rel="canonical" href="https://openosint.tech/">'
    '<link rel="icon" href="/favicon.ico"><link rel="icon" href="/favicon.svg">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="manifest" href="/site.webmanifest">'
    '<meta property="og:title" content="t"><meta property="og:description" content="d">'
    '<meta property="og:image" content="https://openosint.tech/img.png"><meta name="twitter:card" content="c">'
)


def test_checker_reports_each_kind_of_breakage(tmp_path, monkeypatch):
    monkeypatch.setattr(check_site, "DOCS", tmp_path)
    _write(tmp_path, "img.png", "x")
    _write(
        tmp_path,
        "index.html",
        GOOD_HEAD + '</head><body><h1>A</h1><h1>B</h1><a href="/gone/">x</a><a href="/other/#nope">y</a>'
        '<img src="/missing.png"><script src="http://example.com/a.js"></script></body></html>',
    )
    _write(tmp_path, "other/index.html", GOOD_HEAD.replace("<title>Page</title>", "") + "</head><body><h1 id='ok'>O</h1></body></html>")
    _write(tmp_path, "old/index.html", '<html><meta http-equiv="refresh" content="0; url=/"></html>')
    _write(
        tmp_path,
        "sitemap.xml",
        "<urlset><url><loc>https://openosint.tech/</loc></url><url><loc>https://openosint.tech/old/</loc></url>"
        "<url><loc>https://openosint.tech/ghost/</loc></url></urlset>",
    )
    pages = check_site.load_pages()
    problems = check_site.check_pages(pages) + check_site.check_links(pages) + check_site.check_sitemap(pages)
    text = "\n".join(problems)
    for expected in (
        "2 <h1> elements",
        "missing <title>",
        "broken link /gone/",
        "broken anchor /other/#nope",
        "missing asset /missing.png",
        "http:// resource http://example.com/a.js",
        "/old/ is a redirect stub",
        "/ghost/ does not exist",
        "missing indexable page /other/",
    ):
        assert expected in text, f"not reported: {expected}\n{text}"


def test_checker_accepts_a_clean_page(tmp_path, monkeypatch):
    monkeypatch.setattr(check_site, "DOCS", tmp_path)
    _write(tmp_path, "img.png", "x")
    _icons(tmp_path)
    _write(tmp_path, "icon-192.png", "x")
    _write(tmp_path, "index.html", GOOD_HEAD + '</head><body><h1 id="top">A</h1><a href="#top">up</a>' + BEACON + '</body></html>')
    _write(tmp_path, "sitemap.xml", "<urlset><url><loc>https://openosint.tech/</loc></url></urlset>")
    pages = check_site.load_pages()
    problems = check_site.check_pages(pages) + check_site.check_links(pages) + check_site.check_manifest()
    assert problems + check_site.check_sitemap(pages) == []


def test_no_unexpanded_tokens_in_output():
    leaked = [str(p.relative_to(ROOT)) for p in (ROOT / "docs").rglob("*.html") if "%%" in p.read_text(encoding="utf-8")]
    assert leaked == []


def test_checker_requires_exactly_one_analytics_beacon(tmp_path, monkeypatch):
    monkeypatch.setattr(check_site, "DOCS", tmp_path)
    beacon = BEACON
    _write(tmp_path, "img.png", "x")
    _write(tmp_path, "none/index.html", GOOD_HEAD + "</head><body><h1>A</h1></body></html>")
    _write(tmp_path, "two/index.html", GOOD_HEAD + "</head><body><h1>B</h1>" + beacon * 2 + "</body></html>")
    _write(tmp_path, "one/index.html", GOOD_HEAD.replace("Page", "Other").replace("A page.", "Another.") + "</head><body><h1>C</h1>" + beacon + "</body></html>")
    text = "\n".join(check_site.check_pages(check_site.load_pages()))
    assert "none/index.html: 0 Cloudflare Analytics beacons" in text
    assert "two/index.html: 2 Cloudflare Analytics beacons" in text
    assert "one/index.html: 1 Cloudflare" not in text


def test_checker_rejects_placeholder_token_and_missing_icons(tmp_path, monkeypatch):
    monkeypatch.setattr(check_site, "DOCS", tmp_path)
    placeholder = BEACON.replace('"t"', '"REPLACE_WITH_CLOUDFLARE_TOKEN"')
    head = GOOD_HEAD.replace('<link rel="manifest" href="/site.webmanifest">', "")
    _write(tmp_path, "index.html", head + "</head><body><h1>A</h1>" + placeholder + "</body></html>")
    text = "\n".join(check_site.check_pages(check_site.load_pages()) + check_site.check_manifest())
    assert "still the placeholder" in text
    assert "rel='manifest'" in text
    assert "site.webmanifest: missing" in text
