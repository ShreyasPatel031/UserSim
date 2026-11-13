"""X pre-launch mentions by held people (orchestrator 02:00Z Nov 13). Grok Bot X rollout drops (persons / events; posts since Aug 1, 25 newest
per person, page cap 1). For each launch Oct 1 - Nov 10: held people's X posts (post / reply / quote / repost text) in the 7 days before
00:00 PT of the launch day that mention the product NAME (word match, names >= 5 characters or two words), its DOMAIN (where a product
URL is held), or a maker / hunter X HANDLE (handles_20261113.jsonl, identity_source = "0005" only = known at 00:05); separately the
launch day before 03:00 PT. A person counts as covering a window only if their fetched posts reach back past the window start (or are
not truncated). Coverage = share of launches with >= 1 mention; if < 5% the scoring step is skipped. Person side: lift of P(vote for
the launch | mentioned it / its team before launch) over P(vote | covered, not mentioned). Counts only; no handles or text written.
    python x_mentions.py <x drops dir> <handles jsonl> <launches dir> <store dir> <try_e2e urls.json> <out dir>
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
XD, HJ, LDIR, V3, URLS, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & (L.day >= "2026-10-01") & (L.day <= "2026-11-10")].copy(); L["id"] = L.id.astype(str)
start = lambda d: pd.Timestamp(d + " 00:00").tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
P, E = [], []
for f in glob.glob(os.path.join(XD, "*", "persons.jsonl")):
    P += [json.loads(l) for l in open(f)]
for f in glob.glob(os.path.join(XD, "*", "events.jsonl")):
    for l in open(f):
        x = json.loads(l); E.append((x["person_id"], pd.Timestamp(x["ts_lo"]), ((x.get("extra") or {}).get("text") or "").lower()))
P = pd.DataFrame(P).drop_duplicates("person_id", keep="last"); P["oldest"] = pd.to_datetime(P.oldest_fetched_post_at, utc=True, errors="coerce")
E = pd.DataFrame(E, columns=["person_id", "ts", "text"]); E["ts"] = pd.to_datetime(E.ts, utc=True)
H = [json.loads(l) for l in open(HJ)]; HS = {}
for h in H:
    if h.get("identity_source") == "0005" and h.get("handle"): HS.setdefault(str(h["launch_id"]), set()).add(str(h["handle"]).lower().lstrip("@"))
U = json.load(open(URLS)) if os.path.exists(URLS) else {}
dom = {i: re.sub(r"^www\.", "", re.sub(r"^https?://", "", u).split("/")[0]).lower() for i, u in U.items()}
def name_ok(n): n = (n or "").strip(); return len(n) >= 5 or len(n.split()) >= 2
rows, pairs = [], []
for r in L.itertuples():
    s0 = start(r.day); a, b = s0 - pd.Timedelta(days=7), s0; c = s0 + pd.Timedelta(hours=3)
    pats = []
    if name_ok(r.name): pats.append(("name", re.compile(r"(?<![a-z0-9])" + re.escape(r.name.lower()) + r"(?![a-z0-9])")))
    if r.id in dom and dom[r.id]: pats.append(("domain", re.compile(re.escape(dom[r.id]))))
    for hd in HS.get(r.id, ()): pats.append(("handle", re.compile(r"@" + re.escape(hd) + r"(?![a-z0-9_])")))
    cov = set(P[(P.oldest <= a) | (~P.posts_truncated.astype(bool))].person_id)
    pre = E[(E.ts >= a) & (E.ts < b) & E.person_id.isin(cov)]; day = E[(E.ts >= b) & (E.ts < c)]
    hit_pre, hit_day, kinds = set(), set(), set()
    for kind, pt in pats:
        m = pre[pre.text.str.contains(pt)]; hit_pre |= set(m.person_id); kinds |= {kind} if len(m) else set()
        hit_day |= set(day[day.text.str.contains(pt)].person_id)
    rows.append({"id": r.id, "day": r.day, "rank": float(r.daily_rank), "n_patterns": len(pats), "covered_people": len(cov), "pre_mentions": len(hit_pre), "day_mentions": len(hit_day), "kinds": sorted(kinds)})
    pairs.append((r.id, hit_pre, cov))
D = pd.DataFrame(rows)
res = {"design": __doc__.split("\n    python")[0], "x_people": len(P), "x_events": len(E), "launches": len(D), "launches_with_handles_0005": int(sum(1 for i in D.id if i in HS)),
       "launches_with_domain": int(sum(1 for i in D.id if i in dom)), "median_covered_people_per_launch": float(D.covered_people.median()),
       "coverage_pre_any": round(float((D.pre_mentions > 0).mean()), 4), "coverage_day_any": round(float((D.day_mentions > 0).mean()), 4),
       "launches_with_pre_mention": int((D.pre_mentions > 0).sum()), "by_kind": pd.Series([k for ks in D.kinds for k in ks]).value_counts().to_dict(),
       "pre_mention_launches_by_rank": D[D.pre_mentions > 0].assign(g=lambda x: np.where(x["rank"] <= 3, "1-3", np.where(x["rank"] <= 10, "4-10", "11+"))).g.value_counts().to_dict()}
# person side: does mentioning predict that person's vote? (store upvotes; any read)
Pp = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(Pp[Pp.complete].person_id)
Ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); Ev = Ev[(Ev.kind == "upvote")]
votes = set(zip(Ev.person_id, Ev.target_id.astype(str)))
xm = set(P.person_id) & COV
mv, mn, bv, bn = 0, 0, 0, 0
for i, hit, cov in pairs:
    hc = hit & xm; base = (cov & xm) - hit
    mn += len(hc); mv += sum((p, i) in votes for p in hc); bn += len(base); bv += sum((p, i) in votes for p in base)
res["person_side"] = {"mentioner_pairs": mn, "mentioner_vote_rate": round(mv / mn, 4) if mn else None, "base_pairs": bn, "base_vote_rate": round(bv / bn, 5) if bn else None,
                      "lift": round((mv / mn) / (bv / bn), 1) if mn and bn and bv else None}
json.dump(res, open(os.path.join(OUT, "x_mentions.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
# ---------- step 2: leave-day-out blend with the clean 00:05 score (honest_preds_v2; th_n_pre is not held across Oct 1 - Nov 10) ----------
if res["coverage_pre_any"] >= 0.05 and len(sys.argv) > 7:
    Hn = pd.read_parquet(sys.argv[7])[["id", "honest"]]; Hn["id"] = Hn.id.astype(str); X = D.merge(Hn, on="id")
    z = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0
    X["zc"] = X.groupby("day").honest.transform(z); X["zm"] = X.groupby("day").pre_mentions.transform(lambda s: z(np.log1p(s.astype(float))))
    X["zd"] = X.groupby("day").day_mentions.transform(lambda s: z(np.log1p(s.astype(float))))
    def dm(g, col):
        o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    days = sorted(X.day.unique()); rng = np.random.default_rng(0); out = {}
    for extra in ("zm", "zd"):
        per = []
        for d in days:
            tr = X[X.day != d]; w = max((0, .25, .5, 1, 2), key=lambda w: np.mean([dm(g.assign(s=g.zc + w * g[extra]), "s")[0] for _, g in tr.groupby("day")]))
            g = X[X.day == d]; per.append((dm(g, "zc"), dm(g.assign(s=g.zc + w * g[extra]), "s"), w))
        cl = np.array([p[0] for p in per]); cb = np.array([p[1] for p in per]); df = cb - cl
        bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(2000)])
        out["pre-launch mentions" if extra == "zm" else "launch-day mentions before 03:00 (not 00:05-safe)"] = {"days": len(days), "clean": cl.mean(0).round(1).tolist(), "combined": cb.mean(0).round(1).tolist(),
            "gain [mean, lo, hi] top3/5/10": [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)],
            "weights_chosen": pd.Series([p[2] for p in per]).value_counts().to_dict()}
    # late climbers: launches finishing >= 5 places better than the clean score's within-day rank
    X["crank"] = X.groupby("day").honest.rank(ascending=False); X["climb"] = (X.crank - X["rank"]) >= 5
    out["late_climbers"] = {"climbers": int(X.climb.sum()), "share_with_day_mention_among_climbers": round(float((X[X.climb].day_mentions > 0).mean()), 3),
                            "share_with_day_mention_among_others": round(float((X[~X.climb].day_mentions > 0).mean()), 3),
                            "share_with_pre_mention_among_climbers": round(float((X[X.climb].pre_mentions > 0).mean()), 3),
                            "share_with_pre_mention_among_others": round(float((X[~X.climb].pre_mentions > 0).mean()), 3)}
    res["scoring"] = out; json.dump(res, open(os.path.join(OUT, "x_mentions.json"), "w"), indent=1, default=float); print(json.dumps(out, default=float))
