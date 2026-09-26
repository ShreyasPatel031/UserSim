import asyncio
import types
import unittest
from unittest import mock

from mvp import browser_slots as bs


def _study(sid, max_agents=0):
    return types.SimpleNamespace(id=sid, max_agents=max_agents, queue_eta_s=None, queue_position=None, queued_s=0.0)


class BrowserSlotsTest(unittest.TestCase):
    def setUp(self):
        bs._TICKETS.clear()
        bs._ACTIVE.clear()
        bs._COUNT_CACHE.update({"at": 0.0, "value": None})

    def test_first_study_starts_at_once_and_second_is_queued_with_an_eta(self):
        phases = []

        async def go():
            with mock.patch.object(bs, "_enabled", return_value=True), mock.patch.object(
                bs, "_fetch_count", return_value={"n": 0, "median_age_s": None}
            ), mock.patch.object(bs.asyncio, "sleep", new=_fast_sleep):
                a, b = _study("a"), _study("b")
                await bs.acquire(a, lambda *x: None)
                self.assertIn("a", bs._ACTIVE)
                waiter = asyncio.ensure_future(bs.acquire(b, lambda phase, status=None: phases.append((phase, status))))
                await _real_sleep(0.05)
                self.assertFalse(waiter.done())
                self.assertEqual(b.queue_position, 1)
                self.assertGreaterEqual(b.queue_eta_s, 10)
                bs._ACTIVE.pop("a")
                await asyncio.wait_for(waiter, 2)
                self.assertIn("b", bs._ACTIVE)

        asyncio.run(go())
        self.assertTrue(phases and phases[0][1] == "queued")
        self.assertIn("Starting in ~", phases[0][0])

    def test_busy_project_queues_until_enough_sessions_are_free(self):
        counts = [{"n": 12, "median_age_s": 60.0}, {"n": 12, "median_age_s": 63.0}, {"n": 0, "median_age_s": None}]

        async def fetch():
            return counts.pop(0) if counts else {"n": 0, "median_age_s": None}

        async def go():
            with mock.patch.object(bs, "_enabled", return_value=True), mock.patch.object(
                bs, "_fetch_count", side_effect=fetch
            ), mock.patch.object(bs.asyncio, "sleep", new=_fast_sleep):
                s = _study("c")
                seen = []
                await asyncio.wait_for(bs.acquire(s, lambda phase, status=None: seen.append(phase)), 2)
                return seen

        seen = asyncio.run(go())
        self.assertTrue(any("12 of 25 browsers are busy" in p for p in seen))

    def test_small_study_fits_beside_a_busy_project(self):
        async def go():
            with mock.patch.object(bs, "_enabled", return_value=True), mock.patch.object(
                bs, "_fetch_count", return_value={"n": 12, "median_age_s": 30.0}
            ):
                s = _study("d", max_agents=12)
                await asyncio.wait_for(bs.acquire(s, lambda *x: None), 1)

        asyncio.run(go())
        self.assertIn("d", bs._ACTIVE)

    def test_release_sweeps_only_this_studys_sessions(self):
        rows = [
            {"id": "1", "owner": "integration", "study_id": "s1"},
            {"id": "2", "owner": "integration", "study_id": "s1_product"},
            {"id": "3", "owner": "integration", "study_id": "s2"},
            {"id": "4", "owner": "signup", "study_id": ""},
        ]
        released = []
        with mock.patch.object(bs, "_enabled", return_value=True), mock.patch(
            "mvp.kill_switch.list_running_browserbase", return_value=rows
        ), mock.patch("mvp.kill_switch.release_browserbase_session", side_effect=lambda i: released.append(i) or True):
            self.assertEqual(bs.release_study_sessions("s1"), 2)
        self.assertEqual(released, ["1", "2"])


_real_sleep = asyncio.sleep


async def _fast_sleep(_s):
    await _real_sleep(0.01)


class InterruptedTest(unittest.TestCase):
    def test_saved_running_study_is_marked_interrupted(self):
        from mvp.study import looks_interrupted, mark_interrupted

        data = {"id": "zz", "status": "running", "updated_at": "2026-09-26T10:00:00+00:00", "live_sessions": {"a": {"status": "running", "live_active": True}}}
        self.assertTrue(looks_interrupted(data))
        out = mark_interrupted(data)
        self.assertEqual(out["status"], "abandoned")
        self.assertIn("server restarted", out["error"])
        self.assertEqual(out["live_sessions"]["a"]["status"], "killed")
        self.assertFalse(looks_interrupted({"id": "zz", "status": "complete", "updated_at": "2026-09-26T10:00:00+00:00"}))


if __name__ == "__main__":
    unittest.main()
