# Apify Console checklist — manual steps

Nothing here is automated. Work through each Actor in the Console yourself and confirm the result before moving on. This supersedes step 4 of `actors/RELEASE.md` now that both Actors are live — use this file going forward.

---

## 1. Pricing

### OpenOSINT Domain Recon — fix the $0.05 → $0.02 mismatch

The Console currently charges **$0.05** per `domain-report` event. The README, `PRICING.md`, and this branch's marketing copy all say **$0.02** — that was always the intended price, so the Console is wrong, not the docs.

- [ ] Go to **Publication → Monetization → Pay per event** for `openosint-domain-recon`
- [ ] Change `domain-report` from $0.05 to **$0.02**
- [ ] **Read Apify's price-change notice rules before saving.** Apify requires advance notice to existing users before a price *increase* takes effect (typically enforced via a mandatory effective-date delay in the Console UI) — a *decrease* like this one doesn't carry the same restriction, but confirm the current rule in the Console at save time, since Apify has changed this policy before. Since this Actor has 0 runs so far, there's no existing customer to notify either way — do this before it has paying users, not after.

### OpenOSINT Username Recon

- [ ] Confirm `username-scanned` is still $0.04 (no change needed)

### OpenOSINT Email Recon

- [ ] Confirm the three events still read $0.015 (start) / $0.03 (account found) / $0.05 (enriched hit) — no change needed, just verify nothing drifted

## 2. Event titles (Store display text)

Apify pluralizes the event **title** for the Store's "X events" summary line — that's why the Store header currently reads "domain scanneds" / "username scanneds" / "account founds". Fix the titles so the plural reads naturally:

| Actor | Event name (DO NOT CHANGE) | Current title | New title |
|---|---|---|---|
| `openosint-domain-recon` | `domain-report` | *(whatever produces "domain scanneds")* | `domain` → so the Store shows "…/1,000 domains" |
| `openosint-username-recon` | `username-scanned` | *(whatever produces "username scanneds")* | `username` → so the Store shows "…/1,000 usernames" |
| `openosint-email-recon` | *(start event)* | *(existing)* | `run` → "…/1,000 runs" |
| `openosint-email-recon` | *(account-found event)* | *(existing)* | `registered account` → "…/1,000 registered accounts" |
| `openosint-email-recon` | *(enriched-hit event)* | **`Accound Found Enriched`** (typo) | `enriched hit` → "…/1,000 enriched hits" |

- [ ] **Fix the "Accound Found Enriched" typo** on the Email Recon enriched-hit event title
- [ ] Set each title to a plain singular noun (Apify appends the plural + "/1,000" itself) — don't include "found" or "scanned" in the title, that's what produced the awkward plural in the first place
- [ ] **Do not touch the event *name*** (`domain-report`, `username-scanned`, and whatever the three Email Recon event names are) — only the display **title**. The event name is the wire identifier `Actor.charge()` calls in the code; renaming it breaks charging silently (the run keeps executing, but the configured price no longer matches, or the charge call errors). Titles are cosmetic; names are load-bearing.

## 3. Categories & icon

- [ ] `openosint-username-recon` — set category to **"Social media"** (fall back to "Developer tools" if not offered — check the live dropdown, Apify's list changes)
- [ ] `openosint-domain-recon` — set category to **"Security"** (fall back to "Developer tools" if not offered)
- [ ] `openosint-domain-recon` — upload an icon (currently missing). Reuse the OpenOSINT logo mark (`docs/logo.svg`) or a domain/security-themed variant sized per Apify's icon spec
- [ ] Confirm `openosint-email-recon`'s existing category and icon are still set correctly (already published — just a sanity check)

## 4. SEO title / description

Reuse `actors/RELEASE.md` step 4 verbatim — these were already drafted and are within Apify's limits:

**openosint-username-recon**
- Title (47 chars): `Username Search & Social Account Finder | OSINT`
- Description (139 chars): `Search hundreds of sites for a username and find every account that exists. OSINT, fraud checks, brand protection — AI-agent ready via MCP.`

**openosint-domain-recon**
- Title (46 chars): `Email Security Check — SPF, DMARC, DKIM Lookup`
- Description (143 chars): `Check any domain's SPF, DMARC, and DKIM email security — graded A-F, plus RDAP domain lookup. For vendor due diligence and phishing prevention.`

- [ ] Paste both into the Console's **SEO title** / **SEO description** fields
- [ ] `openosint-email-recon` — confirm its existing SEO title/description are still set (already published)

## 5. README

- [ ] Paste `actors/domain-recon/README.md` (already rewritten on this branch) into the Console README editor for `openosint-domain-recon`
- [ ] Paste `actors/username-recon/README.md` (already rewritten on this branch) into the Console README editor for `openosint-username-recon`
- [ ] Paste `marketing/apify/email-recon-README.md` into the Console README editor for `openosint-email-recon` — **verify every `<!-- TOMMASO: ... -->` comment in that file first** and remove the comments once confirmed

## 6. Test run with a max charge cap

For each Actor, run once in the Console with **Max total charge (USD)** set low enough to confirm the cap actually stops the run cleanly, then check the **Pricing** tab to confirm real events were charged at the price set in step 1:

- [ ] `openosint-domain-recon` — max charge **$0.10**, input `{"domains": ["example.com", "github.com", "cloudflare.com", "wikipedia.org", "apify.com"]}` (5 domains × $0.02 = $0.10, so the cap should engage right at the last one)
- [ ] `openosint-username-recon` — max charge **$0.20**, input `{"usernames": ["octocat", "torvalds", "johndoe", "octocat2", "bobsmith"]}` (5 usernames × $0.04 = $0.20)
- [ ] `openosint-email-recon` — max charge **$0.10** (covers the $0.015 start + a couple of account-found events), input a real test email
- [ ] For each: confirm the run ends with a clean status (not `FAILED`), the dataset has the expected items, and the **Pricing** tab shows the correct number of charged events at the correct per-event price
