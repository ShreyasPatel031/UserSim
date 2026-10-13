"""PR #65 review fixes: extra goals, same-subject mail, code typed vs received, ownership, password scrub, DNS."""
from __future__ import annotations

import asyncio
import json
import socket
from types import SimpleNamespace
from unittest import mock

import pytest

from mvp.sim_mcp import report as R
from mvp.sim_mcp import sessions as S


# ---- 1. tasks with goals beyond signup keep their own wording
@pytest.mark.parametrize("task", [
    "Sign up for an account",
    "Sign up and reach the dashboard",
    "Create a free account, verify your email and get to the app",
    "Sign up, confirm your email, then land on the workspace",
])
def test_signup_only_tasks(task):
    assert R.signup_only_goal({"task_prompt": task})


@pytest.mark.parametrize("task", [
    "Sign up and publish a contact form",
    "Create an account and invite a teammate",
    "Sign up, then upload a CSV",
    "Sign up and set up a project",
    "",
])
def test_tasks_with_more_than_signup(task):
    assert not R.signup_only_goal({"task_prompt": task})


def test_signed_in_override_skips_extra_goals(monkeypatch):
    monkeypatch.setattr(R, "signup_verified", lambda row: True)
    monkeypatch.setattr(R, "frame_unrendered", lambda png: False)
    raw = {"signed_in_app_page": True}
    row = {"final_url": "https://app.x.com/dashboard", "task_prompt": "Sign up and publish a contact form"}
    assert R.apply_hard_rules(row, {"goal_reached": False, "reason": "x"}, raw, b"")["goal_reached"] is False
    row["task_prompt"] = "Sign up and reach the dashboard"
    assert R.apply_hard_rules(row, {"goal_reached": False, "reason": "x"}, raw, b"")["goal_reached"] is True


# ---- 2. a later same-subject welcome mail does not retire the verification mail
def _pick(msgs, with_seen=False):
    from mvp import signup_inbox as I

    class Box(I.Inbox):
        backend = "test"

        def __init__(self):
            pass

        def messages(self, newer_than):
            return list(msgs)

    seen: set = set()
    res = Box().wait(host="acme.com", newer_than=0, timeout_s=1, seen=seen)
    return (res, seen) if with_seen else res


def test_same_subject_welcome_keeps_verification():
    msgs = [
        {"id": "a", "subject": "Welcome to Acme", "ts": 1, "text": "Your code is 482913", "from": "no-reply@acme.com"},
        {"id": "b", "subject": "Welcome to Acme", "ts": 2, "text": "Thanks for joining Acme!", "from": "no-reply@acme.com"},
    ]
    picked, seen = _pick(msgs, with_seen=True)
    assert picked["code"] == "482913"
    assert "b" not in seen


def test_same_subject_resends_keep_newest():
    msgs = [
        {"id": "a", "subject": "Log in to Acme", "ts": 1, "text": "Your code is 384912", "from": "no-reply@acme.com"},
        {"id": "b", "subject": "Log in to Acme", "ts": 2, "text": "Your code is 571036", "from": "no-reply@acme.com"},
    ]
    picked, seen = _pick(msgs, with_seen=True)
    assert picked["code"] == "571036" and "a" in seen


# ---- 3. a received code is not a used code
def _sim(**kw):
    row = {}
    sim = SimpleNamespace(signup_codes=[], typed_chars="", identity={"password": "Pw-Secret-123"}, row=row, **kw)
    return sim


def test_code_used_only_once_typed():
    sim = _sim()
    sim.signup_codes.append("482913")
    S.note_code_typed(sim, {"type": "type", "text": "someone@x.com"})
    assert not sim.row.get("signup_code_used")
    S.note_code_typed(sim, {"type": "type", "text": "482913"})
    assert sim.row["signup_code_used"] is True


def test_code_typed_box_by_box():
    sim = _sim()
    sim.signup_codes.append("4829")
    for ch in "4829":
        S.note_code_typed(sim, {"type": "type", "text": ch})
    assert sim.row["signup_code_used"] is True


def test_received_code_alone_does_not_verify():
    row = {"signup_email": "u@x.com", "signup_mail": {"subject": "code"}, "signup_code_received": True,
           "opened_links": [], "trace": []}
    assert not R.signup_verified(row)
    row["signup_code_used"] = True
    assert R.signup_verified(row)


# ---- 4/5. sessions and studies belong to the caller's token
def test_session_owner_enforced():
    sim = SimpleNamespace(owner="aaa")
    with mock.patch.dict(S.SESSIONS, {"s1": sim}):
        assert S.get_session("s1", "aaa") is sim
        with pytest.raises(S.SessionError):
            S.get_session("s1", "bbb")


def test_study_owner_enforced():
    study = {"backend": "mcp", "live_sessions": {"c1": {"mcp_owner": "aaa"}}}
    assert S.owns_study(study, "aaa")
    assert not S.owns_study(study, "bbb")
    assert not S.owns_study({"backend": "website", "live_sessions": {}}, "aaa")


def test_owner_is_token_fingerprint():
    from mvp.sim_mcp import server as SV

    def ctx(tok):
        return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"authorization": f"Bearer {tok}"})))

    assert SV._owner(ctx("t1")) == SV._owner(ctx("t1")) != SV._owner(ctx("t2"))
    assert "t1" not in SV._owner(ctx("t1"))
    assert SV._owner(None) == ""


def test_get_report_refuses_other_callers_study():
    from mvp.sim_mcp import server as SV

    data = {"id": "st1", "backend": "mcp", "live_sessions": {"c1": {"mcp_owner": "someone-else"}}}
    with mock.patch("mvp.study.STUDIES", {}), mock.patch("mvp.study.load_local_study", lambda sid: data):
        out = json.loads(asyncio.run(SV.usersim_get_report(None, "st1", format="json")))
    assert "error" in out


def test_act_refuses_other_callers_session():
    from mvp.sim_mcp import server as SV

    sim = SimpleNamespace(owner="someone-else")
    with mock.patch.dict(S.SESSIONS, {"s1": sim}):
        out = asyncio.run(SV.usersim_act(None, "s1", {"type": "wait"}, "x"))
    assert "unknown session_id" in str(out)


# ---- 6. password never lands in thoughts / notes
def test_scrub_password():
    sim = _sim()
    assert "Pw-Secret-123" not in S.scrub(sim, "I typed Pw-Secret-123 into the box")


# ---- 7. public-looking hostnames that resolve to private addresses
def _resolve(ip):
    return lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.5", "0.0.0.0"])
def test_hostname_resolving_private_rejected(ip):
    with mock.patch("socket.getaddrinfo", _resolve(ip)):
        with pytest.raises(S.SessionError):
            S.normalize_public_url("https://internal.example.com")


def test_hostname_resolving_public_ok():
    with mock.patch("socket.getaddrinfo", _resolve("93.184.216.34")):
        assert S.normalize_public_url("https://example.com").startswith("https://example.com")


def test_navigate_to_private_resolving_host_rejected():
    with mock.patch("socket.getaddrinfo", _resolve("10.0.0.7")):
        with pytest.raises(S.SessionError):
            S.validate_action({"type": "navigate", "url": "https://app.example.com/x"}, "https://example.com")
