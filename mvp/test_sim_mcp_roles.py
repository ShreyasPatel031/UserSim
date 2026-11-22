"""Token roles on /mcp: 'user' (any bare token, as before), 'reader' and 'admin'. The role comes only from the server's
token configuration, never from the request. Readers and admins can pull the website's information and every saved
study; only admins get the server overview; anonymous and plain-token callers get a clear error.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from mvp.sim_mcp import server as SV


def _ctx(token: str | None = None):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    req = SimpleNamespace(headers=headers, client=SimpleNamespace(host="203.0.113.9"))
    return SimpleNamespace(request_context=SimpleNamespace(request=req))


def _configure(raw: str):
    parsed = SV.parse_tokens(raw)
    SV._TOKENS[:] = [t for t, _r in parsed]
    SV._ROLES.clear()
    SV._ROLES.update({t: r for t, r in parsed})


def _run(coro):
    return json.loads(asyncio.run(coro))


class ParseTests(unittest.TestCase):
    def test_roles_and_bare_tokens(self):
        got = SV.parse_tokens("admin=A1 reader=R1,plain-token  user=U1")
        self.assertEqual(got, [("A1", "admin"), ("R1", "reader"), ("plain-token", "user"), ("U1", "user")])

    def test_a_bare_token_containing_equals_keeps_all_of_it(self):
        self.assertEqual(SV.parse_tokens("abc=="), [("abc==", "user")])
        self.assertEqual(SV.parse_tokens("root=abc"), [("root=abc", "user")])  # not a known role prefix

    def test_empty(self):
        self.assertEqual(SV.parse_tokens(""), [])
        self.assertEqual(SV.parse_tokens(None), [])  # type: ignore[arg-type]


class RoleTests(unittest.TestCase):
    def setUp(self):
        _configure("admin=ADMIN-T reader=READER-T USER-T")

    def test_role_comes_from_the_configured_token(self):
        self.assertEqual(SV._role(_ctx()), "anon")
        self.assertEqual(SV._role(_ctx("wrong")), "anon")
        self.assertEqual(SV._role(_ctx("USER-T")), "user")
        self.assertEqual(SV._role(_ctx("READER-T")), "reader")
        self.assertEqual(SV._role(_ctx("ADMIN-T")), "admin")
        self.assertEqual(SV._role(None), "anon")

    def test_a_role_in_the_request_is_ignored(self):
        ctx = _ctx("USER-T")
        ctx.request_context.request.headers["x-role"] = "admin"
        self.assertEqual(SV._role(ctx), "user")

    def test_needs(self):
        self.assertIsNotNone(SV._needs(_ctx(), "reader"))
        self.assertIsNotNone(SV._needs(_ctx("USER-T"), "reader"))
        self.assertIsNone(SV._needs(_ctx("READER-T"), "reader"))
        self.assertIsNone(SV._needs(_ctx("ADMIN-T"), "reader"))
        self.assertIsNotNone(SV._needs(_ctx("READER-T"), "admin"))
        self.assertIsNone(SV._needs(_ctx("ADMIN-T"), "admin"))
        self.assertIn("reader token", json.loads(SV._needs(_ctx(), "reader"))["error"])


SITE = {
    "day": "2026-11-22", "status": {"final": False}, "board": {"as_of": "x"}, "days": ["2026-11-22"],
    "launches": [{"id": "1", "name": "Alpha", "tagline": "t", "slug": "alpha", "topics": ["AI"], "thumb": "http://x",
                  "actual_rank": None, "current_rank": 2, "votes": 5, "board_rank": 2, "board_votes": 5,
                  "maker_name": "SHOULD-NOT-APPEAR"}],
    "points": [{"key": "0005", "label": "pre-launch", "time_pt": "00:20 PT", "ranks": {"1": 1}, "exp_votes": {"1": 9},
                "made_at": "t", "method": "arm3", "sees": "line-up", "internal_note": "SHOULD-NOT-APPEAR"}],
    "accuracy": {"mid": []}, "freshness": {}, "why": {},
}


class ToolGateTests(unittest.TestCase):
    def setUp(self):
        _configure("admin=ADMIN-T reader=READER-T USER-T")

    def test_ph_page_denied_below_reader_and_trimmed_for_reader(self):
        for tok in (None, "USER-T"):
            self.assertIn("error", _run(SV.usersim_ph_page(_ctx(tok))))
        with mock.patch.object(SV, "_fetch_site_json", return_value=SITE) as f:
            out = _run(SV.usersim_ph_page(_ctx("READER-T"), day="2026-11-21"))
        self.assertIn("day=2026-11-21", f.call_args[0][0])
        self.assertEqual(out["launches"][0]["name"], "Alpha")
        self.assertNotIn("thumb", out["launches"][0])
        self.assertNotIn("SHOULD-NOT-APPEAR", json.dumps(out))
        self.assertEqual(out["forecast_points"][0]["ranks"], {"1": 1})

    def test_ph_page_rejects_a_bad_day(self):
        with mock.patch.object(SV, "_fetch_site_json") as f:
            out = _run(SV.usersim_ph_page(_ctx("ADMIN-T"), day="../../etc"))
        self.assertIn("error", out)
        f.assert_not_called()

    def test_list_studies_gate(self):
        for tok in (None, "USER-T"):
            self.assertIn("error", _run(SV.usersim_list_studies(_ctx(tok))))

        async def fake(limit=40):
            return {"studies": [{"id": "s1", "url": "https://e.com", "status": "complete", "segment": "private"}]}

        with mock.patch("mvp.server.list_studies", fake):
            _configure("admin=ADMIN-T reader=READER-T USER-T")  # importing mvp.server mounts /mcp and resets tokens
            out = _run(SV.usersim_list_studies(_ctx("READER-T")))
        self.assertEqual(out["studies"][0]["id"], "s1")
        self.assertNotIn("segment", out["studies"][0])

    def test_admin_overview_is_admin_only(self):
        for tok in (None, "USER-T", "READER-T"):
            self.assertIn("error", _run(SV.usersim_admin_overview(_ctx(tok))))
        out = _run(SV.usersim_admin_overview(_ctx("ADMIN-T")))
        self.assertEqual(out["tokens_by_role"], {"admin": 1, "reader": 1, "user": 1})
        self.assertNotIn("ADMIN-T", json.dumps(out))  # never echoes a token

    def test_reader_reads_any_study_report_but_a_user_does_not(self):
        study = {"id": "s9", "backend": "mcp", "owner": "someone-else", "status": "complete", "phase": "Complete"}
        with mock.patch("mvp.study.STUDIES", {}), mock.patch("mvp.study.load_local_study", return_value=study), \
                mock.patch.object(SV, "is_matrix", return_value=False), \
                mock.patch.object(SV, "build_report", return_value={"headline": "ok"}), \
                mock.patch.object(SV, "report_markdown", return_value="REPORT"):
            self.assertIn("unknown study_id", SV_call_report("USER-T"))
            self.assertEqual(SV_call_report("READER-T"), "REPORT")


class QuickRunTests(unittest.TestCase):
    def setUp(self):
        _configure("admin=ADMIN-T reader=READER-T USER-T")

    def _site(self, calls, page_status=200):
        def fake(path, body, timeout=60.0):
            calls.append((path, body))
            if path in ("/api/try/page", "/api/try/text"):
                if page_status != 200:
                    return page_status, {"error": "boom"}
                return 200, {"analysis": {"name": "X"}, "token": "RUNTOKEN", "caps": {"per_ip_hour": 3}, "used_today": 4}
            return 200, {"step": path.rsplit("/", 1)[1]}
        return fake

    def test_gate(self):
        for tok in (None, "USER-T"):
            self.assertIn("error", _run(SV.usersim_ph_quick_run(_ctx(tok), product_url="https://e.com")))

    def test_needs_an_input(self):
        self.assertIn("product_url", _run(SV.usersim_ph_quick_run(_ctx("READER-T")))["error"])

    def test_runs_all_steps_with_the_run_token_and_hides_it(self):
        calls: list = []
        with mock.patch.object(SV, "_post_site_json", self._site(calls)):
            out = _run(SV.usersim_ph_quick_run(_ctx("READER-T"), product_url="https://e.com"))
        paths = [c[0] for c in calls]
        self.assertEqual(paths[0], "/api/try/page")
        self.assertEqual(sorted(paths[1:]), ["/api/try/asks", "/api/try/launch", "/api/try/people",
                                              "/api/try/reactions"])
        self.assertTrue(all(c[1] == {"token": "RUNTOKEN"} for c in calls[1:]))
        self.assertEqual(out["who_it_resembles"], {"step": "people"})
        self.assertEqual(out["where_it_may_land"], {"step": "launch"})
        self.assertNotIn("RUNTOKEN", json.dumps(out))
        self.assertIn("Simulated", out["reading_note"])
        self.assertIn("Talking points for the founder", out["card_markdown"])
        self.assertIn("can't see your team's Product Hunt network", out["card_markdown"])

    def test_text_route_when_no_url(self):
        calls: list = []
        with mock.patch.object(SV, "_post_site_json", self._site(calls)):
            _run(SV.usersim_ph_quick_run(_ctx("ADMIN-T"), name="Acme", tagline="t", description="d"))
        self.assertEqual(calls[0][0], "/api/try/text")
        self.assertEqual(calls[0][1]["name"], "Acme")

    def test_caps_message(self):
        with mock.patch.object(SV, "_post_site_json", self._site([], page_status=429)):
            out = _run(SV.usersim_ph_quick_run(_ctx("READER-T"), product_url="https://e.com"))
        self.assertIn("caps are used up", out["error"])


LAUNCH = {"id": "1", "name": "Webless Agents", "tagline": "Agents you want to put in front of customers",
          "slug": "webless-agents"}
EXPLAIN = {
    "audience": {"follow_ties": {"value": 21686.0, "rank": 1, "of": 7},
                 "power_users": {"share": 0.112, "usual": 0.035, "day_median": 0.173}},
    "who": {"network": {"follow_ties": 21686},
            "team_past_backers": {"n_held_people": 495, "segments_by_lift": [
                {"segment": "Developer-Marketers", "lift": 3.0, "n": 120}]}},
    "say": {"persona_panel": {"items": [{"interest": "high", "concern": "How does it handle content updates?"}]},
            "top_concerns": ["How does it handle content updates?"],
            "top_questions": ["How quickly do agents update when the source content changes?"]},
    "competitors": {"items": [
        {"name": "Agent Builder by Thesys", "final_daily_rank": 2, "final_votes": 421},
        {"name": "Superflow AI", "final_daily_rank": 3, "commenters_complained": ["The install was unclear."]}]},
    "why": {"all_inputs": [{"input": "team size", "points": 0.2476}, {"input": "pre-launch promotion", "points": -0.0279}]},
    "raw": {"team size": 3},
}


class LaunchCardTests(unittest.TestCase):
    def setUp(self):
        _configure("admin=ADMIN-T reader=READER-T USER-T")

    def test_card_matches_the_page(self):
        card = SV.launch_card(LAUNCH, EXPLAIN)
        md = card["card_markdown"]
        self.assertIn("Top worry: How does it handle content updates?", md)
        self.assertIn("Biggest boost: team size (+28% votes)", md)
        self.assertIn("Closest past launch: Agent Builder by Thesys, finished #2", md)
        self.assertIn("Heavy upvoters in its audience: 11% (typical launch today: 17%)", md)
        tp = card["talking_points"]
        self.assertIn("21,686 people we hold follow the hunter or makers (#1 of the 7", tp[0])
        self.assertIn("Developer-Marketers (3.0×", tp[1])
        self.assertTrue(any("Answer this worry in the first comment" in x for x in tp))
        self.assertTrue(any("Put this answer on the page" in x for x in tp))
        self.assertTrue(any("Superflow AI" in x and "install was unclear" in x for x in tp))
        self.assertIn("producthunt.com/posts/webless-agents", md)

    def test_no_network_says_so(self):
        d = {**EXPLAIN, "audience": {}}
        self.assertIn("can't see your team's Product Hunt network", SV.launch_card(LAUNCH, d)["talking_points"][0])

    def test_find_launch(self):
        ls = [{"id": "1", "name": "Webless Agents", "slug": "webless-agents"}, {"id": "2", "name": "Yoroll", "slug": "yoroll-2"}]
        self.assertEqual(SV.find_launch(ls, "", "webless agents")["id"], "1")
        self.assertEqual(SV.find_launch(ls, "https://www.yoroll.com/pricing", "")["id"], "2")
        self.assertIsNone(SV.find_launch(ls, "https://nope.io", "Nope"))

    def test_tool_gate_and_flow(self):
        for tok in (None, "USER-T"):
            self.assertIn("error", _run(SV.usersim_launch_card(_ctx(tok), name="Webless Agents")))

        def fake(url):
            if "/api/ph/today" in url:
                return {"launches": [LAUNCH]}
            return {"launches": {"1": EXPLAIN}, "labels": {"who": "how reliable"}}

        with mock.patch.object(SV, "_fetch_site_json", side_effect=fake):
            out = _run(SV.usersim_launch_card(_ctx("READER-T"), name="Webless Agents", day="2026-11-22"))
            self.assertEqual(out["launch"]["name"], "Webless Agents")
            self.assertEqual(out["how_reliable"], {"who": "how reliable"})
            miss = _run(SV.usersim_launch_card(_ctx("READER-T"), name="Unknown", day="2026-11-22"))
        self.assertIn("usersim_ph_quick_run", miss["error"])


class HotReloadTests(unittest.TestCase):
    def test_tokens_follow_the_environment_without_a_restart(self):
        import os

        _configure("")  # nothing at startup
        with mock.patch.dict(os.environ, {"MVP_MCP_TOKEN": "admin=NEW-A reader=NEW-R"}, clear=False):
            self.assertEqual(SV._role(_ctx("NEW-A")), "admin")
            self.assertEqual(SV._role(_ctx("NEW-R")), "reader")
            self.assertEqual(SV._role(_ctx("OTHER")), "anon")
        with mock.patch.dict(os.environ, {"MVP_MCP_TOKEN": "reader=NEW-R"}, clear=False):  # NEW-A removed
            self.assertEqual(SV._role(_ctx("NEW-A")), "anon")
            self.assertEqual(SV._role(_ctx("NEW-R")), "reader")

    def test_startup_tokens_are_used_when_nothing_is_configured_now(self):
        import os

        _configure("admin=START-A")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MVP_MCP_TOKEN", None)
            os.environ.pop("MVP_MCP_TOKEN_FILE", None)
            self.assertEqual(SV._role(_ctx("START-A")), "admin")


def SV_call_report(tok: str) -> str:
    return asyncio.run(SV.usersim_get_report(_ctx(tok), "s9"))


if __name__ == "__main__":
    unittest.main()


def test_token_in_query_becomes_header():
    from mvp.sim_mcp.server import _token_from_query

    scope = {"type": "http", "query_string": b"token=abc123&x=1", "headers": [(b"host", b"h")]}
    _token_from_query(scope)
    assert (b"authorization", b"Bearer abc123") in scope["headers"]
    assert b"token" not in scope["query_string"] and scope["query_string"] == b"x=1"
    # a header, when sent, wins; the query token is still stripped from the logs
    scope2 = {"type": "http", "query_string": b"token=zzz", "headers": [(b"authorization", b"Bearer real")]}
    _token_from_query(scope2)
    assert scope2["headers"] == [(b"authorization", b"Bearer real")] and scope2["query_string"] == b""
    scope3 = {"type": "http", "query_string": b"a=b", "headers": []}
    _token_from_query(scope3)
    assert scope3["headers"] == [] and scope3["query_string"] == b"a=b"
