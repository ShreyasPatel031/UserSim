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
        pick = "First" if imgs[0] == prefers else "Second"
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
