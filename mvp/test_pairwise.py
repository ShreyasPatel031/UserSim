"""mvp.pairwise: mocked model, aggregation, order symmetry, A/A = 50/50, flags."""
import asyncio
import json
import re

from mvp import pairwise
from mvp.pairwise import PairEvidence, PairFlags, aggregate, compare_pair, judge_prompt, merge_diffs

PERSONAS = [{"name": f"P{i} Q{i}", "role": "shopper", "bio": "", "goal": "buy"} for i in range(6)]
CTX = {"company": "Acme", "page_type": "homepage", "industry": "retail", "platform": "website"}
A = PairEvidence(label="a", screenshots=[b"AAA"])
B = PairEvidence(label="b", screenshots=[b"BBB"])


def fake(rate):
    """Model mock: rate(first_bytes, second_bytes, prompt, key) -> (rx, ry); records calls."""
    calls = []

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None):
        calls.append((key, contents, temperature))
        if key.startswith("goal"):
            imgs = [c for c in contents if isinstance(c, bytes)]
            return json.dumps({"goal": "buy now", "differences": [
                {"element": "main button", "x": f"text {imgs[0].decode()}", "y": f"text {imgs[1].decode()}"}]}), 10, 5
        imgs = [c for c in contents if isinstance(c, bytes)]
        rx, ry = rate(imgs[0], imgs[1], contents[0], key)
        return json.dumps({"reasons": "because", "rating_x": rx, "rating_y": ry}), 10, 5

    return call, calls


def run(coro):
    return asyncio.run(coro)


def test_a_preferred_in_both_orders():
    call, calls = fake(lambda x, y, p, k: (8, 4) if x == b"AAA" else (4, 8))
    r = run(compare_pair(A, B, PERSONAS, CTX, PairFlags(), call=call))
    assert r["winner"] == "A" and r["p_a"] > 0.9 and r["votes"] == {"A": 6, "B": 0, "tie": 0}
    assert abs(r["mean_diff"] - 4) < 1e-9 and r["se"] == 0
    assert r["orders"]["ab"]["pick"] == "X" and r["orders"]["ba"]["pick"] == "Y"
    assert len(calls) == 12 and r["rationale"]


def test_pure_position_bias_cancels_to_half():
    call, _ = fake(lambda x, y, p, k: (9, 3))  # always prefers whatever is shown first
    r = run(compare_pair(A, B, PERSONAS, CTX, PairFlags(), call=call))
    assert r["winner"] == "tie" and abs(r["p_a"] - 0.5) < 1e-9 and r["mean_diff"] == 0
    assert r["orders"]["ab"]["pick_ab"] == "A" and r["orders"]["ba"]["pick_ab"] == "B"


def test_order_symmetry_swap_inputs_mirrors_result():
    rate = lambda x, y, p, k: (7, 5) if x == b"AAA" else (6, 6)  # noqa: E731
    call, _ = fake(rate)
    r1 = run(compare_pair(A, B, PERSONAS, CTX, PairFlags(), call=call))
    r2 = run(compare_pair(B, A, PERSONAS, CTX, PairFlags(), call=call))
    assert abs(r1["p_a"] + r2["p_a"] - 1) < 1e-9 and abs(r1["mean_diff"] + r2["mean_diff"]) < 1e-9


def test_aa_same_evidence_is_fifty_fifty():
    call, _ = fake(lambda x, y, p, k: (6, 6))
    r = run(compare_pair(A, A, PERSONAS, CTX, PairFlags(goal_diffs=True, debias=True), call=call))
    assert r["p_a"] == 0.5 and r["winner"] == "tie" and r["votes"]["tie"] == 6


def test_aggregation_soft_vote_mean_and_se():
    js = []
    for k, d in enumerate([2, 2, -1, 0, 3, -2]):
        for o in ("ab", "ba"):
            ra, rb = 5 + d, 5
            rx, ry = (ra, rb) if o == "ab" else (rb, ra)
            js.append({"k": k, "persona": PERSONAS[k]["name"], "order": o, "ok": True, "rating_a": ra, "rating_b": rb,
                       "rating_x": rx, "rating_y": ry, "reasons": ""})
    g = aggregate(js, PERSONAS)
    assert g["votes"] == {"A": 3, "B": 2, "tie": 1}
    assert abs(g["mean_diff"] - 4 / 6) < 1e-9 and g["se"] > 0 and 0.5 < g["p_a"] < 1
    assert g["orders"]["ab"]["n"] == 6


def test_unparseable_judgments_are_dropped():
    async def call(key, contents, **kw):
        return "not json", 1, 1

    r = run(compare_pair(A, B, PERSONAS, CTX, PairFlags(), call=call))
    assert r["failed_judgments"] == 12 and r["winner"] == "tie" and r["p_a"] == 0.5


def test_flags_control_prompt_and_calls():
    seen = []
    call, calls = fake(lambda x, y, p, k: (seen.append(p) or (5, 5)))
    run(compare_pair(A, B, PERSONAS, CTX, PairFlags(), call=call))
    assert not any(k.startswith("goal") for k, _, _ in calls)
    assert all("Version X" in p and "differ only" not in p and "choice overload" not in p for p in seen)
    seen.clear()
    call, calls = fake(lambda x, y, p, k: (seen.append(p) or (5, 5)))
    r = run(compare_pair(A, B, PERSONAS, CTX, PairFlags(goal_diffs=True, debias=True), call=call))
    assert sum(k.startswith("goal") for k, _, _ in calls) == 2
    assert r["goal"] == "buy now" and r["diffs"] == [{"element": "main button", "a": "text AAA", "b": "text BBB"}]
    assert all("differ only" in p and "choice overload" in p and "buy now" in p for p in seen)
    # diffs are relabelled per order: Version X is always the first-shown side
    ab = [p for p in seen if re.search(r"Version X: text AAA", p)]
    ba = [p for p in seen if re.search(r"Version X: text BBB", p)]
    assert len(ab) == 6 and len(ba) == 6


def test_one_order_flag():
    call, calls = fake(lambda x, y, p, k: (7, 3))
    r = run(compare_pair(A, B, PERSONAS, CTX, PairFlags(both_orders=False), call=call))
    assert len(calls) == 6 and r["winner"] == "A" and list(r["orders"]) == ["ab"]


def test_neutral_labels_never_leak_side_names():
    p = judge_prompt(PERSONAS[0], CTX, "", None, "ab", False)
    assert "Version X" in p and "Version Y" in p and " A " not in p and "winner" not in p.lower()


def test_merge_diffs_dedupes_and_interleaves():
    m = merge_diffs([[{"element": "CTA button", "a": "1", "b": "2"}, {"element": "hero image", "a": "", "b": ""}],
                     [{"element": "main CTA button", "a": "1", "b": "2"}, {"element": "price table", "a": "", "b": ""}]])
    assert [d["element"] for d in m] == ["CTA button", "hero image", "price table"]


def test_plan_personas_uses_product_prompt():
    async def call(key, contents, **kw):
        assert key == "planner" and "Invent six realistic visitors" in contents[0] and "Acme" in contents[0]
        return json.dumps({"personas": [{"name": "Ann Lee", "role": "r", "bio": "b", "goal": "g"}] * 6}), 1, 1

    ps = run(pairwise.plan_personas(CTX, call=call))
    assert len(ps) == 6 and len({p["name"] for p in ps}) == 6


# ----------------------------------------------------------------- G-FOCUS (argue_both)

def fake_gfocus(prefers=b"AAA", persona_conf="4"):
    """Evaluator mock: picks whichever position holds ``prefers``; records keys, prompts and json_mode."""
    calls = []

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, json_mode=True):
        calls.append((key, contents, temperature, json_mode))
        imgs = [c for c in contents if isinstance(c, bytes)]
        if key.startswith("v1goal"):
            return "[Goal]\nSell more widgets", 10, 5
        if key.startswith("v1diff"):
            return ("[Design priorities]\n1. x\n[UI areas to focus]\n1. y\n[Key UI differences]\n"
                    f"First UI button {imgs[0].decode()}, Second UI button {imgs[1].decode()}."), 10, 5
        if "reason_" in key:
            return "[Evaluation]\n1. because", 10, 5
        pick = "First" if imgs[-2] == prefers else "Second"  # the judged pair is always the last two images
        return (f"[Importance Ranking]\n1. {pick} 1 - key\n[Conclusion]\nBetter version: **{pick}**\n"
                f"Confidence: {persona_conf}\nKey Rationale:\n* button: better"), 10, 5

    return call, calls


def test_gfocus_single_judge_strict_orders():
    call, calls = fake_gfocus(prefers=b"BBB")
    flags = PairFlags(goal_diffs=True, strict_orders=True, argue_both=True, v1_prompts=True, use_personas=False)
    r = run(compare_pair(A, B, None, CTX, flags, call=call))
    assert r["winner"] == "B" and r["orders"]["ab"]["pick_ab"] == "B" and r["orders"]["ba"]["pick_ab"] == "B"
    assert len(r["judgments"]) == 2 and not r["failed_judgments"]
    keys = [c[0] for c in calls]
    assert not any(k.startswith("planner") for k in keys)  # no personas planned
    assert sum(k.startswith("v1goal") for k in keys) == 2 and sum(k.startswith("v1diff") for k in keys) == 2
    assert sum("reason_" in k for k in keys) == 4 and sum("evaluator" in k for k in keys) == 2
    assert all(c[3] is False for c in calls) and all(c[2] == 1.0 for c in calls)  # text mode, paper temperature
    # strict: order ba's reasoning sees only the diffs extracted in order ba (BBB shown first)
    ba_reason = next(c for c in calls if c[0].startswith("argue|ba") and "reason_first" in c[0])[1][0]
    assert "First UI button BBB, Second UI button AAA." in ba_reason and "Sell more widgets" in ba_reason
    assert "assuming first version was more visually persuasive" in ba_reason


def test_gfocus_personas_confidence_weighted():
    call, calls = fake_gfocus(prefers=b"AAA", persona_conf="5")
    flags = PairFlags(goal_diffs=True, strict_orders=True, argue_both=True, v1_prompts=True, use_personas=True)
    r = run(compare_pair(A, B, PERSONAS, CTX, flags, call=call))
    assert r["winner"] == "A" and r["votes"] == {"A": 6, "B": 0, "tie": 0} and len(r["judgments"]) == 12
    ev = next(c for c in calls if "evaluator" in c[0])[1][0]
    assert "Assume that the following user" in ev and "Confidence: <1-5" in ev


def test_parse_v1_verdict():
    assert pairwise.parse_v1_verdict("[Conclusion]\nBetter version: Second\nKey Rationale:") == ("Second", None)
    assert pairwise.parse_v1_verdict("**Better version:** First\nConfidence: 3") == ("First", 3)
    assert pairwise.parse_v1_verdict("Better version: None")[0] is None


def test_default_flags_unchanged_by_gfocus():
    f = PairFlags()
    assert not f.argue_both and f.name() == "both+ratings"
    assert PairFlags(goal_diffs=True, strict_orders=True).name() == "both+ratings+goal_diffs+strict"


def _png(color_box=None, size=(400, 600)):
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.rectangle((20, 20, 380, 60), fill="navy")
    if color_box:
        d.rectangle(color_box, fill="red")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_diff_regions_finds_the_changed_box():
    r = pairwise.diff_regions(_png(), _png((150, 300, 250, 340)))
    assert len(r) == 1
    x0, y0, x1, y1 = r[0]["box"]
    assert x0 <= 150 / 400 <= x1 and y0 <= 300 / 600 <= y1 and (x1 - x0) * (y1 - y0) < 0.1
    assert pairwise.diff_regions(_png(), _png()) == []


def test_gfocus_extras_in_every_stage_and_order_mapped():
    call, calls = fake_gfocus(prefers=b"AAA")
    ev_a = PairEvidence(label="a", screenshots=[b"AAA"], summary="alpha text")
    ev_b = PairEvidence(label="b", screenshots=[b"BBB"], summary="beta text")
    ctx = dict(CTX, change="Button: Presence", task="start a trial")
    flags = PairFlags(goal_diffs=True, strict_orders=True, argue_both=True, v1_prompts=True, use_personas=False,
                      gf_goal=True, gf_page_text=True, gf_audience=True, gf_change=True)
    assert flags.name().endswith("in_goal+in_page_text+in_audience+in_change")
    r = run(compare_pair(ev_a, ev_b, PERSONAS, ctx, flags, call=call))
    assert r["winner"] == "A"
    for key, contents, _, _ in calls:
        p = contents[0]
        assert "Stated goal of the site operator for this page: start a trial" in p and "Button: Presence" in p
        assert "P0 Q0, shopper: buy" in p
        first = "alpha" if key.split("|")[1] == "ab" else "beta"  # v1goal|ab, argue|ab|single|...
        assert f"Text on the first version (machine-read, may contain errors): {first} text" in p


def test_short_pick_one_call_per_order_and_model_forwarding():
    seen = []

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, json_mode=True, model=None):
        seen.append((key, temperature, json_mode, model, contents[1]))
        # always prefers the screenshot b"AAA", wherever it is shown
        return (f"Better version: {'First' if contents[1] == b'AAA' else 'Second'}\nReason: clearer CTA.", 10, 5)

    flags = PairFlags(short_pick=True, temperature=0.0, max_tokens=200, model="projects/p/locations/us-central1/endpoints/1")
    r = run(compare_pair(A, B, None, CTX, flags, call=call))
    assert r["winner"] == "A" and r["orders"]["ab"]["pick_ab"] == "A" and r["orders"]["ba"]["pick_ab"] == "A"
    assert sorted(k for k, *_ in seen) == ["short|ab", "short|ba"]
    assert all(t == 0.0 and not j and m.endswith("endpoints/1") for _, t, j, m, _ in seen)
    assert r["judgments"][0]["reasons"] == "clearer CTA." and "short_pick" in r["flags"]
    assert pairwise.parse_v1_verdict("Better version: Second")[0] == "Second"


def _gf(**kw):
    return PairFlags(goal_diffs=True, strict_orders=True, argue_both=True, v1_prompts=True, use_personas=False, **kw)


def test_samples_per_order_keys_and_counts_per_stage():
    single = fake_gfocus(prefers=b"AAA")
    run(compare_pair(A, B, None, CTX, _gf(), call=single[0]))
    base_keys = {c[0] for c in single[1]}
    expect = {  # (goal, diff, reason, evaluator) calls per pair for 3 samples per order, both orders
        "all": (6, 6, 12, 6), "argue": (2, 2, 12, 6), "evaluator": (2, 2, 4, 6)}
    for stage, (ng, nd, nr, ne) in expect.items():
        call, calls = fake_gfocus(prefers=b"AAA")
        flags = _gf(samples_per_order=3, sample_stage=stage, argue_temperature=0.0)
        r = run(compare_pair(A, B, None, CTX, flags, call=call))
        keys = [c[0] for c in calls]
        assert len(keys) == len(set(keys)), stage  # every sample has its own cache key
        assert base_keys <= set(keys), stage  # sample 0 = the single-sample run's keys (cache reuse)
        got = (sum(k.startswith("v1goal") for k in keys), sum(k.startswith("v1diff") for k in keys),
               sum("reason_" in k for k in keys), sum("evaluator" in k for k in keys))
        assert got == (ng, nd, nr, ne), (stage, got)
        assert all(c[2] == 0.0 for c in calls)
        assert r["winner"] == "A" and all(j["votes"] == {"First": 3 if j["order"] == "ab" else 0,
                                                        "Second": 0 if j["order"] == "ab" else 3, "failed": 0}
                                          for j in r["judgments"])
        assert f"vote3_{stage}" in r["flags"] and "t0" in r["flags"]


def test_majority_vote_per_order():
    n = {"i": 0}

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, json_mode=True):
        if key.startswith("v1goal"):
            return "[Goal]\ng", 1, 1
        if key.startswith("v1diff"):
            return "[Key UI differences]\nFirst UI a, Second UI b.", 1, 1
        if "reason_" in key:
            return "[Evaluation]\n1. r", 1, 1
        # sample 1 of each order dissents; the others say First
        pick = "Second" if "|evaluator|s1" in key else "First"
        n["i"] += 1
        return f"[Conclusion]\nBetter version: {pick}\nKey Rationale:\n* x", 1, 1

    r = run(compare_pair(A, B, None, CTX, _gf(samples_per_order=3, sample_stage="evaluator"), call=call))
    assert n["i"] == 6
    assert r["orders"]["ab"]["pick_ab"] == "A" and r["orders"]["ba"]["pick_ab"] == "B"  # First wins 2-1 per order
    assert r["judgments"][0]["votes"] == {"First": 2, "Second": 1, "failed": 0}
    one = pairwise.vote_judgment([{"pick": "First", "confidence": None, "reasons": "", "reasons_first": "",
                                   "reasons_second": "", "evaluator": ""},
                                  {"pick": None, "confidence": None, "reasons": "", "reasons_first": "",
                                   "reasons_second": "", "evaluator": ""},
                                  {"pick": "Second", "confidence": None, "reasons": "", "reasons_first": "",
                                   "reasons_second": "", "evaluator": ""}], "ab", None)
    assert one["ok"] and one["pick"] == "tie" and one["rating_x"] == one["rating_y"]
    assert _gf().name() == "both+ratings+goal_diffs+strict+argue_both+v1+single"  # defaults: name unchanged


def test_few_shot_evaluator_only_leave_one_out_balanced():
    pool = [pairwise.FewShotExample(id=i, ctx={"company": f"C{i}", "page_type": "homepage" if i < 4 else "pricing",
                                               "industry": "retail" if i % 2 else "saas"},
                                    win=f"W{i}".encode(), lose=f"L{i}".encode()) for i in range(10)]
    ex = pairwise.pick_examples(pool, {"page_type": "homepage", "industry": "retail"}, 3, exclude=1, seed=0)
    assert len(ex) == 3 and all(e.id != 1 for e, _ in ex)
    assert ex[0][0].id == 3  # the only other homepage+retail example ranks first
    assert all(e.ctx["page_type"] == "homepage" for e, _ in ex)  # then same page type (0, 2)
    assert sorted(p for _, p in ex) in (["First", "First", "Second"], ["First", "Second", "Second"])
    assert ex == pairwise.pick_examples(pool, {"page_type": "homepage", "industry": "retail"}, 3, exclude=1, seed=0)
    four = pairwise.pick_examples(pool, {"page_type": "x"}, 4, exclude=0, seed=5)
    assert sorted(p for _, p in four) == ["First", "First", "Second", "Second"]

    call, calls = fake_gfocus(prefers=b"AAA")
    r = run(compare_pair(A, B, None, CTX, _gf(few_shot_k=3, argue_temperature=0.0), call=call, few_shot_pool=pool,
                         pair_id=1))
    assert r["winner"] == "A" and len(r["few_shot"]) == 3 and "fs3" in r["flags"]
    for key, contents, _, _ in calls:
        imgs = [c for c in contents if isinstance(c, bytes)]
        if "evaluator" in key:
            assert key.endswith("|evaluator|fs3") and len(imgs) == 8  # 3 examples x 2 + the pair
            assert "solved examples" in contents[0] and imgs[-2:] in ([b"AAA", b"BBB"], [b"BBB", b"AAA"])
            for e, pos in ex:
                shown = [e.win, e.lose] if pos == "First" else [e.lose, e.win]
                i = contents.index(shown[0])
                assert contents[i + 2] == shown[1] and f"Better version: {pos}" in contents[i + 3]
        else:
            assert len(imgs) == 2 and "solved examples" not in contents[0]  # other stages unchanged
    # no pool: the flag is inert and keys are the baseline's
    call2, calls2 = fake_gfocus(prefers=b"AAA")
    run(compare_pair(A, B, None, CTX, _gf(few_shot_k=3), call=call2))
    assert all("fs3" not in c[0] for c in calls2)


def test_vanilla_prompt_and_parse():
    seen = []

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, json_mode=True, model=None):
        seen.append((key, model, contents[0]))
        return ("Differences: ...\n**More effective:** " + ("First" if contents[1] == b"AAA" else "Second")), 10, 5

    flags = PairFlags(short_pick=True, vanilla=True, temperature=0.0, max_tokens=2048, model="gpt-4o")
    r = run(compare_pair(A, B, None, CTX, flags, call=call))
    assert r["winner"] == "A" and sorted(k for k, *_ in seen) == ["vanilla|ab", "vanilla|ba"]
    assert all(m == "gpt-4o" and p == pairwise.VANILLA_PROMPT for _, m, p in seen) and "vanilla" in r["flags"]
    pv = pairwise.parse_vanilla
    assert pv("More effective: Second") == "Second" and pv("more effective: <first>") == "First"
    assert pv("More effective: [Second]\n") == "Second" and pv("More effective:\n\nFirst") == "First"
    assert pv("First is better. More effective: Second") == "Second" and pv("Both are fine") is None
    assert pv("More effective: First\n...\nMore effective: Second") == "Second"


def test_graded_parse():
    pg = pairwise.parse_graded
    assert pg("... P(First more effective): 72") == 72.0 and pg("**P(First more effective):** 35%") == 35.0
    assert pg("P(First more effective): <60>") == 60.0 and pg("p(first more effective) = 12.5") == 12.5
    assert pg("P(First more effective): 90\n...\nP(First more effective): 40") == 40.0
    assert pg("More effective: First") is None and pg("P(First more effective): 150") is None and pg("") is None


def _graded_call(p_of, seen=None):
    """Mock: p_of(first_bytes, second_bytes) -> P(First) 0-100."""
    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, json_mode=True, model=None):
        if seen is not None:
            seen.append((key, model, contents[0], json_mode))
        imgs = [c for c in contents if isinstance(c, bytes)]
        v = p_of(imgs[0], imgs[1])
        return (f"Differences: ...\nP(First more effective): {v}" if v is not None else "no idea"), 10, 5
    return call


def test_graded_harness_one_answer_for_both_orders():
    seen = []
    flags = PairFlags(short_pick=True, vanilla=True, graded=True, temperature=0.0, max_tokens=2048, model="gpt-6-luna")
    # prefers AAA mildly in the first slot, and a strong second-position bias: P(First)=60 when AAA first, 20 when second
    r = run(compare_pair(A, B, None, CTX, flags, call=_graded_call(lambda f, s: 60 if f == b"AAA" else 20, seen)))
    # p(A) = mean(0.60, 1 - 0.20) = 0.70 -> A, in BOTH orders, although the second call alone picked "Second" (= A)
    assert abs(r["p_a"] - 0.70) < 1e-9 and r["winner"] == "A"
    assert r["orders"]["ab"]["pick_ab"] == "A" and r["orders"]["ba"]["pick_ab"] == "A"
    assert r["orders"]["ab"]["pick"] == "X" and r["orders"]["ba"]["pick"] == "Y"
    assert r["call_orders"]["ab"]["pick_ab"] == "A" and abs(r["confidence"] - 0.4) < 1e-9 and not r["abstain"]
    assert sorted(k for k, *_ in seen) == ["graded|ab", "graded|ba"]
    assert all(m == "gpt-6-luna" and p == pairwise.graded_prompt() and not j for _, m, p, j in seen)
    assert "Beware" not in pairwise.graded_prompt() and "graded" in r["flags"]


def test_graded_pure_position_bias_is_a_tie_and_abstains():
    flags = PairFlags(short_pick=True, vanilla=True, graded=True)
    r = run(compare_pair(A, B, None, CTX, flags, call=_graded_call(lambda f, s: 35)))  # always "Second, 65%"
    assert r["winner"] == "tie" and r["p_a"] == 0.5 and r["abstain"]
    assert r["orders"]["ab"]["pick_ab"] == "tie" == r["orders"]["ba"]["pick_ab"]


def test_graded_swap_symmetry_one_order_unparsed_and_abstain_margin():
    flags = PairFlags(short_pick=True, vanilla=True, graded=True, abstain_margin=25)
    p = lambda f, s: 70 if f == b"AAA" else 45  # noqa: E731
    r1 = run(compare_pair(A, B, None, CTX, flags, call=_graded_call(p)))
    r2 = run(compare_pair(B, A, None, CTX, flags, call=_graded_call(p)))
    assert abs(r1["p_a"] - 0.625) < 1e-9 and abs(r2["p_a"] - 0.375) < 1e-9 and r1["winner"] == "A" == ("B" if r2["winner"] == "A" else "A")
    assert r1["abstain"] and r1["graded"]["margin"] == 12.5  # 12.5 < 25 points
    # only the (A first) order parses: that order alone decides
    r3 = run(compare_pair(A, B, None, CTX, flags, call=_graded_call(lambda f, s: 90 if f == b"AAA" else None)))
    assert r3["winner"] == "A" and abs(r3["p_a"] - 0.9) < 1e-9 and r3["graded"]["n_parsed"] == 1 and not r3["abstain"]
    assert r3["failed_judgments"] == 1


def test_graded_debias_prompt_and_cache_tag():
    seen = []
    flags = PairFlags(short_pick=True, vanilla=True, graded=True, debias=True)
    run(compare_pair(A, B, None, CTX, flags, call=_graded_call(lambda f, s: 55, seen)))
    assert sorted(k for k, *_ in seen) == ["graded_debias|ab", "graded_debias|ba"]
    assert all("order of the two screenshots is random" in p for _, _, p, _ in seen)
    assert pairwise.short_call_tag(PairFlags(short_pick=True, vanilla=True)) == "vanilla"
    assert pairwise.short_call_tag(PairFlags(short_pick=True)) == "short"
    # plain vanilla output is unchanged by the new fields
    assert "graded" not in PairFlags(short_pick=True, vanilla=True).name()


def test_think_headroom_and_worst_case_reservation(monkeypatch):
    from mvp.e2e_ui_run import think_headroom
    assert think_headroom("gemini-2.5-flash") == 0 and think_headroom("gpt-4o") == 0
    assert think_headroom("gemini-3.8-flash") == 8192 and think_headroom("gpt-6-luna") == 4096
    monkeypatch.setenv("MVP_CLAUDE5_THINK_HEADROOM", "2048")
    assert think_headroom("claude-sonnet-5") == 2048


def test_graded_variants_prompt_scale_and_tags():
    base = pairwise.graded_prompt()
    fm = pairwise.graded_prompt(failure_modes=True)
    s7 = pairwise.graded_prompt(scale=7)
    assert "original was kept" in fm and "Hick" in fm and "original was kept" not in base
    assert "Rating (7 = First): <1-7>" in s7 and "P(First" not in s7 and "Identify the key UI differences" in s7
    pg = pairwise.parse_graded
    assert pg("Rating (7 = First): 7", 7) == 100.0 and pg("Rating (7 = First): 4", 7) == 50.0
    assert pg("**Rating (7 = First):** 1", 7) == 0.0 and pg("Rating (7 = First): 9", 7) is None
    f = PairFlags(short_pick=True, vanilla=True, graded=True, failure_modes=True, graded_scale=7, graded_shots=2)
    assert pairwise.short_call_tag(f) == "graded_fm_s7_fs2" and "scale7" in f.name() and "shots2" in f.name()


def test_graded_few_shot_leave_one_out_balanced_and_clean_rationale():
    from mvp.pairwise import FewShotExample
    pool = [FewShotExample(id=j, ctx=CTX, win=f"W{j}".encode(), lose=f"L{j}".encode(), rationale=f"r{j}") for j in range(4)]
    seen = []
    flags = PairFlags(short_pick=True, vanilla=True, graded=True, graded_shots=2, shot_max_px=None)
    r = run(compare_pair(A, B, None, CTX, flags, call=_graded_call(lambda f, s: 70, seen), few_shot_pool=pool, pair_id=0))
    assert [x["id"] for x in r["few_shot"]] == [1, 2] and [x["answer"] for x in r["few_shot"]] == ["First", "Second"]
    got = []

    async def call(key, contents, **kw):
        got.append(contents)
        return "P(First more effective): 60", 1, 1

    run(compare_pair(A, B, None, CTX, flags, call=call, few_shot_pool=pool, pair_id=0))
    imgs = [c for c in got[0] if isinstance(c, bytes)]
    # example 1 winner First (W1, L1), example 2 winner Second (L2, W2), then the judged pair last
    assert imgs[:4] == [b"W1", b"L1", b"L2", b"W2"] and imgs[4:] in ([b"AAA", b"BBB"], [b"BBB", b"AAA"])
    assert any("the First version won" in c for c in got[0] if isinstance(c, str))
    cr = pairwise._clean_rationale
    assert cr("[{'reason': 'The right version (B) removes clutter.', 'law': {}}]") == "The winning version removes clutter."
    assert cr("[{'reason': 'Variant B has a bigger CTA.'}]") == "The winning version has a bigger CTA."
