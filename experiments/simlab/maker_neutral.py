"""Rank-neutral maker identity (orchestrator 09:10Z Nov 12). The API's post.makers is mostly "[REDACTED]" at 00:05 and names
the #1's makers only in later reads (a property of OUR API reads; the PH site shows the full team on launch day). Can we identify
the team for EVERY launch from sources that do not depend on the final rank, and does maker history then help honestly?
Identity sources per launch, with a cut-off c in {00:05 PT, +1 h, +2 h, +4 h} after the 00:01 PT start (thread dumps, exact
createdAt; comment-forecast days only):
  badge   authors of comments (threads and replies) carrying PH's own 'maker' badge, created <= c
  first   author of the earliest top-level comment created <= c (thread-position rule)
  store   people of the store (saved profiles) with a 'launched' event on the launch (profile crawl; not time-cut)
  hunter  the poster (never redacted in our reads)
Coverage by final rank group (#1, #2-3, #4-10, 11+): share of launches with >= 1 identified maker and mean number identified -
must be flat to be usable.
History (strictly before the day, identities of EARLIER launches from the same rank-neutral sources - badge/first over their whole
thread, store, hunter; NOT the API makers list): for the identified makers of L at 00:05, number of earlier launches made or
hunted, best earlier rank, top-3 share, mean / max ln votes of earlier launches; n identified.
Model: ridge month-forward on ln(1+votes) over the clean LM (honest_preds_v2 = PH agent's clean_v3) + the history block, on the
dump days; daily top 3/5/10, #1/#2/#3 pick in top 3, exact winner; paired by day vs the clean LM alone (2,000 day bootstraps).
Leak guard: "rank by number of identified makers" alone (random tie-break): top 3 and exact winner vs chance.
    python maker_neutral.py <cf dir (page*.jsonl.gz, cf_rows.parquet)> <launches dir> <early dir (salt)> <v3 dir> <honest_preds_v2.parquet> <out dir>
"""
import glob, gzip, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge

CFD, LDIR, EDIR, V3, HP, OUT = sys.argv[1:7]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(os.path.join(EDIR, "salt")).read().strip()
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy(); L["id"] = L.id.astype(str); L["y"] = np.log1p(pd.to_numeric(L.votes).astype(float)); L["rank"] = L.daily_rank.astype(float)
L = L.sort_values(["day", "id"]).reset_index(drop=True); bys = {s: i for i, s in enumerate(L.slug)}
L["start"] = pd.to_datetime(L.day).dt.tz_localize("UTC") + pd.to_timedelta(np.where(L.day < "2026-11-01", 7, 8), "h") + pd.Timedelta(minutes=1)
CUTS = {"0005": pd.Timedelta(minutes=4), "1h": pd.Timedelta(hours=1), "2h": pd.Timedelta(hours=2), "4h": pd.Timedelta(hours=4)}
com = {}                                                    # launch index -> list of (person, createdAt, is_top, badge_maker)
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i = bys[p_["slug"]]; seen = set(); out = com.setdefault(i, {})
        def walk(n, top):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t: out[n.get("id")] = (pid(u), pd.Timestamp(t).tz_convert("UTC"), top, "maker" in (n.get("badges") or []))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"], False)
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"], True)
days = set(pd.read_parquet(os.path.join(CFD, "cf_rows.parquet")).day.unique())
ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"])
ev = ev[ev.kind.isin(["launched", "hunted"])]; ev["target_id"] = ev.target_id.astype(str)
store_made = ev[ev.kind == "launched"].groupby("target_id").person_id.apply(set).to_dict()
STORE_IN_MODEL = os.environ.get("STORE") == "1"   # store coverage is rank-biased (saved profiles skew to winners' teams): excluded by default
L["hunter"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]


def ident(i, cut=None):
    c = com.get(i, {}).values(); st = L.start.iat[i]; lim = st + cut if cut is not None else None
    ok = [v for v in c if lim is None or v[1] <= lim]
    badge = {v[0] for v in ok if v[3]} if os.environ.get("NOBADGE") != "1" else set()   # NOBADGE=1: thread position only (live API feed may lack badges)
    tops = sorted([(v[1], v[0]) for v in ok if v[2]]); first = {tops[0][1]} if tops else set()
    store = store_made.get(L.id.iat[i], set())
    return badge, first, store


# coverage by rank group (dump days)
L["grp"] = np.where(L["rank"] == 1, "1", np.where(L["rank"] <= 3, "2-3", np.where(L["rank"] <= 10, "4-10", "11+")))
DD = L[L.day.isin(days) & L.index.isin(list(com))].copy()
res = {"design": __doc__.split("\n    python")[0], "dump_days": len(days), "launches_with_threads": int(len(DD)), "coverage": {}}
for ck, cut in CUTS.items():
    rows = []
    for i in DD.index:
        b, f, s = ident(i, cut); h = {L.hunter.iat[i]} - {None}
        rows.append({"grp": L.grp.iat[i], "badge": len(b), "first": len(f), "store": len(s), "union_no_hunter": len(b | f | s), "union": len((b | f | s) - h), "first_is_badge": float(bool(f & b)) if f else np.nan})
    C = pd.DataFrame(rows); out = {}
    for src in ("badge", "first", "store", "union_no_hunter"):
        out[src] = {g: {"share_any": round(float((x[src] > 0).mean()), 3), "mean_n": round(float(x[src].mean()), 2), "n": int(len(x))} for g, x in C.groupby("grp")}
    out["first author has the maker badge (share)"] = round(float(C.first_is_badge.mean()), 3)
    res["coverage"][ck] = out
    print(ck, json.dumps({k: {g: v["share_any"] for g, v in d.items()} for k, d in out.items() if isinstance(d, dict)}), flush=True)

# history from rank-neutral identities of earlier launches (full thread for earlier launches; store; hunter)
made_by = {}                                                 # person -> list of (day, y, rank) of launches they made (rank-neutral sources)
for i in range(len(L)):
    b, f, s = ident(i, None)
    for p in (b | f | (s if STORE_IN_MODEL else set())): made_by.setdefault(p, []).append((L.day.iat[i], L.y.iat[i], L["rank"].iat[i], i))
hunt_by = {}
for i, h in enumerate(L.hunter):
    if h: hunt_by.setdefault(h, []).append((L.day.iat[i], L.y.iat[i], L["rank"].iat[i], i))
F = []
for i in DD.index:
    b, f, s = ident(i, CUTS["0005"]); team = (b | f | (s if STORE_IN_MODEL else set())) - {L.hunter.iat[i]}; d = L.day.iat[i]
    v = [x for p in team for x in made_by.get(p, []) if x[0] < d and x[3] != i]
    v += [x for p in team for x in hunt_by.get(p, []) if x[0] < d and x[3] != i]
    v = list({x[3]: x for x in v}.values())
    ys, ks = np.array([a[1] for a in v]), np.array([a[2] for a in v])
    F.append({"id": L.id.iat[i], "n_ident": len(team), "mk_prior": np.log1p(len(v)), "mk_best": np.log1p(ks.min()) if len(v) else np.nan,
              "mk_top3": (ks <= 3).mean() if len(v) else np.nan, "mk_ymean": ys.mean() if len(v) else np.nan, "mk_ymax": ys.max() if len(v) else np.nan})
F = pd.DataFrame(F)
H = pd.read_parquet(HP)[["id", "honest"]]; H["id"] = H.id.astype(str)
D = DD[["id", "day", "y", "rank", "grp"]].merge(F, on="id").merge(H, on="id", how="inner").reset_index(drop=True); D["mon"] = D.day.str[:7]
for c in ("mk_best", "mk_top3", "mk_ymean", "mk_ymax"):
    D[c + "_na"] = D[c].isna().astype(float); D[c] = D[c].fillna(D[c].median())
print("model rows", len(D), "days", D.day.nunique(), "months", sorted(D.mon.unique()), flush=True)
BLK = ["n_ident", "mk_prior", "mk_best", "mk_top3", "mk_ymean", "mk_ymax", "mk_best_na", "mk_ymean_na"]
mons = sorted(D.mon.unique())


def fit(cols):
    p = pd.Series(np.nan, index=D.index)
    for m in mons[1:]:
        tr, te = D[D.mon < m], D[D.mon == m]; mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
        p[te.index] = Ridge(alpha=3.0).fit((tr[cols] - mu) / sd, tr.y).predict((te[cols] - mu) / sd)
    return p


def per_day(col):
    out = {}
    for d, g in D[D[col].notna()].groupby("day"):
        if len(g) < 8 or (g["rank"] <= 3).sum() < 3: continue
        g = g.assign(_j=rng.random(len(g)) * 1e-9); o = g.sort_values([col, "_j"], ascending=False)
        out[d] = [len(set(o.id[:k]) & set(g.id[g["rank"] <= k])) / k * 100 for k in (3, 5, 10)] + [float(o["rank"].iat[j] <= 3) * 100 for j in range(3)] + [float(o["rank"].iat[0] == 1) * 100]
    return pd.DataFrame(out, index=["top3", "top5", "top10", "p1", "p2", "p3", "win"]).T


def dboot(X, B=2000):
    v = X.values; bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B)])
    return {c: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j, c in enumerate(X.columns)} | {"days": int(len(v))}


D["s_lm"] = fit(["honest"]); D["s_mk"] = fit(["honest"] + BLK); D["s_n"] = D.n_ident.astype(float)
A, B_ = per_day("s_lm"), per_day("s_mk"); j = A.index.intersection(B_.index)
N = per_day("s_n"); D["s_rand"] = rng.random(len(D)); R = per_day("s_rand")
res["model"] = {"clean LM (ridge on honest_preds_v2)": dboot(A.loc[j]), "clean LM + rank-neutral maker history": dboot(B_.loc[j]),
                "difference (paired)": dboot(B_.loc[j] - A.loc[j]),
                "leak guard: rank by n identified makers alone": dboot(N), "chance (random order)": dboot(R)}
res["block_means_by_rank_group"] = D.groupby("grp")[["n_ident", "mk_prior", "mk_top3", "mk_ymean"]].mean().round(3).to_dict()
res["store_in_model"] = STORE_IN_MODEL
json.dump(res, open(os.path.join(OUT, f"maker_neutral{'_store' if STORE_IN_MODEL else ''}{'_nobadge' if os.environ.get('NOBADGE') == '1' else ''}.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k not in ("design",)}, indent=1, default=str)[:6000])
