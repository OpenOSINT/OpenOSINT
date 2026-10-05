"""/api/setup stores keys in the data directory; /api/setup/status feeds the key form."""

from __future__ import annotations

import os
import stat

import pytest
from httpx import ASGITransport, AsyncClient

import openosint.env as env_module
import openosint.web_server as ws
from openosint import config_store
from openosint.settings_catalog import SETTINGS

REMOTE = ("203.0.113.5", 12345)
TOKEN = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "_ROOT", tmp_path / "package-root")  # legacy location must stay untouched
    monkeypatch.setattr(env_module, "_origins", {})
    monkeypatch.setattr(ws, "_SETUP_ATTEMPTS", {})
    monkeypatch.delenv("OPENOSINT_SETUP_TOKEN", raising=False)
    owned = [s.key for s in SETTINGS]
    for key in owned:
        monkeypatch.delenv(key, raising=False)
    yield
    # /api/setup writes os.environ directly, which monkeypatch cannot undo.
    for key in owned:
        os.environ.pop(key, None)


def client(peer=None, host="127.0.0.1"):
    app = ws.create_app(host=host, port=8080)  # loopback bind by default: not restricted
    transport = ASGITransport(app=app, client=peer) if peer else ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://127.0.0.1:8080")


class TestSaveToDataDirectory:
    async def test_key_is_written_to_openosint_home_not_the_package(self, tmp_path):
        async with client() as c:
            resp = await c.post("/api/setup", json={"SHODAN_API_KEY": "sk-secret-123"})

        body = resp.json()
        home = tmp_path / "openosint-home"
        assert resp.status_code == 200
        assert body["applied"] == ["SHODAN_API_KEY"]
        assert body["saved_to"] == str(home / "config.env")
        assert config_store.read_config() == {"SHODAN_API_KEY": "sk-secret-123"}
        assert not (tmp_path / "package-root").exists()
        assert os.environ["SHODAN_API_KEY"] == "sk-secret-123"

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    async def test_saved_file_is_user_only(self, tmp_path):
        async with client() as c:
            await c.post("/api/setup", json={"SHODAN_API_KEY": "x"})

        mode = stat.S_IMODE((tmp_path / "openosint-home" / "config.env").stat().st_mode)
        assert mode == 0o600

    async def test_response_never_echoes_the_secret(self):
        async with client() as c:
            resp = await c.post("/api/setup", json={"SHODAN_API_KEY": "sk-very-secret-value"})

        assert "sk-very-secret-value" not in resp.text

    async def test_secret_is_not_logged(self, caplog):
        caplog.set_level("DEBUG")
        async with client() as c:
            await c.post("/api/setup", json={"SHODAN_API_KEY": "sk-logged-secret"})

        assert "sk-logged-secret" not in caplog.text

    async def test_new_value_replaces_old_and_keeps_others(self):
        async with client() as c:
            await c.post("/api/setup", json={"SHODAN_API_KEY": "old", "HIBP_API_KEY": "hibp"})
            await c.post("/api/setup", json={"SHODAN_API_KEY": "new"})

        assert config_store.read_config() == {"SHODAN_API_KEY": "new", "HIBP_API_KEY": "hibp"}

    async def test_value_with_control_characters_is_rejected_not_stored(self):
        async with client() as c:
            resp = await c.post("/api/setup", json={"SHODAN_API_KEY": "a\nEVIL=1"})

        assert resp.json()["rejected"] == ["SHODAN_API_KEY"]
        assert config_store.read_config() == {}

    async def test_non_object_body_is_a_400(self):
        async with client() as c:
            resp = await c.post("/api/setup", json=["SHODAN_API_KEY"])

        assert resp.status_code == 400

    async def test_unwritable_data_directory_is_a_clear_500(self, monkeypatch):
        def boom(_updates):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(ws, "write_config", boom)
        async with client() as c:
            resp = await c.post("/api/setup", json={"SHODAN_API_KEY": "x"})

        assert resp.status_code == 500
        assert "Could not save" in resp.json()["message"]
        assert "SHODAN_API_KEY" not in os.environ

    async def test_a_real_environment_variable_wins_and_is_reported(self, monkeypatch):
        monkeypatch.setenv("SHODAN_API_KEY", "from-real-env")
        async with client() as c:
            resp = await c.post("/api/setup", json={"SHODAN_API_KEY": "from-ui"})

        body = resp.json()
        assert body["shadowed_by_environment"] == ["SHODAN_API_KEY"]
        assert body["applied"] == []
        assert os.environ["SHODAN_API_KEY"] == "from-real-env"
        assert config_store.read_config() == {"SHODAN_API_KEY": "from-ui"}

    async def test_saved_key_is_seen_after_a_restart(self, monkeypatch, tmp_path):
        async with client() as c:
            await c.post("/api/setup", json={"VIRUSTOTAL_API_KEY": "vt-key"})
        monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)  # new process: no env yet
        monkeypatch.setattr(env_module, "_load_attempted", False)
        monkeypatch.setattr(env_module, "_loaded_path", None)
        monkeypatch.chdir(tmp_path)

        env_module.load_env()

        assert os.environ["VIRUSTOTAL_API_KEY"] == "vt-key"
        monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)

    async def test_every_catalog_key_is_saveable(self):
        payload = {s.key: f"value-{i}" for i, s in enumerate(SETTINGS)}
        async with client() as c:
            resp = await c.post("/api/setup", json=payload)

        assert sorted(resp.json()["applied"]) == sorted(payload)
        for key in payload:
            os.environ.pop(key, None)


class TestTokenPath:
    async def test_remote_caller_without_token_gets_the_docker_message(self):
        async with client(REMOTE) as c:
            resp = await c.post("/api/setup", json={"SHODAN_API_KEY": "x"})

        assert resp.status_code == 403
        message = resp.json()["message"]
        assert "OPENOSINT_SETUP_TOKEN" in message
        assert "Docker" in message
        assert config_store.read_config() == {}

    async def test_remote_caller_with_the_token_saves_into_the_data_directory(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_SETUP_TOKEN", TOKEN)
        async with client(REMOTE) as c:
            resp = await c.post(
                "/api/setup", json={"SHODAN_API_KEY": "via-token"}, headers={"X-Setup-Token": TOKEN}
            )

        assert resp.status_code == 200
        assert config_store.read_config() == {"SHODAN_API_KEY": "via-token"}
        os.environ.pop("SHODAN_API_KEY", None)

    async def test_repeated_wrong_tokens_are_throttled(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_SETUP_TOKEN", TOKEN)
        statuses = []
        async with client(REMOTE) as c:
            for i in range(ws._SETUP_RL_MAX + 3):
                resp = await c.post(
                    "/api/setup", json={"SHODAN_API_KEY": "x"}, headers={"X-Setup-Token": f"guess-{i}"}
                )
                statuses.append(resp.status_code)
            right = await c.post(
                "/api/setup", json={"SHODAN_API_KEY": "x"}, headers={"X-Setup-Token": TOKEN}
            )

        assert statuses[: ws._SETUP_RL_MAX] == [403] * ws._SETUP_RL_MAX
        assert statuses[ws._SETUP_RL_MAX :] == [429] * 3
        assert right.status_code == 429  # even the right token waits out the window

    async def test_loopback_callers_are_never_throttled(self):
        async with client() as c:
            statuses = {
                (await c.post("/api/setup", json={})).status_code for _ in range(ws._SETUP_RL_MAX + 5)
            }

        assert statuses == {200}


class TestSetupStatus:
    async def test_lists_every_key_with_the_ai_provider_first_and_links(self):
        async with client() as c:
            body = (await c.get("/api/setup/status")).json()

        keys = body["keys"]
        assert {k["key"] for k in keys} == {s.key for s in SETTINGS}
        assert keys[0]["group"] == "ai"
        assert all(k["url"].startswith("https://") for k in keys)
        assert [k["group"] for k in keys] == sorted((k["group"] for k in keys), key=lambda g: g != "ai")

    async def test_reports_configured_without_returning_values(self, monkeypatch):
        monkeypatch.setenv("SHODAN_API_KEY", "sk-do-not-leak")
        async with client() as c:
            resp = await c.get("/api/setup/status")

        by_key = {k["key"]: k for k in resp.json()["keys"]}
        assert by_key["SHODAN_API_KEY"]["configured"] is True
        assert by_key["SHODAN_API_KEY"]["source"] == "environment"
        assert by_key["HIBP_API_KEY"]["configured"] is False
        assert "sk-do-not-leak" not in resp.text

    async def test_loopback_can_save_and_sees_the_config_path(self, tmp_path):
        async with client() as c:
            body = (await c.get("/api/setup/status")).json()

        assert body["can_save"] is True
        assert body["forbidden_message"] is None
        assert body["config_path"] == str(tmp_path / "openosint-home" / "config.env")

    async def test_remote_caller_gets_the_explanation_and_no_paths(self):
        async with client(REMOTE) as c:
            body = (await c.get("/api/setup/status")).json()

        assert body["can_save"] is False
        assert "OPENOSINT_SETUP_TOKEN" in body["forbidden_message"]
        assert body["config_path"] is None

    async def test_restricted_instance_does_not_reveal_operator_keys(self, monkeypatch):
        monkeypatch.setenv("SHODAN_API_KEY", "operator-key")
        async with client(host="0.0.0.0") as c:  # a non-loopback bind is always restricted
            body = (await c.get("/api/setup/status")).json()

        assert body["restricted"] is True
        assert all("configured" not in k for k in body["keys"])
