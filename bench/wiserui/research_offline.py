#!/usr/bin/env python3
"""Zero-cost offline analysis of saved WiserUI-Bench judgments (RESEARCH_HYPOTHESES.md section 3).

Reads results/<run>/pairs.jsonl (no model calls). Per pair and model: FA (winner shown first right), SA (winner
shown second right), CA = FA*SA. Breakdowns by source (GoodUI leak = winner inferred from what shipped; VWO /
abtest.design = reported), platform, page type, changed element / attribute, split; failure modes; model agreement,
oracle upper bounds, offline majority votes, selective-prediction (abstention) curves.

usage: python bench/wiserui/research_offline.py [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import os
import random
import re
from pathlib import Path

BENCH = Path(os.environ.get("WISERUI_BENCH", "/workspace/bench/wiserui"))
RES = BENCH / "results"
RUNS = {"opus55": "van_opus55", "sonnet5": "van_sonnet5", "pro31": "van_g31pro", "flash38": "van_g38flash", "sol": "van_gpt6sol", "luna": "van_gpt6luna",
        "gfocus25": "gfocus_t0_all252", "sonnet46": "van_sonnet46", "gpt5mini": "van_gpt5mini",
        "gpt41mini": "van_gpt41mini", "gpt4o": "van_gpt4o", "flash25": "van_flash"}


def ids(f: str) -> list[int]:
    return [int(x) for x in re.split(r"[,\s]+", (BENCH / f).read_text().strip()) if x]


def load(run: str) -> dict[int, dict]:
    out = {}
    for line in (RES / run / "pairs.jsonl").open():
        r = json.loads(line)
        win = "A" if r["a_is_win"] else "B"
        fa = sa = 0
        for o, ov in r["orders"].items():
            first_is_win = (o == "ab") == (win == "A")
            ok = int(ov.get("pick_ab") == win)
            if first_is_win:
                fa = ok
            else:
                sa = ok
        out[r["index"]] = {"fa": fa, "sa": sa, "ca": fa * sa}
    return out


def pct(x, n):
    return round(100.0 * x / n, 1) if n else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--src-info", default="", help="optional JSON {index: {uplift, date}} scraped from source pages")
    a = ap.parse_args()
    meta = {e["index"]: e for e in json.load(open(BENCH / "repo" / "WiserUI_Bench.json"))}
    main_ids, dev = ids("final_indices_main.txt"), set(ids("dev_indices.txt"))
    M = {k: load(v) for k, v in RUNS.items()}
    for k in M:
        assert set(main_ids) <= set(M[k]), k
    rep: dict = {}

    def src(i):
        s = meta[i]["source"]
        return "goodui_leak(inferred)" if "goodui" in s else "vwo(reported)" if "vwo" in s else "abtest.design"

    # 1. overall
    rep["overall"] = {k: {m: pct(sum(M[k][i][m] for i in main_ids), len(main_ids)) for m in ("ca", "fa", "sa")}
                      for k in M}

    # 2. breakdowns for the strong models (+ ours)
    feats = {
        "source": src,
        "platform": lambda i: meta[i]["web_mobile"],
        "split": lambda i: "dev75" if i in dev else "heldout177",
        "page_type": lambda i: meta[i]["page_type"],
        "industry": lambda i: meta[i]["industry_domain"],
        "n_elements_changed": lambda i: str(min(len(meta[i]["ui_change"]), 3)) + ("+" if len(meta[i]["ui_change"]) >= 3 else ""),
        "n_attrs_changed": lambda i: (lambda n: "1" if n == 1 else "2" if n == 2 else "3-4" if n <= 4 else "5+")(
            sum(len(v) for v in meta[i]["ui_change"].values())),
        "law_type(first)": lambda i: meta[i]["rationale"][0]["law"]["type"] if meta[i]["rationale"] else "none",
    }
    multi = {  # multi-label features: pair counted in each label it has
        "element": lambda i: set(meta[i]["ui_change"]),
        "attribute": lambda i: {x for v in meta[i]["ui_change"].values() for x in v},
        "law": lambda i: {r["law"]["name"] for r in meta[i]["rationale"]},
    }
    show = ["opus55", "pro31", "flash38", "sol", "sonnet5", "gfocus25"]
    br = {}
    for fname, f in feats.items():
        g = collections.defaultdict(list)
        for i in main_ids:
            g[f(i)].append(i)
        br[fname] = {lab: {"n": len(v), **{k: pct(sum(M[k][i]["ca"] for i in v), len(v)) for k in show}}
                     for lab, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}
    for fname, f in multi.items():
        g = collections.defaultdict(list)
        for i in main_ids:
            for lab in f(i):
                g[lab].append(i)
        br[fname] = {lab: {"n": len(v), **{k: pct(sum(M[k][i]["ca"] for i in v), len(v)) for k in show}}
                     for lab, v in sorted(g.items(), key=lambda kv: -len(kv[1])) if len(v) >= 8}
    rep["breakdowns"] = br

    # 3. failure modes: consistent-wrong (both orders pick the loser) vs position-flip
    fm = {}
    for k in M:
        c = collections.Counter()
        for i in main_ids:
            r = M[k][i]
            c["both_right" if r["ca"] else "both_wrong(confident_loser)" if not (r["fa"] or r["sa"])
              else "flip_first_bias" if r["fa"] else "flip_second_bias"] += 1
        fm[k] = {x: pct(v, len(main_ids)) for x, v in c.items()}
    rep["failure_modes"] = fm

    # 4. agreement / oracle / votes
    def oracle(keys):
        return pct(sum(any(M[k][i]["ca"] for k in keys) for i in main_ids), len(main_ids))

    def order_oracle(keys):  # best model chosen separately per order (looser)
        return pct(sum(any(M[k][i]["fa"] for k in keys) and any(M[k][i]["sa"] for k in keys) for i in main_ids),
                   len(main_ids))

    def vote(keys, tiebreak="opus55"):
        # per-order majority across models; tie -> tiebreak model's answer
        n = 0
        for i in main_ids:
            ok = []
            for o in ("fa", "sa"):
                s = sum(M[k][i][o] for k in keys)
                ok.append(s * 2 > len(keys) or (s * 2 == len(keys) and M[tiebreak][i][o]))
            n += all(ok)
        return pct(n, len(main_ids))

    def pooled(keys):
        # order-invariant pooled pick: count votes for the winner over both orders and all models; tie = wrong.
        n = 0
        for i in main_ids:
            s = sum(M[k][i]["fa"] + M[k][i]["sa"] for k in keys)
            n += s * 2 > 2 * len(keys)
        return pct(n, len(main_ids))

    sets = {"opus55+pro31": ["opus55", "pro31"], "opus55+pro31+flash38": ["opus55", "pro31", "flash38"],
            "pro31+flash38": ["pro31", "flash38"], "pro31+flash38+sol": ["pro31", "flash38", "sol"],
            "pro31+flash38+gfocus25": ["pro31", "flash38", "gfocus25"],
            "pro31+flash38+sol+gfocus25+luna": ["pro31", "flash38", "sol", "gfocus25", "luna"],
            "all12": list(M)}
    rep["ensembles"] = {name: {"oracle_CA_any_model_both_orders": oracle(ks),
                               "oracle_per_order": order_oracle(ks),
                               "per_order_majority_CA(tie->opus55)": vote(ks),
                               "pooled_both_orders_majority(=OI-style, strict)": pooled(ks)}
                        for name, ks in sets.items()}
    # cross-model agreement on CA outcome and on picks
    ag = {}
    for x, y in itertools.combinations(["opus55", "pro31", "flash38", "sol", "sonnet5", "gfocus25", "luna"], 2):
        both = sum(M[x][i]["ca"] and M[y][i]["ca"] for i in main_ids)
        pick_same = sum((M[x][i]["fa"] == M[y][i]["fa"]) + (M[x][i]["sa"] == M[y][i]["sa"]) for i in main_ids)
        ag[f"{x}~{y}"] = {"both_CA": pct(both, len(main_ids)), "per_order_pick_agree": pct(pick_same, 2 * len(main_ids))}
    rep["agreement"] = ag

    # 5. hard set: pairs the strong models all get confidently wrong (both orders pick the loser)
    def side(k, i):  # order-invariant outcome: 'W' (right both orders), 'L' (loser both orders), None (flip)
        r = M[k][i]
        return "W" if r["ca"] else "L" if not (r["fa"] or r["sa"]) else None
    hard = [i for i in main_ids if all(side(k, i) == "L" for k in ["opus55", "pro31", "flash38"])]
    allwrong = [i for i in main_ids if not any(M[k][i]["ca"] for k in M)]
    rep["hard"] = {
        "opus55_pro31_flash38_all_confidently_wrong": len(hard),
        "hard_by_source": dict(collections.Counter(src(i) for i in hard)),
        "no_model_of_12_CA": len(allwrong),
        "no_model_CA_by_source": dict(collections.Counter(src(i) for i in allwrong)),
        "source_base": dict(collections.Counter(src(i) for i in main_ids)),
        "hard_ids": hard,
    }

    # 6. order-invariant systems (answer computed from both orders, so identical in both presentations;
    #    its CA equals its accuracy). Flip pairs fall back to the next model, else a coin (expected 0.5).
    def oi_system(chain):
        e = 0.0
        for i in main_ids:
            s_ = next((side(k, i) for k in chain if side(k, i)), None)
            e += 1.0 if s_ == "W" else 0.0 if s_ == "L" else 0.5
        return pct(e, len(main_ids))
    def pooled_coin(keys):
        e = 0.0
        for i in main_ids:
            v = sum(M[k][i]["fa"] + M[k][i]["sa"] for k in keys)
            e += 1.0 if 2 * v > 2 * len(keys) else 0.5 if 2 * v == 2 * len(keys) else 0.0
        return pct(e, len(main_ids))
    rep["order_invariant"] = {
        **{f"{k} alone (flip->coin)": oi_system([k]) for k in ["opus55", "pro31", "flash38", "sol", "sonnet5", "gfocus25"]},
        "pro31 -> flash38 -> coin": oi_system(["pro31", "flash38"]),
        "flash38 -> pro31 -> coin": oi_system(["flash38", "pro31"]),
        "flash38 -> opus55 -> coin": oi_system(["flash38", "opus55"]),
        "pro31 -> opus55 -> coin": oi_system(["pro31", "opus55"]),
        "opus55 -> pro31 -> coin": oi_system(["opus55", "pro31"]),
        "pooled votes opus55+pro31+flash38 (tie->coin)": pooled_coin(["opus55", "pro31", "flash38"]),
        "pooled votes pro31+flash38 (tie->coin)": pooled_coin(["pro31", "flash38"]),
    }
    # what the other models do on each model's flip pairs (is there tie-break signal?)
    fl = {}
    for k in ["opus55", "pro31", "flash38"]:
        inc = [i for i in main_ids if side(k, i) is None]
        fl[k] = {"n_flip": len(inc), **{o: dict(collections.Counter(str(side(o, i)) for i in inc))
                                        for o in ["opus55", "pro31", "flash38", "sol"] if o != k}}
    rep["flip_pair_tiebreak_signal"] = fl
    # cascade cost: cheap model first, escalate only its flip pairs (2 more calls on the expensive model)
    cost = {"flash38": 0.0072, "pro31": 0.0192, "opus55": 0.0562}
    casc = {}
    for cheap, dear in [("flash38", "opus55"), ("pro31", "opus55"), ("flash38", "pro31")]:
        esc = sum(side(cheap, i) is None for i in main_ids) / len(main_ids)
        casc[f"{cheap}->{dear}"] = {"escalated_frac": round(esc, 3), "CA_expected": oi_system([cheap, dear]),
                                    "usd_per_pair": round(cost[cheap] + esc * cost[dear], 4)}
    rep["cascade"] = casc

    # 7. selective prediction: commit only when models are order-consistent and agree
    def tier_stats(pred):
        v = [i for i in main_ids if pred(i)]
        right = sum(side("opus55", i) == "W" if side("opus55", i) else side("pro31", i) == "W" for i in v)
        return {"n": len(v), "coverage": pct(len(v), len(main_ids)), "acc": pct(right, len(v))}
    rep["selective"] = {
        "opus55 consistent": tier_stats(lambda i: side("opus55", i) is not None),
        "opus55 flip": tier_stats(lambda i: side("opus55", i) is None),
        "pro31+flash38 consistent & agree": tier_stats(lambda i: side("pro31", i) and side("pro31", i) == side("flash38", i)),
        "opus55+pro31 consistent & agree": tier_stats(lambda i: side("opus55", i) and side("opus55", i) == side("pro31", i)),
        "opus55+pro31+flash38 consistent & agree": tier_stats(
            lambda i: side("opus55", i) and side("opus55", i) == side("pro31", i) == side("flash38", i)),
    }

    # 8. winner role: VWO success stories are variant wins; GoodUI leaks '_afull' winners = control kept (variant rejected)
    def role(i):
        e = meta[i]
        def r(u):
            n = u.lower().split("/")[-1]
            if re.search(r"control|original|_a[._-]|-a[._-]|_afull|before", n):
                return "ctrl"
            if re.search(r"variat|variant|_b[._-]|-b[._-]|_[b-e]full|after|challenger|treatment", n):
                return "var"
            return "?"
        w, l = r(e["win_url"]), r(e["lose_url"])
        if w == "?" and l != "?":
            w = "var" if l == "ctrl" else "ctrl"
        return f"{src(i).split('(')[0]}:winner={w}"
    g = collections.defaultdict(list)
    for i in main_ids:
        g[role(i)].append(i)
    rep["winner_role"] = {lab: {"n": len(v), **{k: pct(sum(M[k][i]["ca"] for i in v), len(v)) for k in show},
                                **{f"{k}_OI": pct(sum({"W": 1, "L": 0, None: .5}[side(k, i)] for i in v), len(v))
                                   for k in ["opus55", "pro31", "flash38"]}}
                          for lab, v in sorted(g.items()) if len(v) >= 10}

    # 9. optional: source-page facts scraped from the public source URLs (VWO headline uplift, publish year)
    if a.src_info and Path(a.src_info).exists():
        info = {int(k): v for k, v in json.load(open(a.src_info)).items()}
        vw = [i for i in main_ids if info.get(i, {}).get("uplift") is not None]
        ub = {}
        for lo, hi in [(0, 10), (10, 25), (25, 50), (50, 1e9)]:
            v = [i for i in vw if lo <= info[i]["uplift"] < hi]
            ub[f"uplift[{lo},{hi if hi < 1e9 else 'inf'})"] = {"n": len(v), **{k: pct(sum(M[k][i]["ca"] for i in v), len(v)) for k in show}}
        rep["vwo_by_reported_uplift"] = ub
        yr = collections.defaultdict(list)
        for i in main_ids:
            d_ = info.get(i, {}).get("date")
            y = int(d_[-4:]) if d_ and d_[-4:].isdigit() else int(d_[:4]) if d_ else None
            yr["<=2017" if y and y <= 2017 else "2018-2021" if y and y <= 2021 else "2022-2025" if y else "unknown"].append(i)
        rep["by_publish_year"] = {lab: {"n": len(v), **{k: pct(sum(M[k][i]["ca"] for i in v), len(v)) for k in show}}
                                  for lab, v in sorted(yr.items())}

    # 10. paired bootstrap: majority vote of 3 vs its best member
    rng = random.Random(0)
    def vote_ok(keys, i, tb):
        ok = []
        for o in ("fa", "sa"):
            s_ = sum(M[k][i][o] for k in keys)
            ok.append(s_ * 2 > len(keys) or (s_ * 2 == len(keys) and M[tb][i][o]))
        return int(all(ok))
    for ks, tb in [(["opus55", "pro31", "flash38"], "opus55"), (["pro31", "flash38", "sol"], "pro31")]:
        d = [vote_ok(ks, i, tb) - M[tb][i]["ca"] for i in main_ids]
        bs = sorted(sum(d[rng.randrange(len(d))] for _ in d) / len(d) for _ in range(5000))
        rep[f"vote({'+'.join(ks)})_minus_{tb}"] = {"dCA": pct(sum(d), len(d)), "ci95": [round(100 * bs[125], 1), round(100 * bs[4874], 1)],
                                                   "n01": sum(x == 1 for x in d), "n10": sum(x == -1 for x in d)}
    print(json.dumps(rep, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
