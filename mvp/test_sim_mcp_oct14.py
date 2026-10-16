"""Oct 14: proof reason, research tasks need no signup proof / may answer on the first screen, skipped cells, click by text."""
import asyncio

import pytest

from mvp.sim_mcp import report as R
from mvp.sim_mcp import sessions as S


def _row(task, **kw):
    row = {"task_prompt": task, "site_url": "https://plausible.io/", "page_url": "https://plausible.io/",
           "trace": [], "agent_id": "a1", "live_view_url": "https://x", "page_verdict": {"goal_reached": True}}
    row.update(kw)
    return row


def _stub_gates(monkeypatch, moved=False, verified=False):
    import mvp.e2e2_gates as G

    monkeypatch.setattr(G, "beyond_first_screen", lambda row, site: moved)
    monkeypatch.setattr(G, "has_click_type_scroll", lambda row: True)
    monkeypatch.setattr(G, "opened_on_assigned_site", lambda row: True)
    monkeypatch.setattr(R, "_shot_ok", lambda *a: True)
    monkeypatch.setattr(R, "signup_verified", lambda row: verified)


def _study():
    return {"id": "s1", "test_mode": False, "driver": R.DRIVER}


def test_research_task_detection():
    assert R.is_research_task({"task_prompt": "Find out how much the cheapest paid plan costs per month."})
    assert R.is_research_task({"task_prompt": "Compare plans without creating an account."})
    assert not R.is_research_task({"task_prompt": "Sign up with a new account and verify your email."})


def test_research_answer_on_opening_page_passes_with_reason(monkeypatch):
    _stub_gates(monkeypatch, moved=False)
    row = _row("Find out how much the cheapest paid plan costs per month.", trace=[{"step": 1}])
    out = R.proof_checks(_study(), row, "ok")
    assert out["pass"] is True and out["reason"] == "all proof checks passed"
    fs = next(c for c in out["checks"] if c["name"] == "beyond_first_screen")
    assert fs["pass"] and "research task" in fs["detail"]


def test_research_task_with_alias_needs_no_signup_proof(monkeypatch):
    _stub_gates(monkeypatch, moved=True, verified=False)
    row = _row("Find out how much the cheapest paid plan costs per month.", trace=[{"step": 1}],
               signup_email="usersim.signups+x@gmail.com")
    out = R.proof_checks(_study(), row, "ok")
    assert out["pass"] is True
    assert "signup_verified" not in [c["name"] for c in out["checks"]]


def test_signup_task_still_needs_proof_and_reason_names_it(monkeypatch):
    _stub_gates(monkeypatch, moved=True, verified=False)
    row = _row("Sign up with a new account and verify your email.", trace=[{"step": 1}],
               signup_email="usersim.signups+x@gmail.com")
    out = R.proof_checks(_study(), row, "ok")
    assert out["pass"] is False and out["reason"].startswith("signup_verified:")


def test_first_screen_still_required_when_judge_failed(monkeypatch):
    _stub_gates(monkeypatch, moved=False)
    row = _row("Find the price.", trace=[{"step": 1}], page_verdict={"goal_reached": False})
    out = R.proof_checks(_study(), row, "ok")
    assert out["pass"] is False and "beyond_first_screen" in out["reason"]


def test_skipped_cell_gets_a_report_row(monkeypatch):
    import mvp.study as ST

    started = []

    async def fake_finish(study):
        started.append(study.id)

    monkeypatch.setattr(R, "_finish_matrix", fake_finish)
    st = ST.StudyState(id="t-skip", url="https://plausible.io", segment="dev")
    st.status = "running"
    st.live_sessions = {"a1": {"agent_id": "a1", "status": "complete", "site_label": "Product"},
                        "a2": {"agent_id": "a2", "status": "pending", "site_label": "Usefathom", "cell_id": "t1__p1__competitor_1"}}
    st.agent_results = [{"agent_id": "a1", "status": "complete", "mcp_proof": {"pass": True}}]

    async def run():
        return await R.maybe_finish_study(st, force=True)

    assert asyncio.run(run()) is True
    sk = [a for a in st.agent_results if a["agent_id"] == "a2"][0]
    assert sk["status"] == "skipped" and sk["driver_outcome"] == "skipped" and sk["page_verdict"]["skipped"]
    assert sk["site_label"] == "Usefathom" and sk["mcp_proof"]["reason"].startswith("skipped")
    R._FINISHING.discard("t-skip")


def test_click_by_text_validation():
    a = S.validate_action({"type": "click", "text": "Continue"}, "https://x.io")
    assert a["by_text"] is True
    with pytest.raises(S.SessionError):
        S.validate_action({"type": "click"}, "https://x.io")
    a2 = S.validate_action({"type": "click", "x": 10, "y": 10, "text": "Continue"}, "https://x.io")
    assert not a2.get("by_text")


class _El:
    def __init__(self, visible, log):
        self.visible, self.log = visible, log

    async def is_visible(self):
        return self.visible

    async def scroll_into_view_if_needed(self, timeout=0):
        self.log.append("scroll")

    async def click(self, timeout=0):
        self.log.append("click")


class _Loc:
    def __init__(self, els):
        self.els = els

    async def count(self):
        return len(self.els)

    def nth(self, i):
        return self.els[i]

    def filter(self, **kw):
        return _Loc([])


class _Page:
    def __init__(self, log):
        self.log = log

    def get_by_role(self, role, name=None):
        return _Loc([_El(False, self.log), _El(True, self.log)] if role == "button" else [])

    def locator(self, sel):
        return _Loc([])

    def get_by_text(self, pat):
        return _Loc([])


def test_click_by_text_clicks_first_visible_button():
    log = []
    asyncio.run(S.click_by_text(_Page(log), "Continue"))
    assert log == ["scroll", "click"]


def test_click_by_text_reports_missing():
    class Empty(_Page):
        def get_by_role(self, role, name=None):
            return _Loc([])

    with pytest.raises(S.SessionError):
        asyncio.run(S.click_by_text(Empty([]), "Continue"))
