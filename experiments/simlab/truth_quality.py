import json, gzip, glob, re, html, sys
import numpy as np, pandas as pd
SP = sys.argv[1]
CN = json.load(open(f"{SP}/conc/cache.json")); S = sorted({k.split("|", 1)[1] for k in CN if k.startswith("ranked|")})
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["team"] = [{str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if u and not str(u).startswith("[")} | ({str(p).lower()} if p else set()) for m, p in zip(L.makers, L.poster)]
bys = {s: r for s, r in zip(L.slug, L.itertuples())}; need = set(S); rows = {}
clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in need: continue
        s = p_["slug"]; out = rows.setdefault(s, {})
        tops = [e["node"] for e in ((p_.get("threads") or {}).get("edges") or [])]
        def walk(n, top):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = clean(n.get("bodyHtml"))
            out[n.get("id")] = (u, t, n.get("createdAt") or "", top)
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"], False)
        for n in tops: walk(n, True)
R = []
for s in S:
    r = bys[s]; c = rows.get(s, {})
    tops = sorted([(v[2], v[0]) for v in c.values() if v[3] and v[2]])
    first_author = tops[0][1] if tops else ""
    newteam = {first_author, str(r.poster or "").lower()} - {""}
    old = [k for k, v in c.items() if v[0] not in r.team and len(v[1]) > 15]
    new = [k for k, v in c.items() if v[0] not in (r.team | newteam) and len(v[1]) > 15]
    R.append(dict(s=s, rank=r.daily_rank, n_old=len(old), n_new=len(new), first_in_team=first_author in r.team, named_makers=len(r.team) - 1))
D = pd.DataFrame(R); D["dropped"] = D.n_old - D.n_new; D["share"] = D.dropped / D.n_old.clip(lower=1)
D["g"] = np.where(D["rank"] == 1, "1", np.where(D["rank"] <= 3, "2-3", np.where(D["rank"] <= 10, "4-10", "11+")))
print("launches", len(D), "with any extra dropped", int((D.dropped > 0).sum()), "mean share dropped", round(D.share.mean(), 3), "median", D.share.median())
print(D.groupby("g")[["n_old", "dropped", "share"]].mean().round(3).assign(n=D.groupby("g").size(), first_author_already_team=D.groupby("g").first_in_team.mean().round(2)))
D.to_parquet(f"{SP}/truthq.parquet")
json.dump({s: {k: v for k, v in rows[s].items()} for s in rows}, open(f"{SP}/truthq_comments.json", "w"))
