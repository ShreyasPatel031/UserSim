"""Generic fixes from the figma.com home-page run (study 4d947b3f)."""

from __future__ import annotations

import unittest

from mvp.a11y_agent import auth_modal_opened, auth_page, goal_visible, looping, task_kind


def _nodes(n: int, inert: int) -> list[dict]:
    return [{"i": i, "role": "a", "name": f"n{i}", "inert": i < inert} for i in range(n)]


class TaskKindIgnoresRivalAddressTests(unittest.TestCase):
    def test_sketch_domain_does_not_make_a_pricing_task_a_drawing(self):
        task = "Look for pricing or how to get started (vs https://www.sketch.com/)"
        self.assertEqual(task_kind(task), "pricing")
        self.assertTrue(goal_visible(task, {"url": "https://www.sketch.com/pricing/", "title": "Pricing"}))

    def test_real_drawing_tasks_still_draw(self):
        self.assertEqual(task_kind("Sketch a box on the canvas"), "draw")
        self.assertEqual(task_kind("Draw a rectangle (vs https://excalidraw.com/)"), "draw")


class AuthModalTests(unittest.TestCase):
    def test_signup_link_that_opens_a_dialog_on_the_same_page_is_an_account_wall(self):
        before = {"url": "https://www.figma.com/", "nodes": _nodes(20, 0), "dialog": False}
        after = {"url": "https://www.figma.com/", "nodes": _nodes(20, 19), "dialog": False}
        self.assertTrue(auth_modal_opened("https://www.figma.com/signup", before, after))
        after["auth_modal"] = "https://www.figma.com/signup"
        self.assertTrue(auth_page(after))

    def test_ordinary_link_or_navigation_is_not_an_auth_modal(self):
        before = {"url": "https://www.figma.com/", "nodes": _nodes(20, 0)}
        blocked = {"url": "https://www.figma.com/", "nodes": _nodes(20, 19)}
        self.assertFalse(auth_modal_opened("https://www.figma.com/pricing/", before, blocked))
        moved = {"url": "https://www.figma.com/signup", "nodes": _nodes(20, 0)}
        self.assertFalse(auth_modal_opened("https://www.figma.com/signup", before, moved))
        self.assertFalse(auth_modal_opened("https://www.figma.com/signup", before, dict(before)))


class ThreePageLoopTests(unittest.TestCase):
    def test_pricing_trial_home_cycle_is_a_loop(self):
        cycle = [
            ("click Pricing", "https://www.sketch.com/pricing/"),
            ("click Or start a free trial", "https://www.sketch.com/downloads/mac/"),
            ("click Go to Homepage", "https://www.sketch.com/"),
        ]
        trace = [{"step": i + 1, "action": cycle[i % 3][0], "url": cycle[i % 3][1]} for i in range(12)]
        self.assertTrue(looping(trace))
        self.assertFalse(looping(trace[:11]))

    def test_steady_progress_is_not_a_loop(self):
        trace = [{"step": i + 1, "action": f"click item {i}", "url": f"https://x.com/{i}"} for i in range(12)]
        self.assertFalse(looping(trace))


if __name__ == "__main__":
    unittest.main()
