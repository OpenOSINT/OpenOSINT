#!/usr/bin/env python3
"""
openosint_demo.py — VHS demo driver for OpenOSINT v2.18.0.
Produces Rich-formatted terminal output for each demo scene.
Driven by openosint.tape via stdin injection.
"""
import sys
import time

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console(highlight=False)

_TOOLS: list[tuple[str, str, str, bool]] = [
    ("generate_dorks",     "built-in",        "Google dork URL generator",               True),
    ("search_email",       "holehe",           "Social accounts linked to an email",      True),
    ("search_username",    "sherlock",         "Accounts across 300+ platforms",          True),
    ("search_breach",      "HaveIBeenPwned",   "Data breach exposure",                    True),
    ("search_whois",       "python-whois",     "Domain registrant info",                  True),
    ("search_ip",          "ipinfo.io",        "Geolocation, ASN, hostname",              True),
    ("search_domain",      "sublist3r",        "Subdomain enumeration",                   True),
    ("search_paste",       "psbdmp.ws",        "Pastebin dump mentions",                  True),
    ("search_phone",       "phoneinfoga",      "Carrier, country, line type",             True),
    ("search_shodan",      "Shodan API",       "Open ports, banners, CVEs",               True),
    ("search_virustotal",  "VirusTotal API",   "Malware intel — 70+ AV engines",          True),
    ("search_censys",      "Censys API",       "Certificates, ports, infrastructure",     True),
    ("search_ip2location", "IP2Location.io",   "Geoloc + VPN/Proxy/Tor  (sponsored)",    True),
    ("search_abuseipdb",   "AbuseIPDB API",    "Abuse reputation, confidence score",      True),
    ("search_sherlockeye", "Sherlockeye API",  "Reverse Lookup & AI-Powered OSINT",              True),
]


def _banner() -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold #00ff88]OpenOSINT[/] [dim]v2.18.0[/]  [dim]·[/]"
            "  [dim]Provider: Anthropic (claude-sonnet-4-20250514)[/]",
            border_style="#1e293b",
            padding=(0, 2),
        )
    )
    console.print(
        "  Type a target or question. [dim]'help'[/] for commands."
        " [dim]'exit'[/] to quit.\n"
    )


def _tools_table() -> None:
    tbl = Table(
        box=box.SIMPLE_HEAD,
        border_style="#1e293b",
        header_style="bold #00ff88",
        show_header=True,
        padding=(0, 1),
    )
    tbl.add_column("Tool",   style="#f1f5f9", no_wrap=True)
    tbl.add_column("Method", style="dim",     no_wrap=True)
    tbl.add_column("Finds",  style="#94a3b8")
    tbl.add_column("",       style="",        no_wrap=True, justify="right")
    for name, method, finds, ready in _TOOLS:
        status = "[bold green]✓[/]" if ready else "[red]✗[/]"
        tbl.add_row(name, method, finds, status)
    console.print()
    console.print(tbl)
    console.print()


def _show_prompt() -> None:
    sys.stdout.write("\033[1;32mopenosint\033[0m \033[32m❯\033[0m ")
    sys.stdout.flush()


def _dispatch(name: str, args: str, result: str) -> None:
    """Print a tool dispatch line, pause 400ms, print the result, pause 900ms."""
    console.print(f"  [dim]→[/] [#00ff88]{name}[/][dim]({args})[/]")
    time.sleep(0.4)
    console.print(f"    [dim]✓ {result}[/]")
    time.sleep(0.9)


def _scene_investigate() -> None:
    console.print()
    console.print("  [dim]Thinking...[/]")
    time.sleep(0.5)

    _dispatch("generate_dorks",  "target='target@example.com'", "12 dork URLs generated")
    _dispatch("search_email",    "email='target@example.com'",  "Found: Spotify, WordPress, Gravatar, Office365")
    _dispatch("search_breach",   "email='target@example.com'",  "2 breaches: LinkedIn (2016), Adobe (2013)")
    _dispatch("search_username", "username='targetuser'",       "12 accounts found across platforms")
    _dispatch("search_paste",    "query='target@example.com'",  "3 paste references found")

    report = """\
## Summary

**Target:** target@example.com
**Confidence:** High — single identity confirmed

---

## Online Presence

Found 12 registered accounts via username `targetuser`:

| Platform   | URL                                    |
|------------|----------------------------------------|
| Spotify    | open.spotify.com/user/targetuser       |
| WordPress  | targetuser.wordpress.com               |
| Gravatar   | gravatar.com/targetuser                |
| Office365  | email address in active use            |
| GitHub     | github.com/targetuser                  |
| Reddit     | reddit.com/u/targetuser                |
| Twitter/X  | twitter.com/targetuser                 |

---

## Breach Exposure

Found in **2 breach(es)**:

| Breach   | Date       | Leaked Data                         |
|----------|------------|-------------------------------------|
| LinkedIn | 2016-05-17 | Email addresses, Passwords          |
| Adobe    | 2013-10-04 | Email addresses, Passwords, Names   |

**Recommendation:** Credential rotation advised for all reused passwords.

---

## Paste Exposure

3 paste references found on psbdmp.ws — review manually for leaked credentials.
"""
    console.print()
    console.print(Panel(Markdown(report), border_style="#00ff88", padding=(1, 2)))
    console.print()
    console.print("  [dim]✓ Report saved → reports/2026-05-25_target_example_com.md[/]")
    console.print("  [dim]✓ PDF saved     → reports/2026-05-25_target_example_com.pdf[/]")
    console.print()


def _scene_ip_check() -> None:
    console.print()
    console.print("  [dim]Thinking...[/]")
    time.sleep(0.5)

    console.print("  [dim]→[/] [#00ff88]search_ip2location[/][dim](ip='198.51.100.1')[/]")
    time.sleep(0.4)
    for line in [
        "IP: 198.51.100.1",
        "Country: United States (US)",
        "Region: California",
        "City: Los Angeles",
        "Latitude: 34.052235",
        "Longitude: -118.243683",
        "ZIP: 90012",
        "ISP: ExampleNet Inc.",
        "Domain: examplenet.com",
        "ASN: AS64496",
        "Proxy: No",
        "VPN: Yes",
        "TOR: No",
        "Datacenter: Yes",
        "Threat: ANONYMOUS_PROXY",
    ]:
        console.print(f"    [dim][IP2Location] {line}[/]")
    console.print("    [bold yellow]WARNING: VPN/Proxy/Tor detected[/]")
    time.sleep(0.9)

    console.print("  [dim]→[/] [#00ff88]search_abuseipdb[/][dim](ip='198.51.100.1')[/]")
    time.sleep(0.4)
    for line in [
        "IP: 198.51.100.1",
        "Abuse Confidence Score: 87%",
        "Total Reports: 143",
        "Country: US",
        "ISP: ExampleNet Inc.",
        "Domain: examplenet.com",
        "Last Reported: 2026-05-24T18:32:00+00:00",
    ]:
        console.print(f"    [dim][AbuseIPDB] {line}[/]")
    console.print("    [bold red]HIGH ABUSE CONFIDENCE — flagged by AbuseIPDB[/]")
    time.sleep(0.9)

    summary = """\
## IP Threat Summary

**Target:** 198.51.100.1 — **VERDICT: HIGH RISK**

| Attribute      | Value                  |
|----------------|------------------------|
| Country        | United States (US)     |
| ISP            | ExampleNet Inc.        |
| ASN            | AS64496                |
| VPN Detected   | Yes                    |
| Datacenter     | Yes                    |
| Threat Class   | ANONYMOUS_PROXY        |
| Abuse Score    | **87%** (HIGH)         |
| Abuse Reports  | 143 in last 90 days    |
| Last Reported  | 2026-05-24             |

**Recommendation:** Block this IP. High abuse score combined with VPN and datacenter flags indicates automated malicious activity.
"""
    console.print()
    console.print(Panel(Markdown(summary), border_style="#00ff88", padding=(1, 2)))
    console.print()


def main() -> None:
    _banner()
    _tools_table()

    while True:
        _show_prompt()
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye.[/]\n")
            break
        if not line:
            console.print("\n[dim]Goodbye.[/]\n")
            break
        cmd = line.strip()
        if not cmd:
            continue
        if cmd.lower() in ("exit", "quit", "q"):
            console.print("\n[dim]Goodbye.[/]\n")
            break
        if "investigate" in cmd.lower() or "target@example.com" in cmd:
            _scene_investigate()
        elif "198.51.100.1" in cmd or (
            "abuse" in cmd.lower() and "location" in cmd.lower()
        ):
            _scene_ip_check()
        else:
            console.print(f"  [dim]Running investigation for: {cmd}[/]")


if __name__ == "__main__":
    main()
