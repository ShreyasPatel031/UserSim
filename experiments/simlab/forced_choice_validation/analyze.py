"""Is the forced-choice panel a real signal? 30 held days, every featured launch in our table. Intervals: bootstrap over days (2000)."""
import json, sys, numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression
SP = sys.argv[1]; OUT = f"{SP}/fcv"; rng = np.random.default_rng(0)
L = pd.read_parquet(f"{OUT}/launches.parquet"); A = pd.read_parquet(f"{OUT}/arm2_oos.parquet"); L = L.merge(A, on="id", how="left")
def load(p):
    R = [json.loads(l) for l in open(f"{OUT}/fc_pass{p}.jsonl")]; rows = []; allp = {}
    for r in R:
        w = np.array([x["n_people"] for x in r["rows"]], float)
        if not len(w): continue
        rows.append({"id": r["id"], "day": r["day"], "n_seg": len(w), "share_picked": float(np.mean([x["picked"] for x in r["rows"]])), "share_picked_w": float(np.average([x["picked"] for x in r["rows"]], weights=w)),
                     "place": float(np.average([x["place"] for x in r["rows"]], weights=w))})
        for x in r["rows"]:
            for i in x["picks"]: allp[i] = allp.get(i, 0) + 1
            allp[("tot", r["day"])] = allp.get(("tot", r["day"]), 0) + 1
    T = pd.DataFrame(rows); T["share_allcalls"] = [allp.get(i, 0) / allp[("tot", d)] for i, d in zip(T.id, T.day)]; return T, R
T, R = load(1); D = L.merge(T, on=["id", "day"], how="inner"); days = sorted(D.day.unique())
def boot(per_day):  # per_day: array (days, k)
    a = np.asarray(per_day, float); b = np.array([np.nanmean(a[rng.integers(0, len(a), len(a))], 0) for _ in range(2000)])
    return [f"{m:.3f} [{l:.3f}, {h:.3f}]" for m, l, h in zip(np.nanmean(a, 0), np.nanpercentile(b, 2.5, 0), np.nanpercentile(b, 97.5, 0))]
OUTJ = {"n_days": len(days), "n_launches_scored": len(D), "n_launches_on_days": len(L), "segments_per_launch_median": float(D.n_seg.median()), "share_picked_mean": round(D.share_picked.mean(), 3), "chance_pick": round(float((3 / D.groupby("day").id.transform("size")).mean()), 3)}
# 1. daily Spearman with real rank (sign: positive = agrees)
sig = {"mean place": -D.place, "share picked (own call)": D.share_picked, "share picked (all calls that day)": D.share_allcalls, "arm 2 prediction": D.pred}
G = {d: g.index for d, g in D.groupby("day")}
sp = [[spearmanr(s[G[d]], -D.dailyRank[G[d]]).statistic for s in sig.values()] for d in days]
OUTJ["1_daily_spearman_vs_real_rank"] = dict(zip(sig, boot(sp)))
# 2. top-k hits of the panel's ordering vs arm 2 (paired)
D["panel_order"] = -D.place + 1e-3 * D.share_allcalls; D["panel_order2"] = D.share_allcalls - 1e-3 * D.place
def hits(col, k, X=D):
    out = []
    for d, g in X.groupby("day"):
        real = set(g.sort_values("dailyRank").id[:k]); out.append(len(set(g.sort_values(col, ascending=False).id[:k]) & real) / k)
    return np.array(out)
H = {}
for k in (3, 5, 10):
    a, p1, p2 = hits("pred", k), hits("panel_order", k), hits("panel_order2", k); ch = np.array([min(k, len(g)) / len(g) for _, g in D.groupby("day")])
    H[f"top{k}"] = dict(zip(["arm 2", "panel by mean place", "panel by pick share", "chance", "panel(place) minus arm 2", "panel(picks) minus arm 2"], boot(np.c_[a, p1, p2, ch, p1 - a, p2 - a])))
OUTJ["2_topk_hit"] = H
# 3. does it add to arm 2? stack on day-centred log votes
D["y"] = np.log1p(D.votes) - D.groupby("day").votes.transform(lambda s: np.log1p(s).mean())
for c in ("pred", "place", "share_allcalls", "share_picked"): D[c + "_c"] = D[c] - D.groupby("day")[c].transform("mean")
def stack(tr, te, feats):
    m = LinearRegression().fit(tr[feats], tr.y); return m.predict(te[feats]), dict(zip(feats, np.round(m.coef_, 3)))
def run_stack(splits, name):
    P = []
    for trd, ted in splits:
        tr, te = D[D.day.isin(trd)], D[D.day.isin(ted)].copy()
        te["s0"], _ = stack(tr, te, ["pred_c"]); te["s1"], c1 = stack(tr, te, ["pred_c", "place_c"]); te["s2"], c2 = stack(tr, te, ["pred_c", "place_c", "share_allcalls_c"]); P.append(te)
    P = pd.concat(P); res = {"test_days": P.day.nunique(), "coef_last_fold_arm2+place": c1, "coef_last_fold_arm2+place+picks": c2}
    for k in (3, 5, 10):
        a, b, c = hits("s0", k, P), hits("s1", k, P), hits("s2", k, P); res[f"top{k}"] = dict(zip(["arm 2 alone", "+ place", "+ place + picks", "(+place) minus arm 2", "(+place+picks) minus arm 2"], boot(np.c_[a, b, c, b - a, c - a])))
    OUTJ[name] = res
sep = [d for d in days if d < "2026-10-01"]; octo = [d for d in days if "2026-10-01" <= d < "2026-11-01"]; nov = [d for d in days if d >= "2026-11-01"]
run_stack([(sep, octo), (sep + octo, nov)], "3_stack_month_forward"); run_stack([([x for x in days if x != d], [d]) for d in days], "3b_stack_leave_one_day_out (not forward)")
# 4. by segment: does a segment's pick / place predict that segment's real backers?
M = pd.read_parquet(f"{SP}/segments/members_2026-11-16.parquet"); segof = dict(zip(M.person_id, M.subgroup.astype(str)))
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(set(L.id))]
U["seg"] = U.person_id.map(segof); U = U[U.seg.notna()].drop_duplicates(["person_id", "target_id"]); U["day"] = U.target_id.map(dict(zip(L.id, L.day)))
act = U.groupby(["day", "seg"]).person_id.nunique(); bk = U.groupby(["target_id", "seg"]).person_id.nunique(); tot_act = U.groupby("day").person_id.nunique(); tot_bk = U.groupby("target_id").person_id.nunique()
S = pd.DataFrame([{"id": r["id"], "day": r["day"], "seg": str(x["seg"]), "group": x["group"], "picked": x["picked"], "place": x["place"]} for r in R for x in r["rows"]])
S["act"] = [act.get((d, s), 0) for d, s in zip(S.day, S.seg)]; S["bk"] = [bk.get((i, s), 0) for i, s in zip(S.id, S.seg)]; S["tact"] = S.day.map(tot_act); S["tbk"] = S.id.map(tot_bk).fillna(0)
S = S[S.act >= 20]; S["rate"] = S.bk / S.act; S["orate"] = S.tbk / S.tact; S["lift"] = (S.rate + 1e-4) / (S.orate + 1e-4)
OUTJ["4_people"] = {"held people with a segment who voted on these days": int(U.person_id.nunique()), "segment-launch pairs (segment had >= 20 voters that day)": len(S), "real backing rate when picked %": round(100 * S[S.picked].rate.mean(), 2), "real backing rate when not picked %": round(100 * S[~S.picked].rate.mean(), 2),
                    "share of pairs picked %": round(100 * S.picked.mean(), 1)}
def seg_day(col):
    out = []
    for d in days:
        g = S[S.day == d]; v = [spearmanr(-x.place, x[col]).statistic for _, x in g.groupby("seg") if len(x) >= 6 and x[col].nunique() > 1 and x.place.nunique() > 1]; out.append(np.mean(v) if v else np.nan)
    return out
def within_launch():
    out = []
    for d in days:
        g = S[S.day == d]; v = [spearmanr(-x.place, x.lift).statistic for _, x in g.groupby("id") if len(x) >= 4 and x.lift.nunique() > 1 and x.place.nunique() > 1]; out.append(np.mean(v) if v else np.nan)
    return out
OUTJ["4_segment_spearman"] = dict(zip(["place vs the segment's own backing rate, across launches (per segment-day)", "place vs the segment's lift over all voters, across launches", "across segments within one launch: place vs lift"], boot(np.c_[seg_day("rate"), seg_day("lift"), within_launch()])))
bg = {}
for gname, g in S.groupby("group"):
    v = [[x[x.picked].rate.mean() * 100 if x.picked.any() else np.nan, x[~x.picked].rate.mean() * 100] for _, x in g.groupby("day")]; bg[gname] = dict(zip(["backing rate when picked %", "when not picked %"], boot(v)), n_pairs=len(g))
OUTJ["4_by_voter_group"] = bg
# recall at N: rank that day's voters by their segment's place for the launch; N = number of real backers among them
rec = {d: [] for d in days}
for (i, d), g in S.groupby(["id", "day"]):
    N = g.bk.sum(); pool = g.act.sum()
    if N < 5: continue
    def recall(order):
        left, got = N, 0.0
        for _, x in order.iterrows():
            take = min(left, x.act); got += x.bk * take / x.act; left -= take
            if left <= 0: break
        return got / N
    rec[d].append([recall(g.sort_values("place")), N / pool, recall(g.sort_values("rate", ascending=False))])
OUTJ["4_recall_at_N"] = dict(zip(["panel (segments ordered by place)", "random", "ceiling (segments ordered by their real rate)"], boot([np.mean(v, 0) if v else [np.nan] * 3 for v in rec.values()])), launches=sum(len(v) for v in rec.values()),
                             note="pool = held people in the panel's segments who voted on any launch that day; the E5 backer line (25-29% recall at N) uses all held people and person-level scores, so it is not directly comparable")
# 5. stability
try:
    T2, _ = load(2); J = T.merge(T2, on=["id", "day"], suffixes=("", "_2")); st = []
    for d, g in J.groupby("day"):
        g = g.assign(o1=-g.place + 1e-3 * g.share_allcalls, o2=-g.place_2 + 1e-3 * g.share_allcalls_2, q1=g.share_allcalls - 1e-3 * g.place, q2=g.share_allcalls_2 - 1e-3 * g.place_2)
        st.append([len(set(g.nlargest(3, "o1").id) & set(g.nlargest(3, "o2").id)) / 3, len(set(g.nlargest(3, "q1").id) & set(g.nlargest(3, "q2").id)) / 3, spearmanr(g.place, g.place_2).statistic, spearmanr(g.share_allcalls, g.share_allcalls_2).statistic, (g.share_picked.gt(0) == g.share_picked_2.gt(0)).mean()])
    OUTJ["5_stability_rerun"] = dict(zip(["top-3 overlap, ordering by place", "top-3 overlap, ordering by pick share", "Spearman of mean place", "Spearman of pick share", "same picked/not-picked verdict per launch"], np.round(np.mean(st, 0), 3).tolist()), days=len(st), per_day_top3_overlap_place=[round(x[0], 2) for x in st], launches=len(J), note="second pass uses a different line-up order")
except FileNotFoundError: pass
# leak checks
cards = json.load(open(f"{OUT}/cards.json")); bad = 0; tot = 0; names_by_day = L.groupby("day")["name"].agg(lambda s: set(x.lower() for x in s)).to_dict()
for r in L.itertuples():
    for p in (cards.get(f"l-{r.id}") or {}).get("personas") or []:
        for q in p.get("products_they_commonly_upvoted") or []:
            tot += 1; bad += q["product"].lower() in names_by_day[r.day]
OUTJ["leak_checks"] = {"persona-card product mentions": tot, "of which share a name with a launch of the same test day": bad, "line-up text": "name, tagline and the first 160 characters of the maker's own description; no votes, ranks or comments",
                       "persona pool and card history": "upvotes on launch days strictly before the test day", "known limitation": "segment definitions and the one-paragraph segment profiles were fitted on Nov 16 2026 from all held data, so they postdate the test days"}
json.dump(OUTJ, open(f"{OUT}/results.json", "w"), indent=1, default=float); print(json.dumps(OUTJ, indent=1, default=float))
