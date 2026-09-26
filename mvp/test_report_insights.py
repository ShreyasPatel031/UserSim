"""Claims in the study report must cite a real screenshot step."""

from __future__ import annotations

import unittest

from mvp.report_insights import (
    build_report_insights,
    changed_page_state,
    left_start,
    product_completion_gate,
    product_task_passed,
    task_succeeded,
    work_metrics,
)


def _run(
    agent_id: str,
    *,
    site_key: str = "product",
    steps: int = 1,
    difficulty: str = "easy",
    convert: str = "maybe",
    final: str = "https://linear.app/",
    easy: list[str] | None = None,
    friction: list[str] | None = None,
    quote: str = "",
) -> dict:
    trace = []
    for i in range(steps):
        trace.append(
            {
                "step": i,
                "action": f"Opened step {i}",
                "url": final,
                "screenshot_url": f"/api/studies/s/agents/{agent_id}/screenshots/bbox_{i}.png",
                "outcome": "friction" if friction and i == steps - 1 else "neutral",
            }
        )
    return {
        "agent_id": agent_id,
        "persona_name": "Pat",
        "task_title": "Skim the homepage",
        "site_key": site_key,
        "site_label": "Product" if site_key == "product" else site_key,
        "site_url": final,
        "num_steps": steps,
        "difficulty": difficulty,
        "would_convert": convert,
        "final_url": final,
        "what_was_easy": easy or [],
        "friction_points": friction or [],
        "quote": quote,
        "trace": trace,
    }


class WorkMetricTests(unittest.TestCase):
    def test_homepage_only_is_not_task_success(self) -> None:
        run = _run("a", steps=1, final="https://docs.python.org/3/")
        self.assertFalse(task_succeeded(run, "https://docs.python.org/3/"))
        self.assertFalse(left_start(run, "https://docs.python.org/3/"))

    def test_leaving_the_start_url_after_a_click_is_success(self) -> None:
        run = _run("a", steps=2, final="https://docs.python.org/3/tutorial/")
        run["site_url"] = "https://docs.python.org/3/"
        run["trace"][0]["url"] = "https://docs.python.org/3/"
        run["trace"][1]["action"] = "click — index=4"
        run["trace"][1]["url"] = "https://docs.python.org/3/tutorial/"
        self.assertTrue(left_start(run, "https://docs.python.org/3/"))
        self.assertTrue(task_succeeded(run, "https://docs.python.org/3/"))
        metrics = work_metrics([run], "https://docs.python.org/3/")
        self.assertEqual(metrics["left_start_pct"], 100)
        self.assertEqual(metrics["task_success_rate"], 100)
        self.assertEqual(metrics["median_steps"], 2)

    def test_done_after_a_click_on_the_same_url_counts(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        run["trace"][1]["action"] = "done — text=Opened the menu and found Export image"
        run["trace"][1]["url"] = "https://excalidraw.com/"
        run["trace"][0]["action"] = "click — index=25"
        self.assertFalse(left_start(run, "https://excalidraw.com/"))
        self.assertTrue(task_succeeded(run, "https://excalidraw.com/"))

    def test_canvas_drag_changes_page_state_without_a_url_change(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        blank = "900x600:dark=0/2304;"
        drawn = "900x600:dark=40/2304;"
        run["trace"][0]["url"] = "https://excalidraw.com/"
        run["trace"][0]["state_sig"] = {"text": "excalidraw canvas", "canvas": blank}
        run["trace"][1]["action"] = "drag — start_x=120 start_y=180 end_x=400 end_y=320"
        run["trace"][1]["url"] = "https://excalidraw.com/"
        run["trace"][1]["state_sig"] = {"text": "excalidraw canvas", "canvas": drawn}
        run["trace"][1]["step_latency_s"] = 4.2
        self.assertFalse(left_start(run, "https://excalidraw.com/"))
        self.assertTrue(changed_page_state(run, "https://excalidraw.com/"))
        self.assertTrue(task_succeeded(run, "https://excalidraw.com/"))
        metrics = work_metrics([run], "https://excalidraw.com/")
        self.assertEqual(metrics["changed_page_pct"], 100)
        self.assertEqual(metrics["left_start_pct"], 0)
        self.assertEqual(metrics["step_latency_p50"], 4.2)

    def test_done_on_the_first_screen_fails_the_product_gate(self) -> None:
        run = _run("a", steps=2, final="https://linear.app/")
        run["site_url"] = "https://linear.app/"
        run["trace"][0]["action"] = "Opened https://linear.app/"
        run["trace"][1]["action"] = "done — text=The homepage looks modern and clear"
        self.assertFalse(product_task_passed(run, "https://linear.app/"))

    def test_product_gate_needs_half_and_counts_first_screen_as_failure(self) -> None:
        runs = []
        for i in range(8):
            run = _run(f"p{i}", steps=2, final="https://linear.app/")
            run["site_url"] = "https://linear.app/"
            run["site_key"] = "product"
            if i < 4:
                run["trace"][0]["url"] = "https://linear.app/"
                run["trace"][0]["action"] = "click — index=3"
                run["trace"][1]["action"] = "click — index=9"
                run["trace"][1]["url"] = "https://linear.app/pricing"
                run["final_url"] = "https://linear.app/pricing"
            else:
                run["trace"][0]["action"] = "Opened https://linear.app/"
                run["trace"][1]["action"] = "wait — seconds=5"
                run["trace"][1]["url"] = "https://linear.app/"
            runs.append(run)
        runs.append(_run("c1", site_key="competitor_1", steps=1, final="https://asana.com/"))
        gate = product_completion_gate(runs, "https://linear.app/")
        self.assertEqual(gate["product_n"], 8)
        self.assertEqual(gate["success_n"], 4)
        self.assertEqual(gate["required_n"], 4)
        self.assertEqual(len(gate["first_screen_failures"]), 4)
        self.assertTrue(gate["pass"])
        gate["success_n"] = 3
        # A 3/8 result is below the bar. Rebuild from runs to prove it.
        runs[3]["trace"][1]["url"] = "https://linear.app/"
        runs[3]["final_url"] = "https://linear.app/"
        runs[3]["trace"][1]["action"] = "wait — seconds=5"
        gate = product_completion_gate(runs, "https://linear.app/")
        self.assertEqual(gate["success_n"], 3)
        self.assertFalse(gate["pass"])

    def test_one_canvas_sample_is_not_a_page_change(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        base = "900x600:dark=2/2304;"
        flicker = "900x600:dark=4/2304;"
        run["trace"][0]["state_sig"] = {"text": "excalidraw", "canvas": base}
        run["trace"][1]["action"] = "click — index=29"
        run["trace"][1]["state_sig"] = {"text": "excalidraw", "canvas": flicker}
        self.assertFalse(changed_page_state(run, "https://excalidraw.com/"))
        self.assertFalse(task_succeeded(run, "https://excalidraw.com/"))

    def test_title_only_opening_read_then_a_real_page_counts(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        run["trace"][0]["url"] = "https://excalidraw.com/"
        run["trace"][0]["state_sig"] = {"text": "Excalidraw", "canvas": ""}
        run["trace"][1]["url"] = "https://excalidraw.com/"
        run["trace"][1]["state_sig"] = {
            "text": "Excalidraw Selected shape actions Stroke Background " + ("shape " * 30),
            "canvas": "900x600:dark=40/2304;",
        }
        self.assertTrue(changed_page_state(run, "https://excalidraw.com/"))


class InsightTests(unittest.TestCase):
    def test_generic_load_notes_are_not_strengths(self) -> None:
        study = {
            "url": "https://linear.app/",
            "status": "complete",
            "agent_results": [
                _run(
                    "t1__p1__product",
                    easy=["The page loaded without any obvious issues."],
                    quote="The homepage loaded quickly.",
                )
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        self.assertEqual(insights["strengths"], [])
        self.assertTrue(insights["evidence_thin"])
        self.assertIn("thin", insights["headline"].lower())
        self.assertTrue(insights["weaknesses"])
        ev = insights["weaknesses"][0]["evidence"][0]
        self.assertEqual(ev["agent_id"], "t1__p1__product")
        self.assertIn("bbox_0.png", ev["screenshot_url"])
        self.assertEqual(ev["final_url"], "https://linear.app/")

    def test_drawing_canvas_is_a_strength_and_a_bare_load_is_not(self) -> None:
        study = {
            "url": "https://excalidraw.com/",
            "agent_results": [
                _run(
                    "t2__p2__product",
                    final="https://excalidraw.com/",
                    easy=["The site loaded quickly and presented a clear drawing canvas immediately."],
                ),
                _run(
                    "t1__p1__product",
                    final="https://excalidraw.com/",
                    easy=["The page loaded without issues"],
                ),
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        self.assertEqual(len(insights["strengths"]), 1)
        self.assertIn("drawing canvas", insights["strengths"][0]["claim"])
        self.assertEqual(insights["strengths"][0]["evidence"][0]["agent_id"], "t2__p2__product")

    def test_concrete_quote_cites_the_step_shot(self) -> None:
        study = {
            "url": "https://linear.app/",
            "agent_results": [
                _run(
                    "t1__p1__product",
                    quote="The design is clean and modern, which is a good first impression.",
                )
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        self.assertEqual(len(insights["strengths"]), 1)
        ev = insights["strengths"][0]["evidence"][0]
        self.assertEqual(ev["step"], 0)
        self.assertTrue(ev["screenshot_url"].endswith("bbox_0.png"))

    def test_success_tie_orders_by_steps_then_time_then_friction(self) -> None:
        fast = _run("a", site_key="product", steps=1, final="https://linear.app/")
        slow = _run(
            "b",
            site_key="competitor_1",
            steps=4,
            final="https://asana.com/",
            friction=["Pricing table is hard to compare."],
        )
        study = {
            "url": "https://linear.app/",
            "agent_results": [fast, slow],
            "activity_log": [
                {"kind": "agent_start", "agent_id": "a", "at": "2026-09-25T20:00:00+00:00"},
                {"kind": "agent_done", "agent_id": "a", "at": "2026-09-25T20:00:10+00:00"},
                {"kind": "agent_start", "agent_id": "b", "at": "2026-09-25T20:00:00+00:00"},
                {"kind": "agent_done", "agent_id": "b", "at": "2026-09-25T20:01:00+00:00"},
            ],
        }
        # n>=2 required per site for a tie. Add a twin for each.
        study["agent_results"].append(
            _run("a2", site_key="product", steps=1, final="https://linear.app/")
        )
        study["agent_results"].append(
            _run("b2", site_key="competitor_1", steps=4, final="https://asana.com/")
        )
        insights = build_report_insights(study)
        self.assertIsNotNone(insights["tie_note"])
        self.assertIn("fewer steps", insights["tie_note"])
        self.assertEqual(insights["comparisons"][0]["site_key"], "product")
        self.assertLess(
            insights["comparisons"][0]["median_steps"],
            insights["comparisons"][1]["median_steps"],
        )


    def test_wrong_site_and_captcha_are_run_issues_not_friction(self) -> None:
        wrong = _run(
            "bad-nav",
            friction=["Landed on the wrong website instead of Linear."],
            final="https://asana.com/",
        )
        wrong["site_url"] = "https://linear.app/"
        wrong["final_url"] = "https://asana.com/"
        wrong["trace"][-1]["url"] = "https://asana.com/"
        captcha = _run(
            "captcha-run",
            friction=["A captcha blocked the signup form."],
        )
        real = _run(
            "real",
            steps=3,
            final="https://linear.app/pricing",
            friction=["The pricing table is hard to compare."],
        )
        real["site_url"] = "https://linear.app/"
        real["trace"][0]["url"] = "https://linear.app/"
        real["trace"][1]["action"] = "click — index=3"
        real["trace"][1]["url"] = "https://linear.app/pricing"
        real["trace"][2]["url"] = "https://linear.app/pricing"
        study = {
            "url": "https://linear.app/",
            "agent_results": [wrong, captcha, real],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        kinds = {row["kind"] for row in insights["run_issues"]}
        self.assertIn("navigation", kinds)
        self.assertIn("captcha", kinds)
        self.assertEqual(len(insights["run_issues"]), 2)
        blob = " ".join(w["claim"] for w in insights["weaknesses"]).lower()
        self.assertNotIn("captcha", blob)
        self.assertNotIn("wrong website", blob)
        self.assertTrue(any("pricing" in w["claim"].lower() for w in insights["weaknesses"]))
        self.assertEqual(insights["weaknesses"][0]["evidence"][0]["agent_id"], "real")
        self.assertTrue(insights["run_issues"][0]["screenshot_url"])
        self.assertEqual(insights["product_name"], "Linear")
        self.assertTrue(insights["sites"])

    def test_negative_quote_is_a_weakness_not_a_strength(self) -> None:
        study = {
            "url": "https://linear.app/",
            "agent_results": [
                _run(
                    "t1__p1__product",
                    quote="I couldn't figure out how to create an issue from the landing page.",
                    easy=["The design is clean and modern."],
                    friction=["No clear path to create an issue from the landing page."],
                )
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        strength_blob = " ".join(c["claim"] for c in insights["strengths"]).lower()
        weak_blob = " ".join(c["claim"] for c in insights["weaknesses"]).lower()
        self.assertIn("clean", strength_blob)
        self.assertNotIn("couldn't", strength_blob)
        self.assertIn("issue", weak_blob)
        self.assertTrue(insights["weaknesses"][0]["evidence"][0]["screenshot_url"])

    def test_not_seeing_an_obvious_path_is_a_weakness(self) -> None:
        study = {
            "url": "https://linear.app/",
            "agent_results": [
                _run(
                    "t1__p1__product",
                    quote="I'm not seeing an obvious path to creating an issue right from the start.",
                )
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        strength_blob = " ".join(c["claim"] for c in insights["strengths"]).lower()
        weak_blob = " ".join(c["claim"] for c in insights["weaknesses"]).lower()
        self.assertNotIn("not seeing", strength_blob)
        self.assertIn("not seeing", weak_blob)

    def test_steps_and_time_stay_when_no_task_completes(self) -> None:
        product = _run("a", steps=2, final="https://linear.app/")
        rival = _run("b", site_key="competitor_1", steps=4, final="https://asana.com/")
        study = {
            "url": "https://linear.app/",
            "agent_results": [product, rival],
            "activity_log": [
                {"kind": "agent_start", "agent_id": "a", "at": "2026-09-25T20:00:00+00:00"},
                {"kind": "agent_done", "agent_id": "a", "at": "2026-09-25T20:04:07+00:00"},
                {"kind": "agent_start", "agent_id": "b", "at": "2026-09-25T20:00:00+00:00"},
                {"kind": "agent_done", "agent_id": "b", "at": "2026-09-25T20:02:00+00:00"},
            ],
        }
        insights = build_report_insights(study)
        by_key = {row["site_key"]: row for row in insights["sites"]}
        self.assertEqual(by_key["product"]["success_pct"], 0)
        self.assertEqual(by_key["product"]["ok"], 0)
        self.assertEqual(by_key["product"]["median_steps"], 2)
        self.assertEqual(by_key["product"]["median_time_s"], 247.0)
        self.assertIsNone(by_key["product"]["median_success_steps"])
        cell = insights["by_task"][0]["sites"]["product"]
        self.assertEqual(cell["ok"], 0)
        self.assertEqual(cell["n"], 1)
        self.assertEqual(cell["median_all_steps"], 2)
        self.assertEqual(cell["median_time_s"], 247.0)
        self.assertIsNone(cell["median_steps"])


class ReportWordingTests(unittest.TestCase):
    def test_per_account_workspace_slugs_group_as_one_page(self):
        from mvp.report_insights import _page_shape

        a = _page_shape("https://linear.app/riveralabse671/team/RIV/active")
        b = _page_shape("https://linear.app/riveralabs0764/team/RIV/active")
        self.assertEqual(a, b)
        self.assertEqual(a, "linear.app/\u2026/team/RIV/active")
        self.assertEqual(_page_shape("https://linear.app/pricing"), "linear.app/pricing")
        self.assertEqual(_page_shape("https://www.notion.com/product/ai"), "notion.com/product/ai")

    def test_chain_never_shows_the_signup_email_or_cuts_mid_word(self):
        from mvp.report_insights import _chain_item

        self.assertEqual(_chain_item("signed up as linearz7sug5@uberip.com in 106.3s"), "live sign-up (106s)")
        self.assertEqual(_chain_item("type 'Test issue' into Issue title"), "type 'Test issue'")
        self.assertEqual(_chain_item("click Create issue"), "Create issue")
        long = _chain_item("click Open the very long settings menu for workspace")
        self.assertTrue(long.endswith("\u2026"))
        self.assertNotIn("worksp\u2026", long)

    def test_short_brand_keeps_its_domain(self):
        from mvp.report_insights import _pretty_host

        self.assertEqual(_pretty_host("https://cal.com/"), "Cal.com")
        self.assertEqual(_pretty_host("https://miro.com/"), "Miro")
        self.assertEqual(_pretty_host("https://www.tldraw.com/"), "Tldraw")

    def test_failed_usersim_signup_notes_are_not_product_friction(self):
        from mvp.report_insights import _signup_harness_note

        run = {"signup": {"ok": False, "reason": "email_rejected"}}
        self.assertTrue(_signup_harness_note(run, "Email rejected during signup"))
        self.assertTrue(_signup_harness_note(run, "email_rejected during signup"))
        self.assertTrue(_signup_harness_note(run, "The signup process was not completed, preventing project creation."))
        self.assertFalse(_signup_harness_note(run, "The pricing table hides the per-seat price."))
        self.assertFalse(_signup_harness_note({"signup": {"ok": True}}, "Signup asked for a phone number."))


if __name__ == "__main__":
    unittest.main()
