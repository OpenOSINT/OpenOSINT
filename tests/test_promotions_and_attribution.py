"""Promotions of other products are removed; credit to the underlying tool stays.

Samples in tests/fixtures/cli_output/ are the exact text each CLI prints, taken from the
installed sherlock-project (notify.py), holehe (core.py: credit()) and sublist3r (banner())
sources, not a live scan.
"""

from pathlib import Path

import pytest

from openosint.tools.search_domain import _format_domain_results
from openosint.tools.search_email import _format_email_results
from openosint.tools.search_username import _format_username_results

FIX = Path(__file__).parent / "fixtures" / "cli_output"
PROMOS = ("osintsearch", "go deeper than a username")


def _sample(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _no_promos(text: str) -> None:
    assert not [p for p in PROMOS if p in text.lower()], text


def test_sherlock_osintsearch_promotion_is_removed_and_hits_kept():
    out = _format_username_results(_sample("sherlock.txt"), "johndoe99")
    _no_promos(out)
    assert "https://github.com/johndoe99" in out and "Search completed with" in out


def test_holehe_keeps_its_own_credit_lines():
    out = _format_email_results(_sample("holehe.txt"), "a@example.com")
    assert "[+] github.com" in out and "120 websites checked" in out
    assert "Github : https://github.com/megadose/holehe" in out  # upstream's own credit is not ours to delete


@pytest.mark.parametrize(
    "render,sample,arg,tool,url",
    [
        (_format_username_results, "sherlock.txt", "johndoe99", "sherlock", "https://github.com/sherlock-project/sherlock"),
        (_format_email_results, "holehe.txt", "a@example.com", "holehe", "https://github.com/megadose/holehe"),
        (_format_domain_results, "sublist3r.txt", "example.com", "sublist3r", "https://github.com/aboul3la/Sublist3r"),
    ],
)
def test_every_result_ends_with_openosint_attribution(render, sample, arg, tool, url):
    expected = f"Results via {tool} ({url})"
    assert render(_sample(sample), arg).endswith(expected)
    assert render("", arg).endswith(expected)  # also on empty results


def test_sublist3r_subdomains_kept():
    out = _format_domain_results(_sample("sublist3r.txt"), "example.com")
    assert "www.example.com" in out and "mail.example.com" in out


def test_output_that_is_only_a_promotion_counts_as_empty():
    promo_only = "Go deeper than a username. Explore public profiles.\nTry OSINTSearch: https://osintsearch.org\n"
    out = _format_username_results(promo_only, "x")
    assert "No accounts found" in out
    _no_promos(out)
