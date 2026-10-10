"""Third-party promotion/credit lines must not end up in tool results.

Samples in tests/fixtures/cli_output/ are the exact text each CLI prints, taken from the
installed sherlock-project (notify.py), holehe (core.py: credit()) and sublist3r (banner())
sources, not a live scan.
"""

from pathlib import Path

from openosint.tools.search_domain import _format_domain_results
from openosint.tools.search_email import _format_email_results
from openosint.tools.search_username import _format_username_results

FIX = Path(__file__).parent / "fixtures" / "cli_output"
PROMO = ("osintsearch", "go deeper", "palenath", "megadose", "btc donations", "coded by")


def _sample(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _assert_clean(text: str) -> None:
    assert not [p for p in PROMO if p in text.lower()], text


def test_sherlock_promo_footer_is_stripped_and_hits_kept():
    out = _format_username_results(_sample("sherlock.txt"), "johndoe99")
    _assert_clean(out)
    assert "https://github.com/johndoe99" in out and "Search completed with" in out


def test_holehe_credit_lines_are_stripped_and_hits_kept():
    out = _format_email_results(_sample("holehe.txt"), "a@example.com")
    _assert_clean(out)
    assert "[+] github.com" in out and "120 websites checked" in out


def test_sublist3r_banner_is_stripped_and_subdomains_kept():
    out = _format_domain_results(_sample("sublist3r.txt"), "example.com")
    _assert_clean(out)
    assert "www.example.com" in out and "mail.example.com" in out


def test_output_that_is_only_a_promo_counts_as_empty():
    promo_only = "Go deeper than a username. Explore public profiles.\nTry OSINTSearch: https://osintsearch.org\n"
    assert "No accounts found" in _format_username_results(promo_only, "x")
