"""Oct 18 e2e fixes: report proof for 1x1x1 studies, study_owner on saved studies, start_study schema."""

import asyncio
import json
import unittest

from mvp.sim_mcp import report as R
from mvp.sim_mcp import server as srv
from mvp.sim_mcp import sessions as S


def _saved_study(owner: str = "anon:abc") -> dict:
    proof = {"pass": True, "checks": [{"name": "real_action", "pass": True, "detail": "clicked"}]}
    row = {"agent_id": "t1__p1__product", "persona_bio": "b", "task_prompt": "t", "trace": [], "mcp_owner": owner,
           "mcp_proof": proof, "page_verdict": {"goal_reached": True, "reason": "ok"}}
    return {"id": "s1", "backend": "mcp", "status": "complete", "url": "https://x.test",
            "agent_results": [dict(row)], "live_sessions": [dict(row)], "summary": {"mcp_proof": {"runs": 1, "passed": 1}}}


class Oct18Tests(unittest.TestCase):
    def test_one_cell_study_report_shows_proof_pass(self):
        rep = R.build_report(_saved_study())
        self.assertTrue(rep["proof"]["pass"])
        self.assertIn("- Proof: PASS", R.report_markdown(rep))

    def test_owner_of_study_loaded_from_disk(self):
        d = _saved_study("anon:abc")
        self.assertEqual(S.study_owner(d), "anon:abc")
        self.assertTrue(S.owns_study(d, "anon:abc"))
        # Same caller from another IP of its NAT/relay pool: still its study.
        self.assertTrue(S.owns_study(d, "anon:other"))
        self.assertFalse(S.owns_study(d, "tokfingerprint"))
        d["live_sessions"] = {"a": {"mcp_owner": "tok"}}
        self.assertEqual(S.study_owner(d), "tok")
        self.assertFalse(S.owns_study(d, "anon:abc"))
        self.assertFalse(S.owns_study(d, "tok2"))

    def test_session_survives_client_ip_change_without_token(self):
        from types import SimpleNamespace
        sim = SimpleNamespace(id="sid1", owner="anon:ip1")
        S.SESSIONS["sid1"] = sim
        try:
            self.assertIs(S.get_session("sid1", "anon:ip2"), sim)
            with self.assertRaises(S.SessionError):
                S.get_session("sid1", "tokenfp")
            sim.owner = "tokenfp"
            with self.assertRaises(S.SessionError):
                S.get_session("sid1", "anon:ip1")
            with self.assertRaises(S.SessionError):
                S.get_session("sid1", "othertoken")
            self.assertIs(S.get_session("sid1", "tokenfp"), sim)
        finally:
            S.SESSIONS.pop("sid1", None)

    def test_start_study_schema_names_required_fields(self):
        tools = asyncio.run(srv.mcp.list_tools())
        sch = next(t for t in tools if t.name == "usersim_start_study").inputSchema
        defs = sch.get("$defs") or {}
        self.assertEqual(defs["StudyPersona"]["required"], ["bio"])
        self.assertEqual(defs["StudyTask"]["required"], ["prompt"])
        self.assertIn("description", sch["properties"]["personas"])
        self.assertEqual(set(sch["required"]), {"product_url", "personas", "tasks"})
        self.assertIn("Example", json.dumps(sch))


if __name__ == "__main__":
    unittest.main()


class Oct18FixesTests(unittest.TestCase):
    def test_redact_url_hides_tokens_keeps_host_path(self):
        u = ("https://app.clockify.me/memberships?cakeExchangeToken=eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJjbG9ja2lmeSJ9.sig"
             "&email=us.ersim.signups%2Bx@gmail.com&tab=1")
        r = S.redact_url(u)
        self.assertTrue(r.startswith("https://app.clockify.me/memberships?"))
        self.assertNotIn("eyJ", r)
        self.assertIn("tab=1", r)
        self.assertIn("email=us.ersim.signups%2Bx@gmail.com", r)
        self.assertEqual(S.redact_url("https://x.test/a/b"), "https://x.test/a/b")
        self.assertNotIn("abc123", S.redact_url("https://x.test/cb?code=abc123"))
        self.assertNotIn("zzz", S.redact_url("https://x.test/#access_token=zzz&type=bearer"))

    def test_font_links_are_not_verification_links(self):
        from mvp.signup_inbox import _skip_link
        self.assertTrue(_skip_link("https://fonts.googleapis.com/css?family=Roboto:400,500,700&display=swap"))
        self.assertTrue(_skip_link("https://x.test/static/mail.css"))
        self.assertFalse(_skip_link("https://app.clockify.me/verify?token=abc"))

    def test_same_account_as_reuses_alias_and_password(self):
        from types import SimpleNamespace
        from unittest import mock

        def sim(sid, url, inbox=None, identity=None):
            return SimpleNamespace(id=sid, owner="anon:a", product_url=url, inbox=inbox, identity=identity or {},
                                   row={}, agent_id="t1__p1__product", mail_since=0.0, closed=False)

        inbox = SimpleNamespace(address="usersim.signups+clk1@gmail.com")
        first = sim("s1" * 16, "https://clockify.me", inbox, {"email": inbox.address, "password": "pw"})
        second = sim("s2" * 16, "https://app.clockify.me/en/login")
        other = sim("s3" * 16, "https://kanbanflow.com")
        for x in (first, second, other):
            S.SESSIONS[x.id] = x
        try:
            ctx = None
            with mock.patch.object(srv, "_owner", return_value="anon:b"):
                out = json.loads(asyncio.run(srv.usersim_signup_identity(ctx, second.id, same_account_as=first.id)))
                self.assertTrue(out["reused_account"])
                self.assertEqual(out["email"], inbox.address)
                self.assertIs(second.inbox, inbox)
                self.assertEqual(second.row["login_email"], inbox.address)
                self.assertNotIn("signup_email", second.row)
                bad = json.loads(asyncio.run(srv.usersim_signup_identity(ctx, other.id, same_account_as=first.id)))
                self.assertIn("not kanbanflow.com", bad["error"])
                bad = json.loads(asyncio.run(srv.usersim_signup_identity(ctx, other.id, same_account_as="nope")))
                self.assertIn("unknown session_id", bad["error"])
            with mock.patch.object(srv, "_owner", return_value="tokenfp"):
                bad = json.loads(asyncio.run(srv.usersim_signup_identity(ctx, second.id, same_account_as=first.id)))
                self.assertIn("unknown session_id", bad["error"])
        finally:
            for x in (first, second, other):
                S.SESSIONS.pop(x.id, None)
