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


# ----------------------------------------------------------------- frozen "ab" prompts (bench ledger caches by call key)

def test_ab_prompts_are_frozen_at_372b405():
    import hashlib

    p = {"name": "Ann Lee", "role": "shopper", "bio": "Busy parent.", "goal": "buy shoes"}
    c = {"company": "Acme", "page_type": "product page", "industry": "retail", "platform": "website"}
    d = [{"element": "main button", "a": "green Buy", "b": "grey Buy"}]
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()[:16]  # noqa: E731
    assert h(judge_prompt(p, c, "", None, "ab", False)) == "4ff439eef3ef45e2"
    assert h(judge_prompt(p, c, "buy now", d, "ba", True)) == "16d831d5ed411692"
    assert h(pairwise._GOAL_DIFFS.format(ctx=pairwise._ctx_line(c))) == "b9cf54af1062defe"
    assert pairwise._version_parts(A, B) == ["Version X:", b"AAA", "Version Y:", b"BBB"]


def test_default_flags_are_the_draft_defaults():
    f = PairFlags()
    assert (f.both_orders, f.goal_diffs, f.debias, f.temperature, f.max_tokens, f.media_resolution) == (
        True, False, False, 0.4, 700, None)
    assert (f.framing, f.seed, f.json_retries) == ("ab", None, 0)
    assert f.name() == "both+ratings" and PairFlags(goal_diffs=True, debias=True).name() == "both+ratings+goal_diffs+debias"


# ----------------------------------------------------------------- robustness

def test_parse_json_handles_fences_prose_and_two_objects():
    from mvp.pairwise import parse_json

    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}
    assert parse_json('{"a": 1} and also {"b": 2}') == {"a": 1}
    assert parse_json('[note] {"rating_x": 3}') == {"rating_x": 3}
    assert parse_json("") is None and parse_json(None) is None and parse_json("nope") is None


def test_ratings_reject_non_numbers():
    from mvp.pairwise import _rating

    assert _rating("7/10") == 7 and _rating(12) == 10 and _rating(0) == 1
    assert _rating(True) is None and _rating("inf") is None and _rating("nan") is None and _rating(None) is None


def test_json_retry_reasks_with_suffixed_key():
    keys = []

    async def call(key, contents, **kw):
        keys.append(key)
        if key.endswith("|retry1"):
            return json.dumps({"reasons": "ok", "rating_x": 7, "rating_y": 4}), 1, 1
        return "I think X is better", 1, 1

    r = run(compare_pair(A, B, PERSONAS[:2], CTX, PairFlags(json_retries=1), call=call))
    assert r["failed_judgments"] == 0 and all(j["attempts"] == 2 for j in r["judgments"])
    assert sorted(keys) == sorted([f"judge|{o}|{k}{s}" for o in ("ab", "ba") for k in range(2) for s in ("", "|retry1")])
    # without retries the draft behaviour holds: one call each, failed judgments
    keys.clear()
    r = run(compare_pair(A, B, PERSONAS[:2], CTX, PairFlags(), call=call))
    assert r["failed_judgments"] == 4 and len(keys) == 4


def test_model_errors_become_failed_judgments_not_exceptions():
    async def call(key, contents, **kw):
        if key.endswith("|0"):
            raise RuntimeError("gemini call failed: 429")
        return json.dumps({"reasons": "r", "rating_x": 8, "rating_y": 3}), 1, 1

    r = run(compare_pair(A, B, PERSONAS[:3], CTX, PairFlags(), call=call))
    assert r["failed_judgments"] == 2 and r["n_personas"] == 2
    assert r["errors"] and "429" in r["errors"][0]


def test_seed_is_deterministic_per_key_and_only_sent_when_set():
    seen = {}

    async def call(key, contents, *, temperature, max_tokens, media_resolution=None, **kw):
        seen[key] = kw.get("seed")
        return json.dumps({"reasons": "r", "rating_x": 5, "rating_y": 5}), 1, 1

    run(compare_pair(A, B, PERSONAS[:2], CTX, PairFlags(), call=call))
    assert set(seen.values()) == {None}
    run(compare_pair(A, B, PERSONAS[:2], CTX, PairFlags(seed=3), call=call))
    first = dict(seen)
    run(compare_pair(A, B, PERSONAS[:2], CTX, PairFlags(seed=3), call=call))
    assert seen == first and len(set(first.values())) == 4 and None not in first.values()
    run(compare_pair(A, B, PERSONAS[:2], CTX, PairFlags(seed=4), call=call))
    assert seen != first


def test_max_concurrency_bounds_in_flight_calls():
    live = {"now": 0, "max": 0}

    async def call(key, contents, **kw):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await asyncio.sleep(0.01)
        live["now"] -= 1
        return json.dumps({"reasons": "r", "rating_x": 6, "rating_y": 4}), 1, 1

    run(compare_pair(A, B, PERSONAS, CTX, PairFlags(), call=call, max_concurrency=3))
    assert live["max"] == 3


def test_default_call_runs_on_the_bounded_pool(monkeypatch):
    import threading

    from mvp import e2e_ui_run

    got = {}

    def fake_generate(contents, **kw):
        got.update(kw, thread=threading.current_thread().name, n=len(contents))
        return '{"ok": 1}', 5, 2

    monkeypatch.setattr(e2e_ui_run, "gemini_generate", fake_generate)
    pairwise.configure_pool(2)
    out = run(pairwise.default_call("judge|ab|0", ["p", b"x"], temperature=0.4, max_tokens=700, seed=9))
    assert out == ('{"ok": 1}', 5, 2) and got["thread"].startswith("pairwise") and got["n"] == 2
    assert (got["seed"], got["json_mode"], got["retries"], got["model"]) == (9, True, 8, pairwise.PAIRWISE_MODEL)
    out = run(pairwise.vertex_call(retries=2)("k", ["p"], temperature=0.0, max_tokens=10))
    assert got["retries"] == 2 and got["seed"] is None


# ----------------------------------------------------------------- products framing (the product's comparison study)

def test_products_framing_uses_product_labels_and_rejects_goal_diffs():
    import pytest

    seen = []
    call, _ = fake(lambda x, y, p, k: (seen.append(p) or (7, 5)) if x == b"AAA" else (5, 7))
    ev_a = PairEvidence(label="kolanut", screenshots=[b"AAA"], summary="Job: find risk. Steps: 1 click Pricing")
    flags = PairFlags(debias=True, framing="products")
    r = run(compare_pair(ev_a, B, PERSONAS, {"segment": "customer success tools"}, flags, call=call))
    assert r["winner"] == "A" and r["flags"] == "both+ratings+debias+products"
    assert all("Product X" in p and "Version" not in p and "customer success tools" in p for p in seen)
    assert "kolanut" not in " ".join(seen)
    parts = pairwise._version_parts(ev_a, B, "products")
    assert parts[0].startswith("Product X: (what you saw and did there: Job: find risk") and parts[2] == "Product Y:"
    with pytest.raises(ValueError):
        PairFlags(goal_diffs=True, framing="products")
    with pytest.raises(ValueError):
        PairFlags(framing="sites")


def test_aa_is_half_in_products_framing_even_with_a_first_slot_bias():
    call, _ = fake(lambda x, y, p, k: (8, 6))
    r = run(compare_pair(A, A, PERSONAS, {}, PairFlags(framing="products", debias=True), call=call))
    assert r["p_a"] == 0.5 and r["mean_diff"] == 0 and r["winner"] == "tie"
    assert A.fingerprint() == PairEvidence(label="other", screenshots=[b"AAA"]).fingerprint() != B.fingerprint()


def test_bench_loader_calls_compare_pair(tmp_path, monkeypatch):
    """bench/wiserui/run_bench.py stays a thin loader over mvp.pairwise.compare_pair (mocked model, fake dataset)."""
    import importlib.util
    import sys
    from pathlib import Path

    items = [{"index": i, "source": "goodui.org", "company": "Acme", "page_type": "cart", "industry_domain": "retail",
              "web_mobile": "web"} for i in (1, 2)]
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "WiserUI_Bench.json").write_text(json.dumps(items))
    for i in (1, 2):
        d = tmp_path / "images_clean" / str(i)
        d.mkdir(parents=True)
        (d / "win.png").write_bytes(b"WIN")
        (d / "lose.png").write_bytes(b"LOSE")
    monkeypatch.setenv("WISERUI_BENCH", str(tmp_path))

    async def model(key, contents, *, temperature, max_tokens, media_resolution=None, **kw):
        if "planner" in key:
            return json.dumps({"personas": [{"name": f"V{i} W{i}", "role": "r", "bio": "b", "goal": "g"} for i in range(6)]}), 1, 1
        imgs = [c for c in contents if isinstance(c, bytes)]
        rx, ry = (8, 3) if imgs[0] == b"WIN" else (3, 8)
        return json.dumps({"reasons": "r", "rating_x": rx, "rating_y": ry}), 100, 20

    monkeypatch.setattr(pairwise, "default_call", model)
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("run_bench_under_test", root / "bench" / "wiserui" / "run_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["run_bench", "--indices", "1,2", "--stream", "s1", "--personas-from", "",
                                      "--out", str(out)])
    run(mod.main())
    pairs = [json.loads(x) for x in (out / "pairs.jsonl").read_text().splitlines()]
    rows = [json.loads(x) for x in (out / "judgments.jsonl").read_text().splitlines()]
    assert [p["winner"] == ("A" if p["a_is_win"] else "B") for p in pairs] == [True, True]
    assert {(r["index"], r["order"], r["pick"]) for r in rows} == {(i, o, "First" if o == "wl" else "Second")
                                                                  for i in (1, 2) for o in ("wl", "lw")}
    assert json.loads((out / "config.json").read_text())["flags"]["seed"] is None
