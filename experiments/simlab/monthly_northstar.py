"""Monthly north star backtest (orchestrator 21:25Z Nov 11): forecast the final monthly top 3/5/10 at each day-end of the month.
Monthly rank   launches.monthly_rank (warehouse, final, PH's monthly leaderboard rank; the month = PT calendar month of the
               launch day). Complete months held: Jan-Oct 2026 (Nov partial).
Day-end votes  only dated source for past months: the Wayback homepage archive's launchDayScore (PH's frozen launch-day score,
               read from captures taken after the launch day ended; identical across every such capture). Coverage: Jul-Oct
               (~40-55% of launches, ~100% of monthly top 10); May-Jun only a few top posts; none before May. The warehouse
               `votes` is FINAL (read at fetch time) - using it as "votes so far" is a LEAK; shown only as a flagged ceiling.
Inputs at the call (end of PT day c): for launches with day <= c - daily rank (final at day end), launch-day score where held
               (imputed from daily rank + month when missing, with a missing flag), comments by the end of the launch day (exact
               created_at, thread dump), honest pre-launch LM, day of week, days remaining in the month. Weekly rank not used
               (its field is final; it is only known at week end).
Scorers        R0 daily rank only; R1 launch-day score (votes so far at day end; older launches keep their day-end score);
               R2 launch-day score x learned post-day growth (median final/launch-day ratio by daily-rank bucket x weekday x
               days-to-month-end bucket, fitted on earlier months); R3 learned model (ridge on -log monthly rank, month-forward);
               R4 votes so far at the call: latest Wayback latestScore captured after the launch day and before the call
               (falls back to the launch-day score); LEAK final votes (ceiling, flagged).
Calls          every day-end of the month (candidates = launches so far); reported at week-ends (day 7, 14, 21, 28) and month end.
               top-k = overlap of predicted top k among launched-so-far with the final monthly top k (x100); "launched" = share of
               the final top k already launched by the call (the ceiling at that call).
Intervals      months are few (10 for R0, 4 for R1-R3: Jul-Oct). CIs = bootstrap over months; with 4 months they are indicative only.
    python monthly_northstar.py <workdir: launches/ parsed.jsonl honest_preds.parquet comments dump page*.jsonl.gz> <ph_predict dir>
"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge

W, PHD = sys.argv[1:3]; sys.path.insert(0, PHD)
rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(W, "launches", "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.monthly_rank.notna() & L.daily_rank.notna() & (L.day < "2026-11")].copy()
L["id"] = L.id.astype(str); L["m"] = L.day.str[:7]; L["v"] = pd.to_numeric(L.votes, errors="coerce").astype(float)
L["mr"] = L.monthly_rank.astype(float); L["dr"] = L.daily_rank.astype(float)
L.loc[L.mr > 2000, "mr"] = np.nan                                     # one corrupt Feb value (2687 in a 505-launch month)
L = L.dropna(subset=["mr"])
dt = pd.to_datetime(L.day); L["dow"] = dt.dt.dayofweek; L["dom"] = dt.dt.day
L["dleft"] = (dt + pd.offsets.MonthEnd(0) - dt).dt.days

# launch-day score from Wayback captures taken after the day ended
H = pd.read_json(os.path.join(W, "parsed.jsonl"), lines=True); H["post_id"] = H.post_id.astype(str)
H = H[H.launchDayScore.notna() & (H.launchDayScore > 0) & (H.day.astype(str) > "")].copy()
H["cap"] = pd.to_datetime(H.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True)
H["dend"] = pd.to_datetime(H.day.astype(str)).dt.tz_localize("America/Los_Angeles") + pd.Timedelta(days=1)
lds = H[H.cap >= H.dend].groupby("post_id").launchDayScore.median()
L["lds"] = L.id.map(lds); L["has_lds"] = L.lds.notna().astype(int)
CAP = H[H.cap >= H.dend][["post_id", "cap", "latestScore"]].dropna().sort_values("cap")   # dated votes-so-far after launch day

# comments by end of launch day (exact created_at)
import ph_comments as PC
cnt = {}
for f in glob.glob(os.path.join(W, "page*.jsonl.gz")):
    for line in gzip.open(f):
        x = json.loads(line)
        try: info, rr = PC.parse(json.loads(x["html"]))
        except Exception: continue
        if info["slug"]: cnt.setdefault(info["slug"], {}).update({r["comment_id"]: r["created"] for r in rr})
dend = {s: pd.Timestamp(d + " 00:00", tz="America/Los_Angeles") + pd.Timedelta(days=1) for s, d in zip(L.slug, L.day)}
L["c_day"] = [sum(pd.Timestamp(t) <= dend[s] for t in cnt[s].values() if t) if s in cnt else np.nan for s in L.slug]
L["has_c"] = L.c_day.notna().astype(int); L["c_day"] = L.c_day.fillna(0)
Hn = pd.read_parquet(os.path.join(W, "honest_preds.parquet"))[["id", "honest"]]; Hn["id"] = Hn.id.astype(str)
L = L.merge(Hn, on="id", how="left"); L["has_lm"] = L.honest.notna().astype(int); L["honest"] = L.honest.fillna(L.honest.mean())
print("launches", len(L), "lds held", int(L.has_lds.sum()), "comments held", int(L.has_c.sum()), flush=True)

# impute launch-day score where missing: log lds ~ log daily rank + month (fitted on held rows of months <= the call month;
# daily rank is known at day end)
L["l_lds"] = np.log(L.lds)
held = L[L.has_lds == 1]
fit = Ridge(alpha=1.0).fit(np.c_[np.log(held.dr), held.dow], held.l_lds)
L["l_lds_imp"] = np.where(L.has_lds == 1, L.l_lds, fit.predict(np.c_[np.log(L.dr), L.dow]))
L["drb"] = pd.cut(L.dr, [0, 1, 3, 5, 10, 20, 1e9], labels=False); L["dlb"] = pd.cut(L.dleft, [-1, 3, 10, 20, 40], labels=False)
months = sorted(L.m.unique()); M_LDS = [m for m in months if m >= "2026-07"]


def growth_pred(train, test):
    t = train[train.has_lds == 1].copy(); t["g"] = np.log(t.v / t.lds)
    g1 = t.groupby(["drb", "dow", "dlb"]).g.median(); g2 = t.groupby(["drb"]).g.median(); g0 = t.g.median() if len(t) else 0.0
    out = []
    for a, b, c in zip(test.drb, test.dow, test.dlb):
        out.append(g1.get((a, b, c), g2.get(a, g0)))
    return test.l_lds_imp.to_numpy() + np.nan_to_num(np.array(out, float), nan=g0)


FEATS = ["l_lds_imp", "has_lds", "ldr", "dow", "dleft", "lc", "has_c", "honest", "has_lm"]
L["ldr"] = np.log(L.dr); L["lc"] = np.log1p(L.c_day)

scores = {}
for m in months:
    te = L[L.m == m].copy(); tr = L[L.m < m]
    te["R0"] = -te.ldr + 1e-3 * te.l_lds_imp; te["R1"] = te.l_lds_imp
    te["LEAK_final_votes"] = np.log(te.v.fillna(1))
    te["R2"] = growth_pred(tr, te) if len(tr) else te.l_lds_imp
    if len(tr) > 200:
        mu, sd = tr[FEATS].mean(), tr[FEATS].std() + 1e-9
        rg = Ridge(alpha=10.0).fit((tr[FEATS] - mu) / sd, -np.log(tr.mr)); te["R3"] = rg.predict((te[FEATS] - mu) / sd)
    else:
        te["R3"] = np.nan
    scores[m] = te

CALLS = {"day 7": 7, "day 14": 14, "day 21": 21, "day 28": 28, "month end": 31}
res = {"design": __doc__.split("\n    python")[0], "months": months, "lds_months": M_LDS, "per_month": {}, "tables": {}}
rows = []
for m, te in scores.items():
    for cn, cd in CALLS.items():
        sub = te[te.dom <= cd]
        for k in (3, 5, 10):
            truth = set(te.nsmallest(k, "mr").id)
            r = {"m": m, "call": cn, "k": k, "launched": len(truth & set(sub.id)) / k * 100}
            cts = pd.Timestamp(f"{m}-01", tz="America/Los_Angeles") + pd.Timedelta(days=min(cd, te.dom.max()))
            c = CAP[(CAP.cap <= cts) & CAP.post_id.isin(set(sub.id))].groupby("post_id").latestScore.last()
            sub = sub.copy(); sub["R4"] = np.log(sub.id.map(c)).fillna(sub.l_lds_imp)
            for s in ("R0", "R1", "R2", "R3", "R4", "LEAK_final_votes"):
                if sub[s].notna().all() and len(sub) >= k:
                    r[s] = len(set(sub.nlargest(k, s).id) & truth) / k * 100
            rows.append(r)
Rw = pd.DataFrame(rows)


def mboot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0: return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1), int(len(v))]


for span, ms in (("Jul-Oct (launch-day score held)", M_LDS), ("Mar-Oct", [m for m in months if m >= "2026-03"]), ("Jan-Oct", months)):
    T = {}
    for cn in CALLS:
        for k in (3, 5, 10):
            g = Rw[(Rw.call == cn) & (Rw.k == k) & Rw.m.isin(ms)]
            T[f"{cn} top{k}"] = {c: mboot(g[c]) for c in ("launched", "R0", "R1", "R2", "R3", "R4", "LEAK_final_votes") if c in g}
            if span.startswith("Jul"):
                for a in ("R1", "R2", "R3", "R4"):
                    T[f"{cn} top{k}"][f"{a} - R0 (paired by month)"] = mboot(g[a] - g["R0"])
    res["tables"][span] = T
res["per_month"] = Rw.to_dict("records")

# how much of the monthly top 10 is decided on launch day (Jul-Oct)
D = L[L.m.isin(M_LDS)]
dec = {}
for m, g in D.groupby("m"):
    top = g.nsmallest(10, "mr"); held_ = g[g.has_lds == 1]
    dec[m] = {"top10_by_launch_day_score_in_final_top10": len(set(held_.nlargest(10, "lds").id) & set(top.id)),
              "top10_by_daily_rank_in_final_top10": len(set(g.nsmallest(10, "dr").id) & set(top.id)),
              "median_share_of_final_votes_after_launch_day_top10": round(float(np.median(1 - top.lds / top.v)), 3) if top.lds.notna().all() else None,
              "top10_lds_held": int(top.has_lds.sum())}
t10 = D[(D.mr <= 10) & (D.has_lds == 1)]; rest = D[(D.mr > 10) & (D.has_lds == 1)]
dec["pooled"] = {"top10 share of final votes after launch day, median [IQR]": [round(float(x), 3) for x in np.percentile(1 - t10.lds / t10.v, [50, 25, 75])],
                 "others (with launch-day score) median [IQR]": [round(float(x), 3) for x in np.percentile(1 - rest.lds / rest.v, [50, 25, 75])],
                 "n_top10": int(len(t10)), "n_others": int(len(rest))}
res["decided_on_launch_day"] = dec
os.makedirs(os.path.join(W, "out"), exist_ok=True)
json.dump(res, open(os.path.join(W, "out", "monthly_northstar.json"), "w"), indent=1, default=str)
for span, T in res["tables"].items():
    print("==", span)
    for k, v in T.items(): print(k, v)
print(json.dumps(dec, indent=1))
