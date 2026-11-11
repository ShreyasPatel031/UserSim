"""Early-day vote forecast on months (orchestrator 21:50Z Nov 11, item A): Wayback homepage captures taken on a launch's own
PT day carry latestScore (votes at capture time) and comment counts for that day's posts. Does ranking by votes-at-capture
recover the final daily top 3/5/10, by capture time, over Jul-Oct, and does a learned projection beat raw votes at the same t?
Buckets (hours after 00:00 PT of the launch day): 0-4 (pre-reveal; PH hides counts in the UI before ~04:00 PT but the page
state carries latestScore), 4-5 (reveal to +1h), 5-6, 6-8, 8-12, 12-24. Per (day, bucket) the LAST capture in the bucket is used.
A (day, bucket) qualifies when the capture contains >= 80% of the day's ranked line-up (launches.daily_rank). Launches absent
from the capture rank below every present one (score -inf).
Metrics: daily top 3/5/10 overlap with the final daily rank (x100), within-day Spearman; 95% day-bootstrap CIs.
Learned projection (ridge on -log final daily rank, month-forward: trained on earlier months' captures, scored Aug-Oct):
log1p votes at t, hours since 00:00 PT, their interaction, within-capture vote share and rank, velocity (votes/h since the
previous same-day capture, when there is one; flag otherwise), log1p comments at t, honest pre-launch LM. Paired by
(day, bucket) vs raw votes at the same capture.
    python intraday_wayback.py <workdir: parsed.jsonl launches/ honest_preds.parquet>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

W = sys.argv[1]; rng = np.random.default_rng(0)
BKT = [(0, 4, "0-4h pre-reveal"), (4, 5, "4-5h reveal to +1h"), (5, 6, "5-6h"), (6, 8, "6-8h"), (8, 12, "8-12h"), (12, 24, "12-24h")]
H = pd.read_json(os.path.join(W, "parsed.jsonl"), lines=True); H["post_id"] = H.post_id.astype(str); H["day"] = H.day.astype(str)
H["cap"] = pd.to_datetime(H.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True)
H["capPT"] = H.cap.dt.tz_convert("America/Los_Angeles"); H = H[(H.capture_kind == "home") & (H.day == H.capPT.dt.strftime("%Y-%m-%d"))].copy()
H["hr"] = (H.capPT - pd.to_datetime(H.day).dt.tz_localize("America/Los_Angeles")).dt.total_seconds() / 3600
H = H.dropna(subset=["latestScore"]).drop_duplicates(["capture_ts", "post_id"])
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(W, "launches", "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float)
Hn = pd.read_parquet(os.path.join(W, "honest_preds.parquet"))[["id", "honest"]]; Hn["id"] = Hn.id.astype(str)
L = L.merge(Hn, on="id", how="left")
lineup = {d: g for d, g in L.groupby("day")}

caps = H.groupby(["capture_ts", "day"]).hr.first().reset_index()
caps["bucket"] = None
for a, b, nm in BKT: caps.loc[(caps.hr > a) & (caps.hr <= b), "bucket"] = nm
caps = caps.dropna(subset=["bucket"])
rows, qual = [], []
for (d, bk), g in caps.groupby(["day", "bucket"]):
    ct = g.sort_values("hr").capture_ts.iloc[-1]; hr = g.hr.max()
    if d not in lineup: continue
    ln = lineup[d].copy(); c = H[H.capture_ts == ct].set_index("post_id")
    cov = ln.id.isin(c.index).mean(); qual.append({"day": d, "bucket": bk, "cov": cov})
    if cov < 0.8: continue
    prev = H[(H.day == d) & (H.hr < hr - 0.25)]
    pv = prev.sort_values("hr").groupby("post_id").agg(pv=("latestScore", "last"), ph=("hr", "last"))
    ln["v"] = ln.id.map(c.latestScore); ln["cm"] = ln.id.map(c.comments)
    ln = ln.join(pv, on="id"); ln["vel"] = (ln.v - ln.pv) / (hr - ln.ph); ln["has_vel"] = ln.vel.notna().astype(int)
    ln["vel"] = ln.vel.fillna(0).clip(lower=0); ln["present"] = ln.v.notna().astype(int)
    ln["day"] = d; ln["bucket"] = bk; ln["hr"] = hr; rows.append(ln)
X = pd.concat(rows, ignore_index=True)
Q = pd.DataFrame(qual); qual_tab = Q.groupby("bucket").agg(days_with_capture=("day", "size"), days_cov80=("cov", lambda s: int((s >= 0.8).sum()))).to_dict("index")
print("qualifying", qual_tab, flush=True)
X["lv"] = np.log1p(X.v.fillna(0)); X["lcm"] = np.log1p(X.cm.fillna(0)); X["lvel"] = np.log1p(X.vel)
X["sh"] = X.v.fillna(0) / X.groupby(["day", "bucket"]).v.transform(lambda s: s.fillna(0).sum() + 1)
X["vr"] = X.groupby(["day", "bucket"]).lv.rank(ascending=False, pct=True)
X["hon"] = X.honest.fillna(X.honest.mean()); X["has_lm"] = X.honest.notna().astype(int); X["lvh"] = X.lv * X.hr
X["raw"] = np.where(X.present == 1, X.v.fillna(0), -1.0) + 1e-6 * X.hon
FE = ["lv", "hr", "lvh", "sh", "vr", "lvel", "has_vel", "lcm", "hon", "has_lm", "present"]
X["m"] = X.day.str[:7]; X["learned"] = np.nan
for m in sorted(X.m.unique())[1:]:
    tr, te = X.m < m, X.m == m
    mu, sd = X.loc[tr, FE].mean(), X.loc[tr, FE].std() + 1e-9
    rg = Ridge(alpha=10.0).fit((X.loc[tr, FE] - mu) / sd, -np.log(X.loc[tr, "rank"])); X.loc[te, "learned"] = rg.predict((X.loc[te, FE] - mu) / sd)


def per(g, s):
    o = [len(set(g.nlargest(k, s).id) & set(g.nsmallest(k, "rank").id)) / k * 100 for k in (3, 5, 10)]
    return o + [spearmanr(g[s], -g["rank"]).correlation * 100]


def boot(v, B=4000):
    v = np.asarray(v, float); bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B)])
    return [[round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(v.shape[1])]


res = {"design": __doc__.split("\n    python")[0], "qualifying_days": qual_tab, "raw_jul_oct": {}, "aug_oct_paired": {}}
K = ["top3", "top5", "top10", "spearman"]
for _, _, bk in BKT:
    g = X[X.bucket == bk]
    if not len(g): continue
    R = np.array([per(gg, "raw") for _, gg in g.groupby("day")])
    res["raw_jul_oct"][bk] = {"days": len(R), **dict(zip(K, boot(R)))}
    g2 = g[g.learned.notna()]
    if g2.day.nunique() >= 3:
        A = np.array([per(gg, "raw") for _, gg in g2.groupby("day")]); Bm = np.array([per(gg, "learned") for _, gg in g2.groupby("day")])
        Lm = np.array([per(gg, "hon") for _, gg in g2.groupby("day")])
        res["aug_oct_paired"][bk] = {"days": len(A), "raw": dict(zip(K, boot(A))), "learned": dict(zip(K, boot(Bm))),
                                     "learned - raw": dict(zip(K, boot(Bm - A))), "LM only": dict(zip(K, boot(Lm)))}
os.makedirs(os.path.join(W, "out"), exist_ok=True)
json.dump(res, open(os.path.join(W, "out", "intraday_wayback.json"), "w"), indent=1)
print(json.dumps(res["raw_jul_oct"], indent=0)); print(json.dumps(res["aug_oct_paired"], indent=0))
