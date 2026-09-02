"""
OpenOSINT Cloud — environment configuration.

All secrets and tunable values come from environment variables.
Never hardcode values here.
"""
from __future__ import annotations

import os
import secrets

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── OAuth (web dashboard login — GitHub / Google) ─────────────────────────────
# X-API-Key / MCP bearer auth never uses these; this is purely a login layer
# on top of the existing api_key model (see cloud/oauth.py, cloud/routes/oauth.py).
GITHUB_CLIENT_ID     = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SESSION_SECRET_KEY   = os.environ.get("SESSION_SECRET_KEY", "")


def resolve_session_secret() -> str:
    """Return the session-cookie signing secret.

    Fails fast in production (DATABASE_URL set) if SESSION_SECRET_KEY is
    missing, same discipline as CONFIG_ENCRYPTION_KEY in cloud/keys.py.
    Generates an ephemeral secret for local dev / tests.
    """
    if SESSION_SECRET_KEY:
        return SESSION_SECRET_KEY
    if DATABASE_URL:
        raise RuntimeError(
            "SESSION_SECRET_KEY is required when DATABASE_URL is set. "
            "Generate: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return secrets.token_urlsafe(32)

# ── Limits ────────────────────────────────────────────────────────────────────
# Heroku's HTTP router kills requests that don't return the first byte within
# 30 s (H12 error).  Keep this strictly below that limit.
TOOL_TIMEOUT_SECONDS: int = 25

# ── Per-tool credit cost ───────────────────────────────────────────────────────
# Platform-pool tools cost upstream_cost + margin; the single named constant
# below is the only place Shodan's cost needs tuning (referenced once, in
# cloud/key_sources.TOOL_KEY_CONFIG). Placeholder until real usage data comes in.
SHODAN_CREDIT_COST: int = 4

# ── Platform-pool burst limiter ────────────────────────────────────────────────
# Burst smoothing only, not the spend cap (that's the atomic Postgres credit
# decrement in cloud/db.py). Keeps one tenant from hammering a shared platform
# key (Shodan, IP2Location) with rapid-fire requests.
PLATFORM_BURST_WINDOW_SECS: float = float(os.environ.get("PLATFORM_BURST_WINDOW_SECS", "60"))
PLATFORM_BURST_MAX_CALLS: int = int(os.environ.get("PLATFORM_BURST_MAX_CALLS", "20"))

# ── Retention ─────────────────────────────────────────────────────────────────
# Single source of truth for the figure documented in legal/PRIVACY_POLICY.md
# §4 ("Usage logs are kept for 12 months"). A test asserts the policy text
# matches this number so the two cannot silently drift. This is the
# *documented* policy — whether the underlying Heroku log-drain is actually
# configured to this figure is unverified; see legal/REVIEW-QUESTIONS.md.
USAGE_METADATA_RETENTION_DAYS: int = 365

# ── Plan definitions ──────────────────────────────────────────────────────────
# Credits granted when a customer purchases / activates a plan.
PLAN_CREDITS: dict[str, int] = {
    "payg":    100,   # $10 pack → 100 calls @ $0.10/call
    "starter": 1_000, # $19/mo
    "pro":     5_000, # $49/mo
}
