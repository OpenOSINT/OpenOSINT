"""
Classify a response from ``POST https://api.brightdata.com/request`` (SERP API and Web Unlocker).

One place decides what a failure means, from what Bright Data documents:

* Rejected before any fetch: a real outer 401 (token) or 400 (``zone "X" not found``).
* Otherwise the outer status is 200 and the real outcome is in the ``x-brd-*`` headers
  (https://docs.brightdata.com/products/web-unlocker/error-codes). A missing ``x-brd-error``
  means the answer came from the target site itself.
* Outer 5xx with no ``x-brd-*`` headers is Bright Data's own API failing, never the user's key.
* ``Kind.TARGET_STATUS`` (no ``x-brd-error``) is the target site's own HTTP status; whether that is a
  failure is the caller's call (a SERP query: yes; a fetched page: no, a 404 is a finding).
* Credits exhausted: the status is NOT documented. Bright Data's official MCP maps
  ``x-brd-err-code: client_10100`` to "usage limit reached", so we use it as a best-effort hint
  ("this may mean your free credits are used up"), never as a hard claim.

Messages for existing users carry dashboard pages, never the referral link.
"""

from __future__ import annotations

import re
from enum import Enum

from openosint.brightdata import BILLING_URL, TOKEN_URL
from openosint.tools.exceptions import ToolExecutionError

# Official Bright Data status page, once one is confirmed (asked via the partner manager).
# While empty, the outage message just says to contact Bright Data support.
STATUS_PAGE_URL = ""

USAGE_LIMIT_CODE = "client_10100"
_PREVIEW_LEN = 200
_ZONE_NOT_FOUND = re.compile(r'zone "([^"]*)" not found')
_RETRY_ERROR_CODES = frozenset({"failed_query_rejected", "repeat_query_rejected"})
_VERIFICATION_ERROR_CODES = frozenset({"captcha", "verifying"})
_BLOCK_ERROR_CODES = frozenset({"reject_block", "http_status"})
_RETRY_HINT = "query temporarily blocked by Bright Data, retry after 15 seconds"
_VERIFICATION_HINT = "search engine returned a verification page; not billed"
_BLOCK_HINT = "the target blocked the request (captcha or protection page); a retry may succeed"


class Kind(str, Enum):
    TOKEN_REJECTED = "token_rejected"
    ZONE_NOT_FOUND = "zone_not_found"
    CREDITS_HINT = "credits_hint"
    RATE_LIMITED = "rate_limited"
    SERVICE_ERROR = "service_error"
    FORBIDDEN = "forbidden"
    REQUEST_REJECTED = "request_rejected"
    TARGET_BLOCKED = "target_blocked"
    TARGET_STATUS = "target_status"
    TARGET_ERROR = "target_error"
    UNEXPECTED = "unexpected"


class BrightDataError(ToolExecutionError):
    """A classified Bright Data failure. ``stop_batch`` means more requests would fail the same way."""

    def __init__(
        self,
        message: str,
        *,
        kind: Kind = Kind.UNEXPECTED,
        status_code: int | None = None,
        error_code: str | None = None,
        stop_batch: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.error_code = error_code
        self.stop_batch = stop_batch


def redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "***REDACTED***") if api_key else text


def body_preview(response, api_key: str) -> str:
    return redact((getattr(response, "text", "") or "")[:_PREVIEW_LEN], api_key)


def brd_headers(response) -> tuple[int | None, str | None, str | None]:
    """(x-brd-status-code, error code, error message). Proxy-layer failures use the err-code/err-msg spelling."""
    headers = response.headers or {}
    raw_status = headers.get("x-brd-status-code")
    error_code = headers.get("x-brd-error-code") or headers.get("x-brd-err-code")
    error_message = headers.get("x-brd-error") or headers.get("x-brd-err-msg")
    status = int(raw_status) if raw_status and str(raw_status).strip().isdigit() else None
    return status, error_code, error_message


def _brd_failure_message(status: int, error_code: str | None, error_message: str | None) -> str:
    text = f"Bright Data {status}"
    if error_code:
        text += f" {error_code}"
    if error_message:
        text += f": {error_message}"
    if error_code in _RETRY_ERROR_CODES:
        text += f" — {_RETRY_HINT}"
    elif error_code in _VERIFICATION_ERROR_CODES:
        text += f" — {_VERIFICATION_HINT}"
    elif error_code in _BLOCK_ERROR_CODES or (error_code or "").startswith("resolve_failed_"):
        text += f" — {_BLOCK_HINT}"
    elif not error_code and not error_message:
        text += f": the target site itself answered HTTP {status}"
    return text


def _fail(
    message: str, kind: Kind, status: int | None, code: str | None = None, stop: bool = False
) -> BrightDataError:
    return BrightDataError(message, kind=kind, status_code=status, error_code=code, stop_batch=stop)


def _token_rejected(response, api_key: str) -> BrightDataError:
    body = body_preview(response, api_key)
    message = (
        f"Bright Data rejected the API token (HTTP 401, body={body!r}). Check or regenerate it at "
        f"{TOKEN_URL}; BRIGHTDATA_API_KEY takes the token only."
    )
    if "token expired" in (response.text or "").lower():
        message += " Bright Data API key expired — renew it in the Bright Data dashboard."
    return _fail(message, Kind.TOKEN_REJECTED, 401, "auth", stop=True)


def _service_error(status: int) -> BrightDataError:
    message = (
        f"Bright Data's API returned HTTP {status}. This is a Bright Data-side error, not a problem with "
        "your key or zone. Retry in a few minutes; if it persists, contact Bright Data support."
    )
    if STATUS_PAGE_URL:
        message += f" Status page: {STATUS_PAGE_URL}"
    return _fail(message, Kind.SERVICE_ERROR, status, stop=True)


def classify(
    response, *, api_key: str, zone: str, zone_env: str, product: str
) -> BrightDataError | None:
    """The error this response means, or None when the request itself succeeded.

    ``product`` ("SERP API" / "Web Unlocker") and ``zone_env`` only shape the message wording.
    """
    status = response.status_code
    brd_status, brd_code, brd_message = brd_headers(response)

    if brd_code == USAGE_LIMIT_CODE:
        message = (
            f"Bright Data reported a usage limit ({USAGE_LIMIT_CODE}). This may mean your free credits are "
            f"used up — check {BILLING_URL}. Requests resume when credits renew on the 1st of the month "
            "or after you add funds."
        )
        return _fail(message, Kind.CREDITS_HINT, status, USAGE_LIMIT_CODE, stop=True)
    if status == 401:
        return _token_rejected(response, api_key)
    if status == 400:
        match = _ZONE_NOT_FOUND.search(response.text or "")
        if match:
            name = match.group(1) or zone
            message = (
                f"Bright Data zone '{name}' not found. Create a {product} zone in your Bright Data "
                f"dashboard, or set {zone_env} to the name of an existing one."
            )
            return _fail(message, Kind.ZONE_NOT_FOUND, 400, "zone_not_found", stop=True)
        return _fail(
            f"Bright Data rejected the request (HTTP 400, body={body_preview(response, api_key)!r}).",
            Kind.REQUEST_REJECTED,
            400,
        )
    if status == 403:
        message = (
            f"Bright Data refused the request (HTTP 403, body={body_preview(response, api_key)!r}). The "
            "zone may lack permission for this target, or Bright Data policy blocks it."
        )
        return _fail(message, Kind.FORBIDDEN, 403, brd_code)
    if status == 429 and brd_status is None:
        message = (
            "Bright Data rate limit (HTTP 429). Slow down and retry. Bright Data documents a limit of "
            f"1,000 requests/minute for accounts without funds; adding funds lifts it: {BILLING_URL}"
        )
        return _fail(message, Kind.RATE_LIMITED, 429)
    if brd_status is not None:
        if 200 <= brd_status < 300:
            return None
        if brd_code in _BLOCK_ERROR_CODES or (brd_code or "").startswith("resolve_failed_"):
            kind = Kind.TARGET_BLOCKED
        else:
            kind = Kind.TARGET_ERROR if brd_code else Kind.TARGET_STATUS
        return _fail(
            _brd_failure_message(brd_status, brd_code, brd_message), kind, brd_status, brd_code
        )
    if status >= 500:
        return _service_error(status)
    if status != 200:
        message = f"Bright Data {product}: unexpected response (HTTP {status}, body={body_preview(response, api_key)!r})."
        return _fail(message, Kind.UNEXPECTED, status)
    return None
