"""Noise classification, passive-mode gating and the per-request tool-call cap.

Single source of truth for three things:

* how noisy each tool is (``TOOL_POLICY``) and the one-line honest note shown
  in the web UI, in tool descriptions and in the README table;
* whether non-passive tools are enabled (off unless explicitly opted in);
* the tool-call budget every agent loop spends from.

Passive mode is the default everywhere. Opt in with ``--allow-active``,
``OPENOSINT_ALLOW_ACTIVE=1``, the web Settings toggle, or the MCP server
option. A public/restricted web request can never enable active tools.
"""

from __future__ import annotations

import contextvars
import functools
import json
import os
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

ENV_ALLOW_ACTIVE = "OPENOSINT_ALLOW_ACTIVE"
ENV_MAX_CALLS = "OPENOSINT_MAX_TOOL_CALLS"
ENV_MAX_CALLS_MULTI = "OPENOSINT_MAX_TOOL_CALLS_MULTI"
DEFAULT_MAX_CALLS = 15
DEFAULT_MAX_CALLS_MULTI = 30
_TRUE = ("1", "true", "yes", "on")


class Noise(str, Enum):
    PASSIVE = "passive"
    TOUCHES_TARGET = "touches target"
    NOISY = "noisy"
    UNVERIFIED = "unverified"  # egress not yet captured; treated as non-passive
    INHERITS = "inherits"  # fan-out tool: only runs tools the current mode allows


@dataclass(frozen=True)
class ToolPolicy:
    noise: Noise
    note: str
    # Part of an otherwise-passive tool that needs active mode (shown in the label).
    active_part: str = ""

    @property
    def is_passive(self) -> bool:
        return self.noise in (Noise.PASSIVE, Noise.INHERITS)


TOOL_POLICY: dict[str, ToolPolicy] = {
    "generate_dorks": ToolPolicy(Noise.PASSIVE, "Builds Google search URLs locally; sends nothing."),
    "search_breach": ToolPolicy(Noise.PASSIVE, "One request to haveibeenpwned.com."),
    "search_whois": ToolPolicy(Noise.PASSIVE, "Queries the registry/registrar WHOIS server, not the target."),
    "search_rdap": ToolPolicy(Noise.PASSIVE, "Queries IANA and the registry's RDAP server, not the target."),
    "search_ip": ToolPolicy(Noise.PASSIVE, "One request to ipinfo.io."),
    "search_ip2location": ToolPolicy(Noise.PASSIVE, "One request to api.ip2location.io."),
    "search_abuseipdb": ToolPolicy(Noise.PASSIVE, "One request to api.abuseipdb.com."),
    "search_github": ToolPolicy(Noise.PASSIVE, "A few requests to api.github.com."),
    "search_paste": ToolPolicy(Noise.PASSIVE, "One request to psbdmp.ws."),
    "search_censys": ToolPolicy(Noise.PASSIVE, "Censys API; returns data Censys already holds."),
    "search_shodan": ToolPolicy(Noise.PASSIVE, "Shodan API; reads Shodan's existing index, requests no new scan."),
    "search_gdelt_geo": ToolPolicy(Noise.PASSIVE, "Reads GDELT's public news feed."),
    "search_dorks_live": ToolPolicy(
        Noise.PASSIVE, "Google results via Bright Data; the target is sent to those two services."
    ),
    "search_footprint": ToolPolicy(
        Noise.PASSIVE, "Up to 3 Google queries via Bright Data; the target is sent to those two services."
    ),
    "search_dns": ToolPolicy(
        Noise.PASSIVE,
        "Record lookups go through your DNS resolver; the target's nameservers see the resolver, not you.",
        active_part="9 DKIM selector probes (enumeration) run only with active tools enabled.",
    ),
    "search_virustotal": ToolPolicy(
        Noise.PASSIVE,
        "IP, domain and hash lookups read VirusTotal's existing data.",
        active_part=(
            "URL submission makes VirusTotal fetch the target URL and makes the URL visible "
            "to the VirusTotal community, which can reveal your investigation."
        ),
    ),
    # Mode of search_virustotal, not a separate registered tool: gated inside it.
    "search_virustotal_url": ToolPolicy(
        Noise.TOUCHES_TARGET,
        "VirusTotal fetches the submitted URL, and the URL becomes visible to the VirusTotal community, "
        "which can reveal your investigation.",
    ),
    "scrape_url": ToolPolicy(
        Noise.TOUCHES_TARGET,
        "Bright Data fetches the URL, so the target's server logs a request (from Bright Data's IP, not yours).",
    ),
    "search_phone": ToolPolicy(
        Noise.UNVERIFIED,
        "Runs phoneinfoga; what it sends over the network has not been verified with a traffic capture.",
    ),
    "search_username": ToolPolicy(
        Noise.NOISY, "sherlock sends requests from your IP to hundreds of sites; expect rate limits and WAF blocks."
    ),
    "search_email": ToolPolicy(
        Noise.NOISY,
        "holehe probes many sites' sign-up/reset flows with the email from your IP; "
        "may notify the account owner or trigger security alerts.",
    ),
    "search_domain": ToolPolicy(
        Noise.NOISY, "sublist3r scrapes several search engines and aggregators from your IP; expect captchas and blocks."
    ),
    "investigate_graph": ToolPolicy(
        Noise.INHERITS, "Chains tools from a seed; in passive mode it routes only to passive tools."
    ),
    "investigate_multi": ToolPolicy(
        Noise.INHERITS, "Runs one agent per target under a shared tool-call cap; passive unless active is enabled."
    ),
    "graph_export": ToolPolicy(Noise.PASSIVE, "Reads the local graph database only."),
    "graph_neighbors": ToolPolicy(Noise.PASSIVE, "Reads the local graph database only."),
    "graph_review_candidates": ToolPolicy(Noise.PASSIVE, "Reads the local graph database only."),
}

# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

# True = this context (a public/restricted web request) can never use active
# tools, whatever the environment says. Nothing can force-enable.
_force_passive: contextvars.ContextVar[bool] = contextvars.ContextVar("openosint_force_passive", default=False)


def env_allows_active() -> bool:
    return os.environ.get(ENV_ALLOW_ACTIVE, "").strip().lower() in _TRUE


def active_enabled() -> bool:
    """True only when the operator opted in AND this context isn't forced passive."""
    return env_allows_active() and not _force_passive.get()


@contextmanager
def forced_passive(is_forced: bool = True) -> Iterator[None]:
    token = _force_passive.set(is_forced)
    try:
        yield
    finally:
        _force_passive.reset(token)


def set_forced_passive(is_forced: bool) -> contextvars.Token:
    return _force_passive.set(is_forced)


def is_forced_passive() -> bool:
    return _force_passive.get()


def is_tool_enabled(name: str) -> bool:
    """Whether a tool may be offered/run in the current mode. Unknown tools are not enabled."""
    policy = TOOL_POLICY.get(name)
    if policy is None:
        return False
    return policy.is_passive or active_enabled()


def label(name: str) -> str:
    """Short label such as ``[passive]`` or ``[noisy — off by default, needs --allow-active]``."""
    policy = TOOL_POLICY.get(name)
    if policy is None:
        return ""
    text = policy.noise.value
    if not policy.is_passive:
        text += " — off by default, needs --allow-active"
    elif policy.active_part:
        text += "; " + policy.active_part
    return f"[{text}]"


def describe(name: str, description: str) -> str:
    """Tool description with its noise label appended, for agents and MCP clients."""
    policy = TOOL_POLICY.get(name)
    if policy is None:
        return description
    return f"{description} {label(name)} {policy.note}"


def enable_hint() -> str:
    if is_forced_passive():
        return "Active tools are not available on this public/restricted instance."
    return (
        "Enable with --allow-active, OPENOSINT_ALLOW_ACTIVE=1, the web Settings toggle, "
        "or the MCP server's --allow-active option. Active tools are noisy and may leave traces "
        "in third-party and target logs."
    )


def disabled_result(name: str, detail: str = "") -> str:
    """Structured JSON string returned when a non-passive tool/mode is requested in passive mode."""
    policy = TOOL_POLICY.get(name)
    return json.dumps(
        {
            "status": "disabled_in_passive_mode",
            "tool": name,
            "noise": policy.noise.value if policy else "unknown",
            "reason": detail or (policy.note if policy else "Not a registered tool."),
            "how_to_enable": enable_hint(),
        }
    )


def filter_definitions(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tool definitions the current mode may offer, with the noise label in each description."""
    out = []
    for definition in definitions:
        name = definition.get("name", "")
        if not is_tool_enabled(name):
            continue
        out.append({**definition, "description": describe(name, definition.get("description", ""))})
    return out


_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def requires_active(name: str) -> Callable[[_F], _F]:
    """Decorator for async ``run_*_osint`` tools that are non-passive: the choke point
    every surface (CLI, web, MCP, cloud, playbooks, pivot) goes through."""

    def wrap(fn: _F) -> _F:
        @functools.wraps(fn)
        async def inner(*args: Any, **kwargs: Any) -> Any:
            if not is_tool_enabled(name):
                return disabled_result(name)
            return await fn(*args, **kwargs)

        return inner  # type: ignore[return-value]

    return wrap


# ---------------------------------------------------------------------------
# Tool-call budget
# ---------------------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= 1 else default


def max_tool_calls() -> int:
    return _int_env(ENV_MAX_CALLS, DEFAULT_MAX_CALLS)


def max_tool_calls_multi() -> int:
    return _int_env(ENV_MAX_CALLS_MULTI, DEFAULT_MAX_CALLS_MULTI)


@dataclass
class ToolBudget:
    """Mutable counter shared by everything one user request (or one multi run) may spend."""

    limit: int = field(default_factory=max_tool_calls)
    used: int = 0

    def try_consume(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    @property
    def is_exhausted(self) -> bool:
        return self.used >= self.limit

    def message(self) -> str:
        return (
            f"Tool call limit reached ({self.limit} calls for this request). Investigation stopped; "
            f"results so far are above. Send another message to continue, or raise "
            f"{ENV_MAX_CALLS} to allow more."
        )


_budget: contextvars.ContextVar[ToolBudget | None] = contextvars.ContextVar("openosint_budget", default=None)


def current_budget() -> ToolBudget | None:
    return _budget.get()


@contextmanager
def use_budget(budget: ToolBudget) -> Iterator[ToolBudget]:
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)
