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


if __name__ == "__main__":
    unittest.main()
