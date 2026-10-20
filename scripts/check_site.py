#!/usr/bin/env python
"""Check the generated site in docs/ (the "controllo del sito").

    python scripts/check_site.py             # fails (exit 1) on any problem below
    python scripts/check_site.py --external  # report-only check of external links; always exits 0

Problems that fail: broken internal links or anchors, missing assets, pages without a title,
description, canonical or exactly one H1, titles over 60 or descriptions over 155 characters,
duplicate titles, http:// resources, sitemap entries that do not exist or are redirect stubs,
indexable pages missing from the sitemap, and generated output that is out of date.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE_HOST = "openosint.tech"
BEACON_PLACEHOLDER = "REPLACE_WITH_CLOUDFLARE_TOKEN"
REQUIRED_ICON_LINKS = {
    ("icon", "/favicon.ico"),
    ("icon", "/favicon.svg"),
    ("apple-touch-icon", "/apple-touch-icon.png"),
    ("manifest", "/site.webmanifest"),
}
BEACON_HOST = "static.cloudflareinsights.com"  # Cloudflare Web Analytics beacon, the one allowed third-party script
MAX_TITLE = 60
MAX_DESCRIPTION = 155
EXTERNAL_TIMEOUT_SECONDS = 15
EXTERNAL_WORKERS = 8
RESOURCE_TAGS = {"img", "script", "source", "video", "iframe"}


class PageInfo(HTMLParser):
    """Everything the checks need from one HTML file."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.in_title = False
        self.h1_count = 0
        self.description = ""
        self.canonical = ""
        self.robots = ""
        self.lang = ""
        self.ids: set[str] = set()
        self.links: list[str] = []  # <a href>
        self.resources: list[str] = []  # everything the browser loads
        self.json_ld: list[str] = []
        self.beacons = 0
        self.beacon_tokens: list[str] = []
        self.icon_links: set[tuple[str, str]] = set()
        self.meta_names: set[str] = set()
        self._ld_buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "meta":
            self.handle_meta(a)
        elif tag == "link":
            self.handle_link(a)
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._ld_buffer = []
        if tag == "script" and BEACON_HOST in a.get("src", "") and a.get("data-cf-beacon"):
            self.beacons += 1
            self.beacon_tokens.append(a["data-cf-beacon"])
        if tag in RESOURCE_TAGS and a.get("src"):
            self.resources.append(a["src"])
        if a.get("srcset"):
            self.resources += [part.split()[0] for part in a["srcset"].split(",") if part.strip()]

    def handle_meta(self, a: dict[str, str]) -> None:
        name = a.get("name") or a.get("property", "")
        self.meta_names.add(name)
        if name == "description":
            self.description = a.get("content", "")
        elif name == "robots":
            self.robots = a.get("content", "")
        elif name in ("og:image", "twitter:image"):
            self.resources.append(a.get("content", ""))

    def handle_link(self, a: dict[str, str]) -> None:
        self.icon_links.add((a.get("rel", ""), a.get("href", "")))
        if a.get("rel") == "canonical":
            self.canonical = a.get("href", "")
        elif a.get("href"):
            self.resources.append(a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "script" and self._ld_buffer is not None:
            self.json_ld.append("".join(self._ld_buffer))
            self._ld_buffer = None

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self._ld_buffer is not None:
            self._ld_buffer.append(data)


def is_redirect_stub(text: str) -> bool:
    return 'http-equiv="refresh"' in text


def parse(path: Path) -> PageInfo:
    info = PageInfo()
    info.feed(path.read_text(encoding="utf-8"))
    return info


def page_url(path: Path) -> str:
    rel = path.relative_to(DOCS).as_posix()
    return "/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)


def resolve(href: str, from_path: Path) -> tuple[Path | None, str] | None:
    """Map an internal href to (file or None when missing, fragment); None when not internal."""
    if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    url, fragment = urldefrag(href)
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if parsed.netloc != SITE_HOST:
            return None
        path = unquote(parsed.path) or "/"
    elif parsed.scheme or parsed.netloc:
        return None
    else:
        path = unquote(parsed.path)
    if not path:
        return from_path, fragment
    if not path.startswith("/"):
        path = page_url(from_path).rsplit("/", 1)[0] + "/" + path
    parts: list[str] = []
    for part in path.split("/"):
        if part == "..":
            parts = parts[:-1]
        elif part not in ("", "."):
            parts.append(part)
    target = DOCS.joinpath(*parts)
    if path.endswith("/") or not parts:
        target = target / "index.html"
    return (target if target.is_file() else None), fragment


def check_pages(pages: dict[Path, PageInfo]) -> list[str]:
    problems: list[str] = []
    seen: dict[tuple[str, str], Path] = {}
    for path, info in pages.items():
        name = path.relative_to(DOCS).as_posix()
        noindex = "noindex" in info.robots
        title, description = info.title.strip(), info.description.strip()
        if not title:
            problems.append(f"{name}: missing <title>")
        elif len(title) > MAX_TITLE:
            problems.append(f"{name}: title is {len(title)} characters (max {MAX_TITLE})")
        if not description:
            problems.append(f"{name}: missing meta description")
        elif len(description) > MAX_DESCRIPTION:
            problems.append(f"{name}: description is {len(description)} characters (max {MAX_DESCRIPTION})")
        if not noindex and not info.canonical:
            problems.append(f"{name}: missing canonical link")
        if info.h1_count != 1:
            problems.append(f"{name}: {info.h1_count} <h1> elements (need exactly 1)")
        if info.lang != "en":
            problems.append(f"{name}: <html lang> is {info.lang!r}, expected 'en'")
        if not noindex:
            problems += [
                f"{name}: missing {tag}"
                for tag in ("og:title", "og:description", "og:image", "twitter:card")
                if tag not in info.meta_names
            ]
        if info.beacons != 1:
            problems.append(f"{name}: {info.beacons} Cloudflare Analytics beacons (need exactly 1)")
        if any(BEACON_PLACEHOLDER in token or "<TOKEN>" in token for token in info.beacon_tokens):
            problems.append(f"{name}: Cloudflare Analytics token is still the placeholder")
        problems += [
            f"{name}: missing <link rel={rel!r} href={href!r}>" for rel, href in sorted(REQUIRED_ICON_LINKS - info.icon_links)
        ]
        for block in info.json_ld:
            try:
                json.loads(block)
            except ValueError as exc:
                problems.append(f"{name}: invalid JSON-LD ({exc})")
        for label, value in (("title", title), ("description", description)):
            first = seen.setdefault((label, value), path)
            if value and first != path:
                problems.append(f"{name}: same {label} as {first.relative_to(DOCS).as_posix()}")
    return problems


def check_links(pages: dict[Path, PageInfo]) -> list[str]:
    problems: list[str] = []
    for path, info in pages.items():
        name = path.relative_to(DOCS).as_posix()
        problems += [f"{name}: http:// resource {r}" for r in info.links + info.resources if r.startswith("http://")]
        for href in info.links:
            problems += link_problems(name, href, path, pages)
        for href in info.resources:
            target = resolve(href, path)
            if target is not None and target[0] is None:
                problems.append(f"{name}: missing asset {href}")
    for css in DOCS.glob("*.css"):
        for url in re.findall(r"url\(\s*[\"']?([^)\"']+)", css.read_text(encoding="utf-8")):
            target = resolve(url, css)
            if url.startswith("http://"):
                problems.append(f"{css.name}: http:// resource {url}")
            elif target is not None and target[0] is None:
                problems.append(f"{css.name}: missing asset {url}")
    return problems


def link_problems(name: str, href: str, path: Path, pages: dict[Path, PageInfo]) -> list[str]:
    target = resolve(href, path)
    if target is None:
        return []
    file, fragment = target
    if file is None:
        return [f"{name}: broken link {href}"]
    if fragment and file.suffix == ".html":
        info = pages.get(file) or parse(file)
        if fragment not in info.ids:
            return [f"{name}: broken anchor {href}"]
    return []


def check_manifest() -> list[str]:
    manifest = DOCS / "site.webmanifest"
    if not manifest.is_file():
        return ["site.webmanifest: missing"]
    try:
        icons = json.loads(manifest.read_text(encoding="utf-8")).get("icons", [])
    except ValueError as exc:
        return [f"site.webmanifest: invalid JSON ({exc})"]
    return [f"site.webmanifest: missing icon {i.get('src')}" for i in icons if not (DOCS / i.get("src", "").lstrip("/")).is_file()]


def check_sitemap(pages: dict[Path, PageInfo]) -> list[str]:
    sitemap = DOCS / "sitemap.xml"
    if not sitemap.is_file():
        return ["sitemap.xml: missing"]
    problems: list[str] = []
    listed: set[Path] = set()
    for loc in re.findall(r"<loc>([^<]+)</loc>", sitemap.read_text(encoding="utf-8")):
        resolved = resolve(loc, sitemap)
        file = resolved[0] if resolved else None
        if file is None:
            problems.append(f"sitemap.xml: {loc} does not exist (or is not on {SITE_HOST})")
        elif is_redirect_stub(file.read_text(encoding="utf-8")):
            problems.append(f"sitemap.xml: {loc} is a redirect stub")
        else:
            listed.add(file)
    problems += [
        f"sitemap.xml: missing indexable page {page_url(path)}"
        for path, info in pages.items()
        if "noindex" not in info.robots and path not in listed
    ]
    return problems


def check_generated() -> list[str]:
    sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
    try:
        import build_site
    except ImportError as exc:
        return [f"cannot verify generated output ({exc}); install the dev extra: pip install -e '.[dev]'"]
    try:
        return build_site.differences(build_site.build())
    except build_site.BuildError as exc:
        return [f"build failed: {exc}"]


def load_pages() -> dict[Path, PageInfo]:
    pages: dict[Path, PageInfo] = {}
    for path in sorted(DOCS.rglob("*.html")):
        if path.relative_to(DOCS).parts[0] == "assets":
            continue
        if not is_redirect_stub(path.read_text(encoding="utf-8")):
            pages[path] = parse(path)
    return pages


def run_checks() -> list[str]:
    pages = load_pages()
    return check_pages(pages) + check_links(pages) + check_manifest() + check_sitemap(pages) + check_generated()


def fetch_status(url: str) -> str:
    headers = {"User-Agent": "openosint-site-check/1.0"}
    status = "error"
    for method in ("HEAD", "GET"):
        try:
            with urlopen(Request(url, method=method, headers=headers), timeout=EXTERNAL_TIMEOUT_SECONDS) as resp:
                return str(resp.status)
        except Exception as exc:  # report-only: any failure is data, not an error
            code = getattr(exc, "code", None)
            status = str(code or type(exc).__name__)
            if method == "HEAD" and code in (403, 405, 501):
                continue  # some servers refuse HEAD; retry with GET
            return status
    return status


def report_external() -> None:
    found: dict[str, set[str]] = {}
    for path, info in load_pages().items():
        for href in info.links:
            if href.startswith(("http://", "https://")) and urlparse(href).netloc != SITE_HOST:
                found.setdefault(href, set()).add(path.relative_to(DOCS).as_posix())
    with ThreadPoolExecutor(EXTERNAL_WORKERS) as pool:
        statuses = dict(zip(found, pool.map(fetch_status, found)))
    bad = {url: s for url, s in statuses.items() if not s.startswith("2")}
    for url, status in sorted(bad.items()):
        print(f"{status}\t{url}\t(on {', '.join(sorted(found[url])[:3])})")
    print(f"checked {len(found)} external links, {len(bad)} not 2xx (report only, never fails CI)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--external", action="store_true", help="report on external links; always exits 0")
    args = parser.parse_args(argv)
    if args.external:
        report_external()
        return 0
    problems = run_checks()
    for line in problems:
        print(line, file=sys.stderr)
    print(f"check_site: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
