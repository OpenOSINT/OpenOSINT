"""`openosint setup brightdata`: a guided, opt-in setup for the Bright Data tools.

Nothing happens without a yes: the browser is opened only on request, a zone is created only
after an explicit confirmation, and a saved value is replaced only after asking. The token is
read hidden and is never printed.

Only two account endpoints are called, never the billable ``/request`` endpoint:

* ``GET /zone/get_active_zones`` validates the token and lists zone names. The official MCP
  server and Python SDK call it at every start; it is not in Bright Data's API reference, so its
  exact shape and that it costs no credit are UNVERIFIED (audit section 16). The reply is parsed
  defensively.
* ``POST /zone`` creates a zone (documented: "Add a Zone", Admin or Ops role). Bodies follow the
  documentation and the official SDK; ``ub_premium`` is deliberately not sent.
"""

from __future__ import annotations

import getpass
import os
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from openosint import config_store
from openosint.brightdata import (
    TOKEN_URL,
    disclosure,
    referral_link,
    setup_steps,
)
from openosint.brightdata_response import classify
from openosint.config_cli import handle_exposed_directory
from openosint.env import value_source

API_BASE = "https://api.brightdata.com"
LIST_URL = f"{API_BASE}/zone/get_active_zones"
ZONE_URL = f"{API_BASE}/zone"
REQUEST_TIMEOUT = 30
MAX_TOKEN_TRIES = 3
VERIFY_TRIES = 3
VERIFY_WAIT_SECONDS = 2.0
TOKEN_KEY = "BRIGHTDATA_API_KEY"
_YES = ("y", "yes")

# Printed in the signup step only (people who already have an account never see it). It claims
# nothing Bright Data does not document: inviting users and invoice recipients. A work email is not
# required and earns no extra credit.
WORK_EMAIL_ADVICE = (
    "Using this at work? Sign up with your work email so you can invite teammates "
    "and send invoices to your company."
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class ZoneKind:
    setting: str
    label: str
    tools: str
    default_name: str
    example: str
    serp: bool

    @property
    def key(self) -> str:
        return "serp" if self.serp else "unlocker"

    def payload(self, name: str) -> dict:
        """The documented 'Add a Zone' body (SERP: zone.type serp; Web Unlocker: the SDK's form)."""
        if self.serp:
            return {
                "zone": {"name": name, "type": "serp"},
                "plan": {"type": "unblocker", "serp": True},
            }
        return {"zone": {"name": name, "type": "unblocker"}, "plan": {"type": "unblocker"}}


ZONES: tuple[ZoneKind, ...] = (
    ZoneKind(
        "BRIGHTDATA_SERP_ZONE",
        "SERP API",
        "search_dorks_live and search_footprint",
        "openosint_serp",
        "openosint footprint example.com --max-queries 1",
        serp=True,
    ),
    ZoneKind(
        "BRIGHTDATA_UNLOCKER_ZONE",
        "Web Unlocker",
        "scrape_url",
        "openosint_unlocker",
        "openosint --allow-active scrape https://example.com",
        serp=False,
    ),
)

_INTRO = (
    "Bright Data powers three OpenOSINT tools: search_dorks_live and search_footprint (Google results "
    "through its SERP API) and scrape_url (pages that block direct access, through Web Unlocker).\n"
    "OpenOSINT works without it. Using it sends your targets to Bright Data. The free tier is 5,000 "
    "credits a month, one credit per request, no credit card needed."
)


# ---------------------------------------------------------------------------
# Account API (mockable through ``requests``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Listing:
    kind: str  # ok | rejected | no_permission | failed
    names: list[str] | None = None  # None: the reply could not be read
    message: str = ""
    kinds: dict[str, str] = field(
        default_factory=dict
    )  # zone name -> "serp" | "unlocker", when known


def forbidden_message(action: str) -> str:
    """One non-blaming explanation of an HTTP 403, shared by listing and creating zones."""
    return (
        f"Bright Data answered HTTP 403: this token's permission level does not allow {action}. "
        "Nothing is wrong with your setup. Either (a) create the zone in the Bright Data dashboard "
        "(steps below), or (b) use a token with the Admin or Ops role or the 'Zone Management' "
        f"permission ({TOKEN_URL}) and run `openosint setup brightdata` again."
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _zone_items(payload) -> list | None:
    items = payload.get("zones") if isinstance(payload, dict) else payload
    return items if isinstance(items, list) else None


def _zone_kind(item) -> str | None:
    """ "serp" / "unlocker" when the entry says so. A bare ``type: unblocker`` is NOT guessed:
    a SERP zone created elsewhere can look like that."""
    if not isinstance(item, dict):
        return None
    plan = item.get("plan") if isinstance(item.get("plan"), dict) else {}
    if item.get("type") == "serp" or plan.get("serp") is True:
        return "serp"
    if item.get("type") in ("web_unlocker", "unlocker") or plan.get("type") == "unblocker":
        return "unlocker"
    return None


def list_zones(token: str) -> Listing:
    try:
        response = requests.get(LIST_URL, headers=_headers(token), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        return Listing("failed", message=f"Could not reach Bright Data: {exc}")
    if response.status_code == 403:
        return Listing("no_permission", message=forbidden_message("listing zones"))
    error = classify(response, api_key=token, zone="", zone_env="", product="account API")
    if error is not None:
        return Listing("rejected" if error.status_code == 401 else "failed", message=str(error))
    try:
        items = _zone_items(response.json())
    except ValueError:
        items = None
    if items is None:
        return Listing("ok")
    named = [(i.get("name") if isinstance(i, dict) else i, _zone_kind(i)) for i in items]
    named = [(n, k) for n, k in named if isinstance(n, str)]
    return Listing("ok", names=[n for n, _ in named], kinds={n: k for n, k in named if k})


def create_zone(token: str, kind: ZoneKind, name: str) -> tuple[bool, str, bool]:
    """(created or already existed, explanation when it was not, token is forbidden to create)."""
    try:
        response = requests.post(
            ZONE_URL, headers=_headers(token), json=kind.payload(name), timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as exc:
        return False, f"Could not reach Bright Data: {exc}", False
    status, body = response.status_code, (response.text or "").lower()
    if status in (200, 201, 409) or "duplicate" in body or "already exists" in body:
        return True, "", False
    if status == 403:
        return False, forbidden_message("creating zones"), True
    error = classify(response, api_key=token, zone=name, zone_env=kind.setting, product=kind.label)
    return (
        False,
        str(error) if error else f"Bright Data answered HTTP {status} when creating the zone.",
        False,
    )


# ---------------------------------------------------------------------------
# Interactive flow
# ---------------------------------------------------------------------------


class _Session:
    def __init__(self, ask, ask_secret, open_browser, sleep) -> None:
        self.ask, self.ask_secret, self.open_browser, self.sleep = (
            ask,
            ask_secret,
            open_browser,
            sleep,
        )
        self.creation_forbidden = (
            False  # set by the first 403 on POST /zone; never offer creation again
        )

    def yes(self, prompt: str) -> bool:
        return self.ask(prompt).strip().lower() in _YES


def _say(text: str = "") -> None:
    print(text)


def _warn(text: str) -> None:
    print(text, file=sys.stderr)


def _refuse_non_interactive() -> int:
    _warn("openosint setup brightdata needs an interactive terminal (it asks before every change).")
    _warn(
        f"Get an account: {referral_link('setup', dest='signup')} {disclosure()}".rstrip()
    )
    for line in setup_steps(["BRIGHTDATA_API_KEY", *(z.setting for z in ZONES)], guided_hint=False):
        _warn(line)
    _warn(f"Then set those variables in the environment or in {config_store.config_path()}.")
    return EXIT_USAGE


def _signup(session: _Session) -> None:
    link = referral_link("setup", dest="signup")
    _say(f"Sign up here: {link}")
    if disclosure():
        _say(disclosure())
    _say(WORK_EMAIL_ADVICE)
    if session.yes("Open it in your browser? [y/N] "):
        session.open_browser(link)


def _obtain_token(session: _Session, ask_account: bool) -> tuple[str, Listing] | None:
    if ask_account and not session.yes("Do you already have a Bright Data account? [y/N] "):
        _signup(session)
    _say(f"Your API token is in your account settings: {TOKEN_URL}")
    for _ in range(MAX_TOKEN_TRIES):
        token = session.ask_secret("Paste your Bright Data API token (input hidden): ").strip()
        if not token:
            _warn("No token entered.")
            continue
        listing = list_zones(token)
        if listing.kind in ("ok", "no_permission"):
            return token, listing
        _warn(listing.message)
        if listing.kind == "failed":
            return None
    _warn(f"Giving up after {MAX_TOKEN_TRIES} tries. Nothing was saved.")
    return None


def _manual_steps(kind: ZoneKind) -> None:
    for line in setup_steps([kind.setting], guided_hint=False):
        _say(line)


def _verify_zone(token: str, name: str, session: _Session) -> bool:
    for attempt in range(VERIFY_TRIES):
        listing = list_zones(token)
        if listing.names is not None and name in listing.names:
            return True
        if attempt < VERIFY_TRIES - 1:
            session.sleep(VERIFY_WAIT_SECONDS)
    return False


def _create_after_yes(session: _Session, token: str, kind: ZoneKind, name: str) -> bool:
    confirmed = session.yes(
        f"Create {kind.label} zone '{name}' in your Bright Data account? Bright Data's API docs warn this "
        "can modify your account or incur charges; requests are billed per use (1 credit each; free tier: "
        "5,000 credits/month). [y/N] "
    )
    if not confirmed:
        return False
    created, message, forbidden = create_zone(token, kind, name)
    session.creation_forbidden = session.creation_forbidden or forbidden
    if not created:
        _warn(message)
        return False
    if not _verify_zone(token, name, session):
        _say(f"Zone '{name}' was created but is not listed yet; it should appear shortly.")
    return True


def _zone_prompt(kind: ZoneKind, names: list[str], matches: list[str], can_create: bool) -> str:
    if matches:
        also = f" (also found: {', '.join(matches[1:])})" if len(matches) > 1 else ""
        parts = [f"press Enter to use '{matches[0]}'{also}", "type another zone name"]
    elif names:
        parts = ["type one of these names"]
    else:
        parts = ["type the name of an existing zone"]
    if can_create and not matches:
        parts.append(f"press Enter to create '{kind.default_name}'")
    parts.append("or type 'skip'")
    return f"{kind.label} zone for {kind.tools}: {', '.join(parts)}: "


def _choose_zone(
    session: _Session, token: str, kind: ZoneKind, listing: Listing, saved: str
) -> str | None:
    """The zone name to save for *kind*, or None when nothing should change."""
    if saved:
        _warn(f"Saved {kind.setting} '{saved}' was not found in your account.")
    names = listing.names or []
    matches = [n for n in names if listing.kinds.get(n) == kind.key]
    can_create = not session.creation_forbidden
    answer = session.ask(_zone_prompt(kind, names, matches, can_create)).strip()
    if answer.lower() == "skip":
        _manual_steps(kind)
        return None
    name = answer or (matches[0] if matches else kind.default_name)
    exists = listing.names is not None and name in listing.names
    if not exists and not (can_create and _create_after_yes(session, token, kind, name)):
        _manual_steps(kind)
        return None
    if (
        saved
        and saved != name
        and not session.yes(f"Replace saved {kind.setting} '{saved}' with '{name}'? [y/N] ")
    ):
        return None
    return name


def _example(settings: dict[str, str]) -> str:
    for kind in ZONES:
        if settings.get(kind.setting):
            return f"Try it:  {kind.example}   (sends 1 request = 1 credit)"
    return ""


def _warn_overridden(updates: dict[str, str]) -> None:
    for name, value in updates.items():
        if value_source(name) == "environment" and os.environ.get(name, "").strip() != value:
            _warn(
                f"{name} is also set as an environment variable, which takes priority over config.env; "
                "update or unset it for the new value to apply."
            )


def _check_existing_token(token: str) -> tuple[str, Listing | None] | int:
    """(token to keep, its listing), or ("", None) when it was rejected, or an exit code to stop with."""
    listing = list_zones(token)
    if listing.kind == "failed":
        _warn(listing.message)
        return EXIT_FAILED
    if listing.kind == "rejected":
        _warn(f"The saved token was rejected. {listing.message}")
        return "", None
    return token, listing


def run_setup_brightdata(
    *,
    interactive: bool,
    ask: Callable[[str], str] = input,
    ask_secret: Callable[[str], str] = getpass.getpass,
    open_browser: Callable[[str], object] = webbrowser.open,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Return a process exit code: 0 done or already set up, 1 stopped, 2 not interactive."""
    if not interactive:
        return _refuse_non_interactive()
    session = _Session(ask, ask_secret, open_browser, sleep)
    current = {k: os.environ.get(k, "").strip() for k in [TOKEN_KEY, *(z.setting for z in ZONES)]}
    _say(_INTRO)

    token, listing = current[TOKEN_KEY], None
    if token:
        checked = _check_existing_token(token)
        if isinstance(checked, int):
            return checked
        token, listing = checked
    new_token = not token
    if new_token:
        obtained = _obtain_token(session, ask_account=not current[TOKEN_KEY])
        if obtained is None:
            return EXIT_FAILED
        token, listing = obtained

    updates: dict[str, str] = {}
    if new_token:
        saved = config_store.read_config().get(TOKEN_KEY, "")
        if (
            saved
            and saved != token
            and not session.yes(f"Replace the saved {TOKEN_KEY} in config.env? [y/N] ")
        ):
            _say("Kept the saved token. Nothing changed.")
            return EXIT_FAILED
        updates[TOKEN_KEY] = token

    if listing.kind == "no_permission":
        _warn(listing.message)
        if new_token and not session.yes("Save the token anyway? [y/N] "):
            return EXIT_FAILED
        for kind in ZONES:
            _manual_steps(kind)
    else:
        names = listing.names
        satisfied = {
            z.setting: current[z.setting]
            for z in ZONES
            if current[z.setting] and (names is None or current[z.setting] in names)
        }
        if not new_token and len(satisfied) == len(ZONES):
            found = " and ".join(f"{z.label} zone '{satisfied[z.setting]}'" for z in ZONES)
            _say(f"Bright Data is already set up: the token is accepted; {found} found.")
            _say(_example(satisfied))
            return EXIT_OK
        pending = [z for z in ZONES if z.setting not in satisfied]
        if names and pending:
            _say(f"Zones in your account: {', '.join(names)}")
        for kind in pending:
            chosen = _choose_zone(session, token, kind, listing, current[kind.setting])
            if chosen:
                updates[kind.setting] = chosen

    if updates:
        handle_exposed_directory(False, True, ask)
        config_store.write_config(updates)
        _warn_overridden(updates)
        _say(f"Saved to {config_store.config_path()} (user-only): {', '.join(updates)}.")
    settings = {**current, **updates}
    configured = [z for z in ZONES if settings.get(z.setting)]
    if len(configured) == len(ZONES):
        _say("You're ready.")
    elif configured:
        _say(
            "You're partly set up. Run `openosint setup brightdata` again to finish the other zone."
        )
    else:
        _say(
            "Token saved. Create a zone (steps above), then run `openosint setup brightdata` again."
        )
    if _example(settings):
        _say(_example(settings))
    return EXIT_OK
