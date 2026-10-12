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
    row = {"final_url": "https://app.x.com/dashboard"}
    v = R.apply_hard_rules(row, {"goal_reached": False, "reason": "x"}, {"signed_in_app_page": True}, b"")
    assert v["goal_reached"] is True
