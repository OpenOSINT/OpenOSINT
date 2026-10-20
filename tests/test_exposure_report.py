"""HTML report tests: catalogs, escaping, priorities, rendering. No network."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest

from openosint.exposure.models import (
    REASON_CODES,
    CheckError,
    CheckResult,
    CheckSkipped,
    ExposureReport,
)
from openosint.exposure.report import render_html
from openosint.exposure.report.catalog_en import CATALOG as EN
from openosint.exposure.report.catalog_it import CATALOG as IT
from openosint.exposure.report.priorities import top_priorities
from openosint.exposure.report.render_html import DYNAMIC_TITLE_IDS, esc, format_checked_at
from openosint.exposure.scoring import SEVERITY_BY_ID, finding
from tests.exposure_helpers import make_cert, rdap_body, report

LANGS = {"en": EN, "it": IT}


def make(id_: str, category: str, days: int | None = None):
    return finding(id_, category, "t", f"evidence {id_}", "r", days)


# --- translations ------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "it"])
def test_every_finding_id_has_complete_translation(lang):
    findings = LANGS[lang]["findings"]
    assert set(findings) == set(SEVERITY_BY_ID), "catalog ids must match the severity table exactly"
    for id_, text in findings.items():
        for key in ("title", "why_it_matters", "how_to_fix"):
            assert text.get(key, "").strip(), f"{lang}:{id_} is missing {key}"


@pytest.mark.parametrize("lang", ["en", "it"])
def test_only_expiry_titles_have_the_days_placeholder(lang):
    for id_, text in LANGS[lang]["findings"].items():
        assert ("{days}" in text["title"]) == (id_ in DYNAMIC_TITLE_IDS), id_
        assert "{" not in text["why_it_matters"] + text["how_to_fix"], id_


def test_both_catalogs_have_the_same_ui_keys_and_labels():
    assert EN["ui"].keys() == IT["ui"].keys()
    assert EN["severity"].keys() == IT["severity"].keys() == {"critical", "high", "medium", "low", "info"}
    assert list(IT["severity"].values()) == ["Critico", "Alto", "Medio", "Basso", "Informativo"]
    assert EN["category"].keys() == IT["category"].keys()
    assert len(EN["ui"]["glossary_items"]) == len(IT["ui"]["glossary_items"]) == 8
    assert len(EN["ui"]["method_points"]) == len(IT["ui"]["method_points"])


def test_italian_uses_voi_not_tu():
    text = " ".join(t for f in IT["findings"].values() for t in f.values())
    for tu_form in (" tuo ", " tua ", " tuoi ", " tue ", "Controlla ", "Rinnova "):
        assert tu_form not in text, tu_form


@pytest.mark.parametrize("lang", ["en", "it"])
def test_every_reason_code_has_translation(lang):
    reasons = LANGS[lang]["reasons"]
    assert set(reasons) == set(REASON_CODES)
    assert all(text.strip() for text in reasons.values())


def test_evidence_label_is_technical_detail():
    assert EN["ui"]["evidence"] == "Technical detail" and IT["ui"]["evidence"] == "Dettaglio tecnico"


def test_reason_codes_are_validated_and_classified():
    import dns.exception
    import requests

    from openosint.exposure.runner import classify
    from openosint.tools.exceptions import OSINTError

    with pytest.raises(ValueError):
        CheckError("x", "not_a_code")
    assert classify(CheckSkipped("x", "no_rdap_for_tld")) == "no_rdap_for_tld"
    assert classify(CheckError("x")) == "check_failed"
    cases = {
        "timeout": [TimeoutError(), dns.exception.Timeout(), requests.Timeout()],
        "name_not_resolved": [socket.gaierror("x")],
        "unreachable": [ConnectionError("x"), requests.ConnectionError()],
        "dns_error": [dns.resolver.NoNameservers()],
        "rdap_error": [OSINTError("x")],
        "unexpected_error": [RuntimeError("x")],
    }
    for code, excs in cases.items():
        assert code in REASON_CODES
        assert all(classify(e) == code for e in excs), code


def test_failures_in_checks_carry_reason_codes(world):
    world["tls"]["example.com"] = socket.gaierror("no host")
    world["bootstrap"] = {"net": ["https://rdap.example/"]}
    rep = report()
    codes = {c.name: c.reason_code for c in rep.checks}
    assert codes["tls"] == "name_not_resolved" and codes["registration"] == "no_rdap_for_tld"
    assert rep.to_dict()["checks"]["tls"]["reason_code"] == "name_not_resolved"


def test_missing_www_note_has_reason_code(world):
    world["tls"]["www.example.com"] = socket.gaierror("no host")
    tls = next(c for c in report().checks if c.name == "tls")
    assert tls.note_codes == ("www_not_in_dns",)


# --- escaping ----------------------------------------------------------------

PAYLOAD = "<script>alert(1)</script>\"'><img src=x onerror=alert(1)>"


def test_attacker_controlled_values_are_escaped(world):
    world["txt"]["example.com"] = [f"v=spf1 +all {PAYLOAD}"]
    world["rdap"] = rdap_body()
    world["rdap"]["entities"][0]["vcardArray"][1][0][3] = PAYLOAD  # registrar name
    rep = report()
    for lang in ("en", "it"):
        out = render_html(rep, lang)
        assert "<script" not in out and "<img" not in out
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
        assert "&quot;&#x27;&gt;&lt;img" in out
        assert 'onerror=alert(1)>' not in out.replace("&gt;", "")  # no live tag survives


def test_raw_reason_and_notes_never_reach_the_report():
    failed = CheckResult("tls", "error", "touches target", reason=PAYLOAD, reason_code="timeout")
    noted = CheckResult("email", "ok", "passive", notes=(PAYLOAD,), note_codes=("www_not_in_dns",))
    rep = ExposureReport("example.com", "example.com", "2026-07-10T12:00:00+00:00", 5, (noted, failed), None,
                         "incomplete", True, False, ("tls",), ())
    for lang, catalog in LANGS.items():
        out = render_html(rep, lang)
        assert "script" not in out and "alert(1)" not in out
        assert esc(catalog["reasons"]["timeout"]) in out and esc(catalog["reasons"]["www_not_in_dns"]) in out


def test_unknown_reason_code_falls_back_to_generic_text_not_raw_detail():
    check = CheckResult("tls", "error", "touches target", reason="raw english", reason_code="made_up")
    rep = ExposureReport("example.com", "example.com", "2026-07-10T12:00:00+00:00", 5, (check,), None,
                         "incomplete", True, False, ("tls",), ())
    out = render_html(rep, "it")
    assert "raw english" not in out and esc(IT["reasons"]["unexpected_error"]) in out


def test_esc_helper_escapes_quotes():
    assert esc('"a"&<b>\'') == "&quot;a&quot;&amp;&lt;b&gt;&#x27;"


# --- priorities ---------------------------------------------------------------


def test_top3_orders_by_severity_then_multiplier_then_id():
    findings = (
        make("hsts_missing", "http_headers"),       # low, x0.5
        make("spf_softfail", "email"),              # low, x1.0
        make("dnssec_not_enabled", "registration"), # low, x0.75
        make("spf_missing", "email"),               # high
        make("csp_missing", "http_headers"),        # low, x0.5 (ties hsts: id order)
        make("tls_cert_expired", "tls"),            # critical
    )
    ids = [f.id for f in top_priorities(findings)]
    assert ids == ["tls_cert_expired", "spf_missing", "spf_softfail"]
    ids5 = [f.id for f in top_priorities(findings, 6)]
    assert ids5[2:] == ["spf_softfail", "dnssec_not_enabled", "csp_missing", "hsts_missing"]


def test_top3_tie_on_severity_and_category_uses_id_order():
    findings = (make("spf_neutral", "email"), make("dmarc_policy_none", "email"))  # both medium, x1.0
    assert [f.id for f in top_priorities(findings)] == ["dmarc_policy_none", "spf_neutral"]


def test_top3_shows_fewer_when_fewer_qualify_and_never_info():
    findings = (make("domain_age", "registration"), make("mx_missing", "email"), make("hsts_missing", "http_headers"))
    assert [f.id for f in top_priorities(findings)] == ["hsts_missing"]
    assert top_priorities((make("domain_age", "registration"),)) == []


# --- rendering ------------------------------------------------------------------


def test_report_is_self_contained(world):
    world["headers"] = {}
    out = render_html(report(), "en")
    assert out.startswith("<!doctype html>")
    for forbidden in ("<script", "http://", "https://", " src=", "@import", "url(", "<link", "<iframe"):
        assert forbidden not in out, forbidden
    assert "@page" in out and "break-inside:avoid" in out
    assert "break-before" not in out and "page-break-before" not in out  # no forced page break per category


def test_sections_in_required_order(world):
    out = render_html(report(), "en")
    marks = ["<h2>Summary</h2>", "<h2>Summary by area</h2>", "<h2>Top 3 priorities</h2>", "<h2>Email security</h2>",
             "<h2>Website security certificate (TLS)</h2>", "<h2>Domain registration</h2>", "<h2>Website security headers</h2>",
             "Method and limits", "Glossary", "Generated by OpenOSINT"]
    positions = [out.index(m) for m in marks]
    assert positions == sorted(positions)
    assert "report_version 1" in out and "example.com" in out


def test_perfect_domain_report(world):
    out = render_html(report(), "en")
    assert 'class="badge g-A"' in out and "100/100" in out
    assert "No priority issues were found." in out


def test_incomplete_grade_rendering(world):
    world["tls"]["example.com"] = socket.gaierror("no host")  # apex does not resolve -> tls check errors
    rep = report()
    for lang, word in (("en", "Incomplete"), ("it", "Incompleto")):
        out = render_html(rep, lang)
        assert 'class="badge g-incomplete"' in out and word in out
        assert 'class="badge g-A"' not in out and 'class="badge g-B"' not in out
    assert "partial score" in render_html(rep, "en")
    assert "punteggio parziale" in render_html(rep, "it")
    assert "Check could not be completed" in render_html(rep, "en")  # errored check listed with reason
    assert "Not included in the score" in render_html(rep, "en")


def test_skipped_check_listed_with_reason(world):
    world["bootstrap"] = {"net": ["https://rdap.example/"]}
    out = render_html(report(), "en")
    assert "Check skipped" in out and esc(EN["reasons"]["no_rdap_for_tld"]) in out
    it = render_html(report(), "it")
    assert esc(IT["reasons"]["no_rdap_for_tld"]) in it
    assert "no RDAP service for TLD" not in it  # raw English stays in --json


def test_expiry_titles_use_escaped_integer_days(world):
    world["tls"]["example.com"] = (make_cert(days_left=10), "TLSv1.3")
    rep = report()
    f = next(f for f in rep.findings if f.id == "tls_cert_expires_lt_14d")
    assert isinstance(f.days_left, int)
    en, it = render_html(rep, "en"), render_html(rep, "it")
    assert f"expires in {f.days_left} days" in en
    assert f"scade tra {f.days_left} giorni" in it
    assert "{days}" not in en + it


def test_domain_expiry_days_in_title(world):
    world["rdap"] = rdap_body(days_to_expiry=20)
    rep = report()
    f = next(f for f in rep.findings if f.id == "domain_expires_lt_30d")
    assert f"expires in {f.days_left} days" in render_html(rep, "en")


def test_dates_en_utc_and_it_rome_with_utc_in_brackets():
    assert format_checked_at("2026-07-10T12:00:00+00:00", "en") == "2026-07-10 12:00 UTC"
    assert format_checked_at("2026-07-10T12:00:00+00:00", "it") == "10/07/2026 14:00 (ora di Roma, 12:00 UTC)"
    assert format_checked_at("2026-01-10T12:00:00+00:00", "it").startswith("10/01/2026 13:00")  # winter time


def test_italian_report_is_italian(world):
    world["txt"].pop("_dmarc.example.com")
    out = render_html(report(), "it")
    assert '<html lang="it">' in out
    assert "Nessuna protezione DMARC" in out and "Perché conta" in out and "Alto" in out
    assert "Glossario" in out and "Registrar" in out


def test_spf_evidence_uses_actual_host(world):
    world["tls"]["app.example.com"] = (make_cert(hosts=("app.example.com",)), "TLSv1.3")
    world["txt"]["app.example.com"] = []
    rep = report("app.example.com")
    f = next(f for f in rep.findings if f.id == "spf_missing")
    assert "at app.example.com" in f.evidence and "apex" not in f.evidence


def test_days_left_is_not_in_json(world):
    world["tls"]["example.com"] = (make_cert(days_left=10), "TLSv1.3")
    data = report().to_dict()
    assert all("days_left" not in f for f in data["findings"])
    assert set(data["findings"][0]) == {"id", "category", "severity", "title", "evidence", "recommendation"}


# --- CLI -----------------------------------------------------------------------


def test_report_option_does_not_change_json_output(world, tmp_path, capsys, monkeypatch):
    import openosint.exposure
    from openosint import cli

    fixed = report()

    async def fake_run(domain, lookalikes=False, resolver=None):
        return fixed

    monkeypatch.setattr(openosint.exposure, "run_exposure", fake_run)
    asyncio.run(cli._handle_exposure("example.com", json_output=True))
    plain = capsys.readouterr().out
    out_file = tmp_path / "r.html"
    asyncio.run(cli._handle_exposure("example.com", json_output=True, report_path=str(out_file), lang="it"))
    with_report, err = capsys.readouterr()
    assert with_report == plain and json.loads(plain)["domain"] == "example.com"
    assert "Report written" in err
    assert "Riepilogo per area" in out_file.read_text(encoding="utf-8")


def test_unwritable_report_path_exits_1(world, tmp_path, monkeypatch):
    from openosint import cli

    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli._handle_exposure("example.com", json_output=True, report_path=str(tmp_path / "nope" / "r.html")))
    assert exc.value.code == 1

