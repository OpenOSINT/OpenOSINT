# openosint/repl.py
"""
OpenOSINT Interactive REPL.

A Claude Code-style terminal interface for OpenOSINT.
Powered by prompt_toolkit for input handling and Rich for display.

Usage:
    openosint                                  # Anthropic Claude (default)
    openosint --provider ollama                # local Ollama model
    openosint --provider ollama --ollama-model mistral
    openosint --no-pdf                         # disable PDF export
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from openosint import __version__
from openosint.agent import OllamaAgent, OpenOSINTAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_REPORT_CHARS = 300

_TOOL_INFO_ROWS = [
    ("search_email", "holehe", "Social accounts linked to an email"),
    ("search_username", "sherlock", "Accounts across 300+ platforms"),
    ("search_breach", "HaveIBeenPwned", "Data breach exposure"),
    ("search_whois", "python-whois", "Domain registrant info"),
    ("search_ip", "ipinfo.io", "Geolocation, ASN, hostname"),
    ("search_domain", "sublist3r", "Subdomain enumeration"),
    ("generate_dorks", "built-in", "Google dork URLs"),
    ("search_paste", "psbdmp.ws", "Pastebin dump mentions"),
    ("search_phone", "phoneinfoga", "Carrier, country, line type"),
    ("search_shodan", "Shodan API", "Open ports, banners, CVEs"),
    ("search_virustotal", "VirusTotal API", "IP/domain/URL/hash threat analysis"),
    ("search_censys", "Censys API", "Internet infrastructure & certs"),
    ("search_ip2location", "IP2Location.io", "Enhanced IP geolocation & VPN/proxy detection"),
    ("search_abuseipdb", "AbuseIPDB API", "IP abuse confidence score"),
    ("search_github", "GitHub API", "Profile, repos, commit-email discovery"),
    ("search_dns", "dnspython", "DNS records & email security audit"),
    ("search_sherlockeye", "Sherlockeye API", "Reverse Lookup & AI-Powered OSINT (email, phone, IP, etc.)"),
]

# ---------------------------------------------------------------------------
# Rich console
# ---------------------------------------------------------------------------

console = Console()

# ---------------------------------------------------------------------------
# Prompt style
# ---------------------------------------------------------------------------

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "#00ff88 bold",
        "prompt-text": "#f1f5f9",
    }
)

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _print_banner(provider: str, model: str) -> None:
    if provider == "ollama":
        provider_info = f"[dim]Provider: Ollama ({model})[/]"
    else:
        provider_info = f"[dim]Provider: Anthropic ({model})[/]"

    console.print()
    console.print(
        Panel.fit(
            f"[bold #00ff88]OpenOSINT[/] [dim]v{__version__}[/]  [dim]·[/]  {provider_info}",
            border_style="#1e293b",
            padding=(0, 2),
        )
    )
    console.print(
        "  Type a target or question. [dim]'help'[/] for commands. [dim]'exit'[/] to quit.\n"
    )
    Console(stderr=True).print(
        "[yellow]⭐[/] [dim]If OpenOSINT is useful, star it → https://github.com/OpenOSINT/OpenOSINT[/]"
    )


def _print_help() -> None:
    console.print()
    console.print(
        Panel(
            "\n".join(
                [
                    "[bold]Commands:[/]",
                    "",
                    "  [#00ff88]<target>[/]          Investigate any target (email, username, domain, IP, name)",
                    "  [#00ff88]clear[/]             Clear conversation memory",
                    "  [#00ff88]save[/]              Save last report to reports/",
                    "  [#00ff88]tools[/]             List available OSINT tools",
                    "  [#00ff88]config[/]            Show current configuration",
                    "  [#00ff88]history[/]           Browse saved session history",
                    "  [#00ff88]help[/]              Show this message",
                    "  [#00ff88]exit[/] / Ctrl-D     Exit",
                    "",
                    "[bold]Examples:[/]",
                    "",
                    "  openosint ❯ investigate target@example.com",
                    "  openosint ❯ find all accounts for johndoe99",
                    "  openosint ❯ what subdomains does example.com have?",
                    "  openosint ❯ check if +14155552671 is a mobile number",
                    "  openosint ❯ shodan search for apache servers in Berlin",
                ]
            ),
            title="[bold]Help[/]",
            border_style="#1e293b",
            padding=(0, 2),
        )
    )
    console.print()


def _print_tools() -> None:
    from rich.table import Table

    table = Table(
        box=box.SIMPLE_HEAD,
        border_style="#1e293b",
        header_style="bold #00ff88",
        show_header=True,
    )
    table.add_column("Tool", style="#f1f5f9")
    table.add_column("Method", style="dim")
    table.add_column("Finds", style="#94a3b8")

    for row in _TOOL_INFO_ROWS:
        table.add_row(*row)

    console.print()
    console.print(table)
    console.print()


def _print_tool_call(name: str, args: dict[str, Any]) -> None:
    arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
    console.print(f"  [dim]→[/] [#00ff88]{name}[/][dim]({arg_str})[/]")


def _print_result(content: str) -> None:
    console.print()
    console.print(
        Panel(
            Markdown(content),
            border_style="#00ff88",
            padding=(1, 2),
        )
    )
    console.print()


def _print_error(message: str) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold red]Error:[/] {message}",
            border_style="red",
            padding=(0, 2),
        )
    )
    console.print()


def _print_config(
    api_key: str | None,
    provider: str,
    model: str,
    ollama_host: str,
    is_pdf_disabled: bool,
) -> None:
    masked = ("*" * 20 + api_key[-6:]) if api_key and len(api_key) > 6 else "not set"
    rows = [
        f"[bold]Provider:[/] {provider}",
        f"[bold]Model:[/]    {model}",
    ]
    if provider == "anthropic":
        rows.append(f"[bold]API Key:[/]  {masked}")
    else:
        rows.append(f"[bold]Ollama:[/]   {ollama_host}")
    rows += [
        "[bold]Reports:[/]  ./reports/",
        f"[bold]PDF:[/]      {'disabled' if is_pdf_disabled else 'enabled'}",
    ]
    console.print()
    console.print(
        Panel(
            "\n".join(rows),
            title="[bold]Configuration[/]",
            border_style="#1e293b",
            padding=(0, 2),
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# Report saver
# ---------------------------------------------------------------------------


def _save_report(content: str) -> Path:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = reports_dir / f"{timestamp}_report.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


class OpenOSINTRepl:
    """Interactive REPL session."""

    def __init__(
        self,
        api_key: str | None = None,
        provider: str = "anthropic",
        ollama_model: str = "llama3.2",
        ollama_host: str = "http://localhost:11434",
        is_pdf_disabled: bool = False,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._provider = provider
        self._ollama_model = ollama_model
        self._ollama_host = ollama_host
        self._is_pdf_disabled = is_pdf_disabled

        if provider == "ollama":
            self._agent: OpenOSINTAgent | OllamaAgent = OllamaAgent(
                model=ollama_model,
                host=ollama_host,
            )
            self._display_model = ollama_model
        else:
            self._agent = OpenOSINTAgent(api_key=self._api_key)
            self._display_model = "claude-sonnet-4-20250514"

        self._last_response: str = ""
        self._session_start: datetime = datetime.now()
        self._session_prompts: list[str] = []
        self._session_tools: list[str] = []
        self._session_targets: list[str] = []
        self._session_report_path: str = ""
        self._session: PromptSession = PromptSession(
            history=FileHistory(str(Path.home() / ".openosint_history")),
            style=PROMPT_STYLE,
        )

    def _get_prompt_tokens(self) -> HTML:
        return HTML("<prompt>openosint</prompt> <prompt-text>❯</prompt-text> ")

    async def _handle_tool_call(self, name: str, args: dict[str, Any]) -> None:
        _print_tool_call(name, args)

    async def _run_investigation(self, user_input: str) -> None:
        self._session_prompts.append(user_input)

        console.print()
        console.print("  [dim]Thinking...[/]")

        response = await self._agent.run(
            prompt=user_input,
            on_tool_call=self._handle_tool_call,
        )

        if response.error:
            _print_error(response.error)
            return

        # Track tools and targets from this turn
        for tc in response.tool_calls:
            if tc.name not in self._session_tools:
                self._session_tools.append(tc.name)
            for v in tc.input.values():
                if isinstance(v, str) and v not in self._session_targets:
                    self._session_targets.append(v)

        if response.content:
            self._last_response = response.content
            _print_result(response.content)

        # Auto-save structured report
        if "##" in response.content and len(response.content) > _MIN_REPORT_CHARS:
            try:
                path = _save_report(response.content)
                self._session_report_path = str(path)
                console.print(f"  [dim]✓ Report saved → {path}[/]")
                if not self._is_pdf_disabled:
                    await self._generate_pdf(path)
                console.print()
            except Exception:
                logger.debug("Report save failed.", exc_info=True)

    async def _generate_pdf(self, md_path: Path) -> None:
        try:
            from openosint.pdf_report import generate_pdf_report

            pdf_path = await generate_pdf_report(md_path)
            if pdf_path:
                console.print(f"  [dim]✓ PDF saved     → {pdf_path}[/]")
        except Exception:
            logger.debug("PDF generation failed.", exc_info=True)

    def _save_session(self) -> None:
        if not self._session_prompts:
            return
        from openosint.session_history import SessionRecord, save_session

        duration = int((datetime.now() - self._session_start).total_seconds())
        record = SessionRecord(
            timestamp=self._session_start.strftime("%Y-%m-%dT%H:%M:%S"),
            duration_seconds=duration,
            prompts=self._session_prompts,
            tools_used=self._session_tools,
            targets=self._session_targets,
            report_path=self._session_report_path,
        )
        try:
            save_session(record)
        except Exception:
            logger.debug("Session save failed.", exc_info=True)

    async def run(self) -> None:
        """Start the interactive REPL loop."""
        if self._provider == "anthropic" and not self._api_key:
            _print_error(
                "ANTHROPIC_API_KEY is not set.\n"
                "  Export it: [bold]export ANTHROPIC_API_KEY=sk-ant-...[/]\n"
                "  Or use a local model: [bold]openosint --provider ollama[/]"
            )
            sys.exit(1)

        _print_banner(self._provider, self._display_model)

        from openosint.session_history import count_sessions

        n = count_sessions()
        if n > 0:
            s = "s" if n != 1 else ""
            console.print(f"  [dim]💾 {n} session{s} saved — type 'history' to browse[/]\n")

        try:
            while True:
                try:
                    raw = await self._session.prompt_async(
                        self._get_prompt_tokens,
                        style=PROMPT_STYLE,
                    )
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Goodbye.[/]\n")
                    break

                user_input = raw.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit", "q"):
                    console.print("\n[dim]Goodbye.[/]\n")
                    break

                if user_input.lower() == "help":
                    _print_help()
                    continue

                if user_input.lower() == "tools":
                    _print_tools()
                    continue

                if user_input.lower() == "clear":
                    self._agent.clear_history()
                    console.print("  [dim]Conversation memory cleared.[/]\n")
                    continue

                if user_input.lower() == "config":
                    _print_config(
                        self._api_key,
                        self._provider,
                        self._display_model,
                        self._ollama_host,
                        self._is_pdf_disabled,
                    )
                    continue

                if user_input.lower() == "save":
                    if self._last_response:
                        path = _save_report(self._last_response)
                        console.print(f"  [dim]✓ Saved → {path}[/]\n")
                    else:
                        console.print("  [dim]Nothing to save yet.[/]\n")
                    continue

                if user_input.lower() == "history":
                    from openosint.session_history import display_history_table, load_sessions

                    display_history_table(load_sessions(limit=10), console)
                    continue

                await self._run_investigation(user_input)
        finally:
            self._save_session()
