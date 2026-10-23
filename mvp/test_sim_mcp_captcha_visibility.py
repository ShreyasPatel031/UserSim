"""Oct 23: paid CAPTCHA attempts are logged per session; image grids no longer loop to the step cap."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest import mock

from mvp import captcha_spend as cs
from mvp.sim_mcp import limits as L
from mvp.sim_mcp import server as srv


def test_new_limits_have_defaults_and_parse():
    for key in ("paid_captcha_max_tries", "paid_captcha_max_solves", "captcha_max_calls_per_page", "captcha_stuck_steps"):
        assert key in L.DEFAULTS
    bundled = L.parse(L.BUNDLED.read_text())
    assert bundled["paid_captcha_max_tries"] == 6 and bundled["captcha_stuck_steps"] == 12


def test_ledger_events_since(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTCHA_SPEND_LEDGER", str(tmp_path / "l.jsonl"))
    n = cs.ledger_count()
    cs.record_skip(site="asana.com", captcha_type="recaptcha_v2", task_type="ReCaptchaV2TaskProxyLess", reason="solve_attempt_cap")
    ev = cs.events_since(n)
    assert ev == [{"event": "skip", "reason": "solve_attempt_cap", "task_type": "ReCaptchaV2TaskProxyLess",
                   "captcha_type": "recaptcha_v2", "site": "asana.com", "attempt": 0}]


def test_paid_attempt_is_logged_with_page_reaction(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTCHA_SPEND_LEDGER", str(tmp_path / "l.jsonl"))
    page = SimpleNamespace(url="https://asana.com/")
    sim = SimpleNamespace(page=page, row={})

    async def fake_paid(sim_, kind, info):
        cs.record_skip(site="asana.com", captcha_type="recaptcha_v2", task_type="x", reason="per_site_cap")
        return {"ok": True, "type": "recaptcha_v2", "cost_usd": 0.001}

    async def no_sleep(_):
        return None

    async def state(_):
        return {"challenge_open": True, "token_ready": True}

    async def rejected(_):
        return False

    with mock.patch.object(srv, "_paid_token", fake_paid), mock.patch.object(srv.S, "captcha_state", state), \
            mock.patch.object(srv, "_captcha_rejected", rejected), mock.patch("asyncio.sleep", no_sleep):
        out = asyncio.run(srv._paid_token_logged(sim, "recaptcha", {}, "presolve"))
    entry = sim.row["captcha_paid_log"][0]
    assert entry["via"] == "presolve" and entry["result"]["ok"] is True
    assert entry["after"]["challenge_open"] is True and entry["after"]["site_accepted"] is False
    assert entry["ledger"][0]["reason"] == "per_site_cap"
    assert out["after"]["token_ready"] is True
    json.dumps(sim.row)  # stays serialisable for the study JSON


def test_image_challenge_guard_nudges_then_refuses():
    sim = SimpleNamespace(page=object(), row={}, product_url="https://asana.com", owner="x")

    async def open_(_):
        return True

    with mock.patch.object(srv.S, "recaptcha_challenge_open", open_), mock.patch.object(srv, "_paid_captcha_on", lambda: False):
        res = [asyncio.run(srv._image_challenge_guard(sim)) for _ in range(24)]
    assert res[10] is None and isinstance(res[11], dict) and "blocked" in res[11]["next"]
    assert isinstance(res[23], str) and res[23].startswith("captcha_stuck")


def _cell(sid, cell, study="st1", url="https://www.smartsheet.com", inbox=None):
    return SimpleNamespace(id=sid, study=SimpleNamespace(id=study), product_url=url, owner="o", cell_id=cell, matrix=True,
                           agent_id=cell, row={}, closed=False, inbox=inbox,
                           identity={"email": "a@gmail.com", "password": "pw"} if inbox else {}, mail_since=0.0)


def test_study_shares_one_account_per_site(monkeypatch):
    from mvp.sim_mcp import sessions as S

    srv._STUDY_ACCOUNTS.clear()
    a = _cell("sa", "t1__p1__product", inbox=SimpleNamespace(address="u.s.er@gmail.com"))
    b = _cell("sb", "t2__p2__product")
    other_site = _cell("sc", "t1__p1__competitor_1", url="https://asana.com")
    monkeypatch.setitem(S.SESSIONS, "sa", a)
    monkeypatch.setitem(S.SESSIONS, "sb", b)
    srv._register_study_account(a)
    assert srv._study_account_for(a, "o") is None  # the owner itself keeps its own identity
    assert srv._study_account_for(other_site, "o") is None  # another site: its own signup

    out = json.loads(srv._study_account_for(b, "o"))  # owner still working: pending note
    assert out["reused_account"] and "right now" in out["next"] and b.row["shared_study_account"]["verified"] is False
    assert b.inbox.address == "u.s.er@gmail.com"

    b2 = _cell("sd", "t3__p3__product")
    monkeypatch.setattr("mvp.sim_mcp.report.signup_verified", lambda row: True)
    out = json.loads(srv._study_account_for(b2, "o"))
    assert "verified account" in out["next"] and b2.row["shared_study_account"]["verified"] is True


def test_failed_owner_hands_the_account_over(monkeypatch):
    from mvp.sim_mcp import sessions as S

    srv._STUDY_ACCOUNTS.clear()
    a = _cell("sa2", "t1__p1__product", inbox=SimpleNamespace(address="u.s.er@gmail.com"))
    a.closed = True  # owner ended without a verified signup
    monkeypatch.setitem(S.SESSIONS, "sa2", a)
    monkeypatch.setattr("mvp.sim_mcp.report.signup_verified", lambda row: False)
    srv._register_study_account(a)
    b = _cell("sb2", "t2__p2__product")
    assert srv._study_account_for(b, "o") is None and ("st1", "smartsheet.com") not in srv._STUDY_ACCOUNTS
