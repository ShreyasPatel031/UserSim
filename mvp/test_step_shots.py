import asyncio
import unittest
from unittest import mock

from mvp import step_shots


class _Page:
    def __init__(self, fail_first: int = 0) -> None:
        self.calls = 0
        self.fail_first = fail_first
        self.active = 0
        self.max_active = 0

    async def screenshot(self, **_kw):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            if self.calls <= self.fail_first:
                raise RuntimeError("Target navigated")
            return b"jpeg"
        finally:
            self.active -= 1


class StepShotTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_failed_capture_is_retried_after_the_action(self) -> None:
        async def go():
            token = step_shots.STUDY.set("s1")
            try:
                page = _Page(fail_first=1)
                row: dict = {}
                with mock.patch.object(step_shots, "_upload", return_value=True), mock.patch.object(
                    step_shots.asyncio, "sleep", new=_fast_sleep
                ):
                    step_shots.attach(step_shots.start_capture(page), row, "a1", 3, page=page)
                    await step_shots.drain("a1", 2.0)
                return row
            finally:
                step_shots.STUDY.reset(token)

        row = self._run(go())
        self.assertEqual(row.get("screenshot_url"), "/api/studies/s1/agents/a1/screenshots/step_3.jpg")
        self.assertTrue(row.get("screenshot_after_action"))

    def test_captures_on_one_page_do_not_overlap(self) -> None:
        async def go():
            token = step_shots.STUDY.set("s1")
            try:
                page = _Page()
                rows = [{}, {}]
                with mock.patch.object(step_shots, "_upload", return_value=True):
                    step_shots.shot_now(page, rows[0], "a2", 0)
                    step_shots.attach(step_shots.start_capture(page), rows[1], "a2", 1, page=page)
                    await step_shots.drain("a2", 2.0)
                return page, rows
            finally:
                step_shots.STUDY.reset(token)

        page, rows = self._run(go())
        self.assertEqual(page.max_active, 1)
        self.assertTrue(all(r.get("screenshot_url") for r in rows))


_real_sleep = asyncio.sleep


async def _fast_sleep(_s):
    await _real_sleep(0)


if __name__ == "__main__":
    unittest.main()
