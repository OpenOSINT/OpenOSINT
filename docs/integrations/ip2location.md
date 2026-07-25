# IP2Location.io

> **Sponsored placement.** IP2Location.io pays for the "IP Geolocation &
> Threat Intelligence" slot under OpenOSINT's
> [sponsorship program](../../SPONSORSHIP.md). Inclusion here is paid
> placement, not a technical endorsement — see the
> [disclaimer](index.md#disclaimer).

## What it does

[IP2Location.io](https://www.ip2location.io/) is an IP intelligence API:
geolocation, ISP/ASN lookup, and — on its Security Plan — VPN, proxy, Tor
exit-node, and datacenter detection with a threat score.

## Which OpenOSINT tools it plugs into

Dedicated tool: [`openosint/tools/search_ip2location.py`](../../openosint/tools/search_ip2location.py).
`run_ip2location_osint(ip)` calls `GET https://api.ip2location.io/` with your
API key and the target IP, and formats the response (country, region, city,
lat/lon, ZIP, ISP, domain, ASN, and the proxy/VPN/Tor/datacenter/threat
fields). It's exposed three ways:

- **CLI:** `openosint ip2location <IP_ADDRESS> [-t SECONDS]`
- **Agent tool-use:** `search_ip2location` (`openosint/agent.py`)
- **MCP server:** `search_ip2location` tool, parameter `ip` (`openosint/mcp_server.py`)

It also respects OpenOSINT's global upstream-proxy flag — see
`get_requests_proxies()` in [`openosint/proxy.py`](../../openosint/proxy.py) —
so `--proxy` / `OPENOSINT_PROXY_URL` route this lookup too if you've set one.

## Credential setup

- Env var: `IP2LOCATION_API_KEY`
- Get a key: [ip2location.io/pricing](https://www.ip2location.io/pricing?utm_source=openosint&utm_medium=integration_docs&utm_campaign=ip2location)
- Where it's read: `run_ip2location_osint()` falls back to
  `os.environ.get("IP2LOCATION_API_KEY", "")` when no `api_key` argument is
  passed. Add it to `.env` (copy from `.env.example`) or export it directly.
- If unset, the tool returns an error string rather than raising —
  `"Scan error: IP2LOCATION_API_KEY environment variable is not set. Get a
  key at https://www.ip2location.io/pricing"`.

## Working example

```bash
export IP2LOCATION_API_KEY=your_key
openosint ip2location 8.8.8.8
```

```
[IP2Location] IP: 8.8.8.8
[IP2Location] Country: United States (US)
[IP2Location] Region: California
[IP2Location] City: Mountain View
[IP2Location] Latitude: 37.4056
[IP2Location] Longitude: -122.0775
[IP2Location] ISP: Google LLC
[IP2Location] ASN: AS15169 Google LLC
[IP2Location] Proxy: No
[IP2Location] VPN: No
[IP2Location] TOR: No
[IP2Location] Datacenter: Yes
[IP2Location] Threat: clean
```

(Field values above are illustrative — real output depends on your API key's
plan and IP2Location's current data. The VPN/Proxy/Tor/Datacenter/Threat
fields only populate when your key is on the Security Plan; a base-plan key
returns geolocation/ISP/ASN fields only, with those four lines showing "No"
by default per `_format_ip2location_results()`'s handling of a missing
`proxy` dict.)

## Rate limits & cost

The tool surfaces IP2Location's own rate-limit and auth responses directly:
HTTP 400 → invalid request/key, 401 → invalid key, 429 → rate limit exceeded
(`_fetch_ip2location_data()`). Actual quota and pricing tiers are set by
IP2Location, not this codebase — see their pricing page below.

## Link out

[ip2location.io/pricing](https://www.ip2location.io/pricing?utm_source=openosint&utm_medium=integration_docs&utm_campaign=ip2location)
