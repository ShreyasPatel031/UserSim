"""ctx_: theories about close calls, all from data dated before launch day.
  Standing in the day's field   within-day percentile / gap-to-best of the strongest inputs (crowded days)
  Poster spread thin            poster's other launches that day; this launch's standing among them (by maker reach)
  Who comments before launch    pre-launch commenters on the upcoming page: team regulars (backed the team before),
                                active (commented elsewhere in last 30 days), new accounts (joined < 30 days before)
  Swap circles                  people the team supported AND who supported the team (mutual), active in last 7/30 days
Output: data/ctx_features.json"""
import bisect, glob, gzip, json, os, pickle
from collections import defaultdict
import numpy as np, pandas as pd
import commenters as K

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STRONG = ["ph_hunter_followers", "ph_maker_max_followers", "hist_hunter_rel", "fol_hunter", "fol_team", "cm_pre_users",
          "rec_c30", "ph_n_makers", "cm_maker_comm_active30", "x_maker_max_followers"]


def main():
    rows = []
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            team = ({m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")}) - {None}
            rows.append({"id": p["id"], "slug": p["slug"], "day": day, "team": team,
                         "hunter": (p.get("user") or {}).get("username")})
    L = pd.DataFrame(rows)
    team_of = dict(zip(L.slug, L.team)); day_of = dict(zip(L.slug, L.day))
    joined = {}
    for f in ("ph_profiles2", "ph_profiles_rest"):
        for l in gzip.open(f"{D}/{f}.jsonl.gz", "rt"):
            p = json.loads(l); joined[p["username"]] = (p.get("joined") or "")[:10]
    acts = defaultdict(list)                 # user -> comment dates (not on own launches)
    on = defaultdict(list)                   # slug -> [(date, user)]
    gave = defaultdict(list)                 # user -> [(date, slug)] support given
    for slug, v in K.load_comments().items():
        t = team_of.get(slug, set())
        for c in v["rows"]:
            u, dt = c["username"], (c["created"] or "")[:10]
            if u and u != "[REDACTED]" and u not in t:
                acts[u].append(dt); on[slug].append((dt, u)); gave[u].append((dt, slug))
    for u in acts:
        acts[u].sort()
    launches_of = defaultdict(list)          # member -> their slugs
    for s, t in team_of.items():
        for m in t:
            launches_of[m].append(s)
    out = {}
    for r in L.itertuples():
        d = r.day
        d7, d30 = [(pd.Timestamp(d) - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in (7, 30)]
        pre = [u for dt, u in on.get(r.slug, []) if dt < d]
        backers = {u for m in r.team for s in launches_of[m] if day_of[s] < d for dt, u in on.get(s, []) if dt < d}
        active = lambda u, a: bisect.bisect_left(acts.get(u, []), d) - bisect.bisect_left(acts.get(u, []), a) > 0
        # people whose launches the team commented on (all members of those teams)
        sup_people = set().union(*[team_of.get(s, set()) for m in r.team for dt, s in gave.get(m, []) if dt < d] or [set()]) - r.team
        mutual = sup_people & backers
        pre_s = set(pre)
        out[r.id] = {"ctx_pre_regulars": len(pre_s & backers), "ctx_pre_active30": sum(active(u, d30) for u in pre_s),
                     "ctx_pre_new": sum(bool(joined.get(u)) and joined[u] >= d30 for u in pre_s),
                     "ctx_mutual": len(mutual), "ctx_mutual_active7": sum(active(u, d7) for u in mutual),
                     "ctx_mutual_active30": sum(active(u, d30) for u in mutual)}
    C = pd.DataFrame.from_dict(out, orient="index")
    # standing in the day's field and poster spread (needs the main table's inputs)
    df = pickle.load(open(f"{D}/build_cache.pkl", "rb")).drop_duplicates("id").set_index("id")
    df = df.join(C, how="left")
    for f in STRONG + ["ctx_mutual_active7", "ctx_pre_regulars"]:
        if f in df:
            df[f"ctx_pct_{f}"] = df.groupby("day")[f].rank(pct=True)
            df[f"ctx_gap_{f}"] = df[f] - df.groupby("day")[f].transform("max")
    hk = L.drop_duplicates("id").set_index("id").hunter.reindex(df.index)
    df["ctx_hunter_n_today"] = df.groupby([df.day, hk]).day.transform("count")
    df["ctx_hunter_rank_today"] = df.groupby([df.day, hk]).ph_maker_max_followers.rank(ascending=False, method="first")
    cols = [c for c in df.columns if c.startswith("ctx_")]
    res = {i: {c: (None if pd.isna(v) else float(v)) for c, v in row.items()} for i, row in df[cols].iterrows()}
    json.dump(res, open(f"{D}/ctx_features.json", "w"))
    print(len(res), len(cols)); print(df[cols].describe().T[["mean", "50%", "max"]].round(2).head(12))


if __name__ == "__main__":
    main()
