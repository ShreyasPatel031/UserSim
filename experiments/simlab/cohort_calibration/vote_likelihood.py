"""LIKELIHOOD TO VOTE (PREREG.md addendum): frozen per-person p vs whether the person voted. Aggregates only.
    python vote_likelihood.py <store dir> <out json> <day> [<day> ...]"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP
ST, OUT = sys.argv[1:3]; DAYS = sys.argv[3:]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); COMPLETE = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True); last_read = U.groupby("person_id").ft.max()
VOTED = set(zip(U.person_id, U.target_id))
CUTS = sorted(x.split("/")[-1][:10] for x in subprocess.run(["gsutil", "ls", f"{B}/tmp/e5/private/segments/"], capture_output=True, text=True).stdout.split() if x.endswith(".parquet") and "latest" not in x)
_c = {}
def seg(D):
    c = max([x for x in CUTS if x <= D] or [CUTS[0]])
    if c not in _c: _c[c] = pd.read_parquet(io.BytesIO(gcat(f"{B}/tmp/e5/private/segments/{c}.parquet"))).set_index("person_id").group.to_dict()
    return c, _c[c]
rows = []
for D in DAYS:
    raw = gcat(f"{B}/tmp/e5/private/backer_pred/{D}.parquet")
    if not raw: continue
    L = pd.read_parquet(io.BytesIO(raw)); L["launch_id"] = L.launch_id.astype(str); close = PP.close_utc(D)
    L = L[L.person_id.isin(COMPLETE) & (L.person_id.map(last_read) > close)].copy()
    if L.empty: continue
    cut, G = seg(D); L["y"] = [int((p, l) in VOTED) for p, l in zip(L.person_id, L.launch_id)]; L["g"] = L.person_id.map(G); L["day"] = D; L["cut"] = cut
    rows.append(L[["day", "cut", "launch_id", "g", "p", "y"]])
R = pd.concat(rows).reset_index(drop=True); days = sorted(R.day.unique())
# out-of-sample isotonic + constant baseline, each fit on earlier scored days only
R["p_iso"] = np.nan; R["p_const"] = np.nan
for D in days:
    tr = R[R.day < D]; m = R.day == D
    if len(tr) < 1000 or tr.y.sum() < 20: continue
    iso = IsotonicRegression(out_of_bounds="clip", y_min=1e-4, y_max=1 - 1e-4).fit(tr.p, tr.y); R.loc[m, "p_iso"] = iso.predict(R.loc[m, "p"]); R.loc[m, "p_const"] = tr.y.mean()
clip = lambda p: np.clip(p, 1e-4, 1 - 1e-4)
def scores(df, col):
    p = clip(df[col].values); y = df.y.values
    return {"brier": float(np.mean((p - y) ** 2)), "logloss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))}
def reliability(df, col, bins=10):
    x = df[[col, "y"]].dropna().sort_values(col).reset_index(drop=True); qs = [x.iloc[ix] for ix in np.array_split(np.arange(len(x)), bins)]
    pts = [{"mean_p": round(float(q[col].mean()), 4), "observed": round(float(q.y.mean()), 4), "n": int(len(q))} for q in qs if len(q)]
    a = np.array([[q["mean_p"], q["observed"]] for q in pts]); slope = float(np.polyfit(a[:, 0], a[:, 1], 1)[0]) if len(a) > 2 else None
    return {"bins": pts, "slope_observed_on_predicted": round(slope, 3) if slope is not None else None}
def paired(df, a, b, metric):
    d = sorted(df.day.unique())
    def f(x): return scores(x, a)[metric] - scores(x, b)[metric]
    bs = [f(pd.concat([df[df.day == z] for z in rng.choice(d, len(d))])) for _ in range(1000)]
    return [round(f(df), 5), round(float(np.percentile(bs, 2.5)), 5), round(float(np.percentile(bs, 97.5)), 5)]
S = R.dropna(subset=["p_iso"])
out = {"prereg": "PREREG.md addendum (commit 141daf5d)", "rows_scored": int(len(R)), "votes": int(R.y.sum()), "days": days,
       "oos_days (isotonic + constant fit on earlier days)": sorted(S.day.unique()), "rows_oos": int(len(S)), "votes_oos": int(S.y.sum()),
       "raw_p": {**scores(R, "p"), **reliability(R, "p")},
       "oos": {"isotonic": {**scores(S, "p_iso"), **reliability(S, "p_iso")}, "constant": scores(S, "p_const"), "raw_p_same_rows": scores(S, "p"),
               "isotonic minus constant (paired, day bootstrap)": {m: paired(S, "p_iso", "p_const", m) for m in ("brier", "logloss")}},
       "per_day": [{"day": d, "rows": int((R.day == d).sum()), "votes": int(R[R.day == d].y.sum()), "base_rate": round(float(R[R.day == d].y.mean()), 4)} for d in days],
       "by_group": {}}
for g, x in R.groupby("g"):
    if len(x) >= 20 and x.y.sum() >= 20:
        xs = x.dropna(subset=["p_iso"])
        out["by_group"][str(int(g))] = {"rows": int(len(x)), "votes": int(x.y.sum()), "raw_p": scores(x, "p"),
                                        **({"isotonic_oos": scores(xs, "p_iso"), "constant_oos": scores(xs, "p_const"), "reliability_oos": reliability(xs, "p_iso", 5)} if len(xs) >= 20 and xs.y.sum() >= 20 else {})}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps({k: v for k, v in out.items() if k not in ("per_day",)}, indent=1)[:6000])
