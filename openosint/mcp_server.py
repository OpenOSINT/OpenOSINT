# openosint/mcp_server.py
"""
OpenOSINT MCP Server — v2.19.0

Exposes all 17 OSINT tool capabilities plus multi-target investigation
to MCP-compliant AI clients over standard I/O. Tools include:
search_email, search_username, search_breach, search_whois, search_ip,
search_domain, generate_dorks, search_paste, search_phone, search_shodan,
search_virustotal, search_censys, search_ip2location, search_abuseipdb,
search_github, search_dns, search_sherlockeye.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from openosint.json_output import to_json
from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.search_abuseipdb import run_abuseipdb_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_censys import run_censys_osint
from openosint.tools.search_dns import run_dns_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_github import run_github_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_ip2location import run_ip2location_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_virustotal import run_virustotal_osint
from openosint.tools.search_sherlockeye import run_sherlockeye_osint
from openosint.tools.search_whois import run_whois_osint

logging.basicConfig(level=logging.INFO, format="[MCP] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
app = Server("openosint")

_JSON_PROP = {
    "json_output": {"type": "boolean", "description": "Return result as structured JSON."}
}


def _with_json(schema: dict) -> dict:
    """Return a copy of *schema* with the optional json_output property added."""
    props = dict(schema.get("properties", {}))
    props.update(_JSON_PROP)
    return {**schema, "properties": props}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_email",
            description="Enumerate accounts linked to an email using holehe.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                }
            ),
        ),
        Tool(
            name="search_username",
            description="Enumerate platforms where a username is registered using sherlock.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"username": {"type": "string"}},
                    "required": ["username"],
                }
            ),
        ),
        Tool(
            name="search_breach",
            description="Check if an email appears in data breaches via HaveIBeenPwned. Requires HIBP_API_KEY env var.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                }
            ),
        ),
        Tool(
            name="search_whois",
            description="Retrieve WHOIS registration data for a domain.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"domain": {"type": "string"}},
                    "required": ["domain"],
                }
            ),
        ),
        Tool(
            name="search_ip",
            description="Retrieve geolocation and ASN data for an IP address via ipinfo.io.",
            inputSchema=_with_json(
                {"type": "object", "properties": {"ip": {"type": "string"}}, "required": ["ip"]}
            ),
        ),
        Tool(
            name="search_domain",
            description="Enumerate subdomains of a target domain using sublist3r.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"domain": {"type": "string"}},
                    "required": ["domain"],
                }
            ),
        ),
        Tool(
            name="generate_dorks",
            description="Generate targeted Google dork URLs for any target (name, email, username, domain).",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                }
            ),
        ),
        Tool(
            name="search_paste",
            description="Search Pastebin dumps for an email or username via psbdmp.ws.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                }
            ),
        ),
        Tool(
            name="search_phone",
            description="Gather carrier and geolocation data for a phone number using phoneinfoga. Use E.164 format.",
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"phone": {"type": "string"}},
                    "required": ["phone"],
                }
            ),
        ),
        Tool(
            name="search_shodan",
            description=(
                "Query Shodan for host intelligence or banner search. "
                "IP address → host lookup (open ports, org, CVEs). "
                "Any other string → keyword/service search. "
                "Requires SHODAN_API_KEY env var."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                }
            ),
        ),
        Tool(
            name="search_virustotal",
            description=(
                "Check IP, domain, URL, or file hash against VirusTotal's 70+ antivirus "
                "engines and threat intelligence. Auto-detects input type. "
                "Requires VIRUSTOTAL_API_KEY env var."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                }
            ),
        ),
        Tool(
            name="search_censys",
            description=(
                "Search Censys for internet-facing infrastructure data. "
                "IP address → open ports, services, ASN, country. "
                "Domain → certificate history, SANs, issuer, first/last seen. "
                "Requires CENSYS_API_ID and CENSYS_SECRET env vars."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                }
            ),
        ),
        Tool(
            name="search_ip2location",
            description=(
                "Enhanced IP intelligence using IP2Location Security Plan. "
                "Returns geolocation, ISP, ASN, and detects VPN, proxy, Tor exit nodes, "
                "and datacenter hosting. Sponsored integration. "
                "Requires IP2LOCATION_API_KEY env var."
            ),
            inputSchema=_with_json(
                {"type": "object", "properties": {"ip": {"type": "string"}}, "required": ["ip"]}
            ),
        ),
        Tool(
            name="search_abuseipdb",
            description=(
                "Check an IP address against the AbuseIPDB v2 API for abuse reputation. "
                "Returns abuse confidence score (0–100%), total reports, country, ISP, domain, "
                "and last reported timestamp. Shows a warning when score exceeds 50%. "
                "Requires ABUSEIPDB_API_KEY env var."
            ),
            inputSchema=_with_json(
                {"type": "object", "properties": {"ip": {"type": "string"}}, "required": ["ip"]}
            ),
        ),
        Tool(
            name="search_github",
            description=(
                "Search GitHub for a username, email, or keyword. "
                "For exact username matches: returns full profile, recent repos, and emails "
                "discovered from commit history. For other queries: top 5 matching accounts. "
                "Optional GITHUB_TOKEN env var raises rate limit from 60 to 5000 req/h."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                }
            ),
        ),
        Tool(
            name="search_dns",
            description=(
                "Comprehensive DNS record enumeration (A, AAAA, MX, NS, TXT, CNAME, SOA). "
                "Highlights email security misconfigurations: missing SPF, weak SPF policy, "
                "missing or unenforced DMARC, and absent DKIM across common selectors. "
                "No external API or credentials required."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"domain": {"type": "string"}},
                    "required": ["domain"],
                }
            ),
        ),
        Tool(
            name="search_sherlockeye",
            description=(
                "Reverse Lookup & AI-Powered OSINT search via Sherlockeye for email, phone, username, "
                "domain, IP, name, CPF, or CNPJ. Accepts plain values (type inferred) or "
                "type:\"value\" syntax. Set deep_research=true for digital account expansion "
                "on email/phone/name. Requires SHERLOCKEYE_API_KEY env var."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "deep_research": {
                            "type": "boolean",
                            "description": "Enable digital_accounts_expansion module.",
                        },
                    },
                    "required": ["query"],
                }
            ),
        ),
        Tool(
            name="investigate_multi",
            description=(
                "Investigate multiple targets in parallel using the full OSINT tool chain. "
                "Each target gets its own report file. A summary report is also generated. "
                "Maximum 10 targets. Requires ANTHROPIC_API_KEY env var."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of OSINT targets (emails, usernames, domains, IPs). Max 10.",
                    }
                },
                "required": ["targets"],
            },
        ),
    ]


# Map tool name → (coroutine factory, target key for JSON export)
_HANDLERS: dict[str, tuple] = {
    "search_email": (
        lambda a: run_email_osint(a["email"], timeout_seconds=120),
        lambda a: a["email"],
    ),
    "search_username": (
        lambda a: run_username_osint(a["username"], timeout_seconds=180),
        lambda a: a["username"],
    ),
    "search_breach": (
        lambda a: run_breach_osint(a["email"], timeout_seconds=15),
        lambda a: a["email"],
    ),
    "search_whois": (
        lambda a: run_whois_osint(a["domain"], timeout_seconds=15),
        lambda a: a["domain"],
    ),
    "search_ip": (lambda a: run_ip_osint(a["ip"], timeout_seconds=10), lambda a: a["ip"]),
    "search_domain": (
        lambda a: run_domain_osint(a["domain"], timeout_seconds=120),
        lambda a: a["domain"],
    ),
    "generate_dorks": (lambda a: run_dork_osint(a["target"]), lambda a: a["target"]),
    "search_paste": (
        lambda a: run_paste_osint(a["query"], timeout_seconds=15),
        lambda a: a["query"],
    ),
    "search_phone": (
        lambda a: run_phone_osint(a["phone"], timeout_seconds=60),
        lambda a: a["phone"],
    ),
    "search_shodan": (
        lambda a: run_shodan_osint(a["query"], timeout_seconds=30),
        lambda a: a["query"],
    ),
    "search_virustotal": (
        lambda a: run_virustotal_osint(a["target"], timeout_seconds=30),
        lambda a: a["target"],
    ),
    "search_censys": (
        lambda a: run_censys_osint(a["target"], timeout_seconds=30),
        lambda a: a["target"],
    ),
    "search_ip2location": (
        lambda a: run_ip2location_osint(a["ip"], timeout_seconds=30),
        lambda a: a["ip"],
    ),
    "search_abuseipdb": (
        lambda a: run_abuseipdb_osint(a["ip"], timeout_seconds=30),
        lambda a: a["ip"],
    ),
    "search_github": (
        lambda a: run_github_osint(a["query"], timeout_seconds=30),
        lambda a: a["query"],
    ),
    "search_dns": (
        lambda a: run_dns_osint(a["domain"], timeout_seconds=10),
        lambda a: a["domain"],
    ),
    "search_sherlockeye": (
        lambda a: run_sherlockeye_osint(
            a["query"],
            timeout_seconds=120,
            deep_research=bool(a.get("deep_research", False)),
        ),
        lambda a: a["query"],
    ),
}


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    logger.info("Tool: %s | args: %s", name, arguments)
    should_use_json = bool(arguments.get("json_output", False))

    # Special handler for multi-target investigation
    if name == "investigate_multi":
        return await _call_investigate_multi(arguments)

    try:
        if name not in _HANDLERS:
            raise ValueError(f"Unknown tool: '{name}'")
        handler, target_fn = _HANDLERS[name]
        result = await handler(arguments)
        if should_use_json:
            target = target_fn(arguments)
            text = to_json(name, target, result)
        else:
            text = result
        return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)
    except (KeyError, ValueError) as exc:
        logger.error("Validation error: %s", exc)
        return CallToolResult(content=[TextContent(type="text", text=str(exc))], isError=True)
    except Exception as exc:
        logger.exception("Unhandled error in tool '%s'.", name)
        return CallToolResult(
            content=[TextContent(type="text", text=f"Internal error: {exc}")],
            isError=True,
        )


async def _call_investigate_multi(arguments: dict[str, Any]) -> CallToolResult:
    from openosint.multi_target import MAX_TARGETS, run_multi_target

    targets = arguments.get("targets", [])
    if not isinstance(targets, list) or not targets:
        return CallToolResult(
            content=[TextContent(type="text", text="'targets' must be a non-empty list.")],
            isError=True,
        )
    if len(targets) > MAX_TARGETS:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Too many targets ({len(targets)}). Maximum is {MAX_TARGETS}.",
                )
            ],
            isError=True,
        )
    try:
        summary = await run_multi_target(targets, is_pdf_disabled=True)
        return CallToolResult(content=[TextContent(type="text", text=summary)], isError=False)
    except Exception as exc:
        logger.exception("Error in investigate_multi.")
        return CallToolResult(
            content=[TextContent(type="text", text=f"Internal error: {exc}")],
            isError=True,
        )


async def _serve() -> None:
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
