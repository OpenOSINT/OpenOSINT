"""OpenOSINT Username Recon — Apify Actor.

Given one or more usernames, uses sherlock (NSFW sites excluded) to discover
which platforms they are registered on. Monetized via Apify pay-per-event:
one charge per discovered (username, platform) hit — nothing is charged for
usernames that come back empty or fail to scan.

Sherlock's site catalog is scanned in small chunks rather than all ~400+
sites in one call: a single unresponsive site no longer stalls (or loses)
the whole scan, results are pushed as each chunk completes, and a failed
chunk is simply skipped rather than retried (retrying re-hits the same
slow/unresponsive sites for no benefit).
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from datetime import datetime, timezone

from apify import Actor

from openosint.tools.search_username import build_sherlock_site_data, run_username_osint_structured

# Event name — this MUST match exactly what you configure in the Apify
# Console under Publication > Monetization.
EVENT_USERNAME_FOUND = "username-found"

MAX_USERNAMES_PER_RUN = 20
# Typical platform username charset: letters, digits, dot, underscore, hyphen.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,39}$")

# Sherlock caps its own internal concurrency at 20 workers regardless of how
# many sites you hand it in one call — splitting ~400+ sites into chunks of
# 40 (2 worker-waves each) bounds a single chunk's worst case to roughly
# 2 * the per-request timeout below, instead of the whole catalog's.
_CHUNK_SIZE = 40
# Per-site HTTP request timeout, passed through to sherlock's own sherlock()
# call. Kept low deliberately — a real, reachable site responds in well
# under this; a site that doesn't is not worth waiting on.
_SITE_REQUEST_TIMEOUT_SECONDS = 10
# Safety-net ceiling for one whole chunk (all sites in it, worst case both
# worker-waves timing out). If this fires, the chunk's results are dropped
# and scanning moves on — a chunk is never retried.
_CHUNK_TIMEOUT_SECONDS = 45
# Hard wall-clock ceiling for the whole run, checked between usernames and
# between chunks, so a pathological run (everything unresponsive) can't run
# away with the customer's compute budget.
_MAX_RUN_SECONDS = 600

# Sites known (from manual testing) to report "claimed" for usernames that
# don't exist anywhere — e.g. a wildcard/parked-domain response, or a wiki
# that generates a valid-looking "User:<name>" page shell for any string.
# Excluded unconditionally, on top of whatever the per-run control scan
# below finds. F3.cool and Code Snippet Wiki were both confirmed by
# scanning a random, never-registered username and getting "claimed" back.
_KNOWN_NOISY_SITES = {"F3.cool", "Code Snippet Wiki"}


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


def chunk_site_data(site_data: dict, size: int = _CHUNK_SIZE) -> list[dict]:
    """Split a sherlock site-data dict into a list of smaller dicts of at most `size` sites."""
    items = list(site_data.items())
    return [dict(items[i : i + size]) for i in range(0, len(items), size)]


def generate_control_username() -> str:
    """
    A random username, virtually guaranteed to be unregistered everywhere.

    Used once per run to detect sites that report a false "claimed" result
    for this run (e.g. a wildcard DNS/parked-domain response) — see
    scan_username() below. Kept short (12 hex chars) so it isn't rejected by
    sites with tight username-length limits that a real one wouldn't hit.
    """
    return secrets.token_hex(6)


async def scan_chunk(username: str, chunk: dict) -> list[dict] | None:
    """
    Scan one chunk of sites for username.

    Returns None (not raises) on any failure — timeout or otherwise — so a
    single bad chunk never takes down the run. Not retried: a chunk that
    fails almost always failed because a site in it is unresponsive, and
    retrying the same chunk just waits on the same site again.
    """
    try:
        return await asyncio.wait_for(
            run_username_osint_structured(username, chunk, timeout_seconds=_SITE_REQUEST_TIMEOUT_SECONDS),
            timeout=_CHUNK_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        Actor.log.warning(
            f"{username}: chunk of {len(chunk)} site(s) failed — {type(exc).__name__}: {exc!r}"
        )
        return None


async def scan_username(username: str, chunks: list[dict], run_deadline: float) -> tuple[list[dict], bool]:
    """
    Scan username across all chunks, stopping early if the run budget is spent.

    Returns (hits, had_any_successful_chunk). had_any_successful_chunk is
    False only when every chunk failed — that's a genuine scan failure, not
    "zero accounts found", and callers should treat it differently.
    """
    hits: list[dict] = []
    had_success = False
    for chunk in chunks:
        if time.monotonic() > run_deadline:
            break
        result = await scan_chunk(username, chunk)
        if result is None:
            continue
        had_success = True
        hits.extend(result)
    return hits, had_success


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        raw_usernames = actor_input.get("usernames") or []

        if not raw_usernames:
            await Actor.fail(status_message="No usernames provided in input.")
            return

        valid_usernames, rejected_usernames = validate_usernames(raw_usernames)

        if rejected_usernames:
            Actor.log.warning(
                f"Skipping {len(rejected_usernames)} malformed username(s): "
                f"{', '.join(rejected_usernames)}"
            )

        if not valid_usernames:
            await Actor.fail(status_message="No valid usernames left after validation.")
            return

        if len(valid_usernames) > MAX_USERNAMES_PER_RUN:
            await Actor.fail(
                status_message=(
                    f"{len(valid_usernames)} valid username(s) provided, but the limit is "
                    f"{MAX_USERNAMES_PER_RUN} per run. Split this into multiple runs."
                )
            )
            return

        try:
            site_data = build_sherlock_site_data()
        except Exception as exc:
            await Actor.fail(status_message=f"Could not load sherlock site catalog: {exc}")
            return

        chunks = chunk_site_data(site_data)
        Actor.log.info(
            f"Scanning {len(valid_usernames)} username(s) across {len(site_data)} site(s) "
            f"in {len(chunks)} chunk(s) of up to {_CHUNK_SIZE}."
        )

        run_deadline = time.monotonic() + _MAX_RUN_SECONDS

        control_username = generate_control_username()
        control_hits, control_ok = await scan_username(control_username, chunks, run_deadline)
        noisy_platforms = set(_KNOWN_NOISY_SITES) | {hit["platform"] for hit in control_hits}
        if not control_ok:
            Actor.log.warning("Control scan for false-positive detection failed entirely — proceeding without it.")
        newly_flagged = noisy_platforms - _KNOWN_NOISY_SITES
        if newly_flagged:
            Actor.log.info(f"Control scan flagged {len(newly_flagged)} noisy site(s) this run: {sorted(newly_flagged)}")

        total_found = 0
        scanned_ok = 0
        failed_usernames: list[str] = []
        limit_reached = False

        for username in valid_usernames:
            if limit_reached or time.monotonic() > run_deadline:
                break

            hits, had_success = await scan_username(username, chunks, run_deadline)
            checked_at = datetime.now(timezone.utc).isoformat()

            if not had_success:
                failed_usernames.append(username)
                Actor.log.warning(f"{username}: every chunk failed — no results produced.")
                continue

            scanned_ok += 1
            username_found = 0
            for hit in hits:
                if hit["platform"] in noisy_platforms:
                    continue
                item = {**hit, "checkedAt": checked_at}
                charge_result = await Actor.push_data(item, charged_event_name=EVENT_USERNAME_FOUND)
                total_found += 1
                username_found += 1

                if charge_result.event_charge_limit_reached:
                    Actor.log.info("Charge limit reached — stopping.")
                    limit_reached = True
                    break

            Actor.log.info(f"{username}: {username_found} account(s) found")

        ran_out_of_time = time.monotonic() > run_deadline

        if scanned_ok == 0:
            await Actor.fail(
                status_message=f"All {len(valid_usernames)} username(s) failed to scan — no results produced."
            )
            return

        status = f"{total_found} account(s) found for {scanned_ok}/{len(valid_usernames)} username(s) scanned"
        if failed_usernames:
            status += f"; {len(failed_usernames)} failed: {', '.join(failed_usernames)}"
        if ran_out_of_time:
            status += " [stopped early: run time budget exceeded]"
        Actor.log.info(status)
        await Actor.set_status_message(status, is_terminal=not limit_reached)
