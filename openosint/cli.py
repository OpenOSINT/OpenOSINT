# openosint/cli.py
"""
OpenOSINT command-line interface.

Default behaviour  : launches the interactive REPL (Claude Code style).
Subcommands        : direct tool execution without AI (email, username,
                     shodan, multi).

Usage:
    openosint                                   # interactive REPL
    openosint email target@example.com          # direct, no AI
    openosint username johndoe99                # direct, no AI
    openosint shodan 8.8.8.8                    # Shodan lookup, no AI
    openosint multi targets.txt                 # multi-target (file)
    openosint multi email1,email2,email3        # multi-target (inline)
    openosint --parallel email target@example.com
    openosint --json email target@example.com
    openosint --provider ollama                 # use local Ollama
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402

from openosint.json_output import format_tool_result  # noqa: E402
from openosint.tools.search_abuseipdb import run_abuseipdb_osint  # noqa: E402
from openosint.tools.search_breach import run_breach_osint  # noqa: E402
from openosint.tools.search_censys import run_censys_osint  # noqa: E402
from openosint.tools.search_dns import run_dns_osint  # noqa: E402
from openosint.tools.search_email import run_email_osint  # noqa: E402
from openosint.tools.search_github import run_github_osint  # noqa: E402
from openosint.tools.search_sherlockeye import run_sherlockeye_osint  # noqa: E402
from openosint.tools.search_ip2location import run_ip2location_osint  # noqa: E402
from openosint.tools.search_paste import run_paste_osint  # noqa: E402
from openosint.tools.search_shodan import run_shodan_osint  # noqa: E402
from openosint.tools.search_username import run_username_osint  # noqa: E402
from openosint.tools.search_virustotal import run_virustotal_osint  # noqa: E402

_DIVIDER = "=" * 60


# ---------------------------------------------------------------------------
# Ollama pre-flight check
# ---------------------------------------------------------------------------


def _check_ollama_server(host: str) -> bool:
    """Return True if the Ollama HTTP server is accepting connections."""
    import socket
    import urllib.parse

    parsed = urllib.parse.urlparse(host)
    hostname = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        with socket.create_connection((hostname, port), timeout=3):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="[%(levelname)s] %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openosint",
        description=(
            "OpenOSINT — AI-powered OSINT framework.\n"
            "Run without arguments to start the interactive REPL."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  openosint                                   # interactive AI session\n"
            "  openosint email target@example.com          # direct email scan\n"
            "  openosint username johndoe99                # direct username scan\n"
            "  openosint shodan 8.8.8.8                    # Shodan host lookup\n"
            "  openosint censys 8.8.8.8                   # Censys host lookup\n"
            "  openosint censys example.com               # Censys certificate search\n"
            "  openosint ip2location 8.8.8.8              # IP2Location lookup\n"
            "  openosint multi targets.txt                 # multi-target from file\n"
            "  openosint multi a@x.com,b@y.com             # multi-target inline\n"
            "  openosint --parallel email target@example.com\n"
            "  openosint --json email target@example.com\n"
            "  openosint --provider ollama                 # use local Ollama\n"
            "  openosint --provider ollama --ollama-model mistral\n"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        metavar="KEY",
        help="Anthropic API key (overrides ANTHROPIC_API_KEY env var).",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        dest="is_parallel",
        help=(
            "Run independent complementary tools concurrently using asyncio.gather(). "
            "For 'email': runs search_email + search_breach in parallel. "
            "For 'username': runs search_username + search_paste in parallel."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as structured JSON instead of formatted text.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="anthropic",
        choices=["anthropic", "ollama"],
        help="AI provider for the interactive REPL (default: anthropic).",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="llama3.2",
        metavar="MODEL",
        help="Ollama model name (default: llama3.2).  Used when --provider ollama.",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default="http://localhost:11434",
        metavar="URL",
        help="Ollama server URL (default: http://localhost:11434).",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        dest="is_pdf_disabled",
        help="Disable automatic PDF generation alongside Markdown reports.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    # shell — explicit alias for REPL
    subparsers.add_parser(
        "shell",
        help="Start the interactive REPL (default when no command given).",
    )

    # email
    email_cmd = subparsers.add_parser(
        "email",
        help="Direct email scan via holehe (no AI).",
    )
    email_cmd.add_argument("target", type=str, metavar="ADDRESS")
    email_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=120,
        metavar="SECONDS",
        help="Maximum execution time (default: 120).",
    )

    # username
    username_cmd = subparsers.add_parser(
        "username",
        help="Direct username scan via sherlock (no AI).",
    )
    username_cmd.add_argument("target", type=str, metavar="USERNAME")
    username_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=180,
        metavar="SECONDS",
        help="Maximum execution time (default: 180).",
    )

    # shodan
    shodan_cmd = subparsers.add_parser(
        "shodan",
        help="Shodan host lookup or keyword search (no AI). Requires SHODAN_API_KEY.",
    )
    shodan_cmd.add_argument(
        "query",
        type=str,
        metavar="QUERY",
        help="IP address for host lookup, or any Shodan search query.",
    )
    shodan_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # virustotal
    virustotal_cmd = subparsers.add_parser(
        "virustotal",
        help="VirusTotal lookup for IP, domain, URL, or file hash (no AI). Requires VIRUSTOTAL_API_KEY.",
    )
    virustotal_cmd.add_argument(
        "target",
        type=str,
        metavar="TARGET",
        help="IPv4 address, domain, full URL, or file hash (MD5/SHA-1/SHA-256).",
    )
    virustotal_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # censys
    censys_cmd = subparsers.add_parser(
        "censys",
        help="Censys lookup for IP or domain (no AI). Requires CENSYS_API_ID and CENSYS_SECRET.",
    )
    censys_cmd.add_argument(
        "target",
        type=str,
        metavar="TARGET",
        help="IPv4 address for host lookup, or domain for certificate search.",
    )
    censys_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # github
    github_cmd = subparsers.add_parser(
        "github",
        help="GitHub OSINT: profile, repos, and commit-email discovery (no AI).",
    )
    github_cmd.add_argument(
        "query",
        type=str,
        metavar="QUERY",
        help="GitHub username, email address, or keyword.",
    )
    github_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # dns
    dns_cmd = subparsers.add_parser(
        "dns",
        help="DNS record enumeration with email security analysis (no AI).",
    )
    dns_cmd.add_argument(
        "domain",
        type=str,
        metavar="DOMAIN",
        help="Target domain (e.g. example.com).",
    )
    dns_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=10,
        metavar="SECONDS",
        help="DNS query timeout (default: 10).",
    )

    # abuseipdb
    abuseipdb_cmd = subparsers.add_parser(
        "abuseipdb",
        help="AbuseIPDB reputation check for an IP address (no AI). Requires ABUSEIPDB_API_KEY.",
    )
    abuseipdb_cmd.add_argument(
        "ip",
        type=str,
        metavar="IP_ADDRESS",
        help="IPv4 or IPv6 address to check.",
    )
    abuseipdb_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # sherlockeye
    sherlockeye_cmd = subparsers.add_parser(
        "sherlockeye",
        help="Sherlockeye Reverse Lookup & AI-Powered OSINT search (no AI). Requires SHERLOCKEYE_API_KEY.",
    )
    sherlockeye_cmd.add_argument(
        "query",
        type=str,
        metavar="QUERY",
        help='Target value or type:"value" (email, phone, name, domain, ip, username, cpf, cnpj).',
    )
    sherlockeye_cmd.add_argument(
        "--deep-research",
        action="store_true",
        help="Enable Deep Research (digital_accounts_expansion) for email/phone/name.",
    )
    sherlockeye_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=120,
        metavar="SECONDS",
        help="Search timeout (default: 120).",
    )

    # ip2location
    ip2location_cmd = subparsers.add_parser(
        "ip2location",
        help="IP2Location lookup for geolocation, ISP, VPN/Proxy/Tor/Datacenter detection (no AI). Requires IP2LOCATION_API_KEY.",
    )
    ip2location_cmd.add_argument(
        "ip",
        type=str,
        metavar="IP_ADDRESS",
        help="IPv4 or IPv6 address to look up.",
    )
    ip2location_cmd.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # multi
    multi_cmd = subparsers.add_parser(
        "multi",
        help="Investigate multiple targets in parallel (AI-powered).",
    )
    multi_cmd.add_argument(
        "targets",
        type=str,
        metavar="TARGETS",
        help=("Comma-separated list of targets, or path to a file with one target per line."),
    )

    # web
    web_cmd = subparsers.add_parser(
        "web",
        help="Start the web server (opens browser automatically).",
    )
    web_cmd.add_argument(
        "--port",
        type=int,
        default=8080,
        metavar="PORT",
        help="Port to listen on (default: 8080).",
    )
    web_cmd.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        metavar="HOST",
        help="Host/IP to bind to (default: 0.0.0.0).",
    )
    web_cmd.add_argument(
        "--no-browser",
        action="store_true",
        dest="no_browser",
        help="Do not open a browser tab automatically.",
    )

    # history
    history_parser = subparsers.add_parser(
        "history",
        help="Browse saved REPL session history.",
    )
    history_parser.add_argument(
        "--all",
        action="store_true",
        dest="history_all",
        help="List all saved sessions (up to 50).",
    )
    history_parser.add_argument(
        "--last",
        type=int,
        metavar="N",
        dest="history_last",
        default=None,
        help="List last N sessions.",
    )
    history_sub = history_parser.add_subparsers(dest="history_action", metavar="action")

    history_open = history_sub.add_parser("open", help="Open session by number from the list.")
    history_open.add_argument("n", type=int, metavar="N", help="Session number (1-based).")

    history_sub.add_parser("clear", help="Delete all session history files.")

    return parser


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_result(result: str) -> None:
    print(_DIVIDER)
    print(" SCAN RESULTS ".center(60, "="))
    print(_DIVIDER)
    print(result)
    print(_DIVIDER)


def _print_result_labeled(label: str, result: str) -> None:
    print(_DIVIDER)
    print(f" {label} ".center(60, "="))
    print(_DIVIDER)
    print(result)
    print(_DIVIDER)


def _emit_json(data: dict | list) -> None:
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Direct command handlers (no AI)
# ---------------------------------------------------------------------------


async def _handle_email(
    target: str,
    timeout: int,
    is_parallel: bool = False,
    json_output: bool = False,
) -> None:
    if is_parallel:
        print(f"[*] Email scan (parallel): {target}", file=sys.stderr)
        email_result, breach_result = await asyncio.gather(
            run_email_osint(email=target, timeout_seconds=timeout),
            run_breach_osint(email=target),
        )
        if json_output:
            _emit_json(
                [
                    format_tool_result("search_email", target, email_result),
                    format_tool_result("search_breach", target, breach_result),
                ]
            )
        else:
            _print_result_labeled("search_email", email_result)
            _print_result_labeled("search_breach", breach_result)
    else:
        print(f"[*] Email scan: {target}", file=sys.stderr)
        print(f"[*] Timeout: {timeout}s\n", file=sys.stderr)
        result = await run_email_osint(email=target, timeout_seconds=timeout)
        if json_output:
            _emit_json(format_tool_result("search_email", target, result))
        else:
            _print_result(result)


async def _handle_username(
    target: str,
    timeout: int,
    is_parallel: bool = False,
    json_output: bool = False,
) -> None:
    if is_parallel:
        print(f"[*] Username scan (parallel): {target}", file=sys.stderr)
        username_result, paste_result = await asyncio.gather(
            run_username_osint(username=target, timeout_seconds=timeout),
            run_paste_osint(query=target),
        )
        if json_output:
            _emit_json(
                [
                    format_tool_result("search_username", target, username_result),
                    format_tool_result("search_paste", target, paste_result),
                ]
            )
        else:
            _print_result_labeled("search_username", username_result)
            _print_result_labeled("search_paste", paste_result)
    else:
        print(f"[*] Username scan: {target}", file=sys.stderr)
        print(f"[*] Timeout: {timeout}s\n", file=sys.stderr)
        result = await run_username_osint(username=target, timeout_seconds=timeout)
        if json_output:
            _emit_json(format_tool_result("search_username", target, result))
        else:
            _print_result(result)


async def _handle_shodan(
    query: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] Shodan lookup: {query}", file=sys.stderr)
    result = await run_shodan_osint(query=query, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_shodan", query, result))
    else:
        _print_result(result)


async def _handle_virustotal(
    target: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] VirusTotal lookup: {target}", file=sys.stderr)
    result = await run_virustotal_osint(target=target, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_virustotal", target, result))
    else:
        _print_result(result)


async def _handle_censys(
    target: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] Censys lookup: {target}", file=sys.stderr)
    result = await run_censys_osint(target=target, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_censys", target, result))
    else:
        _print_result(result)


async def _handle_abuseipdb(
    ip: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] AbuseIPDB lookup: {ip}", file=sys.stderr)
    result = await run_abuseipdb_osint(ip=ip, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_abuseipdb", ip, result))
    else:
        _print_result(result)


async def _handle_github(
    query: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] GitHub lookup: {query}", file=sys.stderr)
    result = await run_github_osint(query=query, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_github", query, result))
    else:
        _print_result(result)


async def _handle_dns(
    domain: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] DNS lookup: {domain}", file=sys.stderr)
    result = await run_dns_osint(domain=domain, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_dns", domain, result))
    else:
        _print_result(result)


async def _handle_sherlockeye(
    query: str,
    timeout: int,
    deep_research: bool = False,
    json_output: bool = False,
) -> None:
    print(f"[*] Sherlockeye search: {query}", file=sys.stderr)
    result = await run_sherlockeye_osint(
        query=query,
        timeout_seconds=timeout,
        deep_research=deep_research,
    )
    if json_output:
        _emit_json(format_tool_result("search_sherlockeye", query, result))
    else:
        _print_result(result)


async def _handle_ip2location(
    ip: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] IP2Location lookup: {ip}", file=sys.stderr)
    result = await run_ip2location_osint(ip=ip, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_ip2location", ip, result))
    else:
        _print_result(result)


async def _handle_multi(
    targets_arg: str,
    api_key: str | None = None,
    is_pdf_disabled: bool = False,
) -> None:
    from openosint.multi_target import MAX_TARGETS, parse_targets, run_multi_target

    targets = parse_targets(targets_arg)
    if not targets:
        print("[!] No targets found.", file=sys.stderr)
        sys.exit(1)
    if len(targets) > MAX_TARGETS:
        print(
            f"[!] Too many targets ({len(targets)}). Maximum is {MAX_TARGETS}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[*] Multi-target investigation: {len(targets)} target(s)", file=sys.stderr)
    summary = await run_multi_target(targets, api_key=api_key, is_pdf_disabled=is_pdf_disabled)
    _print_result(summary)


# ---------------------------------------------------------------------------
# Web server handler
# ---------------------------------------------------------------------------


async def _handle_web(
    host: str = "0.0.0.0",
    port: int = 8080,
    no_browser: bool = False,
) -> None:
    import threading
    import webbrowser

    from openosint.web_server import serve_async

    if not no_browser:
        display = "localhost" if host in ("0.0.0.0", "") else host
        url = f"http://{display}:{port}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    await serve_async(host=host, port=port)


# ---------------------------------------------------------------------------
# History command handler
# ---------------------------------------------------------------------------


def _handle_history(args: argparse.Namespace) -> None:
    import sys as _sys

    from rich.console import Console as _Console

    from openosint.session_history import (
        clear_sessions,
        display_history_table,
        display_session_detail,
        load_sessions,
    )

    _console = _Console()
    action = getattr(args, "history_action", None)

    if action == "open":
        sessions = load_sessions()
        n = args.n
        if n < 1 or n > len(sessions):
            _console.print(
                f"[bold red]Error:[/] Session {n} not found (total saved: {len(sessions)})"
            )
            _sys.exit(1)
        display_session_detail(sessions[n - 1], n, _console)

    elif action == "clear":
        confirm = input("Delete all session history? [y/N] ").strip().lower()
        if confirm == "y":
            deleted = clear_sessions()
            noun = "file" if deleted == 1 else "files"
            _console.print(f"  [dim]✓ Deleted {deleted} session {noun}.[/]\n")
        else:
            _console.print("  [dim]Aborted.[/]\n")

    else:
        if getattr(args, "history_all", False):
            sessions = load_sessions()
        elif getattr(args, "history_last", None):
            sessions = load_sessions(limit=args.history_last)
        else:
            sessions = load_sessions(limit=10)
        display_history_table(sessions, _console)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def _async_main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args.verbose)

    # No subcommand or explicit 'shell' → launch REPL.
    # Await directly — run_repl() is a sync wrapper that calls asyncio.run()
    # internally, which raises RuntimeError when called from a running event loop.
    if args.command in (None, "shell"):
        if getattr(args, "provider", "anthropic") == "ollama":
            ollama_host = getattr(args, "ollama_host", "http://localhost:11434")
            if not _check_ollama_server(ollama_host):
                print(
                    f"[ERROR] Ollama server is not running at {ollama_host}.",
                    file=sys.stderr,
                )
                print(
                    "Make sure Ollama is installed (https://ollama.com) and running:",
                    file=sys.stderr,
                )
                print(
                    "  macOS/Linux:  curl -fsSL https://ollama.com/install.sh | sh",
                    file=sys.stderr,
                )
                print(
                    "  Windows:      https://ollama.com/download/windows",
                    file=sys.stderr,
                )
                print("", file=sys.stderr)
                print("  ollama serve          # start in terminal", file=sys.stderr)
                print("  ollama pull llama3.2  # pull a model first", file=sys.stderr)
                print("", file=sys.stderr)
                print("Then retry:  openosint --provider ollama", file=sys.stderr)
                sys.exit(1)

        from openosint.repl import OpenOSINTRepl

        repl = OpenOSINTRepl(
            api_key=getattr(args, "api_key", None),
            provider=getattr(args, "provider", "anthropic"),
            ollama_model=getattr(args, "ollama_model", "llama3.2"),
            ollama_host=getattr(args, "ollama_host", "http://localhost:11434"),
            is_pdf_disabled=getattr(args, "is_pdf_disabled", False),
        )
        await repl.run()
        return

    is_parallel = getattr(args, "is_parallel", False)
    json_output = getattr(args, "json_output", False)
    is_pdf_disabled = getattr(args, "is_pdf_disabled", False)

    if args.command == "email":
        await _handle_email(
            args.target, args.timeout, is_parallel=is_parallel, json_output=json_output
        )
    elif args.command == "username":
        await _handle_username(
            args.target, args.timeout, is_parallel=is_parallel, json_output=json_output
        )
    elif args.command == "shodan":
        await _handle_shodan(args.query, args.timeout, json_output=json_output)
    elif args.command == "virustotal":
        await _handle_virustotal(args.target, args.timeout, json_output=json_output)
    elif args.command == "censys":
        await _handle_censys(args.target, args.timeout, json_output=json_output)
    elif args.command == "github":
        await _handle_github(args.query, args.timeout, json_output=json_output)
    elif args.command == "dns":
        await _handle_dns(args.domain, args.timeout, json_output=json_output)
    elif args.command == "abuseipdb":
        await _handle_abuseipdb(args.ip, args.timeout, json_output=json_output)
    elif args.command == "sherlockeye":
        await _handle_sherlockeye(
            args.query,
            args.timeout,
            deep_research=getattr(args, "deep_research", False),
            json_output=json_output,
        )
    elif args.command == "ip2location":
        await _handle_ip2location(args.ip, args.timeout, json_output=json_output)
    elif args.command == "multi":
        await _handle_multi(
            args.targets, api_key=getattr(args, "api_key", None), is_pdf_disabled=is_pdf_disabled
        )
    elif args.command == "web":
        await _handle_web(
            host=getattr(args, "host", "0.0.0.0"),
            port=getattr(args, "port", 8080),
            no_browser=getattr(args, "no_browser", False),
        )
    elif args.command == "history":
        _handle_history(args)
    else:
        parser.print_help()
        sys.exit(1)


def main() -> None:
    """Synchronous entry point registered in pyproject.toml."""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        print("\n[!] Interrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"[!] Fatal: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
