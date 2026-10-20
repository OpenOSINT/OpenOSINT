---
title: "Troubleshooting"
label: "Troubleshooting"
seo_title: "OpenOSINT troubleshooting: common errors and fixes"
description: "Fixes for common OpenOSINT errors: missing API key, ANTHROPIC_API_KEY not set, disabled_in_passive_mode, port in use, Host not allowed, tool not installed."
group: Reference
order: 10
---
Each entry below is a message OpenOSINT really prints.

## `ANTHROPIC_API_KEY is not set.`

The REPL needs an AI provider. Export a key (`export ANTHROPIC_API_KEY=sk-ant-...`), or start with `--provider ollama` or `--provider openai`. Direct commands such as `openosint dns example.com` need none.

## `Scan error: ... cannot run: ... not set.` and `[key_required]`

A tool needs an API key you have not provided. The message names the variable and a link to get one. Set it as an environment variable, put it in `config.env` or `.env`, or save it in the web UI under Settings. See [Configuration](/docs/configuration/).

## `disabled_in_passive_mode`

The tool is active (it touches the target or is noisy) and active tools are off. Pass `--allow-active`, set `OPENOSINT_ALLOW_ACTIVE=1`, or use the web UI switch, after reading [Safety](/docs/safety/). A public or demo instance cannot enable them.

## `Tool call limit reached (N calls for this request)`

The per-request cap stopped the investigation. Send another message to continue, or raise `OPENOSINT_MAX_TOOL_CALLS`.

## `Install it with: uv tool install holehe (or: pip install holehe)`

`search_email`, `search_username` and `search_domain` call separate programs (holehe, sherlock, sublist3r). Install the one named and make sure it is on your `PATH`. See [Install](/docs/install/#external-programs).

## `Port 8080 is already in use.`

Another program holds the port. Start the UI on another one: `openosint web --port 8081`.

## `Refusing to bind to '0.0.0.0'`

`openosint web` only listens on loopback unless you opt in with `--allow-remote` (or `OPENOSINT_ALLOW_REMOTE=1`). That exposes every route to your network, so put it behind a firewall or reverse proxy.

## `Host not allowed. Add it to OPENOSINT_ALLOWED_HOSTS.`

You reached the web UI by a name other than `127.0.0.1`, `localhost` or `::1`. Add that name to `OPENOSINT_ALLOWED_HOSTS`, comma-separated.

## `Model '...' not found. Check ANTHROPIC_MODEL`

`ANTHROPIC_MODEL` names a model the API does not know. Fix it or unset it to use the default.

## `[service_unavailable] search_gdelt_geo`

The GDELT news feed was down or returned a bad file. The globe shows a notice; try again later.

## The MCP server will not start in a desktop app

The app launched with a minimal `PATH` and cannot find `uvx`. Use the absolute path from `which uvx` (macOS, Linux) or `where uvx` (Windows) as the `command`. See [MCP server](/docs/mcp/).

## A `.env` file is ignored

`.env` is searched upward from the directory you run `openosint` from. The MCP server has an unrelated working directory, so set `OPENOSINT_ENV_FILE=/absolute/path/to/.env` in the client's `env` block.

## Still stuck

Run with `-v` for debug logging, then [open an issue](https://github.com/OpenOSINT/OpenOSINT/issues) with the command and the message. Remove any keys first.
