import asyncio
from types import SimpleNamespace


def test_task_succeeded_follows_the_final_page_verdict():
    from mvp.report_insights import task_succeeded

    claimed_but_not_shown = {"failed_step": {"phase": "done"}, "page_verdict": {"goal_reached": False}}
    shown_but_not_claimed = {"failed_step": {"phase": "act", "reason": "step cap 30"}, "page_verdict": {"goal_reached": True}}
    assert task_succeeded(claimed_but_not_shown, "https://kolanut.ai") is False
    assert task_succeeded(shown_but_not_claimed, "https://kolanut.ai") is True
    # No verdict: the agent's own stop still decides.
    assert task_succeeded({"failed_step": {"phase": "done"}}, "https://kolanut.ai") is True


def test_apply_page_verdicts_uses_the_judge_prompt_on_each_final_png(tmp_path, monkeypatch):
    import mvp.e2e2_gates as gates
    import mvp.paths as paths

    monkeypatch.setattr(paths, "MVP_RUNS_DIR", tmp_path)
    shot = tmp_path / "s1" / "a1" / "screenshots"
    shot.mkdir(parents=True)
    (shot / "final.png").write_bytes(b"\x89PNG" + b"0" * 3000)
    seen = {}

    def fake_judge(png, *, task, start_url, final_url="", dom=""):
        seen.update(task=task, start=start_url, final=final_url, dom=dom, n=len(png))
        return {"goal_reached": True, "still_on_opening_screen": False, "reason": "draft in editor"}

    monkeypatch.setattr(gates, "judge_goal_screenshot", fake_judge)
    results = [
        {"agent_id": "a1", "completed": False, "final_url": "https://app/x", "final_screenshot_url": "/api/x/final.png",
         "trace": [{"step": 1, "state_sig": {"text": "Edit Campaign Hi {{firstName}}"}}]},
        {"agent_id": "a2", "completed": True, "final_screenshot_url": ""},
    ]
    study = SimpleNamespace(
        id="s1", url="https://kolanut.ai", agent_results=results,
        live_sessions={"a1": {"agent_id": "a1", "task_prompt": "Draft an outreach message", "site_url": "https://kolanut.ai"}},
    )
    from mvp.page_verdict import apply_page_verdicts

    assert asyncio.run(apply_page_verdicts(study)) == 2
    assert seen["task"] == "Draft an outreach message" and seen["final"] == "https://app/x"
    assert seen["dom"].startswith("Edit Campaign")
    assert results[0]["completed"] is True and results[0]["agent_claimed_done"] is False
    assert results[1]["completed"] is False and results[1]["agent_claimed_done"] is True
    assert results[1]["page_verdict"]["reason"] == "no final screenshot"
