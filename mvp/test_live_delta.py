"""Cursor delta for the home-page poll (/api/studies/<id>/live)."""
import unittest

from mvp.live_delta import HEAVY_KEYS, live_view
from mvp.study import create_study, STUDIES


def _study():
    s = create_study("https://example.com/", "seg")
    s.status = "running"
    s.tasks = [{"id": "t1__p1__product", "title": "A"}, {"id": "t2__p1__product", "title": "B"}]
    s.personas = [{"id": "p1", "name": "Maya"}]
    for aid in ("t1__p1__product", "t2__p1__product"):
        s.live_sessions[aid] = {
            "agent_id": aid,
            "created_at_ts": 1.0,
            "status": "running",
            "accessibility_tree": "x" * 5000,
            "trace": [{"step": 0, "action": "Opened https://example.com/", "ax_tree": "y" * 5000, "state_sig": {"text": "z"}}],
            "live_thoughts": [{"text": str(i)} for i in range(20)],
        }
    return s


class LiveDeltaTest(unittest.TestCase):
    def test_first_poll_has_everything_without_heavy_fields(self):
        s = _study()
        out = live_view(s, 0)
        self.assertEqual(out["session_order"], ["t1__p1__product", "t2__p1__product"])
        self.assertEqual(len(out["live_sessions"]), 2)
        self.assertIn("brief", out)
        self.assertFalse(out["final"])
        row = out["live_sessions"][0]
        self.assertFalse(HEAVY_KEYS & set(row))
        self.assertFalse(HEAVY_KEYS & set(row["trace"][0]))
        self.assertEqual(len(row["live_thoughts"]), 8)

    def test_next_poll_sends_only_changed_agents(self):
        s = _study()
        first = live_view(s, 0)
        again = live_view(s, first["rev"])
        self.assertEqual(again["live_sessions"], [])
        self.assertNotIn("brief", again)
        s.live_sessions["t2__p1__product"]["trace"].append({"step": 1, "action": "click Pricing"})
        s.live_sessions["t2__p1__product"]["last_action"] = "click Pricing"
        delta = live_view(s, again["rev"])
        self.assertEqual([r["agent_id"] for r in delta["live_sessions"]], ["t2__p1__product"])
        self.assertEqual(delta["live_sessions"][0]["trace"][-1]["action"], "click Pricing")
        self.assertGreater(delta["rev"], again["rev"])

    def test_foreign_cursor_gets_everything(self):
        s = _study()
        out = live_view(s, 10_000)
        self.assertEqual(out["since"], 0)
        self.assertEqual(len(out["live_sessions"]), 2)

    def test_terminal_study_is_final(self):
        s = _study()
        s.status = "complete"
        self.assertTrue(live_view(s, 0)["final"])

    def test_endpoint(self):
        from fastapi.testclient import TestClient

        from mvp.server import app

        s = _study()
        STUDIES[s.id] = s
        c = TestClient(app)
        r = c.get(f"/api/studies/{s.id}/live?since=0")
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["delta"])
        self.assertEqual(len(j["live_sessions"]), 2)
        r2 = c.get(f"/api/studies/{s.id}/live?since={j['rev']}").json()
        self.assertEqual(r2["live_sessions"], [])
        missing = c.get("/api/studies/nope/live").json()
        self.assertTrue(missing["final"])


if __name__ == "__main__":
    unittest.main()
