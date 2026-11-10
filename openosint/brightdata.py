"""
Bright Data referral links for every OpenOSINT placement, in one place.

Scheme: ``?sid1=<surface>&sid2=<moment>[&sid3=<tool>]`` plus the same values as
``utm_source=openosint&utm_medium&utm_campaign[&utm_content]``. PartnerStack reports the SubIDs
(``sid1..3``); the UTMs are kept for Bright Data's side.

Destination: signup flows use the Signup link, ``search_dorks_live`` / ``search_footprint`` the SERP API
link, ``scrape_url`` the Web Unlocker link, everything else the base link.

* surface (``utm_medium``): where the link is shown. In-product surfaces are set once at
  startup by the entry point: ``cli`` (default), ``mcp``, ``webui`` (loopback web UI),
  ``webui-remote`` (a network-exposed web UI) and ``demo`` (only demo.openosint.tech).
* moment (``utm_campaign``): setup, quota, blocked or docs.
* ``OPENOSINT_NO_REFERRAL_LINKS=1`` swaps every in-product link for a plain
  ``https://brightdata.com`` and drops the commission wording; instructions stay.

Any text that shows a referral link must also show :func:`disclosure` (or the page-level
equivalent). ``tests/test_brightdata_links.py`` enforces that for the shipped files.
"""

from __future__ import annotations

import os
from urllib.parse import urlencode

_LINKS = {
    "main": "https://get.brightdata.com/984ni58s2oad",
    "signup": "https://get.brightdata.com/openosint-signup",
    "serp": "https://get.brightdata.com/jx2wfi",
    "unlocker": "https://get.brightdata.com/openosint-unlocker",
}
_TOOL_DEST = {"search_dorks_live": "serp", "search_footprint": "serp", "scrape_url": "unlocker"}
_PLAIN = "https://brightdata.com"

# Dashboard pages for people who already have an account (no referral link on these).
TOKEN_URL = "https://brightdata.com/cp/setting/users"
BILLING_URL = "https://brightdata.com/cp/billing"

OPT_OUT_ENV = "OPENOSINT_NO_REFERRAL_LINKS"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

SURFACES = ("readme", "docs", "cli", "mcp", "webui", "webui-remote", "demo", "env-example")
CAMPAIGNS = ("setup", "quota", "blocked", "docs")

REFERRAL_DISCLOSURE = "OpenOSINT earns a referral commission if you sign up through this link."

# Static catalogs (settings, web tool metadata) hold these; resolve() fills them at use time,
# so the link reflects the surface and opt-out of the running process, not of import time.
LINK_PLACEHOLDER = "{brightdata-referral}"
DISCLOSURE_PLACEHOLDER = "{brightdata-disclosure}"

# Set once by the entry point (see set_surface). Process-wide on purpose: one process serves one surface.
_surface = "cli"


def set_surface(surface: str) -> None:
    """Record which surface this process serves (``cli`` is the default)."""
    global _surface
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}; expected one of {SURFACES}")
    _surface = surface


def current_surface() -> str:
    return _surface


def links_enabled() -> bool:
    return os.environ.get(OPT_OUT_ENV, "").strip().lower() not in _TRUTHY


def _build(medium: str, campaign: str, content: str | None, dest: str | None = None) -> str:
    if medium not in SURFACES:
        raise ValueError(f"unknown surface {medium!r}; expected one of {SURFACES}")
    if campaign not in CAMPAIGNS:
        raise ValueError(f"unknown campaign {campaign!r}; expected one of {CAMPAIGNS}")
    dest = dest or _TOOL_DEST.get(content or "", "main")
    if dest not in _LINKS:
        raise ValueError(f"unknown destination {dest!r}; expected one of {tuple(_LINKS)}")
    params = {"sid1": medium, "sid2": campaign}
    if content:
        params["sid3"] = content
    params |= {"utm_source": "openosint", "utm_medium": medium, "utm_campaign": campaign}
    if content:
        params["utm_content"] = content
    return f"{_LINKS[dest]}?{urlencode(params)}"


def referral_link(
    campaign: str = "setup", *, content: str | None = None, dest: str | None = None
) -> str:
    """The link for an in-product message; plain brightdata.com when the user opted out."""
    tracked = _build(_surface, campaign, content, dest)  # also validates the arguments
    return tracked if links_enabled() else _PLAIN


def static_link(
    medium: str, campaign: str, content: str | None = None, dest: str | None = None
) -> str:
    """A link for a published file (site, README). Ignores the runtime surface and opt-out."""
    return _build(medium, campaign, content, dest)


def disclosure() -> str:
    """The one-sentence disclosure, or "" when links are off."""
    return REFERRAL_DISCLOSURE if links_enabled() else ""


def disclosure_suffix() -> str:
    """`` (disclosure)`` to append after an in-line link, or "" when links are off."""
    text = disclosure()
    return f" ({text})" if text else ""


def resolve_static(text: str, medium: str = "docs", campaign: str = "setup") -> str:
    """Like :func:`resolve` for a published page: always tracked and disclosed, never opted out."""
    link = static_link(medium, campaign, dest="signup")
    return (
        text.replace(LINK_PLACEHOLDER, link)
        .replace(DISCLOSURE_PLACEHOLDER, REFERRAL_DISCLOSURE)
        .strip()
    )


def resolve(text: str) -> str:
    """Fill the link and disclosure placeholders in catalog text for the running process."""
    filled = text.replace(LINK_PLACEHOLDER, referral_link(dest="signup")).replace(
        DISCLOSURE_PLACEHOLDER, disclosure()
    )
    return filled.replace(" ()", "").strip()  # "(…)" around a disclosure that opt-out removed


_ZONE_STEPS = {
    "BRIGHTDATA_SERP_ZONE": "Create a SERP API zone in your dashboard; its name goes in BRIGHTDATA_SERP_ZONE.",
    "BRIGHTDATA_UNLOCKER_ZONE": (
        "Create a Web Unlocker zone in your dashboard; its name goes in BRIGHTDATA_UNLOCKER_ZONE."
    ),
}


def setup_steps(missing: list[str], *, guided_hint: bool = True) -> list[str]:
    """Numbered dashboard steps for exactly the Bright Data settings still missing.

    ``guided_hint`` adds a closing line pointing at ``openosint setup brightdata``.
    """
    if not any(name.startswith("BRIGHTDATA") for name in missing):
        return []
    steps = []
    if "BRIGHTDATA_API_KEY" in missing:
        steps.append("Sign up or log in (link above).")
        steps.append(f"Copy your API token from {TOKEN_URL}; it goes in BRIGHTDATA_API_KEY.")
    steps.extend(text for name, text in _ZONE_STEPS.items() if name in missing)
    heading = "Set up Bright Data" + (
        " (the free tier needs no credit card):" if "BRIGHTDATA_API_KEY" in missing else ":"
    )
    lines = [heading] + [f"  {i}. {step}" for i, step in enumerate(steps, start=1)]
    if guided_hint:
        lines.append(
            "  Or run `openosint setup brightdata` for a guided setup (it asks before doing anything)."
        )
    return lines
