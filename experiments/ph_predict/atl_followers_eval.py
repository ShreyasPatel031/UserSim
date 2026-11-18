"""Pre-registered comparison (orchestrator, Nov 7 21:05Z): the honest reference vs the same ranking plus at-launch follower
features. PROVISIONAL: few days qualify; the full test is due ~Nov 20.

Reference: the live forecast (forecasts table, model launch_model) = the live forecast's honest input set, made at
00:05 PT on the launch day. Only its predicted rank is logged, so the reference score is -log(predicted rank).
Features (tables.at_launch_followers, read by the 00:05 PT daily run from data/today/<day>.json):
  ph_maker_max, ph_maker_sum (log1p of makers' PH followersCount), ph_hunter (log1p of hunter's), has_hunter.
  X followers: no 00:05 X read exists (X counts are filled ~01:30 PT or later), so the X feature is missing everywhere.
At-launch rule: a day qualifies only when its read_at is within READ_MAX_MIN minutes after 00:00 PT (the 00:05 run,
sometimes running late). Later re-reads (hours after launch) count as missing, never as a late read.
Test arm: score = reference + ridge fit of the within-day final log-vote residual of the reference on the features
(within-day standardized), trained leave-one-day-out on the other qualifying days only (no test-day labels).
Scored on days with final daily ranks: daily top 3/5/10 overlap with the final top k, paired bootstrap over days.
Rule: a gain counts only if it clears +3.5 on top 3 (and its interval excludes 0).
Counts only; no usernames are printed or written.
usage: python atl_followers_eval.py -> results/atl_followers_eval.json"""
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
READ_MAX_MIN = float(os.environ.get("READ_MAX_MIN", "20"))
OUTAGE = {"2026-11-05", "2026-11-06", "2026-11-07"}
FEATS = ["ph_maker_max", "ph_maker_sum", "ph_hunter", "has_hunter"]


def boot(d, rng, n=10000):
    d = np.asarray(d, float)
    if len(d) < 2:
        return [round(float(d.mean()), 1) if len(d) else None, None, int(len(d))]
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return [round(float(d.mean()), 1), [round(float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def minutes_after_pt_midnight(day, read_at):
    t = pd.Timestamp(read_at).tz_convert("America/Los_Angeles")
    return (t - pd.Timestamp(day).tz_localize("America/Los_Angeles")).total_seconds() / 60


def main():
    from pipeline import warehouse as W
    F = W.query("SELECT launch_id::VARCHAR AS id, day, role, ph_followers, read_at FROM at_launch_followers")
    L = W.query("SELECT id::VARCHAR AS id, day::VARCHAR AS day, daily_rank, votes FROM launches WHERE day::VARCHAR >= '2026-10-25'", do_sync=False)
    P = W.query("SELECT launch_id::VARCHAR AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model' AND forecast_date >= '2026-10-25'", do_sync=False)
    reads = F.groupby("day").read_at.max()
    mins = {d: round(minutes_after_pt_midnight(d, r), 1) for d, r in reads.items()}
    ok_days = sorted(d for d, m in mins.items() if 0 <= m <= READ_MAX_MIN and d not in OUTAGE)
    F = F[F.day.isin(ok_days)]
    mk, hu = F[F.role == "maker"], F[F.role == "hunter"]
    X = pd.DataFrame({"ph_maker_max": np.log1p(mk.groupby("id").ph_followers.max()),
                      "ph_maker_sum": np.log1p(mk.groupby("id").ph_followers.sum()),
                      "ph_hunter": np.log1p(hu.groupby("id").ph_followers.max())})
    X["has_hunter"] = X.ph_hunter.notna().astype(float)
    A = L.merge(P[["id", "predicted_rank"]], on="id").merge(X, left_on="id", right_index=True, how="left")
    A = A[A.day.isin(ok_days) & A.daily_rank.notna()].copy()
    scored = sorted(A.day.unique())
    A["ref"] = -np.log(A.predicted_rank.astype(float))
    A["y"] = np.log1p(A.votes.astype(float))
    for c in ["ref", "y"] + FEATS:   # within-day standardization: the board is a within-day ranking
        g = A.groupby("day")[c]
        A[c + "_z"] = ((A[c] - g.transform("mean")) / (g.transform("std") + 1e-9)).fillna(0)
    A["resid"] = A.y_z - A.ref_z
    Z = [c + "_z" for c in FEATS]
    A["test"] = np.nan
    for d in scored:   # leave one day out: fit on the other qualifying days only
        tr, te = A[A.day != d], A.day == d
        M = tr[Z].values; w = np.linalg.solve(M.T @ M + 5.0 * np.eye(len(Z)), M.T @ tr.resid.values)
        A.loc[te, "test"] = A.loc[te, "ref_z"] + A.loc[te, Z].values @ w
    rng = np.random.default_rng(0); res = {}
    for k in (3, 5, 10):
        a, b = [], []
        for d, g in A.groupby("day"):
            if (g.daily_rank <= k).sum() < k or len(g) < k:
                continue
            top = set(g[g.daily_rank <= k].id)
            a.append(len(set(g.nlargest(k, "ref").id) & top) / k * 100); b.append(len(set(g.nlargest(k, "test").id) & top) / k * 100)
        res[f"day top{k}"] = {"reference": round(float(np.mean(a)), 1) if a else None, "with followers": round(float(np.mean(b)), 1) if b else None,
                              "delta": boot(np.array(b) - np.array(a), rng)}
    d3 = res["day top3"]["delta"]
    verdict = "gain" if d3[0] is not None and d3[0] >= 3.5 and d3[1] and d3[1][0] > 0 else "no gain (does not clear +3.5 on top 3 with an interval above 0)"
    out = {"label": f"PROVISIONAL ({len(scored)} days)", "read_minutes_after_pt_midnight": mins, "read_max_min": READ_MAX_MIN,
           "qualifying_read_days": ok_days, "scored_days": scored, "launches_scored": int(len(A)),
           "excluded": {"late_reads": sorted(d for d, m in mins.items() if not (0 <= m <= READ_MAX_MIN)), "outage": sorted(OUTAGE),
                        "no_final_ranks": sorted(set(ok_days) - set(scored))},
           "x_followers": "missing everywhere (no 00:05 PT X read exists)", "reference": "live launch_model forecast rank (honest live set)",
           "test": "reference + LODO ridge on within-day z of " + ", ".join(FEATS), "boards": res,
           "weekly": "no full week qualifies (week of Nov 2: Nov 5-7 outage; earlier weeks lack 00:05 reads)", "verdict": verdict}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "results", "atl_followers_eval.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
