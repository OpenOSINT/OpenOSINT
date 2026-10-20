"""Runs the four checks concurrently (each blocking check in its own thread) and builds the report."""

from __future__ import annotations

import asyncio
import re
import socket
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import dns.exception
import requests

from openosint.exposure import (
    email_check,
    headers_check,
    lookalikes_check,
    registration_check,
    tls_check,
)
from openosint.exposure.dns_auth import DnsConfig
from openosint.exposure.domains import registrable_domain
from openosint.exposure.models import (
    STATUS_ERROR,
    STATUS_SKIPPED,
    CheckError,
    CheckResult,
    CheckSkipped,
    DomainNotRegistered,
    ExposureReport,
    LookalikeScan,
)
from openosint.exposure.scoring import INCOMPLETE, assess
from openosint.tool_policy import Noise
from openosint.tools.exceptions import OSINTError

MAX_REASON_CHARS = 80
OVERALL_TIMEOUT = 50.0  # seconds; the command must finish well under 60s
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

# name -> (check function, noise label used if the check fails before returning one)
CHECKS = {
    "email": (email_check.run, Noise.PASSIVE.value),
    "registration": (registration_check.run, Noise.PASSIVE.value),
    "tls": (tls_check.run, Noise.TOUCHES_TARGET.value),
    "http_headers": (headers_check.run, Noise.TOUCHES_TARGET.value),
}


CHECK_NAMES = tuple(CHECKS)
PASSIVE_CHECKS = tuple(name for name, (_fn, noise) in CHECKS.items() if noise == Noise.PASSIVE.value)


def select_checks(checks: Iterable[str] | None) -> tuple[str, ...]:
    """The checks to run, in their fixed order. None means all of them; anything else is validated."""
    if checks is None:
        return CHECK_NAMES
    if isinstance(checks, str):
        raise ValueError("checks must be a collection of check names, not a single string.")
    wanted = set(checks)
    if not wanted:
        raise ValueError("checks is empty. Pass None to run every check.")
    unknown = sorted(wanted - set(CHECKS))
    if unknown:
        raise ValueError(f"Unknown check(s): {', '.join(unknown)}. Choose from: {', '.join(CHECK_NAMES)}.")
    return tuple(name for name in CHECK_NAMES if name in wanted)


DNS_CHECKS = frozenset({"email"})  # the checks that do recursive DNS and so take the run's DnsConfig
GUARDED_CHECKS = frozenset({"tls", "http_headers"})  # the checks that connect to the target, and so take public_only


def normalize_domain(raw: str) -> str:
    domain = re.sub(r"^[a-z][a-z0-9+.-]*://", "", raw.strip().lower()).split("/")[0].rstrip(".")
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"'{raw}' is not a valid domain name.")
    return domain


def short_reason(exc: Exception) -> str:
    """One short human sentence for the terminal: no exception class names, no stack text."""
    if isinstance(exc, (CheckError, CheckSkipped, OSINTError)):
        text = " ".join(str(exc).split())
    elif isinstance(exc, (TimeoutError, dns.exception.Timeout, requests.Timeout)):
        text = "network timeout"
    elif isinstance(exc, socket.gaierror):
        text = "name does not resolve"
    elif isinstance(exc, (OSError, requests.RequestException)):
        text = "connection failed"
    elif isinstance(exc, dns.exception.DNSException):
        text = "DNS servers did not answer"
    else:
        text = "unexpected error (details in --json)"
    return text if len(text) <= MAX_REASON_CHARS else text[: MAX_REASON_CHARS - 3] + "..."


def classify(exc: Exception) -> str:
    """Stable reason code (models.REASON_CODES) for an exception."""
    if isinstance(exc, (CheckError, CheckSkipped)):
        return exc.code
    if isinstance(exc, (TimeoutError, dns.exception.Timeout, requests.Timeout)):
        return "timeout"
    if isinstance(exc, OSINTError):
        return "rdap_error"  # only the registration check calls into search_rdap
    if isinstance(exc, socket.gaierror):
        return "name_not_resolved"
    if isinstance(exc, (OSError, requests.RequestException)):
        return "unreachable"
    if isinstance(exc, dns.exception.DNSException):
        return "dns_error"
    return "unexpected_error"


def _guarded(name: str, domain: str, registrable: str, dns_config: DnsConfig, public_only: bool = False) -> CheckResult:
    """Run one check; any failure becomes an error/skipped result, never an exception."""
    fn, noise = CHECKS[name]
    try:
        if name in DNS_CHECKS:
            return fn(domain, registrable, dns_config)
        return fn(domain, registrable, public_only=True) if public_only and name in GUARDED_CHECKS else fn(domain, registrable)
    except DomainNotRegistered:
        raise
    except CheckSkipped as exc:
        return CheckResult(name, STATUS_SKIPPED, noise, reason=short_reason(exc), detail=str(exc),
                           reason_code=classify(exc))
    except Exception as exc:  # noqa: BLE001 - a failing check must not crash the command
        return CheckResult(name, STATUS_ERROR, noise, reason=short_reason(exc),
                           detail=f"{type(exc).__name__}: {exc}", reason_code=classify(exc))


def _lookalike_scan(registrable: str, dns_config: DnsConfig) -> LookalikeScan:
    """The opt-in step; a failure becomes status=error, never an exception or a score change."""
    try:
        return lookalikes_check.scan(registrable, dns_config)
    except Exception as exc:  # noqa: BLE001 - must not crash the command
        return LookalikeScan(STATUS_ERROR, 0, 0, reason_code=classify(exc))


async def run_exposure(
    domain: str,
    lookalikes: bool = False,
    resolver: str | None = None,
    public_only: bool = False,
    checks: Iterable[str] | None = None,
) -> ExposureReport:
    """public_only: the TLS and header checks refuse targets that resolve to non-public addresses (hosted use).

    checks: names to run (CHECK_NAMES), or None for all four. PASSIVE_CHECKS (email, registration) never connect to
    the target. A selection is not graded: score and grade are None and `not_run` lists what was left out, because a
    letter computed from some of the checks would read like a full result. Unknown or empty selections raise ValueError.
    """
    selected = select_checks(checks)
    domain = normalize_domain(domain)
    dns_config = DnsConfig.of(resolver)  # ValueError for a non-IP; applies to the recursive path only
    registrable = registrable_domain(domain)
    started = time.monotonic()
    loop = asyncio.get_running_loop()
    # ponytail: threads cannot be killed; per-call 5-10s timeouts bound stragglers. Add process isolation if that proves false.
    pool = ThreadPoolExecutor(max_workers=len(selected))
    tasks = {name: loop.run_in_executor(pool, _guarded, name, domain, registrable, dns_config, public_only) for name in selected}
    done, pending = await asyncio.wait(tasks.values(), timeout=OVERALL_TIMEOUT, return_when=asyncio.FIRST_EXCEPTION)
    pool.shutdown(wait=False, cancel_futures=True)
    for task in done:  # an unregistered domain aborts the whole report
        if isinstance(task.exception(), DomainNotRegistered):
            raise task.exception()

    checks = tuple(
        tasks[n].result() if tasks[n] in done
        else CheckResult(n, STATUS_ERROR, CHECKS[n][1], reason=f"timed out after {OVERALL_TIMEOUT:.0f}s", reason_code="timeout")
        for n in selected
    )
    not_run = tuple(n for n in CHECK_NAMES if n not in selected)
    # lookalikes are never passed in: they do not affect the grade; a partial selection is not graded at all
    score, grade, capped = (None, None, False) if not_run else assess(checks)
    # After the scored checks, never alongside them: the lookalike pool competes for the same resolver.
    scan = await loop.run_in_executor(None, _lookalike_scan, registrable, dns_config) if lookalikes else None
    return ExposureReport(
        domain=domain,
        registrable_domain=registrable,
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_ms=round((time.monotonic() - started) * 1000),
        checks=checks,
        score=score,
        grade=grade,
        score_is_partial=grade == INCOMPLETE,
        grade_capped_by_critical=capped,
        excluded_checks=tuple(c.name for c in checks if c.status != "ok"),
        findings=tuple(f for c in checks if c.status == "ok" for f in c.findings),
        lookalikes=scan,
        not_run=not_run,
    )
