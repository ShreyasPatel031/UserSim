"""Saved signed-in accounts for seed_vm (mvp/sim_mcp/site_states.py) and their wiring. No network: GCS is faked."""

from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from mvp.sim_mcp import report as R
from mvp.sim_mcp import seed_backend
from mvp.sim_mcp import sessions as S
from mvp.sim_mcp import site_states as SS

FUTURE = time.time() + 86400


def _state(domain="asana.com", expires=FUTURE):
    return {"cookies": [{"name": "ticket", "value": "x", "domain": "." + domain, "path": "/", "expires": expires},
                        {"name": "_ga", "value": "y", "domain": ".google.com", "path": "/", "expires": FUTURE}],
            "origins": []}


class FakeGcs:
    def __init__(self):
        self.store = {}

    def download(self, uri):
        return self.store.get(uri)

    def upload(self, uri, payload):
        self.store[uri] = payload


class Base(unittest.TestCase):
    def setUp(self):
        SS._CACHE.clear()
        self.gcs = FakeGcs()
        for p in (mock.patch("mvp.gcs_store.gcs_download_json", self.gcs.download),
                  mock.patch("mvp.gcs_store.gcs_upload_json", self.gcs.upload),
                  mock.patch.dict("os.environ", {"MVP_SEED_STATES_PREFIX": "gs://b/seed_states",
                                                 "MVP_MCP_SEED_SAVED_ACCOUNTS": "true",
                                                 "MVP_MCP_SEED_CDP_ENDPOINTS": "http://127.0.0.1:19220#3,http://127.0.0.1:19221"})):
            p.start()
            self.addCleanup(p.stop)


class StoreTests(Base):
    def test_only_live_cookies_of_the_site_count(self):
        self.assertEqual(len(SS.live_cookies(_state(), "asana.com")), 1)
        self.assertEqual(SS.live_cookies(_state(expires=time.time() - 5), "asana.com"), [])
        session_cookie = {"cookies": [{"name": "s", "domain": "app.asana.com", "expires": -1}]}
        self.assertEqual(len(SS.live_cookies(session_cookie, "asana.com")), 1)

    def test_save_then_load_round_trip_and_expired_reads_as_none(self):
        self.assertTrue(SS.save("asana.com", _state(), seed="seed-1", study_id="s1", address="a@x"))
        SS._CACHE.clear()
        got = SS.load("asana.com")
        self.assertEqual((got["seed"], got["study_id"]), ("seed-1", "s1"))
        self.assertFalse(SS.save("clickup.com", _state("asana.com"), seed="seed-0"))  # no clickup cookie: not saved
        self.gcs.store["gs://b/seed_states/basecamp.com.json"] = {"storage_state": _state("basecamp.com", time.time() - 1)}
        self.assertIsNone(SS.load("basecamp.com"))

    def test_gcs_error_reads_as_no_state(self):
        with mock.patch("mvp.gcs_store.gcs_download_json", side_effect=RuntimeError("403")):
            self.assertIsNone(SS.load("asana.com"))

    def test_signup_tasks_never_start_signed_in(self):
        self.assertFalse(SS.eligible("Sign up for a free account and verify your email"))
        self.assertFalse(SS.eligible("Create an account and invite a teammate"))
        self.assertTrue(SS.eligible("Build a custom sales CRM"))
        self.assertTrue(SS.eligible("Onboard a new client project"))

    def test_seed_endpoint_mapping(self):
        eps = ["http://127.0.0.1:19220#3", "http://127.0.0.1:19221"]
        self.assertEqual(SS.seed_endpoint("usersim-signup-seed-0", eps), "http://127.0.0.1:19220")
        self.assertEqual(SS.seed_endpoint("seed-1", eps), "http://127.0.0.1:19221")
        self.assertEqual(SS.seed_endpoint("seed-7", eps), "")


class RoutingTests(Base):
    def setUp(self):
        super().setUp()
        seed_backend._IN_USE.clear()
        seed_backend._HEALTH.clear()

    def test_prefer_the_saving_seed_when_free_else_any(self):
        with mock.patch.object(seed_backend, "_healthy", return_value="ws://x"):
            seed_backend._IN_USE["http://127.0.0.1:19220"] = 2  # busier, but it holds the state
            self.assertEqual(seed_backend.acquire(wait_s=0, prefer="http://127.0.0.1:19220").seed_label, "seed-0")
            # now full (cap 3): falls back to another seed instead of waiting
            self.assertEqual(seed_backend.acquire(wait_s=0, prefer="http://127.0.0.1:19220").seed_label, "seed-1")

    def test_saved_account_for(self):
        SS.save("asana.com", _state(), seed="usersim-signup-seed-0")
        sim = SimpleNamespace(task="Build a custom sales CRM", product_url="https://app.asana.com/")
        entry, prefer = S._saved_account_for(sim)
        self.assertEqual((entry["domain"], prefer), ("asana.com", "http://127.0.0.1:19220"))
        self.assertEqual(S._saved_account_for(SimpleNamespace(task="Sign up and verify", product_url="https://asana.com"))[0], None)
        with mock.patch.dict("os.environ", {"MVP_MCP_SEED_SAVED_ACCOUNTS": "false"}):
            self.assertEqual(S._saved_account_for(sim), (None, ""))


class SaveBackTests(Base):
    def _sim(self, verified=False):
        row = {"signup_email": "a@x"} if verified else {}
        return SimpleNamespace(bb=seed_backend.SeedSlot(endpoint="http://127.0.0.1:19221", ws_url="ws://x"),
                               saved_state=_state("clickup.com"), row=row, product_url="https://app.clickup.com/",
                               study=SimpleNamespace(id="st"), inbox=SimpleNamespace(address="a@x"))

    def test_signed_in_run_saves_state(self):
        sim = self._sim()
        self.assertTrue(asyncio.run(R.save_signed_in_state(sim, {"signed_in_app_page": True})))
        saved = self.gcs.store["gs://b/seed_states/clickup.com.json"]
        self.assertEqual((saved["seed"], saved["study_id"], saved["address"]), ("seed-1", "st", "a@x"))
        self.assertEqual(sim.row["saved_account_written"]["domain"], "clickup.com")

    def test_not_signed_in_saves_nothing(self):
        self.assertFalse(asyncio.run(R.save_signed_in_state(self._sim(), {"signed_in_app_page": False})))
        self.assertEqual(self.gcs.store, {})

    def test_verified_signup_saves_even_if_the_judge_missed_the_app_page(self):
        with mock.patch.object(R, "signup_verified", return_value=True):
            self.assertTrue(asyncio.run(R.save_signed_in_state(self._sim(verified=True), {})))

    def test_browserbase_never_saves(self):
        sim = self._sim()
        sim.bb = SimpleNamespace(backend="")
        self.assertFalse(asyncio.run(R.save_signed_in_state(sim, {"signed_in_app_page": True})))



class StartUrlTests(unittest.TestCase):
    """Check studies Nov 17 (02fc3bfc monday, fe089c16 asana, c5f80384 clickup): saved states loaded but cells opened
    the marketing homepage and the model signed up."""

    def test_app_url_from_state(self):
        st = {"cookies": [{"name": "t", "domain": ".asana.com", "expires": FUTURE},
                          {"name": "a", "domain": "app.asana.com", "expires": FUTURE}],
              "origins": [{"origin": "https://asana.com", "localStorage": [{"name": "x"}] * 5},
                          {"origin": "https://app.asana.com", "localStorage": []}]}
        self.assertEqual(SS.app_url_for(st, "asana.com"), "https://app.asana.com/0/home")  # table

    def test_workspace_subdomain_and_auth_hosts_skipped(self):
        st = {"cookies": [{"name": "s", "domain": "auth.monday.com", "expires": FUTURE},
                          {"name": "w", "domain": "usersimteam.monday.com", "expires": FUTURE}],
              "origins": [{"origin": "https://auth.monday.com", "localStorage": [{"name": "x"}] * 9}]}
        self.assertEqual(SS.app_url_for({"storage_state": st}, "monday.com"), "https://usersimteam.monday.com/")

    def test_marketing_only_state_has_no_app_url(self):
        st = {"cookies": [{"name": "t", "domain": ".example.io", "expires": FUTURE},
                          {"name": "w", "domain": "www.example.io", "expires": FUTURE}], "origins": []}
        self.assertEqual(SS.app_url_for(st, "example.io"), "")

    def test_source_file_names_give_the_app_host(self):
        # check_saved_states Nov 17: states whose only app hint was the exported file name came out NO_APP_URL
        entry = {"source": "seed_disk:site_states/app.example.io.json,site_states/example.io.json",
                 "storage_state": {"cookies": [{"name": "t", "domain": ".example.io", "expires": FUTURE}], "origins": []}}
        self.assertEqual(SS.app_url_for(entry, "example.io"), "https://app.example.io/")
        entry["source"] = "seed_disk:profiles/admin.example.io"
        self.assertEqual(SS.app_url_for(entry, "example.io"), "https://admin.example.io/")

    def test_marketing_telemetry_api_hosts_are_never_the_app(self):
        for sub in ("marketing", "go", "us.telemetry", "xapi", "api2", "cdn", "events", "track", "links"):
            st = {"cookies": [{"name": "t", "domain": f"{sub}.example.io", "expires": FUTURE}], "origins": []}
            self.assertEqual(SS.app_url_for(st, "example.io"), "", sub)
        st = {"cookies": [{"name": "t", "domain": "marketing.example.io", "expires": FUTURE},
                          {"name": "u", "domain": "team42.example.io", "expires": FUTURE}], "origins": []}
        self.assertEqual(SS.app_url_for(st, "example.io"), "https://team42.example.io/")

    def test_prefix_without_gcs_store(self):
        import builtins

        real = builtins.__import__

        def no_gcs(name, *a, **k):
            if name == "mvp.gcs_store":
                raise ImportError("no google-cloud-storage")
            return real(name, *a, **k)

        with mock.patch.dict("os.environ", {"MVP_SEED_STATES_PREFIX": "", "MVP_GCS_PREFIX": ""}), \
                mock.patch("builtins.__import__", no_gcs):
            self.assertEqual(SS.prefix(), "gs://usersim-bakeoff-347838016394/seed_states")

    def test_signed_out_pages(self):
        for u in ("https://app.asana.com/-/login", "https://auth.monday.com/users/sign_up_new",
                  "https://app.clickup.com/signup", "https://app.clickup.com/login?x=1",
                  "https://app.asana.com/-/login?forced_logout=true", "https://launchpad.37signals.com/signin"):
            self.assertTrue(SS.looks_signed_out(u), u)
        self.assertFalse(SS.looks_signed_out("https://app.asana.com/0/home/123"))
        self.assertTrue(SS.looks_signed_out("https://app.asana.com/0/home", password_field=True))

    def test_dead_entry_is_not_usable(self):
        self.assertTrue(SS.usable({"storage_state": _state()}, "asana.com"))
        self.assertFalse(SS.usable({"storage_state": _state(), "dead": True}, "asana.com"))


class ModelSeesSignedInTests(unittest.TestCase):
    def _sim(self, dead=False):
        study = mock.MagicMock(live_sessions={S.AGENT_ID: {"saved_account": {"domain": "asana.com", "dead": dead,
                                                                              "start_url": "https://app.asana.com/"}}})
        return S.SimSession(id="s" * 32, study=study, product_url="https://asana.com", task="t", persona="p")

    def test_prompt_and_observation_carry_the_note(self):
        from mvp.sim_mcp import server as srv

        sim = self._sim()
        with mock.patch.dict(S.SESSIONS, {sim.id: sim}):
            text = srv.usersim_simulate_user(sim.id, "p", "t")
        self.assertTrue(text.startswith("IMPORTANT: You are ALREADY SIGNED IN"))
        self.assertIn("https://app.asana.com/", text)
        obs = {"step": 1, "url": "https://app.asana.com/", "title": "Home", "steps_left": 5, "seconds_left": 9,
               "png": _png(), "text": ""}
        meta = srv._obs_content(sim, obs)
        self.assertIn("ALREADY SIGNED IN", json_text(meta))

    def test_dead_state_has_no_note(self):
        from mvp.sim_mcp import server as srv

        sim = self._sim(dead=True)
        with mock.patch.dict(S.SESSIONS, {sim.id: sim}):
            self.assertFalse(srv.usersim_simulate_user(sim.id, "p", "t").startswith("IMPORTANT"))


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1280, 800), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def json_text(content) -> str:
    out = []
    for c in content if isinstance(content, list) else [content]:
        out.append(getattr(c, "text", None) or str(c))
    return " ".join(out)


if __name__ == "__main__":
    unittest.main()
