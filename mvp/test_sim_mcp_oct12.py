"""Oct 12: a billing / payment wall never counts as signed in."""
from mvp.sim_mcp import report as R


def test_billing_wall_urls():
    for u in ["https://app.x.com/billing", "https://app.x.com/settings/billing/", "https://checkout.stripe.com/c/pay/cs_x",
              "https://app.x.com/onboarding/choose-plan?x=1", "https://app.x.com/plans", "https://billing.x.com/",
              "https://app.x.com/upgrade#top"]:
        assert R.billing_wall(u), u
    for u in ["https://app.x.com/dashboard", "https://app.x.com/projects/plan-a", "https://planner.x.com/home", "", "https://x.com/"]:
        assert not R.billing_wall(u), u


def test_billing_wall_blocks_override(monkeypatch):
    monkeypatch.setattr(R, "is_signup_goal", lambda row: True)
    monkeypatch.setattr(R, "signup_verified", lambda row: True)
    monkeypatch.setattr(R, "frame_unrendered", lambda png: False)
    row = {"final_url": "https://app.x.com/billing/plans"}
    v = R.apply_hard_rules(row, {"goal_reached": True, "reason": "ok"}, {"signed_in_app_page": True}, b"")
    assert v["goal_reached"] is False and v["signed_in_app_page"] is False and v["billing_wall"] is True
    row = {"final_url": "https://app.x.com/dashboard", "task_prompt": "Sign up and reach the dashboard"}
    v = R.apply_hard_rules(row, {"goal_reached": False, "reason": "x"}, {"signed_in_app_page": True}, b"")
    assert v["goal_reached"] is True


def test_pricing_page_is_the_answer_for_a_pricing_question(monkeypatch):
    monkeypatch.setattr(R, "frame_unrendered", lambda png: False)
    row = {"final_url": "https://tally.so/pricing", "task_prompt": "Find out what the free plan includes and what you "
           "would pay to remove the product's branding."}
    v = R.apply_hard_rules(row, {"goal_reached": True, "reason": "pricing shown"}, {"signed_in_app_page": False}, b"")
    assert v["goal_reached"] is True and not v.get("billing_wall")


# ---- report format: MCP studies go through the website's finish_study, keeping the MCP verdicts
import asyncio

import mvp.study as S


def _verdict():
    return {"goal_reached": True, "signup_verified": True, "votes_yes": 2,
            "votes": [{"goal_reached": True}, {"goal_reached": True}], "signed_in_app_page": True}


def test_finish_study_keep_verdicts_skips_page_verdicts(monkeypatch):
    import mvp.comparison as C
    import mvp.page_verdict as PV

    called = []

    async def pv(study):
        called.append("pv")
        for r in study.agent_results:
            r["page_verdict"] = {"goal_reached": False}

    async def cs(study):
        called.append("cs")

    monkeypatch.setattr(PV, "apply_page_verdicts", pv)
    monkeypatch.setattr(C, "apply_comparison_scores", cs)
    monkeypatch.setattr(S, "persist_study", lambda *a, **k: None)
    st = S.StudyState(id="t-keep", url="https://x.io", segment="dev")
    st.agent_results = [{"agent_id": "a1", "page_verdict": _verdict(), "completed": True, "trace": []}]
    try:
        asyncio.run(S.finish_study(st, keep_verdicts=True))
    except Exception:  # noqa: BLE001  (later report steps may need network; the verdict step is what is checked)
        pass
    assert "pv" not in called and "cs" in called
    assert st.agent_results[0]["page_verdict"]["votes_yes"] == 2
    assert st.agent_results[0]["page_verdict"]["signup_verified"] is True


def test_finish_study_default_still_runs_page_verdicts(monkeypatch):
    import mvp.comparison as C
    import mvp.page_verdict as PV

    called = []

    async def pv(study):
        called.append("pv")

    async def cs(study):
        called.append("cs")

    monkeypatch.setattr(PV, "apply_page_verdicts", pv)
    monkeypatch.setattr(C, "apply_comparison_scores", cs)
    monkeypatch.setattr(S, "persist_study", lambda *a, **k: None)
    st = S.StudyState(id="t-default", url="https://x.io", segment="dev")
    st.agent_results = [{"agent_id": "a1", "page_verdict": {}, "trace": []}]
    try:
        asyncio.run(S.finish_study(st))
    except Exception:  # noqa: BLE001
        pass
    assert called[:2] == ["pv", "cs"] or set(called) >= {"pv", "cs"}


def _stub_finalize(monkeypatch, finish):
    from mvp.sim_mcp import report as R
    from mvp.sim_mcp import sessions as SS

    async def judge(sid, row):
        return _verdict(), "ok"

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(R, "judge_run", judge)
    monkeypatch.setattr(R, "close", noop)
    monkeypatch.setattr(SS, "settle_final", noop)
    monkeypatch.setattr(R, "proof_checks", lambda p, r, j: {"pass": True, "checks": []})
    monkeypatch.setattr(S, "persist_study", lambda *a, **k: None)
    monkeypatch.setattr(S, "finish_study", finish)
    st = S.StudyState(id="t-fin", url="https://x.io", segment="dev")
    sim = SS.SimSession(id="t", study=st, product_url="https://x.io", task="sign up", persona="p")
    st.live_sessions = {sim.agent_id: {"agent_id": sim.agent_id, "trace": []}}
    return R, sim, st


def test_finalize_uses_website_finish_study_and_keeps_verdicts(monkeypatch):
    seen = {}

    async def finish(study, **kw):
        seen.update(kw)
        study.summary = {"headline": "website headline", "top_strengths": ["x"]}
        study.status = "complete"

    R, sim, st = _stub_finalize(monkeypatch, finish)
    asyncio.run(R.finalize(sim, outcome="completed", notes="ok"))
    assert seen.get("keep_verdicts") is True
    assert st.summary["top_strengths"] == ["x"] and st.summary["headline"] == "website headline"
    assert st.summary["proof"]["pass"] is True and st.summary["judge_status"] == "ok" and st.summary["driver"]
    pv = st.agent_results[0]["page_verdict"]
    assert pv["votes_yes"] == 2 and pv["signup_verified"] is True
    assert st.status == "complete"


def test_finalize_falls_back_when_website_report_fails(monkeypatch):
    async def finish(study, **kw):
        raise RuntimeError("llm down")

    R, sim, st = _stub_finalize(monkeypatch, finish)
    asyncio.run(R.finalize(sim, outcome="completed", notes="ok"))
    assert st.status == "complete" and st.summary["headline"] and "report_error" in st.summary
    assert st.agent_results[0]["page_verdict"]["votes_yes"] == 2


def test_finish_matrix_keeps_verdicts(monkeypatch):
    from mvp.sim_mcp import report as R

    seen = {}

    async def finish(study, **kw):
        seen.update(kw)

    monkeypatch.setattr(S, "finish_study", finish)
    monkeypatch.setattr(S, "persist_study", lambda *a, **k: None)
    st = S.StudyState(id="t-mx", url="https://x.io", segment="dev")
    st.agent_results = [{"agent_id": "a1", "mcp_proof": {"pass": True}, "page_verdict": _verdict()}]
    asyncio.run(R._finish_matrix(st))
    assert seen.get("keep_verdicts") is True and st.summary["mcp_proof"]["passed"] == 1


def test_demo_booking_links_are_never_verify_links():
    from mvp.signup_inbox import _skip_link

    for u in ["https://calendly.com/j-atatus", "https://cal.com/team/demo", "https://meetings.hubspot.com/x"]:
        assert _skip_link(u), u
    assert not _skip_link("https://www.atatus.com/verify?id=abc")


def test_company_email_only_is_detected_from_inline_errors():
    from mvp.sim_mcp.sessions import work_email_required

    assert work_email_required(["Please sign up with your company email address."])
    assert work_email_required(["Free email providers are not allowed"])
    assert work_email_required(["Gmail addresses are not accepted"])
    assert not work_email_required(["Email is required", "work@email.com"])
    assert not work_email_required(["Password must contain a number"])
    assert not work_email_required(None)


def test_finish_asks_once_to_open_the_verification_mail(monkeypatch):
    import json as _json

    from mvp.sim_mcp import server as SV
    from mvp.sim_mcp import sessions as SS

    st = S.StudyState(id="t-nudge", url="https://x.io", segment="dev")
    sim = SS.SimSession(id="n1", study=st, product_url="https://x.io", task="sign up", persona="p")
    sim.inbox = object()
    sim.study.live_sessions = {sim.agent_id: {"agent_id": sim.agent_id, "signup_email": "a+b@gmail.com", "trace": []}}
    monkeypatch.setattr(SS, "get_session", lambda sid: sim)
    finals = []

    async def fin(s, **kw):
        finals.append(kw)
        return st

    monkeypatch.setattr(SV, "finalize", fin)
    monkeypatch.setattr(SV, "build_report", lambda study: {"study_id": "t-nudge", "headline": "h", "proof": {}})
    first = _json.loads(asyncio.run(SV.usersim_finish("n1", "completed", "done")))
    assert first["finished"] is False and "verification" in first["next"] and not finals
    asyncio.run(SV.usersim_finish("n1", "completed", "done"))
    assert len(finals) == 1
    # gave_up / blocked never get the nudge
    sim2 = SS.SimSession(id="n2", study=st, product_url="https://x.io", task="sign up", persona="p")
    sim2.inbox = object()
    monkeypatch.setattr(SS, "get_session", lambda sid: sim2)
    asyncio.run(SV.usersim_finish("n2", "blocked", "work email only"))
    assert len(finals) == 2


def test_act_flattened_action_gets_a_clear_error(monkeypatch):
    import json as _json

    from mvp.sim_mcp import server as SV

    out = _json.loads(asyncio.run(SV.usersim_act("nope", "hop", "I click")))
    assert "ONE object" in out["error"]
    seen = []
    monkeypatch.setattr(SV.S, "get_session", lambda sid: (_ for _ in ()).throw(SV.S.SessionError("unknown session")))
    out = _json.loads(asyncio.run(SV.usersim_act("nope", "click", "I click", x="888", y="31")))
    assert "unknown session" in out["error"]  # rebuilt into an object, so it got as far as the session lookup
    out = _json.loads(asyncio.run(SV.usersim_act("nope", '{"type":"click","x":1,"y":2}', "I click")))
    assert "unknown session" in out["error"]  # parsed, then the bad session id is reported


def test_key_names_are_normalised():
    from mvp.sim_mcp.sessions import norm_keys

    assert norm_keys("BackSpace") == "Backspace"
    assert norm_keys("ctrl+a") == "Control+a"
    assert norm_keys("Cmd+Shift+K") == "Meta+Shift+K"
    assert norm_keys("Return") == "Enter"
    assert norm_keys("F5") == "F5" and norm_keys("a") == "a" and norm_keys("Enter") == "Enter"


def test_site_redirect_on_first_load_counts_as_the_product():
    row = {"site_url": "https://teable.io", "page_url": "https://teable.ai/", "opening_redirect": "https://teable.ai/"}
    assert R._opening_redirect(row)
    assert not R._opening_redirect({"site_url": "https://teable.io", "page_url": "https://teable.ai/"})
    assert not R._opening_redirect({"site_url": "https://teable.io", "page_url": "https://evil.com/",
                                    "opening_redirect": "https://teable.ai/"})


def test_mail_wait_is_capped_below_common_client_timeouts(monkeypatch):
    import json as _json

    import mvp.signup_tools as T
    from mvp.sim_mcp import server as SV
    from mvp.sim_mcp import sessions as SS

    st = S.StudyState(id="t-wait", url="https://x.io", segment="dev")
    sim = SS.SimSession(id="w1", study=st, product_url="https://x.io", task="sign up", persona="p")
    sim.inbox = object()
    st.live_sessions = {sim.agent_id: {"agent_id": sim.agent_id, "trace": []}}
    monkeypatch.setattr(SS, "get_session", lambda sid: sim)
    seen = []
    monkeypatch.setattr(T, "wait_mail", lambda *a, **k: seen.append(k["timeout_s"]))
    out = _json.loads(asyncio.run(SV.usersim_wait_for_verification_link("w1", 180)))
    assert seen == [50] and out["found"] is False and "call this tool again" in out["note"]


def test_mail_link_by_number_or_near_exact_copy():
    import pytest

    from mvp.sim_mcp.server import resolve_mail_link
    from mvp.sim_mcp.sessions import SessionError

    good = "https://baserow.io/verify-email-address/.eJwdi80OgjAMgN-lV2TpuiHQkw_BnYy5kCZOCIVIYnx3p9fv5w2Hpm2UOzA5T62_QMpBHsB_oZJV5qc5Vq2mUMDysjF2U3ebf5WJS4ZynKtsScewl42QrrXF2veBf5WJS4ZynKtsScewl42QrrXF2venstc.CMvBOvDlNB8so1Ao62JiVNt76Ts"
    links = [good, "https://baserow.io", "https://baserow.io/privacy"]
    assert resolve_mail_link(links, "", 1) == good and resolve_mail_link(links, "", 3).endswith("privacy")
    garbled = good.replace("XF2venstc", "XF2veBf5WJS4ZynKtsScewl42QrrXF2venstc")
    assert resolve_mail_link(links, garbled, 0) == good
    with pytest.raises(SessionError):
        resolve_mail_link(links, "https://evil.com/verify-email-address/abc", 0)
    with pytest.raises(SessionError):
        resolve_mail_link(links, "", 9)
    with pytest.raises(SessionError):
        resolve_mail_link([], good, 0)


def test_probe_refuses_bad_certificates_and_unknown_hosts(monkeypatch):
    import httpx
    import pytest

    from mvp.sim_mcp import sessions as SS

    monkeypatch.setenv("MVP_MCP_PROBE_SITES", "1")

    def boom(msg):
        def get(*a, **k):
            raise httpx.ConnectError(msg)
        return get

    monkeypatch.setattr(httpx, "get", boom("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch"))
    with pytest.raises(SS.SessionError):
        SS.probe_reachable("https://harmonizely.com")
    monkeypatch.setattr(httpx, "get", boom("[Errno -2] Name or service not known"))
    with pytest.raises(SS.SessionError):
        SS.probe_reachable("https://nope.invalid")
    monkeypatch.setattr(httpx, "get", boom("Connection refused"))
    SS.probe_reachable("https://flaky.example")  # not a TLS/DNS failure: let the browser try

    def timeout(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "get", timeout)
    SS.probe_reachable("https://slow.example")


def test_cell_whose_browser_failed_goes_back_to_the_queue(monkeypatch):
    import pytest

    from mvp.sim_mcp import sessions as SS

    study = SS.create_matrix_study(product_url="https://a.com", competitors=[], personas=[{"bio": "x"}], tasks=["y"])
    cell = next(iter(study.live_sessions))

    async def bad_open(sim):
        raise RuntimeError("net::ERR_CERT_COMMON_NAME_INVALID")

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(SS, "_open_browser", bad_open)
    monkeypatch.setattr(SS, "maybe_finish_study", noop, raising=False)
    for attempt in range(1, SS.START_TRIES):
        with pytest.raises(SS.SessionError, match="still queued"):
            asyncio.run(SS.start_session(study_id=study.id, cell_id=cell))
        assert study.live_sessions[cell]["status"] == "queued"
    with pytest.raises(RuntimeError):
        import mvp.sim_mcp.report as RR
        monkeypatch.setattr(RR, "maybe_finish_study", noop)
        asyncio.run(SS.start_session(study_id=study.id, cell_id=cell))
    assert study.live_sessions[cell]["status"] == "error"


def test_grouped_codes_are_found():
    from mvp.email_codes import _find_code

    body = ("Confirm your email address\n\nYour confirmation code is below. Enter it in your open browser window "
            "to finish signing in.\n\n935-413\n\nIf you didn't request this email, you can safely ignore it.")
    assert _find_code("Confirm your Koalendar email address", body) == "935413"
    assert _find_code("Sign in", "Your login code is 482 917. It expires in 10 minutes.") == "482917"
    assert _find_code("Welcome", "Questions? Call us at 555-1234 or write to us.") is None


def test_scroll_and_coordinate_aliases_are_normalised():
    from mvp.sim_mcp.sessions import validate_action

    u = "https://x.io"
    assert validate_action({"type": "scroll", "x": 640, "y": 400, "deltaY": 700}, u)["dy"] == 700
    assert validate_action({"type": "scroll", "x": 640, "y": 500, "delta_y": 500}, u)["dy"] == 500
    assert validate_action({"type": "scroll", "x": 640, "y": 500, "direction": "down", "amount": 400}, u)["dy"] == 400
    assert validate_action({"type": "scroll", "x": 640, "y": 500, "direction": "up", "amount": 400}, u)["dy"] == -400
    a = validate_action({"type": "click", "x": "640", "y": "400.0"}, u)
    assert (a["x"], a["y"]) == (640, 400)
