"""`openosint setup brightdata`: guided, opt-in setup. Mocked HTTP and a fake token only, no network."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import openosint.env as env_module
from openosint import brightdata, config_store, setup_brightdata
from openosint.brightdata_response import TOKEN_URL
from openosint.settings_catalog import SETTINGS

TOKEN = "FAKE-token-not-real-0000"
WORK_EMAIL_SENTENCE = (
    "Using this at work? Sign up with your work email so you can invite teammates "
    "and send invoices to your company."
)
LIST_URL = "https://api.brightdata.com/zone/get_active_zones"
ZONE_URL = "https://api.brightdata.com/zone"
SERP_BODY = {
    "zone": {"name": "openosint_serp", "type": "serp"},
    "plan": {"type": "unblocker", "serp": True},
}
UNLOCKER_BODY = {
    "zone": {"name": "openosint_unlocker", "type": "unblocker"},
    "plan": {"type": "unblocker"},
}


class Resp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body if body is not None else [])
        self.headers: dict = {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class Api:
    """Replays queued responses (the last one repeats) and records every call."""

    def __init__(self):
        self.get_queue: list = [Resp(200, [])]
        self.post_queue: list = [Resp(201, {})]
        self.gets: list = []
        self.posts: list = []

    @staticmethod
    def _next(queue):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=None, **kw):
        self.gets.append((url, headers))
        return self._next(self.get_queue)

    def post(self, url, headers=None, json=None, timeout=None, **kw):
        self.posts.append((url, headers, json))
        return self._next(self.post_queue)

    @property
    def urls(self):
        return [u for u, *_ in self.gets] + [u for u, *_ in self.posts]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for setting in SETTINGS:
        monkeypatch.delenv(setting.key, raising=False)
    monkeypatch.delenv(brightdata.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(brightdata, "_surface", "cli")
    monkeypatch.setattr(env_module, "_origins", {})  # value_source() state left by other tests


@pytest.fixture
def api(monkeypatch):
    fake = Api()
    monkeypatch.setattr(setup_brightdata.requests, "get", fake.get)
    monkeypatch.setattr(setup_brightdata.requests, "post", fake.post)
    return fake


class Session:
    def __init__(self, answers=(), secrets=()):
        self.answers, self.secrets = iter(answers), iter(secrets)
        self.prompts: list[str] = []
        self.secret_prompts: list[str] = []
        self.opened: list[str] = []
        self.sleeps: list[float] = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        return next(self.answers)

    def ask_secret(self, prompt):
        self.secret_prompts.append(prompt)
        return next(self.secrets)

    def run(self, *, interactive=True):
        return setup_brightdata.run_setup_brightdata(
            interactive=interactive,
            ask=self.ask,
            ask_secret=self.ask_secret,
            open_browser=self.opened.append,
            sleep=self.sleeps.append,
        )


def _both_zones_listed():
    return [
        Resp(200, []),
        Resp(200, [{"name": "openosint_serp"}]),
        Resp(200, [{"name": "openosint_serp"}, {"name": "openosint_unlocker"}]),
    ]


class TestNonInteractive:
    def test_refuses_with_exit_2_and_prints_the_manual_steps(self, api, capsys):
        session = Session()

        assert session.run(interactive=False) == 2

        err = capsys.readouterr().err
        assert (
            "interactive terminal" in err and "Create a SERP API zone" in err and TOKEN_URL in err
        )
        assert api.urls == [] and session.prompts == [] and session.secret_prompts == []


class TestAlreadySetUp:
    def test_valid_token_and_existing_zones_exit_with_no_prompts_and_no_signup_link(
        self, api, monkeypatch, capsys
    ):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", TOKEN)
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "my_serp")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "my_unlocker")
        api.get_queue = [Resp(200, [{"name": "my_serp"}, {"name": "my_unlocker"}])]
        session = Session()

        assert session.run() == 0

        out = capsys.readouterr().out
        assert "already set up" in out.lower() and "my_serp" in out and "my_unlocker" in out
        assert "get.brightdata.com" not in out and TOKEN not in out
        assert session.prompts == [] and session.opened == [] and not config_store.read_config()
        assert api.urls == [LIST_URL]


class TestNewUser:
    def test_signup_flow_creates_both_zones_after_explicit_yes_and_saves_at_0600(self, api, capsys):
        api.get_queue = _both_zones_listed()
        session = Session(answers=["n", "y", "", "y", "", "y"], secrets=[TOKEN])

        assert session.run() == 0

        assert [p for _, _, p in api.posts] == [SERP_BODY, UNLOCKER_BODY]
        assert all(h["Authorization"] == f"Bearer {TOKEN}" for _, h, _ in api.posts)
        assert config_store.read_config() == {
            "BRIGHTDATA_API_KEY": TOKEN,
            "BRIGHTDATA_SERP_ZONE": "openosint_serp",
            "BRIGHTDATA_UNLOCKER_ZONE": "openosint_unlocker",
        }
        if os.name == "posix":
            assert stat.S_IMODE(config_store.config_path().stat().st_mode) == 0o600
        out = capsys.readouterr()
        assert TOKEN not in out.out + out.err
        assert (
            "You're ready" in out.out
            and "openosint footprint example.com --max-queries 1" in out.out
        )

    def test_the_signup_link_is_the_tracked_cli_setup_link_and_is_disclosed(self, api, capsys):
        api.get_queue = [Resp(200, [])]
        session = Session(answers=["n", "y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert len(session.opened) == 1
        link = session.opened[0]
        assert link.startswith("https://get.brightdata.com/openosint-signup?")
        assert (
            "sid1=cli" in link
            and "sid2=setup" in link
            and "utm_source=openosint" in link
            and "utm_medium=cli" in link
            and "utm_campaign=setup" in link
        )
        assert "commission" in capsys.readouterr().out

    def test_opt_out_opens_a_plain_link_and_drops_the_commission_sentence(
        self, api, monkeypatch, capsys
    ):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")
        session = Session(answers=["n", "y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert session.opened == ["https://brightdata.com"]
        assert "commission" not in capsys.readouterr().out

    def test_the_browser_is_never_opened_without_a_yes(self, api):
        session = Session(answers=["n", "n", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert session.opened == []

    def test_a_user_with_an_account_gets_no_signup_link_and_no_browser(self, api, capsys):
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        out = capsys.readouterr().out
        assert "get.brightdata.com" not in out and TOKEN_URL in out and session.opened == []

    def test_the_token_is_requested_hidden(self, api):
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert len(session.secret_prompts) == 1 and "hidden" in session.secret_prompts[0].lower()
        assert all(TOKEN not in p for p in session.prompts)

    def test_work_email_advice_is_the_agreed_sentence(self):
        assert setup_brightdata.WORK_EMAIL_ADVICE == WORK_EMAIL_SENTENCE

    def test_work_email_advice_claims_nothing_bright_data_does_not_document(self):
        advice = setup_brightdata.WORK_EMAIL_ADVICE.lower()

        assert not any(w in advice for w in ("require", "must", "credit", "bonus", "free", "more"))

    def test_the_work_email_advice_is_shown_at_signup(self, api, capsys):
        session = Session(answers=["n", "n", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert WORK_EMAIL_SENTENCE in capsys.readouterr().out

    def test_the_work_email_advice_is_shown_even_when_referral_links_are_off(
        self, api, monkeypatch, capsys
    ):
        monkeypatch.setenv(brightdata.OPT_OUT_ENV, "1")
        session = Session(answers=["n", "n", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert WORK_EMAIL_SENTENCE in capsys.readouterr().out

    def test_the_work_email_advice_is_hidden_when_you_already_have_an_account(self, api, capsys):
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        out = capsys.readouterr()
        assert "work email" not in out.out + out.err

    def test_the_work_email_advice_is_hidden_when_already_set_up(self, api, monkeypatch, capsys):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", TOKEN)
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "my_serp")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "my_unlocker")
        api.get_queue = [Resp(200, [{"name": "my_serp"}, {"name": "my_unlocker"}])]

        Session().run()

        assert "work email" not in capsys.readouterr().out

    def test_the_docs_page_says_the_same_sentence_at_its_signup_step(self):
        page = (Path(__file__).parent.parent / "site/content/docs/bright-data.md").read_text(
            encoding="utf-8"
        )

        assert WORK_EMAIL_SENTENCE in page


class TestZones:
    def test_declining_creation_posts_nothing_prints_the_dashboard_steps_and_saves_only_the_token(
        self, api, capsys
    ):
        session = Session(answers=["y", "", "n", "", "n"], secrets=[TOKEN])

        assert session.run() == 0

        assert api.posts == []
        assert config_store.read_config() == {"BRIGHTDATA_API_KEY": TOKEN}
        out = capsys.readouterr().out
        assert (
            "Create a SERP API zone in your dashboard" in out
            and "Create a Web Unlocker zone" in out
        )

    def test_creation_prompt_carries_bright_datas_own_warning(self, api):
        session = Session(answers=["y", "", "n", "skip"], secrets=[TOKEN])

        session.run()

        confirm = next(p for p in session.prompts if "Create" in p and "openosint_serp" in p)
        assert (
            "incur charges" in confirm
            and "1 credit" in confirm
            and confirm.rstrip().endswith("[y/N]")
        )

    def test_existing_zones_are_used_without_creating_anything(self, api):
        api.get_queue = [Resp(200, [{"name": "my_serp", "type": "serp"}, {"name": "my_unlocker"}])]
        session = Session(answers=["y", "my_serp", "my_unlocker"], secrets=[TOKEN])

        assert session.run() == 0

        assert api.posts == []
        assert config_store.read_config() == {
            "BRIGHTDATA_API_KEY": TOKEN,
            "BRIGHTDATA_SERP_ZONE": "my_serp",
            "BRIGHTDATA_UNLOCKER_ZONE": "my_unlocker",
        }

    def test_existing_zone_names_are_shown_when_asking(self, api, capsys):
        api.get_queue = [Resp(200, [{"name": "my_serp"}, "plain_name"])]
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        out = capsys.readouterr().out
        assert "my_serp" in out and "plain_name" in out

    def test_a_typed_name_that_does_not_exist_is_created_after_a_yes(self, api):
        api.get_queue = [Resp(200, []), Resp(200, [{"name": "custom"}])]
        session = Session(answers=["y", "custom", "y", "skip"], secrets=[TOKEN])

        session.run()

        assert api.posts[0][2]["zone"]["name"] == "custom"
        assert config_store.read_config()["BRIGHTDATA_SERP_ZONE"] == "custom"

    def test_a_duplicate_zone_counts_as_existing(self, api):
        api.post_queue = [Resp(409, text="conflict")]
        api.get_queue = [Resp(200, []), Resp(200, [{"name": "openosint_serp"}])]
        session = Session(answers=["y", "", "y", "skip"], secrets=[TOKEN])

        assert session.run() == 0

        assert config_store.read_config()["BRIGHTDATA_SERP_ZONE"] == "openosint_serp"

    def test_a_missing_permission_falls_back_to_the_dashboard_steps(self, api, capsys):
        api.post_queue = [Resp(403, text="forbidden")]
        session = Session(answers=["y", "", "y", "skip"], secrets=[TOKEN])

        session.run()

        out = capsys.readouterr()
        assert (
            "Admin or Ops" in out.out + out.err
            and "Create a SERP API zone in your dashboard" in out.out + out.err
        )
        assert "BRIGHTDATA_SERP_ZONE" not in config_store.read_config()

    def test_a_zone_that_is_not_listed_yet_is_waited_for_then_saved_anyway(self, api):
        api.get_queue = [Resp(200, []), Resp(200, [])]  # never appears
        session = Session(answers=["y", "", "y", "skip"], secrets=[TOKEN])

        assert session.run() == 0

        assert len(session.sleeps) >= 1
        assert config_store.read_config()["BRIGHTDATA_SERP_ZONE"] == "openosint_serp"


class TestTokenValidation:
    def test_a_rejected_token_is_explained_and_asked_for_again(self, api, capsys):
        api.get_queue = [Resp(401, text="Invalid token"), Resp(200, [])]
        session = Session(answers=["y", "skip", "skip"], secrets=["FAKE-wrong", TOKEN])

        assert session.run() == 0

        out = capsys.readouterr()
        assert "rejected" in (out.out + out.err).lower() and TOKEN_URL in out.out + out.err
        assert config_store.read_config()["BRIGHTDATA_API_KEY"] == TOKEN

    def test_three_rejections_give_up_and_save_nothing(self, api):
        api.get_queue = [Resp(401, text="Invalid token")]
        session = Session(answers=["y"], secrets=["a", "b", "c"])

        assert session.run() == 1

        assert not config_store.read_config()

    def test_a_token_without_list_permission_is_saved_only_after_a_yes(self, api, capsys):
        api.get_queue = [Resp(403, text="forbidden")]
        session = Session(answers=["y", "n"], secrets=[TOKEN])

        assert session.run() == 1
        assert not config_store.read_config()

        api.get_queue = [Resp(403, text="forbidden")]
        session = Session(answers=["y", "y"], secrets=[TOKEN])
        assert session.run() == 0
        assert config_store.read_config() == {"BRIGHTDATA_API_KEY": TOKEN}
        out = capsys.readouterr()
        assert "permission" in (out.out + out.err).lower() and "HTTP 403" in (out.out + out.err)

    def test_a_bright_data_outage_is_reported_as_theirs_and_stops(self, api, capsys):
        api.get_queue = [Resp(502, text="Bad Gateway")]
        session = Session(answers=["y"], secrets=[TOKEN])

        assert session.run() == 1

        out = capsys.readouterr()
        assert "Bright Data-side" in out.out + out.err and not config_store.read_config()
        assert len(session.secret_prompts) == 1  # not blamed on the token, not asked again

    def test_a_network_error_stops_cleanly(self, api, capsys):
        import requests

        api.get_queue = [requests.ConnectionError("down")]
        session = Session(answers=["y"], secrets=[TOKEN])

        assert session.run() == 1

        assert "reach Bright Data" in (capsys.readouterr().err) and not config_store.read_config()

    def test_an_unreadable_zone_list_is_not_an_error(self, api):
        api.get_queue = [Resp(200, {"unexpected": "shape"})]
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        assert session.run() == 0
        assert config_store.read_config() == {"BRIGHTDATA_API_KEY": TOKEN}


class TestNeverOverwritesWithoutAsking:
    def test_a_saved_but_rejected_token_is_replaced_only_after_a_yes(self, api, monkeypatch):
        config_store.write_config({"BRIGHTDATA_API_KEY": "FAKE-old"})
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "FAKE-old")
        api.get_queue = [Resp(401, text="Invalid token"), Resp(200, [])]
        session = Session(answers=["n", "skip", "skip"], secrets=[TOKEN])
        assert session.run() == 1
        assert config_store.read_config()["BRIGHTDATA_API_KEY"] == "FAKE-old"

        monkeypatch.setenv("BRIGHTDATA_API_KEY", "FAKE-old")
        api.get_queue = [Resp(401, text="Invalid token"), Resp(200, [])]
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])
        assert session.run() == 0
        assert config_store.read_config()["BRIGHTDATA_API_KEY"] == TOKEN

    def test_a_saved_zone_missing_from_the_account_is_replaced_only_after_a_yes(
        self, api, monkeypatch
    ):
        config_store.write_config({"BRIGHTDATA_API_KEY": TOKEN, "BRIGHTDATA_SERP_ZONE": "old_zone"})
        monkeypatch.setenv("BRIGHTDATA_API_KEY", TOKEN)
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "old_zone")
        api.get_queue = [Resp(200, [{"name": "fresh"}])]
        session = Session(answers=["fresh", "n", "skip"])

        session.run()

        assert config_store.read_config()["BRIGHTDATA_SERP_ZONE"] == "old_zone"

    def test_an_environment_variable_that_overrides_the_saved_value_is_called_out(
        self, api, monkeypatch, capsys
    ):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "FAKE-from-env")
        api.get_queue = [Resp(401, text="Invalid token"), Resp(200, [])]
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        out = capsys.readouterr()
        assert "environment variable" in (out.out + out.err) and "takes priority" in (
            out.out + out.err
        )


class TestCostSafety:
    def test_only_the_zone_endpoints_are_ever_called_never_the_billable_request_endpoint(self, api):
        api.get_queue = _both_zones_listed()
        session = Session(answers=["n", "y", "", "y", "", "y"], secrets=[TOKEN])

        session.run()

        assert set(api.urls) <= {LIST_URL, ZONE_URL}
        assert not any(url.endswith("/request") for url in api.urls)


class TestWiring:
    def test_subprocess_refuses_without_a_terminal(self, tmp_path):
        import subprocess
        import sys

        fake_env = tmp_path / "empty.env"
        fake_env.write_text("")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "OPENOSINT_HOME": str(tmp_path / "home"),
            "OPENOSINT_ENV_FILE": str(fake_env),
        }

        result = subprocess.run(
            [sys.executable, "-m", "openosint.cli", "setup", "brightdata"],
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )

        assert result.returncode == 2 and "interactive terminal" in result.stderr
        assert not (tmp_path / "home" / "config.env").exists()

    def test_setup_without_an_action_is_a_usage_error(self, tmp_path):
        import subprocess
        import sys

        fake_env = tmp_path / "empty.env"
        fake_env.write_text("")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "OPENOSINT_HOME": str(tmp_path / "home"),
            "OPENOSINT_ENV_FILE": str(fake_env),
        }

        result = subprocess.run(
            [sys.executable, "-m", "openosint.cli", "setup"],
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )

        assert result.returncode == 2 and "required" in result.stderr

    def test_the_missing_key_message_points_at_the_command(self):
        from openosint.settings_catalog import missing_keys_message

        message = missing_keys_message(
            "search_footprint", ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"]
        )

        assert "openosint setup brightdata" in message
        assert "openosint setup brightdata" not in missing_keys_message(
            "search_shodan", ["SHODAN_API_KEY"]
        )


SERP_TYPED = {"name": "serp_api1", "type": "serp"}
UNLOCKER_TYPED = {"name": "web_unlocker1", "type": "unblocker", "plan": {"type": "unblocker"}}


class TestExistingZonesFirst:
    SAVED = {
        "BRIGHTDATA_API_KEY": TOKEN,
        "BRIGHTDATA_SERP_ZONE": "serp_api1",
        "BRIGHTDATA_UNLOCKER_ZONE": "web_unlocker1",
    }

    def test_a_type_field_preselects_a_matching_zone_as_the_enter_default(self, api):
        api.get_queue = [Resp(200, [SERP_TYPED, UNLOCKER_TYPED])]
        session = Session(answers=["y", "", ""], secrets=[TOKEN])

        assert session.run() == 0

        assert api.posts == [] and config_store.read_config() == self.SAVED
        assert any("press Enter to use 'serp_api1'" in p for p in session.prompts)
        assert any("press Enter to use 'web_unlocker1'" in p for p in session.prompts)
        assert not any("Create " in p for p in session.prompts)

    def test_a_plan_field_works_too(self, api):
        api.get_queue = [
            Resp(
                200,
                [
                    {"name": "serp_api1", "plan": {"type": "unblocker", "serp": True}},
                    {"name": "web_unlocker1", "plan": {"type": "unblocker"}},
                ],
            )
        ]
        session = Session(answers=["y", "", ""], secrets=[TOKEN])

        session.run()

        assert config_store.read_config() == self.SAVED and api.posts == []

    def test_only_a_zone_of_the_matching_type_is_suggested(self, api):
        api.get_queue = [Resp(200, [UNLOCKER_TYPED, {"name": "b_serp", "type": "serp"}])]
        session = Session(answers=["y", "", ""], secrets=[TOKEN])

        session.run()

        assert config_store.read_config()["BRIGHTDATA_SERP_ZONE"] == "b_serp"
        assert config_store.read_config()["BRIGHTDATA_UNLOCKER_ZONE"] == "web_unlocker1"

    def test_a_bare_unblocker_type_is_not_guessed_because_a_serp_zone_can_look_like_that(self, api):
        api.get_queue = [Resp(200, [{"name": "mystery", "type": "unblocker"}])]
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert not any("press Enter to use" in p for p in session.prompts)

    def test_without_a_type_the_names_are_listed_and_you_are_asked_to_type_one(self, api):
        api.get_queue = [Resp(200, [{"name": "serp_api1"}, {"name": "web_unlocker1"}])]
        session = Session(answers=["y", "skip", "skip"], secrets=[TOKEN])

        session.run()

        assert not any("press Enter to use" in p for p in session.prompts)
        first = session.prompts[1]
        assert "type one of these names" in first and "press Enter to create 'openosint_serp'" in first

    def test_several_matches_default_to_the_first_and_mention_the_others(self, api):
        api.get_queue = [Resp(200, [{"name": "serp_a", "type": "serp"}, {"name": "serp_b", "type": "serp"}])]
        session = Session(answers=["y", "", "skip"], secrets=[TOKEN])

        session.run()

        assert "press Enter to use 'serp_a'" in session.prompts[1] and "serp_b" in session.prompts[1]
        assert config_store.read_config()["BRIGHTDATA_SERP_ZONE"] == "serp_a"

    def test_the_zone_list_is_printed_once(self, api, capsys):
        api.get_queue = [Resp(200, [SERP_TYPED])]
        session = Session(answers=["y", "", "skip"], secrets=[TOKEN])

        session.run()

        assert capsys.readouterr().out.count("Zones in your account") == 1


class TestCreationForbidden:
    def _run_two_zones(self, api, answers):
        api.post_queue = [Resp(403, text="forbidden")]
        session = Session(answers=answers, secrets=[TOKEN])
        return session, session.run()

    def test_after_a_403_the_second_zone_is_not_offered_creation(self, api, capsys):
        session, code = self._run_two_zones(api, ["y", "", "y", ""])

        assert code == 0 and len(api.posts) == 1
        assert not any("Create Web Unlocker zone" in p for p in session.prompts)
        assert not any("press Enter to create 'openosint_unlocker'" in p for p in session.prompts)
        assert "Create a Web Unlocker zone in your dashboard" in capsys.readouterr().out

    def test_the_403_is_explained_as_the_tokens_permission_level_with_two_options_once(self, api, capsys):
        self._run_two_zones(api, ["y", "", "y", ""])

        text = (lambda c: c.out + c.err)(capsys.readouterr())
        assert text.count("permission level") == 1
        assert "(a)" in text and "(b)" in text and "Admin or Ops" in text and "Zone Management" in text
        assert TOKEN_URL in text and "Nothing is wrong with your setup" in text

    def test_a_typed_existing_zone_is_still_accepted_after_a_403(self, api):
        api.post_queue = [Resp(403, text="forbidden")]
        api.get_queue = [Resp(200, [{"name": "mine"}])]
        session = Session(answers=["y", "", "y", "mine"], secrets=[TOKEN])

        session.run()

        assert len(api.posts) == 1
        assert config_store.read_config()["BRIGHTDATA_UNLOCKER_ZONE"] == "mine"

    def test_a_typed_name_that_does_not_exist_is_not_created_after_a_403(self, api):
        api.post_queue = [Resp(403, text="forbidden")]
        api.get_queue = [Resp(200, [{"name": "mine"}])]
        session = Session(answers=["y", "", "y", "nope"], secrets=[TOKEN])

        session.run()

        assert len(api.posts) == 1
        assert "BRIGHTDATA_UNLOCKER_ZONE" not in config_store.read_config()

    def test_a_listing_403_uses_the_same_non_blaming_wording(self, api, capsys):
        api.get_queue = [Resp(403, text="forbidden")]
        session = Session(answers=["y", "y"], secrets=[TOKEN])

        session.run()

        text = (lambda c: c.out + c.err)(capsys.readouterr())
        assert "permission level" in text and "(a)" in text and "(b)" in text
