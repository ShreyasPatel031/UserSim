"""Product head to heads through mvp.pairwise (mocked model; no real calls): evidence, picks, matrix, fallbacks."""
import asyncio
import json
import time

import pytest

from mvp import comparison, paths

P, A, B = "https://kolanut.ai/", "https://alpha.com/", "https://beta.com/"
SITES = {"product": P, "competitor_1": A, "competitor_2": B}
SHOT = {"product": b"P", "competitor_1": b"A", "competitor_2": b"B"}


def _png(site: str, kind: str) -> bytes:
    return SHOT[site] + kind.encode() + b"." * 3000


def _run(task, pid, site, score):
    aid = f"{task[:2]}__{pid}__{site}"
    return {
        "agent_id": aid,
        "task_title": task if site == "product" else f"{task} (vs {SITES[site]})",
        "persona_id": pid,
        "site_key": site,
        "site_url": SITES[site],
        "final_url": SITES[site] + "done",
        "final_dom": f"{site} final page words",
        "trace": [{"step": 0, "action": f"Opened {SITES[site]}"}, {"step": 1, "action": "click Pricing"}],
        "signup": {"ok": site == "product"},
        "comparison_score": {"level": "clear_evidence", "score": score, "friction": 1, "reason": f"{aid} reason",
                             "evidence_step": 1},
    }


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "MVP_RUNS_DIR", tmp_path)
    runs = []
    for pid in ("p1", "p2"):
        for task, scores in (("Find risk", (6, 5, 5)), ("Score health", (5, 6, 4))):
            for site, sc in zip(SITES, scores):
                runs.append(_run(task, pid, site, sc))
    for r in runs:
        d = tmp_path / "s1" / r["agent_id"] / "screenshots"
        d.mkdir(parents=True)
        (d / "bbox_0.png").write_bytes(_png(r["site_key"], "open"))
        (d / "final.png").write_bytes(_png(r["site_key"], "final"))
    return {
        "id": "s1", "url": P, "product_name": "Kolanut", "segment": "customer success platforms",
        "competitor_names": {A: "Alpha", B: "Beta"},
        "personas": [{"id": "p1", "name": "Ana Li", "occupation": "CS lead", "bio": "Runs a 5-person team.", "favors": "product"},
                     {"id": "p2", "name": "Bo Kim", "occupation": "VP CS", "bio": "Enterprise.", "favors": A}],
        "task_specs": [{"prompt": "Find risk"}, {"prompt": "Score health"}],
        "agent_results": runs,
    }


def pair_model(prefs, calls=None, delay=0.0):
    """prefs(persona_name, first_site, second_site) -> (rating_x, rating_y); sites decoded from screenshot bytes."""

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, **kw):
        if delay:
            await asyncio.sleep(delay)
        prompt = contents[0]
        imgs = [c for c in contents if isinstance(c, bytes)]
        site = {v: k for k, v in SHOT.items()}
        first, second = site[imgs[0][:1]], site[imgs[-1][:1]]
        name = prompt.split("You are ")[1].split(",")[0]
        if calls is not None:
            calls.append({"key": key, "contents": contents, "seed": kw.get("seed")})
        rx, ry = prefs(name, first, second)
        return json.dumps({"reasons": f"Product X is {'better' if rx > ry else 'worse'} than Product Y.",
                           "rating_x": rx, "rating_y": ry}), 1, 1

    return call


@pytest.fixture
def text_llm(monkeypatch):
    """The text passes (fallback pick, impressions, fixes, headline) with a fixed reply."""
    seen = []

    async def fake(prompt, timeout=40.0):
        seen.append(prompt)
        if "Pick the ONE product" in prompt:
            letter = prompt.split("Products: ")[1].split("Beta")[0].strip().split()[-1].rstrip(":")
            return {"pick": letter, "why": "Text pick.", "cites": []}
        if "Group them" in prompt:
            return {"fixes": []}
        if "headline" in prompt:
            return {"sentences": [{"text": "Kolanut wins.", "cite": ""}]}
        return {"what_it_is": "x", "clarity": 7}

    monkeypatch.setattr(comparison, "_json_call", fake)
    return seen


def _prefers(winner_for):
    """Each persona prefers ``winner_for[name]`` over anything else, in both presentation orders."""

    def prefs(name, first, second):
        fav = winner_for[name]
        if first == fav:
            return 8, 4
        if second == fav:
            return 4, 8
        return 6, 6

    return prefs


def test_site_evidence_is_opening_plus_finals_and_blind(study):
    rows = [r for r in study["agent_results"] if r["persona_id"] == "p1" and r["site_key"] == "competitor_1"]
    ev, cited = comparison.site_evidence("s1", "competitor_1", rows)
    assert [s[:6] for s in ev.screenshots] == [b"Aopen.", b"Afinal", b"Afinal"]
    assert cited == [r["agent_id"] for r in rows]
    assert ev.summary.startswith("Screenshots in order: the opening page, the last page of job 1, the last page of job 2.")
    assert "Find risk" in ev.summary and "(vs " not in ev.summary and "click Pricing" in ev.summary
    assert "__p1__competitor_1 reason" not in ev.summary and "clear_evidence" not in ev.summary
    assert len(ev.summary) <= 1500
    assert comparison.site_evidence("s1", "competitor_1", rows, max_finals=1)[0].screenshots[1:] == [_png("competitor_1", "final")]


def test_head_to_head_pair_uses_the_shared_judge_both_orders(study):
    calls = []
    call = pair_model(_prefers({"Ana Li": "product", "Bo Kim": "competitor_1"}), calls)
    rows = [r for r in study["agent_results"] if r["persona_id"] == "p1"]
    labels = {"product": "Kolanut", "competitor_1": "Alpha", "competitor_2": "Beta"}
    got = asyncio.run(comparison.head_to_head_pair(study["personas"][0], rows, "competitor_1", labels, study_id="s1",
                                                   ctx={"segment": "cs"}, call=call))
    assert got["winner"] == "product" and got["p_product"] > 0.9 and got["mean_diff"] == 4
    assert sorted(c["key"] for c in calls) == ["judge|ab|0", "judge|ba|0"]
    prompt = calls[0]["contents"][0]
    assert "Product X" in prompt and "Kolanut" not in prompt and "Alpha" not in prompt and "favor" not in prompt
    assert "Find risk; Score health" in prompt
    assert all(c["seed"] is not None for c in calls)
    assert got["why"] == "Kolanut is better than Alpha."
    assert got["ratings"]["ab"] == {"product": 8.0, "competitor": 4.0}


def test_apply_picks_come_from_head_to_head(study, text_llm, monkeypatch):
    monkeypatch.setenv("MVP_COMPARE_PAIRWISE_BUDGET_S", "5")
    call = pair_model(_prefers({"Ana Li": "product", "Bo Kim": "competitor_2"}))
    llm = asyncio.run(comparison.apply_comparison_llm(study, pair_call=call))
    picks = {p["persona_id"]: p for p in llm["picks"]}
    assert picks["p1"]["pick"] == "product" and picks["p1"]["source"] == "pairwise"
    assert picks["p2"]["pick"] == "competitor_2" and picks["p2"]["runner_up"] == "product"
    assert llm["head_to_head_meta"]["done"] == 4 and llm["head_to_head_meta"]["pairwise_picks"] == 2
    assert study["summary"]["comparison_llm"]["headline"]

    comp = comparison.build_comparison(study)
    assert comp["pick_counts"] == {"product": 1, "competitor_1": 0, "competitor_2": 1}
    ana, bo = comp["by_persona"]
    assert ana["pick_source"] == "pairwise" and ana["pick_why"].startswith("Kolanut is better")
    assert bo["head_to_head"]["competitor_2"]["winner"] == "competitor_2"
    m = comp["head_to_head"]["matrix"]
    assert (m["product"]["competitor_1"]["wins"], m["product"]["competitor_1"]["ties"]) == (1, 1)
    assert (m["product"]["competitor_2"]["wins"], m["product"]["competitor_2"]["losses"]) == (1, 1)
    assert m["competitor_2"]["product"]["wins"] == 1 and "competitor_2" not in m["competitor_1"]
    assert comp["head_to_head"]["net_wins"] == {"product": 1, "competitor_1": -1, "competitor_2": 0}
    assert comp["head_to_head"]["summary"].startswith("Head to head: Kolanut beats Alpha for 1 of 2 buyers")
    assert comp["head_to_head"]["ranking"][0] == "product"
    # Existing report sections keep their shape and order.
    for key in ("headline_metric", "wins", "losses", "by_persona", "by_task", "versus", "overall", "ranking"):
        assert key in comp


def test_timeout_falls_back_to_the_text_pick(study, text_llm, monkeypatch):
    monkeypatch.setenv("MVP_COMPARE_PAIRWISE_BUDGET_S", "0.05")
    call = pair_model(_prefers({"Ana Li": "product", "Bo Kim": "product"}), delay=5)
    t0 = time.monotonic()
    llm = asyncio.run(comparison.apply_comparison_llm(study, pair_call=call))
    assert time.monotonic() - t0 < 2
    assert llm["head_to_head"] == [] and llm["head_to_head_meta"]["timed_out"] == 4
    assert {p["pick"] for p in llm["picks"]} == {"competitor_2"}  # the text fallback picks Beta's letter
    assert all("source" not in p for p in llm["picks"])
    comp = comparison.build_comparison(study)
    assert comp["head_to_head"] is None and comp["by_persona"][0]["pick_source"] == "persona"


def test_model_errors_and_ties_fall_back_and_never_raise(study, text_llm, monkeypatch):
    async def broken(key, contents, **kw):
        raise RuntimeError("gemini call failed: 429")

    llm = asyncio.run(comparison.apply_comparison_llm(study, pair_call=broken))
    assert {p["pick"] for p in llm["picks"]} == {"competitor_2"}
    assert all(x["winner"] == "" and x["failed_judgments"] == 2 for x in llm["head_to_head"])

    async def explode(*a, **kw):
        raise ValueError("bad study shape")

    monkeypatch.setattr(comparison, "head_to_head_all", explode)
    llm = asyncio.run(comparison.apply_comparison_llm(study))
    assert "error" in llm["head_to_head_meta"] and len(llm["picks"]) == 2


def test_identical_sites_are_a_tie(study, tmp_path, text_llm):
    """A/A: the rival's screenshots and trace are the product's; any first-slot bias cancels to 0.5."""
    for r in study["agent_results"]:
        if r["site_key"] == "competitor_1":
            d = tmp_path / "s1" / r["agent_id"] / "screenshots"
            (d / "bbox_0.png").write_bytes(_png("product", "open"))
            (d / "final.png").write_bytes(_png("product", "final"))
    call = pair_model(lambda name, first, second: (7, 5))
    rows = [r for r in study["agent_results"] if r["persona_id"] == "p1"]
    got = asyncio.run(comparison.head_to_head_pair(study["personas"][0], rows, "competitor_1",
                                                   {"product": "K", "competitor_1": "A"}, study_id="s1", ctx={}, call=call))
    assert got["p_product"] == 0.5 and got["winner"] == ""


def test_pairwise_can_be_switched_off(study, text_llm, monkeypatch):
    monkeypatch.setenv("MVP_COMPARE_PAIRWISE", "0")
    calls = []
    llm = asyncio.run(comparison.apply_comparison_llm(study, pair_call=pair_model(lambda *a: (8, 2), calls)))
    assert calls == [] and llm["head_to_head_meta"] == {"enabled": False, "pairwise_picks": 0}
    assert len(llm["picks"]) == 2


def test_persona_pick_uses_head_to_head_then_text(study, text_llm):
    rows = [r for r in study["agent_results"] if r["persona_id"] == "p1"]
    labels = {"product": "Kolanut", "competitor_1": "Alpha", "competitor_2": "Beta"}
    got = asyncio.run(comparison.persona_pick(study["personas"][0], rows, labels, study_id="s1",
                                              call=pair_model(_prefers({"Ana Li": "competitor_1"}))))
    assert (got["pick"], got["source"], got["runner_up"]) == ("competitor_1", "pairwise", "product")
    got = asyncio.run(comparison.persona_pick(study["personas"][0], rows, labels, study_id="s1",
                                              call=pair_model(lambda *a: (5, 5))))
    assert got["pick"] == "competitor_2" and "source" not in got


def test_pick_rules():
    labels = {"product": "K", "competitor_1": "A", "competitor_2": "B"}

    def row(comp, p, winner):
        return {"competitor": comp, "p_product": p, "winner": winner, "why": comp, "cites": [comp]}

    both_won = [row("competitor_1", 0.8, "product"), row("competitor_2", 0.6, "product")]
    got = comparison.pick_from_head_to_head(both_won, [], labels)
    assert (got["pick"], got["runner_up"], got["why"]) == ("product", "competitor_2", "competitor_1")
    both_lost = [row("competitor_1", 0.3, "competitor_1"), row("competitor_2", 0.1, "competitor_2")]
    got = comparison.pick_from_head_to_head(both_lost, [], labels)
    assert (got["pick"], got["runner_up"]) == ("competitor_2", "competitor_1")
    assert comparison.pick_from_head_to_head([row("competitor_1", 0.8, "product"), row("competitor_2", 0.5, "")], [], labels) is None
    assert comparison.pick_from_head_to_head([], [], labels) is None


def test_rank_sites_head_to_head_breaks_mean_ties_only():
    def r(score, level="clear_evidence", friction=1):
        return {"comparison_score": {"score": score, "level": level, "friction": friction}}

    rows = {"a": [r(5, "vague_marketing")], "b": [r(5, "clear_evidence")], "c": [r(7)]}
    assert comparison.rank_sites(rows) == [["c"], ["b"], ["a"]]
    assert comparison.rank_sites(rows, {"a": 1, "b": -1, "c": -2}) == [["c"], ["a"], ["b"]]
    assert comparison.rank_sites({"a": [r(5)], "b": [r(5)]}, {"a": 0, "b": 0}) == [["a", "b"]]


def test_pair_persona_comes_from_product_personas_and_stays_blind():
    from mvp.fast_plan import pair_persona

    p = {"id": "p1", "name": "Ana  Li", "occupation": "CS lead", "bio": "Runs a team.", "favors": "product",
         "favors_why": "small team", "goals": ["Decide which product fits"]}
    got = pair_persona(p, ["Find risk", "Score health"])
    assert got == {"name": "Ana Li", "role": "CS lead", "bio": "Runs a team.", "goal": "Find risk; Score health"}
    assert pair_persona(p)["goal"] == "Decide which product fits"
    assert pair_persona({"name": "Bo", "role": "VP"})["role"] == "VP"
