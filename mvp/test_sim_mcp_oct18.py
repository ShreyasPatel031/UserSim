"""Oct 18 e2e fixes: report proof for 1x1x1 studies, study_owner on saved studies, start_study schema."""

import asyncio
import json
import unittest

import pytest

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


def test_wait_hint_for_code_mail_says_type_the_code():
    from mvp.sim_mcp.server import wait_next_hint

    assert "type the code 490726" in wait_next_hint("490726", [])
    assert "link_number=1" not in wait_next_hint("490726", [])
    assert "code field" in wait_next_hint("RLX8X1", ["https://cake.com"])
    assert wait_next_hint(None, ["https://x.example/verify"]).startswith("to open a link")
    assert "no code and no link" in wait_next_hint(None, [])


def test_judge_evidence_lists_server_actions_and_drag_is_described():
    from mvp.sim_mcp.report import signup_evidence
    from mvp.sim_mcp.sessions import describe_action

    assert describe_action({"type": "drag", "x": 640, "y": 140, "to_x": 1144, "to_y": 180}) == "drag — (640, 140) to (1144, 180)"
    row = {"login_email": "a@b.c", "trace": [
        {"step": 0, "action_kind": "open", "action": "Opened https://kanbanflow.com", "url": "https://kanbanflow.com/"},
        {"step": 1, "action_kind": "click", "action": "click — (968, 35)", "url": "https://kanbanflow.com/login"},
        {"step": 2, "action_kind": "drag", "action": "drag — (640, 140) to (1144, 180)", "url": "https://kanbanflow.com/board/x"},
    ]}
    ev = signup_evidence(row)
    assert "final screenshot was taken after them" in ev
    assert "drag — (640, 140) to (1144, 180)" in ev and "Opened" not in ev.split("in order")[1]


def test_judge_prompt_counts_end_state_for_move_tasks(monkeypatch):
    import mvp.e2e_ui_run as ui
    from mvp import e2e2_gates

    seen = {}
    monkeypatch.setattr(ui, "gemini_vision_json", lambda prompt, png: seen.setdefault("p", prompt) and {"goal_reached": True})
    e2e2_gates.judge_goal_screenshot(b"x" * 5000, task="mark it done", start_url="https://kanbanflow.com")
    assert "Never fail it as \"already\" or \"still\" in that state" in seen["p"]


def test_same_account_as_survives_restart(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    from unittest import mock

    from mvp import signup_inbox

    monkeypatch.setattr(S, "ACCOUNTS_DIR", tmp_path / "_mcp_accounts")
    monkeypatch.setattr("mvp.email_codes._imap_creds", lambda: ("usersim.signups@gmail.com", "app-pw"))
    inbox = signup_inbox.GmailAliasInbox.for_address("usersim.signups+kanbanflow1@gmail.com")
    first = SimpleNamespace(id="k1" * 16, owner="anon:a", product_url="https://kanbanflow.com", inbox=inbox,
                            identity={"email": inbox.address, "password": "pw"}, agent_id="t1__p1__product")
    S.save_account(first)
    f = S._account_file(first.id)
    assert f.is_file() and oct(os.stat(f).st_mode & 0o777) == "0o600"
    assert first.id not in f.name and "pw" in f.read_text()
    # server restarted: the session is gone from memory
    second = SimpleNamespace(id="k2" * 16, owner="anon:z", product_url="https://kanbanflow.com/login", inbox=None,
                             identity={}, row={}, agent_id="t4__p1__product", mail_since=0.0, closed=False)
    S.SESSIONS[second.id] = second
    try:
        with mock.patch.object(srv, "_owner", return_value="anon:b"):
            out = json.loads(asyncio.run(srv.usersim_signup_identity(None, second.id, same_account_as=first.id)))
        assert out["reused_account"] and out["email"] == inbox.address and out["password"] == "pw"
        assert second.inbox.address == inbox.address and second.row["login_email"] == inbox.address
        assert second.row["reused_account_from"] == "t1__p1__product"
        assert S.load_account(first.id, "tokenfp") is None
        with pytest.raises(ValueError):
            signup_inbox.GmailAliasInbox.for_address("someone.else+x@gmail.com")
    finally:
        S.SESSIONS.pop(second.id, None)


def test_accounts_dir_prefers_dir_outside_app(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "ACCOUNTS_DIR", None)
    monkeypatch.setenv("MVP_MCP_ACCOUNTS_DIR", str(tmp_path / "keep"))
    assert S._accounts_dir() == tmp_path / "keep" and (tmp_path / "keep").is_dir()
    monkeypatch.setattr(S, "ACCOUNTS_DIR", None)
    monkeypatch.setenv("MVP_MCP_ACCOUNTS_DIR", "/proc/nope/x")
    assert S._accounts_dir() == S.MVP_RUNS_DIR / "_mcp_accounts"


def test_select_described_with_option_and_judge_knows_groups(monkeypatch):
    import mvp.e2e_ui_run as ui
    from mvp import e2e2_gates

    assert S.describe_action({"type": "select", "option": "Done", "field": "Column"}) == "select — 'Done' in 'Column'"
    seen = {}
    monkeypatch.setattr(ui, "gemini_vision_json", lambda prompt, png: seen.setdefault("p", prompt) and {"goal_reached": True})
    e2e2_gates.judge_goal_screenshot(b"x" * 5000, task="mark it done", start_url="https://kanbanflow.com")
    assert 'a date group such as "Today"' in seen["p"]


def test_final_marks_reach_the_judge_and_prompt_reads_strikethrough(monkeypatch):
    import mvp.e2e_ui_run as ui
    from mvp import e2e2_gates
    from mvp.sim_mcp.report import signup_evidence

    ev = signup_evidence({"final_marks": ['struck through: "Research"'], "trace": []})
    assert 'Visual state the server read from the final page (CSS / checkbox state): struck through: "Research"' in ev
    assert "Visual state" not in signup_evidence({"trace": []})
    seen = {}
    monkeypatch.setattr(ui, "gemini_vision_json", lambda prompt, png: seen.setdefault("p", prompt) and {"goal_reached": True})
    e2e2_gates.judge_goal_screenshot(b"x" * 5000, task="check off Research", start_url="https://dynalist.io")
    assert "struck-through or greyed-out text instead of a ticked checkbox" in seen["p"]


def test_marks_js_reads_wrapper_strike_and_done_classes():
    js = S._MARKS_JS
    assert "innerText" in js and "marked done by its class" in js and "taken.some" in js
