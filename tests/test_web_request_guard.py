"""Host and browser-origin checks on the local web server."""

import pytest
from httpx import ASGITransport, AsyncClient

import openosint.web_server as ws

PORT = 8080
LOCAL_HOST = f"127.0.0.1:{PORT}"

# Endpoints that change state, use locally held keys or run a tool, plus the
# read-only graph routes. Method matters not: the guard covers all of them.
GUARDED = [
    ("GET", "/api/stream/generate_dorks?input=example.com"),
    ("POST", "/api/run/generate_dorks"),
    ("POST", "/api/setup"),
    ("POST", "/api/chat"),
    ("POST", "/api/openai/test"),
    ("POST", "/api/graph/review/decide"),
    ("GET", "/api/graph/subgraph"),
    ("GET", "/api/tools"),
]


def make_client(host="127.0.0.1", port=PORT, base=LOCAL_HOST):
    app = ws.create_app(host=host, port=port)
    return AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{base}")


async def send(client, method, path, headers=None, **kwargs):
    return await client.request(method, path, headers=headers or {}, **kwargs)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in ("OPENOSINT_ALLOWED_HOSTS", "OPENOSINT_ALLOWED_ORIGINS", "DEMO_ALLOWED_ORIGINS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ws, "_ROOT", tmp_path)  # /api/setup must never touch the real .env


# --------------------------------------------------------------------------
# Host header
# --------------------------------------------------------------------------


class TestHostValidation:
    @pytest.mark.parametrize(
        "host",
        [
            "evil.example.com",
            "evil.example.com:8080",
            "localhost.evil.com:8080",
            "127.0.0.1.evil.com:8080",
            "127.0.0.2:8080",
            "localhost@evil.com",
            "localhost.:8080",
            "0.0.0.0:8080",
            "::1",  # unbracketed IPv6 is not a valid Host
            "",
        ],
    )
    async def test_unexpected_host_is_rejected(self, host):
        async with make_client() as c:
            for path in ("/api/health", "/"):
                r = await send(c, "GET", path, {"Host": host})
                assert r.status_code == 403, (host, path)

    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1:8080", "localhost:8080", "LOCALHOST:8080", "[::1]:8080", "localhost"],
    )
    async def test_loopback_hosts_are_accepted(self, host):
        async with make_client() as c:
            r = await send(c, "GET", "/api/health", {"Host": host})
            assert r.status_code == 200, host

    async def test_loopback_name_on_the_wrong_port_is_rejected(self):
        async with make_client() as c:
            r = await send(c, "GET", "/api/health", {"Host": "localhost:9999"})
            assert r.status_code == 403

    async def test_allowlisted_host_is_accepted(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOWED_HOSTS", "osint.lan, other.lan:8080")
        async with make_client() as c:
            for host in ("osint.lan:8080", "osint.lan", "other.lan:8080"):
                r = await send(c, "GET", "/api/health", {"Host": host})
                assert r.status_code == 200, host
            r = await send(c, "GET", "/api/health", {"Host": "other.lan:9999"})
            assert r.status_code == 403
            r = await send(c, "GET", "/api/health", {"Host": "evil.example.com"})
            assert r.status_code == 403

    @pytest.mark.parametrize("bind", ["0.0.0.0", None])
    async def test_remote_bind_skips_host_validation_without_an_allowlist(self, bind):
        async with make_client(host=bind, base="osint.example.com") as c:
            r = await send(c, "GET", "/api/health", {"Host": "osint.example.com"})
            assert r.status_code == 200

    @pytest.mark.parametrize("bind", ["0.0.0.0", None])
    async def test_remote_bind_validates_host_when_an_allowlist_is_set(self, bind, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOWED_HOSTS", "osint.example.com")
        async with make_client(host=bind) as c:
            ok = await send(c, "GET", "/api/health", {"Host": "osint.example.com"})
            local = await send(c, "GET", "/api/health", {"Host": "localhost:8080"})
            evil = await send(c, "GET", "/api/health", {"Host": "evil.example.com"})
        assert (ok.status_code, local.status_code, evil.status_code) == (200, 200, 403)


# --------------------------------------------------------------------------
# Browser-origin guard
# --------------------------------------------------------------------------


class TestBrowserOriginGuard:
    @pytest.mark.parametrize("site", ["cross-site", "same-site"])
    @pytest.mark.parametrize("method,path", GUARDED)
    async def test_cross_site_fetch_metadata_is_rejected(self, method, path, site):
        async with make_client() as c:
            r = await send(c, method, path, {"Sec-Fetch-Site": site}, content=b"{}")
        assert r.status_code == 403

    @pytest.mark.parametrize("method,path", GUARDED)
    async def test_mismatched_origin_is_rejected(self, method, path):
        async with make_client() as c:
            for origin in ("http://evil.example.com", "null", "http://127.0.0.1:9999"):
                r = await send(c, method, path, {"Origin": origin}, content=b"{}")
                assert r.status_code == 403, origin

    @pytest.mark.parametrize("method,path", GUARDED)
    async def test_same_origin_ui_requests_pass(self, method, path):
        headers = {
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"http://{LOCAL_HOST}",
            "Content-Type": "application/json",
        }
        async with make_client() as c:
            r = await send(c, method, path, headers, content=b"{}")
        assert r.status_code != 403

    async def test_user_initiated_navigation_to_an_api_url_passes(self):
        async with make_client() as c:
            r = await send(c, "GET", "/api/tools", {"Sec-Fetch-Site": "none"})
        assert r.status_code == 200

    @pytest.mark.parametrize("method,path", GUARDED)
    async def test_header_less_scripts_keep_working(self, method, path):
        async with make_client() as c:
            r = await send(c, method, path, {"Content-Type": "application/json"}, content=b"{}")
        assert r.status_code != 403

    async def test_allowlisted_origin_passes_even_when_cross_site(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOWED_ORIGINS", "http://localhost:3000")
        headers = {"Sec-Fetch-Site": "same-site", "Origin": "http://localhost:3000"}
        async with make_client() as c:
            r = await send(c, "GET", "/api/tools", headers)
        assert r.status_code == 200

    async def test_explicit_cors_origin_setting_is_honoured(self, monkeypatch):
        monkeypatch.setenv("DEMO_ALLOWED_ORIGINS", "https://ui.example.com")
        headers = {"Sec-Fetch-Site": "cross-site", "Origin": "https://ui.example.com"}
        async with make_client() as c:
            r = await send(c, "GET", "/api/tools", headers)
        assert r.status_code == 200

    async def test_default_cors_origins_are_not_trusted_by_the_guard(self):
        headers = {"Sec-Fetch-Site": "same-site", "Origin": "http://localhost:3000"}
        async with make_client() as c:
            r = await send(c, "GET", "/api/tools", headers)
        assert r.status_code == 403

    async def test_cors_preflight_is_answered_not_blocked(self):
        preflight = {
            "Origin": "http://localhost:3000",
            "Sec-Fetch-Site": "same-site",
            "Access-Control-Request-Method": "POST",
        }
        async with make_client() as c:
            r = await send(c, "OPTIONS", "/api/chat", preflight)
            evil_host = await send(c, "OPTIONS", "/api/chat", {**preflight, "Host": "evil.example"})
        assert r.status_code in (200, 204)
        assert evil_host.status_code == 403

    async def test_health_and_static_navigation_stay_reachable_cross_site(self):
        async with make_client() as c:
            health = await send(c, "GET", "/api/health", {"Sec-Fetch-Site": "cross-site"})
            page = await send(c, "GET", "/", {"Sec-Fetch-Site": "cross-site"})
        assert (health.status_code, page.status_code) == (200, 200)

    async def test_guard_applies_on_a_remote_bind_too(self):
        async with make_client(host="0.0.0.0", base="osint.example.com") as c:
            bad = await send(c, "GET", "/api/tools", {"Origin": "http://evil.example.com"})
            good = await send(c, "GET", "/api/tools", {"Sec-Fetch-Site": "same-origin"})
        assert (bad.status_code, good.status_code) == (403, 200)

    async def test_origin_behind_a_tls_terminating_proxy_matches_on_host(self):
        # The proxy speaks https to the browser but http to us, so only host:port is compared.
        headers = {"Origin": "https://osint.example.com", "Host": "osint.example.com"}
        async with make_client(host="0.0.0.0", base="osint.example.com") as c:
            r = await send(c, "GET", "/api/tools", headers)
        assert r.status_code == 200


# --------------------------------------------------------------------------
# /api/setup content type
# --------------------------------------------------------------------------


class TestSetupContentType:
    @pytest.mark.parametrize(
        "content_type",
        ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""],
    )
    async def test_non_json_content_type_is_rejected(self, content_type):
        headers = {"Content-Type": content_type} if content_type else {}
        async with make_client() as c:
            r = await send(c, "POST", "/api/setup", headers, content=b"{}")
        assert r.status_code == 415

    @pytest.mark.parametrize(
        "content_type", ["application/json", "application/json; charset=utf-8"]
    )
    async def test_json_content_type_is_accepted(self, content_type, tmp_path):
        async with make_client() as c:
            r = await send(c, "POST", "/api/setup", {"Content-Type": content_type}, content=b"{}")
        assert r.status_code == 200
