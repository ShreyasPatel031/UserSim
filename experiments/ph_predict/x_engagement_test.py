"""X launch-post engagement (raw/x/engagement.jsonl, Grok Bot's team; PARTIAL: Oct 1-25, 105 of 359 launches with a
found post; engagers listed for the highest-engagement posts only; no likers).
1. Do a launch's real Product Hunt voters engage with its X launch post more than other active people do?
   X engagers (reposters, quoters, repliers) are matched to Product Hunt people through the X handle on their PH
   profile (store people.twitter). For each launch with engagers fetched: of the matched engagers, the share who voted on
   (upvoted or commented) the launch on its day, vs the same share for the day's other launches (a placebo: the same
   engagers' votes on launches they did not engage with).
2. Pre-launch input: posts dated before 00:00 PT on launch day only (count, public engagement counts at fetch). Coverage
   is reported; with so few, the stage-1 / top-k tests are reported as not measurable if under 50 launches.
usage: SIMLAB_DATA=data_v2 python x_engagement_test.py <engagement.jsonl> -> results/x_engagement_test.json"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store


def main(path):
    R = [json.loads(l) for l in open(path) if l.strip()]
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str)); day = dict(zip(I.id, I.day))
    tw = {str(t).lower().lstrip("@"): p for p, t in zip(P.person, P.twitter) if isinstance(t, str) and t and t != "None"}
    E = E.assign(item=E.item.astype(str)); Ev = E[E.item.map(day) == E.date]
    votes = Ev.groupby("person").item.apply(set).to_dict()
    lineup = I.groupby("day").id.apply(set).to_dict()
    eng = [r for r in R if r["kind"] in ("repost", "quote", "reply")]
    res = {"rows": len(R), "posts": sum(r["kind"] == "post" for r in R), "engager_rows": len(eng),
           "launches_with_engagers": len({r["launch_id"] for r in eng})}
    matched, hits, placebo_hits, placebo_n = 0, 0, 0, 0
    seen = set()
    for r in eng:
        x, u = str(r["launch_id"]), tw.get((r.get("user") or "").lower())
        if not u or (x, u) in seen or x not in day:
            continue
        seen.add((x, u)); matched += 1
        v = votes.get(u, set())
        hits += x in v
        others = lineup.get(day[x], set()) - {x}
        placebo_hits += len(v & others); placebo_n += len(others)
    res["engagers_matched_to_PH_people"] = matched
    res["share_who_voted_on_the_launch"] = round(hits / matched, 3) if matched else None
    res["share_voting_on_each_other_launch_that_day"] = round(placebo_hits / placebo_n, 4) if placebo_n else None
    if matched:
        p0 = placebo_hits / max(placebo_n, 1); se = np.sqrt(max(hits / matched * (1 - hits / matched), 1e-9) / matched)
        res["lift"] = round((hits / matched) / p0, 1) if p0 else None
        res["share_ci95"] = [round(max(0, hits / matched - 1.96 * se), 3), round(min(1, hits / matched + 1.96 * se), 3)]
    # how many of a launch's real voters are reachable through X at all: voters with a known X handle
    xs = set(tw.values()); vl = Ev.groupby("item").person.apply(set)
    oct_ids = [x for x in day if "2026-10-01" <= day[x] <= "2026-10-25"]
    res["share_of_Oct_voters_with_X_handle"] = round(float(np.mean([len(vl.get(x, set()) & xs) / max(len(vl.get(x, set())), 1) for x in oct_ids if len(vl.get(x, set()))])), 3)
    # pre-launch posts
    pre = [r for r in R if r["kind"] == "post" and pd.Timestamp(r["post_at"]) < pd.Timestamp(r["day"]).tz_localize("America/Los_Angeles")]
    res["prelaunch_posts"] = len(pre); res["launches_with_prelaunch_post"] = len({r["launch_id"] for r in pre})
    res["prelaunch_test"] = "not measurable (fewer than 50 launches)" if res["launches_with_prelaunch_post"] < 50 else "run"
    json.dump(res, open("results/x_engagement_test.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
