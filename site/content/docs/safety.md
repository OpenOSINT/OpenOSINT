---
title: "Safety and responsible use"
label: "Safety"
seo_title: "OpenOSINT safety: passive mode, tool-call cap, noise labels"
description: "OpenOSINT is passive by default. How active tools are enabled, the per-request tool-call cap of %%MAX_CALLS%%, what each noise label means, and responsible use."
group: Reference
order: 7
---
OpenOSINT is built so that a default install does not touch your target and cannot run away with requests.

## Passive by default

In passive mode agents and MCP clients are only offered tools that query third-party data sources or compute locally. Tools that touch the target's infrastructure, or send many requests about it from your IP, are not just refused: they are not offered to the model at all, and an MCP client does not see them in `tools/list`. If a disabled tool is requested anyway, it returns a structured `disabled_in_passive_mode` result that says how to enable it.

Enable active tools only when you mean to:

| Where | How |
|---|---|
| CLI and REPL | `openosint --allow-active ...` |
| Any process | `OPENOSINT_ALLOW_ACTIVE=1` |
| Web UI | Settings, "Enable active tools" (local installs only) |
| MCP server | `openosint-mcp --allow-active`, or `OPENOSINT_ALLOW_ACTIVE=1` in the client's `env` |

A publicly reachable or demo web instance can never enable active tools, whatever its settings.

## Tool-call cap

Each user request may spend at most `OPENOSINT_MAX_TOOL_CALLS` tool calls (default %%MAX_CALLS%%); every new message starts a fresh budget. `investigate_multi` shares one cap across all its targets (`OPENOSINT_MAX_TOOL_CALLS_MULTI`, default %%MAX_CALLS_MULTI%%). When the cap is reached the investigation stops with an explicit message and keeps the results so far.

## Noise labels

| Level | Meaning |
|---|---|
| passive | Queries third-party data sources or computes locally. Standard DNS lookups are the one indirect exception: they reach the target's nameservers through your resolver. |
| touches target | Makes requests the target's own infrastructure can see. |
| noisy | High request volume, or requests to many services about the target. Expect rate limits, blocks and possible alerts. |
| unverified | Network behaviour not yet confirmed with a traffic capture. Treated as non-passive. |
| inherits | A fan-out tool that only runs what the current mode allows. |

What each tool actually sends, generated from the code:

<!-- gen:noise -->

## Responsible use

- **Passive is not private.** Every service you query sees your search, and usually your API key or IP address. Treat lookups on Shodan, Have I Been Pwned, VirusTotal, Bright Data and similar services as visible to those providers.
- **Authorization.** Investigate only targets you are permitted to. Local laws on personal data differ; the legal and operational responsibility is yours. Read the [disclaimer](https://github.com/OpenOSINT/OpenOSINT/blob/main/DISCLAIMER.md).
- **Verify the output.** Tool results are real; the AI's reading of them is not proof. Check a finding at its source before you act on it.
- **Stored personal data.** The optional [entity graph](/docs/entity-graph/) keeps data on your disk. You are its controller.
