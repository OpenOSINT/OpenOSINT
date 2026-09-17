"""OpenOSINT Username Recon — Apify Actor.

Given one or more usernames, uses sherlock (NSFW sites excluded) to discover
which platforms they are registered on. Monetized via Apify pay-per-event:
one charge per discovered (username, platform) hit — nothing is charged for
usernames that come back empty or fail to scan.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from apify import Actor

from openosint.tools.exceptions import OSINTError
from openosint.tools.search_username import build_sherlock_site_data, run_username_osint_structured

# Event name — this MUST match exactly what you configure in the Apify
# Console under Publication > Monetization.
EVENT_USERNAME_FOUND = "username-found"

MAX_USERNAMES_PER_RUN = 20
# Typical platform username charset: letters, digits, dot, underscore, hyphen.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,39}$")
_PER_USERNAME_TIMEOUT_SECONDS = 90
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 5


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def validate_usernames(raw: list) -> tuple[list[str], list[str]]:
    """Dedupe and split raw input into (valid, rejected) usernames."""
    deduped = _dedupe_preserve_order([str(u) for u in raw])
    valid, rejected = [], []
    for username in deduped:
        if _USERNAME_RE.match(username):
            valid.append(username)
        else:
            rejected.append(username)
    return valid, rejected


async def scan_with_retry(username: str, site_data: dict) -> list[dict]:
    """Scan a single username, retrying transient failures with backoff.

    A single username's scan failing (timeout, network error) must not fail
    the whole run — this returns an empty list rather than raising.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await asyncio.wait_for(
                run_username_osint_structured(username, site_data),
                timeout=_PER_USERNAME_TIMEOUT_SECONDS,
            )
        except (OSINTError, asyncio.TimeoutError) as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                Actor.log.warning(f"{username}: attempt {attempt + 1} failed ({exc}); retrying")
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    Actor.log.warning(f"{username}: scan failed after {_MAX_ATTEMPTS} attempt(s): {last_exc}")
    return []


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        raw_usernames = actor_input.get("usernames") or []

        if not raw_usernames:
            Actor.log.error("No usernames provided in input.")
            return

        valid_usernames, rejected_usernames = validate_usernames(raw_usernames)

        if rejected_usernames:
            Actor.log.warning(
                f"Skipping {len(rejected_usernames)} malformed username(s): "
                f"{', '.join(rejected_usernames)}"
            )

        if not valid_usernames:
            Actor.log.error("No valid usernames left after validation.")
            return

        if len(valid_usernames) > MAX_USERNAMES_PER_RUN:
            Actor.log.error(
                f"{len(valid_usernames)} valid username(s) provided, but the limit is "
                f"{MAX_USERNAMES_PER_RUN} per run. Split this into multiple runs."
            )
            return

        try:
            site_data = build_sherlock_site_data()
        except OSINTError as exc:
            Actor.log.error(f"Could not load sherlock site catalog: {exc}")
            return

        Actor.log.info(f"Scanning {len(valid_usernames)} username(s) across {len(site_data)} site(s).")

        total_found = 0
        scanned = 0
        limit_reached = False

        for username in valid_usernames:
            if limit_reached:
                break

            hits = await scan_with_retry(username, site_data)
            scanned += 1
            checked_at = datetime.now(timezone.utc).isoformat()

            for hit in hits:
                item = {**hit, "checkedAt": checked_at}
                charge_result = await Actor.push_data(item, charged_event_name=EVENT_USERNAME_FOUND)
                total_found += 1

                if charge_result.event_charge_limit_reached:
                    Actor.log.info("Charge limit reached — stopping.")
                    limit_reached = True
                    break

            Actor.log.info(f"{username}: {len(hits)} account(s) found")

        status = f"{total_found} account(s) found for {scanned} username(s) scanned"
        Actor.log.info(status)
        await Actor.set_status_message(status, is_terminal=not limit_reached)
