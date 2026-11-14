"""Re-read order for the daily upvote_refresh job (orchestrator 22:55Z Nov 14). Held data only; nothing is pulled.

Question: the job reads each person's Upvotes tab newest first down to the first held upvote. Which order of people
recovers the most of yesterday's votes per page read?

Data
  people   complete people in store_v3 (persons.complete, whole-person rule), salted ids only
  votes    their dated upvotes (events.parquet, kind=upvote), dated by the upvoted launch's PT day (store upvote times are
           fetch snapshots, not vote times), deduped person x launch
  truth    day d = launches of day d (Oct 1 - Nov 12) with final votes; a person counts for day d only if their upvotes tab
           was read after d closed (fetched_at >= d+1 08:00Z), so every order is scored on the same people
  coverage per-launch min(recovered upvoters, displayed votes) / displayed votes, summed (pool_size.py capped headline)
Orders (each day, using only votes on launches dated before d)
  a  most active first: upvotes on launches of d-30..d-1
  b  E5's CF-only predicted backers of day d's launches first (tmp/e5/private/backer_arms/<d>.parquet, arm CF-only;
     score = sum of p over the day's listed launches; lists frozen with reads before d 00:00 PT), then the rest by (a).
     Only Nov 8-12 exist, so (b) is compared on those 5 days in a separate run
  c  any upvote in d-7..d-1 first, random within groups
  d  random
  e  (extra) upvotes on launches of d-7..d-1 (7-day count)
Cost: the job reads the people in order up to a budget of N people each morning. A person costs max(1, ceil(n/20)) pages,
  n = their upvotes since the job last read them (launch-dated); everyone is taken as freshly read the day before the run
  starts. People not read keep accumulating, so their next read costs more.
Intervals: launch bootstrap (1000) over the window's launches; paired differences vs (a) on the same resamples.
usage: python reread_order.py DATA_DIR -> results/reread_order.json + .md   (counts only)"""
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = sys.argv[1] if len(sys.argv) > 1 else "."
OCT_LEVEL = {"all": 0.517, "top3": 0.836}
BUDGETS = [1000, 5000, 20000]
GRID = [250, 500, 1000, 2000, 3000, 5000, 7500, 10000, 15000, 20000, 30000, 40000, 50000, 70000]
NBOOT = 1000

P = pd.read_parquet(f"{D}/persons.parquet", columns=["person_id", "complete"])
C = P[P.complete.astype(bool)].person_id.unique()
pix = {p: i for i, p in enumerate(C)}; NP = len(C)
T = pd.read_parquet(f"{D}/tabs.parquet", columns=["person_id", "tab", "fetched_at"])
T = T[(T.tab == "upvotes") & T.person_id.isin(pix)].groupby("person_id").fetched_at.max()
fetched = np.full(NP, np.datetime64("NaT", "us"), dtype="datetime64[us]")
fetched[[pix[p] for p in T.index]] = pd.to_datetime(T.values, utc=True).tz_localize(None).values.astype("datetime64[us]")
L = pd.read_parquet(f"{D}/launches.parquet")
L = L[L.day.notna()].copy(); L["votes"] = L.votes.astype(float)
days_all = sorted(L.day.unique()); dix = {d: i for i, d in enumerate(days_all)}
E = pd.read_parquet(f"{D}/events.parquet", columns=["person_id", "kind", "target_id"])
E = E[(E.kind == "upvote") & E.person_id.isin(pix)]
E = E.assign(id=E.target_id.astype(str))[["person_id", "id"]].drop_duplicates()
E = E.merge(L[["id", "day"]], on="id")
E["p"] = E.person_id.map(pix).astype(np.int64); E["k"] = E.day.map(dix).astype(np.int64)
cnt = np.zeros((NP, len(days_all) + 1), np.int32)     # column k+1 = votes on launches of day k
np.add.at(cnt, (E.p.values, E.k.values + 1), 1); cs = cnt.cumsum(1)   # cs[:, k+1] = votes on days <= k

W = [d for d in days_all if "2026-10-01" <= d <= "2026-11-12" and L[(L.day == d)].votes.notna().any()]
Lw = L[L.day.isin(W) & L.votes.notna() & (L.votes > 0)].reset_index(drop=True)
Lw["top3"] = Lw.daily_rank <= 3
lix = {l: i for i, l in enumerate(Lw.id)}
Ew = E[E.id.isin(lix)].copy(); Ew["l"] = Ew.id.map(lix)
byday = {d: g for d, g in Ew.groupby("day")}
eligible = {d: fetched >= np.datetime64(str(pd.Timestamp(d) + pd.Timedelta(days=1, hours=8))) for d in W}

arms = {}
for d in W:
    f = f"{D}/{d}.parquet"
    if os.path.exists(f):
        A = pd.read_parquet(f); A = A[A.arm == "CF-only"]
        bad = A[pd.to_datetime(A.reads_before, utc=True) > pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC")]
        assert len(bad) == 0, f"leak: {d} list reads after the day opened"
        assert (A.svd_max_lday < d).all(), f"leak: {d} svd rows dated on/after the day"
        s = A[A.person_id.isin(pix)].groupby("person_id").p.sum()
        v = np.zeros(NP); v[[pix[p] for p in s.index]] = s.values; arms[d] = v


def scores(o, d, rng):
    k = dix[d]; r = rng.random(NP) * 1e-3
    a30 = cs[:, k] - cs[:, max(k - 30, 0)]; a7 = cs[:, k] - cs[:, max(k - 7, 0)]
    if o == "a": return a30 + r
    if o == "b": return arms[d] * 1e9 + a30 + r
    if o == "c": return (a7 > 0) + r
    if o == "d": return r
    if o == "e": return a7 + r


def run(order, budget, days, seed=7):
    """sequential: returns per-day pages, per-launch recovered (len Lw), per-day people read"""
    last = np.full(NP, dix[days[0]] - 1)      # freshly read the day before the run starts
    rec = np.zeros(len(Lw)); pages = []; rng = np.random.default_rng(seed)
    for d in days:
        el = eligible[d]; s = np.where(el, scores(order, d, rng), -np.inf)
        n = min(budget, int(el.sum())); sel = np.argpartition(-s, n - 1)[:n] if n < NP else np.arange(NP)
        k = dix[d]; new = cs[sel, k + 1] - cs[sel, last[sel] + 1]
        pages.append(int(np.maximum(1, np.ceil(new / 20)).sum())); last[sel] = k
        m = np.zeros(NP, bool); m[sel] = True
        g = byday.get(d)
        if g is not None:
            gg = g[m[g.p.values] & el[g.p.values]]
            rec += np.bincount(gg.l.values, minlength=len(Lw))
    return np.array(pages), rec


def summ(rec, mask):
    v = Lw.votes.values; t3 = Lw.top3.values
    cap = np.minimum(rec, v)
    return {"votes_recovered": int(rec[mask].sum()), "cov_all": cap[mask].sum() / v[mask].sum(), "cov_top3": cap[mask & t3].sum() / v[mask & t3].sum()}


def boot(recs, mask, ref):
    rng = np.random.default_rng(11); idx = np.where(mask)[0]; v = Lw.votes.values; t3 = Lw.top3.values
    out = {o: {"votes": [], "all": [], "top3": [], "dv": [], "dall": [], "dtop3": []} for o in recs}
    for _ in range(NBOOT):
        s = rng.choice(idx, len(idx)); s3 = s[t3[s]]
        st = {}
        for o, r in recs.items():
            cap = np.minimum(r, v)
            st[o] = (r[s].sum(), cap[s].sum() / v[s].sum(), cap[s3].sum() / v[s3].sum())
        for o in recs:
            for j, key in enumerate(["votes", "all", "top3"]):
                out[o][key].append(st[o][j]); out[o]["d" + key if key != "votes" else "dv"].append(st[o][j] - st[ref][j])
    ci = lambda x: [round(float(q), 4) for q in np.percentile(x, [2.5, 97.5])]
    return {o: {k: ci(x) for k, x in dd.items()} for o, dd in out.items()}


def study(days, orders, label):
    mask = Lw.day.isin(days).values; res = {"days": [days[0], days[-1], len(days)], "launches": int(mask.sum()),
                                           "eligible_people_mean": int(np.mean([eligible[d].sum() for d in days]))}
    full_p, full_r = run("d", NP, days)
    res["read_everyone"] = {**{k: round(float(x), 4) for k, x in summ(full_r, mask).items()}, "pages_per_day": round(float(full_p.mean()))}
    res["budgets"] = {}
    for N in BUDGETS:
        recs, pg = {}, {}
        for o in orders:
            pg[o], recs[o] = run(o, N, days)
        B = boot(recs, mask, "a")
        res["budgets"][N] = {o: {**{k: round(float(x), 4) for k, x in summ(recs[o], mask).items()},
                                 "pages_per_day": round(float(pg[o].mean())), "votes_per_page": round(float(recs[o][mask].sum() / pg[o].sum()), 3),
                                 "ci": B[o]} for o in orders}
    # pages per day to reach a coverage target (pooled over the run's days); linear interpolation on the budget grid.
    # targets: the Oct level (absolute) and 95% / 99% of what reading every person gives on these days (the ceiling)
    ce = res["read_everyone"]
    tg = {"oct_level": OCT_LEVEL, "95pct_of_read_everyone": {"all": 0.95 * ce["cov_all"], "top3": 0.95 * ce["cov_top3"]},
          "99pct_of_read_everyone": {"all": 0.99 * ce["cov_all"], "top3": 0.99 * ce["cov_top3"]}}
    res["targets"] = {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in tg.items()}
    res["pages_to_target"] = {}
    for o in orders:
        pts = []
        for N in GRID:
            p, r = run(o, N, days); s = summ(r, mask); pts.append((N, p.mean(), s["cov_all"], s["cov_top3"]))
        need = {}
        for tn, tv in tg.items():
            for key, j in (("all", 2), ("top3", 3)):
                tgt = tv[key]; hit = None
                for a_, b_ in zip(pts, pts[1:]):
                    if a_[j] >= tgt: hit = a_[:2]; break
                    if b_[j] >= tgt:
                        f = (tgt - a_[j]) / (b_[j] - a_[j]); hit = (a_[0] + f * (b_[0] - a_[0]), a_[1] + f * (b_[1] - a_[1])); break
                need[f"{tn}_{key}"] = {"people": round(hit[0]), "pages_per_day": round(hit[1])} if hit else None
        res["pages_to_target"][o] = {"need": need, "curve_people_pages_covall_covtop3": [[n, round(p), round(a, 4), round(t, 4)] for n, p, a, t in pts]}
    print(label, json.dumps({k: v for k, v in res.items() if k not in ("pages_to_target", "budgets")})[:3000])
    print(label, "pages to target", json.dumps({o: v["need"] for o, v in res["pages_to_target"].items()}))
    return res


out = {"method": __doc__, "people_complete": int(NP), "oct_level": OCT_LEVEL}
out["main_oct1_nov12"] = study(W, ["a", "c", "d", "e"], "MAIN")
out["oct_only_read_everyone"] = study([d for d in W if d <= "2026-10-31"], ["a"], "OCT")["read_everyone"]
bd = [d for d in W if d in arms]
out["with_b_" + bd[0] + "_" + bd[-1]] = study(bd, ["a", "b", "c", "d", "e"], "B")
json.dump(out, open(os.path.join(HERE, "results", "reread_order.json"), "w"), indent=1, default=str)
