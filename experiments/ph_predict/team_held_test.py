"""Team held share at 00:05 vs the published 00:05 line's accuracy (pre-registered: results/team_held_prereg.md).
Inputs: per-day team_shadow outputs computed with the newest store_v3 copy published at or before d 00:05 PT (dir of <d>.jsonl,
argv[1]); published 00:05 forecast parquets; truth_daily.json. Writes results/team_held_test.json. Counts and launch ids only.
usage: python team_held_test.py <dir with <d>.jsonl>"""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
STORE_USED = {"2026-11-14": "11-13T19:58Z", "2026-11-15": "11-13T19:58Z", "2026-11-16": "11-13T19:58Z", "2026-11-17": "11-13T19:58Z",
              "2026-11-18": "11-17T09:29Z", "2026-11-19": "11-18T09:00Z", "2026-11-20": "11-19T08:54Z", "2026-11-21": "11-20T09:09Z",
              "2026-11-22": "11-21T09:03Z"}


def main(src):
    TD = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/web/truth_daily.json"], capture_output=True, text=True).stdout)["days"]
    rows, days = [], {}
    for f in sorted(glob.glob(os.path.join(src, "*.jsonl"))):
        d = os.path.basename(f)[:10]
        if d not in TD or TD[d].get("status") != "counts": days[d] = "no final ranks yet"; continue
        p = tempfile.mkdtemp() + "/f.parquet"
        subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p], check=True)
        F = pd.read_parquet(p); F["id"] = F.id.astype(str); pm = str(F.published_model.iloc[0]) if "published_model" in F else "arm2"; col = "pred_arm3" if pm == "arm3" else next(c for c in ("pred_arm2", "pred") if c in F and F[c].notna().all())
        F["pred_rank"] = F[col].rank(ascending=False, method="first")
        T = pd.DataFrame([json.loads(l) for l in open(f)]); T["id"] = T.launch_id.astype(str)
        tr = {str(k): int(v) for k, v in TD[d]["ranks"].items()}
        X = F[["id", "pred_rank"]].merge(T[["id", "n_team", "n_team_complete"]], on="id", how="left")
        X["final_rank"] = X.id.map(tr); X["day"] = d; X["n_team"] = pd.to_numeric(X.n_team); X["n_team_complete"] = pd.to_numeric(X.n_team_complete)
        X["held"] = X.n_team_complete / X.n_team.where(X.n_team > 0)
        X["true_top3"] = X.final_rank <= 3; X["pred_top3"] = X.pred_rank <= 3
        rows.append(X); days[d] = {"published": pm, "launches": len(X), "ranked": int(X.final_rank.notna().sum()), "store_copy": STORE_USED.get(d),
                                   "mean_held": round(float(X.held.mean()), 3), "top3_hits": int((X.true_top3 & X.pred_top3).sum())}
    A = pd.concat(rows, ignore_index=True); A = A[A.held.notna() & A.final_rank.notna()].copy()
    A["err"] = (np.log(A.pred_rank) - np.log(A.final_rank)).abs(); A = A[np.isfinite(A.err)].copy()
    t3 = A[A.true_top3].copy(); med = float(t3.held.median()); t3["high"] = t3.held > 0   # amendment 1: median is 0, split at > 0
    dl = sorted(A.day.unique()); rng = np.random.default_rng(0)

    def stats(sub_t3, sub_all):
        h, l = sub_t3[sub_t3.high], sub_t3[~sub_t3.high]
        if not len(h) or not len(l): return None
        diff = h.pred_top3.mean() - l.pred_top3.mean()
        e = sub_all[["held", "err"]].dropna(); return diff, diff * (len(l) / len(sub_t3)) * 100, spearmanr(e.held, e.err)[0]
    base = stats(t3, A); bs = []
    for _ in range(10000):
        pick = rng.choice(dl, len(dl)); s3 = pd.concat([t3[t3.day == d] for d in pick]); sa = pd.concat([A[A.day == d] for d in pick])
        r = stats(s3, sa)
        if r: bs.append(r)
    bs = np.array(bs); ci = lambda i: [round(float(np.percentile(bs[:, i], 2.5)), 3), round(float(np.percentile(bs[:, i], 97.5)), 3)]
    per_day = pd.DataFrame([{"day": d, **v} for d, v in days.items() if isinstance(v, dict)])
    rho_day = spearmanr(per_day.mean_held, per_day.top3_hits)[0] if len(per_day) >= 3 else None
    diff = base[0]; sd = float(bs[:, 0].std()); need = (int(np.ceil(len(dl) * (1.96 * sd / abs(diff)) ** 2)) if diff else None)
    res = {"prereg": "results/team_held_prereg.md", "team_shadow_commit": "4e4dd4e9 (the nightly worktree; the prereg's fcbcd617 was a slip)",
           "days": days, "n_days_scored": len(dl), "launches_with_team": int(len(A)), "true_top3_launches": int(len(t3)), "median_held_top3": round(med, 3),
           "top3_hit_high": round(float(t3[t3.high].pred_top3.mean()) * 100, 1), "top3_hit_low": round(float(t3[~t3.high].pred_top3.mean()) * 100, 1),
           "n_high": int(t3.high.sum()), "n_low": int((~t3.high).sum()),
           "primary_diff_high_minus_low_pts": [round(diff * 100, 1)] + [round(100 * x, 1) for x in ci(0)],
           "upper_bound_gain_top3_pts": [round(base[1], 1)] + [round(100 * x, 1) for x in [ci(1)[0] / 100, ci(1)[1] / 100]],
           "spearman_held_vs_log_rank_error": [round(float(base[2]), 3)] + ci(2),
           "per_day_spearman_mean_held_vs_top3_hits": (round(float(rho_day), 3) if rho_day is not None else None),
           "days_needed_at_observed_effect": need,
           "decision": "MATTERS (primary CI excludes 0)" if (ci(0)[0] > 0 or ci(0)[1] < 0) else "NOT SHOWN (primary CI covers 0)"}
    json.dump(res, open(os.path.join(HERE, "results", "team_held_test.json"), "w"), indent=1, default=str); print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
