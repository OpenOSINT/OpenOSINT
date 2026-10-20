---
title: "Configuration"
label: "Configuration"
seo_title: "OpenOSINT configuration: API keys and environment variables"
description: "Every OpenOSINT API key and environment variable, which tools need one, where settings live and the order they load in. Generated from the code."
group: Use
order: 6
---
OpenOSINT starts with zero configuration. A key is only needed by the tool that uses it, plus one AI provider if you use the chat or REPL.

## Where settings come from

Highest priority first. The first source to set a variable wins.

1. Real environment variables.
2. `config.env` in the data directory: `~/.openosint/config.env`, or `$OPENOSINT_HOME/config.env`. The web UI saves keys here with user-only permissions where the OS supports it.
3. A `.env` file, found by searching upward from the directory you run `openosint` from, or the file named by `OPENOSINT_ENV_FILE`.

For the MCP server, set the variables in the client's `env` block; see [MCP server](/docs/mcp/).

## API keys and tokens

This table is generated from the key catalog in the code, so it matches the version you install.

<!-- gen:config-keys -->

The Bright Data key and zones are created in the [Bright Data dashboard](%%BRIGHTDATA_LINK_DOCS%%) (a free tier is available). That is a referral link: OpenOSINT earns a commission if you sign up through it, at no extra cost to you.

These tools need no key: <!-- gen:keyless -->. Tools that are noisy or touch the target also need `--allow-active`; see the [tools reference](/tools/).

## Behaviour settings

| Variable | Default | Purpose |
|---|---|---|
| `OPENOSINT_ALLOW_ACTIVE` | off | `1` enables active tools. Same as `--allow-active`. |
| `OPENOSINT_MAX_TOOL_CALLS` | %%MAX_CALLS%% | Maximum calls per user request. |
| `OPENOSINT_MAX_TOOL_CALLS_MULTI` | %%MAX_CALLS_MULTI%% | One shared cap for `investigate_multi` across all targets. |
| `ANTHROPIC_MODEL` | `%%DEFAULT_MODEL%%` | Model requested from Anthropic. `OPENOSINT_MODEL` still works but is deprecated. |
| `OPENOSINT_HOME` | `~/.openosint` | Data directory: `config.env`, `graph.db`, session history. |
| `OPENOSINT_GRAPH_DB` | `$OPENOSINT_HOME/graph.db` | Overrides only the graph database path. |
| `OPENOSINT_ENV_FILE` | unset | Explicit path to a `.env` file. A bad path is an error. |
| `OPENOSINT_PROXY_URL` | unset | Upstream proxy (`http://`, `https://` or `socks5://`) for web-facing tools. `--proxy` overrides it. |
| `OPENOSINT_ALLOWED_HOSTS` | loopback names | Extra `Host` values the web UI accepts, comma-separated. |
| `OPENOSINT_ALLOWED_ORIGINS` | unset | Extra browser origins allowed to call `/api/*`. |
| `OPENOSINT_ALLOW_REMOTE` | off | `1` is the same as `--allow-remote` for `openosint web`. |
| `OPENOSINT_SETUP_TOKEN` | unset | Lets a non-loopback browser save keys, sent as `X-Setup-Token`. |
| `OPENOSINT_GDELT_WINDOW_HOURS` | 6 (max 24) | Hours of news the globe keeps in memory. |
| `OPENOSINT_GDELT_MAX_ARTICLES` | 30000 | Hard cap on stored news articles; oldest are dropped first. |
| `OPENOSINT_GDELT_USE_PROXY` | off | Route GDELT downloads through the proxy. |

A real environment variable always wins over a saved value, and the web UI says so when that happens.

## A `.env` file

Create a file named `.env` in the directory you work from:

```bash
ANTHROPIC_API_KEY=sk-ant-...
SHODAN_API_KEY=your-key
```
