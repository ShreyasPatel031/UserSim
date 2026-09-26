"""Canvas ink detection: open-ended draw tasks ("draw a diagram with a hand-drawn feel")."""

from __future__ import annotations

import asyncio
import unittest

from mvp.a11y_agent import (
    _READ_JS,
    _drag_on_canvas,
    canvas_inked,
    canvas_note,
    goal_visible,
    strokes_needed,
    task_kind,
)

EMPTY = "2880x1640:dark=0/318000:h=0;"
THIN = "2880x1640:dark=3/318000:h=1x9k2a;"  # a thin pen stroke crosses a few scanned rows
THIN_ELSEWHERE = "2880x1640:dark=3/318000:h=7pq01z;"
BOX = "2880x1640:dark=240/318000:h=abc123;"


class CanvasInkedTest(unittest.TestCase):
    def test_thin_stroke_counts_by_position_hash(self):
        # A freehand stroke adds only a few dark samples: under the count
        # threshold, but the ink-position hash changes.
        self.assertTrue(canvas_inked(EMPTY, THIN))

    def test_second_stroke_elsewhere_counts(self):
        self.assertTrue(canvas_inked(THIN, THIN_ELSEWHERE))

    def test_same_ink_is_not_a_change(self):
        self.assertFalse(canvas_inked(THIN, THIN))
        self.assertFalse(canvas_inked(EMPTY, EMPTY))

    def test_dark_count_jump_counts(self):
        self.assertTrue(canvas_inked(EMPTY, BOX))

    def test_erasing_everything_is_not_ink(self):
        self.assertFalse(canvas_inked("10x10:dark=2/100:h=zz;", "10x10:dark=0/100:h=0;"))

    def test_tainted_or_missing_canvas_never_counts(self):
        self.assertFalse(canvas_inked("taint;", "taint;"))
        self.assertFalse(canvas_inked(EMPTY, "taint;"))
        # No canvas mounted yet at the baseline read.
        self.assertFalse(canvas_inked("", BOX))


class StrokesNeededTest(unittest.TestCase):
    def test_diagram_needs_two_strokes(self):
        for task in (
            "Draw a diagram with hand-drawn feel",
            "Draw a simple diagram with shapes",
            "Sketch a flowchart",
            "Draw a box and an arrow",
            "Draw two connected boxes",
        ):
            self.assertEqual(strokes_needed(task), 2, task)

    def test_single_shape_needs_one(self):
        for task in ("Draw a rectangle on the canvas", "Draw a basic shape on the canvas", "Sketch a circle"):
            self.assertEqual(strokes_needed(task), 1, task)
        self.assertEqual(task_kind("Draw a diagram with hand-drawn feel"), "draw")


def _read(canvas: str, *, opened: str = EMPTY, strokes: int | None = None, drew: bool = True) -> dict:
    read = {
        "url": "https://whiteboard.example/",
        "canvas": canvas,
        "opened_canvas": opened,
        "drew": drew,
        "shapes": 0,
        "opened_shapes": 0,
    }
    if strokes is not None:
        read["ink_strokes"] = strokes
    return read


class GoalVisibleDrawTest(unittest.TestCase):
    def test_thin_freehand_stroke_is_a_drawing(self):
        self.assertTrue(goal_visible("Draw a rectangle on the canvas", _read(THIN, strokes=1)))

    def test_diagram_needs_a_second_stroke(self):
        task = "Draw a diagram with hand-drawn feel"
        self.assertFalse(goal_visible(task, _read(THIN, strokes=1)))
        self.assertTrue(goal_visible(task, _read(THIN_ELSEWHERE, strokes=2)))

    def test_old_reads_without_stroke_count_still_judge_ink(self):
        self.assertTrue(goal_visible("Draw a diagram", _read(BOX)))

    def test_no_drag_or_no_ink_is_not_a_drawing(self):
        self.assertFalse(goal_visible("Draw a rectangle", _read(BOX, drew=False, strokes=1)))
        self.assertFalse(goal_visible("Draw a rectangle", _read(EMPTY, strokes=1)))

    def test_tool_icons_are_not_shapes(self):
        # The page scan skips SVG icons inside buttons, toolbars and labels.
        self.assertIn('closest(', _READ_JS)
        self.assertIn('[role="toolbar"]', _READ_JS)


class CanvasNoteTest(unittest.TestCase):
    def _tree(self, w: int, h: int) -> list:
        return [{"role": "canvas", "name": "", "x": 0, "y": 0, "w": w, "h": h}]

    def test_whiteboard_change_is_noted(self):
        self.assertTrue(canvas_note({"canvas": EMPTY}, {"canvas": THIN, "nodes": self._tree(1440, 820)}))

    def test_small_or_missing_canvas_is_quiet(self):
        self.assertFalse(canvas_note({"canvas": EMPTY}, {"canvas": THIN, "nodes": self._tree(120, 60)}))
        self.assertFalse(canvas_note({"canvas": EMPTY}, {"canvas": THIN, "nodes": []}))


class _Mouse:
    def __init__(self):
        self.points: list[tuple[int, int]] = []

    async def move(self, x, y, steps=1):
        self.points.append((int(x), int(y)))

    async def down(self):
        pass

    async def up(self):
        pass


class _Page:
    viewport_size = {"width": 1440, "height": 900}

    def __init__(self):
        self.mouse = _Mouse()
        self.shots = 0

    async def screenshot(self, **_kw):
        self.shots += 1
        return b""

    async def wait_for_timeout(self, _ms):
        pass


class DragPlacementTest(unittest.TestCase):
    def _path(self, index: int) -> list[tuple[int, int]]:
        page = _Page()
        # canvas_x/canvas_y are the box centre, as in the tree.
        action = {"act": "drag", "drag_index": index, "canvas_x": 720, "canvas_y": 450, "canvas_w": 1440, "canvas_h": 820}
        asyncio.run(_drag_on_canvas(page, action))
        return page.mouse.points

    def test_each_drag_lands_somewhere_new_inside_the_canvas(self):
        starts = set()
        for index in range(6):
            path = self._path(index)
            self.assertGreaterEqual(len(path), 4)  # an outline, not one straight line
            for x, y in path:
                self.assertTrue(0 < x < 1440 and 40 < y < 860, (index, x, y))
            starts.add(path[0])
        self.assertEqual(len(starts), 6)

    def test_drag_takes_no_screenshot_and_leaves_a_clip_under_the_stroke(self):
        page = _Page()
        action = {"act": "drag", "drag_index": 0, "canvas_x": 720, "canvas_y": 450, "canvas_w": 1440, "canvas_h": 820}
        asyncio.run(_drag_on_canvas(page, action))
        self.assertEqual(page.shots, 0)
        clip = action["_drag_clip"]
        xs = [x for x, _ in page.mouse.points]
        ys = [y for _, y in page.mouse.points]
        self.assertLessEqual(clip["x"], min(xs))
        self.assertGreaterEqual(clip["x"] + clip["width"], max(xs))
        self.assertLessEqual(clip["y"], min(ys))
        self.assertGreaterEqual(clip["y"] + clip["height"], max(ys))

    def test_first_drag_is_centred_clear_of_edge_toolbars(self):
        xs = [x for x, _ in self._path(0)]
        ys = [y for _, y in self._path(0)]
        self.assertTrue(1440 * 0.3 < min(xs) and max(xs) < 1440 * 0.7)
        self.assertTrue(450 - 820 * 0.2 < min(ys) and max(ys) < 450 + 820 * 0.2)


if __name__ == "__main__":
    unittest.main()


class ReadJsThinStrokeBrowserTest(unittest.TestCase):
    """The page scan itself sees a 1px pen stroke. Needs local Chrome; skipped otherwise."""

    def test_thin_stroke_changes_the_scan(self):
        try:
            from patchright.sync_api import sync_playwright
        except Exception:  # noqa: BLE001
            self.skipTest("patchright not installed")
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True, channel="chrome")
                except Exception:  # noqa: BLE001
                    browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content('<canvas id="c" width="1200" height="800"></canvas>')
                before = page.evaluate(_READ_JS)["canvas"]
                # A 1px freehand-like stroke that misses the old sparse point grid.
                page.evaluate(
                    """() => { const g = document.getElementById('c').getContext('2d');
                    g.strokeStyle = '#1e1e1e'; g.lineWidth = 1; g.beginPath();
                    g.moveTo(403, 301); g.bezierCurveTo(450, 333, 507, 318, 551, 371); g.stroke(); }"""
                )
                after = page.evaluate(_READ_JS)["canvas"]
                browser.close()
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"no local browser: {exc}")
        self.assertIn("dark=0/", before)
        self.assertTrue(canvas_inked(before, after), (before, after))
