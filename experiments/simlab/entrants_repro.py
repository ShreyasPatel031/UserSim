"""Independent reproduction of PH ops' weekly board with predicted entrants (b1e4f767, weekly_board_pred.py) - E5, Nov 14.
Board for day D of a Mon-Sun week (published the morning of D, after the 00:05 forecast): (a) launches of days < D in the week by final
votes; (b) (a) + D's line-up at calibrated arm-2 predicted votes, calibration log1p(votes) = a + b * pred fit on rows of months < D's
month only (identity when there is no earlier month: leak check), arm-2 preds = walk-forward 'both' (PH ops' X.parquet dump). Truth =
weekly_rank <= k from the stored day files. Also (b_MTW): insert only when D is Mon / Tue / Wed. Paired week bootstrap. Counts only.
    python entrants_repro.py <X.parquet> <days dir> <out json>"""
import json, sys, glob, os
import numpy as np, pandas as pd
Xp, DD, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
X = pd.read_parquet(Xp); X["id"] = X.id.astype(str)
rows = []
for f in glob.glob(f"{DD}/2026-*.json"):
    d = os.path.basename(f)[:10]
    for p in json.load(open(f)): rows.append({"id": str(p["id"]), "day": d, "votes": p.get("votesCount"), "wr": p.get("weeklyRank")})
V = pd.DataFrame(rows).drop_duplicates("id"); X = X.merge(V[["id", "votes", "wr"]], on="id", how="left"); X["mon"] = X.day.str[:7]
cal = {}
for m in sorted(X.mon.unique()):
    tr = X[(X.mon < m) & X.votes.notna()]
    cal[m] = (0.0, 1.0) if tr.empty else tuple(np.polyfit(tr.both, np.log1p(tr.votes), 1)[::-1])
X["pv"] = [np.expm1(cal[m][0] + cal[m][1] * b) for m, b in zip(X.mon, X.both)]
V["dt"] = pd.to_datetime(V.day); V["ws"] = V.dt - pd.to_timedelta(V.dt.dt.weekday, "D")
X["dt"] = pd.to_datetime(X.day); X["ws"] = X.dt - pd.to_timedelta(X.dt.dt.weekday, "D")
weeks = sorted(w for w in X.ws.unique() if (X.ws == w).sum() and X[X.ws == w].day.nunique() == 7 and X[X.ws == w].day.min() >= "2026-04-06")
R = []
for w in weeks:
    W = V[V.ws == w]; truth = {k: set(W[W.wr <= k].id) for k in (3, 5, 10)}; XW = X[X.ws == w]
    for i in range(7):
        D = w + pd.Timedelta(days=i); prev = W[W.dt < D].sort_values("votes", ascending=False); ent = XW[XW.dt == D]
        a = prev.id.tolist()
        b = pd.concat([prev[["id", "votes"]], ent[["id"]].assign(votes=ent.pv.values)]).sort_values("votes", ascending=False).id.tolist()
        r = {"week": str(w.date()), "dow": i}
        for k in (3, 5, 10):
            h = lambda o: len(set(o[:k]) & truth[k]) / k * 100
            r[f"a{k}"], r[f"b{k}"] = h(a), h(b); r[f"m{k}"] = h(b) if i <= 2 else h(a)
        R.append(r)
R = pd.DataFrame(R)
def wb(df, x, y):
    g = df.groupby("week")[[x, y]].mean(); d = (g[y] - g[x]).values; bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
    return [round(float(d.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)]
out = {"weeks": len(weeks), "board days": len(R), "calibration": {m: [round(a, 3), round(b, 3)] for m, (a, b) in cal.items()}}
for lab, df in [("all", R)] + [(n, R[R.dow == i]) for i, n in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]:
    out[lab] = {f"top{k}": {"a": round(df[f"a{k}"].mean(), 1), "b": round(df[f"b{k}"].mean(), 1), "b-a": wb(df, f"a{k}", f"b{k}")} for k in (3, 5, 10)}
out["Mon-Wed only vs always (all days)"] = {f"top{k}": {"mtw": round(R[f"m{k}"].mean(), 1), "mtw - always": wb(R, f"b{k}", f"m{k}"), "mtw - a": wb(R, f"a{k}", f"m{k}")} for k in (3, 5, 10)}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps({k: v for k, v in out.items() if k != "calibration"}))
