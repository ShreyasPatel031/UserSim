"""Audience for a new product, known before launch day, for the simulation (prefix nsa_). For every launch:
  nsa_hunter_ties   pool people who upvoted or commented on the hunter's earlier hunted launches (a new team's
                    nearest network on Product Hunt), active in the 30 days before
  nsa_comp_ties     pool people who upvoted the 5 most similar earlier launches (competitors by meaning of name,
                    tagline, description), active in the 30 days before
  nsa_team_ties     pool people who backed the makers' earlier launches (makers only), active in the 30 days before
  nsa_active        pool people active in the 30 days before (the day's audience on Product Hunt)
  nsa_ph_makers / nsa_ph_hunter   Product Hunt followers of the makers (sum) and of the hunter
  nsa_x_makers      X followers of the makers (sum, fxtwitter profiles)
All counts log1p. Follower counts are as fetched (after launch for older days), the same footing as the launch model.
usage: python newsim_audience.py <warehouse dir> -> data/nsa_features.json"""
import bisect, glob, gzip, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main(wh):
    L = {}
    for f in sorted(glob.glob(f"{D}/days/*.json")):
        for p in json.load(open(f)):
            L[str(p["id"])] = {"day": f[-15:-5], "makers": [m for m in p.get("makers") or [] if isinstance(m, dict)], "hunter": (p.get("user") or {})}
    xf = {}
    for l in gzip.open(f"{D}/x_people.jsonl.gz", "rt"):
        r = json.loads(l)
        if r.get("profile"):
            xf[r["handle"].lower()] = r["profile"].get("followers") or 0
    E = pd.concat([pd.read_parquet(f, columns=["person", "launch_id", "date"]) for f in glob.glob(f"{wh}/events/*.parquet")])
    E["launch_id"] = E.launch_id.astype(str)
    E = E.sort_values("date")
    by_launch = {i: (list(g.date), list(g.person)) for i, g in E.groupby("launch_id")}   # sorted by date
    by_date = {d: set(g.person) for d, g in E.groupby("date")}
    dates = sorted(by_date)
    act_cache = {}

    def active_set(d):   # people with any event in the 30 days before d
        if d not in act_cache:
            cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            s = set()
            for x in dates[bisect.bisect_left(dates, cut): bisect.bisect_left(dates, d)]:
                s |= by_date[x]
            act_cache[d] = s
        return act_cache[d]

    def engaged(ids, d):
        out = set()
        for i in ids:
            g = by_launch.get(i)
            if g:
                out.update(g[1][: bisect.bisect_left(g[0], d)])
        return out & active_set(d)
    by_maker, by_hunter = defaultdict(list), defaultdict(list)
    for i, r in sorted(L.items(), key=lambda kv: kv[1]["day"]):
        for m in r["makers"]:
            by_maker[m.get("username")].append(i)
        by_hunter[r["hunter"].get("username")].append(i)
    Z = np.load(f"{D}/emb.npz"); zid = [str(x) for x in Z["launch_ids"]]; V = Z["launch"] / np.linalg.norm(Z["launch"], axis=1, keepdims=True)
    zix = {x: k for k, x in enumerate(zid)}; zday = np.array([L.get(x, {}).get("day", "9999") for x in zid])
    days_active = {}
    out = {}
    for n, (i, r) in enumerate(L.items()):
        d = r["day"]
        team = {m.get("username") for m in r["makers"]} - {None}
        team_prev = {j for m in team for j in by_maker[m] if L[j]["day"] < d}
        h = r["hunter"].get("username")
        hunt_prev = {j for j in by_hunter.get(h, []) if L[j]["day"] < d} if h and h not in team else set()
        comp = []
        if i in zix:
            s = V @ V[zix[i]]; s[zday >= d] = -9
            comp = [zid[k] for k in np.argsort(-s)[:5]]
        if d not in days_active:
            days_active[d] = len(active_set(d))
        out[i] = {"nsa_team_ties": float(np.log1p(len(engaged(team_prev, d)))), "nsa_hunter_ties": float(np.log1p(len(engaged(hunt_prev, d)))),
                  "nsa_comp_ties": float(np.log1p(len(engaged(comp, d)))), "nsa_active": float(np.log1p(days_active[d])),
                  "nsa_ph_makers": float(np.log1p(sum(m.get("followersCount") or 0 for m in r["makers"]))),
                  "nsa_ph_hunter": float(np.log1p(r["hunter"].get("followersCount") or 0)),
                  "nsa_x_makers": float(np.log1p(sum(xf.get((m.get("twitterUsername") or "").lower(), 0) for m in r["makers"])))}
        if n % 1000 == 0:
            print(n, len(L), flush=True)
    json.dump(out, open(f"{D}/nsa_features.json", "w"))
    print("saved", len(out))


if __name__ == "__main__":
    main(sys.argv[1])
