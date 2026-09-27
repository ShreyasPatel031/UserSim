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

    def test_tie_rule_level_then_friction_then_tie(self):
        from mvp.comparison import rank_sites

        def r(score, level, friction):
            return {"comparison_score": {"score": score, "level": level, "friction": friction}}

        # Same mean: the higher best level wins.
        tiers = rank_sites({"a": [r(4, "clear_evidence", 1)], "b": [r(4, "vague_marketing", 1)]})
        self.assertEqual(tiers, [["a"], ["b"]])
        # Same mean and level: lower friction wins.
        tiers = rank_sites({"a": [r(4, "clear_evidence", 2)], "b": [r(4, "clear_evidence", 0)]})
        self.assertEqual(tiers, [["b"], ["a"]])
        # Still equal: a tie, never an arbitrary order.
        tiers = rank_sites({"a": [r(1, "wall_or_nothing", 3)], "b": [r(1, "wall_or_nothing", 3)]})
        self.assertEqual(tiers, [["a", "b"]])

    def test_task_tie_has_no_winner(self):
        for r in self.study["agent_results"]:
            if r.get("agent_id", "").startswith("t1__") and r["site_key"] in {"product", "competitor_2"}:
                r["comparison_score"] = {"level": "clear_evidence", "score": 5, "friction": 1, "reason": "x"}
        c = build_comparison(self.study)
        t1 = c["by_task"][0]
        self.assertEqual(t1["winner"], "")
        self.assertEqual(t1["tied"], ["product", "competitor_2"])
        self.assertEqual(t1["winner_label"], "Tie: Kolanut = Beta")
        self.assertEqual(t1["product_rank"], 1)

    def test_persona_llm_pick_is_headline(self):
        self.study["summary"] = {"comparison_llm": {"picks": [
            {"persona_id": "p1", "pick": "competitor_1", "why": "better scores", "cites": ["t2__p1__competitor_1"]},
        ]}}
        c = build_comparison(self.study)
        self.assertEqual(c["by_persona"][0]["pick"], "competitor_1")
        self.assertEqual(c["by_persona"][0]["pick_source"], "persona")
        # p2 has no persona pick: its scores decide (Kolanut 5.0 vs Alpha 4.5).
        self.assertEqual(c["by_persona"][1]["pick_source"], "scores")
        self.assertEqual(c["pick_counts"], {"product": 1, "competitor_1": 1, "competitor_2": 0})
        self.assertEqual(c["headline_metric"], "Kolanut: 1 of 2 buyers, Alpha: 1, Beta: 0")

    def test_wins_and_losses_rows(self):
        c = build_comparison(self.study)
        self.assertEqual(c["wins"][0]["task"], "Find risk")
        self.assertEqual(c["wins"][0]["competitor_label"], "Alpha")
        self.assertEqual(c["losses"][0]["task"], "Score health")
        self.assertIn("quote", c["losses"][0]["competitor_evidence"])

    def test_refs_stripped_from_text(self):
        from mvp.comparison import _strip_refs

        self.assertEqual(_strip_refs("Kolanut leads in drafting (R2)."), "Kolanut leads in drafting.")
        self.assertEqual(_strip_refs("It worked (R1, R3) and failed [R4]."), "It worked and failed.")

    def test_refs_resolve(self):
        from mvp.comparison import _refs, _resolve

        refs = _refs([{"agent_id": "t1__p1__product"}, {"agent_id": "t2__p1__competitor_1"}])
        self.assertEqual(_resolve("R2", refs), "t2__p1__competitor_1")
        self.assertEqual(_resolve("[r1]", refs), "t1__p1__product")
        self.assertEqual(_resolve("t1", refs), "")

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


def test_infra_stop_runs_are_left_out():
    from mvp.comparison import infra_stop

    assert infra_stop({"stop_reason": "session ended", "num_steps": 0}).startswith("agent never ran")
    assert "cut short" in infra_stop({"stop_reason": "study budget", "num_steps": 7})
    assert infra_stop({"stop_reason": "done", "num_steps": 4}) == ""
    assert "cut short" in infra_stop({"stop_reason": "model returned no action", "num_steps": 1})


def test_persona_pick_is_blind_and_maps_letters_back(monkeypatch):
    import asyncio

    from mvp import comparison

    seen = {}

    async def fake(prompt, timeout=40.0):
        seen["prompt"] = prompt
        # Pick whichever letter ChurnZero got.
        letter = prompt.split("Products: ")[1].split("ChurnZero")[0].strip().split()[-1].rstrip(":")
        return {"pick": letter, "why": f"Product {letter} did it.", "cites": ["R1"]}

    monkeypatch.setattr(comparison, "_json_call", fake)
    rows = [
        {"agent_id": "t1__p1__product", "site_key": "product", "persona_id": "p1", "task_prompt": "Do x",
         "comparison_score": {"level": "in_product", "score": 5, "friction": 1, "reason": "ok"}},
        {"agent_id": "t1__p1__competitor_1", "site_key": "competitor_1", "persona_id": "p1", "task_prompt": "Do x",
         "comparison_score": {"level": "clear_evidence", "score": 6, "friction": 0, "reason": "ok"}},
    ]
    got = asyncio.run(comparison.persona_pick_text({"id": "p1", "name": "P"}, rows, {"product": "Kolanut", "competitor_1": "ChurnZero"}))
    assert got["pick"] == "competitor_1"
    assert "product under study" not in seen["prompt"]
    assert "product: Kolanut" not in seen["prompt"]
    assert "ChurnZero did it" in got["why"]
    assert got["against_scores"] is False
