"""run_exposure(..., checks=...): run only some checks. All offline, via the `world` fixture."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import pytest

from openosint import cli
from openosint.exposure import api, headers_check, registration_check, runner
from openosint.exposure.models import DomainNotRegistered
from openosint.exposure.render import render
from openosint.exposure.report import render_html
from openosint.tools.search_rdap import RDAPNotFound
from tests.exposure_helpers import ids


def run(**kwargs):
    return asyncio.run(runner.run_exposure("example.com", **kwargs))


@pytest.fixture
def calls(world, monkeypatch):
    """Which network seams were touched: DNS (email), RDAP, TLS, headers."""
    seen = {"headers": 0}

    def counting_get(url):
        seen["headers"] += 1
        return world["headers"]

    monkeypatch.setattr(headers_check, "_get", counting_get)
    return seen


# --- the names --------------------------------------------------------------------------------


def test_the_check_names_and_the_passive_subset_are_exported():
    assert runner.CHECK_NAMES == ("email", "registration", "tls", "http_headers")
    assert runner.PASSIVE_CHECKS == ("email", "registration")
    assert api.CHECK_NAMES is runner.CHECK_NAMES and api.PASSIVE_CHECKS is runner.PASSIVE_CHECKS
    assert {"CHECK_NAMES", "PASSIVE_CHECKS"} <= set(api.__all__)


def test_the_passive_subset_is_exactly_the_checks_labelled_passive():
    from openosint.tool_policy import Noise

    passive = {n for n, (_fn, noise) in runner.CHECKS.items() if noise == Noise.PASSIVE.value}

    assert set(runner.PASSIVE_CHECKS) == passive


# --- the default is unchanged -----------------------------------------------------------------


def test_without_checks_everything_runs_and_is_graded_as_before(world, calls):
    rep = run()

    assert [c.name for c in rep.checks] == list(runner.CHECK_NAMES)
    assert (rep.grade, rep.score, rep.not_run) == ("A", 100, ())
    assert world["tls_hosts"] and calls["headers"] == 1


def test_selecting_all_four_is_the_same_as_the_default(world):
    rep = run(checks=("tls", "http_headers", "registration", "email"))

    assert [c.name for c in rep.checks] == list(runner.CHECK_NAMES)  # fixed order, not the caller's
    assert (rep.grade, rep.score, rep.not_run) == ("A", 100, ())


# --- a selection ------------------------------------------------------------------------------


def test_passive_selection_never_touches_the_target(world, calls):
    world["txt"]["_dmarc.example.com"] = []  # a finding to prove the checks really ran

    rep = run(checks=runner.PASSIVE_CHECKS)

    assert [c.name for c in rep.checks] == ["email", "registration"]
    assert world["tls_hosts"] == [] and calls["headers"] == 0  # no connection to the domain
    assert world["rdap_queried"] == ["example.com"]  # the registry was asked
    assert {"dmarc_missing", "domain_age"} <= ids(rep)  # both selected checks produced findings
    assert {c.noise for c in rep.checks} == {"passive"}


def test_a_selection_is_not_graded_and_says_what_was_left_out(world):
    rep = run(checks=runner.PASSIVE_CHECKS)

    assert rep.grade is None and rep.score is None
    assert rep.score_is_partial is False and rep.grade_capped_by_critical is False
    assert rep.not_run == ("tls", "http_headers")
    assert rep.excluded_checks == ()  # nothing failed: they were simply not selected


def test_findings_of_a_selection_are_reported_but_never_turned_into_a_grade(world):
    world["txt"]["example.com"] = []  # no SPF

    rep = run(checks=["email"])

    assert "spf_missing" in ids(rep) or any(i.startswith("spf") for i in ids(rep))
    assert rep.grade is None and rep.not_run == ("registration", "tls", "http_headers")


@pytest.mark.parametrize(
    ("selection", "expected"),
    (
        (["registration", "email"], ["email", "registration"]),  # fixed order
        (("email", "email", "email"), ["email"]),  # duplicates collapse
        ({"tls"}, ["tls"]),  # any iterable
        ((n for n in ("http_headers",)), ["http_headers"]),
        (frozenset({"registration", "tls"}), ["registration", "tls"]),
    ),
)
def test_selection_is_normalised(world, selection, expected):
    rep = run(checks=selection)

    assert [c.name for c in rep.checks] == expected


def test_only_the_selected_active_checks_run(world, calls):
    rep = run(checks=["tls"])

    assert [c.name for c in rep.checks] == ["tls"] and world["tls_hosts"]
    assert calls["headers"] == 0 and world["rdap_queried"] == []


def test_a_selected_check_that_fails_is_an_error_not_a_not_run(world, monkeypatch):
    def boom(domain, bootstrap):
        raise RuntimeError("registry down")

    monkeypatch.setattr(registration_check, "_rdap", boom)

    rep = run(checks=runner.PASSIVE_CHECKS)

    assert rep.excluded_checks == ("registration",) and rep.not_run == ("tls", "http_headers")
    assert {c.name: c.status for c in rep.checks}["registration"] == "error"


def test_an_unregistered_domain_still_aborts_a_selection_that_includes_registration(
    world, monkeypatch
):
    def missing(domain, bootstrap):
        raise RDAPNotFound("404")

    monkeypatch.setattr(registration_check, "_rdap", missing)

    with pytest.raises(DomainNotRegistered):
        run(checks=["registration"])


def test_lookalikes_and_a_selection_combine_without_grading(world, monkeypatch):
    from openosint.exposure import lookalikes_check
    from openosint.exposure.models import LookalikeScan

    monkeypatch.setattr(lookalikes_check, "scan", lambda registrable, dns: LookalikeScan("ok", 0, 0))

    rep = run(checks=runner.PASSIVE_CHECKS, lookalikes=True)

    assert rep.lookalikes is not None and rep.grade is None


# --- validation -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "match"),
    (
        (["email", "ssl"], "Unknown check.*ssl.*Choose from: email, registration, tls, http_headers"),
        (["Email"], "Unknown check"),
        ([], "empty"),
        ((), "empty"),
        (set(), "empty"),
        ("email", "not a single string"),
        ("tls,email", "not a single string"),
    ),
)
def test_bad_selections_raise_value_error_before_any_network_call(world, calls, bad, match):
    with pytest.raises(ValueError, match=match):
        run(checks=bad)

    assert calls["headers"] == 0 and world["tls_hosts"] == [] and world["rdap_queried"] == []


def test_unknown_names_are_all_listed():
    with pytest.raises(ValueError) as caught:
        runner.select_checks(["nope", "email", "also-nope"])

    assert "also-nope, nope" in str(caught.value)


# --- the report -------------------------------------------------------------------------------


def test_to_dict_carries_not_run_for_every_report(world):
    full = run().to_dict()
    partial = run(checks=runner.PASSIVE_CHECKS).to_dict()

    assert full["not_run"] == [] and partial["not_run"] == ["tls", "http_headers"]
    assert partial["grade"] is None and partial["score"] is None
    assert list(partial["checks"]) == ["email", "registration"]
    assert json.loads(json.dumps(partial)) == partial


def test_the_terminal_summary_says_not_graded(world):
    text = render(run(checks=runner.PASSIVE_CHECKS))

    assert "Not graded" in text and "tls, http_headers" in text
    assert "Grade: None" not in text and "None/100" not in text


@pytest.mark.parametrize(("lang", "badge"), (("en", "Not graded"), ("it", "Senza voto")))
def test_the_html_report_says_not_graded_in_both_languages(world, lang, badge):
    world["txt"]["_dmarc.example.com"] = []
    for rep in (run(checks=runner.PASSIVE_CHECKS), run(checks=["registration"])):
        html = render_html(rep, lang)

        assert badge in html
        assert "grade None" not in html and "g-None" not in html and "Overall grade" not in html


def test_the_full_html_report_is_unchanged(world):
    html = render_html(run(), "en")

    assert "Not graded" not in html and "Overall grade A" in html


# --- the CLI ----------------------------------------------------------------------------------


def test_the_cli_flag_is_parsed_into_a_normalised_tuple():
    parser = cli._build_parser()

    assert parser.parse_args(["exposure", "example.com"]).checks is None
    parsed = parser.parse_args(["exposure", "example.com", "--checks", "registration, email,"])
    assert parsed.checks == ("email", "registration")


def test_the_cli_passes_the_selection_and_leaves_the_default_call_alone(monkeypatch, capsys):
    seen = []

    async def fake(domain, lookalikes=False, resolver=None, **extra):
        seen.append(extra)
        raise ValueError("stop here")

    monkeypatch.setattr("openosint.exposure.run_exposure", fake)
    for checks in (("email",), None):
        with pytest.raises(SystemExit):
            asyncio.run(cli._handle_exposure("example.com", checks=checks))

    assert seen == [{"checks": ("email",)}, {}]  # no new keyword unless the flag was given


def test_the_cli_rejects_unknown_checks_with_a_clean_message():
    out = subprocess.run(
        [sys.executable, "-m", "openosint.cli", "exposure", "example.com", "--checks", "email,ssl"],
        capture_output=True, text=True, timeout=60,
    )

    assert out.returncode == 2 and "Unknown check" in out.stderr and "Traceback" not in out.stderr
