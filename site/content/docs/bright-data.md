---
title: "Using OpenOSINT with Bright Data"
label: "Bright Data"
seo_title: "Using OpenOSINT with Bright Data: setup, cost, errors"
description: "Set up the Bright Data tools in OpenOSINT: guided setup, manual steps, example output, cost and what each error means."
group: Use
order: 7.5
---
**Referral link.** The Bright Data signup link on this page is a referral link: OpenOSINT earns a commission if you sign up through it, at no extra cost to you. The tools work the same either way, and every other tool in OpenOSINT needs no Bright Data account.

Three OpenOSINT tools run through [Bright Data](https://brightdata.com):

- `search_dorks_live` and `search_footprint` fetch Google results through the Bright Data **SERP API**.
- `scrape_url` fetches pages that block direct access through **Web Unlocker**. It is an active tool and also needs `--allow-active`.

Using them sends your targets (the search queries and URLs) to Bright Data. Read [Safety](/docs/safety/) first.

## Cost

One request is one credit. Bright Data's free tier is 5,000 credits a month, shared across its products, and needs no credit card. `search_dorks_live` sends one request per dork (5 by default) and `search_footprint` one per query (3 by default), so `--max-dorks` and `--max-queries` set what a run costs.

## Fastest setup

```bash
openosint setup brightdata
```

It asks before every change:

1. Asks whether you already have an account, and opens the signup page only if you say yes.
2. Reads your API token without echoing it, and checks it by listing your zones.
3. **Reuses zones you already have.** A SERP API zone and a Web Unlocker zone in your account are offered as the default, so you only press Enter.
4. Creates a missing zone only after an explicit yes. If your token is not allowed to create zones (HTTP 403), it says so once, stops offering, and prints the dashboard steps below instead.
5. Saves what you confirmed to `config.env`, readable only by you, and never replaces a saved value without asking.

It needs an interactive terminal. If you stop halfway, run it again to finish the other zone.

## Manual setup

1. [Sign up for Bright Data](%%BRIGHTDATA_LINK_DOCS%%){: target="_blank" rel="sponsored noopener" }, or log in. Using this at work? Sign up with your work email so you can invite teammates and send invoices to your company. If you already have an account, skip this.
2. Copy your API token from [brightdata.com/cp/setting/users](https://brightdata.com/cp/setting/users). It goes in `BRIGHTDATA_API_KEY`.
3. Create a **SERP API** zone in your dashboard. Its name goes in `BRIGHTDATA_SERP_ZONE`.
4. Create a **Web Unlocker** zone. Its name goes in `BRIGHTDATA_UNLOCKER_ZONE`.

Set the three values where your interface reads them:

| Interface | Where |
|---|---|
| CLI and REPL | The environment, or `config.env` in `~/.openosint/` (or `$OPENOSINT_HOME`) |
| MCP server | The `env` block of the `openosint` server in your MCP client config, then restart the server |
| Web UI | Settings, which saves to `config.env` |

See [Configuration](/docs/configuration/) for the load order and [MCP server](/docs/mcp/) for the `env` block. `OPENOSINT_NO_REFERRAL_LINKS=1` turns the referral links inside OpenOSINT's own messages into a plain `https://brightdata.com`.

## Example output

The text below is what the tools return, as printed by the code. The CLI frames it in a `SCAN RESULTS` banner; an MCP client or the agent receives it as is. The results are placeholders from the reserved `example.com` domain, not a live capture.

### `search_dorks_live`

```bash
openosint search-dorks-live example.com --max-dorks 1
```

```text
Bright Data live dork search for 'example.com' (1 queries):

[+] Dork: "example.com"
    Title:   Example Domain
    URL:     https://www.example.com/
    Snippet: This domain is for use in illustrative examples in documents.

    Title:   Example Domain - Example Org
    URL:     https://www.example.org/about
    Snippet: Another reserved example domain.
```

### `search_footprint`

```bash
openosint footprint example.com --max-queries 1
```

```text
[Footprint] example.com  |  type: domain  |  1 query

[+] Query 1/1: site:example.com
    1. Example Domain
       URL:     https://www.example.com/
       Display: www.example.com
       Snippet: This domain is for use in illustrative examples in documents.

    2. Example Domain - Example Org
       URL:     https://www.example.org/about
       Display: www.example.org
       Snippet: Another reserved example domain.

── Discovered URLs ──────────────────────────────────────────
[Footprint] URL: https://www.example.com/
[Footprint] Domain: example.com
[Footprint] URL: https://www.example.org/about
[Footprint] Domain: example.org
```

The `[Footprint]` lines at the end feed the entity graph.

### `scrape_url`

```bash
openosint --allow-active scrape https://example.com
```

```text
[Web Unlocker] URL: https://example.com

# Example Domain

This domain is for use in illustrative examples in documents.
```

When the site itself answers with an error status, `scrape_url` reports it and still returns the body. A removed page or profile can be a finding, so this is not a failure:

```text
[Web Unlocker] URL: https://example.com/old-page
[Target returned HTTP 404]

# Not Found

The requested page does not exist.
```

## Usage and limits

- Check your remaining credits at [brightdata.com/cp/billing/overview](https://brightdata.com/cp/billing/overview) and add funds at [brightdata.com/cp/billing](https://brightdata.com/cp/billing).
- At the end of the free credits, requests stop. You are not charged unless you have deposited funds. Credits renew on the 1st of each month and do not roll over.
- Accounts without deposited funds are limited to 1,000 requests a minute.

## Troubleshooting

These tools stop at the first account-level failure instead of retrying every query. The messages are printed by the code, so you can search for them:

```text
Bright Data rejected the API token (HTTP 401, body='...'). Check or regenerate it at https://brightdata.com/cp/setting/users; BRIGHTDATA_API_KEY takes the token only.
```

The token is wrong, revoked or expired.

```text
Bright Data zone 'NAME' not found. Create a SERP API zone in your Bright Data dashboard, or set BRIGHTDATA_SERP_ZONE to the name of an existing one.
```

For `scrape_url` the message says Web Unlocker and `BRIGHTDATA_UNLOCKER_ZONE`.

```text
Bright Data reported a usage limit (client_10100). This may mean your free credits are used up — check https://brightdata.com/cp/billing. Requests resume when credits renew on the 1st of the month or after you add funds.
```

Bright Data does not document this response, so the message says "may".

```text
Bright Data's API returned HTTP 502. This is a Bright Data-side error, not a problem with your key or zone. Retry in a few minutes; if it persists, contact Bright Data support.
```

The same applies to HTTP 500, 503 and 504.

```text
Bright Data 403 reject_block — the target blocked the request (captcha or protection page); a retry may succeed
```

The website refused the fetch. Some targets cannot be fetched.

More entries are in [Troubleshooting](/docs/troubleshooting/).

## More

Bright Data's own walkthrough: [OpenOSINT with Bright Data](https://brightdata.com/blog/how-tos/openosint-with-bright-data).
