# API keys

The default flow needs none. When a keyed tool would add something, tell the user which variable to set (shell environment, `.env`, or the MCP client's `env` block). Never ask them to paste a key into the chat.

| Tool | Variable | Adds |
|---|---|---|
| `search_shodan` | `SHODAN_API_KEY` | Open ports and banners Shodan already indexed |
| `search_censys` | `CENSYS_API_ID` + `CENSYS_SECRET` | Hosts and certificates Censys already indexed |
| `search_virustotal` | `VIRUSTOTAL_API_KEY` | Reputation for a domain, IP or hash |
| `search_abuseipdb` | `ABUSEIPDB_API_KEY` | Abuse reports for an IP |
| `search_breach` | `HIBP_API_KEY` | Breach exposure for an email address |
| `search_github` | `GITHUB_TOKEN` (optional) | Higher GitHub rate limit |
| `search_ip` | `IPINFO_TOKEN` (optional) | Higher ipinfo rate limit |
| `search_footprint`, `search_dorks_live` | `BRIGHTDATA_API_KEY` | Live search-engine results (target is sent to Bright Data) |

Wording when a key is missing: "`search_shodan` needs `SHODAN_API_KEY`. Set it and I will rerun it; the findings below do not include Shodan data."
