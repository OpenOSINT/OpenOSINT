---
title: "Quickstart"
label: "Quickstart"
seo_title: "OpenOSINT quickstart: first investigation in 5 minutes"
description: "Run a DNS lookup and an exposure report with no API key, then start the AI REPL with Anthropic, Ollama or an OpenAI-compatible endpoint."
group: Get started
order: 3
---
This takes about five minutes. The first two steps need no API key and no AI provider.

## 1. Run a tool directly

```bash
openosint dns example.com
```

```text
[*] DNS lookup: example.com
============================================================
======================= SCAN RESULTS =======================
============================================================
[DNS] Domain: example.com
[DNS] A: 104.20.23.154, 172.66.147.243
[DNS] NS: elliott.ns.cloudflare.com., hera.ns.cloudflare.com.
[DNS] SPF: v=spf1 -all
[DNS] DMARC: "v=DMARC1;p=reject;sp=reject;adkim=s;aspf=s"
[DNS] DKIM not checked: selector probing is enumeration (needs --allow-active).
```

Output is trimmed here; the addresses will differ. The last line shows passive mode at work: DKIM selector probing is enumeration, so it waits for `--allow-active`.

Add `--json` before the command for structured output: `openosint --json email target@example.com`.

## 2. Grade a domain's external exposure

```bash
openosint exposure example.com --checks email,registration
```

```text
Not graded: only some checks were selected (not run: tls, http_headers).

Checks:
  email         OK       [passive]
  registration  OK       [passive]

Findings:
  [LOW] DMARC has no aggregate report address (dmarc_no_rua)
      fix: Add rua=mailto:... so you receive reports on who sends mail as your domain.
```

These two checks never contact the target. See [Exposure report](/docs/exposure/).

## 3. Start the interactive REPL

The REPL lets an AI agent choose and chain tools. It needs one provider:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
openosint
```

No Anthropic key? Use a local model or any OpenAI-compatible endpoint instead:

```bash
openosint --provider ollama --ollama-model llama3.2
openosint --provider openai --openai-base-url http://localhost:4000/v1
```

The banner shows the version, the provider and the current limits: passive mode and the maximum number of tool calls per request. Then type a target or a question, for example `investigate target@example.com`.

| REPL command | Does |
|---|---|
| a target or question | Starts an investigation |
| `tools` | Lists the available tools |
| `config` | Shows the current configuration |
| `save` | Saves the last report to `reports/` |
| `history` | Browses saved sessions |
| `clear` | Clears conversation memory |
| `help`, `exit` | Shows help, quits |

Every result in the session comes from a real tool call and is shown with that call. Treat the AI's summary as a lead to verify.

## 4. Run a fixed recipe without AI

```bash
openosint playbook domain example.com
```

Playbooks run a fixed list of tools and write a Markdown report. The bundled recipes are `domain`, `ip` and `person`.

## Next

- [Use it from Claude or another MCP client](/docs/mcp/)
- [Add API keys](/docs/configuration/)
- [Understand passive mode](/docs/safety/)
