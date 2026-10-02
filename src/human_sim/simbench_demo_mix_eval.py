"""Compare the demographic persona mixture against plain / invented personas on the questions it covers."""

from __future__ import annotations

import ast
import json

import numpy as np

from human_sim import simbench_mass_levers as M

ARMS = {"plain": ("retr6_rev2", M.HAIKU), "invented": ("P_groundall5", M.HAIKU),
        "demo_mix": ("C5_demo_mix", M.HAIKU), "demo_mix_v2": ("C5b_demo_mix", M.HAIKU), "own": ("C5_own", M.HAIKU), "D3": ("D3_same_group_same_topic", M.HAIKU)}


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def S(q, p):
    return M.components(q, p)["S"]


def persona_diversity(q, arm):
    segs = q["traces"][arm]
    segs = ast.literal_eval(segs) if isinstance(segs, str) else segs
    D = np.array([[s["dist"].get(k, 0.0) for k in q["keys"]] for s in segs], float)
    D /= D.sum(1, keepdims=True)
    return float(np.mean([M.tvd(x, D.mean(0)) for x in D]))


def main():
    M.EVAL_ARMS, M.DEV_ARMS = ARMS, ARMS
    out = {}
    for which in ("dev", "eval"):
        qs = [q for q in M.load(which) if "demo_mix" in q["preds"] and "plain" in q["preds"] and "invented" in q["preds"]]
        res = {}
        print(f"\n==== {which}: questions covered by the demographic mixture: {len(qs)}")
        for split in ("Pop", "Grouped"):
            qq = [q for q in qs if q["split"] == split]
            if not qq:
                continue
            b = np.array([S(q, q["preds"]["plain"]) for q in qq])
            label = "country-level questions" if split == "Pop" else "subgroup questions"
            print(f"-- {label} (N {len(qq)})")
            rows = {}
            for arm in ("plain", "invented", "demo_mix", "demo_mix_v2", "own", "D3"):
                sub = [(i, q) for i, q in enumerate(qq) if arm in q["preds"]]
                if len(sub) < 0.85 * len(qq):
                    continue
                s = np.array([S(q, q["preds"][arm]) for _, q in sub])
                d = s - b[[i for i, _ in sub]]
                cons = [M.Hn(q["preds"][arm]) for _, q in sub if q["Hn"] < 0.65]
                rows[arm] = {"N": len(sub), "S": float(s.mean()), "vs_plain": float(d.mean()), "ci": ci(d),
                             "consensus_spread": float(np.mean(cons)) if cons else None}
                print(f"   {arm:10s} N {len(sub):3d}  S {s.mean():5.1f}  vs plain {d.mean():+5.1f} {str(ci(d)):>14s}"
                      + (f"  consensus spread {np.mean(cons):.2f}" if cons else ""))
            true_cons = [q["Hn"] for q in qq if q["Hn"] < 0.65]
            if true_cons:
                print(f"   (true consensus spread {np.mean(true_cons):.2f})")
            div = [persona_diversity(q, "demo_mix_v2") for q in qq if "demo_mix_v2" in q.get("traces", {})]
            inv = [persona_diversity(q, "invented") for q in qq if "invented" in q.get("traces", {})]
            print(f"   how different personas' answers are (TVD to their average): demographic {np.mean(div):.3f}, invented {np.mean(inv):.3f}")
            rows["persona_diversity"] = {"demographic": float(np.mean(div)), "invented": float(np.mean(inv))}
            res[split] = rows
        out[which] = res
    (M.OUT / "demo_mix_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
