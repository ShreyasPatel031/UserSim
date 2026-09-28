"""Offline tests for the self-study loop guards (agent marker, dogfood guard, kill auth, start caps)."""
import asyncio
import os
import types
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from mvp import browser_slots as bs
from mvp import self_guard as sg

TOKEN = "s3cret-admin-token"


def _study(sid, max_agents=0):
    return types.SimpleNamespace(
        id=sid, max_agents=max_agents, queue_eta_s=None, queue_position=None, queued_s=0.0, test_mode=False, tasks_override=[]
    )


def _reset_slots():
    bs._TICKETS.clear()
    bs._ACTIVE.clear()
    bs._OBJS.clear()
    bs._PENDING.clear()
    bs._STARTS.clear()
    bs._COUNT_CACHE.update({"at": 0.0, "value": None})


class _Base(unittest.TestCase):
    def setUp(self):
        _reset_slots()
        sg._DNS_CACHE.clear()
        self._dns = mock.patch.object(sg, "_resolves_to_own_ip_sync", return_value=False)
        self._dns.start()
        from mvp import server

        self.server = server
        self.client = TestClient(server.app)

    def tearDown(self):
        self._dns.stop()
        _reset_slots()

    def _landing(self):
        async def same(url):
            return url

        return mock.patch.object(self.server, "_landing_url", side_effect=same)


class AgentHeaderTests(_Base):
    def test_study_submit_from_agent_browser_is_403(self):
        with mock.patch("mvp.study.create_study") as create:
            res = self.client.post("/api/studies", json={"url": "amazon.com"}, headers={"X-UserSim-Agent": "abc"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("agent browsers", res.json()["detail"])
        create.assert_not_called()

    def test_preflight_announcing_the_agent_header_is_403(self):
        res = self.client.options(
            "/api/studies",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type,x-usersim-agent"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["reason"], "agent header (preflight)")

    def test_kill_from_agent_browser_is_403_even_with_the_admin_token(self):
        with mock.patch.dict(os.environ, {"USERSIM_ADMIN_TOKEN": TOKEN}), mock.patch(
            "mvp.kill_switch.kill_now_async"
        ) as kill:
            res = self.client.post(
                "/api/runtime/kill", json={}, headers={"X-UserSim-Agent": "abc", "Authorization": f"Bearer {TOKEN}"}
            )
        self.assertEqual(res.status_code, 403)
        kill.assert_not_called()

    def test_reads_from_agent_browsers_still_work(self):
        res = self.client.get("/api/runtime/queue", headers={"X-UserSim-Agent": "abc"})
        self.assertEqual(res.status_code, 200)

    def test_guarded_paths(self):
        self.assertTrue(sg.guarded_request("POST", "/api/studies"))
        self.assertTrue(sg.guarded_request("POST", "/api/studies/x/email"))
        self.assertTrue(sg.guarded_request("OPTIONS", "/api/runtime/kill"))
        self.assertFalse(sg.guarded_request("GET", "/api/studies"))
        self.assertFalse(sg.guarded_request("POST", "/api/internal/live-frame"))


class IpDenylistTests(_Base):
    def test_forwarded_address_in_denylist_is_refused(self):
        env = {"USERSIM_AGENT_DENY_IPS": "203.0.113.0/24, 198.51.100.7", "USERSIM_ADMIN_TOKEN": TOKEN}
        with mock.patch.dict(os.environ, env), mock.patch("mvp.kill_switch.kill_now_async") as kill:
            res = self.client.post(
                "/api/runtime/kill", json={},
                headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9", "Authorization": f"Bearer {TOKEN}"},
            )
        self.assertEqual(res.status_code, 403)
        self.assertIn("203.0.113.9", res.json()["reason"])
        kill.assert_not_called()

    def test_reason_function(self):
        with mock.patch.dict(os.environ, {"USERSIM_AGENT_DENY_IPS": "198.51.100.7,not-an-ip"}):
            self.assertEqual(sg.agent_request_reason({}, "198.51.100.7"), "denylisted address 198.51.100.7")
            self.assertEqual(sg.agent_request_reason({"x-real-ip": "198.51.100.7"}, "10.0.0.1"), "denylisted address 198.51.100.7")
            self.assertEqual(sg.agent_request_reason({}, "10.0.0.1"), "")
        self.assertEqual(sg.agent_request_reason({}, "198.51.100.7"), "")


class OwnHostTests(unittest.TestCase):
    def test_own_hosts(self):
        for url in [
            "https://35-202-98-224.sslip.io/live",
            "35-202-98-224.sslip.io",
            "http://35.202.98.224:8000/",
            "https://usersim.vercel.app/",
            "https://www.usersim.vercel.app",
            "https://usersim-git-main-team.vercel.app/",
            "https://app.35.202.98.224.nip.io/",
        ]:
            self.assertTrue(sg.is_own_host(url), url)
        for url in ["amazon.com", "https://notusersim.vercel.app", "https://1-2-3-4.sslip.io", "", "https://vercel.app"]:
            self.assertFalse(sg.is_own_host(url), url)

    def test_hosts_from_env(self):
        with mock.patch.dict(os.environ, {"USERSIM_OWN_HOSTS": "usersim.example.com, WWW.Other.io"}):
            self.assertTrue(sg.is_own_host("https://usersim.example.com/x"))
            self.assertTrue(sg.is_own_host("https://api.other.io"))
        self.assertFalse(sg.is_own_host("https://usersim.example.com/x"))

    def test_custom_domain_resolving_to_our_vm(self):
        sg._DNS_CACHE.clear()
        with mock.patch.object(sg.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("35.202.98.224", 443))]):
            self.assertEqual(asyncio.run(sg.own_urls(["https://alias.example.org"])), ["https://alias.example.org"])
        sg._DNS_CACHE.clear()

    def test_planner_never_picks_usersim_as_a_rival(self):
        from mvp.fast_plan import pick_competitors

        got = pick_competitors(["https://usersim.vercel.app/", "https://maze.co/", "https://www.userlytics.com/"], "rival.io")
        self.assertEqual(got, ["https://maze.co/", "https://www.userlytics.com/"])


class DogfoodGuardTests(_Base):
    def test_own_target_is_409_and_starts_nothing(self):
        with self._landing(), mock.patch("mvp.study.create_study") as create, mock.patch("mvp.preopen.start_preopen") as pre:
            res = self.client.post("/api/studies", json={"url": "https://35-202-98-224.sslip.io/"})
        self.assertEqual(res.status_code, 409)
        body = res.json()
        self.assertIn("own site", body["detail"])
        self.assertEqual(body["sample_report_url"], "/blandai")
        create.assert_not_called()
        pre.assert_not_called()

    def test_own_competitor_is_409(self):
        with self._landing(), mock.patch("mvp.study.create_study") as create:
            res = self.client.post("/api/studies", json={"url": "https://maze.co", "competitors": ["usersim.vercel.app"]})
        self.assertEqual(res.status_code, 409)
        create.assert_not_called()

    def test_redirect_landing_on_usersim_is_409(self):
        async def to_us(_url):
            return "https://usersim.vercel.app/"

        with mock.patch.object(self.server, "_landing_url", side_effect=to_us):
            res = self.client.post("/api/studies", json={"url": "https://short.link/abc"})
        self.assertEqual(res.status_code, 409)

    def test_admin_flag_needs_the_token(self):
        with mock.patch.dict(os.environ, {"USERSIM_ADMIN_TOKEN": TOKEN}), self._landing(), mock.patch(
            "mvp.study.create_study"
        ) as create:
            none = self.client.post("/api/studies", json={"url": "usersim.vercel.app", "admin_dogfood": True})
            wrong = self.client.post(
                "/api/studies", json={"url": "usersim.vercel.app", "admin_dogfood": True},
                headers={"Authorization": "Bearer nope"},
            )
        self.assertEqual(none.status_code, 401)
        self.assertEqual(wrong.status_code, 403)
        create.assert_not_called()

    def test_admin_flag_with_the_token_passes_the_guard(self):
        # The start cap answers next, so passing the guard is visible without starting a study.
        with mock.patch.dict(os.environ, {"USERSIM_ADMIN_TOKEN": TOKEN}), self._landing(), mock.patch.object(
            bs, "submit_retry_after", return_value=42
        ), mock.patch("mvp.study.create_study") as create:
            res = self.client.post(
                "/api/studies", json={"url": "usersim.vercel.app", "admin_dogfood": True},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        self.assertEqual(res.status_code, 429)
        create.assert_not_called()

    def test_admin_dogfood_from_an_agent_browser_is_still_403(self):
        with mock.patch.dict(os.environ, {"USERSIM_ADMIN_TOKEN": TOKEN}), self._landing():
            res = self.client.post(
                "/api/studies", json={"url": "usersim.vercel.app", "admin_dogfood": True},
                headers={"Authorization": f"Bearer {TOKEN}", "X-UserSim-Agent": "s1"},
            )
        self.assertEqual(res.status_code, 403)

    def test_other_sites_are_not_refused(self):
        self.assertIsNone(asyncio.run(sg.dogfood_refusal(["https://amazon.com", "maze.co"], False, None)))


class KillAuthTests(_Base):
    def _kill(self, headers=None, env=None):
        async def fake_kill(**kw):
            return {"ok": True, "args": kw}

        with mock.patch.dict(os.environ, env or {}, clear=False), mock.patch(
            "mvp.kill_switch.kill_now_async", side_effect=fake_kill
        ) as kill:
            if not env:
                os.environ.pop("USERSIM_ADMIN_TOKEN", None)
            res = self.client.post("/api/runtime/kill", json={"agents": True}, headers=headers or {})
        return res, kill

    def test_no_token_configured_refuses_everyone(self):
        res, kill = self._kill({"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(res.status_code, 403)
        kill.assert_not_called()

    def test_missing_bearer_is_401(self):
        res, kill = self._kill({}, {"USERSIM_ADMIN_TOKEN": TOKEN})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.headers.get("www-authenticate"), "Bearer")
        kill.assert_not_called()

    def test_wrong_token_is_403(self):
        res, kill = self._kill({"Authorization": "Bearer wrong"}, {"USERSIM_ADMIN_TOKEN": TOKEN})
        self.assertEqual(res.status_code, 403)
        kill.assert_not_called()

    def test_right_token_kills(self):
        res, kill = self._kill({"Authorization": f"Bearer {TOKEN}"}, {"USERSIM_ADMIN_TOKEN": TOKEN})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        kill.assert_called_once()

    def test_auth_is_checked_before_the_body(self):
        with mock.patch.dict(os.environ, {"USERSIM_ADMIN_TOKEN": TOKEN}):
            res = self.client.post("/api/runtime/kill", content=b"not json")
        self.assertEqual(res.status_code, 401)

    def test_compare_is_constant_time(self):
        with mock.patch.dict(os.environ, {"USERSIM_ADMIN_TOKEN": TOKEN}), mock.patch.object(
            sg.hmac, "compare_digest", wraps=sg.hmac.compare_digest
        ) as cmp:
            self.assertIsNone(sg.admin_error(f"Bearer {TOKEN}"))
        cmp.assert_called_once()

    def test_live_page_has_no_kill_button(self):
        from pathlib import Path

        static = Path(__file__).resolve().parent / "static"
        self.assertNotIn("kill-agents", (static / "live.html").read_text())
        self.assertNotIn("/api/runtime/kill", (static / "live.js").read_text())


_real_sleep = asyncio.sleep


async def _fast_sleep(_s):
    await _real_sleep(0.01)


class QueueBeforeBrowserTests(unittest.TestCase):
    def setUp(self):
        _reset_slots()

    def tearDown(self):
        _reset_slots()

    def test_queued_study_never_creates_a_session(self):
        from mvp import a11y_agent, early_start, preopen

        created = []

        def fake_create(**kw):
            created.append(kw.get("study_id"))
            return types.SimpleNamespace(id="bb1", connect_url="ws://x")

        async def go():
            with mock.patch.object(bs, "_enabled", return_value=True), mock.patch.object(
                bs, "_fetch_count", return_value={"n": 0, "median_age_s": None}
            ), mock.patch.object(bs.asyncio, "sleep", new=_fast_sleep), mock.patch(
                "capability.browserbase_client.create_session", side_effect=fake_create
            ), mock.patch.object(preopen, "_open_one") as open_one:
                running, queued = _study("run1"), _study("q1")
                bs.reserve(running)
                self.assertTrue(bs.admit_now(running))
                bs.reserve(queued)
                self.assertFalse(bs.may_open("q1"))

                preopen.start_preopen(queued, "https://maze.co")
                waiter = asyncio.ensure_future(bs.acquire(queued, lambda *a, **k: None))
                await _real_sleep(0.05)
                self.assertFalse(waiter.done())
                self.assertIn("q1", bs._TICKETS)
                self.assertFalse(bs.may_open("q1"))
                self.assertFalse(early_start.may_start(queued))
                with self.assertRaises(RuntimeError):
                    early_start.start_early_agent(queued, "https://maze.co", {"persona": {}, "task": "x"})
                with self.assertRaises(RuntimeError):
                    await a11y_agent._create_session_or_close("q1", timeout=1)
                self.assertFalse(await preopen.admitted("q1", wait_s=0.05))
                open_one.assert_not_called()
                self.assertEqual(created, [])

                bs.release(running)
                await asyncio.wait_for(waiter, 2)
                self.assertIn("q1", bs._ACTIVE)
                self.assertTrue(bs.may_open("q1"))
                await a11y_agent._create_session_or_close("q1", timeout=1)
                self.assertEqual(created, ["q1"])

        asyncio.run(go())

    def test_preopen_admits_before_it_opens_any_browser(self):
        from mvp import preopen

        seen = []

        async def fake_open(study_id, url, pool):
            seen.append(study_id in bs._ACTIVE)
            await pool["q"].put(None)

        async def go():
            with mock.patch.object(bs, "_enabled", return_value=True), mock.patch.object(
                bs, "_fetch_count", return_value={"n": 0, "median_age_s": None, "recent_ages_s": []}
            ), mock.patch.object(preopen, "_open_one", side_effect=fake_open), mock.patch.dict(
                os.environ, {"MVP_PREOPEN": "3", "MVP_A11Y_LOOP": "1"}
            ):
                s = _study("idle1")
                bs.reserve(s)
                preopen.start_preopen(s, "https://maze.co")
                self.assertTrue(await preopen.admitted("idle1", wait_s=2))
                await _real_sleep(0.05)
                await preopen.release("idle1")

        asyncio.run(go())
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(seen))

    def test_busy_project_opens_nothing_and_leaves_the_study_to_the_queue(self):
        from mvp import preopen

        async def go():
            with mock.patch.object(bs, "_enabled", return_value=True), mock.patch.object(
                bs, "_fetch_count", return_value={"n": 20, "median_age_s": 30.0, "recent_ages_s": []}
            ), mock.patch.object(preopen, "_open_one") as open_one:
                s = _study("busy1")
                bs.reserve(s)
                preopen.start_preopen(s, "https://maze.co")
                self.assertFalse(await preopen.admitted("busy1", wait_s=2))
                open_one.assert_not_called()
                self.assertFalse(bs.may_open("busy1"))

        asyncio.run(go())


class StartRateCapTests(_Base):
    def test_submit_over_the_start_cap_is_429_with_retry_after(self):
        with mock.patch.dict(os.environ, {"MVP_MAX_STUDY_STARTS": "2", "MVP_STUDY_START_WINDOW_S": "600"}):
            for sid in ("a", "b"):
                bs._admit(_study(sid))
                bs._ACTIVE.pop(sid)
            with self._landing(), mock.patch("mvp.study.create_study") as create:
                res = self.client.post("/api/studies", json={"url": "https://maze.co"})
        self.assertEqual(res.status_code, 429)
        retry = int(res.headers["retry-after"])
        self.assertGreater(retry, 590)
        self.assertLessEqual(retry, 600)
        self.assertEqual(res.json()["retry_after_s"], retry)
        create.assert_not_called()

    def test_pending_submits_count_against_the_cap(self):
        with mock.patch.dict(os.environ, {"MVP_MAX_STUDY_STARTS": "2"}):
            bs.reserve(_study("p1"))
            self.assertIsNone(bs.submit_retry_after())
            bs.reserve(_study("p2"))
            self.assertIsNotNone(bs.submit_retry_after())
            bs.release(_study("p2"))
            self.assertIsNone(bs.submit_retry_after())

    def test_cap_zero_turns_it_off(self):
        with mock.patch.dict(os.environ, {"MVP_MAX_STUDY_STARTS": "0"}):
            for i in range(20):
                bs._admit(_study(f"z{i}"))
            self.assertIsNone(bs.submit_retry_after())

    def test_queued_study_waits_for_the_window_and_the_queue_timeout_does_not_skip_it(self):
        phases = []

        async def go():
            with mock.patch.dict(os.environ, {"MVP_MAX_STUDY_STARTS": "1", "MVP_QUEUE_MAX_WAIT_S": "0"}), mock.patch.object(
                bs, "_enabled", return_value=True
            ), mock.patch.object(bs, "_fetch_count", return_value={"n": 0, "median_age_s": None}), mock.patch.object(
                bs.asyncio, "sleep", new=_fast_sleep
            ):
                bs._admit(_study("done1"))
                bs._ACTIVE.pop("done1")
                s = _study("late1")
                waiter = asyncio.ensure_future(bs.acquire(s, lambda phase, status=None: phases.append(phase)))
                await _real_sleep(0.1)
                self.assertFalse(waiter.done())
                self.assertNotIn("late1", bs._ACTIVE)
                bs._STARTS.clear()
                await asyncio.wait_for(waiter, 2)
                self.assertIn("late1", bs._ACTIVE)

        asyncio.run(go())
        self.assertTrue(any("1 studies started here in the last 10 minutes" in p for p in phases), phases)

    def test_concurrency_cap_holds_past_the_queue_timeout(self):
        async def go():
            with mock.patch.dict(os.environ, {"MVP_MAX_CONCURRENT_STUDIES": "2", "MVP_QUEUE_MAX_WAIT_S": "0"}), mock.patch.object(
                bs, "_enabled", return_value=True
            ), mock.patch.object(bs, "_fetch_count", return_value={"n": 0, "median_age_s": None}), mock.patch.object(
                bs.asyncio, "sleep", new=_fast_sleep
            ):
                bs._admit(_study("r1"))
                bs._admit(_study("r2"))
                waiter = asyncio.ensure_future(bs.acquire(_study("r3"), lambda *a, **k: None))
                await _real_sleep(0.1)
                self.assertFalse(waiter.done())
                bs._ACTIVE.pop("r1")
                await asyncio.wait_for(waiter, 2)
                self.assertIn("r3", bs._ACTIVE)

        asyncio.run(go())


class AgentActionFilterTests(unittest.TestCase):
    OWN = "https://usersim.vercel.app/"

    def test_no_typing_pressing_or_buttons_on_usersim(self):
        block = sg.agent_action_block
        self.assertTrue(block(self.OWN, {"act": "type", "name": "Product URL", "role": "textbox", "text": "amazon.com"}))
        self.assertTrue(block(self.OWN, {"act": "press", "key": "Enter"}))
        self.assertTrue(block(self.OWN, {"act": "click", "name": "Run", "role": "button"}))
        self.assertTrue(block("https://35-202-98-224.sslip.io/live", {"act": "click", "name": "Kill all agents", "role": "button"}))
        self.assertTrue(block(self.OWN, {"act": "click", "name": "Start study", "role": "link", "href": "/"}))
        self.assertEqual(block(self.OWN, {"act": "click", "name": "Live", "role": "link", "href": "/live"}), "")
        self.assertEqual(block(self.OWN, {"act": "scroll"}), "")

    def test_links_to_the_study_api_are_refused_anywhere(self):
        block = sg.agent_action_block
        self.assertTrue(block("https://maze.co", {"act": "click", "role": "link", "href": "https://usersim.vercel.app/api/runtime/kill"}))
        self.assertTrue(block(self.OWN, {"act": "click", "role": "link", "name": "x", "href": "/api/studies"}))
        self.assertEqual(block("https://maze.co", {"act": "click", "role": "button", "name": "Run test"}), "")
        self.assertEqual(block("https://maze.co", {"act": "type", "role": "textbox", "name": "URL"}), "")

    def test_model_never_sees_usersim_controls(self):
        from mvp.a11y_agent import _nodes_for_model

        nodes = [
            {"name": "Product URL", "role": "textbox"},
            {"name": "Run", "role": "button"},
            {"name": "Live", "role": "link", "href": "/live"},
        ]
        kept = [n["name"] for n in _nodes_for_model(nodes, set(), page_url=self.OWN)]
        self.assertEqual(kept, ["Live"])
        kept = [n["name"] for n in _nodes_for_model(nodes, set(), page_url="https://maze.co")]
        self.assertEqual(kept, ["Product URL", "Run", "Live"])


class MarkerTests(unittest.TestCase):
    def test_marker_scoped_to_own_hosts_and_study_calls_fail_in_browser(self):
        sent = []
        handlers = {}

        class FakeCdp:
            def on(self, name, fn):
                handlers[name] = fn

            async def send(self, method, params=None):
                sent.append((method, params or {}))

        class FakeContext:
            def __init__(self):
                self.pages = [object()]
                self.listeners = {}

            async def new_cdp_session(self, page):
                return FakeCdp()

            def on(self, name, fn):
                self.listeners[name] = fn

        async def go():
            ctx = FakeContext()
            n = await sg.install_agent_marker(ctx, "study-9")
            self.assertEqual(n, 1)
            self.assertIn("page", ctx.listeners)
            self.assertEqual(await sg.install_agent_marker(ctx, "study-9"), 0)
            enable = [p for m, p in sent if m == "Fetch.enable"][0]
            urls = [p["urlPattern"] for p in enable["patterns"]]
            self.assertIn("*://usersim.vercel.app/*", urls)
            self.assertTrue(all(any(h in u for h in sg.own_hosts()) for u in urls))
            fire = handlers["Fetch.requestPaused"]
            fire({"requestId": "1", "request": {"method": "POST", "url": "https://usersim.vercel.app/api/studies", "headers": {}}})
            fire({"requestId": "2", "request": {"method": "GET", "url": "https://usersim.vercel.app/", "headers": {"Accept": "*/*"}}})
            await _real_sleep(0.01)

        asyncio.run(go())
        by_id = {p.get("requestId"): (m, p) for m, p in sent if p.get("requestId")}
        self.assertEqual(by_id["1"][0], "Fetch.failRequest")
        method, params = by_id["2"]
        self.assertEqual(method, "Fetch.continueRequest")
        self.assertIn({"name": "X-UserSim-Agent", "value": "study-9"}, params["headers"])
        self.assertIn({"name": "Accept", "value": "*/*"}, params["headers"])

    def test_marker_can_be_turned_off(self):
        ctx = mock.MagicMock()
        with mock.patch.dict(os.environ, {"USERSIM_AGENT_MARKER": "0"}):
            self.assertEqual(asyncio.run(sg.install_agent_marker(ctx, "s")), 0)
        ctx.new_cdp_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
