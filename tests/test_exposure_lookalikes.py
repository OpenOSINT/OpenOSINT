"""Lookalike step tests. No network: DNS is replaced by a fake `_query`."""

from __future__ import annotations

import asyncio
import re
import time

import dns.resolver
import pytest

from openosint.exposure import lookalikes_check as lc
from openosint.exposure import runner
from openosint.exposure.lookalikes_gen import MAX_CANDIDATES, TECHNIQUE_PRIORITY, generate
from openosint.exposure.models import STATUS_ERROR, ExposureReport, Lookalike, LookalikeScan
from openosint.exposure.render import render
from openosint.exposure.report import render_html
from openosint.exposure.report.catalog_en import CATALOG as EN
from openosint.exposure.report.catalog_it import CATALOG as IT
from tests.exposure_helpers import report

NXDOMAIN = dns.resolver.NXDOMAIN()
SERVFAIL = dns.resolver.NoNameservers()
LANGS = {"en": EN, "it": IT}


def fake_dns(monkeypatch, table: dict, default=NXDOMAIN, log: list | None = None):
    """table: (name, rtype) -> list of answers | exception. Missing names use `default` for every type."""

    def query(name, rtype, dns_config=None):
        if log is not None:
            log.append((name, rtype))
        out = table.get((name, rtype), table.get((name, "*"), default))
        if isinstance(out, BaseException):
            raise out
        return out

    monkeypatch.setattr(lc, "_query", query)


# --- generator -----------------------------------------------------------------


def test_generator_is_deterministic_and_deduplicated():
    first, skipped = generate("openosint.tech")
    again, _ = generate("openosint.tech")
    domains = [c.domain for c in first]
    assert first == again and skipped == 0
    assert len(domains) == len(set(domains))
    assert "openosint.tech" not in domains


def test_generator_covers_every_v1_technique():
    cands = {c.domain: c.technique for c in generate("openosint.tech")[0]}
    assert cands["openosint.com"] == "tld_swap"
    assert cands["0penosint.tech"] == "homoglyph"
    assert cands["openosnit.tech"] == "swap"
    assert cands["openoosint.tech"] == "repetition"
    assert cands["openosint-billing.com"] == "combo"
    assert cands["open-osint.tech"] == "hyphenation"
    assert cands["opwnosint.tech"] == "keyboard"
    assert set(cands.values()) == set(TECHNIQUE_PRIORITY)


def test_idn_homoglyphs_are_punycode_ascii_only():
    idn = [c.domain for c in generate("openosint.tech")[0] if c.technique == "homoglyph_idn"]
    assert idn and all(d.startswith("xn--") and d.isascii() for d in idn)


def test_candidates_are_valid_ascii_labels():
    for c in generate("openosint.tech")[0]:
        label = c.domain.split(".")[0]
        assert c.domain.isascii() and re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", label), c.domain


def test_cap_keeps_the_highest_priority_and_counts_the_rest():
    everything, _ = generate("internationalization.com", 10**6)
    kept, skipped = generate("internationalization.com")
    assert len(kept) == MAX_CANDIDATES and skipped == len(everything) - MAX_CANDIDATES > 0
    assert kept == everything[:MAX_CANDIDATES]
    ranks = [TECHNIQUE_PRIORITY.index(c.technique) for c in kept]
    assert ranks == sorted(ranks)
    assert kept[0].technique == "tld_swap"
    assert everything[-1].technique == "insertion"


# --- detection -----------------------------------------------------------------


def test_nxdomain_stops_after_the_first_query(monkeypatch):
    log: list = []
    fake_dns(monkeypatch, {}, log=log)
    assert lc.probe("nope.com") == ("not_registered", False, False)
    assert log == [("nope.com", "NS")]


@pytest.mark.parametrize("error", [SERVFAIL, dns.resolver.LifetimeTimeout()])
def test_servfail_and_timeout_are_unknown_never_registered(monkeypatch, error):
    fake_dns(monkeypatch, {("x.com", "*"): error})
    assert lc.probe("x.com")[0] == "unknown"


def test_later_error_without_any_answer_is_unknown(monkeypatch):
    fake_dns(monkeypatch, {("x.com", "NS"): [], ("x.com", "A"): SERVFAIL, ("x.com", "AAAA"): [], ("x.com", "MX"): []})
    assert lc.probe("x.com")[0] == "unknown"


def test_noerror_without_data_is_unknown_only_nxdomain_is_not_registered(monkeypatch):
    fake_dns(monkeypatch, {("x.com", "*"): []})
    assert lc.probe("x.com") == ("unknown", False, False)


def test_answers_set_registered_mx_and_a_flags(monkeypatch):
    fake_dns(monkeypatch, {("a.com", "NS"): ["ns1."], ("a.com", "A"): ["1.2.3.4"], ("a.com", "AAAA"): [], ("a.com", "MX"): []})
    assert lc.probe("a.com") == ("registered", False, True)
    fake_dns(monkeypatch, {("m.com", "NS"): [], ("m.com", "A"): [], ("m.com", "AAAA"): [], ("m.com", "MX"): ["10 mail.m.com."]})
    assert lc.probe("m.com") == ("registered", True, False)


def test_null_mx_means_no_mail(monkeypatch):
    fake_dns(monkeypatch, {("n.com", "NS"): ["ns1."], ("n.com", "A"): [], ("n.com", "AAAA"): [], ("n.com", "MX"): ["0 ."]})
    assert lc.probe("n.com") == ("registered", False, False)


# --- scan ----------------------------------------------------------------------


def test_wildcard_tld_candidates_are_unknown_and_not_queried(monkeypatch):
    log: list = []

    def query(name, rtype, dns_config=None):
        log.append(name)
        if name.endswith(".biz"):
            return ["1.2.3.4"]  # biz answers for everything
        raise NXDOMAIN

    monkeypatch.setattr(lc, "_query", query)
    result = lc.scan("example.com")
    biz = [r for r in result.results if r.domain.endswith(".biz")]
    assert biz and all(r.state == "unknown" and r.unknown_reason == "wildcard_tld" for r in biz)
    assert not [n for n in log if n.endswith(".biz") and not n.startswith("wc")]
    assert result.count("registered") == 0


def test_scan_finds_registered_lookalikes_and_builds_findings(monkeypatch):
    table = {
        ("examp1e.com", "NS"): ["ns."], ("examp1e.com", "A"): ["1.2.3.4"], ("examp1e.com", "AAAA"): [], ("examp1e.com", "MX"): [],
        ("exmaple.com", "MX"): ["10 mx.exmaple.com."],
        ("exmaple.com", "NS"): ["ns."],
        ("exmaple.com", "A"): [], ("exmaple.com", "AAAA"): [],
    }
    fake_dns(monkeypatch, table)
    result = lc.scan("example.com")
    by_domain = {r.domain: r for r in result.results}
    assert by_domain["exmaple.com"].has_mx and not by_domain["exmaple.com"].has_a
    assert by_domain["examp1e.com"].has_a and by_domain["examp1e.com"].state == "registered"
    ids = {f.id: f for f in result.findings}
    assert set(ids) == {"lookalike_with_mx", "lookalike_registered"}
    assert "exmaple[.]com" in ids["lookalike_with_mx"].evidence and "exmaple.com" not in ids["lookalike_with_mx"].evidence


def test_none_found_finding(monkeypatch):
    fake_dns(monkeypatch, {})
    result = lc.scan("example.com")
    assert [f.id for f in result.findings] == ["lookalikes_none_found"]


def test_evidence_list_is_capped_at_20_but_json_has_everything(monkeypatch):
    def query(name, rtype, dns_config=None):
        if name.startswith("wc"):  # the wildcard probe: nothing answers for a random label
            raise NXDOMAIN
        return ["1.2.3.4"] if rtype == "A" else []

    monkeypatch.setattr(lc, "_query", query)
    result = lc.scan("example.com")
    registered = result.count("registered")
    assert registered > lc.EVIDENCE_CAP
    ev = result.findings[0].evidence
    assert ev.count("[.]") == lc.EVIDENCE_CAP and f"+{registered - lc.EVIDENCE_CAP} more" in ev
    assert len(result.to_dict()["candidates"]) == registered


def test_deadline_marks_unfinished_unknown_separately_from_cap(monkeypatch):
    monkeypatch.setattr(lc, "_query", lambda name, rtype, dns_config=None: time.sleep(0.6) or [])
    started = time.monotonic()
    result = lc.scan("internationalization.com", limit=20, deadline=0.2)
    assert time.monotonic() - started < 0.55
    assert result.skipped_over_cap > 0
    assert result.count("unknown", "deadline") == 20 and result.count("registered") == 0
    counts = result.to_dict()["counts"]
    assert counts["unknown_deadline"] == 20 and result.to_dict()["skipped_over_cap"] == result.skipped_over_cap


def test_timeouts_and_pending_candidates_are_unknown_never_not_registered(monkeypatch):
    """Every candidate lookup times out: nothing may be reported as not registered or registered."""
    fake_dns(monkeypatch, {}, default=dns.resolver.LifetimeTimeout())
    result = lc.scan("example.com")
    assert result.results and {r.state for r in result.results} == {"unknown"}
    assert result.count("not_registered") == 0 and result.count("registered") == 0


def test_pending_at_the_deadline_is_unknown_never_not_registered(monkeypatch):
    monkeypatch.setattr(lc, "_query", lambda name, rtype, dns_config=None: time.sleep(0.5) or (_ for _ in ()).throw(NXDOMAIN))
    result = lc.scan("internationalization.com", limit=20, deadline=0.2)
    assert result.count("not_registered") == 0 and result.count("unknown", "deadline") == 20


def test_unknown_candidates_are_retried_once_and_resolved(monkeypatch):
    calls: dict[str, int] = {}

    def query(name, rtype, dns_config=None):
        if name.startswith("wc"):
            raise NXDOMAIN
        calls[name] = calls.get(name, 0) + 1
        if name == "exmaple.com":
            if calls[name] == 1:
                raise dns.resolver.LifetimeTimeout()  # first pass: the router chokes
            return ["ns."] if rtype == "NS" else (["1.2.3.4"] if rtype == "A" else [])
        raise NXDOMAIN

    monkeypatch.setattr(lc, "_query", query)
    result = lc.scan("example.com")
    by_domain = {r.domain: r for r in result.results}
    assert by_domain["exmaple.com"].state == "registered" and result.count("unknown") == 0


def test_unknown_after_the_retry_stays_unknown(monkeypatch):
    fake_dns(monkeypatch, {("exmaple.com", "*"): SERVFAIL})
    result = lc.scan("example.com")
    assert {r.domain: r.state for r in result.results}["exmaple.com"] == "unknown"


def test_pool_is_bounded_to_8_workers():
    assert lc.MAX_WORKERS == 8 and lc.QUERY_TIMEOUT == 2.0 and lc.DEADLINE == 25.0 and MAX_CANDIDATES == 300


# --- score exclusion and JSON ----------------------------------------------------


def _scan_with(*results: Lookalike) -> LookalikeScan:
    return LookalikeScan("ok", len(results), 0, results, lc.build_findings(results))


def test_grade_and_score_are_identical_with_and_without_lookalikes(world, monkeypatch):
    bad = _scan_with(Lookalike("examp1e.com", "homoglyph", "registered", True, True))
    monkeypatch.setattr(runner.lookalikes_check, "scan", lambda registrable, dns_config=None: bad)
    plain = report()
    with_scan = asyncio.run(runner.run_exposure("example.com", lookalikes=True))
    assert (plain.score, plain.grade, plain.excluded_checks) == (with_scan.score, with_scan.grade, with_scan.excluded_checks)
    assert plain.findings == with_scan.findings
    assert with_scan.lookalikes is bad and plain.lookalikes is None


def test_json_is_additive_and_null_when_off(world, monkeypatch):
    plain = report().to_dict()
    assert plain["lookalikes"] is None
    monkeypatch.setattr(runner.lookalikes_check, "scan", lambda registrable, dns_config=None: _scan_with())
    on = asyncio.run(runner.run_exposure("example.com", lookalikes=True)).to_dict()
    assert on.keys() == plain.keys() and {k: v for k, v in on.items() if k != "lookalikes"} == {
        k: v for k, v in plain.items() if k not in ("lookalikes", "checked_at", "duration_ms")
    } | {k: on[k] for k in ("checked_at", "duration_ms")}
    assert on["lookalikes"]["scoring"] == "excluded" and on["lookalikes"]["dns_only"] is True
    assert set(on["lookalikes"]) >= {"generated", "checked", "skipped_over_cap", "counts", "candidates", "findings"}


def test_scan_failure_becomes_error_status_not_a_crash(world, monkeypatch):
    def boom(registrable):
        raise RuntimeError("x")

    monkeypatch.setattr(runner.lookalikes_check, "scan", boom)
    rep = asyncio.run(runner.run_exposure("example.com", lookalikes=True))
    assert rep.lookalikes.status == STATUS_ERROR and rep.lookalikes.reason_code == "unexpected_error"
    assert rep.grade == report().grade


def test_cli_passes_the_flag(monkeypatch, capsys):
    import openosint.exposure
    from openosint import cli

    seen = {}

    async def fake_run(domain, lookalikes=False, resolver=None):
        seen["flag"] = lookalikes
        raise ValueError("stop")

    monkeypatch.setattr(openosint.exposure, "run_exposure", fake_run)
    with pytest.raises(SystemExit):
        asyncio.run(cli._handle_exposure("example.com", lookalikes=True))
    assert seen["flag"] is True


def test_terminal_output_says_lookalikes_are_not_scored(world):
    scan = _scan_with(Lookalike("examp1e.com", "homoglyph", "registered", True, True))
    out = render(_with(report(), scan))
    assert "NOT part of the score or grade" in out and "examp1e[.]com" in out and "examp1e.com" not in out


# --- HTML report -----------------------------------------------------------------


def _with(rep: ExposureReport, scan: LookalikeScan | None) -> ExposureReport:
    from dataclasses import replace

    return replace(rep, lookalikes=scan)


EVIL = '"><script>alert(1)</script>.com'
RESULTS = (
    Lookalike("zz-nomail.com", "combo", "registered", False, True),
    Lookalike("aa-mail.com", "homoglyph", "registered", True, False),
    Lookalike("xn--opensint-qbh.tech", "homoglyph_idn", "registered", True, True),
    Lookalike(EVIL, "swap", "registered", False, False),
    Lookalike("unk-wild.biz", "tld_swap", "unknown", unknown_reason="wildcard_tld"),
    Lookalike("gone.com", "swap", "not_registered"),
)


@pytest.mark.parametrize("lang", ["en", "it"])
def test_report_section_escaping_defang_and_no_links(world, lang):
    base = report()
    html = render_html(_with(base, _scan_with(*RESULTS)), lang)
    plain = render_html(base, lang)
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;[.]com" in html
    assert html.count("<a ") == plain.count("<a ")  # no link added for any lookalike
    assert all(r.domain not in html for r in RESULTS)  # raw (clickable-looking) names never appear
    assert "aa-mail[.]com" in html and "xn--opensint-qbh[.]tech" in html


@pytest.mark.parametrize("lang", ["en", "it"])
def test_report_lists_only_registered_mx_first_then_by_domain(world, lang):
    html = render_html(_with(report(), _scan_with(*RESULTS)), lang)
    order = [html.index(d) for d in ("aa-mail[.]com", "xn--opensint-qbh[.]tech", "zz-nomail[.]com")]
    assert order == sorted(order) and html.index("&lt;script&gt;") > order[1]  # MX rows first: aa, xn--, then non-MX sorted
    assert "unk-wild" not in html and "gone[.]com" not in html
    ui = LANGS[lang]["ui"]
    assert ui["lookalike_types"]["homoglyph_idn"] in html and "омен" not in html
    assert ui["lookalikes_checked"].format(checked=6) in html and ui["lookalikes_unknown"].format(unknown=1) in html
    assert "<thead>" in html and ui["lookalikes_defang_note"] in html
    assert ui["lookalikes_not_scored"] in html and ui["method_lookalikes"] in html


@pytest.mark.parametrize("lang", ["en", "it"])
def test_report_without_flag_has_no_lookalike_section(world, lang):
    html = render_html(report(), lang)
    assert LANGS[lang]["ui"]["lookalikes_title"] not in html and LANGS[lang]["ui"]["method_lookalikes"] not in html


@pytest.mark.parametrize("lang", ["en", "it"])
def test_report_none_found_and_error_states(world, lang):
    ui = LANGS[lang]["ui"]
    none = render_html(_with(report(), _scan_with(Lookalike("gone.com", "swap", "not_registered"))), lang)
    assert ui["lookalikes_none"] in none and "<th>" + ui["col_domain"] not in none
    failed = render_html(_with(report(), LookalikeScan(STATUS_ERROR, 0, 0, reason_code="timeout")), lang)
    assert LANGS[lang]["reasons"]["timeout"] in failed


@pytest.mark.parametrize("lang", ["en", "it"])
def test_catalog_covers_lookalike_ids_and_types(lang):
    cat = LANGS[lang]
    for id_ in ("lookalike_with_mx", "lookalike_registered", "lookalikes_none_found"):
        assert all(cat["findings"][id_].get(k, "").strip() for k in ("title", "why_it_matters", "how_to_fix"))
    assert set(cat["ui"]["lookalike_types"]) == set(TECHNIQUE_PRIORITY)
    assert cat["category"]["lookalikes"]


# --- report polish: summary sentence, counts line, table ------------------------------------------------------------


def _summary_text(lang: str, *results: Lookalike, skipped: int = 0) -> str:
    scan = LookalikeScan("ok", len(results) + skipped, skipped, results, lc.build_findings(results))
    html = render_html(_with(report(), scan), lang)
    return html.split("<h2>" + LANGS[lang]["ui"]["summary"] + "</h2><p>")[1].split("</p>")[0]


def _lk(domain, mx=False, state="registered"):
    return Lookalike(domain, "swap", state, mx, True)


def test_italian_summary_sentence_plural_singular_and_none(world):
    two_of_three = _summary_text("it", _lk("a.com", True), _lk("b.com", True), _lk("c.com"))
    assert "Abbiamo inoltre trovato 3 domini simili al vostro, 2 dei quali possono ricevere email: non incidono sul voto" in two_of_three
    assert "vedete la sezione «Domini simili al vostro»." in two_of_three
    assert "1 dei quali può ricevere email" in _summary_text("it", _lk("a.com", True), _lk("b.com"))
    assert "nessuno dei quali risulta poter ricevere email" in _summary_text("it", _lk("a.com"), _lk("b.com"))
    assert "1 dominio simile al vostro, che può ricevere email: non incide sul voto" in _summary_text("it", _lk("a.com", True))
    assert "1 dominio simile al vostro, che non risulta poter ricevere email:" in _summary_text("it", _lk("a.com"))
    assert "Tra le 2 varianti controllate non abbiamo trovato domini simili registrati." in _summary_text(
        "it", _lk("a.com", state="not_registered"), _lk("b.com", state="not_registered"))


def test_english_summary_sentence_plural_singular_and_none(world):
    assert "We also found 3 domains similar to yours, 2 of which can receive email: they do not affect the grade" in _summary_text(
        "en", _lk("a.com", True), _lk("b.com", True), _lk("c.com"))
    assert "1 of which can receive email" in _summary_text("en", _lk("a.com", True), _lk("b.com"))
    assert "none of which appear able to receive email" in _summary_text("en", _lk("a.com"), _lk("b.com"))
    assert "1 domain similar to yours, which can receive email: it does not affect" in _summary_text("en", _lk("a.com", True))
    assert "Among the 1 variants checked we found no registered lookalike domains." in _summary_text(
        "en", _lk("a.com", state="not_registered"))


@pytest.mark.parametrize("lang", ["en", "it"])
def test_summary_sentence_says_when_some_variants_are_unverifiable(world, lang):
    unk = [Lookalike(f"u{i}.com", "swap", "unknown", unknown_reason="dns_error") for i in range(12)]
    ui = LANGS[lang]["ui"]["lk_summary"]
    assert ui["unknown_many"].format(n=12) in _summary_text(lang, _lk("a.com", True), *unk)
    assert ui["unknown_many"].format(n=12) in _summary_text(lang, *unk)  # nothing found, still not "complete"
    assert ui["unknown_one"] in _summary_text(lang, _lk("a.com"), unk[0])
    assert "(" not in _summary_text(lang, _lk("a.com")).split("a.com")[-1].split(":")[0]  # none unknown: no parenthesis


@pytest.mark.parametrize("lang", ["en", "it"])
def test_summary_is_unchanged_without_the_flag_or_on_error(world, lang):
    plain = render_html(report(), lang)
    assert LANGS[lang]["ui"]["lookalikes_title"] not in plain
    failed = render_html(_with(report(), LookalikeScan(STATUS_ERROR, 0, 0, reason_code="timeout")), lang)
    marker = "<h2>" + LANGS[lang]["ui"]["summary"] + "</h2><p>"
    assert failed.split(marker)[1].split("</p>")[0] == plain.split(marker)[1].split("</p>")[0]


@pytest.mark.parametrize("lang", ["en", "it"])
def test_counts_line_always_shows_checked_and_the_rest_only_when_positive(world, lang):
    ui = LANGS[lang]["ui"]
    clean = render_html(_with(report(), _scan_with(_lk("a.com"), _lk("b.com", state="not_registered"))), lang)
    assert ui["lookalikes_checked"].format(checked=2) in clean
    assert ui["lookalikes_unknown"].split("{")[0] not in clean and ui["lookalikes_skipped"].split("{")[0] not in clean
    scan = LookalikeScan("ok", 5, 3, (_lk("a.com"), Lookalike("u.com", "swap", "unknown", unknown_reason="deadline")), ())
    full = render_html(_with(report(), scan), lang)
    assert ui["lookalikes_unknown"].format(unknown=1) in full and ui["lookalikes_skipped"].format(skipped=3) in full


@pytest.mark.parametrize("lang", ["en", "it"])
def test_table_header_yes_no_defang_note_and_print_rules(world, lang):
    ui = LANGS[lang]["ui"]
    html = render_html(_with(report(), _scan_with(_lk("a.com", True), _lk("b.com"))), lang)
    assert f'<th>{ui["col_domain"]}</th>' in html and ui["col_domain"] in ("Domain", "Dominio")
    assert "<td>" + ui["yes"] + "</td>" in html and "<td>" + ui["no"] + "</td>" in html
    assert (ui["yes"], ui["no"]) in (("Yes", "No"), ("Sì", "No"))
    assert html.count(ui["lookalikes_defang_note"]) == 1 and html.index("</table>") < html.index(ui["lookalikes_defang_note"])
    assert "table.lk tr{break-inside:avoid}" in html and "table.lk thead{display:table-header-group}" in html


def test_variation_label_uses_estensione_in_italian():
    assert IT["ui"]["lookalike_types"]["tld_swap"] == "stesso nome, estensione diversa"
    assert "terminazion" not in " ".join(IT["ui"]["lookalike_types"].values())
