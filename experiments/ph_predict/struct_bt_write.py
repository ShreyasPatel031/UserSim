"""STRUCT-BT26, local part (orchestrator 14:33Z Nov 25: the simulation needs a structural input for EVERY 2026 day; TARGETS-0 could only
score 24 weeks on the 191 non-contiguous days). Input: oos.parquet from struct_bt_vm.py (arm-3 month-forward replica, every 2026 day
Jan 1 - Nov 24; test month m trained only on days before m). Output: results/structural/backtest/<day>.json in the existing
structural_shortlist.day_file format, every launch with the arm-3 score / rank plus
  pred_votes   predicted final votes from a score -> votes calibration fitted MONTH-FORWARD: for test month m, least squares of
               log1p(votes) on the arm-3 score over every OOS row of earlier months (2025 OOS months included, so January has a fit),
               then expm1(a + b * score) times the smearing factor mean(exp(residual)) of those rows (Duan) so daily sums are unbiased.
arm 2 scores are carried over from the previous file of the same day where it had them (the stored backtest / live days); arm 3 is the
replica on every day (one consistent series). The truth block (final rank, votes) is never an input; it comes from the warehouse.
Also writes results/structural/backtest_v2.json: coverage, the calibration per month and its out-of-sample check (per-day sum of
pred_votes vs real, per-launch log error), and the replica's agreement with the stored arm-3 backtest.
usage: python struct_bt_write.py <oos.parquet>"""
import glob, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))   # experiments/ (pipeline package)
import structural_shortlist as SS
BT = os.path.join(SS.OUT, "backtest")


def calib(O):
    """{month: (a, b, smear, n_rows)} fitted on rows of months before it."""
    out = {}
    for m in sorted(O.loc[O.day >= "2026-01-01", "mon"].unique()):
        P = O[(O.day < f"{m}-01") & O.votes.notna() & (O.votes >= 0)]
        y = np.log1p(P.votes.astype(float)); x = P.arm3_ref.astype(float)
        b, a = np.polyfit(x, y, 1); r = y - (a + b * x)
        out[m] = (float(a), float(b), float(np.mean(np.exp(r))), int(len(P)))
    return out


def main(oos):
    from pipeline import warehouse
    W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str); W = W.sort_values("updated_at").drop_duplicates("id", keep="last").set_index("id")
    O = pd.read_parquet(oos); O["id"] = O.id.astype(str); O["day"] = O.day.astype(str).str[:10]; O["mon"] = O.day.str[:7]
    C = calib(O); T = O[O.day >= "2026-01-01"].copy()
    T["pred_votes"] = [C[m][2] * np.expm1(C[m][0] + C[m][1] * s) for m, s in zip(T.mon, T.arm3_ref)]
    prev = {}
    for f in glob.glob(os.path.join(BT, "*.json")):
        d = json.load(open(f)); prev[d["day"]] = {r["id"]: r.get("score_arm2") for r in d["launches"]}
    files, chk, ag = 0, [], []
    for d, g in T.groupby("day"):
        a2 = prev.get(d, {})
        L = pd.DataFrame({"id": g.id.values, "name": g.id.map(W.name).values, "score_arm3": g.arm3_ref.values,
                          "score_arm2": [a2.get(i) if a2.get(i) is not None else np.nan for i in g.id]})
        TR = pd.DataFrame({"id": g.id.values, "final_rank": g.dailyRank.values, "votes": g.id.map(W.votes).values})
        out = SS.day_file(d, "backtest month-forward 2026, arm-3 replica (struct_bt_vm.py; trained on months before the day's month)", L, TR)
        pv = dict(zip(g.id, g.pred_votes))
        for r in out["launches"]:
            r["pred_votes"] = round(float(pv[r["id"]]), 1)
        out["pred_votes_method"] = (f"month-forward calibration fitted on {C[d[:7]][3]} OOS rows of earlier months: "
                                    f"expm1({C[d[:7]][0]:.4f} + {C[d[:7]][1]:.4f} * score) * {C[d[:7]][2]:.4f}")
        out["arm2_note"] = "arm-2 scores carried over from the stored backtest / live file where it had them; null elsewhere"
        json.dump(out, open(os.path.join(BT, f"{d}.json"), "w")); files += 1
        v = g.id.map(W.votes).astype(float)
        if v.notna().sum() >= 10:
            chk.append({"day": d, "sum_pred": float(g.pred_votes.sum()), "sum_real": float(v.sum()),
                        "mae_log": float(np.nanmean(np.abs(np.log1p(g.pred_votes.values) - np.log1p(v.values))))})
    # agreement with the stored arm-3 backtest (Apr-Oct 2026)
    st = os.path.join(HERE, "results", "arm3_vs_arm2_preds.parquet")
    if os.path.exists(st):
        A = pd.read_parquet(st); A["id"] = A.id.astype(str); M = T.merge(A[["id", "arm3"]], on="id")
        ag = {"rows": int(len(M)), "spearman": round(float(M.arm3_ref.rank().corr(M.arm3.rank())), 4)}
    K = pd.DataFrame(chk); days = sorted(T.day.unique())
    allday = pd.date_range("2026-01-01", days[-1]).strftime("%Y-%m-%d")
    res = {"experiment": "STRUCT-BT26", "asked": "orchestrator 14:33Z Nov 25", "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
           "files_written": files, "first": days[0], "last": days[-1], "days": len(days),
           "missing_days": [x for x in allday if x not in set(days)], "launch_rows": int(len(T)),
           "replica_vs_stored_arm3": ag,
           "calibration_by_month": {m: {"a": round(c[0], 4), "b": round(c[1], 4), "smear": round(c[2], 4), "fit_rows": c[3]} for m, c in C.items()},
           "pred_votes_check": {"days": int(len(K)),
                                "median_day_ratio_pred_over_real": round(float((K.sum_pred / K.sum_real).median()), 3) if len(K) else None,
                                "p10_p90_day_ratio": [round(float((K.sum_pred / K.sum_real).quantile(q)), 3) for q in (0.1, 0.9)] if len(K) else None,
                                "median_launch_abs_log_error": round(float(K.mae_log.median()), 3) if len(K) else None},
           "leak_checks": "scores month-forward (train < month start); the votes calibration for month m uses only OOS rows of earlier months; "
                          "truth (final rank, votes) is only in each file's truth block and in this check"}
    json.dump(res, open(os.path.join(SS.OUT, "backtest_v2.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "calibration_by_month"}, default=str)[:3000])


if __name__ == "__main__":
    main(sys.argv[1])
