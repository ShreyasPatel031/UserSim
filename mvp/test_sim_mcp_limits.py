"""Oct 17: open /mcp with caps from mvp/sim_mcp/limits.json (callers without a token)."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from mvp.sim_mcp import limits as L
from mvp.sim_mcp import server as SV
from mvp.sim_mcp import sessions as S

BASE_ENV = {"MVP_MCP_LIMITS_URL": "off"}


def _ctx(ip: str = "203.0.113.5", auth: str = "", peer: str = "127.0.0.1"):
    headers = {"x-forwarded-for": ip}
    if auth:
        headers["authorization"] = auth
    req = SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))
    return SimpleNamespace(request_context=SimpleNamespace(request=req))


class LimitsFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {**BASE_ENV, "MVP_MCP_SPEND_FILE": os.path.join(self.tmp.name, "s.json")})
        self.env.start()
        for k in list(os.environ):
            if k.startswith("MVP_MCP_") and k.upper()[8:].lower() in L.DEFAULTS:
                os.environ.pop(k)
        L.reset_for_tests()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_bundled_file_has_every_key_with_docs(self):
        data = json.loads(L.BUNDLED.read_text())
        self.assertEqual(set(data["limits"]), set(L.DEFAULTS))
        for key, row in data["limits"].items():
            self.assertTrue(row.get("about"), key)
            self.assertEqual(row["value"], L.DEFAULTS[key], key)

    def test_defaults(self):
        self.assertEqual(L.get("anon_max_concurrent_sessions_per_ip"), 3)
        self.assertEqual(L.get("anon_daily_usd_per_ip"), 6.0)
        self.assertEqual(L.get("anon_daily_usd_global"), 20.0)
        self.assertIs(L.get("anon_allow_sms"), True)
        self.assertEqual(L.get("sms_lease_s"), 600)
        self.assertEqual(L.get("anon_daily_sms_leases_per_ip"), 10)
        self.assertIn("apple", L.get("sms_sender_denylist"))

    def test_env_override_and_bad_values_ignored(self):
        with mock.patch.dict(os.environ, {"MVP_MCP_ANON_DAILY_USD_PER_IP": "0.5", "MVP_MCP_ALLOW_ANONYMOUS": "0"}):
            self.assertEqual(L.get("anon_daily_usd_per_ip"), 0.5)
            self.assertIs(L.get("allow_anonymous"), False)
        vals = L.parse(json.dumps({"limits": {"max_sessions": {"value": -1}, "anon_allow_sms": {"value": "yes"},
                                              "anon_max_cells_per_study": {"value": 4}, "bogus": {"value": 1}}}))
        self.assertEqual(vals, {"anon_max_cells_per_study": 4})

    def test_refresh_from_main_applies_and_bad_file_keeps_last_good(self):
        good = json.dumps({"limits": {"anon_max_concurrent_sessions_per_ip": {"value": 1}}}).encode()

        class Resp:
            def __init__(self, body): self.body = body
            def read(self, n=-1): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with mock.patch.dict(os.environ, {"MVP_MCP_LIMITS_URL": "https://example.invalid/limits.json"}):
            with mock.patch("urllib.request.urlopen", return_value=Resp(good)):
                self.assertTrue(L.refresh_now())
            self.assertEqual(L.get("anon_max_concurrent_sessions_per_ip"), 1)
            with mock.patch("urllib.request.urlopen", return_value=Resp(b"not json")):
                self.assertFalse(L.refresh_now())
            self.assertEqual(L.get("anon_max_concurrent_sessions_per_ip"), 1)

    def test_client_ip_only_trusts_last_hop_from_local_proxy(self):
        self.assertEqual(L.client_ip({"x-forwarded-for": "1.1.1.1, 203.0.113.5"}, "127.0.0.1"), "203.0.113.5")
        self.assertEqual(L.client_ip({"x-forwarded-for": "1.1.1.1"}, "198.51.100.7"), "198.51.100.7")

    def test_daily_caps_per_ip_and_global(self):
        with mock.patch.dict(os.environ, {"MVP_MCP_ANON_DAILY_USD_PER_IP": "0.25", "MVP_MCP_ANON_DAILY_USD_GLOBAL": "0.40"}):
            L.charge("a", 0.2, "x")
            with self.assertRaises(L.CapExceeded) as e:
                L.charge("a", 0.1, "one step")
            self.assertEqual(e.exception.limit, "anon_daily_usd_per_ip")
            L.charge("b", 0.2, "x")
            with self.assertRaises(L.CapExceeded) as e:
                L.charge("c", 0.1, "one step")
            self.assertEqual(e.exception.limit, "anon_daily_usd_global")
        # persisted, so a restart does not reset it
        saved = json.loads(open(os.environ["MVP_MCP_SPEND_FILE"]).read())
        self.assertAlmostEqual(saved["total"], 0.4)


class ServerCapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {**BASE_ENV, "MVP_MCP_SPEND_FILE": os.path.join(self.tmp.name, "s.json")})
        self.env.start()
        L.reset_for_tests()
        SV._TOKENS[:] = ["tok-1"]
        self.saved = dict(S.SESSIONS)
        S.SESSIONS.clear()

    def tearDown(self):
        S.SESSIONS.clear()
        S.SESSIONS.update(self.saved)
        SV._TOKENS[:] = []
        self.env.stop()
        self.tmp.cleanup()

    def _sim(self, owner, client="203.0.113.5"):
        sim = SimpleNamespace(id=os.urandom(8).hex(), owner=owner, client=client, closed=False, inbox=None, sms_number=None)
        S.SESSIONS[sim.id] = sim
        return sim

    def test_owner_is_per_ip_without_token_and_per_token_with_one(self):
        a, b = SV._owner(_ctx("203.0.113.5")), SV._owner(_ctx("203.0.113.6"))
        self.assertTrue(a.startswith("anon:") and b.startswith("anon:") and a != b)
        self.assertFalse(SV._owner(_ctx(auth="Bearer tok-1")).startswith("anon:"))
        self.assertTrue(SV._owner(_ctx(auth="Bearer wrong")).startswith("anon:"))

    def test_other_ip_cannot_reach_my_session_or_inbox(self):
        sim = self._sim(SV._owner(_ctx("203.0.113.5")))
        sim.inbox = SimpleNamespace(address="usersim.signups+x1@gmail.com")
        out = json.loads(asyncio.run(SV.usersim_wait_for_verification_code(_ctx("203.0.113.6"), sim.id, 10)))
        self.assertIn("unknown session_id", out["error"])

    def test_three_concurrent_sessions_per_ip(self):
        owner = SV._owner(_ctx())
        for _ in range(3):
            self._sim(owner)
        with self.assertRaises(S.SessionError) as e:
            S._check_capacity("203.0.113.5", owner)
        self.assertIn("anon_max_concurrent_sessions_per_ip", str(e.exception))
        S._check_capacity("203.0.113.9", SV._owner(_ctx("203.0.113.9")))  # another IP is fine

    def test_start_session_refused_when_budget_used_up(self):
        with mock.patch.dict(os.environ, {"MVP_MCP_ANON_DAILY_USD_PER_IP": "0.05"}):
            out = json.loads(asyncio.run(SV.usersim_start_session(_ctx(), product_url="https://example.com",
                                                                   task="t", persona="p")))
        self.assertEqual(out["limit"], "anon_daily_usd_per_ip")
        self.assertIn("daily UserSim budget", out["error"])

    def test_act_refused_when_budget_used_up(self):
        owner = SV._owner(_ctx())
        sim = self._sim(owner)
        L.charge(owner, float(L.get("anon_daily_usd_per_ip")), "x")
        out = json.loads(asyncio.run(SV.usersim_act(_ctx(), sim.id, {"type": "wait", "ms": 10}, "hm")))
        self.assertEqual(out["limit"], "anon_daily_usd_per_ip")

    def test_token_caller_not_charged(self):
        SV._spend(SV._owner(_ctx(auth="Bearer tok-1")), "one step")
        self.assertEqual(L.spend_summary()["total_usd"], 0)

    def test_no_plus_refused_without_token(self):
        sim = self._sim(SV._owner(_ctx()))
        out = json.loads(asyncio.run(SV.usersim_signup_identity(_ctx(), sim.id, no_plus=True)))
        self.assertIn("anon_allow_shared_aliases", out["error"])

    def test_plain_shared_address_refused_without_token(self):
        sim = self._sim(SV._owner(_ctx()))
        sim.product_url = "https://chatwoot.com"
        sim.row = {}
        plain = (SimpleNamespace(address="usersim.signups@gmail.com"), {"email": "usersim.signups@gmail.com"})
        with mock.patch("mvp.signup_tools.new_signup", return_value=plain):
            out = json.loads(asyncio.run(SV.usersim_signup_identity(_ctx(), sim.id)))
        self.assertIn("anon_allow_shared_aliases", out["error"])
        self.assertIsNone(sim.inbox)

    def test_paid_captcha_off_without_token(self):
        self.assertFalse(SV._paid_allowed(SimpleNamespace(owner="anon:abc")))
        self.assertTrue(SV._paid_allowed(SimpleNamespace(owner="0123456789abcdef")))


class SmsLeaseTests(unittest.TestCase):
    """Oct 17 evening: SMS works without a token, made safe by a one-session lease + sender denylist."""

    def setUp(self):
        from mvp.sim_mcp import sms_lease

        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {**BASE_ENV, "MVP_MCP_SPEND_FILE": os.path.join(self.tmp.name, "s.json"),
                                                "MVP_MCP_ANON_ALLOW_SMS": "1"})
        self.env.start()
        L.reset_for_tests()
        sms_lease.reset_for_tests()
        self.saved = dict(S.SESSIONS)
        S.SESSIONS.clear()
        from mvp.sms_provider import Number

        self.num = Number(phone="+15550000000", backend="ntfy", raw={"topic": "t"})
        self.lp = mock.patch("mvp.sms_provider.lease_number", return_value=self.num)
        self.lp.start()

    def tearDown(self):
        self.lp.stop()
        S.SESSIONS.clear()
        S.SESSIONS.update(self.saved)
        self.env.stop()
        self.tmp.cleanup()

    def _sim(self, ip):
        sim = SimpleNamespace(id=os.urandom(8).hex(), owner=SV._owner(_ctx(ip)), client=ip, closed=False, inbox=None,
                              sms_number=None, row={}, product_url="https://acme.test", close_reason="")
        S.SESSIONS[sim.id] = sim
        return sim

    def _phone(self, sim, ip):
        return json.loads(asyncio.run(SV.usersim_signup_phone(_ctx(ip), sim.id)))

    def test_no_token_gets_number_and_second_caller_is_busy(self):
        a, b = self._sim("203.0.113.5"), self._sim("203.0.113.6")
        out = self._phone(a, "203.0.113.5")
        self.assertEqual(out["phone"], "+15550000000")
        self.assertEqual(out["lease"], "new")
        busy = self._phone(b, "203.0.113.6")
        self.assertTrue(busy["busy"])
        self.assertIn("busy", busy["error"])
        self.assertGreater(busy["retry_after_s"], 500)
        self.assertNotIn("phone", busy)
        self.assertEqual(self._phone(a, "203.0.113.5")["lease"], "renewed")  # same session keeps it

    def test_wait_only_for_lease_holder_after_lease_start_with_denylist(self):
        a, b = self._sim("203.0.113.5"), self._sim("203.0.113.6")
        self._phone(a, "203.0.113.5")
        b.sms_number = self.num  # even if b somehow had the number object
        out = json.loads(asyncio.run(SV.usersim_wait_for_sms_code(_ctx("203.0.113.6"), b.id, 10)))
        self.assertIn("no longer holds the SMS number", out["error"])
        seen = {}

        def fake_wait(number, **kw):
            seen.update(kw)
            return "482913"

        with mock.patch("mvp.sms_provider.wait_for_sms", side_effect=fake_wait):
            out = json.loads(asyncio.run(SV.usersim_wait_for_sms_code(_ctx("203.0.113.5"), a.id, 10)))
        self.assertEqual(out, {"found": True, "code": "482913"})
        self.assertEqual(seen["newer_than"], a.row["sms_since"])
        self.assertEqual(seen["slack_s"], 0.0)
        self.assertIs(seen["skip"], L.sms_denied)

    def test_lease_frees_when_session_closes_or_expires(self):
        from mvp.sim_mcp import sms_lease

        a, b = self._sim("203.0.113.5"), self._sim("203.0.113.6")
        self._phone(a, "203.0.113.5")
        a.closed = True
        self.assertEqual(self._phone(b, "203.0.113.6")["lease"], "new")
        sms_lease.reset_for_tests()
        with mock.patch.dict(os.environ, {"MVP_MCP_SMS_LEASE_S": "0"}):
            self.assertEqual(self._phone(self._sim("203.0.113.7"), "203.0.113.7")["lease"], "new")
        self.assertEqual(self._phone(b, "203.0.113.6")["lease"], "new")  # expired at once

    def test_daily_lease_cap_per_ip(self):
        from mvp.sim_mcp import sms_lease

        with mock.patch.dict(os.environ, {"MVP_MCP_ANON_DAILY_SMS_LEASES_PER_IP": "2"}):
            for _ in range(2):
                sms_lease.reset_for_tests()
                self.assertIn("phone", self._phone(self._sim("203.0.113.5"), "203.0.113.5"))
            sms_lease.reset_for_tests()
            out = self._phone(self._sim("203.0.113.5"), "203.0.113.5")
        self.assertEqual(out["limit"], "anon_daily_sms_leases_per_ip")

    def test_phone_from_env(self):
        from mvp import sms_provider as P

        with mock.patch.dict(os.environ, {"MVP_SMS_PHONE": "+15550001111"}):
            self.assertEqual(P.vault_phone(), "+15550001111")

    def test_denylist_matches_apple_and_2fa_not_ordinary_codes(self):
        self.assertTrue(L.sms_denied("", "Your Apple Account Code is: 426078. Don't share it with anyone."))
        self.assertTrue(L.sms_denied("Apple", "426078"))
        self.assertTrue(L.sms_denied("", "G-123456 is your Google verification code."))
        self.assertTrue(L.sms_denied("Chase", "Your one-time code is 123456"))
        self.assertFalse(L.sms_denied("+18885551234", "Your Acme verification code is 553311"))
        self.assertFalse(L.sms_denied("", "Welcome to Pineapple Notes: code 553311"))  # whole words only
        self.assertFalse(L.sms_denied("", "City Bikes code 553311"))

    def test_ntfy_reader_drops_denylisted_and_old_texts(self):
        import time as _t

        from mvp import sms_provider as P

        now = _t.time()
        lines = "\n".join(json.dumps(m) for m in [
            {"event": "message", "id": "1", "time": now - 30, "title": "+1888", "message": "Acme code 111111"},  # before lease
            {"event": "message", "id": "2", "time": now + 1, "title": "", "message": "Your Apple Account Code is: 426078."},
            {"event": "message", "id": "3", "time": now + 2, "title": "+1888", "message": "Your Acme code is 553311"},
        ])
        resp = SimpleNamespace(status_code=200, text=lines)
        with mock.patch.object(P.httpx, "get", return_value=resp):
            got = P.wait_for_sms(self.num, timeout_s=1, newer_than=now, poll_s=0.1, skip=L.sms_denied, slack_s=0.0)
        self.assertEqual(got, "553311")
        only_apple = SimpleNamespace(status_code=200, text=lines.split("\n")[1])
        with mock.patch.object(P.httpx, "get", return_value=only_apple):
            got = P.wait_for_sms(self.num, timeout_s=0.3, newer_than=now, poll_s=0.1, skip=L.sms_denied, slack_s=0.0)
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
