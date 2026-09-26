"""Strict e2e gates. Saved studies must fail. A synthetic study must pass."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from mvp.e2e2_gates import (
    FAILURE_INFRASTRUCTURE,
    FAILURE_MODEL_TIMEOUT,
    FAILURE_NO_FIRST_ACTION,
    FAILURE_PRODUCT,
    FAILURE_STUCK,
    assess_infrastructure_abort,
    assess_page_opened,
    assess_stuck_abort,
    assess_time_to_first_action,
    beyond_first_screen,
    build_early_failures,
    evaluate_strict_gates,
    has_click_type_scroll,
    is_browserbase_or_concurrency_loss,
    is_click_type_scroll,
    render_markdown,
    stuck_no_progress,
)
from mvp.report_insights import build_report_insights

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e2e2_studies"
REPORT_HTML = (Path(__file__).resolve().parent / "static" / "report.html").read_text()

LINEAR = "e59af231-7118-4776-9305-0978ce8d7c25"
EXCALIDRAW = "1e1def83-4281-4536-b93d-2caa7a8a63ea"
MDN = "11afd7e2-41fa-49b5-8b42-14a455255103"


def _load(study_id: str) -> dict:
    return json.loads((FIXTURES / f"{study_id}.json").read_text())


def _startup_that_used_to_pass() -> dict:
    """The old harness passed on these numbers alone."""
    return {
        "yeses": 24,
        "elapsed_s": 280,
        "missing_shot": 0,
        "max_creation_to_shot_s": 0.05,
        "slow_agents": 0,
        "vision_nos": 0,
        "expected": 24,
        "time_to_first_value_s": 8.0,
        "time_to_first_value_agent": "t1__p1__product",
        "total_time_s": 280.0,
        "report_ready": True,
    }


def _loads(url: str) -> bool:
    return bool(str(url or "").strip())


def _evaluate(study: dict, **kwargs) -> dict:
    return evaluate_strict_gates(
        study,
        startup=kwargs.pop("startup", _startup_that_used_to_pass()),
        screenshot_loads=kwargs.pop("screenshot_loads", _loads),
        report_html=kwargs.pop("report_html", REPORT_HTML),
        report_url=kwargs.pop(
            "report_url",
            f"http://127.0.0.1:3000/report?study={study.get('id')}",
        ),
        **kwargs,
    )


def _gate(result: dict, gate_id: str) -> dict:
    for gate in result["gates"]:
        if gate["id"] == gate_id:
            return gate
    raise AssertionError(gate_id)


def _run(
    agent_id: str,
    *,
    site_key: str = "product",
    site_url: str = "https://linear.app/",
    final: str | None = None,
    task: str = "Find how to create a new issue",
    success: bool = False,
    browser_error: str = "",
) -> dict:
    start = site_url
    end = final if final is not None else (start if not success else "https://linear.app/team/issue/new")
    trace = [
        {
            "step": 0,
            "action": "click — index=2",
            "url": start,
            "screenshot_url": f"/api/studies/s/agents/{agent_id}/screenshots/bbox_0.png",
        }
    ]
    if success:
        trace.append(
            {
                "step": 3,
                "action": "click — index=11",
                "url": end,
                "screenshot_url": f"/api/studies/s/agents/{agent_id}/screenshots/step_3.png",
            }
        )
    row = {
        "agent_id": agent_id,
        "persona_id": agent_id.split("__")[1],
        "persona_name": "Pat",
        "task_id": agent_id.split("__")[0],
        "task_title": task,
        "task_prompt": task,
        "site_key": site_key,
        "site_label": "Linear" if site_key == "product" else site_key,
        "site_url": start,
        "final_url": end,
        "created_at_ts": 1_000.0,
        "page_open_at_ts": 1_000.04,
        "ax_tree": "navigation main landmark button Create issue",
        "num_steps": 4 if success else 1,
        "trace": trace,
        "what_was_easy": (
            ["The issue form is easy to find from the sidebar."] if success and site_key == "product" else []
        ),
        "friction_points": (
            ["The save button is hard to find after the title is filled in."]
            if success and site_key == "product"
            else []
        ),
        "quote": "",
    }
    if browser_error:
        row["browser_error"] = browser_error
        row["mode"] = "browser_partial"
        row["final_url"] = ""
        row["trace"] = []
        row["num_steps"] = 0
        row["what_was_easy"] = []
        row["friction_points"] = []
    return row


def _matrix(product_flags: list[bool], *, bb_at: int | None = None) -> dict:
    """4 personas × 2 tasks × 3 sites. product_flags length 8, True = goal reached."""
    tasks = ["Find how to create a new issue", "Look for pricing or how to get started"]
    runs = []
    i = 0
    for task_i, task in enumerate(tasks, start=1):
        for persona_i in range(1, 5):
            aid = f"t{task_i}__p{persona_i}__product"
            if bb_at is not None and i == bb_at:
                runs.append(
                    _run(aid, task=task, browser_error="Browserbase create concurrency cap busy")
                )
            else:
                runs.append(_run(aid, task=task, success=product_flags[i]))
            i += 1
            for comp_i, url in ((1, "https://asana.com/"), (2, "https://trello.com/")):
                runs.append(
                    _run(
                        f"t{task_i}__p{persona_i}__competitor_{comp_i}",
                        site_key=f"competitor_{comp_i}",
                        site_url=url,
                        final=url,
                        task=task,
                        success=False,
                    )
                )
    study = {
        "id": "synthetic-pass",
        "url": "https://linear.app/",
        "status": "complete",
        "segment": "Product managers comparing issue trackers",
        "competitors": ["https://asana.com/", "https://trello.com/"],
        "personas": [{"id": f"p{n}", "name": f"P{n}"} for n in range(1, 5)],
        "tasks": [{"id": f"t{n}", "title": title, "prompt": title} for n, title in enumerate(tasks, start=1)],
        "agent_results": runs,
        "activity_log": [],
    }
    study["summary"] = {"headline": "Synthetic", "insights": build_report_insights(study)}
    return study


class SavedStudyTests(unittest.TestCase):
    def test_linear_startup_vision_yes_is_not_task_success(self) -> None:
        study = _load(LINEAR)
        result = _evaluate(study, vision_goal={})
        self.assertFalse(result["pass"])
        product = _gate(result, "product_task_completion")
        self.assertFalse(product["pass"])
        self.assertEqual(result["product_task_success"]["value"], "0/8")
        self.assertFalse(_gate(result, "product_strength")["pass"])
        self.assertFalse(_gate(result, "top_weakness_not_homepage_only")["pass"])
        self.assertTrue(_gate(result, "agent_count")["pass"])
        ids = [gate["id"] for gate in result["gates"]]
        self.assertNotIn("vision_yes", ids)
        self.assertNotIn("first_screenshot", ids)
        self.assertNotIn("first_screenshot_latency", ids)
        self.assertIn("page_opened", ids)
        self.assertFalse(_gate(result, "page_opened")["pass"])
        self.assertTrue(_gate(result, "study_budget")["pass"])
        self.assertTrue(_gate(result, "infra_honesty")["pass"])
        # A judge YES is the completion signal. The report checks still fail.
        vision = {
            str(r.get("agent_id")): {
                "goal_reached": True,
                "still_on_opening_screen": False,
                "reason": "The final screenshot shows the requested issue form.",
            }
            for r in study["agent_results"]
            if r.get("site_key") == "product"
        }
        judged = _evaluate(study, vision_goal=vision)
        self.assertEqual(judged["product_task_success"]["value"], "8/8")
        self.assertTrue(_gate(judged, "product_task_completion")["pass"])
        self.assertFalse(judged["pass"])
        self.assertFalse(_gate(judged, "product_strength")["pass"])

    def test_excalidraw_keeps_opening_frame_runs_in_the_denominator(self) -> None:
        study = _load(EXCALIDRAW)
        result = _evaluate(study, vision_goal={})
        self.assertFalse(result["pass"])
        self.assertEqual(result["product_task_success"]["n"], 8)
        self.assertEqual(result["product_task_success"]["value"], "0/8")
        excluded = [
            r["agent_id"]
            for r in study["agent_results"]
            if r.get("site_key") == "product" and r.get("exclude_from_insights")
        ]
        self.assertEqual(len(excluded), 2)
        self.assertTrue(all(aid in result["product_task_success"]["first_screen_ids"] for aid in excluded))
        self.assertFalse(_gate(result, "product_strength")["pass"])
        self.assertFalse(_gate(result, "product_weakness")["pass"])
        self.assertFalse(_gate(result, "top_weakness_not_homepage_only")["pass"])
        self.assertTrue(_gate(result, "first_screen_not_excluded")["pass"])
        self.assertLessEqual(
            len(result["run_issues"]),
            6,
        )
        by_id = {row["agent_id"]: row for row in result["failures"]["failed_runs"]}
        for aid in excluded:
            self.assertEqual(by_id[aid]["type"], FAILURE_INFRASTRUCTURE)
            self.assertIn("judge_reason", by_id[aid])
            self.assertTrue(by_id[aid]["trace_link"])

    def test_mdn_fails_the_half_completion_bar(self) -> None:
        study = _load(MDN)
        movers = []
        for run in study["agent_results"]:
            if run.get("site_key") != "product":
                continue
            start = run.get("site_url") or study["url"]
            if beyond_first_screen(run, start):
                movers.append(run["agent_id"])
        self.assertEqual(movers, ["t1__p1__product", "t2__p4__product"])
        result = _evaluate(study, vision_goal={aid: True for aid in movers})
        self.assertFalse(result["pass"])
        self.assertEqual(result["product_task_success"]["value"], "2/8")
        self.assertFalse(_gate(result, "product_task_completion")["pass"])
        self.assertFalse(_gate(result, "product_strength")["pass"])
        # A real weakness exists, but two of eight is not a pass.
        self.assertTrue(_gate(result, "product_weakness")["pass"])


class SyntheticGateTests(unittest.TestCase):
    def test_half_of_product_runs_with_a_real_report_passes(self) -> None:
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        vision = {
            r["agent_id"]: True
            for r, flag in zip(
                [r for r in study["agent_results"] if r["site_key"] == "product"],
                flags,
            )
            if flag
        }
        result = _evaluate(study, vision_goal=vision)
        if not result["pass"]:
            self.fail("\n".join(result["fail_reasons"]))
        self.assertEqual(result["product_task_success"]["value"], "4/8")
        self.assertEqual(len(result["competitor_task_success"]), 2)
        text = render_markdown(result, study_id=study["id"], product_url=study["url"])
        self.assertIn("| ", text)
        for gate in result["gates"]:
            self.assertIn(f"`{gate['id']}`", text)
            self.assertIn("PASS" if gate["pass"] else "FAIL", text)
        self.assertIn("pass: true", text)
        self.assertIn("`study_budget`", text)
        failed_ids = {row["agent_id"] for row in result["failures"]["failed_runs"]}
        self.assertTrue(failed_ids.isdisjoint(result["product_task_success"]["success_ids"]))
        product_fails = [
            row
            for row in result["failures"]["failed_runs"]
            if row["site_key"] == "product"
        ]
        self.assertEqual(len(product_fails), 4)
        self.assertTrue(all(row["type"] == FAILURE_PRODUCT for row in product_fails))
        sample = product_fails[0]
        for key in ("type", "judge_reason", "trace_link", "final_screenshot"):
            self.assertTrue(sample.get(key), key)

    def test_browserbase_loss_counts_against_the_product_rate(self) -> None:
        flags = [True, True, True, True, False, False, False, False]
        study = _matrix(flags, bb_at=7)
        bb = [r for r in study["agent_results"] if is_browserbase_or_concurrency_loss(r)]
        self.assertEqual(len(bb), 1)
        self.assertIn(bb[0]["agent_id"], {row["agent_id"] for row in study["summary"]["insights"]["run_issues"]})
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and not is_browserbase_or_concurrency_loss(r) and r["num_steps"] == 4
        }
        result = _evaluate(study, vision_goal=vision)
        self.assertEqual(result["product_task_success"]["value"], "4/8")
        self.assertEqual(result["browserbase_concurrency_losses"], [bb[0]["agent_id"]])
        self.assertTrue(_gate(result, "infra_honesty")["pass"])
        # Silent exclusion: the report drops the loss and the gate must fail.
        study["summary"]["insights"]["run_issues"] = []
        hidden = _evaluate(study, vision_goal=vision)
        self.assertFalse(_gate(hidden, "infra_honesty")["pass"])
        self.assertEqual(hidden["product_task_success"]["value"], "4/8")
        self.assertFalse(hidden["pass"])

    def test_run_issue_cap_is_25_percent(self) -> None:
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        issues = []
        for run in study["agent_results"]:
            if run["site_key"] == "product":
                continue
            if len(issues) >= 7:
                break
            issues.append(
                {
                    "kind": "navigation",
                    "agent_id": run["agent_id"],
                    "reason": f"Agent never reached {run['site_url']}",
                }
            )
        study["summary"]["insights"]["run_issues"] = issues
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        over = _evaluate(study, vision_goal=vision)
        self.assertFalse(_gate(over, "run_issue_rate")["pass"])
        self.assertIn("7/24", str(_gate(over, "run_issue_rate")["value"]))
        study["summary"]["insights"]["run_issues"] = issues[:6]
        at_cap = _evaluate(study, vision_goal=vision)
        self.assertTrue(_gate(at_cap, "run_issue_rate")["pass"])
        self.assertIn("6/24", str(_gate(at_cap, "run_issue_rate")["value"]))

    def test_agent_summary_cannot_pass_without_a_judge_yes(self) -> None:
        study = _matrix([True, False, False, False, False, False, False, False])
        product = [r for r in study["agent_results"] if r["site_key"] == "product"]
        for run in product:
            run["what_was_easy"] = ["I created the issue and saved it."]
            run["friction_points"] = []
            run["quote"] = "Done, the new issue is filed."
        result = _evaluate(study, vision_goal={})
        self.assertEqual(result["product_task_success"]["value"], "0/8")
        self.assertFalse(_gate(result, "product_task_completion")["pass"])
        only = product[0]["agent_id"]
        yes = _evaluate(
            study,
            vision_goal={
                only: {
                    "goal_reached": True,
                    "still_on_opening_screen": False,
                    "reason": "The issue form is open.",
                }
            },
        )
        self.assertEqual(yes["product_task_success"]["success_ids"], [only])

    def test_stuck_is_steps_not_a_timeout(self) -> None:
        sig = {"text": " ".join(["homepage"] * 30), "canvas": ""}
        run = _run("t1__p1__product", success=False)
        run["trace"] = [
            {
                "step": step,
                "action": "click — index=1",
                "url": "https://linear.app/",
                "state_sig": dict(sig),
                "screenshot_url": f"/api/studies/s/agents/t1__p1__product/screenshots/step_{step}.png",
            }
            for step in (0, 1, 2)
        ]
        self.assertTrue(stuck_no_progress(run))
        opening = _run("t1__p2__product", success=False)
        self.assertFalse(stuck_no_progress(opening))
        study = _matrix([False] * 8)
        study["agent_results"] = [
            run if r["agent_id"] == "t1__p1__product" else r for r in study["agent_results"]
        ]
        timed = next(r for r in study["agent_results"] if r["agent_id"] == "t1__p2__product")
        timed["last_action"] = "Timed out — browser closed"
        timed["what_was_easy"] = ["I finished the task before the clock."]
        result = _evaluate(
            study,
            vision_goal={
                "t1__p1__product": {
                    "goal_reached": False,
                    "still_on_opening_screen": True,
                    "reason": "Still the Linear marketing homepage.",
                },
                "t1__p2__product": {
                    "goal_reached": True,
                    "still_on_opening_screen": False,
                    "reason": "This YES must not override a model timeout.",
                },
            },
        )
        by_id = {row["agent_id"]: row for row in result["failures"]["failed_runs"]}
        self.assertEqual(by_id["t1__p1__product"]["type"], FAILURE_STUCK)
        self.assertEqual(
            by_id["t1__p1__product"]["judge_reason"],
            "Still the Linear marketing homepage.",
        )
        self.assertIn("step=2", by_id["t1__p1__product"]["trace_link"])
        self.assertTrue(by_id["t1__p1__product"]["final_screenshot"].endswith("step_2.png"))
        self.assertEqual(by_id["t1__p2__product"]["type"], FAILURE_MODEL_TIMEOUT)
        self.assertNotIn("t1__p1__product", result["product_task_success"]["success_ids"])
        self.assertNotIn("t1__p2__product", result["product_task_success"]["success_ids"])
        self.assertEqual(result["product_task_success"]["value"], "0/8")

    def test_study_budget_is_eight_minutes(self) -> None:
        study = _matrix([True, True, False, False, True, True, False, False])
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        under = _evaluate(study, vision_goal=vision, startup={**_startup_that_used_to_pass(), "elapsed_s": 408})
        self.assertTrue(_gate(under, "study_budget")["pass"])
        self.assertIn("480", _gate(under, "study_budget")["threshold"])
        self.assertIn("408", _gate(under, "study_budget")["threshold"])
        over = _evaluate(study, vision_goal=vision, startup={**_startup_that_used_to_pass(), "elapsed_s": 481})
        self.assertFalse(_gate(over, "study_budget")["pass"])
        self.assertFalse(over["pass"])
        self.assertNotIn("elapsed", {g["id"] for g in over["gates"]})


def _opened(agent_id: str, *, error: str = "", phase: str = "Live browser agents") -> dict:
    return {
        "agent_id": agent_id,
        "site_key": "product",
        "task_prompt": "Find how to create a new issue",
        "phase": phase,
        "last_action": "Opened https://linear.app/",
        "error": error,
        "browser_error": error,
        "final_url": "https://linear.app/",
        "trace": [
            {
                "step": 0,
                "action": "Opened https://linear.app/",
                "url": "https://linear.app/",
                "screenshot_url": f"/api/studies/s/agents/{agent_id}/screenshots/bbox_0.png",
            }
        ],
    }


def _acting(agent_id: str) -> dict:
    run = _opened(agent_id)
    run["trace"].append(
        {
            "step": 1,
            "action": "click — index=4",
            "url": "https://linear.app/login",
            "screenshot_url": f"/api/studies/s/agents/{agent_id}/screenshots/step_1.png",
        }
    )
    run["last_action"] = "click — index=4"
    return run


def _stamp_open(run: dict, opened: float = 1_000.0) -> dict:
    """Stamp the page-open time the study JSON records. A screenshot is not a start."""
    run["page_open_at_ts"] = opened
    return run


class EarlyFailureTests(unittest.TestCase):
    def test_idle_agent_aborts_when_the_max_is_blown_and_a_fast_fleet_passes(self) -> None:
        shot = 1_000.0
        silent = [_stamp_open(_opened(f"a{i}"), shot) for i in range(24)]
        inside = assess_time_to_first_action(silent, now=shot + 10.0)
        self.assertFalse(inside["abort"])
        self.assertFalse(inside["ok"])
        blown = assess_time_to_first_action(silent, now=shot + 10.01)
        self.assertTrue(blown["abort"])
        self.assertEqual(blown["type"], FAILURE_NO_FIRST_ACTION)
        self.assertEqual(blown["acted"], 0)
        self.assertEqual(blown["agents"], 24)
        self.assertIn("FAIL time_to_first_action", blown["reason"])
        self.assertIn("phase=Live browser agents", blown["reason"])
        self.assertEqual(blown["ids"], [f"a{i}" for i in range(24)])
        # A longer --first-action-s only delays the abort. It does not loosen 5s/10s.
        held = assess_time_to_first_action(silent, now=shot + 11.0, abort_after_s=60)
        self.assertFalse(held["abort"])
        self.assertFalse(held["ok"])
        late_flag = assess_time_to_first_action(silent, now=shot + 60.01, abort_after_s=60)
        self.assertTrue(late_flag["abort"])
        seen: dict[str, float] = {}
        fast = [_stamp_open(_acting(f"a{i}"), shot) for i in range(24)]
        for i, run in enumerate(fast):
            seen[run["agent_id"]] = shot + 2.0 + (i % 3) * 0.5
        healthy = assess_time_to_first_action(
            fast, now=shot + 30.0, action_seen_at=seen
        )
        self.assertFalse(healthy["abort"])
        self.assertTrue(healthy["ok"])
        self.assertLessEqual(healthy["median_s"], 5)
        self.assertLessEqual(healthy["max_s"], 10)
        self.assertEqual(healthy["n"], 24)
        # The live-UI stamp stays on the poll that first showed the action.
        again = assess_time_to_first_action(
            fast, now=shot + 40.0, action_seen_at=seen
        )
        self.assertEqual(again["median_s"], healthy["median_s"])
        self.assertEqual(again["max_s"], healthy["max_s"])
        slow_seen = dict(seen)
        slow_seen["a0"] = shot + 10.5
        slow = assess_time_to_first_action(
            fast, now=shot + 30.0, action_seen_at=slow_seen
        )
        self.assertFalse(slow["abort"])
        self.assertFalse(slow["ok"])
        self.assertGreater(slow["max_s"], 10)
        at_limit = [_stamp_open(_acting(f"b{i}"), shot) for i in range(24)]
        limit_seen = {
            run["agent_id"]: shot + (5.0 if i < 23 else 10.0)
            for i, run in enumerate(at_limit)
        }
        exact = assess_time_to_first_action(
            at_limit, now=shot + 12.0, action_seen_at=limit_seen
        )
        self.assertEqual(exact["median_s"], 5.0)
        self.assertEqual(exact["max_s"], 10.0)
        self.assertTrue(exact["ok"])
        over = dict(limit_seen)
        over[at_limit[-1]["agent_id"]] = shot + 10.01
        past = assess_time_to_first_action(
            at_limit, now=shot + 12.0, action_seen_at=over
        )
        self.assertFalse(past["ok"])
        self.assertGreater(past["max_s"], 10)
        short = fast[:23]
        self.assertFalse(
            assess_time_to_first_action(
                short, now=shot + 4.0, action_seen_at=seen
            )["ok"]
        )
        doc = build_early_failures(
            {"id": "s", "url": "https://linear.app/"},
            silent,
            blown,
            base_url="http://127.0.0.1:3000",
        )
        self.assertEqual(len(doc["failed_runs"]), 24)
        self.assertTrue(all(row["type"] == FAILURE_NO_FIRST_ACTION for row in doc["failed_runs"]))
        self.assertTrue(doc["failed_runs"][0]["trace_link"])
        self.assertTrue(doc["failed_runs"][0]["final_screenshot"])
        self.assertIn("phase=", doc["failed_runs"][0]["judge_reason"])

    def test_only_click_type_and_scroll_count_as_the_first_action(self) -> None:
        self.assertTrue(is_click_type_scroll("click — index=4"))
        self.assertTrue(is_click_type_scroll("input — index=54"))
        self.assertTrue(is_click_type_scroll("type — text=hello"))
        self.assertTrue(is_click_type_scroll("scroll"))
        self.assertTrue(is_click_type_scroll("send_keys — keys=Enter"))
        self.assertFalse(is_click_type_scroll("Opened https://linear.app/"))
        self.assertFalse(is_click_type_scroll("Opening https://linear.app/"))
        self.assertFalse(is_click_type_scroll("go_to_url — url=https://linear.app/"))
        self.assertFalse(is_click_type_scroll("search — query=pricing"))
        self.assertFalse(is_click_type_scroll("Page is open. Starting the simulated user…"))
        opened = _stamp_open(_opened("searcher"))
        opened["trace"].append(
            {"step": 1, "action": "search — query=pricing", "url": "https://linear.app/"}
        )
        self.assertFalse(has_click_type_scroll(opened))
        typed = _stamp_open(_opened("typer"))
        typed["last_action"] = "input — index=3"
        self.assertTrue(has_click_type_scroll(typed))

    def test_saved_studies_blow_the_action_max(self) -> None:
        for study_id in (LINEAR, EXCALIDRAW, MDN):
            study = _load(study_id)
            runs = study["agent_results"]
            for run in runs:
                run["page_open_at_ts"] = 1_000.0
            check = assess_time_to_first_action(runs, now=1_011.0, action_seen_at={})
            self.assertTrue(check["abort"], study_id)
            self.assertEqual(check["agents"], 24)
            self.assertLess(check["n"], 24, study_id)
            self.assertGreater(len(check["ids"]), 0, study_id)

    def test_cdp_and_session_drops_abort_as_infrastructure(self) -> None:
        runs = [_opened(f"a{i}") for i in range(24)]
        runs[0]["browser_error"] = "Root CDP client not initialized"
        cdp = assess_infrastructure_abort(runs)
        self.assertTrue(cdp["abort"])
        self.assertEqual(cdp["type"], FAILURE_INFRASTRUCTURE)
        self.assertIn("Root CDP client not initialized", cdp["reason"])
        self.assertIn("a0", cdp["reason"])
        drops = [_opened(f"a{i}") for i in range(24)]
        for run in drops[:6]:
            run["browser_error"] = "Browserbase session closed"
        self.assertFalse(assess_infrastructure_abort(drops)["abort"])
        drops[6]["browser_error"] = "Browserbase session dropped"
        over = assess_infrastructure_abort(drops)
        self.assertTrue(over["abort"])
        self.assertEqual(over["drop_n"], 7)
        self.assertIn("over 25%", over["reason"])

    def test_same_action_three_times_is_stuck_and_aborts(self) -> None:
        run = _opened("loop")
        run["trace"] = [
            {
                "step": step,
                "action": "click — index=726",
                "url": "https://linear.app/",
                "state_sig": {"text": " ".join(["homepage"] * 30), "canvas": ""},
            }
            for step in (1, 2, 3)
        ]
        self.assertTrue(stuck_no_progress(run))
        varied = _opened("moves")
        varied["trace"] = [
            {
                "step": step,
                "action": action,
                "url": "https://linear.app/",
                "state_sig": {"text": " ".join(["homepage"] * 30), "canvas": ""},
            }
            for step, action in ((1, "click — index=1"), (2, "click — index=2"), (3, "scroll"))
        ]
        self.assertFalse(stuck_no_progress(varied))
        decision = assess_stuck_abort([run, varied])
        self.assertTrue(decision["abort"])
        self.assertEqual(decision["type"], FAILURE_STUCK)
        self.assertEqual(decision["ids"], ["loop"])

    def test_first_action_gate_fails_the_study(self) -> None:
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        startup = _startup_that_used_to_pass()
        startup["first_action_check"] = {
            "measured": True,
            "ok": False,
            "acted": 0,
            "agents": 24,
            "since_s": 60,
            "detail": "a0 phase=Live error= last_action=Opened https://linear.app/",
        }
        result = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertFalse(_gate(result, "first_action")["pass"])
        self.assertFalse(result["pass"])
        self.assertIn("0/24", str(_gate(result, "first_action")["value"]))

    def test_time_to_first_action_gate_shows_value_and_threshold(self) -> None:
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        startup = _startup_that_used_to_pass()
        startup["time_to_first_action_check"] = {
            "measured": True,
            "ok": True,
            "median_s": 2.5,
            "max_s": 4.0,
            "n": 24,
            "agents": 24,
        }
        passed = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertTrue(_gate(passed, "time_to_first_action")["pass"])
        self.assertTrue(passed["pass"])
        self.assertIn("2.5s", str(_gate(passed, "time_to_first_action")["value"]))
        self.assertIn("4.0s", str(_gate(passed, "time_to_first_action")["value"]))
        self.assertIn(
            "median <= 5s and max <= 10s at 24 agents",
            _gate(passed, "time_to_first_action")["threshold"],
        )
        text = render_markdown(passed, study_id=study["id"], product_url=study["url"])
        self.assertIn("`time_to_first_action`", text)
        self.assertIn("median=2.5s max=4.0s n=24/24", text)
        startup["time_to_first_action_check"] = {
            "measured": True,
            "ok": False,
            "median_s": 6.0,
            "max_s": 11.0,
            "n": 24,
            "agents": 24,
            "detail": "max blown",
        }
        failed = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertFalse(_gate(failed, "time_to_first_action")["pass"])
        self.assertFalse(failed["pass"])
        self.assertIn("6.0s", str(_gate(failed, "time_to_first_action")["value"]))
        self.assertIn("11.0s", str(_gate(failed, "time_to_first_action")["value"]))

    def test_screenshot_stamp_does_not_start_the_action_clock(self) -> None:
        shot = 1_000.0
        silent = [_opened(f"a{i}") for i in range(24)]
        for run in silent:
            run["first_screenshot_at_ts"] = shot
        untouched = assess_time_to_first_action(silent, now=shot + 30.0)
        self.assertFalse(untouched["abort"])
        self.assertEqual(untouched["n"], 0)
        self.assertEqual(untouched["per_agent"][0]["start"], "")
        ready = [_opened(f"b{i}") for i in range(24)]
        for run in ready:
            run["browser_ready_at_ts"] = shot
            run["first_screenshot_at_ts"] = shot + 50
        blown = assess_time_to_first_action(ready, now=shot + 10.01)
        self.assertTrue(blown["abort"])
        self.assertEqual(blown["per_agent"][0]["start"], "browser_ready_at_ts")
        opened = _acting("c0")
        opened["browser_ready_at_ts"] = shot
        opened["page_open_at_ts"] = shot + 1.0
        opened["first_screenshot_at_ts"] = shot
        seen = {"c0": shot + 3.0}
        check = assess_time_to_first_action(
            [opened], now=shot + 12.0, action_seen_at=seen, expected=1
        )
        self.assertEqual(check["per_agent"][0]["start"], "page_open_at_ts")
        self.assertEqual(check["per_agent"][0]["latency_s"], 2.0)
        self.assertTrue(check["ok"])


def _opened_page(agent_id: str, **extra) -> dict:
    run = {
        "agent_id": agent_id,
        "site_url": "https://www.linear.app/en-US/",
        "created_at_ts": 1_000.0,
        "page_open_at_ts": 1_000.04,
        "ax_tree": "button Create issue",
        "trace": [
            {
                "step": 0,
                "action": "Opened https://linear.app/",
                "url": "https://linear.app/",
            }
        ],
    }
    run.update(extra)
    return run


class PageOpenedTests(unittest.TestCase):
    def test_right_site_within_5s_passes_without_a_screenshot(self) -> None:
        runs = [_opened_page(f"a{i}") for i in range(24)]
        check = assess_page_opened(runs)
        self.assertTrue(check["ok"])
        self.assertFalse(check["abort"])
        self.assertEqual(check["opened"], 24)
        ready = []
        for i in range(24):
            run = _opened_page(f"b{i}")
            del run["page_open_at_ts"]
            run["browser_ready_at_ts"] = 1_002.0
            ready.append(run)
        session = assess_page_opened(ready)
        self.assertTrue(session["ok"], session["reason"])
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        for run in study["agent_results"]:
            for step in run.get("trace") or []:
                step.pop("screenshot_url", None)
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        result = _evaluate(study, vision_goal=vision)
        self.assertTrue(_gate(result, "page_opened")["pass"], _gate(result, "page_opened"))
        self.assertIn("URL host matches", _gate(result, "page_opened")["threshold"])

    def test_wrong_host_empty_ax_and_slow_open_fail(self) -> None:
        wrong = assess_page_opened(
            [
                _opened_page(
                    "bad",
                    trace=[{"step": 0, "url": "https://example.com/", "action": "Opened"}],
                )
            ],
            now=1_001.0,
        )
        self.assertTrue(wrong["abort"])
        self.assertEqual(wrong["wrong_site"], 1)
        empty = _opened_page("ax")
        empty["ax_tree"] = ""
        missing = assess_page_opened([empty])
        self.assertTrue(missing["abort"])
        self.assertEqual(missing["missing_ax"], 1)
        slow = assess_page_opened([_opened_page("slow", page_open_at_ts=1_006.0)])
        self.assertTrue(slow["abort"])
        self.assertEqual(slow["slow"], 1)
        waiting_run = _opened_page("wait")
        del waiting_run["page_open_at_ts"]
        waiting_run["ax_tree"] = ""
        waiting = assess_page_opened([waiting_run], now=1_001.0)
        self.assertFalse(waiting["abort"])
        self.assertFalse(waiting["ok"])
        shot_only = _opened_page("shot")
        del shot_only["page_open_at_ts"]
        shot_only["first_screenshot_at_ts"] = 1_000.04
        finished = assess_page_opened([shot_only])
        self.assertTrue(finished["abort"])
        self.assertEqual(finished["opened"], 0)

    def test_strength_and_weakness_cite_step_ax_and_the_final_screenshot(self) -> None:
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        for run in study["agent_results"]:
            if run.get("num_steps") == 4:
                run["final_screenshot_url"] = f"/final/{run['agent_id']}.png"
            for step in run.get("trace") or []:
                step.pop("screenshot_url", None)
                step["ax_tree"] = "textbox Title button Save"
        insights = study["summary"]["insights"]
        for bucket in ("strengths", "weaknesses"):
            for claim in insights.get(bucket) or []:
                for ev in claim.get("evidence") or []:
                    ev.pop("screenshot_url", None)
                    ev["final_screenshot"] = f"/final/{ev['agent_id']}.png"
                    ev["ax_tree"] = "textbox Title button Save"
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        result = _evaluate(study, vision_goal=vision)
        self.assertTrue(_gate(result, "product_strength")["pass"], result["fail_reasons"])
        self.assertTrue(_gate(result, "product_weakness")["pass"], result["fail_reasons"])
        self.assertIn("AX or URL", _gate(result, "product_strength")["threshold"])
        self.assertIn("final screenshot", _gate(result, "product_weakness")["threshold"])
        self.assertTrue(result["pass"], result["fail_reasons"])
        for claim in insights["strengths"] + insights["weaknesses"]:
            for ev in claim.get("evidence") or []:
                ev.pop("final_screenshot", None)
                ev.pop("ax_tree", None)
                ev.pop("step_url", None)
                ev.pop("url", None)
        for run in study["agent_results"]:
            run.pop("final_screenshot_url", None)
            for step in run.get("trace") or []:
                step.pop("ax_tree", None)
        bare = _evaluate(study, vision_goal=vision)
        self.assertFalse(_gate(bare, "product_strength")["pass"])
        self.assertFalse(_gate(bare, "product_weakness")["pass"])


class HeadlineMetricTests(unittest.TestCase):
    def _passing(self) -> tuple[dict, dict]:
        flags = [True, True, False, False, True, True, False, False]
        study = _matrix(flags)
        vision = {
            r["agent_id"]: True
            for r in study["agent_results"]
            if r["site_key"] == "product" and r["num_steps"] == 4
        }
        return study, vision

    def test_headline_gates_lead_the_summary(self) -> None:
        study, vision = self._passing()
        startup = _startup_that_used_to_pass()
        startup["time_to_first_value_s"] = 10.0
        startup["total_time_s"] = 480.0
        startup["report_ready"] = True
        result = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertEqual(
            [gate["id"] for gate in result["gates"][:2]],
            ["time_to_first_value", "total_time"],
        )
        self.assertIn("time_to_first_action", [gate["id"] for gate in result["gates"]])
        self.assertTrue(_gate(result, "time_to_first_value")["pass"])
        self.assertIn("10.0s", str(_gate(result, "time_to_first_value")["value"]))
        self.assertIn("<= 10s", _gate(result, "time_to_first_value")["threshold"])
        self.assertIn("URL submit", _gate(result, "time_to_first_value")["threshold"])
        self.assertTrue(_gate(result, "total_time")["pass"])
        self.assertIn("480.0s", str(_gate(result, "total_time")["value"]))
        self.assertIn("<= 480s", _gate(result, "total_time")["threshold"])
        self.assertIn("report is ready", _gate(result, "total_time")["threshold"])
        self.assertTrue(result["pass"])
        text = render_markdown(result, study_id=study["id"], product_url=study["url"])
        self.assertLess(text.index("## Headline"), text.index("| Gate |"))
        self.assertLess(text.index("`time_to_first_value`"), text.index("`total_time`"))
        self.assertLess(text.index("`total_time`"), text.index("`full_matrix`"))
        self.assertIn("`time_to_first_action`", text)
        self.assertIn("median <= 5s and max <= 10s at 24 agents", text)

    def test_first_value_over_10s_and_total_over_budget_fail(self) -> None:
        study, vision = self._passing()
        startup = _startup_that_used_to_pass()
        startup["time_to_first_value_s"] = 10.01
        late = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertFalse(_gate(late, "time_to_first_value")["pass"])
        self.assertFalse(late["pass"])
        self.assertTrue(_gate(late, "time_to_first_action")["pass"])
        startup["time_to_first_value_s"] = 9.0
        startup["total_time_s"] = 481.0
        over = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertTrue(_gate(over, "time_to_first_value")["pass"])
        self.assertFalse(_gate(over, "total_time")["pass"])
        self.assertFalse(over["pass"])
        startup["total_time_s"] = 100.0
        startup["report_ready"] = False
        not_ready = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertFalse(_gate(not_ready, "total_time")["pass"])
        self.assertIn("report not ready", str(_gate(not_ready, "total_time")["value"]))

    def test_missing_headline_clocks_fail(self) -> None:
        study, vision = self._passing()
        startup = _startup_that_used_to_pass()
        startup["time_to_first_value_s"] = None
        startup["total_time_s"] = None
        startup["report_ready"] = False
        result = _evaluate(study, vision_goal=vision, startup=startup)
        self.assertEqual(_gate(result, "time_to_first_value")["value"], "not recorded")
        self.assertFalse(_gate(result, "time_to_first_value")["pass"])
        self.assertEqual(_gate(result, "total_time")["value"], "not ready")
        self.assertFalse(_gate(result, "total_time")["pass"])
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
