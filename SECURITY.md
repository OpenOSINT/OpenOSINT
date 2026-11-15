# Security Policy

## Supported Versions

Only the latest release on the `main` branch receives security fixes.
Older versions are not patched — please upgrade before reporting.

| Version | Supported |
|---------|-----------|
| 2.25.x (latest) | ✅ |
| < 2.25.0 | ❌ |

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

### Preferred channel — GitHub Private Vulnerability Reporting

Use GitHub's built-in private advisory flow:

[**Report a vulnerability →**](https://github.com/OpenOSINT/OpenOSINT/security/advisories/new)

This keeps the report confidential until a fix is released and lets us coordinate the disclosure timeline with you directly.

### Alternative channel — email

If you cannot use GitHub's advisory form, send a report to:

**[commercial@openosint.tech](mailto:commercial@openosint.tech)**

Include:
- A clear description of the vulnerability
- Steps to reproduce (proof-of-concept code or commands)
- The component affected (CLI, MCP server, REPL, Web UI, a specific tool integration)
- The potential impact as you assess it

Encrypting your report is welcome but not required.

---

## Response Timeline

| Milestone | Target |
|-----------|--------|
| Acknowledgement | Within **72 hours** |
| Status update / triage result | Within **7 days** |
| Fix or mitigation | Depends on severity and complexity |

We will keep you informed at each step. If you have not heard back within 72 hours, follow up by email.

---

## Scope

### In scope

- Core framework (`openosint/agent.py`, `openosint/pivot.py`, `openosint/correlation.py`, etc.)
- Interactive REPL (`openosint/repl.py`)
- CLI (`openosint/cli.py`)
- MCP server (`openosint/mcp_server.py`)
- Web UI / FastAPI server (`openosint/web_server.py`)
- All tool integrations under `openosint/tools/`
- Dependency vulnerabilities that directly affect users of this package

### Out of scope

- **The retired public demo** — `demo.openosint.tech` was shut down on 2026-11-14 and now only redirects to the OpenOSINT Cloud app. Reports about it are not accepted.
- **Third-party APIs (Shodan, VirusTotal, Censys, IP2Location, etc.)** — OpenOSINT is a BYOK (bring your own key) tool. Your API keys are passed directly from your environment to the respective APIs and never touch OpenOSINT's servers. Vulnerabilities in those upstream services should be reported to those providers.
- Social-engineering attacks against maintainers
- Denial-of-service attacks against the OpenOSINT Cloud service or its hosts

---

## Disclosure Policy

We follow **coordinated responsible disclosure**:

1. You report privately through one of the channels above.
2. We triage, develop a fix, and prepare a GitHub Security Advisory.
3. We coordinate a release date with you (typically within 90 days of the initial report).
4. We publish the advisory and release the patched version simultaneously.

Researchers who report valid vulnerabilities will be **credited by name in the advisory** unless they prefer to remain anonymous — just let us know your preference when you report.

---

*OpenOSINT is maintained by [Tommaso Bertocchi](mailto:commercial@openosint.tech).
The project is MIT-licensed and for authorized security research and educational use only.*
