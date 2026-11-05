"""Every setting a user can supply, with where to get it and which tools use it.

Single source of truth for: the web UI's key form, what /api/setup accepts, and
the "needs X key" text every tool returns when a key is missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from openosint.brightdata import (
    DISCLOSURE_PLACEHOLDER,
    LINK_PLACEHOLDER,
    current_surface,
    resolve,
    setup_steps,
)
from openosint.config_store import config_path

GROUP_AI = "ai"
GROUP_TOOLS = "tools"

_IP2LOCATION_URL = "https://www.ip2location.io/pricing?utm_source=openosint&utm_medium=webui&utm_campaign=ip2location"


@dataclass(frozen=True)
class SettingKey:
    key: str
    label: str
    group: str
    url: str
    used_by: tuple[str, ...] = ()
    secret: bool = True
    optional: bool = False
    note: str = ""


SETTINGS: tuple[SettingKey, ...] = (
    SettingKey(
        "ANTHROPIC_API_KEY",
        "Anthropic API key",
        GROUP_AI,
        "https://console.anthropic.com/settings/keys",
        used_by=("chat",),
        note="Powers the chat. Alternatives: an OpenAI-compatible server (Settings) or free local Ollama.",
    ),
    SettingKey(
        "OPENAI_BASE_URL",
        "OpenAI-compatible endpoint: base URL",
        GROUP_AI,
        "",
        used_by=("chat",),
        secret=False,
        note="Alternative to Anthropic: OpenRouter, LiteLLM, vLLM, llama.cpp… e.g. https://openrouter.ai/api/v1 or http://localhost:4000/v1",
    ),
    SettingKey(
        "OPENAI_MODEL",
        "OpenAI-compatible endpoint: model",
        GROUP_AI,
        "",
        used_by=("chat",),
        secret=False,
    ),
    SettingKey(
        "OPENAI_API_KEY",
        "OpenAI-compatible endpoint: API key",
        GROUP_AI,
        "",
        used_by=("chat",),
        note="Local servers may not need one.",
    ),
    SettingKey(
        "HIBP_API_KEY",
        "Have I Been Pwned API key",
        GROUP_TOOLS,
        "https://haveibeenpwned.com/API/Key",
        used_by=("search_breach",),
        note="Paid subscription.",
    ),
    SettingKey(
        "SHODAN_API_KEY",
        "Shodan API key",
        GROUP_TOOLS,
        "https://account.shodan.io",
        used_by=("search_shodan",),
        note="Free tier available.",
    ),
    SettingKey(
        "VIRUSTOTAL_API_KEY",
        "VirusTotal API key",
        GROUP_TOOLS,
        "https://www.virustotal.com/gui/my-apikey",
        used_by=("search_virustotal",),
        note="Free tier available.",
    ),
    SettingKey(
        "ABUSEIPDB_API_KEY",
        "AbuseIPDB API key",
        GROUP_TOOLS,
        "https://www.abuseipdb.com/account/api",
        used_by=("search_abuseipdb",),
        note="Free tier available.",
    ),
    SettingKey(
        "IP2LOCATION_API_KEY",
        "IP2Location.io API key",
        GROUP_TOOLS,
        _IP2LOCATION_URL,
        used_by=("search_ip2location",),
        note="Sponsor of OpenOSINT.",
    ),
    SettingKey(
        "CENSYS_API_ID",
        "Censys API ID",
        GROUP_TOOLS,
        "https://censys.io/account",
        used_by=("search_censys",),
        secret=False,
    ),
    SettingKey(
        "CENSYS_SECRET",
        "Censys API secret",
        GROUP_TOOLS,
        "https://censys.io/account",
        used_by=("search_censys",),
    ),
    SettingKey(
        "BRIGHTDATA_API_KEY",
        "Bright Data API key",
        GROUP_TOOLS,
        LINK_PLACEHOLDER,
        used_by=("search_dorks_live", "scrape_url", "search_footprint"),
        note=f"A free tier (5,000 requests/month) is available. {DISCLOSURE_PLACEHOLDER}",
    ),
    SettingKey(
        "BRIGHTDATA_SERP_ZONE",
        "Bright Data SERP zone name",
        GROUP_TOOLS,
        LINK_PLACEHOLDER,
        used_by=("search_dorks_live", "search_footprint"),
        secret=False,
        note=f"Your Bright Data SERP API zone name (e.g. 'serp_api1'); create the zone in the dashboard. {DISCLOSURE_PLACEHOLDER}",
    ),
    SettingKey(
        "BRIGHTDATA_UNLOCKER_ZONE",
        "Bright Data Web Unlocker zone name",
        GROUP_TOOLS,
        LINK_PLACEHOLDER,
        used_by=("scrape_url",),
        secret=False,
        note=f"Your Bright Data Web Unlocker zone name (e.g. 'web_unlocker1'); create the zone in the dashboard. {DISCLOSURE_PLACEHOLDER}",
    ),
    SettingKey(
        "IPINFO_TOKEN",
        "ipinfo.io token (optional)",
        GROUP_TOOLS,
        "https://ipinfo.io/signup",
        used_by=("search_ip",),
        optional=True,
        note="search_ip works without it; a token raises the rate limit.",
    ),
    SettingKey(
        "GITHUB_TOKEN",
        "GitHub token (optional)",
        GROUP_TOOLS,
        "https://github.com/settings/tokens",
        used_by=("search_github",),
        optional=True,
        note="search_github works without it; a token raises the rate limit.",
    ),
)

_BY_KEY = {s.key: s for s in SETTINGS}
SETTING_NAMES: frozenset[str] = frozenset(_BY_KEY)
SAVEABLE_NAMES: frozenset[str] = SETTING_NAMES


def setting(key: str) -> SettingKey | None:
    return _BY_KEY.get(key)


def public_catalog() -> list[dict]:
    """The form's field list: AI provider first, then tool keys. Never any values."""
    ordered = sorted(SETTINGS, key=lambda s: (s.group != GROUP_AI, s.optional))
    return [
        {
            "key": s.key,
            "label": s.label,
            "group": s.group,
            "url": resolve(s.url),
            "used_by": list(s.used_by),
            "secret": s.secret,
            "optional": s.optional,
            "note": resolve(s.note),
        }
        for s in ordered
    ]


_WEB_SURFACES = ("webui", "webui-remote", "demo")


def _add_it_line(missing: list[str]) -> str:
    """Where to put the missing settings, worded for the surface that is asking."""
    names, cfg, surface = " and ".join(missing), config_path(), current_surface()
    if surface == "mcp":
        return (
            f'Add it: put {names} in the "env" block of the openosint server in your MCP client config, '
            f"or in {cfg} — then restart the MCP server and run this again."
        )
    if surface in _WEB_SURFACES:
        return (
            f'Add it: web UI → Settings → "Save keys to server", or set {names} in the '
            f"environment, or put it in {cfg} — then run this again."
        )
    return f"Add it: set {names} in the environment or in {cfg} — then run this again."


def missing_keys_details(missing: list[str]) -> list[str]:
    """Everything after the two header lines: where to get it, the setup steps, where to put it."""
    # Someone who already holds a Bright Data token has an account: no signup link for them.
    has_account = (
        any(n.startswith("BRIGHTDATA") for n in missing) and "BRIGHTDATA_API_KEY" not in missing
    )
    lines: list[str] = []
    seen_urls: list[str] = []
    for entry in (setting(name) for name in missing):
        url = resolve(entry.url) if entry else ""
        if not entry or url in seen_urls or (has_account and entry.key.startswith("BRIGHTDATA")):
            continue
        seen_urls.append(url)
        note = resolve(entry.note)
        suffix = f" — {note}" if note else ""
        lines.append(f"Get one: {url}{suffix}")
    return lines + setup_steps(missing) + [_add_it_line(missing)]


def _labels(missing: list[str]) -> str:
    entries = [setting(name) for name in missing]
    return _join([e.label if e else name for e, name in zip(entries, missing)])


def missing_keys_message(tool: str, missing: list[str]) -> str:
    """The one human-readable result a tool returns when it lacks its credentials."""
    header = [
        f"Scan error: {tool} cannot run: {_labels(missing)} not set.",
        f"[key_required] {', '.join(missing)}",
    ]
    return "\n".join(header + missing_keys_details(missing))


def missing_keys_extra(tool: str, missing: list[str]) -> str:
    """The same guidance as a follow-on to another refusal (e.g. passive mode), without the error header."""
    return "\n".join([f"{tool} also needs {_labels(missing)}."] + missing_keys_details(missing))


def missing_from(
    names: list[str], supplied: dict[str, str] | None, environ: dict[str, str]
) -> list[str]:
    supplied = supplied or {}
    return [n for n in names if not (supplied.get(n) or environ.get(n, "")).strip()]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
