"""Can per-person factors add accuracy ON TOP of the product's own-review level? Model-free, no spend.

The handoff's people-like-them averages compare a segment's ratings across products, which mixes "which products this
segment reviews" with "how this segment rates". Here each factor's offset is learned WITHIN products: the mean of
(rating - that product's mean) for a factor level, over every product except the person's own, shrunk with k=SHRINK.
Prediction = own-review level (heldout_bench's best: last 100 own reviews before the person, shrunk to the category
mean, k=10) + w * sum of the person's factor offsets. w is chosen on DEV products, scored on TEST, per platform.

    python personalize.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
sys.path.insert(0, str(CTX / "experiments/staged_context"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus as C  # noqa: E402
import heldout_bench as HB  # noqa: E402
import ux_mcp as U  # noqa: E402

OUT = HB.OUT.parent / "personalize"
SHRINK = 50.0
WS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
FACTORS = {"capterra": ["role_family", "size_fine", "time_used", "industry"], "g2": ["role_family", "size3", "industry"]}


def offsets(d: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    """Per person x output: leave-own-product-out within-product offset of each factor level."""
    rows = []
    P = X[["rid", "source", "product", "output"]].merge(d[["rid"] + sorted({f for v in FACTORS.values() for f in v})], on="rid")
    for (src, r), people in P.groupby(["source", "output"]):
        dd = d[(d.source == src) & d[r].notna()].copy()
        dd["res"] = dd[r] - dd.groupby("product")[r].transform("mean")
        for f in FACTORS[src]:
            tot = dd.groupby(f).res.agg(["sum", "count"])
            own = dd.groupby(["product", f]).res.agg(["sum", "count"])
            t = tot.reindex(people[f]).fillna(0).to_numpy()
            o = own.reindex(pd.MultiIndex.from_arrays([people["product"], people[f]])).fillna(0).to_numpy()
            s, n = t[:, 0] - o[:, 0], t[:, 1] - o[:, 1]
            people = people.assign(**{f"off_{f}": s / (n + SHRINK)})
        rows.append(people)
    out = pd.concat(rows, ignore_index=True)
    offs = [c for c in out.columns if c.startswith("off_")]
    out["off_sum"] = out[offs].fillna(0).sum(axis=1)
    return out[["rid", "output"] + offs + ["off_sum"]]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    X = pd.read_pickle(HB.OUT / "estimates.pkl")
    d = HB.frame()
    X = X.merge(offsets(d, X), on=["rid", "output"])
    n = X.own_last100_n.fillna(0)
    X["level"] = ((n * X.own_last100_mean.fillna(0) + 10 * X.category_mean) / (n + 10)).fillna(X.segment_mean)
    sc = X.output.map(HB.SCALE)
    lo, hi = X.output.map(lambda r: U.RATINGS[r][0]), X.output.map(lambda r: U.RATINGS[r][1])
    rows = []
    for w in WS:
        pred = (X.level + w * X.off_sum).clip(lo, hi)
        e2 = ((pred - X.y) / sc) ** 2
        for (s, sp, o), g in X.assign(e2=e2, pred=pred).groupby(["source", "split", "output"]):
            ws = [z.pred.rank().corr(z.y.rank()) for _, z in g.groupby("product") if len(z) >= 10 and z.pred.std() > 0 and z.y.std() > 0]
            rows.append({"w": w, "source": s, "split": sp, "output": o, "rmse": float(np.sqrt(g.e2.mean())),
                         "within_spearman": float(np.mean(ws)) if ws else 0.0, "n": len(g)})
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "by_weight.csv", index=False)
    best = R[R.split == "dev"].groupby(["source", "output", "w"]).rmse.mean().reset_index()
    best = best.loc[best.groupby(["source", "output"]).rmse.idxmin()].set_index(["source", "output"]).w
    t = R[R.split == "test"].set_index(["source", "output", "w"])
    lines = []
    for (s, o), w in best.items():
        base, pick = t.loc[(s, o, 0.0)], t.loc[(s, o, w)]
        lines.append({"source": s, "output": o, "w_dev": w, "test_rmse_level": base.rmse, "test_rmse_personal": pick.rmse,
                      "test_spearman_level": base.within_spearman, "test_spearman_personal": pick.within_spearman, "n": int(base.n)})
    L = pd.DataFrame(lines)
    L.to_csv(OUT / "test_report.csv", index=False)
    pd.set_option("display.width", 220)
    print(L.round(4).to_string(index=False))
    # the offsets themselves, on all data (for reading)
    tabs = []
    for src, fs in FACTORS.items():
        dd = d[d.source == src]
        for r in ([x for x in U.RATINGS if dd[x].notna().any()]):
            z = dd[dd[r].notna()].copy()
            z["res"] = z[r] - z.groupby("product")[r].transform("mean")
            for f in fs:
                g = z.groupby(f).res.agg(["mean", "count"])
                g = g[g["count"] >= 200]
                tabs.append(g.assign(source=src, output=r, factor=f).reset_index().rename(columns={f: "level"}))
    T = pd.concat(tabs, ignore_index=True)
    T.to_csv(OUT / "within_product_offsets.csv", index=False)
    print("\nlargest within-product offsets (n >= 200):")
    print(T.reindex(T["mean"].abs().sort_values(ascending=False).index).head(25).round(3).to_string(index=False))


if __name__ == "__main__" and not any(a.startswith("--export") for a in sys.argv):
    main()


def export(path: Path) -> None:
    """Shrunk within-product offsets per factor level (all Capterra + G2 data) and the DEV-chosen weights, for
    mvp/agent_mode.py. Aggregate calibration constants only; no product's reviews are shipped."""
    import json

    d = HB.frame()
    rep = pd.read_csv(OUT / "test_report.csv")
    out = {"about": "Within-product rating offsets per persona factor level (rating minus that product's mean, averaged "
                    f"over Capterra/G2 reviewers, shrunk with k={SHRINK:.0f}); weight per output chosen on DEV products "
                    "(experiments/human_experience/personalize.py).", "outputs": {}}
    for r in ("overall_rating", "ease_of_use_rating", "recommendation_score"):
        z = d[(d.source == "capterra") & d[r].notna()].copy()
        z["res"] = z[r] - z.groupby("product")[r].transform("mean")
        w = rep[(rep.source == "capterra") & (rep.output == r)].w_dev.iloc[0]
        fac = {}
        for f in ("role_family", "size_fine", "time_used", "industry"):
            g = z.groupby(f).res.agg(["sum", "count"])
            fac[f] = {str(k): round(float(s / (n + SHRINK)), 4) for k, (s, n) in g.iterrows() if n >= 30}
        out["outputs"][r] = {"weight": float(w), "factors": fac}
    path.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__" and "--export" in sys.argv[1:2]:
    export(Path(sys.argv[sys.argv.index("--export") + 1]))


def export_segments(path: Path) -> None:
    """Aggregate people-like-them stats (all Capterra reviews): mean rating per factor level and the unhappy share
    (overall <= 3 or recommend <= 6), for agent mode's "People like this person" section. Calibration constants only."""
    import json

    df = U.data()
    df = df.assign(role_family=df.reviewer_job_title.fillna("").map(lambda t: C.E.role_family(t)))
    unhappy = (df.overall_rating <= 3) | (df.recommendation_score <= 6)
    cols = {"role_family": "role_family", "company_size": "reviewer_company_size", "time_used": "reviewer_time_used_product",
            "industry": "reviewer_industry"}
    out = {"about": f"Mean ratings and unhappy share per persona factor level over {len(df)} Capterra reviews of "
                    f"{df.product_name.nunique()} products (experiments/human_experience/personalize.py export_segments).",
           "all": {r: round(float(df[r].mean()), 3) for r in U.RATINGS}, "unhappy_all": round(float(unhappy.mean()), 4),
           "factors": {}}
    for key, col in cols.items():
        lv = {}
        for v, g in df.groupby(col):
            if len(g) < 30 or v in ("unknown", ""):
                continue
            lv[str(v)] = {**{r: [round(float(g[r].mean()), 3), int(g[r].notna().sum())] for r in U.RATINGS if g[r].notna().any()},
                          "unhappy": round(float(unhappy[g.index].mean()), 4)}
        out["factors"][key] = lv
    path.write_text(json.dumps(out) + "\n")


if __name__ == "__main__" and "--export-segments" in sys.argv:
    export_segments(Path(sys.argv[sys.argv.index("--export-segments") + 1]))
