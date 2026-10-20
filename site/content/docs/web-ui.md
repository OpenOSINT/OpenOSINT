---
title: "Web UI"
label: "Web UI"
seo_title: "OpenOSINT web UI: chat, globe and graph on your machine"
description: "Run openosint web to get a local browser app with AI chat, a worldwide news globe and a graph view. Default port 8080, loopback only, no account needed."
group: Use
order: 5
---
The web UI is a local browser app. It starts without any API key; keyless tools work at once and the chat needs a provider.

## Start it

```bash
openosint web
```

Or without installing: `uvx openosint web`. The server prints its address and opens your browser. By default it listens on `http://127.0.0.1:8080/`.

| Option | Effect |
|---|---|
| `--port N` | Use another port. If 8080 is busy, OpenOSINT exits and suggests the next one. |
| `--no-browser` | Do not open a browser tab. |
| `--host HOST` | Bind to another address (default `127.0.0.1`). |
| `--allow-remote` | Required for any non-loopback host. It exposes the server to your network. |

## The three views

- **Chat.** Ask in plain language. Tool output streams in as result cards, each tied to the tool call that produced it.
- **Globe.** Recent worldwide news, placed on a map by the `search_gdelt_geo` tool. Hold Shift and drag to search only inside an area. Nothing is downloaded until you first use it.
- **Graph.** A view of the entities found in the current chat. It is built in your browser and is separate from the stored [entity graph](/docs/entity-graph/).

## Choose an AI provider

Open Settings and pick one:

| Provider | What you need |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` |
| Ollama (local) | A running [Ollama](https://ollama.com) and `pip install "openosint[ollama]"` |
| OpenAI-compatible | `OPENAI_BASE_URL`, plus `OPENAI_API_KEY` if the server wants one |

Settings can also save tool keys on this computer. They go to `config.env` in the data directory (`~/.openosint/`, or `$OPENOSINT_HOME`), never into the installed package. Values are not logged or sent back to the browser. See [Configuration](/docs/configuration/).

Active tools are off by default. On a local install, Settings has an "Enable active tools" switch; a public or demo instance can never enable them. See [Safety](/docs/safety/).

## Reaching it by another name

On a loopback bind the server only answers requests whose `Host` is `127.0.0.1`, `localhost` or `::1`, and browser requests to `/api/*` must come from the UI's own origin. If you use another host name, such as a LAN name or reverse proxy, set `OPENOSINT_ALLOWED_HOSTS=osint.lan,localhost`. A separate front end on another origin needs `OPENOSINT_ALLOWED_ORIGINS`.

## Docker

```bash
docker compose up --build
```

The container publishes `127.0.0.1:8080` only. A browser reaches the container over the Docker network, so it cannot save keys by default. Set the keys in your compose environment or `.env`, or set `OPENOSINT_SETUP_TOKEN` to a long random string and enter it in the UI's key panel.

## Files it writes

The graph database and session history live in the data directory. The web UI writes no reports; CLI and REPL reports go to `./reports/`.
