"""Does a bigger model inside the segments harness fix both spread and side? Dev set, logged runs."""

from __future__ import annotations

import json
import math

import numpy as np

from human_sim import simbench_mass_levers as M

H, S46, S55 = M.HAIKU, "claude-sonnet-4-6", "claude-sonnet-5-5"
ARMS = {
    "haiku_retr6": ("retr6_rev2", H),
    "haiku_seg": ("B_n3_soft_rev2", H),
    "haiku_seg_fwd": ("B_n3_soft", H),
    "haiku_ground": ("B_ground3_rev2", H),
    "s46_retr6": ("retr6", S46),
    "s46_seg": ("B_n3_soft_rev2", S46),
    "s55_retr6": ("retr6", S55),
    "s55_seg": ("B_n3_soft_rev2", S55),
    "s55_seg_fwd": ("B_n3_soft", S55),
    "s55_ground": ("B_ground3_rev2", S55),
}
BOTH = {"haiku_seg_both": ("haiku_seg", "haiku_seg_fwd"), "s55_seg_both": ("s55_seg", "s55_seg_fwd")}
REF = "haiku_ground"

SLICES = {
    "divided (truth)": lambda q: q["Hn"] >= M.DIV,
    "divided shared surveys": lambda q: q["Hn"] >= M.DIV and q["group3"] == "shared_survey",
    "divided Pop-only tasks": lambda q: q["Hn"] >= M.DIV and q["group3"] == "pop_only_task",
    "predicted divided (no truth)": lambda q: not math.isnan(q["nbr_h"]) and q["nbr_h"] >= M.DIV,
    "all questions": lambda q: True,
    "all shared surveys": lambda q: q["group3"] == "shared_survey",
}


def _paired_ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def main():
    M.DEV_ARMS = ARMS
    qs = M.load("dev")
    for q in qs:
        for k, (a, b) in BOTH.items():
            if a in q["preds"] and b in q["preds"]:
                q["preds"][k] = (q["preds"][a] + q["preds"][b]) / 2
    names = list(ARMS) + list(BOTH)
    out = {}
    for sname, pick in SLICES.items():
        qq = [q for q in qs if pick(q) and all(n in q["preds"] for n in names)]
        rows = {}
        for n in names:
            c = [M.components(q, q["preds"][n]) for q in qq]
            s = np.array([x["S"] for x in c])
            ref = np.array([M.components(q, q["preds"][REF])["S"] for q in qq])
            flips = [x["flip"] for x in c if not math.isnan(x.get("flip", math.nan))]
            rows[n] = {
                "S": round(float(s.mean()), 1),
                "vs_haiku_ground": round(float((s - ref).mean()), 1),
                "ci": _paired_ci(s - ref),
                "top1_right": round(float(np.mean([x["top_right"] for x in c])), 2),
                "wrong_side_ordinal": round(float(np.mean(flips)), 2) if flips else None,
                "entropy_gap": round(float(np.mean([x["entropy_gap"] for x in c])), 3),
                "shape_err": round(float(np.mean([x["profile_error"] for x in c])), 3),
            }
        out[sname] = {"N": len(qq), "arms": rows}
        print(f"\n== {sname} (N {len(qq)})")
        print(f"{'arm':16s} {'S':>6s} {'vs ref':>7s} {'CI':>15s} {'top1':>5s} {'flip':>5s} {'Hgap':>7s} {'shape':>6s}")
        for n, r in rows.items():
            print(f"{n:16s} {r['S']:6.1f} {r['vs_haiku_ground']:+7.1f} {str(r['ci']):>15s} {r['top1_right']:5.2f} "
                  f"{r['wrong_side_ordinal'] if r['wrong_side_ordinal'] is not None else '-':>5} "
                  f"{r['entropy_gap']:+7.3f} {r['shape_err']:6.3f}")
    (M.OUT / "sonnet_segments_report.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
