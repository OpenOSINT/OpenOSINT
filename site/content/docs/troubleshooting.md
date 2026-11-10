---
title: "Troubleshooting"
label: "Troubleshooting"
seo_title: "OpenOSINT troubleshooting: common errors and fixes"
description: "Fixes for common OpenOSINT errors: missing API key, ANTHROPIC_API_KEY not set, disabled_in_passive_mode, port in use, Host not allowed, tool not installed."
group: Reference
order: 12
---
Each entry below is a message OpenOSINT really prints.

## `ANTHROPIC_API_KEY is not set.`

The REPL needs an AI provider. Export a key (`export ANTHROPIC_API_KEY=sk-ant-...`), or start with `--provider ollama` or `--provider openai`. Direct commands such as `openosint dns example.com` need none.

## `Scan error: ... cannot run: ... not set.` and `[key_required]`

A tool needs an API key you have not provided. The message names the variable and a link to get one, and the last line says where to put it for the interface you are using: the environment or `config.env` on the CLI, the `env` block of the MCP client config for the MCP server (restart it afterwards), or Settings in the web UI. For the Bright Data tools it also lists the dashboard steps for exactly the settings you are missing (token, then a SERP API or Web Unlocker zone). `scrape_url` also needs `--allow-active`; if both are missing you get one message listing both. See [Configuration](/docs/configuration/).

## `Bright Data ...` errors from `search_dorks_live`, `search_footprint` and `scrape_url`

These tools stop at the first account-level failure instead of retrying every query, and the message says which kind it is:

- **`rejected the API token (HTTP 401)`**: the token is wrong, revoked or expired. Check or regenerate it in your Bright Data account settings, and set `BRIGHTDATA_API_KEY` to the token only.
- **`zone 'NAME' not found`**: the zone does not exist in your account. Create a SERP API zone (for `search_dorks_live` and `search_footprint`) or a Web Unlocker zone (for `scrape_url`), or set `BRIGHTDATA_SERP_ZONE` / `BRIGHTDATA_UNLOCKER_ZONE` to an existing zone name.
- **`reported a usage limit (client_10100) ... may mean your free credits are used up`**: a best-effort hint. Bright Data's free tier is 5,000 credits a month, shared across its products and renewed on the 1st; without deposited funds requests stop at the limit. Check usage and add funds on the Bright Data billing page. Bright Data does not document the exact response, so this message says "may".
- **`Bright Data-side error`** (HTTP 500, 502, 503 or 504 from `api.brightdata.com`): not your key or zone. Retry in a few minutes; if it persists, contact Bright Data support.
- **`the target blocked the request`** (a CAPTCHA or protection page): the website refused the fetch. A retry can help; some targets cannot be fetched.
- **`[Target returned HTTP 404]`** (or 410, 401, 5xx) at the top of a `scrape_url` result: not a failure. The site itself answered with that status, and the page body follows. A removed page or profile can be a finding in its own right.

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

## Limitations

- **Authorized use only.** OpenOSINT queries public and semi-public sources. It does not bypass authentication, exploit systems, or access anything you are not already entitled to see. You are responsible for the law and for the terms of service of every source you query. See the [disclaimer](https://github.com/OpenOSINT/OpenOSINT/blob/main/DISCLAIMER.md).
- **No aggregation guarantees.** Each tool reports what its upstream source currently returns. A negative result (no breach found, no accounts found) means the source did not report a match, not that no exposure exists.
- **Many tools depend on third-party services you do not control.** The keyed tools (Shodan, VirusTotal, Censys, AbuseIPDB, IP2Location, HaveIBeenPwned and the three [Bright Data](%%BRIGHTDATA_LINK_DOCS%%)-backed tools) are subject to that provider's uptime, rate limits and pricing. Free tiers are small; heavy use needs a paid plan with the provider, not with OpenOSINT. The Bright Data link is a referral link: OpenOSINT earns a commission if you sign up through it, at no extra cost to you.
- **Local binaries are unsandboxed subprocesses.** `holehe`, `sherlock`, `sublist3r` and `phoneinfoga` run as external processes on your machine. Keep them updated yourself; OpenOSINT does not patch or vet them.
- **The entity graph module is additive, not authoritative.** `same_as` links are scored candidates for human review, not verified identity matches. See [Entity graph](/docs/entity-graph/).
- **AI output is a lead, not proof.** The agent can only call OpenOSINT's tools (by default only the passive ones). Tool results come from real executions and are shown with the tool call that produced them, but the model can still misread, misattribute or over-weight a result, and its tool selection can be wrong or incomplete for a given target. Check the raw tool output before acting on a conclusion.

## Still stuck

Run with `-v` for debug logging, then [open an issue](https://github.com/OpenOSINT/OpenOSINT/issues) with the command and the message. Remove any keys first.
