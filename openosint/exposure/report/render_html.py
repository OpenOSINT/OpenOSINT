"""One self-contained HTML file: inline CSS, no JavaScript, no external resources.

Every dynamic value (hosts, evidence, reasons, registrar names...) is attacker-influenced, so
everything that is not a fixed structural tag goes through esc().
"""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openosint import __version__
from openosint.exposure.lookalikes_check import defang
from openosint.exposure.models import (
    STATUS_ERROR,
    STATUS_OK,
    CheckResult,
    ExposureReport,
    Finding,
    LookalikeScan,
)
from openosint.exposure.report import catalog_en, catalog_it
from openosint.exposure.report.priorities import sort_key, top_priorities
from openosint.exposure.scoring import INCOMPLETE, REQUIRED_CHECKS

REPORT_VERSION = 1
CATALOGS = {"en": catalog_en.CATALOG, "it": catalog_it.CATALOG}
DYNAMIC_TITLE_IDS = catalog_en.DYNAMIC_TITLE_IDS
CATEGORY_ORDER = ("email", "tls", "registration", "http_headers")
# info findings whose "why it matters" adds something the title does not
KEEP_WHY_IDS = ("mx_missing", "dkim_not_found_common_selectors", "dkim_unverified", "tls_unreachable_443")
HIDDEN_IDS = ("domain_age",)  # shown as a "Verified" line instead of a card
DATE_KEYS = ("date", "created")
GROUPED_SEVERITIES = ("low", "info")  # header findings this mild share one table card
STATUS_ICONS = {"ok": "\u2713", "improve": "!", "urgent": "\u25b2", "critical": "\u2715", "unverified": "?"}
ROME = "Europe/Rome"

CSS = """
:root{--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--bg:#fff;--card:#f6f8fa}
*{box-sizing:border-box}
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:var(--fg);background:var(--bg);margin:0}
main{max-width:860px;margin:0 auto;padding:24px 16px 40px}
h1{font-size:1.5rem;margin:0 0 4px}
h2{font-size:1.2rem;margin:28px 0 10px;border-bottom:2px solid var(--line);padding-bottom:4px;break-after:avoid}
h3{font-size:1rem;margin:0 0 6px}
.meta{color:var(--muted);margin:0}
.head{display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin-top:16px}
.badge{width:104px;height:104px;border-radius:14px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#fff;font-weight:700;text-align:center;padding:6px}
.badge .g{font-size:3rem;line-height:1}.badge .g.long{font-size:1.1rem}
.g-A{background:#1a7f37}.g-B{background:#4c8c2b}.g-C{background:#9a6700}.g-D{background:#bc4c00}.g-F{background:#cf222e}.g-incomplete{background:#57606a}
.score{font-size:1.4rem;font-weight:600}
.meaning{font-size:1.05rem;font-weight:600}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top;font-size:.9rem}
th{background:var(--card)}td.n,th.n{text-align:center;width:64px}
.prio{padding-left:0;list-style:none;margin:6px 0}.prio li{margin:6px 0;break-inside:avoid}.prio .act{color:var(--muted)}
.st-critical{color:#82071e;font-weight:700}.st-urgent{color:#cf222e;font-weight:700}.st-improve{color:#9a6700;font-weight:700}.st-ok{color:#1a7f37;font-weight:700}.st-unverified{color:var(--muted);font-weight:700}
.info{font-size:.85rem;color:var(--muted);margin:6px 0;padding-left:8px;border-left:3px solid var(--line);break-inside:avoid}
.info .sev{font-size:.75rem;background:#8c959f}.info .ev{font:11.5px/1.3 ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
.vh{font-weight:600;margin:10px 0 2px;break-after:avoid}ul.ok{list-style:none;padding-left:0;margin:2px 0;font-size:.9rem}ul.ok li{margin:1px 0;word-break:break-word}ul.ok li:before{content:"✓ ";color:#1a7f37;font-weight:700}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0;break-inside:avoid}
.sev{display:inline-block;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.03em;border-radius:4px;padding:1px 7px;margin-right:6px;color:#fff;vertical-align:middle}
.sev-critical{background:#82071e}.sev-high{background:#cf222e}.sev-medium{background:#9a6700}.sev-low{background:#0969da}.sev-info{background:#57606a}
.lbl{font-weight:600}
pre.ev{font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;background:#fff;border:1px solid var(--line);border-radius:4px;padding:6px 8px;margin:6px 0 0;white-space:pre-wrap;word-break:break-all}
.status{border-left:4px solid #9a6700;background:#fff8c5;padding:6px 10px;margin:10px 0;break-inside:avoid}
.small{font-size:.85rem;color:var(--muted)}
table.gl th{background:none;width:150px;font-size:inherit;white-space:nowrap}table.gl td{font-size:inherit}table.gl tr{break-inside:avoid}
table.lk tr{break-inside:avoid}table.lk thead{display:table-header-group}
code,.nb{font:12px/1.4 ui-monospace,Menlo,Consolas,monospace}.nb{white-space:nowrap}td code{font-size:inherit}
footer{margin-top:32px;padding-top:10px;border-top:1px solid var(--line);color:var(--muted);font-size:.85rem}
@page{size:A4;margin:12mm}
@media print{body{font-size:9.5pt;line-height:1.35;-webkit-print-color-adjust:exact;print-color-adjust:exact}main{max-width:none;padding:0}h1{font-size:1.3rem}h2{margin:12px 0 6px;font-size:1.1rem}.badge{width:80px;height:80px}.badge .g{font-size:2.2rem}.head{margin-top:8px;gap:16px}.card{background:#fff;padding:6px 10px;margin:6px 0}.card p{margin:3px 0}pre.ev{font-size:8.5pt;padding:3px 6px;margin:3px 0 0}th,td{padding:3px 6px}.prio li{margin:4px 0}footer{margin-top:14px}table.gl th{width:130px}code,.nb{font-size:9pt}}
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_checked_at(iso: str, lang: str) -> str:
    """EN: UTC. IT: Europe/Rome local time with the UTC time alongside (UTC only if tzdata is missing)."""
    utc = datetime.fromisoformat(iso)
    if lang == "it":
        try:
            local = utc.astimezone(ZoneInfo(ROME))
        except ZoneInfoNotFoundError:
            return f"{utc:%d/%m/%Y %H:%M} UTC"
        return f"{local:%d/%m/%Y %H:%M} (ora di Roma, {utc:%H:%M} UTC)"
    return f"{utc:%Y-%m-%d %H:%M} UTC"


def _title(cat: dict, f: Finding) -> str:
    title = cat["findings"][f.id]["title"]
    if f.id in DYNAMIC_TITLE_IDS:  # the only titles with a placeholder; filled with an integer
        title = title.format(days=int(f.days_left) if f.days_left is not None else "?")
    return title


def _fill(cat: dict, template: str, data: tuple) -> str:
    """Catalog template + raw values (None = unknown). Values are verbatim; the caller escapes the result."""
    ui = cat["ui"]
    values = {k: ui["unknown"] if v is None else v for k, v in data}
    for key in DATE_KEYS:
        if key in values and values[key] != ui["unknown"]:
            values[key] = date.fromisoformat(values[key]).strftime(ui["date_fmt"])
    if "age_months" in values:
        values["age"] = _age_text(ui, int(values["age_months"]))
    return template.format(**values)


def _age_text(ui: dict, months: int) -> str:
    n, unit = (months // 12, "year") if months >= 24 else (months, "month")
    return ui[f"age_{unit}_one"] if n == 1 else ui[f"age_{unit}"].format(n=n)


def _evidence(cat: dict, f: Finding) -> str:
    """Evidence in the report language; the raw English string only when no template applies."""
    template = cat["evidence"].get(f.ev_id or "")
    if template:
        try:
            return _fill(cat, template, f.ev_data)
        except (KeyError, IndexError, ValueError):
            pass
    return f.evidence


def _sev_tag(cat: dict, severity: str) -> str:
    return f'<span class="sev sev-{esc(severity)}">{esc(cat["severity"][severity])}</span>'


def _finding_card(cat: dict, f: Finding, anchor: str) -> str:
    text = cat["findings"][f.id]
    ui = cat["ui"]
    return (
        f'<div class="card" id="{esc(anchor)}"><h3>{_sev_tag(cat, f.severity)}{esc(_title(cat, f))}</h3>'
        f'<p><span class="lbl">{esc(ui["why"])}:</span> {esc(text["why_it_matters"])}</p>'
        f'<p><span class="lbl">{esc(ui["fix"])}:</span> {esc(text["how_to_fix"])}</p>'
        f'<p class="small">{esc(ui["evidence"])}:</p><pre class="ev">{esc(_evidence(cat, f))}</pre></div>'
    )


def _info_item(cat: dict, f: Finding, anchor: str) -> str:
    why = f'<div>{esc(cat["findings"][f.id]["why_it_matters"])}</div>' if f.id in KEEP_WHY_IDS else ""
    return (
        f'<div class="info" id="{esc(anchor)}">{_sev_tag(cat, f.severity)}{esc(_title(cat, f))}{why}'
        f'<div class="ev">{esc(_evidence(cat, f))}</div></div>'
    )


def _nowrap(text: str) -> str:
    """Escaped text that may wrap only at spaces (each token is unbreakable, hyphens included)."""
    return " ".join(f'<span class="nb">{esc(t)}</span>' for t in text.split(" "))


def _mono_quotes(text: str) -> str:
    """Escaped prose where "quoted" header values are monospace and unbreakable inside tokens."""
    parts = re.split(r'("[^"]*")', text)
    return "".join(f"<code>{_nowrap(p)}</code>" if p.startswith('"') else esc(p) for p in parts)


def _headers_card(cat: dict, items: list[Finding], anchors: dict[int, str]) -> str:
    ui = cat["ui"]
    rows = "".join(
        f'<tr id="{esc(anchors[id(f)])}"><td><code>{_nowrap(cat["headers"][f.id][0])}</code></td>'
        f'<td>{esc(cat["headers"][f.id][1])}</td><td>{_mono_quotes(cat["headers"][f.id][2])}</td></tr>'
        for f in items
    )
    top = min(items, key=sort_key)
    return (
        f'<div class="card"><h3>{_sev_tag(cat, top.severity)}{esc(ui["headers_card"])}</h3>'
        f'<table><tr><th>{esc(ui["col_header"])}</th><th>{esc(ui["col_does"])}</th><th>{esc(ui["col_enable"])}</th></tr>{rows}</table></div>'
    )


def _counts_phrase(ui: dict, issues: list[Finding]) -> str:
    n = Counter(f.severity for f in issues)
    crit = n["critical"]
    parts = [ui["crit_none"] if not crit else ui["crit_one"] if crit == 1 else ui["crit_many"].format(n=crit)]
    parts += [ui["sev_phrase"].format(n=n[s], sev=ui["sev_words"][s]) for s in ("high", "medium", "low") if n[s]]
    return parts[0] if len(parts) == 1 else f'{", ".join(parts[:-1])} {ui["and_word"]} {parts[-1]}'


def _summary(cat: dict, rep: ExposureReport, priorities: list[Finding]) -> str:
    ui = cat["ui"]
    score = "-" if rep.score is None else rep.score
    issues = [f for f in rep.findings if f.severity != "info"]
    if rep.not_run:
        first = ui["summary_not_graded"].format(not_run=", ".join(cat["category"][c] for c in rep.not_run))
        if not issues:
            return f'{first} {ui["summary_none"]}'
        return f'{first} {ui["summary_issues"].format(n=len(issues), counts=_counts_phrase(ui, issues))} {ui["summary_top"].format(title=_title(cat, priorities[0]))}'
    if rep.grade != INCOMPLETE and issues:
        counts = _counts_phrase(ui, issues)
        first = ui["summary_grade_counts"].format(grade=rep.grade, score=score, counts=counts)
        return f'{first} {ui["summary_top"].format(title=_title(cat, priorities[0]))}'
    if rep.grade == INCOMPLETE:
        missing = ", ".join(cat["category"][c] for c in rep.excluded_checks if c in REQUIRED_CHECKS)
        first = (
            ui["summary_grade_none"]
            if rep.score is None
            else ui["summary_grade_incomplete"].format(missing=missing, score=score)
        )
    else:
        first = ui["summary_grade"].format(grade=rep.grade, score=score)
    if not issues:
        return f'{first} {ui["summary_none"]}'
    counts = ", ".join(
        f"{cat['severity'][s]}: {n}"
        for s in ("critical", "high", "medium", "low")
        if (n := sum(1 for f in issues if f.severity == s))
    )
    key = "summary_issues_one" if len(issues) == 1 else "summary_issues"
    return f'{first} {ui[key].format(n=len(issues), counts=counts)} {ui["summary_top"].format(title=_title(cat, priorities[0]))}'


def _lookalike_summary(cat: dict, scan: LookalikeScan | None) -> str:
    """One sentence for the summary paragraph; empty without the flag or when the step failed."""
    if scan is None or scan.status != STATUS_OK:
        return ""
    ui = cat["ui"]
    t = ui["lk_summary"]
    n_unknown = scan.count("unknown")
    unknown = "" if not n_unknown else t["unknown_one"] if n_unknown == 1 else t["unknown_many"].format(n=n_unknown)
    registered = [r for r in scan.results if r.state == "registered"]
    mail = sum(1 for r in registered if r.has_mx)
    if not registered:
        key = "none"
    elif len(registered) == 1:
        key = "one_mail" if mail else "one_nomail"
    else:
        key = "many_nomail" if not mail else "many_one_mail" if mail == 1 else "many_mail"
    return t[key].format(checked=len(scan.results), n=len(registered), mail=mail, unknown=unknown, section=ui["lookalikes_title"])


def _reason_text(cat: dict, code: str | None) -> str:
    """Translated reason; raw English detail never reaches the report (it stays in --json)."""
    return cat["reasons"].get(code or "", cat["reasons"]["unexpected_error"])


def _check_status(cat: dict, check: CheckResult | None) -> str:
    if check is None or check.status == STATUS_OK:
        codes = check.note_codes if check else ()
        return "".join(f'<p class="small">{esc(_reason_text(cat, c))}</p>' for c in codes)
    ui = cat["ui"]
    label = ui["check_error"] if check.status == STATUS_ERROR else ui["check_skipped"]
    return f'<div class="status"><strong>{esc(label)}:</strong> {esc(_reason_text(cat, check.reason_code))} {esc(ui["excluded_note"])}</div>'


def _verified(cat: dict, check: CheckResult | None) -> str:
    """Compact list of what passed; unknown ids are skipped rather than shown raw."""
    if check is None or check.status != STATUS_OK:
        return ""
    lines = []
    for p in check.passed:
        template = cat["passed"].get(p.id)
        if template:
            try:
                lines.append(f"<li>{esc(_fill(cat, template, p.data))}</li>")
            except (KeyError, IndexError, ValueError):
                continue
    if not lines:
        return ""
    return f'<p class="vh">{esc(cat["ui"]["verified"])}</p><ul class="ok">{"".join(lines)}</ul>'


def _is_grouped_header(cat: dict, f: Finding) -> bool:
    return f.category == "http_headers" and f.severity in GROUPED_SEVERITIES and f.id in cat["headers"]


def _section(cat: dict, rep: ExposureReport, category: str, anchors: dict[int, str]) -> str:
    check = next((c for c in rep.checks if c.name == category), None)
    items = sorted((f for f in rep.findings if f.category == category and f.id not in HIDDEN_IDS), key=sort_key)
    grouped = [f for f in items if _is_grouped_header(cat, f)]
    cards = [f for f in items if f not in grouped and f.severity != "info"]
    infos = [f for f in items if f not in grouped and f.severity == "info"]
    body = "".join(_finding_card(cat, f, anchors[id(f)]) for f in cards)
    body += _headers_card(cat, grouped, anchors) if grouped else ""
    body += "".join(_info_item(cat, f, anchors[id(f)]) for f in infos)
    if not items and (check is None or check.status == STATUS_OK):
        body = f'<p class="small">{esc(cat["ui"]["no_findings"])}</p>'
    return f"<section><h2>{esc(cat['category'][category])}</h2>{_check_status(cat, check)}{body}{_verified(cat, check)}</section>"


def _lookalike_table(cat: dict, scan: LookalikeScan) -> str:
    """Registered lookalikes only, with email first. Names are defanged, escaped text: never links."""
    ui = cat["ui"]
    registered = sorted((r for r in scan.results if r.state == "registered"), key=lambda r: (not r.has_mx, r.domain))
    if not registered:
        return f'<p class="small">{esc(ui["lookalikes_none"])}</p>'
    yes_no = lambda flag: esc(ui["yes"] if flag else ui["no"])  # noqa: E731
    rows = "".join(
        f'<tr><td><code>{esc(defang(r.domain))}</code></td><td>{esc(ui["lookalike_types"].get(r.technique, r.technique))}</td>'
        f'<td>{yes_no(r.has_mx)}</td><td>{yes_no(r.has_a)}</td></tr>'
        for r in registered
    )
    return (
        f'<table class="lk"><thead><tr><th>{esc(ui["col_domain"])}</th><th>{esc(ui["col_variation"])}</th>'
        f'<th>{esc(ui["col_mail"])}</th><th>{esc(ui["col_web"])}</th></tr></thead><tbody>{rows}</tbody></table>'
        f'<p class="small">{esc(ui["lookalikes_defang_note"])}</p>'
    )


def _lookalikes_section(cat: dict, scan: LookalikeScan | None) -> str:
    if scan is None:
        return ""
    ui = cat["ui"]
    head = f'<h2>{esc(ui["lookalikes_title"])}</h2><p class="small">{esc(ui["lookalikes_not_scored"])}</p>'
    if scan.status != STATUS_OK:
        failed = f'<div class="status"><strong>{esc(ui["check_error"])}:</strong> {esc(_reason_text(cat, scan.reason_code))} {esc(ui["excluded_note"])}</div>'
        return f"<section>{head}{failed}</section>"
    unknown = scan.count("unknown")
    counts = " ".join([
        ui["lookalikes_checked"].format(checked=len(scan.results)),
        *([ui["lookalikes_unknown"].format(unknown=unknown)] if unknown else []),
        *([ui["lookalikes_skipped"].format(skipped=scan.skipped_over_cap)] if scan.skipped_over_cap else []),
    ])
    return (
        f'<section>{head}<p>{esc(ui["lookalikes_intro"])}</p><p>{esc(ui["lookalikes_todo"])}</p>'
        f'{_lookalike_table(cat, scan)}<p class="small">{esc(counts)}</p></section>'
    )


def _area_status(check: CheckResult | None, items: list[Finding]) -> str:
    if check is None or check.status != STATUS_OK:
        return "unverified"
    if any(f.severity == "critical" for f in items):
        return "critical"
    if any(f.severity == "high" for f in items):
        return "urgent"
    return "improve" if any(f.severity != "info" for f in items) else "ok"


def _area_table(cat: dict, rep: ExposureReport) -> str:
    ui = cat["ui"]
    severities = ("critical", "high", "medium", "low")
    head = "".join(f'<th class="n">{esc(cat["severity"][s])}</th>' for s in severities)
    rows = []
    for category in CATEGORY_ORDER:
        check = next((c for c in rep.checks if c.name == category), None)
        items = [f for f in rep.findings if f.category == category]
        status = _area_status(check, items)
        counts = "".join(
            f'<td class="n">{"-" if status == "unverified" else sum(1 for f in items if f.severity == s)}</td>'
            for s in severities
        )
        rows.append(
            f'<tr><td>{esc(cat["category"][category])}</td>'
            f'<td class="st-{status}">{STATUS_ICONS[status]} {esc(ui["status"][status])}</td>{counts}</tr>'
        )
    return (
        f'<table><tr><th>{esc(ui["col_area"])}</th><th>{esc(ui["col_status"])}</th>{head}</tr>{"".join(rows)}</table>'
    )


def _priority_list(cat: dict, priorities: list[Finding], anchors: dict[int, str]) -> str:
    if not priorities:
        return f'<p class="small">{esc(cat["ui"]["no_priorities"])}</p>'
    items = "".join(
        f'<li>{_sev_tag(cat, f.severity)}<a href="#{esc(anchors[id(f)])}">{esc(_title(cat, f))}</a> '
        f'<span class="act">{esc(cat["findings"][f.id]["action"])}</span></li>'
        for f in priorities
    )
    return f'<ol class="prio">{items}</ol>'


def render_html(rep: ExposureReport, lang: str = "en") -> str:
    cat = CATALOGS[lang]
    ui = cat["ui"]
    priorities = top_priorities(rep.findings)
    anchors = {id(f): f"f-{i}" for i, f in enumerate(rep.findings)}
    is_incomplete = rep.grade == INCOMPLETE or bool(rep.not_run)
    badge_text = ui["grade_not_graded"] if rep.not_run else ui["grade_incomplete"] if is_incomplete else (rep.grade or "-")
    badge_class = "g-incomplete" if is_incomplete else f"g-{rep.grade}"
    score_label = f"{ui['score_partial']} " if rep.grade == INCOMPLETE else ""
    score = "-" if rep.score is None else f"{rep.score}/100"
    meaning = "" if is_incomplete else ui["grade_meaning"].get(rep.grade or "", "")
    meaning_html = f'<div class="meaning">{esc(meaning)}</div>' if meaning else ""
    registrable_html = (
        ""
        if rep.registrable_domain == rep.domain
        else f" &middot; {esc(ui['registrable'])}: <strong>{esc(rep.registrable_domain)}</strong>"
    )
    sections = "".join(_section(cat, rep, c, anchors) for c in CATEGORY_ORDER)
    method_points = [*ui["method_points"], *([ui["method_lookalikes"]] if rep.lookalikes else [])]
    method = "".join(f"<li>{esc(p)}</li>" for p in method_points)
    glossary_items = [*ui["glossary_items"], *([ui["glossary_lookalike"]] if rep.lookalikes else [])]
    glossary = "".join(f'<tr><th scope="row">{esc(t)}</th><td>{esc(d)}</td></tr>' for t, d in glossary_items)
    summary = " ".join(filter(None, (_summary(cat, rep, priorities), _lookalike_summary(cat, rep.lookalikes))))
    return f"""<!doctype html>
<html lang="{esc(ui['html_lang'])}"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(ui['title'])} - {esc(rep.domain)}</title><style>{CSS}</style></head><body><main>
<header><h1>{esc(ui['title'])}</h1>
<p class="meta">{esc(ui['host'])}: <strong>{esc(rep.domain)}</strong>{registrable_html}</p>
<p class="meta">{esc(ui['checked'])}: {esc(format_checked_at(rep.checked_at, lang))}</p>
<div class="head"><div class="badge {esc(badge_class)}"><span class="g{' long' if is_incomplete else ''}">{esc(badge_text)}</span><span>{esc(ui['grade'])}</span></div>
<div><div class="score">{esc(score_label)}{esc(ui['score'])}: {esc(score)}</div>{meaning_html}<div class="small">{esc(ui['cap_note'])}</div></div></div></header>
<section><h2>{esc(ui['summary'])}</h2><p>{esc(summary)}</p></section>
<section><h2>{esc(ui['area_summary'])}</h2>{_area_table(cat, rep)}</section>
<section><h2>{esc(ui['priorities'])}</h2>{_priority_list(cat, priorities, anchors)}</section>
<h2>{esc(ui['details'])}</h2>{sections}
{_lookalikes_section(cat, rep.lookalikes)}
<section><h2>{esc(ui['method'])}</h2><ul>{method}</ul></section>
<section><h2>{esc(ui['glossary'])}</h2><table class="gl">{glossary}</table></section>
<footer>{esc(ui['footer'])} &middot; {esc(ui['version'])} {esc(__version__)} &middot; {esc(ui['report_version'])} {esc(REPORT_VERSION)}</footer>
</main></body></html>
"""
