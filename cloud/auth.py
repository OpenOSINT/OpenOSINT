"""FastAPI dependencies for auth: X-API-Key (customers) and X-Setup-Token (operator)."""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from cloud import db

_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_setup_token_header = APIKeyHeader(name="X-Setup-Token", auto_error=False)


async def get_customer(api_key: str | None = Security(_key_header)) -> db.Customer:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    customer = await db.get_customer(api_key)
    if customer is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return customer


async def require_setup_token(token: str | None = Security(_setup_token_header)) -> None:
    """Gate for operator-only read endpoints (e.g. GET /v1/waitlist/stats).

    Same OPENOSINT_SETUP_TOKEN env var and secrets.compare_digest check as
    openosint/web_server.py's /api/setup gate. No loopback bypass here — this
    gateway always runs remotely (Heroku), so an unset token means the route
    stays closed rather than open-by-default.
    """
    expected = os.environ.get("OPENOSINT_SETUP_TOKEN", "").strip()
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Missing or invalid X-Setup-Token")
