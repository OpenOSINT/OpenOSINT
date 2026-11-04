---
title: "Agent Skill and Claude Code plugin"
label: "Agent Skill & plugin"
seo_title: "OpenOSINT Agent Skill and Claude Code plugin: install"
description: "Install the OpenOSINT Agent Skill or Claude Code plugin for passive OSINT and exposure checks. Install steps per agent, passive rules and troubleshooting."
group: Get started
order: 2
---
OpenOSINT ships as an [Agent Skill](https://agentskills.io/) and as a Claude Code plugin. An agent that has it can investigate a domain, IP address or organization with real, passive tools, and must cite the tool call behind every finding. It needs [`uv`](https://docs.astral.sh/uv/getting-started/installation/) and network access. It needs no API key and no OpenOSINT AI provider: your agent is the model.

## Install

### Claude Code (plugin)

The plugin bundles both skills and a passive [MCP server](/docs/mcp/), pinned to release %%VERSION%%.

```text
/plugin marketplace add OpenOSINT/OpenOSINT
/plugin install openosint@openosint
/openosint:osint example.com
```

### Any agent that supports Agent Skills

Codex, Gemini CLI, Cursor and other Agent Skills clients can install the skills only (no MCP server):

```bash
npx skills add OpenOSINT/OpenOSINT
```

Then ask your agent in plain words, or invoke the skill by name, for example `/osint example.com` in Claude Code. See [the namespacing note](#osint-or-openosintosint-does-nothing) below.

### By hand

Copy `skills/osint/` and `skills/exposure/` from the [repository](https://github.com/OpenOSINT/OpenOSINT/tree/main/skills) into the skills folder your agent reads (for Claude Code, `~/.claude/skills/` or `.claude/skills/` in a project).

## What the skills do

| Skill | Use it for | What it runs |
|---|---|---|
| `osint` | Recon on a domain, IP address or organization | `exposure`, `dns`, `rdap`, `whois`, `dorks`, `gdelt` and `ip` as the target needs, then a Markdown report |
| `exposure` | "How exposed is this domain?" | `openosint exposure DOMAIN`: an A to F grade for email authentication, TLS, registration and security headers |

Both call the [CLI](/docs/cli/) with `--json` through `uvx --from openosint==%%VERSION%% openosint ...`, so they work on any agent without an MCP server. When the `openosint` MCP server is already connected, the `osint` skill uses its tools instead; they return the same data.

The report has four parts: target and scope, findings (each with its citation), what was not checked or needs a key, and leads to verify.

## The passive rules

The skills hold the agent to these rules:

1. **Passive by default.** No `--allow-active`, no `OPENOSINT_ALLOW_ACTIVE`, and no `scrape`, `username`, `email` or subdomain brute-force unless you ask for that tool by name. If an active tool would help, the agent says so and asks.
2. **Authorization.** Only targets you own or are authorized to assess. If the target looks like a private individual, the agent stops and asks what the legitimate purpose is. OpenOSINT is not designed for people search.
3. **Every finding cites its tool call**, written as `claim [tool: args]`. No citation, no finding.
4. **Summaries are leads, not proof.** The agent reports what a tool returned, and shows errors and empty results as such.
5. **A missing key is named, not skipped.** The agent tells you which variable to set. See [Configuration](/docs/configuration/).

One thing still contacts the target: the `exposure` TLS and header checks make a connection on port 443. For zero contact, ask for `exposure DOMAIN --checks email,registration` (DNS and registry only, not graded). More in [Safety](/docs/safety/).

## Troubleshooting

### `uvx` is not found

Install uv (`curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS and Linux), then open a new terminal so it is on your `PATH`. Desktop apps often start with a minimal `PATH`: for the plugin's MCP server, or any MCP client, use the absolute path from `which uvx` (macOS, Linux) or `where uvx` (Windows) as the command.

### `/osint` or `/openosint:osint` does nothing

Skills installed by the Claude Code plugin are namespaced by the plugin name, so they are `/openosint:osint` and `/openosint:exposure`. Skills installed on their own (`npx skills add`, or copied by hand) are not namespaced, so the same skill is `/osint`. If a command is not found, type `/` and look at the list to see which form you have.

### The first run is slow, or fails offline

`uvx` downloads the pinned OpenOSINT release the first time and caches it. That needs network access; later runs start from the cache.

### A tool says a key is missing

That is expected for the keyed tools (Shodan, Censys, VirusTotal, AbuseIPDB, HaveIBeenPwned). The default flow does not use them. See [Configuration](/docs/configuration/) for the variable names, or [Troubleshooting](/docs/troubleshooting/).

### I want the noisy tools

Ask for the tool by name and set `OPENOSINT_ALLOW_ACTIVE=1` yourself. Read the [noise table](/docs/safety/) first: those tools send traffic from your IP or to the target.
