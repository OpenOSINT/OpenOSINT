"""POST /v1/enrich — run an OSINT tool against a target."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cloud import db, rate_limit, tools
from cloud.auth import get_customer
from cloud.config import TOOL_TIMEOUT_SECONDS
from cloud.key_sources import (
    MissingCredentialError,
    get_credit_cost,
    is_platform_pool_tool,
    resolve_key,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_ERROR_PREFIXES = ("Scan error", "Internal error", "Error:")
_CONTACT_MESSAGE = "No credits remaining. Contact commercial@openosint.tech for access."


def _log_id(api_key: str) -> str:
    """A customer identifier safe to log: never the full key, never the
    target. Enough to correlate requests in support/incident review, not
    enough to reconstruct the credential."""
    return f"...{api_key[-4:]}" if len(api_key) > 4 else "***"


def _log_outcome(tool: str, api_key: str, status: str, elapsed: float) -> None:
    """The only per-request line Cloud logs: identifier, tool name, outcome
    status, and timing. Never the target, never a provider response body."""
    logger.info(
        "enrich: customer=%s tool=%s status=%s elapsed=%.2fs",
        _log_id(api_key), tool, status, elapsed,
    )


class EnrichRequest(BaseModel):
    tool: str
    target: str


class EnrichResponse(BaseModel):
    tool: str
    target: str
    timestamp: str
    results: list[str]
    error: str | None
    credits_left: int


@router.post("/enrich", response_model=EnrichResponse)
async def enrich(
    body: EnrichRequest,
    customer: db.Customer = Depends(get_customer),
) -> EnrichResponse:
    # 400 — tool not in allow-list (no credit touch)
    if body.tool not in tools.ALLOW_LIST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool '{body.tool}' is not available in v1.  "
                f"Available: {sorted(tools.ALLOW_LIST)}"
            ),
        )

    # Resolve upstream key before any credit touch — 422 on missing tenant key
    try:
        api_key = await resolve_key(body.tool, customer.api_key)
    except MissingCredentialError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # 429 — burst smoothing on shared platform-pool keys (not the spend cap)
    if is_platform_pool_tool(body.tool) and not rate_limit.platform_pool_limiter.allow(
        f"{customer.api_key}:{body.tool}"
    ):
        raise HTTPException(
            status_code=429,
            detail=f"Too many '{body.tool}' requests. Please slow down and try again shortly.",
        )

    cost = get_credit_cost(body.tool)

    # 402 — fast pre-check (avoids a DB round-trip for obviously empty accounts)
    if customer.credits < cost:
        _raise_402(customer.plan)

    # Run the tool first; we only charge on a successful result
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            tools.dispatch(body.tool, body.target, api_key=api_key),
            timeout=float(TOOL_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        _log_outcome(body.tool, customer.api_key, "timeout", time.monotonic() - start)
        raise HTTPException(
            status_code=504,
            detail=f"Tool '{body.tool}' exceeded the {TOOL_TIMEOUT_SECONDS} s timeout",
        )
    elapsed = time.monotonic() - start

    # No charge when the tool returned an upstream error
    first_line = result["results"][0] if result["results"] else (result.get("error") or "")
    if any(first_line.startswith(p) for p in _ERROR_PREFIXES):
        _log_outcome(body.tool, customer.api_key, "upstream_error", elapsed)
        return EnrichResponse(
            tool=result["tool"],
            target=result["target"],
            timestamp=result["timestamp"],
            results=result["results"],
            error=result["error"],
            credits_left=customer.credits,
        )

    # Atomically deduct `cost` credits (guards against concurrent exhaustion)
    new_credits = await db.decrement_credits(customer.api_key, cost)
    if new_credits is None:
        # Race: a concurrent request drained the last credit between pre-check and now
        _log_outcome(body.tool, customer.api_key, "credits_exhausted", elapsed)
        _raise_402(customer.plan)

    _log_outcome(body.tool, customer.api_key, "ok", elapsed)
    return EnrichResponse(
        tool=result["tool"],
        target=result["target"],
        timestamp=result["timestamp"],
        results=result["results"],
        error=result["error"],
        credits_left=new_credits,
    )


def _raise_402(plan: str) -> None:
    raise HTTPException(status_code=402, detail={"message": _CONTACT_MESSAGE})
