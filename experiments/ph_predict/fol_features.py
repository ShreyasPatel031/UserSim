"""fol_: the poster's and builders' audience inside our ~19k sampled Product Hunt people (who follows them; lists read
Oct 25, so not dated), and how busy the poster is (launches they post the same day / last 7 days).
Output: data/fol_features.json"""
import glob, gzip, json, os
from collections import Counter, defaultdict
import bisect
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def day_files():
    """Finished days, plus live "today" files for days not finished yet (the live forecast's rows)."""
    days = sorted(glob.glob(f"{D}/days/*.json")); have = {os.path.basename(f) for f in days}
    return days + [f for f in sorted(glob.glob(f"{D}/today/*.json")) if os.path.basename(f) not in have]


def main():
    fol = Counter(); fans = defaultdict(set)  # username -> sampled people who follow them
    for l in gzip.open(f"{D}/ph_following.jsonl.gz", "rt"):
        r = json.loads(l)
        for u, _ in r.get("following") or []:
            fol[u] += 1; fans[u].add(r["username"])
    import commenters as K
    acts = defaultdict(list)  # person -> sorted comment dates (complete history)
    backed = defaultdict(set)  # team member -> people who commented on their launches (with date)
    slug_team = {}
    rows = []
    for fn in day_files():
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            rows.append({"id": p["id"], "day": day, "hunter": (p.get("user") or {}).get("username"),
                         "makers": [m["username"] for m in p.get("makers") or []]})
            slug_team[p["slug"]] = ({m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")}) - {None}
    for slug, v in K.load_comments().items():
        t = slug_team.get(slug, set())
        for c in v["rows"]:
            u, dt = c["username"], (c["created"] or "")[:10]
            if u and u not in t:
                acts[u].append(dt)
                for m in t:
                    backed[m].add((dt, u))
    for u in acts:
        acts[u].sort()
    L = pd.DataFrame(rows)
    L["d"] = pd.to_datetime(L.day)
    same = L.groupby(["hunter", "day"]).id.transform("count")
    out = {}
    for r, s in zip(L.itertuples(), same):
        prev = L[(L.hunter == r.hunter) & (L.d < r.d) & (L.d >= r.d - pd.Timedelta(days=7))] if r.hunter else []
        mf = [fol[m] for m in r.makers if m != r.hunter]
        out[r.id] = {"fol_hunter": float(np.log1p(fol[r.hunter])), "fol_team": float(np.log1p(sum(mf))),
                     "fol_team_max": float(np.log1p(max(mf, default=0))),
                     "busy_same_day": int(s), "busy_7d": int(len(prev))}
        team = ({r.hunter} if r.hunter else set()) | set(r.makers)
        F = set().union(*[fans.get(m, set()) for m in team]) if team else set()
        d30 = (r.d - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        act = sum(1 for u in F if (lambda a: bisect.bisect_left(a, r.day) - bisect.bisect_left(a, d30))(acts.get(u, [])) > 0)
        loyal = {u for m in team for dt, u in backed.get(m, ()) if dt < r.day} & F
        out[r.id].update({"fol_active30": float(np.log1p(act)), "fol_loyal": float(np.log1p(len(loyal))),
                          "fol_any": float(np.log1p(len(F)))})
    json.dump(out, open(f"{D}/fol_features.json", "w"))
    print(len(out), pd.DataFrame(out.values()).describe().T[["mean", "50%", "max"]].round(2))


if __name__ == "__main__":
    main()
