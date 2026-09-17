# Release runbook — username-recon & domain-recon

Manual steps only. Nothing here is automated — run each step yourself, in order, and confirm the result before moving to the next one. Nothing gets published by running tests or by any Claude Code session.

---

## 1. Merge PRs

Merge the `apify-cloud-actors` branch's PR(s) into `main` on GitHub. Confirm CI is green before merging.

## 2. Tag `v2.29.0` — publishing to PyPI is fully automated from here

```bash
git checkout main && git pull
git tag v2.29.0
git push origin v2.29.0
```

That's it — do not run `python -m build` / `twine upload` yourself. Pushing the tag triggers `.github/workflows/release.yml`, which builds the package, publishes to PyPI via trusted publishing (OIDC, no token/twine involved), creates the GitHub Release, waits for the new version to actually appear on PyPI, and publishes to the MCP Registry.

Watch it run: open the repo's **Actions** tab → the "Release" workflow run for the `v2.29.0` tag (or `gh run watch` from the CLI right after pushing the tag). Wait for it to go green before moving to step 3 — it also confirms the "Publish to MCP Registry" workflow (triggered separately by the GitHub Release this creates) succeeds or safely no-ops on the already-published version.

Confirm on PyPI: `pip index versions openosint` should list `2.29.0`. Both Actors' `requirements.txt` already pin `openosint >= 2.29.0`, so their Docker builds will pull this release automatically — no Actor-side code change needed for this step.

## 3. `apify login`, then `apify push` for both Actors

```bash
apify login   # opens a browser, or paste an API token from the Apify Console
```

```bash
cd actors/username-recon
apify push
```

```bash
cd actors/domain-recon
apify push
```

`apify push` builds using `.actor/Dockerfile`, which installs only from `requirements.txt` against the real PyPI `openosint` package — it never references `local-wheels/` or `.actor/Dockerfile.local` (those exist only for `build-local.sh`). So step 2 must be done first or the build will fail to resolve `openosint>=2.29.0`.

## 4. Apify Console — pricing, categories, SEO

For **each** Actor, in the Apify Console under **Publication**:

### Monetization → Pay per event

**openosint-username-recon**

| Event name | Price |
|---|---|
| `username-scanned` | $0.04 |

See `actors/username-recon/PRICING.md` for the reasoning.

**openosint-domain-recon**

| Event name | Price |
|---|---|
| `domain-report` | $0.02 |

See `actors/domain-recon/PRICING.md` for the reasoning.

### Categories

Apify's exact category list changes over time — check what's currently offered in the Console dropdown and pick the closest match rather than forcing one that doesn't exist. As of this writing, the closest fits are:
- `openosint-username-recon` → **"Social media"** (fall back to "Developer tools" if not offered)
- `openosint-domain-recon` → **"Security"** (fall back to "Developer tools" if not offered)

### SEO title and description

Paste these into the Console's **SEO title** / **SEO description** fields verbatim (both are within Apify's limits — title under 60 chars, description under 160 chars):

**openosint-username-recon**
- Title (47 chars): `Username Search & Social Account Finder | OSINT`
- Description (139 chars): `Search hundreds of sites for a username and find every account that exists. OSINT, fraud checks, brand protection — AI-agent ready via MCP.`
- Keywords covered: username search, social media account finder, OSINT

**openosint-domain-recon**
- Title (46 chars): `Email Security Check — SPF, DMARC, DKIM Lookup`
- Description (143 chars): `Check any domain's SPF, DMARC, and DKIM email security — graded A-F, plus RDAP domain lookup. For vendor due diligence and phishing prevention.`
- Keywords covered: email security check, SPF DMARC DKIM checker, domain lookup

## 5. Verify with a paid-plan-like test run and a max total charge

In the Console, run each Actor with:
- **Max total charge (USD)** set to a small nonzero value (e.g. $0.20 for username-recon — 5 usernames at $0.04, or $0.10 for domain-recon — 5 domains at $0.02), to confirm the charge-limit-stop logic actually engages and the run ends with a clean status message rather than an error.
- Real input:
  - username-recon: `{"usernames": ["octocat", "torvalds", "johndoe", "octocat2", "bobsmith"]}` — 5 usernames so the low max-charge cap is actually hit before the last one.
  - domain-recon: `{"domains": ["example.com", "github.com", "cloudflare.com", "wikipedia.org", "apify.com"]}`
- Confirm: the dataset has the expected items, the run's **Pricing** tab in the Console shows the correct number of charged events at the correct price, and the run stops cleanly (not `FAILED`) once the max charge is reached.

Locally, before spending real money in the Console, the same shape of run can be dry-run without Docker (local runs never touch real Apify billing — `Actor.charge()` and `Actor.push_data()` just log a "not using pay-per-event" warning and continue):

```bash
cd actors/username-recon && apify run --purge
cd actors/domain-recon && apify run --purge
```

## 6. Update the README Cloud table and `docs/cloud/index.html` with the real Store URLs

Once both Actors are live on the Store, add one row each to:

- `README.md` — the `<!-- Add one row per new Actor here as they ship -->` marker inside the **☁️ OpenOSINT Cloud** table (around line 33). Follow the existing row's format, e.g.:
  ```
  | OpenOSINT Username Recon | one or more usernames | every platform where each is registered | [▶ Run on Apify](https://apify.com/complete_analogy/openosint-username-recon?utm_source=github&utm_medium=readme&utm_campaign=cloud-table) |
  | OpenOSINT Domain Recon | one or more domains | A-F email-security grade, RDAP data, dork URLs | [▶ Run on Apify](https://apify.com/complete_analogy/openosint-domain-recon?utm_source=github&utm_medium=readme&utm_campaign=cloud-table) |
  ```
- `docs/cloud/index.html` — the matching `<!-- Add one row per new Actor here as they ship -->` marker (around line 129), same two rows, `utm_source=site&utm_medium=cloud&utm_campaign=actors-table` instead.

Use the **real** Store slugs from the Console (they should match `openosint-username-recon` / `openosint-domain-recon` if the `.actor/actor.json` `name` fields are unchanged) — don't guess the URL. Every outbound link must carry UTM parameters, per this repo's sponsorship-work convention.
