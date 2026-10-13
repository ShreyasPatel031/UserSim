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
