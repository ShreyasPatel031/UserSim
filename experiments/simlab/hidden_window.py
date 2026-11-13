"""Hidden-window voter signal (orchestrator 01:33Z Nov 13). Two parts.
REAL: per launch, the number of held (complete) people whose upvote of that launch is seen in a re-read fetched by 01:00 / 02:00 /
02:45 PT of the launch day, unweighted and weighted by the person's past hit rate (share of their earlier upvotes on launches that
finished top 10). Sources: raw/_cursor/hidden_window/<day>/upvotes.jsonl.gz (Cursor re-reads, when present) + in-window reads in the
store. Combined with the clean 00:05 score: z(clean) + w z(ln(1 + count)), w leave-one-day-out.
SIMULATED CEILING: no per-launch vote order is held, so the time proxy is binomial thinning of each launch's FINAL votes: held share c
(28% / 41% coverage) x share cast before 03:00 PT f (30% / 50% / 70%, an assumption - the hidden period vote curve is not observed);
20 draws per setting, the same blend, days = all clean as-live days with final votes. Paired day bootstrap vs clean alone.
    python hidden_window.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>
"""
import glob, gzip, hashlib, json, os, subprocess, sys
import numpy as np, pandas as pd
V3, CLEAN, LDIR, SALTD, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
BK = "gs://usersim-bakeoff-347838016394/usersim_sim"
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float); L["votes"] = pd.to_numeric(L.votes, errors="coerce")
C = pd.read_parquet(CLEAN); C["id"] = C.id.astype(str); C = C.merge(L[["id", "votes"]], on="id", how="left"); C = C[C.votes.notna()]
DAYS = sorted(C.day.unique()); start = lambda d: pd.Timestamp(d + " 00:00").tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
z = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist()
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)] + [100.0 * (o[0] in t[:3])]
def blend(D, col, days):
    D = D.copy(); D["zc"] = D.groupby("day").clean_v3_nosite.transform(z); D["zx"] = D.groupby("day")[col].transform(lambda s: z(np.log1p(s.astype(float))))
    out = {}
    for d in days:
        tr = D[(D.day != d) & D.day.isin(days)]
        w = max((0, .25, .5, 1, 2, 4), key=lambda w: np.mean([dm(g.assign(s=g.zc + w * g.zx), "s")[0] for _, g in tr.groupby("day")]))
        g = D[D.day == d]; out[d] = (dm(g, "zc"), dm(g.assign(s=g.zc + w * g.zx), "s"), dm(g, "zx"), w)
    return out
def summ(per):
    cl = np.array([v[0] for v in per.values()]); cb = np.array([v[1] for v in per.values()]); al = np.array([v[2] for v in per.values()]); df = cb - cl
    bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(2000)])
    return {"days": len(df), "clean": cl.mean(0).round(1).tolist(), "combined": cb.mean(0).round(1).tolist(), "signal_alone": al.mean(0).round(1).tolist(),
            "gain [mean, lo, hi] top3/5/10/p1": [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(4)]}
res = {"design": __doc__.split("\n    python")[0]}
# ---------- REAL ----------
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id", "fetched_at"]); E = E[(E.kind == "upvote") & E.person_id.isin(COV)]
E["target_id"] = E.target_id.astype(str); E["fetched_at"] = pd.to_datetime(E.fetched_at, utc=True); lday = dict(zip(L.id, L.day)); top10 = set(L[L["rank"] <= 10].id)
E["lday"] = E.target_id.map(lday); E = E[E.lday.notna()]
reads = [E[["person_id", "target_id", "fetched_at", "lday"]].assign(src="store")]
for d in DAYS:
    p = subprocess.run(["gsutil", "cat", f"{BK}/raw/_cursor/hidden_window/{d}/upvotes.jsonl.gz"], capture_output=True)
    if p.returncode or not p.stdout: continue
    rows = []
    for l in gzip.decompress(p.stdout).decode().splitlines():
        x = json.loads(l); who = x.get("person_id") or (pid(x["username"]) if x.get("username") else None); t = str(x.get("post_id") or x.get("launch_id") or "")
        if who and t: rows.append({"person_id": who, "target_id": t, "fetched_at": pd.Timestamp(x.get("fetched_at"), tz="UTC") if x.get("fetched_at") else pd.NaT, "lday": lday.get(t), "src": "cursor"})
    if rows: reads.append(pd.DataFrame(rows))
R_ = pd.concat(reads); R_["fetched_at"] = pd.to_datetime(R_.fetched_at, utc=True)
hit = {}
for d in DAYS:   # past hit rate per person as of the day (earlier upvotes, any read)
    h = E[E.lday < d]; hit[d] = h.assign(t10=h.target_id.isin(top10)).groupby("person_id").t10.mean()
real = {}
for cut in ("01:00", "02:00", "02:45"):
    cnt, wcnt, npeople = {}, {}, {}
    for d in DAYS:
        a, b = start(d) + pd.Timedelta(minutes=5), pd.Timestamp(d + " " + cut).tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
        r = R_[(R_.lday == d) & (R_.fetched_at >= a) & (R_.fetched_at <= b)].drop_duplicates(["person_id", "target_id"])
        npeople[d] = int(r.person_id.nunique()); cnt.update(r.groupby("target_id").size().to_dict())
        wcnt.update(r.assign(w=r.person_id.map(hit[d]).fillna(0.1)).groupby("target_id").w.sum().to_dict())
    D = C.assign(cnt=C.id.map(cnt).fillna(0), wcnt=C.id.map(wcnt).fillna(0))
    real[cut] = {"people_reread_in_window_by_day": npeople, "unweighted": summ(blend(D, "cnt", DAYS)), "weighted_by_past_hit_rate": summ(blend(D, "wcnt", DAYS))}
res["real"] = real; print("real", {k: (sum(v["people_reread_in_window_by_day"].values()), v["unweighted"]["gain [mean, lo, hi] top3/5/10/p1"][0]) for k, v in real.items()}, flush=True)
# ---------- SIMULATED CEILING ----------
sim = {}
for c in (0.28, 0.41):
    for f in (0.3, 0.5, 0.7):
        per_draw = []
        for r_ in range(20):
            g_ = np.random.default_rng(r_); D = C.assign(obs=g_.binomial(C.votes.astype(int).values, c * f))
            per_draw.append(blend(D, "obs", DAYS))
        # pool days x draws for the interval (paired by day within draw)
        pooled = {f"{d}|{k}": v for k, pd_ in enumerate(per_draw) for d, v in pd_.items()}
        s = summ(pooled); s["days"] = len(DAYS); sim[f"coverage {int(c * 100)}%, pre-03:00 share {int(f * 100)}%"] = s
        print(c, f, s["gain [mean, lo, hi] top3/5/10/p1"][0], "alone", s["signal_alone"][:3], flush=True)
res["simulated"] = sim
json.dump(res, open(os.path.join(OUT, "hidden_window.json"), "w"), indent=1, default=float); print("saved")
# ---------- REALISTIC CEILING: the actual held voters (non-random pool), thinned by the pre-03:00 share ----------
held = E.groupby("target_id").person_id.nunique(); C["held"] = C.id.map(held).fillna(0).astype(int)
cov_day = C.groupby("day").apply(lambda g: g.held.sum() / g.votes.sum())
OK = [d for d in DAYS if cov_day[d] >= 0.2]   # days the store covers (reads end Nov 10)
real_ceiling = {"days_used": OK, "held_coverage_by_day": cov_day.round(3).to_dict()}
for f in (0.3, 0.5, 0.7, 1.0):
    per_draw = [blend(C.assign(obs=np.random.default_rng(r_).binomial(C.held.values, f)), "obs", OK) for r_ in range(20 if f < 1 else 1)]
    s = summ({f"{d}|{k}": v for k, pd_ in enumerate(per_draw) for d, v in pd_.items()}); s["days"] = len(OK)
    real_ceiling[f"actual held voters, pre-03:00 share {int(f * 100)}%"] = s; print("held", f, s["gain [mean, lo, hi] top3/5/10/p1"][0], "alone", s["signal_alone"][:3], flush=True)
res["realistic_ceiling_actual_held_voters"] = real_ceiling
json.dump(res, open(os.path.join(OUT, "hidden_window.json"), "w"), indent=1, default=float); print("saved2")
