---
title: "OpenOSINT documentation"
label: "Overview"
seo_title: "OpenOSINT documentation | CLI, MCP server and web UI"
description: "Docs for OpenOSINT %%VERSION%%, an MIT-licensed engine with %%TOOL_COUNT%% passive OSINT tools. Use it as a CLI, an MCP server or a local web UI."
group: Get started
order: 1
---
OpenOSINT is an open-source engine for passive checks of public information. It wraps %%TOOL_COUNT%% investigation tools (DNS, WHOIS and RDAP, IP intelligence, breach lookups, GitHub, news and more) behind one interface. An AI agent can pick and chain the tools for you, or you can run each one directly.

This documentation covers version **%%VERSION%%**. The code is MIT licensed and needs Python 3.10 or newer.

## Who it is for

Security researchers, analysts and developers who want repeatable lookups on domains, IP addresses, emails and usernames, with every finding shown next to the tool call that produced it. Use it only on targets you are allowed to investigate; see [Safety](/docs/safety/).

## Three ways to use it

- **[CLI and REPL](/docs/quickstart/)**: direct subcommands such as `openosint dns example.com`, plus an interactive session where the agent chooses the tools.
- **[MCP server](/docs/mcp/)**: the same tools inside Claude Desktop, Claude Code, Cursor or any MCP client.
- **[Web UI](/docs/web-ui/)**: a local browser app with chat, a news globe and a graph view.

## How it behaves

- **Passive by default.** Tools that touch the target or send many requests from your IP are off until you opt in. See [Safety](/docs/safety/).
- **Real results only.** Tools run as Python code; only their actual output reaches the model. AI summaries are leads to verify, not proof.
- **Most tools need no key.** Some need an API key; the [configuration](/docs/configuration/) page lists which.

## Where to go next

1. [Install](/docs/install/) it.
2. Run your first investigation in the [quickstart](/docs/quickstart/).
3. Browse the [tools reference](/tools/).

For a hosted version with no setup, see [Monitor and Diligence](https://app.openosint.tech/?utm_source=openosint.tech&utm_medium=referral&utm_campaign=docs).
