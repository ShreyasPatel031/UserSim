"""Shared page read: first move and the fields the strict e2e reads."""

from __future__ import annotations

import os
import unittest

from capability.gemini_config import extract_json
from mvp.a11y_agent import (
    _READ_JS,
    GATE_FIELDS,
    action_label,
    apply_gate_fields,
    classify_failure,
    failure_breakdown,
    fast_action_model,
    _nodes_for_model,
    account_wall,
    achievable_without_account,
    linear_mock_inert,
    offhost_excalidraw_tool,
    stamp_first_click,
    format_ax,
    goal_visible,
    stamp_published_step,
    note_progress,
    trace_canvas,
    tree_action,
    taskfix_session_cap,
    notes_from_trace,
    pick_action,
    progress_signature,
    study_budget_s,
    would_repeat_action,
)


class A11yAgentTest(unittest.TestCase):
    def test_tree_is_capped_text(self) -> None:
        nodes = [{"i": i, "role": "button", "name": f"Item {i}"} for i in range(200)]
        text = format_ax(nodes)
        self.assertEqual(len(text.splitlines()), 150)
        self.assertTrue(text.startswith("0 button Item 0"))

    def test_first_move_is_a_click_from_the_shared_tree(self) -> None:
        nodes = [
            {"i": 0, "role": "a", "name": "Blog", "x": 10, "y": 10},
            {"i": 1, "role": "button", "name": "Pricing", "x": 40, "y": 20},
        ]
        action = pick_action("Find pricing or the signup path", nodes)
        self.assertEqual(action["act"], "click")
        self.assertEqual(action["name"], "Pricing")
        self.assertTrue(action_label(action).startswith("click "))

    def test_link_target_beats_skip_to_content(self) -> None:
        nodes = [
            {"i": 0, "role": "a", "name": "Skip to content", "href": "https://linear.app/#content", "x": 1, "y": 1},
            {"i": 1, "role": "a", "name": "Changelog", "href": "https://linear.app/changelog", "x": 2, "y": 2},
        ]
        action = pick_action("Open the changelog and see what shipped recently", nodes)
        self.assertEqual(action["href"], "https://linear.app/changelog")
        self.assertFalse(goal_visible("Find pricing", {"url": "https://linear.app/"}))
        self.assertTrue(goal_visible("Find pricing", {"url": "https://linear.app/pricing"}))
        self.assertFalse(goal_visible("Open the changelog", {"url": "https://linear.app/docs"}))
        self.assertTrue(goal_visible("Open the changelog", {"url": "https://linear.app/changelog"}))
        self.assertFalse(goal_visible("Find how to create a new issue", {"url": "https://linear.app/"}))
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {
                    "url": "https://linear.app/",
                    "text": "New issue Inbox My issues issue title description",
                },
            )
        )
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {"url": "https://linear.app/acme/team/ENG/active", "title": "Linear", "text": "Inbox My issues"},
            )
        )
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {"url": "https://linear.app/docs/creating-issues", "title": "Create issues – Linear Docs"},
            )
        )
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {
                    "url": "https://linear.app/docs/creating-issues",
                    "title": "Create issues – Linear Docs",
                    "nodes": [
                        {"role": "textbox", "name": "Issue title"},
                        {"role": "textarea", "name": "Description"},
                    ],
                },
            )
        )
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {"url": "https://linear.app/developers/create-issues-using-linear-new", "title": "Create issues using linear.new"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Find how to create a new issue",
                {
                    "url": "https://linear.app/acme/issue/new",
                    "nodes": [
                        {"role": "textbox", "name": "Issue title"},
                        {"role": "textarea", "name": "Description"},
                    ],
                },
            )
        )
        self.assertFalse(
            goal_visible("Draw a simple rectangle on the canvas", {"url": "https://excalidraw.com/", "canvas": "1x1:dark=0/1;", "drew": True})
        )
        self.assertFalse(
            goal_visible(
                "Draw a simple rectangle on the canvas",
                {"url": "https://excalidraw.com/", "text": "Selected shape actions Stroke width", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=0/900;"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Draw a simple rectangle on the canvas",
                {"url": "https://excalidraw.com/", "text": "Selected shape actions", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=24/900;"},
            )
        )

    def test_gate_fields_are_present(self) -> None:
        sess: dict = {}
        apply_gate_fields(
            sess,
            page_open_at_ts=10.0,
            session_ready_at_ts=9.0,
            page_url="https://linear.app/",
            accessibility_tree="0 button Pricing",
            first_action_at_ts=10.2,
            phase_ms={"page_open_ms": 40, "first_action_ms": 200},
            failed_step=None,
        )
        for key in GATE_FIELDS:
            self.assertIn(key, sess)
        self.assertEqual(sess["page_opened_at_ts"], 10.0)
        self.assertEqual(sess["browser_session_ready_at_ts"], 9.0)
        self.assertEqual(sess["ax_tree"], "0 button Pricing")
        self.assertEqual(sess["phase_ms"]["first_action_ms"], 200)
        self.assertIsNone(sess["failed_step"])
        self.assertEqual(sess["first_action_at_ts"], 10.2)
        same = {}
        apply_gate_fields(
            same,
            page_open_at_ts=10.0,
            session_ready_at_ts=9.0,
            first_action_at_ts=10.0,
        )
        self.assertIsNone(same["first_action_at_ts"])
        self.assertIn("const fakeIssue = /newIssue/.test(cls)", _READ_JS)
        self.assertIn("!header && (fakeIssue || (!href && mock))", _READ_JS)

    def test_action_model_is_the_lite_sibling(self) -> None:
        prev = os.environ.get("MVP_AGENT_ACTION_MODEL")
        browser = os.environ.get("MVP_BROWSER_MODEL")
        os.environ.pop("MVP_AGENT_ACTION_MODEL", None)
        os.environ["MVP_BROWSER_MODEL"] = "gemini-test-flash"
        try:
            self.assertEqual(fast_action_model(), "gemini-test-flash-lite")
            os.environ["MVP_AGENT_ACTION_MODEL"] = "gemini-explicit"
            self.assertEqual(fast_action_model(), "gemini-explicit")
        finally:
            if prev is None:
                os.environ.pop("MVP_AGENT_ACTION_MODEL", None)
            else:
                os.environ["MVP_AGENT_ACTION_MODEL"] = prev
            if browser is None:
                os.environ.pop("MVP_BROWSER_MODEL", None)
            else:
                os.environ["MVP_BROWSER_MODEL"] = browser

    def test_study_budget_is_eight_minutes(self) -> None:
        prev = os.environ.get("MVP_STUDY_BUDGET_S")
        os.environ.pop("MVP_STUDY_BUDGET_S", None)
        try:
            self.assertEqual(study_budget_s(), 480.0)
        finally:
            if prev is None:
                os.environ.pop("MVP_STUDY_BUDGET_S", None)
            else:
                os.environ["MVP_STUDY_BUDGET_S"] = prev

    def test_stops_before_a_third_identical_action(self) -> None:
        read = {"url": "https://linear.app/", "text": "Issue tracking homepage", "canvas": ""}
        trace = [
            {"step": 0, "action": "Opened https://linear.app/", "url": "https://linear.app/", "state_sig": {"text": read["text"], "canvas": ""}},
            {"step": 1, "action": "click New issue", "url": "https://linear.app/", "state_sig": {"text": read["text"], "canvas": ""}},
            {"step": 2, "action": "click New issue", "url": "https://linear.app/", "state_sig": {"text": read["text"], "canvas": ""}},
        ]
        self.assertFalse(would_repeat_action(trace[:2], "click New issue", read))
        self.assertTrue(would_repeat_action(trace, "click New issue", read))
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {"url": "https://linear.app/changelog/new-issue-ui", "title": "Changelog"},
            )
        )
        kept = _nodes_for_model(
            [
                {"i": 0, "role": "button", "name": "New issue", "inert": True},
                {"i": 1, "role": "a", "name": "Pricing", "href": "https://linear.app/pricing"},
                {"i": 2, "role": "a", "name": "Docs", "href": "https://linear.app/docs"},
                {"i": 3, "role": "a", "name": "Log in", "href": "https://linear.app/login"},
            ],
            {"new issue"},
        )
        self.assertEqual([node["name"] for node in kept], ["Pricing", "Docs"])
        easy, friction = notes_from_trace(
            [
                {"step": 0, "action": "Opened https://linear.app/", "url": "https://linear.app/"},
                {"step": 1, "action": "click New issue", "url": "https://linear.app/", "changed": False},
                {
                    "step": 2,
                    "action": "click Pricing",
                    "url": "https://linear.app/pricing",
                    "changed": True,
                    "decision": {"easy": "Pricing was in the header."},
                },
            ]
        )
        self.assertTrue(any("Pricing" in line and "pricing" in line for line in easy))
        self.assertTrue(any("easy" in line and "clear" in line for line in easy))
        self.assertTrue(any("changed nothing" in line for line in friction))
        self.assertTrue(any("unclear" in line for line in friction))
        self.assertFalse(any("free plan is listed" in line for line in easy))

    def test_canvas_flicker_does_not_excuse_a_repeated_click(self) -> None:
        read = {"url": "https://miro.com/index/", "text": "Miro homepage", "canvas": "dark=100"}
        trace = [
            {"step": 0, "action": "Opened https://miro.com/", "url": "https://miro.com/", "state_sig": {"text": "Miro", "canvas": "dark=2888"}},
            {"step": 1, "action": "click Export image", "url": "https://miro.com/index/", "state_sig": {"text": "Miro", "canvas": "dark=1444"}},
            {"step": 2, "action": "click Export image", "url": "https://miro.com/index/", "state_sig": {"text": "Miro", "canvas": "dark=2018"}},
        ]
        self.assertFalse(would_repeat_action(trace[:2], "click Export image", read))
        self.assertTrue(would_repeat_action(trace, "click Export image", read))
        self.assertIsNone(
            tree_action(
                "Find how to export or share the drawing",
                {"url": "https://miro.com/", "nodes": []},
            )
        )
        export = tree_action(
            "Find how to export or share",
            {
                "url": "https://www.tldraw.com/",
                "nodes": [{"i": 3, "role": "menuitem", "name": "Export as PNG", "x": 40, "y": 120}],
            },
        )
        self.assertEqual(export["name"], "Export as PNG")
        self.assertEqual(export["x"], 40)
        rectangle = tree_action(
            "Draw a simple box",
            {
                "url": "https://www.tldraw.com/",
                "nodes": [{"i": 1, "role": "button", "name": "Rectangle", "x": 80, "y": 40}],
            },
        )
        self.assertEqual(rectangle["name"], "Rectangle")
        self.assertEqual(rectangle["act"], "click")
        drag = tree_action(
            "Draw a simple box",
            {
                "url": "https://www.tldraw.com/",
                "text": "canvas",
                "nodes": [{"i": 9, "role": "canvas", "name": "canvas", "x": 400, "y": 300, "w": 800, "h": 600}],
            },
            history=["click Rectangle"],
        )
        self.assertEqual(drag["act"], "drag")
        self.assertIsNone(
            tree_action(
                "Draw a simple box",
                {"url": "https://miro.com/", "text": "Whiteboard", "nodes": []},
            )
        )
        help_click = tree_action(
            "Find help or how to contact support",
            {
                "url": "https://www.etsy.com/",
                "nodes": [{"i": 2, "role": "a", "name": "Help", "href": "https://www.etsy.com/help"}],
            },
        )
        self.assertEqual(help_click["name"], "Help")
        self.assertEqual(
            trace_canvas("dark=10", "dark=400", "https://miro.com/", "Find how to export or share"),
            "dark=10",
        )
        self.assertEqual(
            trace_canvas("dark=0", "dark=20", "https://www.tldraw.com/", "Draw a simple box"),
            "dark=20",
        )
        step = {
            "step": 2,
            "action": "click Pricing",
            "url": "https://linear.app/",
            "observation": "homepage",
            "state_sig": {"text": "homepage", "canvas": "dark=10"},
        }
        stamp_published_step(
            step,
            task="Look for pricing or how to get started",
            read={
                "url": "https://linear.app/pricing",
                "text": "Pricing Free Basic Business",
                "canvas": "dark=800",
                "nodes": [{"i": 0, "role": "a", "name": "Pricing"}],
            },
            screenshot_url="/api/studies/s/agents/a/screenshots/final.png",
        )
        self.assertEqual(step["final_screenshot_url"], "/api/studies/s/agents/a/screenshots/final.png")
        self.assertEqual(step["screenshot_url"], step["final_screenshot_url"])
        self.assertIn("Pricing", step["state_sig"]["text"])
        self.assertEqual(step["state_sig"]["canvas"], "dark=10")
        self.assertTrue(step["goal_visible"])
        self.assertIn("Pricing", step["ax_tree"])
        self.assertFalse(
            goal_visible(
                "Draw a simple box",
                {"url": "https://excalidraw.com/", "text": "Selected shape actions", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=0/900;"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Draw a simple box",
                {"url": "https://excalidraw.com/", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=18/900;"},
            )
        )

    def test_taskfix_cap_is_two_until_the_wide_run(self) -> None:
        owner = os.environ.get("MVP_BB_OWNER")
        wide = os.environ.get("MVP_TASKFIX_WIDE")
        wide_cap = os.environ.get("MVP_TASKFIX_WIDE_CAP")
        try:
            os.environ.pop("MVP_TASKFIX_WIDE", None)
            self.assertEqual(taskfix_session_cap(), 2)
            os.environ["MVP_TASKFIX_WIDE"] = "1"
            self.assertEqual(taskfix_session_cap(), 24)
            os.environ["MVP_TASKFIX_WIDE_CAP"] = "8"
            self.assertEqual(taskfix_session_cap(), 8)
        finally:
            if owner is None:
                os.environ.pop("MVP_BB_OWNER", None)
            else:
                os.environ["MVP_BB_OWNER"] = owner
            if wide is None:
                os.environ.pop("MVP_TASKFIX_WIDE", None)
            else:
                os.environ["MVP_TASKFIX_WIDE"] = wide
            if wide_cap is None:
                os.environ.pop("MVP_TASKFIX_WIDE_CAP", None)
            else:
                os.environ["MVP_TASKFIX_WIDE_CAP"] = wide_cap

    def test_stuck_after_three_identical_signatures(self) -> None:
        sig = progress_signature(
            url="https://linear.app/",
            screenshot_hash="abc",
            text="Issue tracking",
            canvas="canvas:0",
        )
        streak, reason = note_progress(None, sig, 0)
        self.assertEqual(streak, 0)
        self.assertEqual(reason, "")
        streak, reason = note_progress(sig, sig, streak)
        self.assertEqual(streak, 1)
        streak, reason = note_progress(sig, sig, streak)
        self.assertEqual(streak, 2)
        streak, reason = note_progress(sig, sig, streak)
        self.assertEqual(streak, 3)
        self.assertIn("stuck:", reason)
        self.assertIn("screenshot hash", reason)
        moved = progress_signature(
            url="https://linear.app/pricing",
            screenshot_hash="def",
            text="Pricing",
            canvas="canvas:0",
        )
        streak, reason = note_progress(sig, moved, 2)
        self.assertEqual(streak, 0)
        self.assertEqual(reason, "")

    def test_failure_buckets(self) -> None:
        self.assertEqual(classify_failure(stop_reason="stuck: no progress for 3 consecutive steps"), "stuck")
        self.assertEqual(classify_failure(stop_reason="browser dead: target closed"), "our infrastructure")
        self.assertEqual(classify_failure(stop_reason="study budget"), "our infrastructure")
        self.assertEqual(
            classify_failure(error="gemini model timed out"),
            "model timeout",
        )
        self.assertEqual(classify_failure(stop_reason="done", goal_reached=False), "product")
        self.assertEqual(classify_failure(stop_reason="done", goal_reached=True), "")
        self.assertEqual(classify_failure(stop_reason="needs_account"), "")
        table = failure_breakdown(
            [
                {"site_key": "product", "agent_id": "a", "stop_reason": "stuck: no progress for 3 consecutive steps"},
                {"site_key": "product", "agent_id": "b", "stop_reason": "done", "goal_reached": False},
                {"site_key": "competitor", "agent_id": "c", "stop_reason": "browser dead: closed"},
            ]
        )
        self.assertEqual(table["counts"]["stuck"], 1)
        self.assertEqual(table["counts"]["product"], 1)
        self.assertEqual(table["counts"]["our infrastructure"], 1)

    def test_extract_json_keeps_the_first_object(self) -> None:
        self.assertEqual(extract_json('{"act":"click","i":1}\n{"act":"done"}'), {"act": "click", "i": 1})
        self.assertEqual(extract_json('note {"act":"drag"} trailing'), {"act": "drag"})

    def test_linear_hero_hash_is_inert_and_the_header_is_not(self) -> None:
        self.assertIn("Mmx1Wq_", _READ_JS)
        self.assertIn("qM9FAa_", _READ_JS)
        self.assertIn("TZTsQG_", _READ_JS)
        self.assertIn("!header && (fakeIssue || (!href && mock))", _READ_JS)
        self.assertNotIn("[A-Za-z][A-Za-z0-9]{4,}_", _READ_JS)
        self.assertTrue(linear_mock_inert("Mmx1Wq_navItem", ""))
        self.assertTrue(linear_mock_inert("qM9FAa_rowButton", ""))
        self.assertTrue(linear_mock_inert("Mmx1Wq_newIssue", ""))
        self.assertFalse(linear_mock_inert("TZTsQG_link", ""))
        self.assertFalse(linear_mock_inert("TZTsQG_link", "https://linear.app/signup"))
        self.assertFalse(linear_mock_inert("Mmx1Wq_navItem", "https://linear.app/pricing"))
        home = [
            {"role": "button", "name": "Inbox", "href": "", "inert": linear_mock_inert("Mmx1Wq_navItem", "")},
            {"role": "button", "name": "My issues", "href": "", "inert": linear_mock_inert("qM9FAa_row", "")},
            {"role": "a", "name": "Sign up", "href": "https://linear.app/signup", "inert": linear_mock_inert("TZTsQG_link", "https://linear.app/signup")},
        ]
        picked = tree_action("Find how to create a new issue", {"nodes": home})
        self.assertEqual(picked["name"], "Sign up")

    def test_issue_target_is_docs_then_create_issues(self) -> None:
        home = [
            {"role": "button", "name": "Inbox", "href": "", "inert": True},
            {"role": "button", "name": "My issues", "href": "", "inert": True},
            {"role": "a", "name": "Pricing", "href": "https://linear.app/pricing"},
            {"role": "a", "name": "Documentation", "href": "https://linear.app/docs"},
        ]
        docs = [
            {"role": "a", "name": "Skip to content →", "href": "https://linear.app/docs#skip-nav"},
            {"role": "button", "name": "Issues", "href": ""},
            {"role": "a", "name": "Docs", "href": "https://linear.app/docs"},
        ]
        opened = [
            {"role": "a", "name": "Skip to content →", "href": "https://linear.app/docs/creating-issues#skip-nav"},
            {"role": "button", "name": "Issues", "href": ""},
            {"role": "a", "name": "Create issues", "href": "https://linear.app/docs/creating-issues"},
        ]
        self.assertIsNone(tree_action("Find how to create a new issue", {"nodes": home}))
        composer = tree_action(
            "Find how to create a new issue",
            {
                "nodes": [
                    *home,
                    {"role": "button", "name": "New issue", "href": ""},
                    {"role": "a", "name": "Sign up", "href": "https://linear.app/signup"},
                ]
            },
        )
        self.assertEqual(composer["name"], "New issue")
        self.assertNotIn("/docs", composer["href"])
        offered = _nodes_for_model(
            [
                {"role": "a", "name": "Documentation", "href": "https://linear.app/docs"},
                {"role": "button", "name": "New issue", "href": ""},
                {"role": "a", "name": "Sign up", "href": "https://linear.app/signup"},
            ],
            set(),
            "Find how to create a new issue",
        )
        offered_names = [node["name"] for node in offered]
        self.assertEqual(offered_names, ["New issue", "Sign up"])
        self.assertEqual(
            tree_action("Open the documentation for creating issues", {"nodes": home})["name"],
            "Documentation",
        )
        docs_task = "Open the documentation for creating issues"
        self.assertEqual(tree_action(docs_task, {"nodes": docs})["name"], "Issues")
        self.assertEqual(tree_action(docs_task, {"nodes": opened})["href"], "https://linear.app/docs/creating-issues")
        pricing = tree_action(
            "Look for pricing or how to get started",
            {"nodes": home},
        )
        self.assertEqual(pricing["name"], "Pricing")

    def test_first_click_clock_is_after_the_page_is_open(self) -> None:
        sess = {"page_open_at_ts": 50.0, "browser_ready_at_ts": 49.0, "first_action_at_ts": 50.0}
        stamp_first_click(sess)
        self.assertGreater(sess["first_action_at_ts"], sess["page_open_at_ts"])
        self.assertGreater(sess["first_action_at_ts"], sess["browser_ready_at_ts"])
        kept = {"page_open_at_ts": 50.0, "browser_ready_at_ts": 49.0, "first_action_at_ts": 51.0}
        stamp_first_click(kept)
        self.assertEqual(kept["first_action_at_ts"], 51.0)

    def test_account_tasks_stay_account_tasks(self) -> None:
        original = "Create a new issue in your workspace"
        self.assertEqual(achievable_without_account("https://linear.app/", original), original)
        signup = tree_action(
            original,
            {
                "nodes": [
                    {"role": "a", "name": "Documentation", "href": "https://linear.app/docs"},
                    {"role": "a", "name": "Sign up", "href": "https://linear.app/signup"},
                ]
            },
        )
        self.assertEqual(signup["name"], "Sign up")
        self.assertNotIn("/docs", signup["href"])
        kept = _nodes_for_model(
            [
                {"role": "a", "name": "Sign up", "href": "https://linear.app/signup"},
                {"role": "a", "name": "Docs", "href": "https://linear.app/docs"},
            ],
            set(),
            original,
        )
        self.assertEqual([node["name"] for node in kept], ["Sign up"])

    def test_account_wall_returns_the_signup_url(self) -> None:
        self.assertIsNone(
            account_wall(
                {
                    "url": "https://linear.app/",
                    "text": "Plan and build your product Sign up Log in",
                    "nodes": [{"role": "a", "name": "Sign up", "href": "https://linear.app/signup"}],
                }
            )
        )
        login = account_wall(
            {
                "url": "https://linear.app/login",
                "text": "Log in",
                "nodes": [{"role": "a", "name": "Sign up", "href": "https://linear.app/signup"}],
            }
        )
        self.assertEqual(login["signup_url"], "https://linear.app/signup")
        self.assertEqual(login["reason"], "login_url")
        form = account_wall(
            {
                "url": "https://linear.app/",
                "text": "Welcome",
                "nodes": [
                    {"role": "input", "type": "email", "name": "Email"},
                    {"role": "input", "type": "password", "name": "Password"},
                    {"role": "a", "name": "Create account", "href": "https://linear.app/signup"},
                ],
            }
        )
        self.assertEqual(form["reason"], "email_password")
        self.assertEqual(form["signup_url"], "https://linear.app/signup")
        modal = account_wall(
            {
                "url": "https://excalidraw.com/",
                "text": "Sign up to continue and save this drawing",
                "nodes": [{"role": "a", "name": "Sign up", "href": "https://plus.excalidraw.com/sign-up"}],
            }
        )
        self.assertEqual(modal["reason"], "modal")
        self.assertIn("sign-up", modal["signup_url"])

    def test_strength_and_weakness_cite_a_step_past_the_first_screen(self) -> None:
        from mvp.a11y_agent import publish_final_shot
        from mvp.e2e2_gates import _qualifying_claims
        from mvp.report_insights import build_report_insights

        easy, friction = notes_from_trace(
            [
                {"step": 0, "action": "Opened https://linear.app/", "url": "https://linear.app/"},
                {
                    "step": 1,
                    "action": "click New issue",
                    "url": "https://linear.app/",
                    "changed": False,
                },
                {
                    "step": 2,
                    "action": "click Pricing",
                    "url": "https://linear.app/pricing",
                    "changed": True,
                },
            ]
        )
        shot = "/api/studies/s/agents/a/screenshots/final.png"
        trace = [
            {
                "step": 0,
                "action": "Opened https://linear.app/",
                "url": "https://linear.app/",
                "state_sig": {"text": "homepage " * 12, "canvas": ""},
            },
            {
                "step": 1,
                "action": "click New issue",
                "url": "https://linear.app/",
                "changed": False,
                "state_sig": {"text": "homepage " * 12, "canvas": ""},
            },
            {
                "step": 2,
                "action": "click Pricing",
                "url": "https://linear.app/pricing",
                "changed": True,
                "accessibility_tree": "0 link Pricing plans",
                "state_sig": {"text": "pricing plans " * 12, "canvas": ""},
            },
        ]
        publish_final_shot(trace, shot)
        self.assertEqual(trace[2]["screenshot_url"], shot)
        self.assertFalse(trace[0].get("screenshot_url"))
        run = {
            "agent_id": "a",
            "site_key": "product",
            "site_url": "https://linear.app/",
            "task_title": "Look for pricing or how to get started",
            "final_url": "https://linear.app/pricing",
            "final_screenshot_url": shot,
            "final_screenshot": shot,
            "what_was_easy": easy,
            "friction_points": friction,
            "num_steps": 3,
            "trace": trace,
        }
        study = {"id": "s", "url": "https://linear.app/", "agent_results": [run]}
        insights = build_report_insights(study)
        self.assertGreaterEqual(len(insights["strengths"]), 1)
        self.assertGreaterEqual(len(insights["weaknesses"]), 1)
        runs_by_id = {"a": run}

        def loads(url: str) -> bool:
            return str(url).endswith("final.png")

        self.assertGreaterEqual(
            len(_qualifying_claims(insights["strengths"], runs_by_id, study, loads)),
            1,
        )
        self.assertGreaterEqual(
            len(_qualifying_claims(insights["weaknesses"], runs_by_id, study, loads)),
            1,
        )


class ClockAndCdpTests(unittest.TestCase):
    def test_offhost_excalidraw_shortcut_is_blocked(self) -> None:
        self.assertFalse(
            offhost_excalidraw_tool(
                {"act": "click", "name": "Rectangle"},
                "https://excalidraw.com/",
            )
        )
        self.assertTrue(
            offhost_excalidraw_tool(
                {"act": "click", "name": "Export image"},
                "https://linear.app/",
            )
        )
        self.assertTrue(
            offhost_excalidraw_tool({"act": "drag", "name": "canvas"}, "https://miro.com/")
        )

    def test_first_published_click_sets_ttfv_from_url_submit(self) -> None:
        from mvp.study import StudyState, note_first_published_action

        study = StudyState(id="s", url="https://linear.app", segment="pm")
        study.url_submit_at_ts = 1_000.0
        note_first_published_action(study, "t1__p1__product", "Opened https://linear.app")
        self.assertIsNone(study.time_to_first_value_s)
        note_first_published_action(study, "t1__p2__product", "click Pricing")
        self.assertEqual(study.time_to_first_value_agent, "t1__p2__product")
        self.assertGreater(study.time_to_first_value_s, 0)
        first = study.time_to_first_value_s
        note_first_published_action(study, "t1__p1__product", "scroll down")
        self.assertEqual(study.time_to_first_value_s, first)
        self.assertEqual(study.time_to_first_value_agent, "t1__p2__product")

    def test_parallel_cdp_threads_do_not_share_one_pipe(self) -> None:
        import asyncio

        from playwright.sync_api import sync_playwright

        from mvp.a11y_agent import _CDP_POOL, _attach_cdp

        self.assertGreaterEqual(_CDP_POOL._max_workers, 24)
        browsers = []
        pw = sync_playwright().start()
        try:
            for i in range(4):
                browser = pw.chromium.launch(
                    headless=True,
                    args=[f"--remote-debugging-port={9333 + i}"],
                )
                page = browser.new_page()
                page.set_content(f"<title>t{i}</title><a href='https://example.com'>Go</a>")
                browsers.append(browser)
            # Chromium prints the ws url on stderr; read it from the browser.
            endpoints = []
            for i, browser in enumerate(browsers):
                # The debugging port serves /json/version.
                import urllib.request

                with urllib.request.urlopen(
                    f"http://127.0.0.1:{9333 + i}/json/version", timeout=5
                ) as resp:
                    import json

                    endpoints.append(json.loads(resp.read())["webSocketDebuggerUrl"])

            async def _all() -> list[str]:
                async def _one(endpoint: str, url: str) -> str:
                    browser, page, created, opened = await _attach_cdp(endpoint, url)
                    try:
                        title = await page.title()
                        loc = page.get_by_role("link", name="Go", exact=True)
                        self.assertGreater(await loc.count(), 0)
                        self.assertGreaterEqual(opened, created)
                        return str(title)
                    finally:
                        await browser._session.close()

                return await asyncio.gather(
                    *[
                        _one(
                            endpoints[i],
                            "data:text/html,<title>n%d</title><a href='https://example.com/'>Go</a>"
                            % i,
                        )
                        for i in range(4)
                    ]
                )

            def _run() -> list[str]:
                return asyncio.run(_all())

            t0 = __import__("time").perf_counter()
            # The agent loop may already own a loop in-process. Run this one aside.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                titles = pool.submit(_run).result()
            elapsed = __import__("time").perf_counter() - t0
        finally:
            for browser in browsers:
                try:
                    browser.close()
                except Exception:
                    pass
            pw.stop()
        self.assertEqual(sorted(titles), ["n0", "n1", "n2", "n3"])
        # Four serial connects would be several seconds. Parallel stays well under that.
        self.assertLess(elapsed, 12)


class FinalPngOnCancelTest(unittest.TestCase):
    def test_capture_returns_url_only_when_upload_succeeds(self) -> None:
        import asyncio
        from pathlib import Path
        from unittest.mock import patch

        from mvp.a11y_agent import _capture_final_png

        class Page:
            async def wait_for_load_state(self, *_a: object, **_k: object) -> None:
                return None

            async def screenshot(self, path: str, **_k: object) -> None:
                Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 3000)

            async def evaluate(self, *_a: object, **_k: object) -> None:
                return None

        async def _run(uploaded: bool) -> str:
            with patch("mvp.study.upload_saved_final", return_value=uploaded):
                url, _ms = await _capture_final_png(Page(), "study-x", "agent-y", "pricing")
            return url

        def _go(uploaded: bool) -> str:
            return asyncio.run(_run(uploaded))

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            kept = pool.submit(_go, True).result()
            dropped = pool.submit(_go, False).result()
        self.assertEqual(
            kept, "/api/studies/study-x/agents/agent-y/screenshots/final.png"
        )
        self.assertEqual(dropped, "")


class ForceLocalFleetTests(unittest.TestCase):
    def test_force_local_browser_skips_gcp_fleet(self) -> None:
        from mvp.study import _fleet_preferred

        old = os.environ.get("MVP_FORCE_LOCAL_BROWSER")
        os.environ["MVP_FORCE_LOCAL_BROWSER"] = "1"
        try:
            self.assertFalse(_fleet_preferred())
        finally:
            if old is None:
                os.environ.pop("MVP_FORCE_LOCAL_BROWSER", None)
            else:
                os.environ["MVP_FORCE_LOCAL_BROWSER"] = old


if __name__ == "__main__":
    unittest.main()
