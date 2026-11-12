"""Voter-based 00:05 forecast harness (orchestrator 22:53Z Nov 12; re-run with one command on a new store snapshot).
Days: Oct 29-31, Nov 2, 3, 4, 8, 9, 10, 11. Line-up and clean score: PH agent's clean_live_rows_nosite.parquet (clean_v3_nosite, as live).
Covered people = complete persons in the store. Pair model P(person upvotes launch): logistic regression on [ln(1+upvotes 30d),
ln(1+upvotes 90d), days since last upvote, topic-taste match, follows the hunter, is the hunter], trained on the 7 launch days before the
test day (features at each training day from history before that day; all negatives of active people subsampled 10%).
Expected covered votes E(L) = sum over active covered people of P. Combined = z(clean) + w z(ln(E + 0.1)), w leave-one-day-out from
{0, .25, .5, 1, 2}. EDGES env: none / hunter / hunter_maker (follows of the hunter, + the first named maker); "followers_feature_only"
= the launch-level sum over active covered followers of ln(1+upvotes 90d), added to clean instead of E. Timing: STRICT = only upvotes / follows from reads fetched before 00:00 PT of the test day; LENIENT = every read of
an upvote on an earlier day's launch (what a fresh read the night before would give). HIDDEN: votes on today's launches seen in reads
fetched 00:05-04:00 PT of the day (re-reads in the hidden window). Coverage curve: covered people subsampled to 10/20/30/41% of votes
(5 draws). Truth: official daily rank. Paired day bootstrap vs clean alone.
    python voter_harness.py <store dir (events/persons parquet)> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
V3, CLEAN, LDIR, SALTD, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
DAYS = ["2026-10-29", "2026-10-30", "2026-10-31", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float); L["votes"] = pd.to_numeric(L.votes, errors="coerce")
L["tops"] = [json.loads(s) if isinstance(s, str) and s.startswith("[") else [] for s in L.topics]
L["hunter"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]
TOP = pd.Series([t for ts in L.tops for t in ts]).value_counts().index[:40].tolist(); TI = {t: i for i, t in enumerate(TOP)}
lday = dict(zip(L.id, L.day)); ltop = {i: [TI[t] for t in ts if t in TI] for i, ts in zip(L.id, L.tops)}; lhun = dict(zip(L.id, L.hunter))
LT = pd.DataFrame([(i, j) for i, js in ltop.items() for j in js], columns=["target_id", "j"])
def first_maker(m):
    try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
    except Exception: ms = []
    ms = [x for x in ms if x and not str(x).startswith("[")]; return pid(ms[0]) if ms else None
lmak = {i: first_maker(m) for i, m in zip(L.id, L.makers)}
EDGES = os.environ.get("EDGES", "hunter")   # none | hunter | hunter_maker
start = lambda d: pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id", "fetched_at"])
E = E[E.person_id.isin(COV)]; E["fetched_at"] = pd.to_datetime(E.fetched_at, utc=True)
U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()]
FO = E[(E.kind == "follows") & E.target_id.isin(set(L.hunter.dropna()) | {v for v in lmak.values() if v})][["person_id", "target_id", "fetched_at"]]
C = pd.read_parquet(CLEAN); C["id"] = C.id.astype(str); C = C[C.day.isin(DAYS)]
# coverage of each test launch's votes by covered people (truth side, any read)
cov_l = U[U.lday.isin(DAYS)].groupby("target_id").person_id.nunique()
def feats(day, H, people=None):
    """person features at `day` from history H (upvotes with lday < day)."""
    h = H[H.lday < day]; d0 = pd.Timestamp(day)
    dd = (d0 - pd.to_datetime(h.lday)).dt.days
    g = pd.DataFrame({"p": h.person_id.values, "dd": dd.values, "t": h.target_id.values})
    act = g.groupby("p").agg(n30=("dd", lambda s: (s <= 30).sum()), n90=("dd", lambda s: (s <= 90).sum()), last=("dd", "min"))
    act = act[act.n90 > 0]
    if people is not None: act = act[act.index.isin(people)]
    tv = np.zeros((len(act), len(TOP)), np.float32); ix = pd.Series(np.arange(len(act)), index=act.index)
    g90 = g[(g.dd <= 90) & g.p.isin(act.index)].merge(LT, left_on="t", right_on="target_id")
    if len(g90): np.add.at(tv, (ix[g90.p].values, g90.j.values), 1.0)
    tv /= np.maximum(tv.sum(1, keepdims=True), 1)
    return act, tv, ix
def pair_X(act, tv, lineup, follows):
    rows = []
    for i in lineup:
        oh = np.zeros(len(TOP), np.float32); oh[ltop.get(i, [])] = 1
        h = lhun.get(i); fs = set(follows.get(h, set())) if h and EDGES != "none" else set()
        if EDGES == "hunter_maker" and lmak.get(i): fs |= follows.get(lmak[i], set())
        fh = act.index.isin(fs)
        rows.append(np.column_stack([np.log1p(act.n30.values), np.log1p(act.n90.values), np.log1p(act["last"].values), tv @ oh / max(oh.sum(), 1),
                                     fh.astype(float), (act.index == h).astype(float) if h and EDGES != "none" else np.zeros(len(act))]))
    return rows
def expected(day, mode, keep=None):
    cut = start(day); H = U if mode == "lenient" else U[U.fetched_at < cut]
    F = FO if mode == "lenient" else FO[FO.fetched_at < cut]; follows = F.groupby("target_id").person_id.agg(set).to_dict()
    tr_days = sorted(d for d in L.day.unique() if d < day)[-7:]; Xs, ys = [], []
    for t in tr_days:
        act, tv, _ = feats(t, H); lu = L[L.day == t].id.tolist()
        if not len(act): continue
        voted = H[H.lday == t].groupby("target_id").person_id.agg(set).to_dict()
        for i, X in zip(lu, pair_X(act, tv, lu, follows)):
            y = act.index.isin(voted.get(i, set())).astype(int); m = (y == 1) | (rng.random(len(y)) < 0.1)
            Xs.append(X[m]); ys.append(y[m])
    lu = C[C.day == day].id.tolist()
    if not Xs or sum(int(y.sum()) for y in ys) < 20: return {i: 0.0 for i in lu}, 0
    X, y = np.vstack(Xs), np.concatenate(ys); w = np.where(y == 1, 1.0, 10.0)   # undo the 10% negative subsample
    m = LogisticRegression(max_iter=300).fit(X, y, sample_weight=w)
    act, tv, _ = feats(day, H, keep)
    if not len(act): return {i: 0.0 for i in lu}, len(act)
    Fl = {}
    for i in lu:
        fs = set(follows.get(lhun.get(i), set())) | (follows.get(lmak.get(i), set()) if EDGES == "hunter_maker" else set())
        Fl[i] = float(np.log1p(act.n90[act.index.isin(fs)]).sum()) if EDGES != "none" else 0.0
    FOLL.update(Fl)
    return {i: float(m.predict_proba(X_)[:, 1].sum()) for i, X_ in zip(lu, pair_X(act, tv, lu, follows))}, len(act)
FOLL = {}
z = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0
def day_metrics(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist()
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)] + [100.0 * (o[0] in t[:3])]
def evaluate(Es, hidden=None):
    D = C.copy(); D["E"] = D.id.map(lambda i: Es.get(i, 0.0)); D["zc"] = D.groupby("day").clean_v3_nosite.transform(z); D["ze"] = D.groupby("day").E.transform(lambda s: z(np.log(s + 0.1)))
    if hidden is not None: D["zh"] = D.groupby("day").id.transform(lambda s: z(np.log1p(s.map(lambda i: hidden.get(i, 0)).astype(float))))
    extra = "zh" if hidden is not None else "ze"; WS = (0, .25, .5, 1, 2); per = {}
    for d in DAYS:   # leave-one-day-out weight
        tr = D[(D.day != d) & D.day.isin(DAYS)]
        best = max(WS, key=lambda w: np.mean([day_metrics(g.assign(s=g.zc + w * g[extra]), "s")[0] for _, g in tr.groupby("day")]))
        g = D[D.day == d]; per[d] = {"w": best, "clean": day_metrics(g, "zc"), "comb": day_metrics(g.assign(s=g.zc + best * g[extra]), "s")}
    cl = np.array([per[d]["clean"] for d in DAYS]); cb = np.array([per[d]["comb"] for d in DAYS]); df = cb - cl
    bs = np.array([df[rng.integers(0, len(DAYS), len(DAYS))].mean(0) for _ in range(4000)])
    return {"clean top3/5/10/p1": cl.mean(0).round(1).tolist(), "combined": cb.mean(0).round(1).tolist(),
            "gain [mean, lo, hi] top3/5/10/p1": [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(4)],
            "per_day": {d: {"w": per[d]["w"], "clean_top3": per[d]["clean"][0], "comb_top3": per[d]["comb"][0]} for d in DAYS}}
res = {"design": __doc__.split("\n    python")[0], "covered_people": len(COV),
       "coverage_of_votes_by_day": {d: round(float((C[C.day == d].id.map(cov_l).fillna(0) / C[C.day == d].id.map(dict(zip(L.id, L.votes)))).mean()), 3) for d in DAYS}}
for mode in ("strict", "lenient"):
    Es, n_act = {}, {}
    for d in DAYS:
        e, n_act[d] = expected(d, mode); Es.update(e)
    res[mode] = {"active_people_by_day": n_act, **evaluate(Es), "followers_feature_only": evaluate({}, hidden=dict(FOLL)) if EDGES != "none" else None}
    json.dump(res, open(os.path.join(OUT, f"voter_harness_{EDGES}.json"), "w"), indent=1, default=float); print(mode, res[mode]["gain [mean, lo, hi] top3/5/10/p1"], flush=True)
    if mode == "lenient" and os.environ.get("CURVE", "1") == "1":
        curve = {}
        allp = np.array(sorted(COV)); base_cov = float(np.nanmean(list(res["coverage_of_votes_by_day"].values())))
        for lvl in (0.10, 0.20, 0.30):
            gains = []
            for r_ in range(5):
                keep = set(allp[np.random.default_rng(r_).random(len(allp)) < lvl / base_cov]); Es2 = {}
                for d in DAYS: Es2.update(expected(d, mode, keep)[0])
                gains.append(evaluate(Es2)["gain [mean, lo, hi] top3/5/10/p1"][0][0])
            curve[f"{int(lvl * 100)}%"] = {"top3_gain_mean_of_5_draws": round(float(np.mean(gains)), 1), "draw_range": [round(min(gains), 1), round(max(gains), 1)]}
        curve[f"{int(round(base_cov * 100))}% (all covered)"] = {"top3_gain": res[mode]["gain [mean, lo, hi] top3/5/10/p1"][0]}
        res["coverage_curve_lenient"] = curve; print("curve", curve, flush=True)
        json.dump(res, open(os.path.join(OUT, f"voter_harness_{EDGES}.json"), "w"), indent=1, default=float)
# hidden-window variant: today's votes seen in reads fetched 00:05-04:00 PT of the day
hid = {}; nread = {}
for d in DAYS:
    a, b = start(d) + pd.Timedelta(minutes=5), start(d) + pd.Timedelta(hours=4)
    h = U[(U.lday == d) & (U.fetched_at >= a) & (U.fetched_at <= b)]; nread[d] = int(h.person_id.nunique()); hid.update(h.groupby("target_id").person_id.nunique().to_dict())
res["hidden_window"] = {"people_reread_in_window_by_day": nread, **(evaluate({}, hidden=hid) if sum(nread.values()) else {"note": "no reads in the hidden window yet"})}
json.dump(res, open(os.path.join(OUT, f"voter_harness_{EDGES}.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float)[:3000])
