# openosint/mcp_server.py
"""
OpenOSINT MCP Server — v2.23.0

Exposes all 20 OSINT tool capabilities plus multi-target investigation
to MCP-compliant AI clients over standard I/O. Tools include:
search_email, search_username, search_breach, search_whois, search_ip,
search_domain, generate_dorks, search_paste, search_phone, search_shodan,
search_virustotal, search_censys, search_ip2location, search_abuseipdb,
search_github, search_dns, search_gdelt_geo, search_dorks_live, scrape_url,
search_footprint.
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
from openosint.tools.scrape_url import run_scrape_url_osint
from openosint.tools.search_abuseipdb import run_abuseipdb_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_censys import run_censys_osint
from openosint.tools.search_dns import run_dns_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_dorks_live import run_dorks_live_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint, split_geojson_fence
from openosint.tools.search_github import run_github_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_ip2location import run_ip2location_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_virustotal import run_virustotal_osint
from openosint.tools.search_whois import run_whois_osint
from openosint.tools.search_footprint import run_footprint_osint

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
            name="search_gdelt_geo",
            description=(
                "Search worldwide, geolocated news coverage via the GDELT GEO 2.0 API. "
                "No API key required. Returns a text summary plus the raw GeoJSON "
                "FeatureCollection. Optionally scope to a bounding box."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "timespan": {
                            "type": "integer",
                            "description": "Lookback window in minutes (15-1440). Default 60.",
                        },
                        "maxpoints": {
                            "type": "integer",
                            "description": "Max point features to return (1-500). Default 250.",
                        },
                        "bbox": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 4,
                            "maxItems": 4,
                            "description": "[min_lon, min_lat, max_lon, max_lat]",
                        },
                    },
                    "required": ["query"],
                }
            ),
        ),
        Tool(
            name="search_dorks_live",
            description=(
                "Execute Google dork queries for a target via the Bright Data SERP API, "
                "returning live structured results (title, URL, snippet). "
                "Runs up to 5 dorks by default — each is a billable API call. "
                "Requires BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE env vars."
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
            name="scrape_url",
            description=(
                "Fetch any public URL through the Bright Data Web Unlocker API, bypassing "
                "Cloudflare, CAPTCHA, and bot-protection. Returns the page as clean Markdown. "
                "Requires BRIGHTDATA_API_KEY and BRIGHTDATA_UNLOCKER_ZONE env vars."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                }
            ),
        ),
        Tool(
            name="search_footprint",
            description=(
                "Collect a target's public search-engine footprint via the Bright Data SERP API. "
                "Detects entity type (email, username, domain, phone, or full name) and runs "
                "entity-type-aware Google queries, returning structured results and Entity "
                "Correlation Graph nodes/edges for discovered domains and profiles. "
                "Requires BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE env vars."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "max_queries": {
                            "type": "integer",
                            "description": "Max SERP queries (default 3, each is billable).",
                        },
                    },
                    "required": ["target"],
                }
            ),
        ),
        Tool(
            name="graph_export",
            description=(
                "Export the additive FollowTheMoney entity graph (openosint.graph) as "
                "newline-delimited JSON, one FtM entity per line (.ftm-compatible). "
                "Optionally exclude whole datasets, e.g. exclude_datasets=['openosint:hibp'] "
                "to omit every breach-derived fact. Requires the 'graph' extra: "
                "pip install 'openosint[graph]'."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {
                        "exclude_datasets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dataset names to omit entirely, e.g. ['openosint:hibp'].",
                        }
                    },
                }
            ),
        ),
        Tool(
            name="graph_neighbors",
            description=(
                "Traverse the FollowTheMoney entity graph from one entity id out to a given "
                "depth, returning entities, edges, and per-edge provenance (collection "
                "method, confidence, run id). Set cross_layer=true to also surface bridge "
                "links into the raw infra correlation graph (IPs, domains, hashes). "
                "Requires the 'graph' extra: pip install 'openosint[graph]'."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "depth": {
                            "type": "integer",
                            "description": "Hops to traverse (default 1, capped at 5).",
                        },
                        "cross_layer": {
                            "type": "boolean",
                            "description": "Include bridge links into the raw infra graph.",
                        },
                    },
                    "required": ["entity_id"],
                }
            ),
        ),
        Tool(
            name="graph_review_candidates",
            description=(
                "Human review queue for suggested same_as entity matches produced by "
                "graph-dedup cross-referencing. action='list' shows pending candidates "
                "(score, identifying properties, human-readable match explanation), "
                "filterable by schema/score range/dataset. action='decide' records a human "
                "verdict on one pair: decision='accept' merges it (judgement='positive'), "
                "decision='reject' permanently excludes it from future suggestions "
                "(judgement='negative'). Nothing in this project ever auto-merges — only "
                "this action can write judgement='positive'."
            ),
            inputSchema=_with_json(
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "decide"]},
                        "schema": {
                            "type": "string",
                            "enum": ["Person", "LegalEntity", "Organization", "UserAccount"],
                            "description": "list filter: restrict to one FtM schema.",
                        },
                        "min_score": {
                            "type": "number",
                            "description": "list filter: minimum score.",
                        },
                        "max_score": {
                            "type": "number",
                            "description": "list filter: maximum score.",
                        },
                        "dataset": {
                            "type": "string",
                            "description": "list filter: either entity must carry a statement from this dataset.",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "decide: first entity of the pair.",
                        },
                        "canonical_id": {
                            "type": "string",
                            "description": "decide: second entity of the pair.",
                        },
                        "decision": {"type": "string", "enum": ["accept", "reject"]},
                        "reviewer_id": {
                            "type": "string",
                            "description": "decide: reviewer identifier, recorded if given.",
                        },
                    },
                    "required": ["action"],
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
    "search_gdelt_geo": (
        lambda a: run_gdelt_geo_osint(
            a["query"],
            timeout_seconds=15,
            timespan=int(a.get("timespan", 60)),
            maxpoints=int(a.get("maxpoints", 250)),
            bbox=tuple(a["bbox"]) if a.get("bbox") else None,
        ),
        lambda a: a["query"],
    ),
    "search_dorks_live": (
        lambda a: run_dorks_live_osint(a["target"], timeout_seconds=30),
        lambda a: a["target"],
    ),
    "scrape_url": (
        lambda a: run_scrape_url_osint(a["url"], timeout_seconds=60),
        lambda a: a["url"],
    ),
    "search_footprint": (
        lambda a: run_footprint_osint(
            a["target"],
            max_queries=int(a.get("max_queries", 3)),
            timeout_seconds=30,
        ),
        lambda a: a["target"],
    ),
}


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    logger.info("Tool: %s | args: %s", name, arguments)
    should_use_json = bool(arguments.get("json_output", False))

    # Special handler for multi-target investigation
    if name == "investigate_multi":
        return await _call_investigate_multi(arguments)

    # Graph tools: dispatched separately (not via _HANDLERS) so that importing
    # openosint.graph.mcp_tools — and therefore followthemoney — happens ONLY
    # here, on first use of one of these three tools, never at module import
    # time. That keeps every other, unrelated MCP tool working even when the
    # `graph` extra is not installed.
    if name in _GRAPH_TOOL_NAMES:
        return await _call_graph_tool(name, arguments)

    try:
        if name not in _HANDLERS:
            raise ValueError(f"Unknown tool: '{name}'")
        handler, target_fn = _HANDLERS[name]
        result = await handler(arguments)
        # Claude Desktop and every other MCP client has no globe — the raw
        # FeatureCollection is pure waste here, strip it unconditionally.
        result, _ = split_geojson_fence(result)
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


_GRAPH_TOOL_NAMES = frozenset({"graph_export", "graph_neighbors", "graph_review_candidates"})


async def _call_graph_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    should_use_json = bool(arguments.get("json_output", False))
    try:
        from openosint.graph.mcp_tools import (
            run_graph_export,
            run_graph_neighbors,
            run_graph_review_candidates,
        )

        if name == "graph_export":
            result = await run_graph_export(exclude_datasets=arguments.get("exclude_datasets"))
            target = "graph-export"
        elif name == "graph_neighbors":
            result = await run_graph_neighbors(
                arguments["entity_id"],
                depth=int(arguments.get("depth", 1)),
                cross_layer=bool(arguments.get("cross_layer", False)),
            )
            target = arguments["entity_id"]
        else:
            result = await run_graph_review_candidates(
                arguments["action"],
                schema=arguments.get("schema"),
                min_score=arguments.get("min_score"),
                max_score=arguments.get("max_score"),
                dataset=arguments.get("dataset"),
                entity_id=arguments.get("entity_id"),
                canonical_id=arguments.get("canonical_id"),
                decision=arguments.get("decision"),
                reviewer_id=arguments.get("reviewer_id"),
            )
            target = arguments.get("entity_id", arguments["action"])

        text = to_json(name, target, result) if should_use_json else result
        return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)
    except ImportError as exc:
        message = (
            f"{name} requires the 'graph' extra (followthemoney), which is not installed in "
            f"this environment. Install it with: pip install 'openosint[graph]' ({exc})"
        )
        return CallToolResult(content=[TextContent(type="text", text=message)], isError=True)
    except (KeyError, ValueError) as exc:
        logger.error("Validation error in graph tool '%s': %s", name, exc)
        return CallToolResult(content=[TextContent(type="text", text=str(exc))], isError=True)
    except Exception as exc:
        logger.exception("Unhandled error in graph tool '%s'.", name)
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
