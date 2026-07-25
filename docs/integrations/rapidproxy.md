# RapidProxy

> **Sponsored placement.** RapidProxy pays for the "Residential Proxies" slot
> under OpenOSINT's [sponsorship program](../../SPONSORSHIP.md). Inclusion
> here is paid placement, not a technical endorsement — see the
> [disclaimer](index.md#disclaimer).

**RapidProxy has no dedicated `search_*` tool in this codebase.** Unlike the
other integration pages here, there's no `search_rapidproxy.py` module and no
`RAPIDPROXY_API_KEY`. What actually exists, verified against
[`openosint/proxy.py`](../../openosint/proxy.py), is a generic upstream-proxy
layer that any HTTP/SOCKS5 proxy provider — RapidProxy included — can be
pointed at.

## What it does

[RapidProxy](https://www.rapidproxy.io/) sells residential proxy IPs (90M+
IPs, 200+ countries per their own marketing) for routing outbound HTTP
traffic through consumer-network exit nodes.

## Which OpenOSINT tools it plugs into

Not a bespoke integration — it plugs into OpenOSINT's **generic upstream
proxy** setting: the `--proxy` CLI flag or `OPENOSINT_PROXY_URL` env var
(CLI flag takes precedence — see `get_proxy_url()` in `openosint/proxy.py`).
Point that at your RapidProxy gateway URL and it applies to every tool that
calls `get_requests_proxies()`, `get_aiohttp_proxy()`/`get_aiohttp_connector()`,
`get_subprocess_env()`, or `get_sherlock_proxy_args()`:

`search_abuseipdb`, `search_breach`, `search_censys`, `search_domain`,
`search_email`, `search_github`, `search_ip`, `search_ip2location`,
`search_paste`, `search_phone`, `search_shodan`, `search_username`,
`search_virustotal`.

**Explicitly excluded** (per the docstring in `openosint/proxy.py`):
`search_dns` (raw DNS resolution isn't proxyable via HTTP/SOCKS),
`generate_dorks` (no network call), the Anthropic client in `agent.py`
(LLM traffic, not target-facing), and the Bright Data–backed tools
`scrape_url`, `search_dorks_live`, `search_footprint` (Bright Data is
already the residential-network layer for those; a second proxy in front is
a redundant hop and isn't wired in).

SOCKS5 proxy URLs (`socks5://` / `socks5h://`) require the optional
`openosint[socks]` extra (`pysocks` + `aiohttp-socks`); plain `http://` /
`https://` gateway URLs need nothing extra.

## Credential setup

- Env var: `OPENOSINT_PROXY_URL` (or pass `--proxy` on the command line,
  which overrides the env var)
- Format: a full proxy URL, e.g. `http://user:pass@host:port` or
  `socks5://user:pass@host:port`
- RapidProxy gateway hostname/port/credential format: **TODO — verify
  against RapidProxy's own dashboard/docs before publishing**, this
  codebase has no RapidProxy-specific constant to confirm it against.
- Verify it's working: `openosint proxy-test` prints your exit IP via
  `https://api.ipify.org`, using the same `get_requests_proxies()` path the
  other tools use.

## Working example

```bash
export OPENOSINT_PROXY_URL=http://user:pass@<rapidproxy-gateway-host>:<port>  # TODO: real RapidProxy gateway value
openosint proxy-test
openosint ip2location 8.8.8.8   # now routed through the RapidProxy gateway
```

Equivalent one-off form, without exporting the env var:

```bash
openosint --proxy socks5://user:pass@host:1080 email target@example.com
```

## Rate limits & cost

Bandwidth/IP-rotation limits and pricing are set by RapidProxy, not this
codebase. See their pricing page below.

## Link out

[rapidproxy.io](https://www.rapidproxy.io/?ref=openosint&utm_source=openosint&utm_medium=integration_docs&utm_campaign=rapidproxy)
