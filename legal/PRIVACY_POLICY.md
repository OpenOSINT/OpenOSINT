> **Not legal advice.** Starting-point template. Review carefully with a lawyer or DPO before relying on this document. You are in the EU, so the GDPR applies.

# Privacy Policy

**Effective date:** 2026-08-30
**Data controller (where stated below):** Tommaso Bertocchi, contact commercial@openosint.tech.

OpenOSINT is offered through several distinct surfaces, and our role is not the same on all of them. This policy is organized by surface for that reason — read the section for the surface you actually use; do not assume a fact from one section holds on another.

## 1. Public demo (demo.openosint.tech)

This surface has its own, separate **Terms of Use** and **Privacy & Cookie Notice** at https://openosint.tech/demo/terms/ and https://openosint.tech/demo/privacy/. Those documents control for the demo; this section is a summary, not a substitute. In short: the demo is Bring Your Own Key. When you supply your own key, we use it only to fulfil the lookup you request, directly with the provider you chose — we do not use an operator-held key on your behalf, and your key is stored in your browser session only, never on our servers. Breach-data lookups are disabled on the demo outright, regardless of key source.

## 2. Cookies and tracking

This website (openosint.tech) sets no cookies and loads no analytics, advertising, or fingerprinting scripts. There is no Google Analytics, Google Tag Manager, Meta pixel, Hotjar, or any other third-party tracker on any page. No cookie consent banner is shown because none is required — there are no non-essential cookies or trackers to consent to. If that changes, this policy and the site will be updated before any tracking is introduced.

## 3. OpenOSINT Cloud API

For OpenOSINT Cloud, we are the processor for the lookups you run, and a data recipient for account sign-in.

**Data we process:**
- **Account data:** your email address via GitHub/Google OAuth login. Cloud access is invite-only and provisioned manually — we do not collect or process payment card data ourselves. If you purchase the AI OSINT Prompt Pack, Operator's Playbook, or Setup Sprint, payment is processed by **Gumroad** (acting as Merchant of Record for those digital products); we receive limited order data (email, product purchased) from Gumroad and never see full card details.
- **Credentials you store (BYOK):** API keys you add for tenant-source tools. These are **encrypted at rest** and used only to perform the lookups you request.
- **Query inputs/outputs:** the target you submit and the result returned. These are not written to our database — see `cloud/routes/enrich.py` — and are not present in our application logs either: Cloud's logging is limited to a redacted customer identifier, the tool name, request timing, and an outcome status (ok / error / timeout), never the target or a provider's response body.

**Purposes and legal bases (GDPR Art. 6):** providing the Service and processing payments — performance of a contract; security, abuse prevention, and metering — legitimate interests; legal and tax compliance — legal obligation.

**Data about third parties in queries:** a result may include personal data about a third party. For that data **you are the data controller**, responsible for your lawful basis and for honoring data-subject rights. We process it on your behalf transiently to return the result to you.

**Recipients:** **Gumroad** (digital-product payments), **Heroku** (Cloud API hosting and its Postgres database), **IP2Location** (a sponsored lookup where we do hold and use our own key on your behalf — the one exception to the BYOK model above), and **GitHub**/**Google** (OAuth identity providers for dashboard sign-in only, not query content). A current, detailed list — including the public demo, which this policy does not otherwise cover — is available at https://openosint.tech/subprocessors. Where data is transferred outside the EEA, we rely on appropriate safeguards such as Standard Contractual Clauses.

**Retention:** account and billing records are kept as required for legal/tax purposes. Usage metadata — the redacted identifier, tool name, timing, and status described above — is retained for 365 days (12 months) and then deleted or anonymized; this figure is pinned in code at `cloud/config.py:USAGE_METADATA_RETENTION_DAYS` specifically so it cannot silently drift from what this policy states. **Open item:** whether the underlying Heroku log-drain for this application is actually configured to this figure has not been verified against this repository — it is an account-level setting outside version control. Stored BYOK credentials are deleted when you remove them or close your account.

## 4. Local web UI, CLI, and MCP server (self-hosted)

When you run OpenOSINT yourself — the web UI on your own machine or network, the command-line interface, or the MCP server connected to an assistant like Claude Desktop — **you are the controller**, not us. We do not operate that instance, and nothing from your use of it is transmitted to us or processed by us. Any provider you configure with your own key (an AI backend, a data source) is a relationship between you and that provider under their terms, not ours.

## 5. Your rights

Under the GDPR you have rights of access, rectification, erasure, restriction, portability, and objection with respect to data we process as described in Section 3. To exercise them, contact commercial@openosint.tech. You may lodge a complaint with your supervisory authority — in Italy, the **Garante per la protezione dei dati personali**.

## 6. Security

We apply reasonable technical and organizational measures, including encryption at rest for stored credentials and TLS in transit. No system is perfectly secure.

## 7. Changes

We may update this policy; material changes will be posted at https://openosint.tech/privacy with a revised effective date.
