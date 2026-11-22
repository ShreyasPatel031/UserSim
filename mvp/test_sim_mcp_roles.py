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


def SV_call_report(tok: str) -> str:
    return asyncio.run(SV.usersim_get_report(_ctx(tok), "s9"))


if __name__ == "__main__":
    unittest.main()
