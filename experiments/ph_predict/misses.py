"""Where the current model fails (Sep–Oct): launches that made a day's top 5 but were ranked low before launch,
and launches predicted top 3 that flopped. Compares them with correct calls on every pre-launch input, plus a few
new ones (posting time, how many of our 19k sampled people follow the team).
Output: results/misses.csv (one row per launch with group), results/misses_diff.csv (input differences)."""
import gzip, json, os
from collections import Counter, defaultdict
import numpy as np, pandas as pd
from vote_sim import load, D, R


def main():
    P = pd.read_csv(f"{R}/predictions.csv"); P["id"] = P.id.astype(str)
    P = P[P.day >= "2026-09-01"].copy()
    P["prank"] = P.groupby("day").pred.rank(ascending=False, method="first")
    L = load().set_index("id")
    fol = Counter()  # username -> sampled people who follow them
    for l in gzip.open(f"{D}/ph_following.jsonl.gz", "rt"):
        for u, _ in json.loads(l).get("following") or []:
            fol[u] += 1
    created = {}
    for f in os.listdir(f"{D}/days"):
        for p in json.load(open(f"{D}/days/{f}")):
            created[p["id"]] = p["createdAt"]
    P["hour_pt"] = [(pd.Timestamp(created[i]) - pd.Timedelta(hours=7)).hour if i in created else np.nan for i in P.id]
    P["sample_follow_hunter"] = [fol[L.hunter.get(i)] if i in L.index else 0 for i in P.id]
    P["sample_follow_team"] = [sum(fol[m] for m in L.makers.get(i, set())) if i in L.index else 0 for i in P.id]
    P["group"] = np.select([(P.dailyRank <= 5) & (P.prank > 10), (P.dailyRank <= 5) & (P.prank <= 5),
                            (P.prank <= 3) & (P.dailyRank > 15)], ["missed winner", "caught winner", "false alarm"], "other")
    P.to_csv(f"{R}/misses.csv", index=False)
    num = [c for c in P.columns if P[c].dtype.kind in "fi" and c not in
           ("votes", "comments", "dailyRank", "weeklyRank", "monthlyRank", "pred", "prank", "is_today")]
    g = P.groupby("group")[num].median().T
    sd = P[num].std().replace(0, np.nan)
    mean = P.groupby("group")[num].mean().T
    g["missed_vs_caught (sd)"] = (mean["missed winner"] - mean["caught winner"]) / sd
    g["missed_vs_other (sd)"] = (mean["missed winner"] - mean["other"]) / sd
    g = g.reindex(g["missed_vs_other (sd)"].abs().sort_values(ascending=False).index)
    g.to_csv(f"{R}/misses_diff.csv")
    print(P.group.value_counts().to_dict())
    print(g.head(30).round(2).to_string())
    cols = ["day", "name", "tagline", "dailyRank", "prank", "votes", "ph_hunter_followers", "ph_self_hunted",
            "ph_maker_max_followers", "sample_follow_hunter", "sample_follow_team", "hour_pt"]
    print(P[P.group == "missed winner"].sort_values("prank", ascending=False)[cols].head(40).to_string(index=False))


if __name__ == "__main__":
    main()
