"""
Smoke tests for OpenOSINT Cloud gateway.

Runs against the in-memory DB backend (DATABASE_URL not set).
Tool dispatch is mocked — no real network calls.

Coverage:
  (a) 401 on missing / invalid API key
  (b) 402 when credits are exhausted
  (c) success path decrements credits and returns structured result
  (d) non-allow-listed tool returns 400
  (e) key store/retrieve roundtrip — encrypted at rest, masked on GET /v1/keys
  (f) enrich uses stored customer key and passes it to the tool
  (g) missing customer key returns 422 without decrementing credits
  (h) server-source tool (ip2location) reads key from env, not customer store
  (i) upstream error leaves credits unchanged
  (j) allow-list is exactly the 5 infrastructure tools; removed tools return 400
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from cloud import db, keys
from cloud.main import create_app

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_memory_store():
    """Clear in-memory state before each test to prevent cross-test pollution."""
    db._MEMORY_CUSTOMERS.clear()
    db._MEMORY_USERS.clear()
    db._MEMORY_USERS_BY_IDENTITY.clear()
    db._next_user_id = 1
    keys._MEMORY_KEYS.clear()
    # Reset cached Fernet so tests always get a fresh ephemeral key
    keys._fernet = None
    yield


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _seed(api_key: str, credits: int = 10, plan: str = "starter") -> db.Customer:
    """Insert a test customer into the in-memory store."""
    customer = db.Customer(
        api_key=api_key,
        credits=credits,
        plan=plan,
    )
    db._MEMORY_CUSTOMERS[api_key] = customer
    return customer


# ── (a) authentication ────────────────────────────────────────────────────────


async def test_missing_api_key_returns_401(client):
    resp = await client.post("/v1/enrich", json={"tool": "search_ip", "target": "8.8.8.8"})
    assert resp.status_code == 401


async def test_invalid_api_key_returns_401(client):
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_ip", "target": "8.8.8.8"},
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert resp.status_code == 401


# ── (b) credits exhausted ─────────────────────────────────────────────────────


async def test_zero_credits_returns_402(client):
    _seed("key-402", credits=0)
    # search_dns has KeySource.none — key resolution is skipped, so 402 fires cleanly
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_dns", "target": "example.com"},
        headers={"X-API-Key": "key-402"},
    )
    assert resp.status_code == 402
    body = resp.json()
    assert "commercial@openosint.tech" in body["detail"]["message"]


# ── (c) success path ──────────────────────────────────────────────────────────


async def test_success_decrements_credits_and_returns_result(client):
    _seed("key-200", credits=5)
    fake_result = {
        "tool": "search_dns",
        "target": "example.com",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "results": ["[+] A: 93.184.216.34"],
        "error": None,
    }
    with patch("cloud.tools.dispatch", new=AsyncMock(return_value=fake_result)):
        resp = await client.post(
            "/v1/enrich",
            json={"tool": "search_dns", "target": "example.com"},
            headers={"X-API-Key": "key-200"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["credits_left"] == 4
    assert body["results"] == ["[+] A: 93.184.216.34"]
    assert body["error"] is None
    # Confirm the DB was actually mutated
    assert db._MEMORY_CUSTOMERS["key-200"].credits == 4


# ── (d) tool not on allow-list ────────────────────────────────────────────────


async def test_non_allowlisted_tool_returns_400(client):
    _seed("key-400", credits=10)
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_breach", "target": "8.8.8.8"},
        headers={"X-API-Key": "key-400"},
    )
    assert resp.status_code == 400
    # Credits must NOT have been decremented for a rejected tool
    assert db._MEMORY_CUSTOMERS["key-400"].credits == 10


# ── usage endpoint ────────────────────────────────────────────────────────────


async def test_usage_returns_credits_and_plan(client):
    _seed("key-usage", credits=7, plan="pro")
    resp = await client.get("/v1/usage", headers={"X-API-Key": "key-usage"})
    assert resp.status_code == 200
    assert resp.json() == {"plan": "pro", "credits": 7}


# ── (e) key store / retrieve roundtrip ───────────────────────────────────────


async def test_key_store_retrieve_roundtrip():
    _seed("key-roundtrip")
    await keys.store_key("key-roundtrip", "ipinfo", "tok_abc123")

    # Plaintext is recoverable
    assert await keys.get_key("key-roundtrip", "ipinfo") == "tok_abc123"

    # Raw store holds ciphertext, not plaintext
    raw = keys._MEMORY_KEYS[("key-roundtrip", "ipinfo")]
    assert b"tok_abc123" not in raw

    # Masked value shows exactly last 4 chars
    listed = await keys.list_keys("key-roundtrip")
    assert listed == [{"provider": "ipinfo", "masked": "****c123"}]

    # Short secret (≤4 chars) never leaks
    assert keys.mask("ab") == "****"
    assert keys.mask("abcd") == "****"
    assert keys.mask("abcde") == "****bcde"


# ── (e1) MultiFernet rotation: old secrets still decrypt, writes use new key ──


async def test_multifernet_rotation_old_secret_decrypts_and_reencrypts():
    from cryptography.fernet import Fernet, InvalidToken

    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    # Pre-rotation: single key A, matches today's single-key setups.
    with patch.dict(os.environ, {"CONFIG_ENCRYPTION_KEY": key_a}):
        keys._fernet = None
        await keys.store_key("key-rotate", "ipinfo", "secret_under_a")

    # Rotate: B becomes primary, A kept only so old ciphertext still decrypts.
    with patch.dict(os.environ, {"CONFIG_ENCRYPTION_KEY": f"{key_b},{key_a}"}):
        keys._fernet = None

        # Old secret, encrypted under A, still readable post-rotation.
        assert await keys.get_key("key-rotate", "ipinfo") == "secret_under_a"

        # Re-encrypts under the new primary (B) on next write.
        await keys.store_key("key-rotate", "ipinfo", "secret_under_b")
        new_ciphertext = keys._MEMORY_KEYS[("key-rotate", "ipinfo")]
        assert Fernet(key_b).decrypt(new_ciphertext) == b"secret_under_b"
        with pytest.raises(InvalidToken):
            Fernet(key_a).decrypt(new_ciphertext)  # not readable by the old key alone

        # Public API round-trips correctly against the new ciphertext too.
        assert await keys.get_key("key-rotate", "ipinfo") == "secret_under_b"


# ── (e2) censys compound secret: bad format rejected, good format round-trips ─


async def test_censys_secret_bad_format_returns_422(client):
    _seed("key-censys-bad", credits=5)
    resp = await client.post(
        "/v1/keys",
        json={"provider": "censys", "secret": "no-colon-here"},
        headers={"X-API-Key": "key-censys-bad"},
    )
    assert resp.status_code == 422
    assert "censys" in resp.json()["detail"]
    assert await keys.get_key("key-censys-bad", "censys") is None


async def test_censys_secret_well_formed_round_trips_to_censys_keys(client):
    from cloud.tools import _censys_keys

    _seed("key-censys-good", credits=5)
    resp = await client.post(
        "/v1/keys",
        json={"provider": "censys", "secret": "myapiid:myapisecret"},
        headers={"X-API-Key": "key-censys-good"},
    )
    assert resp.status_code == 204

    stored = await keys.get_key("key-censys-good", "censys")
    assert stored == "myapiid:myapisecret"
    assert _censys_keys(stored) == {
        "CENSYS_API_ID": "myapiid",
        "CENSYS_SECRET": "myapisecret",
    }


# ── (f) enrich uses stored customer key ──────────────────────────────────────


async def test_enrich_uses_stored_customer_key(client):
    _seed("key-byok", credits=5)
    await keys.store_key("key-byok", "ipinfo", "tok_abc123")

    captured: list[str | None] = []

    async def fake_dispatch(tool, target, api_key=None):
        captured.append(api_key)
        return {
            "tool": tool,
            "target": target,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "results": ["[+] IP: 1.2.3.4"],
            "error": None,
        }

    with patch("cloud.tools.dispatch", new=fake_dispatch):
        resp = await client.post(
            "/v1/enrich",
            json={"tool": "search_ip", "target": "1.2.3.4"},
            headers={"X-API-Key": "key-byok"},
        )

    assert resp.status_code == 200
    assert captured == ["tok_abc123"]
    assert db._MEMORY_CUSTOMERS["key-byok"].credits == 4


# ── (g) missing customer key → 422, credits unchanged ────────────────────────


async def test_missing_customer_key_returns_422_no_credit_deduct(client):
    _seed("key-nokey", credits=5)
    # No ipinfo key stored

    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_ip", "target": "1.2.3.4"},
        headers={"X-API-Key": "key-nokey"},
    )

    assert resp.status_code == 422
    assert "ipinfo" in resp.json()["detail"]
    # Credits must be untouched
    assert db._MEMORY_CUSTOMERS["key-nokey"].credits == 5


# ── (h) server-source tool reads key from env ────────────────────────────────


async def test_server_source_reads_env_key(client):
    _seed("key-server", credits=5)
    captured: list[str | None] = []

    async def fake_dispatch(tool, target, api_key=None):
        captured.append(api_key)
        return {
            "tool": tool,
            "target": target,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "results": ["[IP2Location] IP: 1.2.3.4"],
            "error": None,
        }

    with patch("cloud.tools.dispatch", new=fake_dispatch):
        with patch.dict(os.environ, {"IP2LOCATION_API_KEY": "srv_key_xyz"}):
            resp = await client.post(
                "/v1/enrich",
                json={"tool": "search_ip2location", "target": "1.2.3.4"},
                headers={"X-API-Key": "key-server"},
            )

    assert resp.status_code == 200
    assert captured == ["srv_key_xyz"]
    assert db._MEMORY_CUSTOMERS["key-server"].credits == 4


# ── (h2) per-tool credit cost + platform-pool burst limiter ─────────────────


async def test_shodan_costs_configured_credit_amount(client):
    from cloud.config import SHODAN_CREDIT_COST
    from cloud.tools import _SHODAN_ENTRY

    _seed("key-shodan-cost", credits=10)

    async def fake_dispatch(tool, target, api_key=None):
        return {
            "tool": tool,
            "target": target,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "results": ["[Shodan] Host: 1.2.3.4"],
            "error": None,
        }

    # search_shodan is deliberately absent from ALLOW_LIST until SHODAN_API_KEY
    # is set in prod (see cloud/tools.py) — reinject it here so this test can
    # still exercise the real >1-cost billing path via _SHODAN_ENTRY.
    with patch.dict("cloud.tools.ALLOW_LIST", {"search_shodan": _SHODAN_ENTRY}):
        with patch("cloud.tools.dispatch", new=fake_dispatch):
            with patch.dict(os.environ, {"SHODAN_API_KEY": "srv_shodan_key"}):
                resp = await client.post(
                    "/v1/enrich",
                    json={"tool": "search_shodan", "target": "1.2.3.4"},
                    headers={"X-API-Key": "key-shodan-cost"},
                )

    assert resp.status_code == 200
    assert resp.json()["credits_left"] == 10 - SHODAN_CREDIT_COST
    assert db._MEMORY_CUSTOMERS["key-shodan-cost"].credits == 10 - SHODAN_CREDIT_COST


async def test_platform_pool_burst_limit_returns_429(client):
    from cloud.config import SHODAN_CREDIT_COST
    from cloud.rate_limit import InProcessSlidingWindowLimiter
    from cloud.tools import _SHODAN_ENTRY

    _seed("key-burst", credits=10)

    async def fake_dispatch(tool, target, api_key=None):
        return {
            "tool": tool,
            "target": target,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "results": ["[Shodan] Host: 1.2.3.4"],
            "error": None,
        }

    # search_shodan is deliberately absent from ALLOW_LIST — reinject it (see
    # test_shodan_costs_configured_credit_amount) so this still exercises the
    # real platform-pool burst limiter via a >1-cost tool.
    one_call_limiter = InProcessSlidingWindowLimiter(window_secs=60, max_calls=1)
    with patch.dict("cloud.tools.ALLOW_LIST", {"search_shodan": _SHODAN_ENTRY}):
        with patch("cloud.rate_limit.platform_pool_limiter", one_call_limiter):
            with patch("cloud.tools.dispatch", new=fake_dispatch):
                with patch.dict(os.environ, {"SHODAN_API_KEY": "srv_shodan_key"}):
                    first = await client.post(
                        "/v1/enrich",
                        json={"tool": "search_shodan", "target": "1.2.3.4"},
                        headers={"X-API-Key": "key-burst"},
                    )
                    second = await client.post(
                        "/v1/enrich",
                        json={"tool": "search_shodan", "target": "1.2.3.4"},
                        headers={"X-API-Key": "key-burst"},
                    )

    assert first.status_code == 200
    assert second.status_code == 429
    # Rejected (429) call must not be charged
    assert db._MEMORY_CUSTOMERS["key-burst"].credits == 10 - SHODAN_CREDIT_COST


# ── (i) upstream error leaves credits unchanged ──────────────────────────────


async def test_upstream_error_leaves_credits_unchanged(client):
    _seed("key-err", credits=5)
    await keys.store_key("key-err", "ipinfo", "tok_abc123")

    error_result = {
        "tool": "search_ip",
        "target": "1.2.3.4",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "results": ["Scan error: network failure"],
        "error": None,
    }

    with patch("cloud.tools.dispatch", new=AsyncMock(return_value=error_result)):
        resp = await client.post(
            "/v1/enrich",
            json={"tool": "search_ip", "target": "1.2.3.4"},
            headers={"X-API-Key": "key-err"},
        )

    assert resp.status_code == 200
    assert resp.json()["results"] == ["Scan error: network failure"]
    assert resp.json()["credits_left"] == 5
    assert db._MEMORY_CUSTOMERS["key-err"].credits == 5


async def test_platform_pool_upstream_error_charges_zero_credits(client):
    """A >1-cost platform tool (Shodan) must not charge on upstream failure."""
    from cloud.tools import _SHODAN_ENTRY

    _seed("key-shodan-err", credits=10)

    error_result = {
        "tool": "search_shodan",
        "target": "1.2.3.4",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "results": ["Scan error: Shodan quota exceeded"],
        "error": None,
    }

    # search_shodan is deliberately absent from ALLOW_LIST — reinject it (see
    # test_shodan_costs_configured_credit_amount).
    with patch.dict("cloud.tools.ALLOW_LIST", {"search_shodan": _SHODAN_ENTRY}):
        with patch("cloud.tools.dispatch", new=AsyncMock(return_value=error_result)):
            with patch.dict(os.environ, {"SHODAN_API_KEY": "srv_shodan_key"}):
                resp = await client.post(
                    "/v1/enrich",
                    json={"tool": "search_shodan", "target": "1.2.3.4"},
                    headers={"X-API-Key": "key-shodan-err"},
                )

    assert resp.status_code == 200
    assert resp.json()["results"] == ["Scan error: Shodan quota exceeded"]
    assert resp.json()["credits_left"] == 10
    assert db._MEMORY_CUSTOMERS["key-shodan-err"].credits == 10


# ── (j) allow-list shape and removed-tool 400s ───────────────────────────────

from cloud.tools import ALLOW_LIST as _ALLOW_LIST

_EXPECTED_TOOLS = {
    "search_ip", "search_ip2location", "search_abuseipdb", "search_dns", "search_domain",
    "search_virustotal", "search_censys",
}


def test_allow_list_is_exactly_the_infrastructure_tools():
    assert set(_ALLOW_LIST.keys()) == _EXPECTED_TOOLS


async def test_search_github_returns_400(client):
    _seed("key-gh-400", credits=5)
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_github", "target": "octocat"},
        headers={"X-API-Key": "key-gh-400"},
    )
    assert resp.status_code == 400
    assert db._MEMORY_CUSTOMERS["key-gh-400"].credits == 5


async def test_search_paste_returns_400(client):
    _seed("key-paste-400", credits=5)
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_paste", "target": "example@example.com"},
        headers={"X-API-Key": "key-paste-400"},
    )
    assert resp.status_code == 400
    assert db._MEMORY_CUSTOMERS["key-paste-400"].credits == 5


async def test_generate_dorks_returns_400(client):
    _seed("key-dorks-400", credits=5)
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "generate_dorks", "target": "example.com"},
        headers={"X-API-Key": "key-dorks-400"},
    )
    assert resp.status_code == 400
    assert db._MEMORY_CUSTOMERS["key-dorks-400"].credits == 5


# ── (l) Shodan attribution appended only for search_shodan ───────────────────


async def test_dispatch_appends_shodan_attribution():
    from cloud import tools as cloud_tools

    # search_shodan is deliberately absent from ALLOW_LIST (see
    # test_shodan_costs_configured_credit_amount) — reinject it so dispatch()
    # still runs the real attribution-appending path.
    with patch.dict("cloud.tools.ALLOW_LIST", {"search_shodan": cloud_tools._SHODAN_ENTRY}):
        with patch("cloud.tools.run_shodan_osint", new=AsyncMock(return_value="[Shodan] Host: 1.2.3.4")):
            result = await cloud_tools.dispatch("search_shodan", "1.2.3.4", api_key="k")

    assert result["results"][-1] == "Data provided by Shodan (shodan.io)."


async def test_dispatch_does_not_attribute_other_tools():
    from cloud import tools as cloud_tools

    with patch("cloud.tools.run_dns_osint", new=AsyncMock(return_value="A: 1.2.3.4")):
        result = await cloud_tools.dispatch("search_dns", "example.com", api_key=None)

    assert "Data provided by Shodan (shodan.io)." not in result["results"]


async def test_shodan_attribution_reaches_rest_response_body(client):
    """Attribution must survive to the actual JSON body the client parses,
    not just the internal dispatch() dict — real dispatch() runs here, only
    the low-level upstream call is mocked."""
    from cloud.tools import _SHODAN_ENTRY

    _seed("key-shodan-attr", credits=10)

    # search_shodan is deliberately absent from ALLOW_LIST — reinject it (see
    # test_shodan_costs_configured_credit_amount).
    with patch.dict("cloud.tools.ALLOW_LIST", {"search_shodan": _SHODAN_ENTRY}):
        with patch("cloud.tools.run_shodan_osint", new=AsyncMock(return_value="[Shodan] Host: 1.2.3.4")):
            with patch.dict(os.environ, {"SHODAN_API_KEY": "srv_shodan_key"}):
                resp = await client.post(
                    "/v1/enrich",
                    json={"tool": "search_shodan", "target": "1.2.3.4"},
                    headers={"X-API-Key": "key-shodan-attr"},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == ["[Shodan] Host: 1.2.3.4", "Data provided by Shodan (shodan.io)."]


async def test_dashboard_requires_login(client):
    resp = await client.get("/dashboard")
    assert resp.status_code == 401


async def test_oauth_callback_redirects_to_dashboard_and_dashboard_loads(client, monkeypatch):
    from cloud.routes import oauth as oauth_routes

    class FakeOAuthClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"sub": "google_dash", "email": "dash@example.com"}}

    monkeypatch.setattr(oauth_routes.oauth, "create_client", lambda provider: FakeOAuthClient())

    login_resp = await client.get("/auth/callback/google", follow_redirects=False)
    assert login_resp.status_code in (302, 307)
    assert login_resp.headers["location"] == "/dashboard"

    dash_resp = await client.get("/dashboard")
    assert dash_resp.status_code == 200
    assert "text/html" in dash_resp.headers["content-type"]


async def _login(client, monkeypatch, sub: str, email: str) -> None:
    """Shared helper: log the test client in as a fresh OAuth user (session
    cookie persists on the client for subsequent requests)."""
    from cloud.routes import oauth as oauth_routes

    class FakeOAuthClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"sub": sub, "email": email}}

    monkeypatch.setattr(oauth_routes.oauth, "create_client", lambda provider: FakeOAuthClient())
    await client.get("/auth/callback/google", follow_redirects=False)


async def test_link_key_requires_login(client):
    resp = await client.post("/v1/link-key", json={"customer_api_key": "whatever"})
    assert resp.status_code == 401


async def test_link_key_not_found_returns_404(client, monkeypatch):
    await _login(client, monkeypatch, "google_link_404", "l404@example.com")
    resp = await client.post("/v1/link-key", json={"customer_api_key": "no-such-key"})
    assert resp.status_code == 404


async def test_link_key_success(client, monkeypatch):
    _seed("key-link-ok", credits=5)
    await _login(client, monkeypatch, "google_link_ok", "lok@example.com")

    resp = await client.post("/v1/link-key", json={"customer_api_key": "key-link-ok"})
    assert resp.status_code == 200

    me = await client.get("/v1/me")
    assert me.json()["linked"] is True


async def test_link_key_conflict_returns_409(client, monkeypatch):
    _seed("key-link-conflict", credits=5)

    await _login(client, monkeypatch, "google_link_c1", "c1@example.com")
    first = await client.post("/v1/link-key", json={"customer_api_key": "key-link-conflict"})
    assert first.status_code == 200

    await client.get("/auth/logout")
    await _login(client, monkeypatch, "google_link_c2", "c2@example.com")
    second = await client.post("/v1/link-key", json={"customer_api_key": "key-link-conflict"})
    assert second.status_code == 409


# ── logging: no target values, in any log line, on the Cloud surface ─────────
#
# cloud/main.py used to run its root logger at INFO, which let every
# openosint.tools.* module's free-text logging (built for CLI/MCP debugging,
# and including the raw target) straight through. See
# .claude/LEGAL_CONTEXT.md §4.1 and legal/INCIDENT-NOTES.md.


def test_shared_tool_loggers_are_silenced_for_cloud(caplog):
    """Direct proof of the suppression mechanism: openosint.tools.* loggers
    inherit an effective level above CRITICAL once cloud.main has configured
    logging, so a call that would otherwise log the target produces nothing."""
    import logging as _logging

    import cloud.main  # noqa: F401 -- import applies the logging config

    target_logger = _logging.getLogger("openosint.tools.search_ip")
    sentinel = "SENTINEL-TARGET-203.0.113.99"
    with caplog.at_level(_logging.DEBUG):
        target_logger.info("Starting IP lookup for: %s", sentinel)
        target_logger.warning("IP lookup failed: %s", sentinel)
        target_logger.exception("Unexpected error during IP lookup: %s", sentinel)

    assert sentinel not in caplog.text


async def test_enrich_end_to_end_logs_no_target_value(client, caplog):
    """Run a real /v1/enrich request through the real search_ip tool code
    (only the outbound HTTP call is faked) and prove the captured log output
    contains the tool name and outcome status, but never the target."""
    import logging

    _seed("key-log-proof", credits=5)
    await keys.store_key("key-log-proof", "ipinfo", "tok_test_byok")
    sentinel_ip = "203.0.113.77"  # TEST-NET-3 (RFC 5737) — reserved, not a real host

    fake_response = type(
        "FakeResponse",
        (),
        {"status_code": 200, "json": lambda self: {"ip": sentinel_ip, "org": "AS0 Reserved"}},
    )()

    with (
        patch("openosint.tools.search_ip.requests.get", return_value=fake_response),
        caplog.at_level(logging.DEBUG),
    ):
        resp = await client.post(
            "/v1/enrich",
            json={"tool": "search_ip", "target": sentinel_ip},
            headers={"X-API-Key": "key-log-proof"},
        )

    assert resp.status_code == 200
    assert sentinel_ip not in caplog.text, "target value leaked into Cloud's captured logs"
    assert "tool=search_ip" in caplog.text
    assert "status=ok" in caplog.text


def test_retention_constant_matches_documented_policy():
    """legal/PRIVACY_POLICY.md §4 states '12 months' — pinned to this constant
    so the documented figure and the implemented one cannot drift apart."""
    from cloud.config import USAGE_METADATA_RETENTION_DAYS

    assert USAGE_METADATA_RETENTION_DAYS == 365
