---
name: exposure
description: Grade a domain's external exposure A-F with OpenOSINT (email authentication, TLS, domain registration, security headers). Use when the user asks for an exposure check, security posture, email-spoofing or DMARC/SPF check, or "how exposed is this domain". No API key needed.
license: MIT
compatibility: Needs uv (for `uvx`) and network access.
argument-hint: "<domain>"
---

# OpenOSINT: exposure report

Domain: $ARGUMENTS (ask for one if empty). Only run this on domains the user owns or is authorized to assess.

```bash
uvx --from openosint==2.38.0 openosint --json exposure DOMAIN
```

- The TLS and header checks connect to the domain on port 443. If the user wants no contact with the target, run `exposure DOMAIN --checks email,registration` instead (DNS and registry only; the result is not graded).
- Optional: `--report PATH.html` writes a printable report; `--lookalikes` adds a DNS-only search for lookalike domains (not part of the grade).
- Do not pass `--allow-active`.

Report the grade, then each check's findings, each cited as `claim [exposure DOMAIN, <check>]`. The grade is a point-in-time summary, not a compliance result or a vulnerability scan. Findings are leads to verify, not proof. If the command fails or a check is skipped, say so; do not estimate a grade.
