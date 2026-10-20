#!/usr/bin/env python
"""Build openosint.tech: Jinja2 layouts + Markdown/HTML content in site/ -> generated HTML in docs/.

    python scripts/build_site.py           # write generated files into docs/
    python scripts/build_site.py --check   # exit 1 if docs/ differs from a fresh build

Needs the dev extra (jinja2, markdown). Docs facts (env vars, noise levels, tool list, version) are
read from the package itself, so the pages cannot drift from the code.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DOCS = ROOT / "docs"
BASE_URL = "https://openosint.tech"
REPO_URL = "https://github.com/OpenOSINT/OpenOSINT"
HOSTED_URL = "https://app.openosint.tech/?utm_source=openosint.tech&utm_medium=referral&utm_campaign=nav"
CONTACT = "mailto:commercial@openosint.tech"
WORDS_PER_MINUTE = 220
# MCP-only helpers that are not part of the "N investigation tools" catalog (same set as tests/test_docs_consistency.py).
NON_CATALOG_TOOLS = {"investigate_multi", "graph_export", "graph_neighbors", "graph_review_candidates"}

NAV = [
    {"label": "Docs", "href": "/docs/", "section": "docs", "external": False},
    {"label": "Tools", "href": "/tools/", "section": "tools", "external": False},
    {"label": "Blog", "href": "/blog/", "section": "blog", "external": False},
    {"label": "GitHub", "href": REPO_URL, "section": "", "external": True},
]
FOOTER = [
    {"label": "Blog", "href": "/blog/"},
    {"label": "Tools", "href": "/tools/"},
    {"label": "Commercial", "href": "/commercial/"},
    {"label": "Sponsors", "href": "/sponsors.html"},
    {"label": "Terms", "href": "/terms/"},
    {"label": "Privacy", "href": "/privacy/"},
    {"label": "Acceptable Use", "href": "/acceptable-use/"},
    {"label": "Subprocessors", "href": "/subprocessors/"},
    {"label": "Contact", "href": CONTACT},
]


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------- sources


def split_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise BuildError(f"{path}: missing front matter")
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        raise BuildError(f"{path}: unterminated front matter")
    return yaml.safe_load(head) or {}, body.lstrip("\n")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((SITE / "data" / name).read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def project_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    if not match:
        raise BuildError("version not found in pyproject.toml")
    return match.group(1)


def stars_display(stars: int) -> str:
    step = 100 if stars >= 1000 else 10
    return f"{stars // step * step:,}+"


def git_date(path: str) -> str:
    """Last commit date of a source file (YYYY-MM-DD); today while it is not committed yet."""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", path], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    return out or datetime.date.today().isoformat()


# --------------------------------------------------------------------------- facts read from the package


def tool_names() -> list[str]:
    src = (ROOT / "openosint" / "mcp_server.py").read_text(encoding="utf-8")
    seen: list[str] = []
    for name in re.findall(r'name="([a-z0-9_]+)"', src):
        if name not in NON_CATALOG_TOOLS and name not in seen:
            seen.append(name)
    return seen


def config_keys_markdown() -> str:
    from openosint.settings_catalog import SETTINGS

    rows = ["| Variable | Used by | Needed | Notes |", "|---|---|---|---|"]
    for s in sorted(SETTINGS, key=lambda s: (s.group != "ai", s.optional, s.key)):
        used = ", ".join(f"`{u}`" for u in s.used_by)
        needed = "optional" if s.optional else ("one provider" if s.group == "ai" else "required for those tools")
        rows.append(f"| `{s.key}` | {used} | {needed} | {s.note} |")
    return "\n".join(rows)


def noise_markdown() -> str:
    from openosint.tool_policy import markdown_table

    return markdown_table()


def token_values() -> dict[str, str]:
    from openosint.agent import DEFAULT_ANTHROPIC_MODEL
    from openosint.brightdata import BRIGHTDATA_LINK_SITE_DOCS
    from openosint.tool_policy import DEFAULT_MAX_CALLS, DEFAULT_MAX_CALLS_MULTI

    return {
        "VERSION": project_version(),
        "BRIGHTDATA_LINK_DOCS": BRIGHTDATA_LINK_SITE_DOCS,
        "MAX_CALLS": str(DEFAULT_MAX_CALLS),
        "MAX_CALLS_MULTI": str(DEFAULT_MAX_CALLS_MULTI),
        "DEFAULT_MODEL": DEFAULT_ANTHROPIC_MODEL,
        "TOOL_COUNT": str(len(tool_names())),
        "POST_COUNT": str(len(list((SITE / "content" / "blog").glob("*.html")))),
    }


def tools_table_html() -> str:
    from openosint.brightdata import BRIGHTDATA_LINK_SITE_TOOLS
    from openosint.settings_catalog import SETTINGS
    from openosint.tool_policy import TOOL_POLICY

    data = load_yaml("tools.yaml")
    names = tool_names()
    if set(data) != set(names):
        raise BuildError(f"site/data/tools.yaml out of sync with mcp_server.py: {sorted(set(data) ^ set(names))}")
    rows = []
    for name in names:
        info, policy = data[name], TOOL_POLICY[name]
        needs = [f"<code>{s.key}</code>" + (" (optional)" if s.optional else "") for s in SETTINGS if name in s.used_by]
        if info.get("binary"):
            needs.insert(0, f"<code>{info['binary']}</code> on PATH")
        if not policy.is_passive:
            needs.append("<code>--allow-active</code>")
        method = html.escape(info["method"])
        if info["method"].startswith("Bright Data"):
            method = f'<a href="{html.escape(BRIGHTDATA_LINK_SITE_TOOLS)}" target="_blank" rel="noopener">{method}</a>'
        rows.append(
            f'<tr><td><a href="#{name}"><code>{name}</code></a></td><td>{method}</td>'
            f'<td>{html.escape(info["finds"])}</td><td>{policy.noise.value}</td>'
            f'<td class="needs">{"; ".join(needs) or "&mdash;"}</td></tr>'
        )
    head = "<tr><th>Tool</th><th>Source</th><th>What it finds</th><th>Noise</th><th>Needs</th></tr>"
    return "<table>\n" + head + "\n" + "\n".join(rows) + "\n</table>"


def keyless_markdown() -> str:
    from openosint.settings_catalog import SETTINGS

    needing_key = {tool for s in SETTINGS if not s.optional and s.group == "tools" for tool in s.used_by}
    return ", ".join(f"`{name}`" for name in tool_names() if name not in needing_key)


GENERATORS = {"config-keys": config_keys_markdown, "noise": noise_markdown, "keyless": keyless_markdown}


def expand_tokens(text: str) -> str:
    for token, value in token_values().items():
        text = text.replace(f"%%{token}%%", value)
    return re.sub(r"<!-- gen:([a-z-]+) -->", lambda m: GENERATORS[m.group(1)](), text)


def expand_meta(meta: dict) -> dict:
    return {k: expand_tokens(v) if isinstance(v, str) else v for k, v in meta.items()}


# --------------------------------------------------------------------------- rendering helpers


def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "attr_list", "sane_lists"])
    return wrap_tables(md.convert(expand_tokens(text)))


def wrap_tables(body: str) -> str:
    return re.sub(
        r"<table>.*?</table>",
        lambda m: f'<div class="table-wrap" tabindex="0" role="region" aria-label="Table">{m.group(0)}</div>',
        body,
        flags=re.S,
    )


def reading_minutes(body: str) -> int:
    words = len(re.sub(r"<[^>]+>", " ", body).split())
    return max(1, math.ceil(words / WORDS_PER_MINUTE))


def ld(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False).replace("</", "<\\/")


def seo_title(meta: dict) -> str:
    if meta.get("seo_title"):
        return meta["seo_title"]
    suffixed = f"{meta['title']} | OpenOSINT"
    return suffixed if len(suffixed) <= 60 else meta["title"]


def make_page(url: str, template: str, meta: dict, body: str = "", **extra) -> dict:
    out = url.lstrip("/")
    out = out + "index.html" if out == "" or out.endswith("/") else out
    return {
        "url": url,
        "out": out,
        "template": template,
        "title": meta["title"],
        "seo_title": seo_title(meta),
        "description": meta["description"],
        "canonical": BASE_URL + url,
        "og_type": "website",
        "section": "",
        "noindex": False,
        "jsonld": [],
        "scripts": [],
        "body": body,
        "body_has_h1": "<h1" in body,
        **extra,
    }


def software_ld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": "OpenOSINT",
        "description": "Open-source engine for passive checks of public information: CLI, MCP server and web UI.",
        "codeRepository": REPO_URL,
        "programmingLanguage": "Python",
        "license": "https://opensource.org/licenses/MIT",
        "url": BASE_URL + "/",
    }


def org_ld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "OpenOSINT",
        "url": BASE_URL + "/",
        "logo": BASE_URL + "/logo.svg",
        "description": "Open-source engine for passive checks of public information, with hosted products Monitor and Diligence.",
        "email": "commercial@openosint.tech",
        "sameAs": [REPO_URL, "https://app.openosint.tech/"],
    }


def breadcrumb_ld(crumbs: list[dict]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": c["name"], "item": BASE_URL + c["url"]}
            for i, c in enumerate(crumbs, 1)
        ],
    }


# --------------------------------------------------------------------------- page collection


def docs_pages(group_order: list[str]) -> tuple[list[dict], list[dict]]:
    """Return (pages, sidebar groups). Order and grouping come from each page's front matter."""
    loaded = [(p, *split_front_matter(p)) for p in (SITE / "content" / "docs").glob("*.md")]
    loaded.sort(key=lambda item: item[1]["order"])
    entries = [
        {"url": "/docs/" if p.stem == "index" else f"/docs/{p.stem}/", "label": m.get("label", m["title"]), "group": m["group"]}
        for p, m, _ in loaded
    ]
    groups = [{"title": g, "links": [e for e in entries if e["group"] == g]} for g in group_order]
    # The generated tools reference lives outside /docs/ but belongs in the sidebar, first under Reference.
    groups[-1] = {**groups[-1], "links": [{"url": "/tools/", "label": "Tools reference"}, *groups[-1]["links"]]}
    pages = []
    for i, (path, meta, body) in enumerate(loaded):
        entry = entries[i]
        crumbs = [{"name": "Home", "url": "/"}, {"name": "Docs", "url": "/docs/"}]
        if entry["url"] != "/docs/":
            crumbs.append({"name": entry["label"], "url": entry["url"]})
        jsonld = [ld(breadcrumb_ld(crumbs))]
        if entry["url"] == "/docs/":
            jsonld.insert(0, ld(software_ld()))
        pages.append(
            make_page(
                entry["url"], "doc.html", expand_meta(meta), render_markdown(body), section="docs", jsonld=jsonld,
                breadcrumbs=crumbs, source=rel(path), edit_url=f"{REPO_URL}/edit/main/{rel(path)}",
                prev=entries[i - 1] if i else None,
                next=entries[i + 1] if i + 1 < len(entries) else None,
            )
        )
    return pages, groups


def blog_pages() -> list[dict]:
    pages = []
    for path in (SITE / "content" / "blog").glob("*.html"):
        meta, body = split_front_matter(path)
        url = f"/blog/{path.name}"
        date, modified = str(meta["date"]), str(meta.get("modified", meta["date"]))
        article = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": meta["title"],
            "description": meta["description"],
            "author": {"@type": "Organization", "name": "OpenOSINT"},
            "publisher": {"@type": "Organization", "name": "OpenOSINT", "url": BASE_URL + "/"},
            "datePublished": date,
            "dateModified": modified,
            "mainEntityOfPage": BASE_URL + url,
            "image": BASE_URL + "/assets/og.png",
        }
        body = wrap_tables(body)
        pages.append(
            make_page(
                url, "post.html", meta, body, section="blog", og_type="article", jsonld=[ld(article)],
                date=date, modified=modified, reading_minutes=reading_minutes(body), source=rel(path),
            )
        )
    return sorted(pages, key=lambda p: (p["date"], p["url"]), reverse=True)


def static_pages() -> list[dict]:
    pages = []
    for path in sorted((SITE / "content" / "pages").glob("*.html")):
        meta, body = split_front_matter(path)
        pages.append(
            make_page(
                meta["url"], meta.get("template", "page.html"), meta, wrap_tables(body),
                section=meta.get("section", ""), noindex=bool(meta.get("noindex")),
                scripts=meta.get("scripts", []), source=rel(path),
            )
        )
    return pages


def special_pages(posts: list[dict]) -> list[dict]:
    home = make_page(
        "/", "home.html", expand_meta(load_yaml("home.yaml")), jsonld=[ld(org_ld()), ld(software_ld())],
        source="site/layouts/home.html",
    )
    tools_meta, tools_intro = split_front_matter(SITE / "content" / "tools.html")
    tools_meta, tools_intro = expand_meta(tools_meta), expand_tokens(tools_intro)
    detail = (SITE / "content" / "partials" / "tools-detail.html").read_text(encoding="utf-8")
    tools_crumbs = [
        {"name": "Home", "url": "/"}, {"name": "Docs", "url": "/docs/"}, {"name": "Tools reference", "url": "/tools/"}
    ]
    tools = make_page(
        "/tools/", "doc.html", tools_meta,
        wrap_tables(tools_intro + "\n" + tools_table_html() + "\n<hr>\n" + detail),
        section="tools", source="site/content/tools.html", jsonld=[ld(breadcrumb_ld(tools_crumbs))],
        breadcrumbs=tools_crumbs, edit_url=f"{REPO_URL}/edit/main/site/content/tools.html", prev=None, next=None,
    )
    blog_meta = load_yaml("blog.yaml")
    blog = make_page(
        "/blog/", "blog_index.html", expand_meta(blog_meta), section="blog", intro=blog_meta["intro"],
        posts=[{"url": p["url"], "title": p["title"], "date": p["date"], "summary": p["description"]} for p in posts],
        source="site/data/blog.yaml",
    )
    not_found = make_page(
        "/404.html", "page.html",
        {
            "title": "Page not found",
            "description": "This page does not exist on openosint.tech. Use the docs, tools or blog links to find what you were looking for.",
        },
        '<p>The page you asked for does not exist or has moved.</p>\n<ul>\n<li><a href="/">Home</a></li>\n'
        '<li><a href="/docs/">Documentation</a></li>\n<li><a href="/tools/">Tools reference</a></li>\n'
        '<li><a href="/blog/">Blog</a></li>\n</ul>',
        noindex=True, source="scripts/build_site.py",
    )
    return [home, tools, blog, not_found]


def sitemap_xml(pages: list[dict]) -> str:
    entries = []
    for page in sorted(pages, key=lambda p: p["url"]):
        if page["noindex"]:
            continue
        lastmod = page.get("modified") or git_date(page["source"])
        entries.append(f"  <url>\n    <loc>{BASE_URL}{page['url']}</loc>\n    <lastmod>{lastmod}</lastmod>\n  </url>")
    body = "\n".join(entries)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'


# --------------------------------------------------------------------------- build


def build() -> dict[str, str]:
    """Return {path relative to docs/: file text} for every generated file."""
    cfg = load_yaml("site.yaml")
    docs, groups = docs_pages(cfg["docs_groups"])
    posts = blog_pages()
    pages = docs + posts + static_pages() + special_pages(posts)
    urls = [p["url"] for p in pages]
    if len(urls) != len(set(urls)):
        raise BuildError(f"duplicate page urls: {sorted({u for u in urls if urls.count(u) > 1})}")
    site = {
        "version": project_version(),
        "stars_display": stars_display(cfg["stars"]),
        "tool_count": len(tool_names()),
        "cf_analytics_token": cfg["cf_analytics_token"],
        "docs_groups": groups,
        "nav": NAV,
        "footer": FOOTER,
        "hosted_url": HOSTED_URL,
        "og_image": BASE_URL + "/assets/og.png",
    }
    env = Environment(
        loader=FileSystemLoader([SITE / "layouts", SITE / "content"]), undefined=StrictUndefined, autoescape=True
    )
    outputs = {
        p["out"]: env.get_template(p["template"]).render(page=p, site=site, posts=p.get("posts", [])) for p in pages
    }
    outputs["sitemap.xml"] = sitemap_xml(pages)
    outputs["robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n"
    outputs["llms.txt"] = (ROOT / "llms.txt").read_text(encoding="utf-8")
    return outputs


def is_redirect_stub(text: str) -> bool:
    return 'http-equiv="refresh"' in text


def stale_files(outputs: dict[str, str]) -> list[str]:
    """HTML in docs/ that is neither generated nor a redirect stub."""
    stale = []
    for path in sorted(DOCS.rglob("*.html")):
        key = path.relative_to(DOCS).as_posix()
        if key.startswith("assets/") or key in outputs:
            continue
        if not is_redirect_stub(path.read_text(encoding="utf-8")):
            stale.append(key)
    return stale


def normalize_sitemap(text: str) -> str:
    # lastmod comes from git history, which moves when the regenerated files are committed.
    return re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod/>", text)


def differences(outputs: dict[str, str]) -> list[str]:
    problems = []
    for key, text in outputs.items():
        path = DOCS / key
        if not path.exists():
            problems.append(f"missing: docs/{key}")
            continue
        current = path.read_text(encoding="utf-8")
        same = normalize_sitemap(current) == normalize_sitemap(text) if key == "sitemap.xml" else current == text
        if not same:
            problems.append(f"out of date: docs/{key}")
    problems += [f"stale (not generated, not a redirect stub): docs/{key}" for key in stale_files(outputs)]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/ differs from a fresh build")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    try:
        outputs = build()
    except BuildError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 2
    if args.check:
        problems = differences(outputs)
        for line in problems:
            print(line, file=sys.stderr)
        if problems:
            print("run: python scripts/build_site.py", file=sys.stderr)
        return 1 if problems else 0
    for key, text in outputs.items():
        path = DOCS / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    print(f"wrote {len(outputs)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
