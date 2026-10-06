"""Black-box check of the web server's request guard (stdlib only).

Usage: python scripts/ci/check_guard.py http://127.0.0.1:8080 [--restricted true|false] [--fresh]

Extra checks for a server reached from a non-loopback peer (Docker):
  --expect-setup-blocked        /api/setup/status says can_save is false with the clear
                                OPENOSINT_SETUP_TOKEN message, and POST /api/setup is a 403
                                carrying that same message (not a silent failure)
  --save-with-token TOKEN       POST a test key with X-Setup-Token and expect 200
  --expect-configured KEY       /api/setup/status lists KEY as configured (after a restart)

Always asserts that a request with a foreign Host header and a cross-site POST to
/api/setup are both rejected with 403. With --restricted, also asserts the value of
/api/health's `restricted`; with --fresh, that demo_mode and setup_complete are false
(a fresh install with no keys and no restriction).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT_SECS = 10


def status_of(url: str, *, method: str = "GET", headers: dict | None = None, body=None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def check_rejections(base: str) -> None:
    code = status_of(f"{base}/api/health", headers={"Host": "evil.example"})
    assert code == 403, f"foreign Host header got {code}, expected 403"
    code = status_of(
        f"{base}/api/setup",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Origin": "https://evil.example",
            "Sec-Fetch-Site": "cross-site",
        },
        body={},
    )
    assert code == 403, f"cross-site POST /api/setup got {code}, expected 403"
    print(f"ok  guard rejects a foreign Host and a cross-site /api/setup at {base}")


def _json(url: str, *, method: str = "GET", headers: dict | None = None, body=None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def check_setup_blocked(base: str) -> None:
    code, status = _json(f"{base}/api/setup/status")
    assert code == 200 and status["can_save"] is False, f"expected can_save false, got {status}"
    assert "OPENOSINT_SETUP_TOKEN" in status["forbidden_message"], status
    code, body = _json(
        f"{base}/api/setup",
        method="POST",
        headers={"Content-Type": "application/json"},
        body={"SHODAN_API_KEY": "ci-test-key"},
    )
    assert code == 403, f"POST /api/setup without a token got {code}, expected 403"
    assert "OPENOSINT_SETUP_TOKEN" in body["message"] and "Docker" in body["message"], body
    print("ok  setup is blocked with a clear message (no token)")


def check_token_save(base: str, token: str) -> None:
    code, body = _json(
        f"{base}/api/setup",
        method="POST",
        headers={"Content-Type": "application/json", "X-Setup-Token": token},
        body={"SHODAN_API_KEY": "ci-test-key"},
    )
    assert code == 200 and body["applied"] == ["SHODAN_API_KEY"], f"token save failed: {code} {body}"
    assert "ci-test-key" not in json.dumps(body), "response echoed the key"
    print("ok  setup token saves a key")


def check_configured(base: str, key: str) -> None:
    _, status = _json(f"{base}/api/setup/status")
    entry = next(k for k in status["keys"] if k["key"] == key)
    assert entry.get("configured") is True and entry.get("source") == "config", entry
    print(f"ok  {key} is configured from the data directory")


def check_health(base: str, restricted: bool | None, fresh: bool) -> None:
    with urllib.request.urlopen(f"{base}/api/health", timeout=TIMEOUT_SECS) as resp:
        health = json.load(resp)
    if restricted is not None:
        assert health["restricted"] is restricted, f"restricted={health['restricted']}: {health}"
    if fresh:
        assert health["demo_mode"] is False, f"demo_mode is not false: {health}"
        assert health["setup_complete"] is False, f"setup_complete is not false: {health}"
    print(f"ok  health: restricted={health['restricted']} demo_mode={health['demo_mode']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("--restricted", choices=("true", "false"))
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--expect-setup-blocked", action="store_true")
    parser.add_argument("--save-with-token")
    parser.add_argument("--expect-configured")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    restricted = None if args.restricted is None else args.restricted == "true"
    check_health(base, restricted, args.fresh)
    check_rejections(base)
    if args.expect_setup_blocked:
        check_setup_blocked(base)
    if args.save_with_token:
        check_token_save(base, args.save_with_token)
    if args.expect_configured:
        check_configured(base, args.expect_configured)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        sys.exit(f"FAIL: {exc}")
