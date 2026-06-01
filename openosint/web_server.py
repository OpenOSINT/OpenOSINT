# openosint/web_server.py
"""
OpenOSINT Web Server — FastAPI REST + SSE backend.

Routes:
  GET  /                       serve web/index.html
  GET  /api/health             version + setup status
  GET  /api/tools              tool catalog with availability
  POST /api/run/{tool_name}    run tool, return full result
  GET  /api/stream/{tool_name} stream output via Server-Sent Events
  POST /api/chat               AI chat with tool_use (SSE)
  POST /api/setup              save API keys to .env
  GET  /docs/*                 docs/ static files (mounted)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import AsyncIterator

import requests as _requests

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_censys import run_censys_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_ip2location import run_ip2location_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_virustotal import run_virustotal_osint
from openosint.tools.search_sherlockeye import run_sherlockeye_osint
from openosint.tools.search_whois import run_whois_osint

_VERSION = "2.19.0"
_ROOT = Path(__file__).parent.parent

# Web assets: prefer the package-relative path (pip install) with project-root fallback (dev/editable)
_PACKAGE_WEB = Path(__file__).parent / "web"
_WEB_DIR = _PACKAGE_WEB if _PACKAGE_WEB.exists() else _ROOT / "web"

# ---------------------------------------------------------------------------
# Tool catalog — drives both the REST API and the frontend sidebar
# ---------------------------------------------------------------------------

_TOOL_CATALOG: list[dict] = [
    {
        "name": "search_email",
        "description": "Enumerate accounts linked to an email via holehe.",
        "input_label": "Email address",
        "input_placeholder": "target@example.com",
        "category": "Identity",
        "icon": "📧",
        "requires_binary": ["holehe"],
        "requires_env": [],
        "binary_hints": {"holehe": "pip install holehe"},
    },
    {
        "name": "search_username",
        "description": "Enumerate platforms where a username is registered via sherlock.",
        "input_label": "Username",
        "input_placeholder": "johndoe99",
        "category": "Identity",
        "icon": "👤",
        "requires_binary": ["sherlock"],
        "requires_env": [],
        "binary_hints": {"sherlock": "pip install sherlock-project"},
    },
    {
        "name": "search_breach",
        "description": "Check if an email appears in data breaches via HaveIBeenPwned.",
        "input_label": "Email address",
        "input_placeholder": "target@example.com",
        "category": "Identity",
        "icon": "🔓",
        "requires_binary": [],
        "requires_env": ["HIBP_API_KEY"],
        "env_hints": {"HIBP_API_KEY": "haveibeenpwned.com/API/Key"},
    },
    {
        "name": "search_ip",
        "description": "Retrieve geolocation and ASN data for an IP address via ipinfo.io.",
        "input_label": "IP address",
        "input_placeholder": "8.8.8.8",
        "category": "Network",
        "icon": "🌐",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_whois",
        "description": "Retrieve WHOIS registration data for a domain.",
        "input_label": "Domain",
        "input_placeholder": "example.com",
        "category": "Network",
        "icon": "🔍",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_domain",
        "description": "Enumerate subdomains of a target domain via sublist3r.",
        "input_label": "Domain",
        "input_placeholder": "example.com",
        "category": "Network",
        "icon": "🗺️",
        "requires_binary": ["sublist3r"],
        "requires_env": [],
        "binary_hints": {"sublist3r": "pip install sublist3r"},
    },
    {
        "name": "search_ip2location",
        "description": "Enhanced IP intelligence: geolocation, ISP, VPN/Proxy/Tor detection.",
        "input_label": "IP address",
        "input_placeholder": "8.8.8.8",
        "category": "Network",
        "icon": "📍",
        "requires_binary": [],
        "requires_env": ["IP2LOCATION_API_KEY"],
        "env_hints": {"IP2LOCATION_API_KEY": "ip2location.io/pricing"},
    },
    {
        "name": "generate_dorks",
        "description": "Generate targeted Google dork URLs for any target.",
        "input_label": "Target (name, email, username, domain)",
        "input_placeholder": "john doe",
        "category": "Recon",
        "icon": "🔎",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_paste",
        "description": "Search Pastebin dumps for an email or username via psbdmp.ws.",
        "input_label": "Email or username",
        "input_placeholder": "target@example.com",
        "category": "Recon",
        "icon": "📋",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_phone",
        "description": "Gather carrier and geolocation data for a phone number.",
        "input_label": "Phone number (E.164 format)",
        "input_placeholder": "+14155552671",
        "category": "Recon",
        "icon": "📱",
        "requires_binary": ["phoneinfoga"],
        "requires_env": [],
        "binary_hints": {"phoneinfoga": "github.com/sundowndev/phoneinfoga/releases"},
    },
    {
        "name": "search_censys",
        "description": "Search Censys for internet-facing infrastructure data.",
        "input_label": "IP address or domain",
        "input_placeholder": "example.com",
        "category": "Recon",
        "icon": "🔭",
        "requires_binary": [],
        "requires_env": ["CENSYS_API_ID", "CENSYS_SECRET"],
        "env_hints": {
            "CENSYS_API_ID": "search.censys.io/account",
            "CENSYS_SECRET": "search.censys.io/account",
        },
    },
    {
        "name": "search_shodan",
        "description": "Query Shodan for host intelligence or banner search.",
        "input_label": "IP address or search query",
        "input_placeholder": "8.8.8.8",
        "category": "Recon",
        "icon": "🛡️",
        "requires_binary": [],
        "requires_env": ["SHODAN_API_KEY"],
        "env_hints": {"SHODAN_API_KEY": "account.shodan.io"},
    },
    {
        "name": "search_virustotal",
        "description": "Check IP, domain, URL, or file hash against VirusTotal.",
        "input_label": "IP, domain, URL, or file hash",
        "input_placeholder": "8.8.8.8",
        "category": "Recon",
        "icon": "🦠",
        "requires_binary": [],
        "requires_env": ["VIRUSTOTAL_API_KEY"],
        "env_hints": {"VIRUSTOTAL_API_KEY": "virustotal.com/gui/my-apikey"},
    },
    {
        "name": "search_sherlockeye",
        "description": "Reverse Lookup & AI-Powered OSINT via Sherlockeye (email, phone, IP, username, etc.).",
        "input_label": "Query (value or type:\"value\")",
        "input_placeholder": "user@example.com",
        "category": "Identity",
        "icon": "🔎",
        "requires_binary": [],
        "requires_env": ["SHERLOCKEYE_API_KEY"],
        "env_hints": {"SHERLOCKEYE_API_KEY": "app.sherlockeye.io/api"},
    },
]

# Map tool name → async callable(input_value: str, timeout: int) -> str
_RUNNERS: dict[str, object] = {
    "search_email": lambda v, t: run_email_osint(v, timeout_seconds=t),
    "search_username": lambda v, t: run_username_osint(v, timeout_seconds=t),
    "search_breach": lambda v, t: run_breach_osint(v, timeout_seconds=t),
    "search_whois": lambda v, t: run_whois_osint(v, timeout_seconds=t),
    "search_ip": lambda v, t: run_ip_osint(v, timeout_seconds=t),
    "search_domain": lambda v, t: run_domain_osint(v, timeout_seconds=t),
    "search_ip2location": lambda v, t: run_ip2location_osint(v, timeout_seconds=t),
    "generate_dorks": lambda v, _t: run_dork_osint(v),
    "search_paste": lambda v, t: run_paste_osint(v, timeout_seconds=t),
    "search_phone": lambda v, t: run_phone_osint(v, timeout_seconds=t),
    "search_shodan": lambda v, t: run_shodan_osint(v, timeout_seconds=t),
    "search_virustotal": lambda v, t: run_virustotal_osint(v, timeout_seconds=t),
    "search_censys": lambda v, t: run_censys_osint(v, timeout_seconds=t),
    "search_sherlockeye": lambda v, t: run_sherlockeye_osint(v, timeout_seconds=t),
}

# Claude tool schemas (one string "input" param per tool)
_CLAUDE_TOOLS: list[dict] = [
    {
        "name": meta["name"],
        "description": meta["description"],
        "input_schema": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": f"{meta['input_label']} — e.g. {meta['input_placeholder']}",
                }
            },
            "required": ["input"],
        },
    }
    for meta in _TOOL_CATALOG
]


def _check_available(meta: dict) -> tuple[bool, str | None]:
    """Return (is_available, reason_if_not) for a tool."""
    for binary in meta.get("requires_binary", []):
        if not shutil.which(binary):
            hint = meta.get("binary_hints", {}).get(binary, f"install {binary}")
            return False, f"{binary} not in PATH — {hint}"
    for key in meta.get("requires_env", []):
        if not os.environ.get(key, "").strip():
            hint = meta.get("env_hints", {}).get(key, "")
            suffix = f" — {hint}" if hint else ""
            return False, f"{key} not set{suffix}"
    return True, None


_KNOWN_ENV_KEYS = [
    "ANTHROPIC_API_KEY",
    "HIBP_API_KEY",
    "IPINFO_TOKEN",
    "IP2LOCATION_API_KEY",
    "CENSYS_API_ID",
    "CENSYS_SECRET",
    "SHODAN_API_KEY",
    "VIRUSTOTAL_API_KEY",
    "SHERLOCKEYE_API_KEY",
]


def _is_setup_complete() -> bool:
    if (_ROOT / ".env").exists():
        return True
    return any(os.environ.get(k, "").strip() for k in _KNOWN_ENV_KEYS)


def _get_ai_backend() -> tuple[str, str | None, bool | None]:
    """Return (backend_name, ollama_host, ollama_reachable)."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "claude", None, None
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        resp = _requests.get(f"{ollama_host}/api/tags", timeout=2)
        reachable = resp.status_code == 200
    except Exception:
        reachable = False
    return ("ollama" if reachable else "none"), ollama_host, reachable


class RunRequest(BaseModel):
    input: str
    timeout: int = 120


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    model: str = "claude"
    ollama_model: str = "llama3.2"
    ollama_host: str = "http://localhost:11434"


# ---------------------------------------------------------------------------
# AI chat streaming helpers
# ---------------------------------------------------------------------------


async def _run_tool(tool_name: str, tool_input: str, timeout: int = 120) -> str:
    if tool_name not in _RUNNERS:
        return f"Unknown tool: {tool_name}"
    try:
        return await _RUNNERS[tool_name](tool_input, timeout)
    except Exception as exc:
        return f"Error: {exc}"


async def _stream_claude(messages: list[dict]) -> AsyncIterator[dict]:
    """Yield SSE event dicts while running an agentic Claude loop with tool_use."""
    try:
        import anthropic as _anthropic
    except ImportError:
        yield {
            "type": "error",
            "message": "anthropic package not installed. Run: pip install anthropic",
        }
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        yield {"type": "error", "message": "ANTHROPIC_API_KEY not set."}
        return

    client = _anthropic.AsyncAnthropic(api_key=api_key)
    msgs = list(messages)
    _MAX_TOOL_ROUNDS = 5
    _tool_rounds = 0

    system_prompt = (
        "You are OpenOSINT, an AI-powered OSINT investigation assistant. "
        "When the user asks you to investigate a target, use the available tools to gather intelligence. "
        "Summarize findings clearly and highlight anything suspicious or notable. "
        "Always clarify what tools you used and what each result means."
    )

    while True:
        _tool_rounds += 1
        if _tool_rounds > _MAX_TOOL_ROUNDS:
            yield {"type": "error", "message": "Tool call limit reached (5 rounds)."}
            return
        full_content: list[dict] = []
        pending_tool_results: list[dict] = []
        current_block: dict | None = None
        current_tool_json = ""
        stop_reason = "end_turn"

        try:
            async with client.messages.stream(
                model="claude-sonnet-4-5",
                max_tokens=4096,
                system=system_prompt,
                tools=_CLAUDE_TOOLS,
                messages=msgs,
            ) as stream:
                async for event in stream:
                    etype = event.type

                    if etype == "content_block_start":
                        cb = event.content_block
                        if cb.type == "text":
                            current_block = {"type": "text", "text": ""}
                            full_content.append(current_block)
                        elif cb.type == "tool_use":
                            current_block = {
                                "type": "tool_use",
                                "id": cb.id,
                                "name": cb.name,
                                "input": {},
                            }
                            current_tool_json = ""
                            full_content.append(current_block)

                    elif etype == "content_block_delta":
                        d = event.delta
                        if (
                            d.type == "text_delta"
                            and current_block
                            and current_block["type"] == "text"
                        ):
                            current_block["text"] += d.text
                            yield {"type": "text", "content": d.text}
                        elif d.type == "input_json_delta":
                            current_tool_json += d.partial_json

                    elif etype == "content_block_stop":
                        if current_block and current_block["type"] == "tool_use":
                            try:
                                input_data = (
                                    json.loads(current_tool_json) if current_tool_json else {}
                                )
                            except Exception:
                                input_data = {"input": current_tool_json}
                            current_block["input"] = input_data

                            tool_name = current_block["name"]
                            tool_input = input_data.get("input", "")
                            if not tool_input and input_data:
                                tool_input = next(
                                    (v for v in input_data.values() if isinstance(v, str)),
                                    str(input_data),
                                )

                            yield {
                                "type": "tool_start",
                                "tool": tool_name,
                                "input": str(tool_input),
                            }

                            t0 = time.monotonic()
                            result = await _run_tool(tool_name, str(tool_input))
                            elapsed = round(time.monotonic() - t0, 2)

                            yield {
                                "type": "tool_result",
                                "tool": tool_name,
                                "output": result,
                                "elapsed": elapsed,
                            }
                            pending_tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": current_block["id"],
                                    "content": result,
                                }
                            )

                        current_block = None
                        current_tool_json = ""

                final_msg = await stream.get_final_message()
                stop_reason = final_msg.stop_reason or "end_turn"

        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            return

        if stop_reason != "tool_use" or not pending_tool_results:
            break

        msgs = msgs + [
            {"role": "assistant", "content": full_content},
            {"role": "user", "content": pending_tool_results},
        ]

    yield {"type": "done"}


async def _stream_ollama(
    messages: list[dict], ollama_host: str, ollama_model: str
) -> AsyncIterator[dict]:
    """Yield SSE event dicts using Ollama chat API with tool_use."""
    host = ollama_host.rstrip("/")
    msgs = list(messages)

    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in _CLAUDE_TOOLS
    ]

    while True:
        try:
            payload = {
                "model": ollama_model,
                "messages": msgs,
                "tools": ollama_tools,
                "stream": False,
            }
            if _httpx is not None:
                async with _httpx.AsyncClient(timeout=120) as client:
                    r = await client.post(f"{host}/api/chat", json=payload)
                if r.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"Ollama returned HTTP {r.status_code}: {r.text[:200]}",
                    }
                    return
                data = r.json()
            else:
                # fallback: run blocking requests in a thread
                _payload = payload  # capture for lambda
                raw = await asyncio.to_thread(
                    lambda: _requests.post(f"{host}/api/chat", json=_payload, timeout=120)
                )
                if raw.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"Ollama returned HTTP {raw.status_code}: {raw.text[:200]}",
                    }
                    return
                data = raw.json()
        except Exception as exc:
            yield {"type": "error", "message": f"Ollama request failed: {exc}"}
            return

        msg = data.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        if content:
            yield {"type": "text", "content": content}

        if not tool_calls:
            break

        tool_results_for_next = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {"input": raw_args}
            tool_input = raw_args.get("input", "")
            if not tool_input and raw_args:
                tool_input = next(
                    (v for v in raw_args.values() if isinstance(v, str)), str(raw_args)
                )

            yield {"type": "tool_start", "tool": tool_name, "input": str(tool_input)}

            t0 = time.monotonic()
            result = await _run_tool(tool_name, str(tool_input))
            elapsed = round(time.monotonic() - t0, 2)

            yield {"type": "tool_result", "tool": tool_name, "output": result, "elapsed": elapsed}
            tool_results_for_next.append({"role": "tool", "content": result})

        msgs = (
            msgs
            + [{"role": "assistant", "content": content, "tool_calls": tool_calls}]
            + tool_results_for_next
        )

    yield {"type": "done"}


# ---------------------------------------------------------------------------
# Demo chat — pre-scripted SSE stream, no API key required
# ---------------------------------------------------------------------------


async def _demo_chat_stream(message: str) -> AsyncIterator[dict]:
    """Yield scripted SSE events that look like a real investigation."""

    async def stream_text(text: str) -> AsyncIterator[dict]:
        words = text.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield {"type": "text", "content": chunk}
            await asyncio.sleep(0.03)

    msg_lower = message.lower()

    # --- tools / availability query ---
    if any(kw in msg_lower for kw in ("tool", "available", "what can")):
        lines = [
            "I have **13 OSINT tools** available for investigations:\n\n",
            "**Identity:** `search_email`, `search_username`, `search_breach`\n\n",
            "**Network:** `search_ip`, `search_whois`, `search_domain`, `search_ip2location`\n\n",
            "**Recon:** `generate_dorks`, `search_paste`, `search_phone`, `search_shodan`, `search_virustotal`, `search_censys`\n\n",
            "Just give me a target — email address, username, domain, or IP.",
        ]
        for line in lines:
            async for event in stream_text(line):
                yield event
        yield {"type": "done"}
        return

    # --- email investigation ---
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", message)
    if email_match or any(kw in msg_lower for kw in ("email", "investigate", "@")):
        email = email_match.group(0) if email_match else "demo@example.com"
        async for event in stream_text(f"Investigating **{email}**...\n\n"):
            yield event

        yield {"type": "tool_start", "tool": "search_email", "input": email}
        await asyncio.sleep(1.5)
        yield {
            "type": "tool_result",
            "tool": "search_email",
            "output": (
                "[+] Spotify       https://open.spotify.com/user/demo\n"
                "[+] GitHub        https://github.com/demo\n"
                "[+] Gravatar      https://gravatar.com/demo\n"
                "[+] WordPress     https://wordpress.com/demo\n"
                "[*] Holehe scan complete — 4 accounts found"
            ),
            "elapsed": 1.4,
        }

        yield {"type": "tool_start", "tool": "search_breach", "input": email}
        await asyncio.sleep(1.2)
        yield {
            "type": "tool_result",
            "tool": "search_breach",
            "output": (
                "[!] LinkedIn (2016-05-17) — Passwords, Email addresses\n"
                "[!] Adobe (2013-10-04) — Passwords, Email addresses, Usernames\n"
                "[*] 2 breach(es) found via HaveIBeenPwned"
            ),
            "elapsed": 1.1,
        }

        summary = (
            f"## Summary\n\nTarget **{email}** has accounts on **4 platforms** "
            "and appears in **2 known data breaches** (LinkedIn 2016, Adobe 2013). "
            "Credential rotation strongly advised."
        )
        async for event in stream_text(summary):
            yield event
        yield {"type": "done"}
        return

    # --- IP investigation ---
    ip_match = re.search(r"\b(\d{1,3}\.){3}\d{1,3}\b", message)
    if ip_match or "ip" in msg_lower:
        ip = ip_match.group(0) if ip_match else "8.8.8.8"

        yield {"type": "tool_start", "tool": "search_ip", "input": ip}
        await asyncio.sleep(1.0)
        yield {
            "type": "tool_result",
            "tool": "search_ip",
            "output": (
                f"[+] IP: {ip}\n"
                "[+] Hostname: dns.google\n"
                "[+] Country: US — Mountain View, California\n"
                "[+] Org: AS15169 Google LLC\n"
                "[+] Timezone: America/Los_Angeles"
            ),
            "elapsed": 0.9,
        }

        yield {"type": "tool_start", "tool": "search_whois", "input": ip}
        await asyncio.sleep(0.8)
        yield {
            "type": "tool_result",
            "tool": "search_whois",
            "output": (
                "[+] IP Range: 8.8.8.0/24\n"
                "[+] Owner: Google LLC\n"
                "[+] Abuse: network-abuse@google.com\n"
                "[+] Country: US\n"
                "[+] Registered: 2014-03-14"
            ),
            "elapsed": 0.7,
        }

        summary = (
            f"**{ip}** is a Google public DNS server located in Mountain View, "
            "California. Owned by Google LLC (AS15169). No threat indicators found."
        )
        async for event in stream_text(summary):
            yield event
        yield {"type": "done"}
        return

    # --- default ---
    default_msg = (
        "I can help you investigate **emails**, **usernames**, **domains**, "
        "and **IP addresses** using 11 specialized OSINT tools. "
        "What would you like to look into?"
    )
    async for event in stream_text(default_msg):
        yield event
    yield {"type": "done"}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenOSINT",
        version=_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # GET /api/health
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health():
        ai_backend, ollama_host, ollama_reachable = _get_ai_backend()
        return {
            "status": "ok",
            "version": _VERSION,
            "setup_complete": _is_setup_complete(),
            "ai_backend": ai_backend,
            "ollama_host": ollama_host,
            "ollama_reachable": ollama_reachable,
        }

    # ------------------------------------------------------------------
    # GET /api/tools
    # ------------------------------------------------------------------

    @app.get("/api/tools")
    async def list_tools():
        result = []
        for meta in _TOOL_CATALOG:
            available, reason = _check_available(meta)
            result.append(
                {
                    "name": meta["name"],
                    "description": meta["description"],
                    "input_label": meta["input_label"],
                    "input_placeholder": meta["input_placeholder"],
                    "category": meta["category"],
                    "icon": meta.get("icon", ""),
                    "available": available,
                    "unavailable_reason": reason,
                }
            )
        return result

    # ------------------------------------------------------------------
    # POST /api/run/{tool_name}
    # ------------------------------------------------------------------

    @app.post("/api/run/{tool_name}")
    async def run_tool(tool_name: str, req: RunRequest):
        if tool_name not in _RUNNERS:
            return JSONResponse(
                {
                    "status": "error",
                    "output": f"Unknown tool: {tool_name}",
                    "tool": tool_name,
                    "elapsed": 0,
                },
                status_code=404,
            )
        start = time.monotonic()
        try:
            result = await _RUNNERS[tool_name](req.input, req.timeout)
            elapsed = round(time.monotonic() - start, 2)
            return {"status": "ok", "output": result, "tool": tool_name, "elapsed": elapsed}
        except Exception as exc:
            elapsed = round(time.monotonic() - start, 2)
            return JSONResponse(
                {"status": "error", "output": str(exc), "tool": tool_name, "elapsed": elapsed},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/stream/{tool_name}  — Server-Sent Events
    # ------------------------------------------------------------------

    @app.get("/api/stream/{tool_name}")
    async def stream_tool(request: Request, tool_name: str, input: str, timeout: int = 120):
        if tool_name not in _RUNNERS:

            async def _err() -> AsyncIterator[dict]:
                yield {"data": json.dumps({"line": f"Unknown tool: {tool_name}", "done": False})}
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": 0})}

            return EventSourceResponse(_err(), ping=15)

        async def event_gen() -> AsyncIterator[dict]:
            yield {
                "data": json.dumps({"line": f"[*] Running {tool_name} on: {input}", "done": False})
            }
            yield {"data": json.dumps({"line": "", "done": False})}
            start = time.monotonic()
            try:
                result = await _RUNNERS[tool_name](input, timeout)
                elapsed = round(time.monotonic() - start, 2)
                for line in result.splitlines():
                    if await request.is_disconnected():
                        return
                    yield {"data": json.dumps({"line": line, "done": False})}
                    await asyncio.sleep(0.012)
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": elapsed})}
            except Exception as exc:
                elapsed = round(time.monotonic() - start, 2)
                yield {"data": json.dumps({"line": f"Error: {exc}", "done": False})}
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": elapsed})}

        return EventSourceResponse(event_gen(), ping=15)

    # ------------------------------------------------------------------
    # GET /api/chat/test — lightweight backend connectivity check
    # ------------------------------------------------------------------

    @app.get("/api/chat/test")
    async def chat_test():
        has_claude = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        if has_claude:
            return {"status": "ok", "backend": "claude", "ollama_reachable": None}

        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            if _httpx is not None:
                async with _httpx.AsyncClient(timeout=1.5) as client:
                    r = await client.get(f"{ollama_host}/api/tags")
                    reachable = r.status_code == 200
            else:
                raw = await asyncio.to_thread(
                    lambda: _requests.get(f"{ollama_host}/api/tags", timeout=1.5)
                )
                reachable = raw.status_code == 200
        except Exception:
            reachable = False

        return {
            "status": "ok",
            "backend": "ollama" if reachable else "none",
            "ollama_reachable": reachable,
        }

    # ------------------------------------------------------------------
    # POST /api/chat  — AI chat with tool_use, SSE streaming
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        messages: list[dict] = []
        for h in req.history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": req.message})

        use_ollama = req.model == "ollama" or not os.environ.get("ANTHROPIC_API_KEY", "").strip()
        use_ollama = use_ollama and bool(req.ollama_host)

        async def generate():
            if use_ollama:
                gen = _stream_ollama(messages, req.ollama_host, req.ollama_model)
            else:
                gen = _stream_claude(messages)

            async for event in gen:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # POST /api/setup  — save API keys to .env
    # ------------------------------------------------------------------

    @app.post("/api/setup")
    async def setup(request: Request):
        body: dict = await request.json()
        env_path = _ROOT / ".env"
        existing: dict[str, str] = {}
        if env_path.exists():
            for raw in env_path.read_text().splitlines():
                line = raw.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()
        for k, v in body.items():
            v_str = str(v).strip()
            if v_str:
                existing[k.strip()] = v_str
                os.environ[k.strip()] = v_str
        env_path.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # POST /api/demo/chat  — pre-scripted demo stream, no API key needed
    # ------------------------------------------------------------------

    @app.post("/api/demo/chat")
    async def demo_chat(req: ChatRequest):
        async def generate():
            async for event in _demo_chat_stream(req.message):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # Static mounts — docs, then catch-all for frontend
    # ------------------------------------------------------------------

    docs_path = _ROOT / "docs"
    if docs_path.exists():
        app.mount("/docs", StaticFiles(directory=str(docs_path), html=True), name="docs")

    web_static = _WEB_DIR / "static"
    if web_static.exists():
        app.mount("/static", StaticFiles(directory=str(web_static)), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        index = _WEB_DIR / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text())
        return HTMLResponse(
            "<h1>OpenOSINT</h1>"
            "<p><strong>web/index.html not found.</strong></p>"
            "<p>If you installed via pip, this is a packaging issue — please report it at "
            "https://github.com/OpenOSINT/OpenOSINT/issues</p>"
            "<p>If running from source, make sure <code>openosint/web/index.html</code> exists.</p>",
            status_code=404,
        )

    return app


# ---------------------------------------------------------------------------
# Entry points (called from cli.py)
# ---------------------------------------------------------------------------


async def serve_async(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run uvicorn within an already-running asyncio event loop."""
    from dotenv import load_dotenv

    load_dotenv()
    app = create_app()
    _print_banner(host, port)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", loop="none")
    server = uvicorn.Server(config)
    await server.serve()


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Standalone blocking entry point."""
    from dotenv import load_dotenv

    load_dotenv()
    app = create_app()
    _print_banner(host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _print_banner(host: str, port: int) -> None:
    display = "localhost" if host in ("0.0.0.0", "") else host
    print(f"[*] OpenOSINT {_VERSION} web server")
    print(f"[*] App  → http://{display}:{port}/")
    print(f"[*] Docs → http://{display}:{port}/docs/")
    print("[*] Press Ctrl+C to stop.")
