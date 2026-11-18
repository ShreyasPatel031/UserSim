"""Audit of the published weekly-board gain "+2.5 / +5.2 / +7.3" (orchestrator 23:00Z Nov 14): (b) current board + D's 00:05
line-up at calibrated arm-2 predicted votes vs (a) current board, share of the board's top k in the true weekly top k, all
board days of 29 full weeks Apr 6 - Oct 25 2026. Held data only; counts only.

Variants (each changes one thing from the one before)
  V0  as published: weekly_board_pred.py logic; calibration month-forward (months < D's month); truth = warehouse weekly_rank
  V1  truth = results/web/truth_weekly.json (E5's single truth source; periods with status ok)
  V2  V1 + calibration fitted only on launches dated before the week's Monday (strict: nothing from the week itself)
  V3  V2 + launches without an arm-2 prediction left out of (b) instead of entering at the day's median prediction
Leak checks (asserted): the predictions are the stored arm-2 month-forward backtest (history_retrain_decomp_preds_arm2.parquet,
  trained on months < D's month, arm2_explain.py line 16); calibration rows dated before the week (V2, V3); the inserted day's
  values use no final votes of that day; (a) and (b) are scored on the same weeks and days (paired).
Intervals: paired week bootstrap (4000) of the mean over board days.
usage: python weekly_board_audit.py X.parquet L.parquet truth_weekly.json -> results/weekly_board_audit.{json,md}"""
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
X = pd.read_parquet(sys.argv[1])[["id", "both"]]; X["id"] = X.id.astype(str)
L0 = pd.read_parquet(sys.argv[2]); L0["id"] = L0.id.astype(str)
TW = json.load(open(sys.argv[3]))["periods"]
P = pd.read_parquet(os.path.join(HERE, "results", "history_retrain_decomp_preds_arm2.parquet")); P["id"] = P.id.astype(str)
chk = X.merge(P[["id", "both"]], on="id", suffixes=("", "_s"))
assert len(chk) == len(X) and (chk.both - chk.both_s).abs().max() < 1e-9, "X.both is not the stored arm-2 backtest"
L0 = L0.merge(X, on="id", how="left"); L0["mon"] = L0.day.str[:7]; L0["lv"] = np.log1p(L0.votes.astype(float))
L0["wk"] = pd.to_datetime(L0.day).dt.to_period("W-SUN").apply(lambda p: str(p.start_time.date()))
KS = (3, 5, 10)
weeks = [w for w in sorted(L0.wk.unique()) if "2026-04-06" <= w <= "2026-10-19"]


def fit(prev):
    if len(prev) >= 200:
        b, a = np.polyfit(prev.both, prev.lv, 1); return a, b, len(prev), prev.day.max()
    return 0.0, 1.0, 0, None


def board_days(strict_cal, truth_src, median_fill):
    L = L0.copy(); L["cal"] = np.nan; info = {}
    if strict_cal:
        for w in weeks:
            prev = L[(L.day < w) & L.both.notna() & (L.mon >= "2026-04")]
            a, b, n, mx = fit(prev); assert mx is None or mx < w, "calibration row inside the week"
            k = L.wk == w; L.loc[k, "cal"] = a + b * L.loc[k, "both"]; info[w] = [round(a, 3), round(b, 3), n, mx]
    else:
        for m in sorted(L.mon.unique()):
            prev = L[(L.mon < m) & L.both.notna() & (L.mon >= "2026-04")]
            a, b, n, mx = fit(prev); k = L.mon == m; L.loc[k, "cal"] = a + b * L.loc[k, "both"]; info[m] = [round(a, 3), round(b, 3), n, mx]
    if median_fill:
        L["cal"] = L.cal.fillna(L.groupby("day").cal.transform("median"))
    L["pv"] = np.expm1(L.cal)
    R = []
    for w in weeks:
        Z = L[L.wk == w]
        if truth_src == "warehouse":
            truth = {k: set(Z[Z.weekly_rank <= k].id) for k in KS}
        else:
            t = TW.get(w)
            if not t or t.get("status") != "ok":
                continue
            rk = {str(i): r for i, r in t["ranks"].items()}
            truth = {k: {i for i, r in rk.items() if r <= k} for k in KS}
        for D in sorted(Z.day.unique()):
            prev = Z[Z.day < D].assign(v=lambda z: z.votes.astype(float))
            today = Z[(Z.day == D) & Z.pv.notna()]
            ins = today.assign(v=today.pv)
            assert not np.allclose(ins.v.values, today.votes.astype(float).values) or len(ins) == 0, "inserted values equal final votes"
            B = {"a": prev, "b": pd.concat([prev, ins])}
            R.append({"week": w, "day": D, "dow": pd.Timestamp(D).day_name()[:3],
                      **{f"{n}_{k}": len(set(b.nlargest(k, "v").id) & truth[k]) / k for n, b in B.items() for k in KS}})
    return pd.DataFrame(R), info


def paired(R, k, B_=4000, seed=0):
    d = (R[f"b_{k}"] - R[f"a_{k}"]); dm = d.groupby(R.week).mean(); ws = dm.index.values; rng = np.random.default_rng(seed)
    bs = [dm.loc[rng.choice(ws, len(ws))].mean() for _ in range(B_)]
    return {"a": round(100 * R[f"a_{k}"].mean(), 1), "b": round(100 * R[f"b_{k}"].mean(), 1), "diff": round(100 * d.mean(), 1),
            "ci": [round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]}


V = {"V0_published": (False, "warehouse", True), "V1_truth_file": (False, "truth_file", True),
     "V2_strict_calibration": (True, "truth_file", True), "V3_no_median_fill": (True, "truth_file", False)}
out = {"method": __doc__, "variants": {}}
md = ["# Audit: weekly board gain from inserting the next day's 00:05 line-up", "",
      "Paired (b) - (a), share of the board's top k in the true weekly top k, mean over board days; week bootstrap 95%.", "",
      "| variant | weeks | board days | top 3 | top 5 | top 10 |", "|---|---|---|---|---|---|"]
for name, (sc, ts, mf) in V.items():
    R, info = board_days(sc, ts, mf)
    res = {"weeks": int(R.week.nunique()), "board_days": int(len(R)), **{f"top{k}": paired(R, k) for k in KS},
           "by_weekday": {dn: {f"top{k}": paired(R[R.dow == dn], k) for k in KS} for dn in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
           "excluding_monday": {f"top{k}": paired(R[R.dow != "Mon"], k) for k in KS}, "calibration": info}
    out["variants"][name] = res
    cell = lambda r: f"{r['diff']:+} [{r['ci'][0]:+}, {r['ci'][1]:+}] ({r['a']} -> {r['b']})"
    md.append(f"| {name} | {res['weeks']} | {res['board_days']} | " + " | ".join(cell(res[f'top{k}']) for k in KS) + " |")
    print(name, res["weeks"], res["board_days"], {k: res[f"top{k}"] for k in KS})
open(os.path.join(HERE, "results", "weekly_board_audit.json"), "w").write(json.dumps(out, indent=1, default=str))
open(os.path.join(HERE, "results", "weekly_board_audit.md"), "w").write("\n".join(md) + "\n")
