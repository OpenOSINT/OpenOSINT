---
title: "Use OpenOSINT as an MCP server"
label: "MCP server"
seo_title: "OpenOSINT MCP server for Claude Desktop and Claude Code"
description: "Add the openosint-mcp server to Claude Desktop, Claude Code, Cursor or any MCP client with uvx. Config snippets, API keys, and how to enable active tools."
group: Use
order: 4
---
The MCP server exposes the OpenOSINT tools to any [Model Context Protocol](https://modelcontextprotocol.io/) client over stdio. The client's own model drives the tools; OpenOSINT only runs them and returns real output.

## Requirements

Install [uv](https://docs.astral.sh/uv/). `uvx` then fetches and runs OpenOSINT on demand, so there is no separate install step. The command every client runs is the same:

```bash
uvx --from openosint openosint-mcp
```

If you installed the package with pip, the executable is `openosint-mcp`.

## Claude Code

```bash
claude mcp add openosint -- uvx --from openosint openosint-mcp
claude mcp list
```

Add API keys with `-e` flags before the `--`:

```bash
claude mcp add openosint -e SHODAN_API_KEY=your-key -e HIBP_API_KEY=your-key -- uvx --from openosint openosint-mcp
```

## Claude Desktop

Edit `claude_desktop_config.json` and restart the app. On macOS it is at `~/Library/Application Support/Claude/`, on Windows at `%APPDATA%\Claude\`.

```json
{
  "mcpServers": {
    "openosint": {
      "command": "uvx",
      "args": ["--from", "openosint", "openosint-mcp"],
      "env": {
        "SHODAN_API_KEY": "your-key"
      }
    }
  }
}
```

## Cursor and other clients

Any client that can launch a stdio MCP server takes the same command and arguments. For Cursor, put the JSON above in `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project).

Desktop apps often start with a minimal `PATH` that does not include `uvx`. If the server fails to start, replace `"uvx"` with the absolute path printed by `which uvx` (macOS, Linux) or `where uvx` (Windows).

## API keys

Put keys in the client's `env` block, as above. The server is started by the client with an unrelated working directory, so a `.env` file is not picked up reliably. To use one anyway, point to it:

```json
"env": { "OPENOSINT_ENV_FILE": "/absolute/path/to/.env" }
```

The [configuration page](/docs/configuration/) lists every key and which tools need it.

## Passive tools only, by default

`tools/list` returns only the passive tools, so the client's model never sees the noisy ones. Each tool description carries its noise label. To also expose the tools that touch the target or are noisy, do one of:

- append `--allow-active` after `openosint-mcp`;
- set `OPENOSINT_ALLOW_ACTIVE=1` in the `env` block.

Read the [noise table](/docs/safety/) before you do.

The server does not cap how many tools your client calls. Only `investigate_multi`, which runs several targets at once, shares one budget of %%MAX_CALLS_MULTI%% calls by default.

## Pin a version

```bash
uvx --from openosint==%%VERSION%% openosint-mcp
```

From a source checkout, use `"command": "python", "args": ["-m", "openosint.mcp_server"]`.

## Example prompt

```text
Investigate example.com. Check its DNS and email authentication, then its registration.
```
