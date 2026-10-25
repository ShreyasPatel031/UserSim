"""rec_: reciprocity — how much the launch's team (makers + the person posting it) supported OTHER launches before
launch day, from every 2026 comment. Product Hunt is a community: people you supported may come back.

Per launch L on day D, team T (usernames), using only comments dated before D:
  rec_c7 / rec_c30 / rec_c90   comments the team left on other launches in the last 7 / 30 / 90 days
  rec_launches90               distinct other launches they commented on (90 days)
  rec_pool90                   distinct people on those launches' teams (people who might return the favour)
  rec_owed90                   of those people, how many had NOT yet commented on any of this team's launches
  rec_returned                 people who already commented on the team's earlier launches after the team supported them
  rec_active_days30            distinct days with a team comment (last 30 days)
Output: data/recip_features.json"""
import glob, json, os
from collections import defaultdict
import pandas as pd
import commenters as K

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    rows = []
    for fn in sorted(glob.glob(f"{D}/days/*.json")):
        day = os.path.basename(fn)[:10]
        for p in json.load(open(fn)):
            team = ({m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")}) - {None}
            rows.append({"id": p["id"], "slug": p["slug"], "day": day, "team": team})
    L = pd.DataFrame(rows)
    team_of = dict(zip(L.slug, L.team)); day_of = dict(zip(L.slug, L.day))
    cm = K.load_comments()
    by_user = defaultdict(list)  # username -> [(date, slug)] comments on launches they are not on the team of
    for slug, v in cm.items():
        t = team_of.get(slug, set())
        for c in v["rows"]:
            u = c["username"]
            if u and u != "[REDACTED]" and u not in t:
                by_user[u].append(((c["created"] or "")[:10], slug))
    commenters_on = defaultdict(set)  # slug -> users who commented (not team)
    for u, lst in by_user.items():
        for _, s in lst:
            commenters_on[s].add(u)
    out = {}
    for r in L.itertuples():
        d = r.day
        d7, d30, d90 = [(pd.Timestamp(d) - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in (7, 30, 90)]
        ev = [(dt, s) for u in r.team for dt, s in by_user.get(u, []) if dt < d]
        c90 = [(dt, s) for dt, s in ev if dt >= d90]
        launches90 = {s for _, s in c90}
        pool = set().union(*[team_of.get(s, set()) for s in launches90]) - r.team if launches90 else set()
        earlier_team_launches = [s for s, t in team_of.items() if t & r.team and day_of[s] < d]
        backers = set().union(*[commenters_on[s] for s in earlier_team_launches]) if earlier_team_launches else set()
        out[r.id] = {"rec_c7": sum(dt >= d7 for dt, _ in ev), "rec_c30": sum(dt >= d30 for dt, _ in ev), "rec_c90": len(c90),
                     "rec_launches90": len(launches90), "rec_pool90": len(pool), "rec_owed90": len(pool - backers),
                     "rec_returned": len(pool & backers), "rec_active_days30": len({dt for dt, _ in ev if dt >= d30})}
    json.dump(out, open(f"{D}/recip_features.json", "w"))
    v = pd.DataFrame(out.values())
    print(len(out)); print(v.describe().T[["mean", "50%", "max"]].round(1))


if __name__ == "__main__":
    main()
