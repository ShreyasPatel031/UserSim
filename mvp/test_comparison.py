import unittest

from mvp.comparison import build_comparison, coerce_score, score_prompt
from mvp.fast_plan import compare_personas, compare_tasks, resolve_favors
from mvp.a11y_agent import public_task, website_eval_task


def _run(aid, task, pid, site, url, score, level="clear_evidence"):
    return {
        "agent_id": aid,
        "task_title": task if site == "product" else f"{task} (vs {url})",
        "persona_id": pid,
        "site_key": site,
        "site_url": url,
        "final_url": url + "x",
        "final_screenshot_url": f"/shots/{aid}.png",
        "comparison_score": {"level": level, "score": score, "reason": f"{aid} reason", "evidence_step": 3},
    }


class ScoreTests(unittest.TestCase):
    def test_score_clamped_to_level_band(self):
        s = coerce_score({"level": "wall_or_nothing", "score": 8, "friction": 9, "reason": "demo wall"})
        self.assertEqual(s["score"], 2.0)
        self.assertEqual(s["friction"], 3)
        self.assertIsNone(coerce_score({"level": "great", "score": 5}))

    def test_prompt_uses_trace_and_access(self):
        run = {
            "task_title": "Identify at-risk accounts (vs https://churnzero.com/)",
            "site_url": "https://churnzero.com/",
            "website_eval": {"wall_url": "https://churnzero.com/demo"},
            "trace": [{"step": 1, "action": "click Book a demo", "url": "https://churnzero.com/demo"}],
            "final_url": "https://churnzero.com/features",
            "final_dom": "Health scores",
        }
        text = score_prompt(run, {"name": "Ana", "bio": "CS lead"}, site_label="ChurnZero", is_product=False)
        self.assertIn("Job to be done: Identify at-risk accounts\n", text)
        self.assertIn("step 1: click Book a demo @ https://churnzero.com/demo", text)
        self.assertIn("no self-serve account", text)


class BuildTests(unittest.TestCase):
    def setUp(self):
        P, A, B = "https://kolanut.ai", "https://a.com/", "https://b.com/"
        runs = []
        for pid in ("p1", "p2"):
            runs += [
                _run(f"t1__{pid}__product", "Find risk", pid, "product", P, 8, "in_product"),
                _run(f"t1__{pid}__competitor_1", "Find risk", pid, "competitor_1", A, 3, "vague_marketing"),
                _run(f"t1__{pid}__competitor_2", "Find risk", pid, "competitor_2", B, 5),
                _run(f"t2__{pid}__product", "Score health", pid, "product", P, 2, "wall_or_nothing"),
                _run(f"t2__{pid}__competitor_1", "Score health", pid, "competitor_1", A, 6),
                _run(f"t2__{pid}__competitor_2", "Score health", pid, "competitor_2", B, 1.5, "wall_or_nothing"),
            ]
        runs.append({"agent_id": "lost", "site_key": "product", "comparison_score": {"score": None, "excluded": True}})
        self.study = {
            "url": P,
            "product_name": "Kolanut",
            "competitor_names": {A: "Alpha", B: "Beta"},
            "personas": [{"id": "p1", "name": "Ana", "favors": "product"}, {"id": "p2", "name": "Bo", "favors": A}],
            "task_specs": [{"prompt": "Find risk", "favors": "product"}, {"prompt": "Score health", "favors": A}],
            "agent_results": runs,
        }

    def test_task_winners_ranks_and_versus(self):
        c = build_comparison(self.study)
        self.assertEqual(c["n_scored"], 12)
        t1, t2 = c["by_task"]
        self.assertEqual((t1["winner_label"], t1["product_rank"]), ("Kolanut", 1))
        self.assertEqual((t2["winner_label"], t2["product_rank"]), ("Alpha", 2))
        self.assertEqual(t2["expected_favorite"], "competitor_1")
        self.assertEqual(c["wins"][0]["runner_up"], "Beta")
        self.assertEqual(c["losses"][0]["winner"], "Alpha")
        alpha = next(v for v in c["versus"] if v["label"] == "Alpha")
        self.assertEqual([i["task"] for i in alpha["strengths"]], ["Find risk"])
        self.assertEqual([i["task"] for i in alpha["weaknesses"]], ["Score health"])
        ev = alpha["weaknesses"][0]["competitor_evidence"]
        self.assertEqual((ev["agent_id"], ev["step"], ev["screenshot"]), ("t2__p1__competitor_1", 3, "/shots/t2__p1__competitor_1.png"))

    def test_persona_picks(self):
        c = build_comparison(self.study)
        ana = c["by_persona"][0]
        self.assertEqual(ana["pick_label"], "Kolanut")
        self.assertTrue(ana["product_wins"])
        self.assertEqual(c["by_persona"][1]["expected_favorite"], "competitor_1")

    def test_none_without_scores(self):
        self.assertIsNone(build_comparison({"agent_results": [{"agent_id": "x"}]}))


class PlanTests(unittest.TestCase):
    def test_favors_resolve_to_picked_urls(self):
        comps = ["https://churnzero.com/", "https://www.gainsight.com/"]
        names = {"https://churnzero.com/": "ChurnZero"}
        self.assertEqual(resolve_favors("product", "kolanut.ai", comps), "product")
        self.assertEqual(resolve_favors("https://gainsight.com", "kolanut.ai", comps), comps[1])
        self.assertEqual(resolve_favors("ChurnZero", "kolanut.ai", comps, names), comps[0])
        self.assertEqual(resolve_favors("someone else", "kolanut.ai", comps), "")

    def test_tasks_drop_credentials_and_extra_pricing(self):
        data = {"tasks": [
            {"task": "Connect your CRM data source", "favors": "product"},
            {"task": "Compare plan prices", "favors": "product"},
            {"task": "Find pricing for 20 seats", "favors": "product"},
            {"task": "Identify at-risk accounts", "favors": "https://churnzero.com/"},
        ]}
        tasks = compare_tasks(data, "kolanut.ai", ["https://churnzero.com/"], {})
        self.assertEqual([t["prompt"] for t in tasks], ["Compare plan prices", "Identify at-risk accounts"])
        self.assertEqual(tasks[1]["favors"], "https://churnzero.com/")

    def test_personas_keep_favor_and_why(self):
        data = {"personas": [{"name": "Ana Li", "role": "CSM", "bio": "x", "favors": "product", "why": "small team"}]}
        p = compare_personas(data, "kolanut.ai", [], {})
        self.assertEqual((p[0]["favors"], p[0]["favors_why"]), ("product", "small team"))


class WebsiteEvalTests(unittest.TestCase):
    def test_eval_task_is_public_and_not_pricing(self):
        from mvp.competitor_urls import competitor_task_prompt
        from mvp.a11y_agent import task_kind

        t = website_eval_task(competitor_task_prompt("Identify at-risk customer accounts", "https://churnzero.com/"), "https://churnzero.com/")
        self.assertTrue(t.startswith("Find out from the churnzero.com website whether this product can: Identify at-risk customer accounts."))
        self.assertTrue(public_task(t))
        self.assertNotEqual(task_kind(t), "pricing")


if __name__ == "__main__":
    unittest.main()
