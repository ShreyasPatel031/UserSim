"""Strict e2e gates. Saved studies must fail. A synthetic study must pass."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from mvp.e2e2_gates import (
    FAILURE_INFRASTRUCTURE,
    FAILURE_MODEL_TIMEOUT,
    FAILURE_PRODUCT,
    FAILURE_STUCK,
    beyond_first_screen,
    evaluate_strict_gates,
    is_browserbase_or_concurrency_loss,
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
        self.assertTrue(_gate(result, "vision_yes")["pass"])
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


if __name__ == "__main__":
    unittest.main()
