"""
OpenOSINT Cloud — database layer.

Uses asyncpg when DATABASE_URL is set (Heroku Postgres in production).
Falls back to an in-memory store when DATABASE_URL is absent (tests / local dev).

Public API
----------
init_pool()                              — call on app startup
close_pool()                             — call on app shutdown
get_customer(api_key)        → Customer | None
decrement_credits(api_key, cost=1) → int | None   (None = not enough credits)
get_or_create_user(provider, provider_user_id, email) → User
get_user(user_id)            → User | None
link_existing_customer_key(user_id, api_key) → "ok" | "not_found" | "conflict"
"""
from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

try:
    import asyncpg  # type: ignore
    _HAS_ASYNCPG = True
except ImportError:
    _HAS_ASYNCPG = False

_pool: Any = None  # asyncpg.Pool or None


# ── domain model ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Customer:
    api_key: str
    credits: int
    plan: str
    created_at: datetime = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class WaitlistSignup:
    id: int
    email: str
    role: str | None
    use_case: str | None
    plan_interest: str | None
    source: str | None
    created_at: datetime = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class User:
    """An OAuth login identity (GitHub / Google). Web-dashboard login only —
    X-API-Key / MCP bearer auth never reads this table."""
    id: int
    provider: str
    provider_user_id: str
    email: str | None
    customer_api_key: str | None
    created_at: datetime = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── in-memory store (tests only) ─────────────────────────────────────────────

_MEMORY_CUSTOMERS: dict[str, Customer] = {}   # api_key → Customer

_MEMORY_USERS: dict[int, User] = {}                        # id → User
_MEMORY_USERS_BY_IDENTITY: dict[tuple[str, str], int] = {}  # (provider, provider_user_id) → id
_next_user_id = 1

_MEMORY_WAITLIST: dict[str, WaitlistSignup] = {}  # lowercased email → WaitlistSignup
_next_waitlist_id = 1


def _is_memory_mode() -> bool:
    return _pool is None


# ── pool lifecycle ────────────────────────────────────────────────────────────

async def init_pool() -> None:
    global _pool
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.warning("DATABASE_URL not set — using in-memory store (tests / local dev only)")
        return
    if not _HAS_ASYNCPG:
        raise RuntimeError(
            "asyncpg is required for production.  "
            "Add asyncpg>=0.29.0 to requirements.txt and redeploy."
        )
    # Heroku Postgres exposes a postgres:// DSN; asyncpg requires postgresql://
    dsn = database_url.replace("postgres://", "postgresql://", 1)
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    logger.info("Database pool connected")


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ── read ──────────────────────────────────────────────────────────────────────

async def get_customer(api_key: str) -> Customer | None:
    if _is_memory_mode():
        return _MEMORY_CUSTOMERS.get(api_key)
    row = await _pool.fetchrow(
        "SELECT api_key, credits, plan, created_at "
        "FROM customers WHERE api_key = $1",
        api_key,
    )
    if row is None:
        return None
    return Customer(
        api_key=row["api_key"],
        credits=row["credits"],
        plan=row["plan"],
        created_at=row["created_at"],
    )


# ── write ─────────────────────────────────────────────────────────────────────

async def decrement_credits(api_key: str, cost: int = 1) -> int | None:
    """
    Atomically subtract `cost` credits if credits >= cost.

    Returns the new credit balance on success.
    Returns None if there weren't enough credits (caller should respond 402).
    """
    if _is_memory_mode():
        current = _MEMORY_CUSTOMERS.get(api_key)
        if current is None or current.credits < cost:
            return None
        updated = dataclasses.replace(current, credits=current.credits - cost)
        _MEMORY_CUSTOMERS[api_key] = updated
        return updated.credits
    row = await _pool.fetchrow(
        "UPDATE customers SET credits = credits - $2 "
        "WHERE api_key = $1 AND credits >= $2 "
        "RETURNING credits",
        api_key,
        cost,
    )
    return row["credits"] if row else None


# ── users (OAuth login identities) ────────────────────────────────────────────

async def get_or_create_user(provider: str, provider_user_id: str, email: str | None) -> User:
    """Find the user for (provider, provider_user_id), creating one on first login.

    Refreshes `email` on every login without clobbering a previously stored
    address when the provider returns none this time (e.g. a private GitHub
    email). No implicit link to any `customers` row — that only happens via
    the manual "link an existing key" flow (link_existing_customer_key).
    """
    if _is_memory_mode():
        global _next_user_id
        identity = (provider, provider_user_id)
        existing_id = _MEMORY_USERS_BY_IDENTITY.get(identity)
        if existing_id is not None:
            current = _MEMORY_USERS[existing_id]
            updated = dataclasses.replace(current, email=email or current.email)
            _MEMORY_USERS[existing_id] = updated
            return updated
        user = User(
            id=_next_user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            customer_api_key=None,
        )
        _MEMORY_USERS[user.id] = user
        _MEMORY_USERS_BY_IDENTITY[identity] = user.id
        _next_user_id += 1
        return user

    row = await _pool.fetchrow(
        """
        INSERT INTO users (provider, provider_user_id, email)
        VALUES ($1, $2, $3)
        ON CONFLICT (provider, provider_user_id)
        DO UPDATE SET email = COALESCE(EXCLUDED.email, users.email)
        RETURNING id, provider, provider_user_id, email,
                  customer_api_key, created_at
        """,
        provider,
        provider_user_id,
        email,
    )
    return _user_from_row(row)


async def get_user(user_id: int) -> User | None:
    if _is_memory_mode():
        return _MEMORY_USERS.get(user_id)
    row = await _pool.fetchrow(
        "SELECT id, provider, provider_user_id, email, "
        "customer_api_key, created_at FROM users WHERE id = $1",
        user_id,
    )
    return _user_from_row(row) if row is not None else None


def _user_from_row(row: Any) -> User:
    return User(
        id=row["id"],
        provider=row["provider"],
        provider_user_id=row["provider_user_id"],
        email=row["email"],
        customer_api_key=row["customer_api_key"],
        created_at=row["created_at"],
    )


def _customer_api_key_claimed(api_key: str, exclude_user_id: int) -> bool:
    """True if some other user already holds this customer_api_key (memory mode)."""
    return any(
        u.customer_api_key == api_key
        for uid, u in _MEMORY_USERS.items()
        if uid != exclude_user_id
    )


async def link_existing_customer_key(user_id: int, api_key: str) -> str:
    """
    Manual-claim path: a user pastes a customer_api_key they already have
    (provisioned by hand — see cloud/routes/enrich.py's contact-for-access
    flow) onto their dashboard account.

    Returns "ok", "not_found" (no customers row for this api_key), or
    "conflict" (api_key already linked to a different user's row) — the
    caller maps this to a clean HTTP response, never a 500.
    """
    if _is_memory_mode():
        customer = _MEMORY_CUSTOMERS.get(api_key)
        if customer is None:
            return "not_found"
        if _customer_api_key_claimed(api_key, user_id):
            return "conflict"
        user = _MEMORY_USERS.get(user_id)
        if user is None:
            return "not_found"
        _MEMORY_USERS[user_id] = dataclasses.replace(user, customer_api_key=api_key)
        return "ok"

    customer_row = await _pool.fetchrow(
        "SELECT api_key FROM customers WHERE api_key = $1", api_key
    )
    if customer_row is None:
        return "not_found"
    try:
        await _pool.execute(
            "UPDATE users SET customer_api_key = $2 WHERE id = $1",
            user_id,
            api_key,
        )
    except asyncpg.UniqueViolationError:
        return "conflict"
    return "ok"


# ── waitlist (pre-launch demand signups) ──────────────────────────────────────

async def add_waitlist_signup(
    email: str,
    role: str | None,
    use_case: str | None,
    plan_interest: str | None,
    source: str | None,
) -> None:
    """Insert a waitlist signup. Silently no-ops on a duplicate email — the
    caller always returns the same success response either way, so it
    doesn't need or use this function's return value."""
    if _is_memory_mode():
        global _next_waitlist_id
        if email in _MEMORY_WAITLIST:
            return
        _MEMORY_WAITLIST[email] = WaitlistSignup(
            id=_next_waitlist_id,
            email=email,
            role=role,
            use_case=use_case,
            plan_interest=plan_interest,
            source=source,
        )
        _next_waitlist_id += 1
        return

    await _pool.execute(
        """
        INSERT INTO waitlist (email, role, use_case, plan_interest, source)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (email) DO NOTHING
        """,
        email,
        role,
        use_case,
        plan_interest,
        source,
    )


async def get_waitlist_stats() -> dict[str, Any]:
    """Aggregate counts for GET /v1/waitlist/stats. Never returns individual
    emails — export those via direct SQL (see CLOUD.md)."""
    if _is_memory_mode():
        signups = list(_MEMORY_WAITLIST.values())
        return {
            "total": len(signups),
            "by_role": _count_by(signups, lambda s: s.role),
            "by_plan_interest": _count_by(signups, lambda s: s.plan_interest),
            "by_source": _count_by(signups, lambda s: s.source),
        }

    total = await _pool.fetchval("SELECT count(*) FROM waitlist")
    return {
        "total": total,
        "by_role": await _grouped_role_counts(),
        "by_plan_interest": await _grouped_plan_interest_counts(),
        "by_source": await _grouped_source_counts(),
    }


def _count_by(signups: list[WaitlistSignup], key: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for signup in signups:
        value = key(signup)
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


# Three static queries rather than one query built with an interpolated
# column name — no dynamic SQL in this module, even though the (internal-
# only) callers above would only ever pass one of these three literals.
async def _grouped_role_counts() -> dict[str, int]:
    rows = await _pool.fetch(
        "SELECT role AS key, count(*) AS n FROM waitlist "
        "WHERE role IS NOT NULL GROUP BY role"
    )
    return {row["key"]: row["n"] for row in rows}


async def _grouped_plan_interest_counts() -> dict[str, int]:
    rows = await _pool.fetch(
        "SELECT plan_interest AS key, count(*) AS n FROM waitlist "
        "WHERE plan_interest IS NOT NULL GROUP BY plan_interest"
    )
    return {row["key"]: row["n"] for row in rows}


async def _grouped_source_counts() -> dict[str, int]:
    rows = await _pool.fetch(
        "SELECT source AS key, count(*) AS n FROM waitlist "
        "WHERE source IS NOT NULL GROUP BY source"
    )
    return {row["key"]: row["n"] for row in rows}
