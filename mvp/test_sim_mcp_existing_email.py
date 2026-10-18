"""Oct 18: callers behind rotating egress IPs, and signing back in to accounts the signup inbox made earlier.

1. No-token callers are keyed by IP. A cloud agent's outbound IP changed between calls (160.79.106.16 / .136 /
   .139 / .134 within seconds), so usersim_start_session worked and every next call said "unknown session_id".
   Between anonymous callers the uuid4 session_id is now the credential; token holders stay private.
2. Asana asks for an emailed magic link when an account signs in from a new browser, and the wait tools could
   only read the alias issued in the same session. usersim_signup_identity(existing_email=...) re-opens an
   earlier signup-inbox alias for token holders.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from mvp.sim_mcp import sessions as S
from mvp.signup_tools import existing_signup

CREDS = ("usersim.signups@gmail.com", "app-password")


class _Sim:
    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.inbox = None
        self.identity = None
        self.row: dict = {}
        self.mail_since = 0.0


class AnonOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = dict(S.SESSIONS)

    def tearDown(self) -> None:
        S.SESSIONS.clear()
        S.SESSIONS.update(self.saved)

    def test_anon_caller_keeps_session_after_ip_change_when_enabled(self):
        S.SESSIONS["a1"] = _Sim("anon:ip-one")
        with mock.patch.dict("os.environ", {"MVP_MCP_ANON_SESSION_ID_IS_CREDENTIAL": "true"}):
            self.assertIs(S.get_session("a1", "anon:ip-two"), S.SESSIONS["a1"])

    def test_strict_per_ip_by_default(self):
        S.SESSIONS["a1"] = _Sim("anon:ip-one")
        with self.assertRaises(S.SessionError):
            S.get_session("a1", "anon:ip-two")

    def test_token_sessions_stay_private(self):
        S.SESSIONS["t1"] = _Sim("tokenfp")
        with self.assertRaises(S.SessionError):
            S.get_session("t1", "anon:ip-two")
        with self.assertRaises(S.SessionError):
            S.get_session("t1", "othertokenfp")
        S.SESSIONS["a2"] = _Sim("anon:ip-one")
        with self.assertRaises(S.SessionError):
            S.get_session("a2", "tokenfp")

    def test_unknown_id_still_unknown(self):
        with self.assertRaises(S.SessionError):
            S.get_session("nope", "anon:ip-one")

    def test_reports_readable_but_studies_not_writable_across_anon_ips(self):
        study = {"backend": "mcp", "live_sessions": {"c1": {"mcp_owner": "anon:ip-one"}}}
        self.assertTrue(S.owns_study(study, "anon:ip-two", anon_read=True))
        self.assertFalse(S.owns_study(study, "anon:ip-two"))
        self.assertFalse(S.owns_study(study, "tokenfp", anon_read=True))


class ExistingEmailTests(unittest.TestCase):
    def _signup(self, addr: str):
        with mock.patch("mvp.email_codes._imap_creds", return_value=CREDS):
            return existing_signup(addr)

    def test_accepts_signup_inbox_aliases(self):
        for addr in ("usersim.signups+asana5b8a91@gmail.com", "usersim.s.ign.ups+asana5b8a91@gmail.com"):
            inbox, ident = self._signup(addr)
            self.assertEqual(inbox.address, addr)
            self.assertEqual(ident, {"email": addr})
            self.assertEqual((inbox.username, inbox.app_password), CREDS)

    def test_rejects_other_mailboxes(self):
        for addr in ("someone+asana@gmail.com", "usersim.signups+x@company.com", "usersim.signups@evil.com"):
            with self.assertRaises(RuntimeError):
                self._signup(addr)

    def test_tool_refuses_anonymous_callers(self):
        from mvp.sim_mcp import server as SV

        sim = _Sim("anon:ip-one")
        with mock.patch.object(SV, "_owner", return_value="anon:ip-one"), \
                mock.patch.object(SV.S, "get_session", return_value=sim):
            out = json.loads(asyncio.run(SV.usersim_signup_identity(
                None, "a1", existing_email="usersim.signups+asana5b8a91@gmail.com")))
        self.assertIn("error", out)
        self.assertIsNone(sim.inbox)

    def test_tool_reopens_alias_for_token_holders(self):
        from mvp.sim_mcp import server as SV

        sim = _Sim("tokenfp")
        with mock.patch.object(SV, "_owner", return_value="tokenfp"), \
                mock.patch.object(SV.S, "get_session", return_value=sim), \
                mock.patch("mvp.email_codes._imap_creds", return_value=CREDS):
            out = json.loads(asyncio.run(SV.usersim_signup_identity(
                None, "t1", existing_email="usersim.signups+asana5b8a91@gmail.com")))
        self.assertEqual(out["email"], "usersim.signups+asana5b8a91@gmail.com")
        self.assertNotIn("password", out)
        self.assertEqual(sim.inbox.address, "usersim.signups+asana5b8a91@gmail.com")


if __name__ == "__main__":
    unittest.main()
