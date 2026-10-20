"""Report layout polish: executive page, passed items, evidence templates, header table, info items."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from openosint.exposure.models import CheckResult, ExposureReport
from openosint.exposure.report import render_html
from openosint.exposure.report.catalog_en import CATALOG as EN
from openosint.exposure.report.catalog_it import CATALOG as IT
from openosint.exposure.report.render_html import esc
from openosint.exposure.scoring import SEVERITY_BY_ID, finding
from tests.exposure_helpers import GOOD_SPF, make_cert, rdap_body, report

LANGS = {"en": EN, "it": IT}
CATEGORY = {"spf_missing": "email", "tls_cert_invalid_chain": "tls", "hsts_missing": "http_headers", "csp_missing": "http_headers", "dmarc_policy_none": "email",
            "spf_softfail": "email", "dmarc_pct_below_100": "email", "dmarc_no_rua": "email",
            "dnssec_not_enabled": "registration", "x_content_type_options_missing": "http_headers",
            "frame_protection_missing": "http_headers", "tls_cert_expired": "tls"}
EXPOSURE_SRC = Path(__file__).parent.parent / "openosint" / "exposure"


def build(ids: list[str], grade="C", score=71) -> ExposureReport:
    findings = tuple(finding(i, CATEGORY[i], "t", f"raw {i}", "r") for i in ids)
    checks = tuple(CheckResult(n, "ok", "passive") for n in ("email", "tls", "registration", "http_headers"))
    return ExposureReport("example.com", "example.com", "2026-07-10T12:00:00+00:00", 5, checks, score, grade,
                          False, False, (), findings)


def section(out: str, heading: str) -> str:
    start = out.index(f"<h2>{heading}</h2>")
    return out[start : out.index("<h2>", start + 1)]


# --- 1. executive page ----------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "it"])
def test_grade_legend_and_cap_note(lang):
    ui = LANGS[lang]["ui"]
    assert set(ui["grade_meaning"]) == set("ABCDF")
    for grade, meaning in ui["grade_meaning"].items():
        out = render_html(build([], grade=grade, score=90), lang)
        assert f'<div class="meaning">{meaning}</div>' in out
        assert ui["cap_note"] in out
    assert list(IT["ui"]["grade_meaning"].values()) == ["Ottimo", "Buono", "Migliorabile", "Carente", "Critico"]


def test_italian_summary_sentence_example():
    ids = ["dmarc_policy_none", "spf_softfail", "dmarc_pct_below_100", "dmarc_no_rua", "dnssec_not_enabled",
           "hsts_missing", "csp_missing", "x_content_type_options_missing"]
    out = render_html(build(ids), "it")
    assert ("Il voto complessivo è C (71/100): nessun problema critico, 1 di gravità media e 7 di gravità bassa. "
            "La priorità principale è «Il DMARC è in sola osservazione».") in out


def test_english_summary_and_critical_wording():
    out = render_html(build(["tls_cert_expired", "hsts_missing"], grade="D", score=55), "en")
    assert "The overall grade is D (55/100): 1 critical issue and 1 of low severity." in out
    assert "The top priority is “" in out


def test_area_table_has_icon_and_text_for_each_status(world):
    world["bootstrap"] = {"net": ["https://rdap.example/"]}  # registration skipped -> not verified
    world["txt"].pop("_dmarc.example.com")  # email: high issue -> urgent
    table = section(render_html(report(), "it"), "Riepilogo per area")
    assert "\u25b2 Urgente" in table and "? Non verificato" in table and "✓ OK" in table
    crit = render_html(build(["tls_cert_expired"], grade="D"), "en")
    assert "✕ Critical" in section(crit, "Summary by area")


def test_priorities_are_compact_links_to_the_detail_cards():
    out = render_html(build(["dmarc_policy_none", "spf_softfail", "hsts_missing", "csp_missing"]), "it")
    prio = section(out, "Le 3 priorità")
    assert prio.count("<li>") == 3 and "Perché conta" not in prio and "<pre" not in prio
    hrefs = re.findall(r'href="#([^"]+)"', prio)
    assert len(hrefs) == 3
    for anchor in hrefs:
        assert f'id="{anchor}"' in out
    assert esc(IT["findings"]["dmarc_policy_none"]["action"]) in prio


@pytest.mark.parametrize("lang", ["en", "it"])
def test_every_non_info_finding_has_a_short_action(lang):
    for id_, text in LANGS[lang]["findings"].items():
        if SEVERITY_BY_ID[id_] != "info":
            assert text["action"].strip() and "{" not in text["action"], id_


# --- 2. passed items ------------------------------------------------------------------


def test_passed_lists_in_json_and_report(world):
    rep = report()
    data = rep.to_dict()["checks"]
    assert {p["id"] for p in data["email"]["passed"]} == {"mx_present", "spf_present", "dmarc_present", "dkim_found"}
    assert next(p for p in data["registration"]["passed"] if p["id"] == "domain_registered")["data"]["registrar"] == "Test Registrar"
    en, it = render_html(rep, "en"), render_html(rep, "it")
    for text in ("SPF present", "DMARC present (policy reject)", "certificate valid until", "Test Registrar",
                 "Strict-Transport-Security", "DNSSEC enabled", "Verified"):
        assert text in en, text
    for text in ("SPF presente", "DMARC presente (policy reject)", "certificato valido fino al", "Test Registrar",
                 "emesso da CN=Test CA", "Verificato"):
        assert text in it, text
    assert it.count("emesso da CN=Test CA") == 2  # apex and www, one line each


def test_headers_passed_lists_only_present_headers(world):
    world["headers"] = {"Strict-Transport-Security": "max-age=1"}
    passed = next(c for c in report().checks if c.name == "http_headers").passed
    assert dict(passed[0].data)["headers"] == "Strict-Transport-Security"


def test_nothing_passed_for_failed_aspects(world):
    world["txt"]["example.com"] = []
    world["rdap"] = rdap_body(days_to_expiry=20, signed=False)
    ids = {p.id for c in report().checks for p in c.passed}
    assert not ids & {"spf_present", "domain_registered", "dnssec_signed"}


def _source_ids(pattern: str) -> set[str]:
    return {m for f in EXPOSURE_SRC.glob("*_check.py") for m in re.findall(pattern, f.read_text())}


@pytest.mark.parametrize("lang", ["en", "it"])
def test_catalog_has_template_for_every_passed_and_evidence_id(lang):
    cat = LANGS[lang]
    assert _source_ids(r'Passed\("(\w+)"') <= set(cat["passed"])
    assert _source_ids(r'\bev\("(\w+)"') <= set(cat["evidence"])
    header_ids = {i for i in SEVERITY_BY_ID if CATEGORY.get(i) == "http_headers" or i == "referrer_policy_missing"}
    assert set(cat["headers"]) == header_ids


@pytest.mark.parametrize("section_name", ["passed", "evidence"])
def test_templates_use_same_placeholders_in_both_languages(section_name):
    field = re.compile(r"{(\w+)}")
    assert EN[section_name].keys() == IT[section_name].keys()
    for key in EN[section_name]:
        assert set(field.findall(EN[section_name][key])) == set(field.findall(IT[section_name][key])), key


# --- 3. evidence ---------------------------------------------------------------------


def test_evidence_has_no_python_repr_in_terminal_or_json(world):
    world["rdap"] = rdap_body(signed=False)
    rep = report()
    f = next(f for f in rep.findings if f.id == "dnssec_not_enabled")
    assert f.evidence == "DNSSEC: not signed"  # terminal and --json
    assert next(j for j in rep.to_dict()["findings"] if j["id"] == "dnssec_not_enabled")["evidence"] == f.evidence
    it, en = render_html(rep, "it"), render_html(rep, "en")
    assert "DNSSEC: non firmato" in it and "DNSSEC: not signed" in en
    assert "delegationSigned" not in it + en and "{'" not in it + en


def test_evidence_words_follow_the_report_language(world):
    world["txt"].pop("_dmarc.example.com")
    world["dkim"] = ([], False)
    world["headers"] = {}
    rep = report()
    bumped = tuple(dataclasses.replace(f, severity="medium") if f.id == "csp_missing" else f for f in rep.findings)
    rep = dataclasses.replace(rep, findings=bumped)  # a header card with evidence (the table has none)
    it, en = render_html(rep, "it"), render_html(rep, "en")
    for text in ("nessun record v=DMARC1 trovato in _dmarc.example.com", "nessuno dei selettori comuni ha risposto",
                 "intestazione assente nella risposta"):
        assert text in it, text
    for text in ("no v=DMARC1 record found at _dmarc.example.com", "none of the common selectors answered",
                 "header not present in response"):
        assert text in en, text


def test_found_at_template_and_raw_values_stay_verbatim_and_escaped(world):
    world["txt"]["_dmarc.example.com"] = ["v=DMARC1; p=none; rua=mailto:<b>x</b>@example.com"]
    rep = report()
    it = render_html(rep, "it")
    assert "v=DMARC1; p=none; rua=mailto:&lt;b&gt;x&lt;/b&gt;@example.com (trovato in _dmarc.example.com)" in it
    assert "<b>x" not in it
    assert "(found at _dmarc.example.com)" in next(f.evidence for f in rep.findings if f.id == "dmarc_policy_none")


def test_unknown_registrar_is_translated(world):
    world["rdap"]["entities"] = []
    it = render_html(report(), "it")
    assert "registrato presso non indicato" in it and "unknown" not in it


# --- 4. header table -----------------------------------------------------------------


def test_mild_header_findings_share_one_table_card(world):
    world["headers"] = {}
    out = render_html(report(), "en")
    assert out.count("Missing security headers") == 1
    card = out[out.index("Missing security headers") :]
    card = card[: card.index("</table>")]
    assert card.count("<tr id=") == 5 and "What it does" in card and "How to enable it" in card
    assert "Referrer-Policy" in card  # the info finding joins the table
    assert out.count('class="card"') == 1  # no per-header cards


def test_top3_links_into_header_table_rows_resolve(world):
    world["headers"] = {}
    out = render_html(report(), "en")
    hrefs = re.findall(r'href="#([^"]+)"', section(out, "Top 3 priorities"))
    assert len(hrefs) == 3
    for anchor in hrefs:
        assert f'<tr id="{anchor}">' in out, anchor


def test_medium_header_finding_gets_its_own_card(world):
    world["headers"] = {}
    rep = report()
    bumped = tuple(dataclasses.replace(f, severity="medium") if f.id == "csp_missing" else f for f in rep.findings)
    out = render_html(dataclasses.replace(rep, findings=bumped), "en")
    assert out.count('class="card"') == 2  # the csp card + the table card for the rest
    assert out.count("<tr id=") == 4  # csp left the table


def test_anchors_are_unique(world):
    world["tls"]["example.com"] = (make_cert(days_left=10), "TLSv1.3")
    world["tls"]["www.example.com"] = world["tls"]["example.com"]
    world["headers"] = {}
    ids = re.findall(r' id="(f-\d+)"', render_html(report(), "en"))
    assert len(ids) == len(set(ids)) >= 7


# --- 5. info findings ----------------------------------------------------------------


def test_info_findings_are_compact_without_why_label(world):
    world["dkim"] = ([], False)
    out = render_html(report(), "en")
    assert 'class="info"' in out and "Why it matters" not in out and 'class="card"' not in out


def test_domain_age_card_is_gone_from_report_but_kept_in_json(world):
    rep = report()
    assert any(f.id == "domain_age" for f in rep.findings)
    assert any(f["id"] == "domain_age" for f in rep.to_dict()["findings"])
    out = render_html(rep, "en")
    assert 'class="info"' not in out and "Domain registered 10.0 years" not in out


def test_info_finding_keeps_why_when_catalog_text_adds_value(world):
    world["mx"] = []
    world["txt"]["example.com"] = ["v=spf1 -all"]
    out = render_html(report(), "en")
    assert 'class="info"' in out and EN["findings"]["mx_missing"]["why_it_matters"][:40] in out


# --- polish: dates, registered-on line, header tokens, glossary, empty text ---------------------------


def test_italian_dates_are_dd_mm_yyyy_and_english_iso(world):
    rep = report()
    created = next(p for p in next(c for c in rep.checks if c.name == "registration").passed
                   if p.id == "domain_registered_on")
    iso = dict(created.data)["date"]
    y, m, d = iso.split("-")
    it, en = render_html(rep, "it"), render_html(rep, "en")
    assert f"Dominio registrato in data {d}/{m}/{y} (9 anni fa)" in it
    assert f"Domain registered on {iso} (9 years ago)" in en
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", it.split("<h2>Metodo")[0].replace(" (ora di Roma, ", " ("))
    assert re.search(r"valido fino al \d\d/\d\d/\d{4}", it) and re.search(r"valid until 20\d\d-\d\d-\d\d", en)


def test_italian_dates_in_evidence_too(world):
    world["tls"]["example.com"] = (make_cert(days_left=10), "TLSv1.3")
    it = render_html(report(), "it")
    assert re.search(r"scade in data \d\d/\d\d/\d{4} \(giorni rimanenti: \d+\)", it)


def test_registered_on_age_wording():
    from openosint.exposure.report.render_html import _age_text
    for lang, expected in (("en", ["1 month ago", "5 months ago", "23 months ago", "2 years ago", "9 years ago"]),
                           ("it", ["1 mese fa", "5 mesi fa", "23 mesi fa", "2 anni fa", "9 anni fa"])):
        assert [_age_text(LANGS[lang]["ui"], m) for m in (1, 5, 23, 24, 119)] == expected


def test_registrable_name_not_repeated_when_equal(world):
    out = render_html(report(), "en")
    assert "Registrable domain" not in out
    world["tls"]["app.example.com"] = (make_cert(hosts=("app.example.com",)), "TLSv1.3")
    world["txt"]["app.example.com"] = [GOOD_SPF]
    assert "Registrable domain: <strong>example.com</strong>" in render_html(report("app.example.com"), "en")


def test_header_table_is_monospace_and_wraps_only_at_spaces(world):
    world["headers"] = {}
    out = render_html(report(), "it")
    table = out[out.index("<table><tr><th>Intestazione"):]
    table = table[: table.index("</table>")]
    assert "<code>" in table
    for token in ("max-age=15552000", "strict-origin-when-cross-origin", "Strict-Transport-Security"):
        assert f'<span class="nb">{token}' in table or f'<span class="nb">&quot;{token}' in table, token
    assert ".nb{white-space:nowrap}" in out


def test_glossary_rows_are_table_rows_that_do_not_split(world):
    out = render_html(report(), "en")
    assert out.count('<th scope="row">') == 8 and "<dl" not in out
    assert "table.gl tr{break-inside:avoid}" in out


def test_empty_area_text(world):
    assert EN["ui"]["no_findings"] == "No issues found." and IT["ui"]["no_findings"] == "Nessun problema rilevato."
    out = render_html(report(), "it")
    assert out.count("Nessun problema rilevato.") == 4  # clean domain: every area, incl. registration (age card hidden)


def test_italian_dates_never_follow_il_or_a_bare_article():
    # "il 08/..." / "il 11/..." read badly; dates take "in data" or "fino al"
    for key in ("evidence", "passed"):
        for name, template in IT[key].items():
            assert not re.search(r"\bil \{(date|created)\}", template), name


@pytest.mark.parametrize("lang", ["en", "it"])
def test_glossary_defines_mx_and_lookalike_only_with_the_flag(world, lang):
    from tests.test_exposure_lookalikes import RESULTS, _scan_with, _with

    cat = LANGS[lang]["ui"]
    assert "MX" in dict(cat["glossary_items"]) and cat["glossary_lookalike"][0] not in render_html(report(), lang)
    with_flag = render_html(_with(report(), _scan_with(*RESULTS)), lang)
    assert f'<th scope="row">{cat["glossary_lookalike"][0]}</th>' in with_flag and with_flag.count('<th scope="row">') == 9
