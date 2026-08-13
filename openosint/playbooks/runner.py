# openosint/playbooks/runner.py
"""Execute a playbook Recipe against a target and write a branded Markdown/PDF report."""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable

from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_dns import run_dns_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_footprint import run_footprint_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_virustotal import run_virustotal_osint
from openosint.tools.search_whois import run_whois_osint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_MAP: dict[str, Callable[..., Awaitable[str]]] = {
    "search_whois": run_whois_osint,
    "search_dns": run_dns_osint,
    "generate_dorks": run_dork_osint,
    "search_domain": run_domain_osint,
    "search_footprint": run_footprint_osint,
    "search_email": run_email_osint,
    "search_breach": run_breach_osint,
    "search_ip": run_ip_osint,
    "search_shodan": run_shodan_osint,
    "search_virustotal": run_virustotal_osint,
    "search_paste": run_paste_osint,
    "search_username": run_username_osint,
    "search_phone": run_phone_osint,
}

# ---------------------------------------------------------------------------
# Tool requirements
# Each entry: (env_vars, binaries, optional_note)
# An empty list means "no requirement — always available".
# ---------------------------------------------------------------------------

_Req = tuple[list[str], list[str], str | None]

TOOL_REQUIREMENTS: dict[str, _Req] = {
    "search_whois": ([], [], None),
    "search_dns": ([], [], None),
    "generate_dorks": ([], [], None),
    "search_domain": ([], ["sublist3r"], None),
    "search_footprint": (
        ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"],
        [],
        "Sign up at brightdata.com to obtain your API key and SERP zone.",
    ),
    "search_email": ([], ["holehe"], None),
    "search_breach": (["HIBP_API_KEY"], [], None),
    "search_ip": ([], [], None),
    "search_shodan": (["SHODAN_API_KEY"], [], None),
    "search_virustotal": (["VIRUSTOTAL_API_KEY"], [], None),
    "search_paste": ([], [], None),
    "search_username": ([], ["sherlock"], None),
    "search_phone": ([], ["phoneinfoga"], None),
}

# ---------------------------------------------------------------------------
# Step state
# ---------------------------------------------------------------------------


class StepState(Enum):
    NOT_CONFIGURED = "not_configured"
    INVALID_INPUT = "invalid_input"
    EMPTY = "empty"
    ERROR = "error"
    SUCCESS = "success"


# ---------------------------------------------------------------------------
# Self-caught error detection
# Tools like run_paste_osint / run_email_osint catch their own exceptions and
# return error strings rather than raising.  These prefixes / phrases identify
# those strings so _run_step can assign the correct state instead of SUCCESS.
# ---------------------------------------------------------------------------

_TOOL_ERROR_PREFIXES: tuple[str, ...] = (
    "Scan error:",
    "Internal error:",
    "Network error:",
    "Connection error:",
    "Tool error:",
)

# "please enter" catches holehe's "Please enter a target email !" message.
_INVALID_INPUT_MARKERS: tuple[str, ...] = ("please enter",)


def _looks_like_invalid_input(output: str) -> bool:
    return any(marker in output.lower() for marker in _INVALID_INPUT_MARKERS)


def _looks_like_tool_error(output: str) -> bool:
    stripped = output.strip()
    return any(stripped.startswith(prefix) for prefix in _TOOL_ERROR_PREFIXES)


# ---------------------------------------------------------------------------
# Requirements check
# ---------------------------------------------------------------------------


def _missing_requirements(tool: str) -> tuple[list[str], str | None]:
    """Return (list_of_missing_items, optional_note) for *tool*."""
    env_vars, binaries, note = TOOL_REQUIREMENTS.get(tool, ([], [], None))
    missing: list[str] = []
    for var in env_vars:
        if not os.environ.get(var):
            missing.append(var)
    for binary in binaries:
        if shutil.which(binary) is None:
            missing.append(binary)
    return missing, note


# ---------------------------------------------------------------------------
# Per-step execution
# ---------------------------------------------------------------------------


async def _run_step(tool: str, target: str) -> tuple[StepState, object]:
    """Run a single tool step.  Never raises."""
    missing, _note = _missing_requirements(tool)
    if missing:
        return StepState.NOT_CONFIGURED, ""

    try:
        output = await TOOL_MAP[tool](target)  # type: ignore[call-arg]
    except Exception as exc:
        logger.debug("Step '%s' raised: %s", tool, exc)
        return StepState.ERROR, str(exc)

    if not output:
        return StepState.EMPTY, ""
    if isinstance(output, str) and not output.strip():
        return StepState.EMPTY, ""

    if isinstance(output, str):
        if _looks_like_invalid_input(output):
            return StepState.INVALID_INPUT, output
        if _looks_like_tool_error(output):
            return StepState.ERROR, output

    return StepState.SUCCESS, output


# ---------------------------------------------------------------------------
# Output formatters — strip console prefixes, render clean Markdown
# ---------------------------------------------------------------------------


def _parse_dns_bullets(output: str, header: str) -> list[str]:
    """Extract '  • item' lines from a '[DNS] header:' section."""
    items: list[str] = []
    in_section = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(header):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("• "):  # •
                items.append(stripped[2:])
            elif stripped.startswith("[DNS]") or (stripped and not line.startswith(" ")):
                break
    return items


def _format_whois(output: str) -> str:
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[+] ") and ": " in stripped:
            content = stripped[4:]
            key, _, value = content.partition(": ")
            rows.append((key.strip(), value.strip()))
    if not rows:
        return f"```\n{output.strip()}\n```"
    lines = ["| Field | Value |", "|---|---|"]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _format_dns(output: str) -> str:
    sections: list[str] = []

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[DNS] A: "):
            ips = [ip.strip() for ip in stripped[9:].split(",") if ip.strip()]
            if ips:
                t = ["**A Records**", "", "| IP Address |", "|---|"]
                t.extend(f"| `{ip}` |" for ip in ips)
                sections.append("\n".join(t))
        elif stripped.startswith("[DNS] AAAA: "):
            ips = [ip.strip() for ip in stripped[12:].split(",") if ip.strip()]
            if ips:
                t = ["**AAAA Records**", "", "| IPv6 Address |", "|---|"]
                t.extend(f"| `{ip}` |" for ip in ips)
                sections.append("\n".join(t))
        elif stripped.startswith("[DNS] NS: "):
            nss = [ns.strip().rstrip(".") for ns in stripped[10:].split(",") if ns.strip()]
            if nss:
                t = ["**NS Records**", "", "| Nameserver |", "|---|"]
                t.extend(f"| `{ns}` |" for ns in nss)
                sections.append("\n".join(t))

    mx_items = _parse_dns_bullets(output, "[DNS] MX records:")
    if mx_items:
        t = ["**MX Records**", "", "| Priority | Host |", "|---|---|"]
        for item in mx_items:
            parts = item.split(None, 1)
            priority = parts[0] if len(parts) == 2 else "—"
            host = parts[1] if len(parts) == 2 else item
            t.append(f"| {priority} | `{host}` |")
        sections.append("\n".join(t))

    email_lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[DNS] SPF:"):
            email_lines.append(f"- **SPF:** `{stripped[10:].strip()}`")
        elif stripped.startswith("[DNS] DMARC:"):
            dmarc_raw = stripped[12:].strip().strip('"')
            email_lines.append(f"- **DMARC:** `{dmarc_raw}`")
    if email_lines:
        sections.append("**Email Security**\n\n" + "\n".join(email_lines))

    dkim_items = _parse_dns_bullets(output, "[DNS] DKIM selectors found:")
    if dkim_items:
        t = ["**DKIM Selectors**", "", "| Selector | Status |", "|---|---|"]
        for item in dkim_items:
            col_idx = item.find(":")
            if col_idx > 0:
                sel = item[:col_idx].strip()
                rest = item[col_idx + 1:].strip()
                m = re.search(r"p=([^\s;]*)", rest)
                status = "Revoked / not published" if (m and not m.group(1)) else "Active"
            else:
                sel, status = item, "Unknown"
            t.append(f"| `{sel}` | {status} |")
        sections.append("\n".join(t))

    txt_items = _parse_dns_bullets(output, "[DNS] TXT (other):")
    if txt_items:
        t = ["**TXT Records**"]
        t.extend(f"- `{item}`" for item in txt_items)
        sections.append("\n".join(t))

    return "\n\n".join(sections) if sections else f"```\n{output.strip()}\n```"


def _format_dorks(output: str) -> str:
    dorks: list[tuple[str, str]] = []
    lines = output.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("[+] "):
            query = stripped[4:]
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().startswith("http"):
                dorks.append((query, lines[j].strip()))
                i = j + 1
                continue
        i += 1
    if not dorks:
        return f"```\n{output.strip()}\n```"
    return "\n".join(f"{idx}. [{q}]({u})" for idx, (q, u) in enumerate(dorks, 1))


def _format_subdomains(output: str) -> str:
    subs = [
        line.strip()[4:]
        for line in output.splitlines()
        if line.strip().startswith("[+] ") and "." in line.strip()[4:]
    ]
    if not subs:
        return f"```\n{output.strip()}\n```"
    t = ["| Subdomain |", "|---|"]
    t.extend(f"| `{s}` |" for s in subs)
    return "\n".join(t)


def _format_footprint(output: object) -> str:
    if isinstance(output, dict):
        if output.get("error"):
            return f"```\n{output['error']}\n```"
            
        urls = output.get("discovered_urls", [])
        if not urls:
            return "No results found."
            
        rendered: list[str] = []
        if output.get("queries"):
            rendered.append(f"**Queries Run: {output.get('queries', 0)}**\n")
            
        for i, url in enumerate(urls, 1):
            rendered.append(f"{i}. **[{url}]({url})**")
            
        return "\n".join(rendered).rstrip()
        
    if not isinstance(output, str):
        return f"```\n{output}\n```"

    query_blocks: list[tuple[str, list[dict]]] = []
    current_query: str | None = None
    current_results: list[dict] = []
    current_result: dict | None = None

    for line in output.splitlines():
        # Stop before the Discovered URLs block
        if "[Footprint] URL:" in line or "[Footprint] Domain:" in line:
            break

        stripped = line.strip()

        # Skip the header summary line
        if stripped.startswith("[Footprint]") and "|" in stripped:
            continue

        # New query block
        if stripped.startswith("[+] Query "):
            if current_query is not None:
                if current_result:
                    current_results.append(current_result)
                    current_result = None
                query_blocks.append((current_query, current_results))
                current_results = []
            _, _, rest = stripped.partition(": ")
            current_query = rest.strip() or stripped
            continue

        # Result entry: "    N. Title"
        m = re.match(r"^\s+(\d+)\.\s+(.+)$", line)
        if m and current_query is not None:
            if current_result:
                current_results.append(current_result)
            current_result = {
                "title": m.group(2).strip(),
                "url": "",
                "display": "",
                "snippet": "",
            }
            continue

        # Field lines within a result
        if current_result is not None:
            if stripped.startswith("URL:"):
                current_result["url"] = stripped[4:].strip()
            elif stripped.startswith("Display:"):
                current_result["display"] = stripped[8:].strip()
            elif stripped.startswith("Snippet:"):
                raw = stripped[8:].strip()
                current_result["snippet"] = re.sub(
                    r"\s*(Read more|Learn more\.?)\s*$", "", raw, flags=re.IGNORECASE
                ).strip()

    # Flush last query
    if current_query is not None:
        if current_result:
            current_results.append(current_result)
        query_blocks.append((current_query, current_results))

    if not query_blocks:
        return f"```\n{output.strip()}\n```"

    rendered = []
    counter = 0
    for query_text, results in query_blocks:
        rendered.append(f"**Query: `{query_text}`**")
        rendered.append("")
        if not results:
            rendered.append("*No results.*")
            rendered.append("")
            continue
        for r in results:
            counter += 1
            title = r["title"] or "Untitled"
            url, display, snippet = r["url"], r["display"], r["snippet"]
            link = f"[{title}]({url})" if url else title
            rendered.append(f"{counter}. **{link}**  ")
            if display and snippet:
                rendered.append(f"   `{display}` — {snippet}")
            elif display:
                rendered.append(f"   `{display}`")
            elif snippet:
                rendered.append(f"   {snippet}")
            rendered.append("")

    return "\n".join(rendered).rstrip()


def _format_ip_info(output: str) -> str:
    """Render ipinfo.io output ([+] Key: Value) as a Markdown table."""
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[+] ") and ": " in stripped:
            content = stripped[4:]
            key, _, value = content.partition(": ")
            rows.append((key.strip(), value.strip()))
    if not rows:
        return f"```\n{output.strip()}\n```"
    lines = ["| Field | Value |", "|---|---|"]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _format_virustotal(output: str) -> str:
    """Render [VirusTotal] Key: Value lines as a Markdown table."""
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[VirusTotal] ") and ": " in stripped:
            content = stripped[len("[VirusTotal] "):]
            key, _, value = content.partition(": ")
            rows.append((key.strip(), value.strip()))
    if not rows:
        return f"```\n{output.strip()}\n```"
    lines = ["| Field | Value |", "|---|---|"]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _format_paste(output: str) -> str:
    """Render psbdmp paste results as a numbered link list."""
    stripped = output.strip()
    if not stripped or stripped.startswith("No pastes found"):
        return "*No paste-site mentions found.*"
    links: list[str] = []
    header: str = ""
    for line in output.splitlines():
        s = line.strip()
        if s.startswith("Found in "):
            header = s
        elif s.startswith("[+] http"):
            url_date = s[4:].strip()
            url, _, date = url_date.partition(" (")
            date = date.rstrip(")")
            label = date if date else url
            links.append(f"[{label}]({url.strip()})")
    if not links:
        return f"```\n{stripped}\n```"
    result: list[str] = []
    if header:
        result.append(f"**{header}**")
        result.append("")
    result.extend(f"{i}. {link}" for i, link in enumerate(links, 1))
    return "\n".join(result)


def _format_username(output: str) -> str:
    """Render sherlock [+] Platform: URL output as a Markdown table."""
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[+] ") and ": http" in stripped:
            content = stripped[4:]
            platform, _, url = content.partition(": ")
            if url.startswith("http"):
                rows.append((platform.strip(), url.strip()))
    if not rows:
        return f"```\n{output.strip()}\n```"
    lines = ["| Platform | Profile URL |", "|---|---|"]
    for platform, url in rows:
        lines.append(f"| {platform} | [{url}]({url}) |")
    return "\n".join(lines)


def _format_holehe(output: str) -> str:
    """Render holehe [+] platform lines as a bullet list of found registrations."""
    found: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("[+] "):
            platform = stripped[4:].strip()
            if platform:
                host = platform if "." in platform else f"{platform}.com"
                found.append(f"- [{host}](https://{host})")
    if not found:
        return "*No registered accounts found.*"
    return "\n".join(found)


def _format_step_output(tool_name: str, output: object) -> str:
    """Dispatch to a tool-specific Markdown formatter, falling back to fenced code."""
    if tool_name == "search_whois":
        return _format_whois(output)  # type: ignore
    if tool_name == "search_dns":
        return _format_dns(output)  # type: ignore
    if tool_name == "generate_dorks":
        return _format_dorks(output)  # type: ignore
    if tool_name == "search_domain":
        return _format_subdomains(output)  # type: ignore
    if tool_name == "search_footprint":
        return _format_footprint(output)
    if tool_name == "search_ip":
        return _format_ip_info(output)  # type: ignore
    if tool_name == "search_virustotal":
        return _format_virustotal(output)  # type: ignore
    if tool_name == "search_paste":
        return _format_paste(output)  # type: ignore
    if tool_name == "search_username":
        return _format_username(output)  # type: ignore
    if tool_name == "search_email":
        return _format_holehe(output)  # type: ignore
    
    if isinstance(output, str):
        return f"```\n{output.strip()}\n```"
    import json
    return f"```json\n{json.dumps(output, indent=2)}\n```"


# ---------------------------------------------------------------------------
# Rule-based Observations (deterministic, no LLM)
# ---------------------------------------------------------------------------

_CDN_PATTERNS: list[tuple[str, str]] = [
    ("cloudflare.com", "Cloudflare"),
    ("awsdns", "Amazon Route 53"),
    ("googledomains.com", "Google Domains"),
    ("akam.net", "Akamai"),
    ("fastly.net", "Fastly"),
]


def _build_observations(
    step_results: list[tuple[str, str, StepState, str]],
) -> str:
    """Return Markdown bullet observations derived from step data, or '' if none apply."""
    dns_out = ""
    whois_out = ""
    for _sid, tool, state, output in step_results:
        if state == StepState.SUCCESS:
            if tool == "search_dns":
                dns_out = output
            elif tool == "search_whois":
                whois_out = output

    notes: list[str] = []

    # ── Email security posture ──────────────────────────────────────────────
    spf_val = ""
    dmarc_val = ""
    for line in dns_out.splitlines():
        s = line.strip()
        if s.startswith("[DNS] SPF:"):
            spf_val = s.split("[DNS] SPF:", 1)[1].strip()
        elif s.startswith("[DNS] DMARC:"):
            dmarc_val = s.split("[DNS] DMARC:", 1)[1].strip().strip('"')

    if spf_val or dmarc_val:
        parts: list[str] = []
        if spf_val:
            m = re.search(r"([+\-~?])all", spf_val)
            qualifier = m.group(1) if m else "?"
            label = {
                "-": "hard fail",
                "~": "soft fail",
                "+": "permissive — spoofing risk",
                "?": "neutral",
            }.get(qualifier, "unknown")
            parts.append(f"SPF `{spf_val}` ({label})")
        else:
            parts.append("no SPF record")

        if dmarc_val:
            pm = re.search(r"p=(\w+)", dmarc_val)
            policy = pm.group(1) if pm else "unknown"
            parts.append(f"DMARC `p={policy}`")
        else:
            parts.append("no DMARC record")

        summary = " + ".join(parts)
        if "-all" in spf_val and re.search(r"p=reject", dmarc_val):
            summary += " → strict reject policy"
        elif not spf_val or not dmarc_val:
            summary += " → email spoofing may be possible"
        notes.append(f"**Email security:** {summary}")

    # ── DKIM selectors ──────────────────────────────────────────────────────
    dkim_items = _parse_dns_bullets(dns_out, "[DNS] DKIM selectors found:")
    if dkim_items:
        empty = sum(
            1
            for item in dkim_items
            if (dm := re.search(r"p=([^\s;]*)", item)) and not dm.group(1)
        )
        active = len(dkim_items) - empty
        total = len(dkim_items)
        if empty == total:
            notes.append(
                f"**DKIM selectors:** {total} probed — "
                "all returned empty `p=` (revoked or not published)"
            )
        elif empty:
            notes.append(
                f"**DKIM selectors:** {total} probed — "
                f"{empty} revoked (empty `p=`), {active} active"
            )
        else:
            notes.append(f"**DKIM selectors:** {active} active")

    # ── CDN / proxy detection ───────────────────────────────────────────────
    cdn_found: str | None = None
    for line in (dns_out + "\n" + whois_out).splitlines():
        s = line.strip()
        if "[DNS] NS:" in s or "[+] Name Servers:" in s:
            ns_part = s.split(":", 1)[1].lower() if ":" in s else ""
            for pattern, cdn_label in _CDN_PATTERNS:
                if pattern in ns_part:
                    cdn_found = cdn_label
                    break
        if cdn_found:
            break
    if cdn_found:
        notes.append(f"**CDN / proxy:** Nameservers indicate {cdn_found}")

    # ── Domain age ─────────────────────────────────────────────────────────
    for line in whois_out.splitlines():
        if "[+] Created:" in line:
            created_str = line.split("[+] Created:", 1)[1].strip()[:10]
            try:
                from datetime import date

                created = date.fromisoformat(created_str)
                today = datetime.now(timezone.utc).date()
                age_days = (today - created).days
                age_years = age_days // 365
                if age_years >= 2:
                    notes.append(
                        f"**Domain age:** registered {created.strftime('%Y-%m-%d')} "
                        f"({age_years} years old)"
                    )
                elif age_days < 180:
                    notes.append(
                        f"**Domain age:** registered {created.strftime('%Y-%m-%d')} "
                        f"({age_days} days ago — recently registered)"
                    )
                else:
                    notes.append(
                        f"**Domain age:** registered {created.strftime('%Y-%m-%d')}"
                    )
            except ValueError:
                pass
            break

    return "\n".join(f"- {note}" for note in notes)


# ---------------------------------------------------------------------------
# Executive summary (via EXTRACTOR_REGISTRY — no ad-hoc regex)
# ---------------------------------------------------------------------------


def _build_summary(
    target: str,
    recipe_target_type: str,
    step_results: list[tuple[str, str, StepState, object]],
) -> str:
    from openosint.correlation import EntityType, make_entity
    from openosint.extractors import EXTRACTOR_REGISTRY

    _TYPE_MAP: dict[str, EntityType] = {
        "domain": EntityType.DOMAIN,
        "email": EntityType.EMAIL,
        "ip": EntityType.IP,
        "username": EntityType.USERNAME,
        "phone": EntityType.PHONE,
        "url": EntityType.URL,
        "hash": EntityType.HASH,
        "person": EntityType.PERSON,
    }
    seed_type = _TYPE_MAP.get(recipe_target_type, EntityType.DOMAIN)
    seed = make_entity(seed_type, target, 1.0, "playbook")

    completed = sum(1 for _, _, state, _ in step_results if state == StepState.SUCCESS)
    skipped_nc = sum(1 for _, _, state, _ in step_results if state == StepState.NOT_CONFIGURED)
    skipped_inv = sum(1 for _, _, state, _ in step_results if state == StepState.INVALID_INPUT)
    total = len(step_results)

    # Extract entities per tool so each count can be attributed to its source
    tool_entities: dict[str, dict[EntityType, set[str]]] = {}
    for _step_id, tool_name, state, output in step_results:
        if state != StepState.SUCCESS:
            continue
        extractor = EXTRACTOR_REGISTRY.get(tool_name)
        if extractor is None:
            continue
        entities, _ = extractor(output, seed)
        bucket = tool_entities.setdefault(tool_name, {})
        for entity in entities:
            bucket.setdefault(entity.type, set()).add(entity.value)

    lines: list[str] = []
    skip_parts: list[str] = []
    if skipped_nc:
        skip_parts.append(f"{skipped_nc} skipped — not configured")
    if skipped_inv:
        skip_parts.append(f"{skipped_inv} not applicable")
    skip_note = f" ({', '.join(skip_parts)})" if skip_parts else ""
    lines.append(f"- **Steps completed:** {completed}/{total}{skip_note}")

    # Subdomains: only enumeration step — not WHOIS nameservers
    subs = len(tool_entities.get("search_domain", {}).get(EntityType.DOMAIN, set()))
    if subs:
        lines.append(f"- **Subdomains of target:** {subs}")

    # IPs: from DNS A/AAAA records
    ips = len(tool_entities.get("search_dns", {}).get(EntityType.IP, set()))
    if ips:
        lines.append(f"- **IP addresses found:** {ips}")

    # Registrant emails: from WHOIS
    emails = len(tool_entities.get("search_whois", {}).get(EntityType.EMAIL, set()))
    if emails:
        lines.append(f"- **Registrant emails:** {emails}")

    # SERP results: from footprint (separate URL vs domain counts)
    serp_urls = len(tool_entities.get("search_footprint", {}).get(EntityType.URL, set()))
    if serp_urls:
        lines.append(f"- **SERP URLs found:** {serp_urls}")

    related = len(tool_entities.get("search_footprint", {}).get(EntityType.DOMAIN, set()))
    if related:
        lines.append(f"- **Related domains in search results:** {related}")

    # ISP/org from IP geolocation
    ip_orgs = len(tool_entities.get("search_ip", {}).get(EntityType.ORG, set()))
    if ip_orgs:
        lines.append(f"- **ISP / Hosting org:** {ip_orgs}")

    # ASN — union of search_ip and search_virustotal (deduplicated by value)
    ip_asns = len(
        tool_entities.get("search_ip", {}).get(EntityType.ASN, set())
        | tool_entities.get("search_virustotal", {}).get(EntityType.ASN, set())
    )
    if ip_asns:
        lines.append(f"- **ASNs identified:** {ip_asns}")

    # Hostnames from Shodan
    shodan_hostnames = len(
        tool_entities.get("search_shodan", {}).get(EntityType.DOMAIN, set())
    )
    if shodan_hostnames:
        lines.append(f"- **Hostnames from Shodan:** {shodan_hostnames}")

    # Platform accounts from sherlock
    accounts = len(tool_entities.get("search_username", {}).get(EntityType.URL, set()))
    if accounts:
        lines.append(f"- **Platform accounts found:** {accounts}")

    # Registered platforms from holehe
    registered = len(tool_entities.get("search_email", {}).get(EntityType.URL, set()))
    if registered:
        lines.append(f"- **Email registrations found:** {registered}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------


def _build_report(
    recipe_label: str,
    recipe_name: str,
    target_type: str,
    target: str,
    date_str: str,
    step_results: list[tuple[str, str, StepState, object]],
    summary: str,
    observations: str,
    steps_map: dict[str, tuple[str, str]],
) -> str:
    lines: list[str] = [
        f"# {recipe_label} — {target}",
        "",
        f"**Target:** {target}  ",
        f"**Target type:** {target_type}  ",
        f"**Date:** {date_str}  ",
        f"**Recipe:** {recipe_name}  ",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        summary,
        "",
        "---",
        "",
    ]

    if observations:
        lines += [
            "## Observations",
            "",
            observations,
            "",
            "---",
            "",
        ]

    for step_id, tool_name, state, output in step_results:
        section, _ = steps_map[step_id]
        lines.append(f"## {section}")
        lines.append("")

        if state == StepState.SUCCESS:
            lines.append(_format_step_output(tool_name, output))
        elif state == StepState.NOT_CONFIGURED:
            missing, note = _missing_requirements(tool_name)
            missing_str = " and ".join(missing)
            lines.append(f"> ℹ️ Skipped — set {missing_str} to enable this section.")
            if note:
                lines.append(f"> {note}")
        elif state == StepState.INVALID_INPUT:
            lines.append("> ℹ️ Not applicable for this target type.")
        elif state == StepState.EMPTY:
            lines.append("> No results found.")
        else:
            lines.append(f"> ⚠ Step error: {output}")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_playbook(
    recipe: "Recipe",  # type: ignore[name-defined]  # noqa: F821
    target: str,
    is_pdf_disabled: bool = False,
    reports_dir: Path | None = None,
) -> Path:
    """
    Execute *recipe* against *target*.

    Returns the Path to the written Markdown report.  Individual step failures
    (tool errors, missing keys/binaries) are always captured in the report and
    never propagate.  Raises ``OSError`` only when the reports directory cannot
    be created or the report file cannot be written — the caller is responsible
    for handling filesystem-level errors.
    """
    from openosint.playbooks.loader import Recipe  # local import to avoid circular

    reports_path = reports_dir or Path("reports")
    try:
        reports_path.mkdir(exist_ok=True)
    except OSError as exc:
        raise OSError(
            f"Cannot create reports directory '{reports_path}': {exc}"
        ) from exc

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe_target = "".join(c if c.isalnum() or c in "-_." else "_" for c in target)
    md_path = reports_path / f"{date_prefix}_{safe_target}_{recipe.name}_report.md"

    steps_map: dict[str, tuple[str, str]] = {
        step.id: (step.section, step.tool) for step in recipe.steps
    }

    step_results: list[tuple[str, str, StepState, str]] = []
    for step in recipe.steps:
        logger.info("Playbook '%s': running step '%s' (%s)", recipe.name, step.id, step.tool)
        state, output = await _run_step(step.tool, target)
        step_results.append((step.id, step.tool, state, output))

    summary = _build_summary(target, recipe.target_type, step_results)
    observations = _build_observations(step_results)
    report_md = _build_report(
        recipe_label=recipe.label,
        recipe_name=recipe.name,
        target_type=recipe.target_type,
        target=target,
        date_str=date_str,
        step_results=step_results,
        summary=summary,
        observations=observations,
        steps_map=steps_map,
    )

    try:
        md_path.write_text(report_md, encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot write report to '{md_path}': {exc}") from exc

    logger.info("Playbook report written: %s", md_path)

    if not is_pdf_disabled:
        try:
            from openosint.pdf_report import generate_pdf_report

            await generate_pdf_report(md_path)
        except Exception:
            logger.debug("PDF generation skipped.", exc_info=True)

    return md_path
