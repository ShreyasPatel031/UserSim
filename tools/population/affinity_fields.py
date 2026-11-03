"""Which-launch test (affinity): among pool people who turned up on PT day d, which of d's launches did they vote for?
For each (person, day) with >=1 vote on a day-d launch, score every featured launch of d by each feature; report the within-
person-day AUC (P(voted launch scores above a non-voted one), ties 0.5) and coverage (share of person-days where the feature is
non-zero for at least one launch). Features use only events before d except LATE_* (read after d).
Inputs (DATA_DIR): days/<date>.json (launches with makers + hunter), ph_team_history.jsonl, makers_by_product.jsonl,
up/upvotes_page1_full.jsonl, daily/1102/following_page1.jsonl, people_v3g/events.parquet.
Usage: python affinity_fields.py DATA_DIR [FIRST_DAY LAST_DAY]
"""
import glob, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd

D = sys.argv[1]
d0, d1 = (sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ("2026-10-01", "2026-10-25")
PT = "America/Los_Angeles"
pday = lambda s: pd.to_datetime(s, utc=True, format="mixed").dt.tz_convert(PT).dt.tz_localize(None).dt.normalize()

# launches, teams, topics
launch_day, team, topics = {}, defaultdict(set), {}
for p in sorted(glob.glob(f"{D}/days/*.json")):
    for L in json.load(open(p)):
        pid = str(L["id"])
        launch_day[pid] = pd.Timestamp(os.path.basename(p)[:10])
        for m in L.get("makers") or []:
            if m.get("username"):
                team[pid].add(m["username"].lower())
        if (L.get("user") or {}).get("username"):
            team[pid].add(L["user"]["username"].lower())
        topics[pid] = {e["node"]["name"] for e in ((L.get("topics") or {}).get("edges") or [])}
slug2id = {}
for p in sorted(glob.glob(f"{D}/days/*.json")):
    for L in json.load(open(p)):
        slug2id[L["slug"]] = str(L["id"])
for l in open(f"{D}/makers_by_product.jsonl"):
    r = json.loads(l)
    pid = slug2id.get(r.get("slug"))
    if pid:
        team[pid] |= {m["handle"].lower() for m in r.get("makers") or [] if m.get("handle")}
th = pd.read_json(f"{D}/ph_team_history.jsonl", lines=True)
th["user"] = th.username.str.lower()
th["day"] = pday(th.featuredAt.fillna(th.createdAt))
th["post_id"] = th.post_id.astype(str)
member_posts = th.groupby("user").apply(lambda g: list(zip(g.post_id, g.day)), include_groups=False).to_dict()
for pid, ms in team.items():  # also day-file launches as team posts
    for m in ms:
        member_posts.setdefault(m, []).append((pid, launch_day[pid]))

# person histories
u = pd.read_json(f"{D}/up/upvotes_page1_full.jsonl", lines=True, dtype={"post_id": str})
u = u[u.post_id.notna()].copy()
u["user"] = u.username.str.lower(); u["post_id"] = u.post_id.astype(str); u["day"] = pday(u.launched_at)
meta = u.groupby("user").agg(hm=("has_more", "first"), oldest=("day", "min"))
ups = u.groupby("user").apply(lambda g: list(zip(g.post_id, g.day)), include_groups=False).to_dict()
e = pd.read_parquet(f"{D}/people_v3g/events.parquet")
c = e[(e.platform == "producthunt") & (e.kind == "comment")].copy()
c["user"] = c.person_id.str.replace("^ph:", "", regex=True).str.lower()
c["t"] = pd.to_datetime(c.ts, utc=True, format="mixed").dt.tz_convert(PT).dt.tz_localize(None)
cms = c.groupby("user").apply(lambda g: list(zip(g.target_id.astype(str), g.t)), include_groups=False).to_dict()
fol = pd.read_json(f"{D}/daily/1102/following_page1.jsonl", lines=True)
follows = fol.groupby(fol.username.str.lower()).followee.apply(lambda s: set(s.str.lower())).to_dict()
post_team = defaultdict(set)  # post -> members, for "voted for this team before"
for m, ps in member_posts.items():
    for pid, _ in ps:
        post_team[pid].add(m)

day_launches = defaultdict(list)
for pid, d in launch_day.items():
    day_launches[d].append(pid)

feats = ["follows_team_LATE", "upvoted_team_before", "commented_team_before", "commented_this_launch_before_day",
         "topic_share_30d", "team_member_upvoted_person_before", "LATE_votes_count"]
votes_count = {}
for p in sorted(glob.glob(f"{D}/days/*.json")):
    for L in json.load(open(p)):
        votes_count[str(L["id"])] = L.get("votesCount") or 0
made_by = defaultdict(set)  # user -> posts they made/hunted
for m, ps in member_posts.items():
    for pid, _ in ps:
        made_by[m].add(pid)

auc = defaultdict(list); cov = defaultdict(int); n_pd = 0; pairs = []
for d in pd.date_range(d0, d1):
    Ls = day_launches.get(d, [])
    if len(Ls) < 2:
        continue
    Lset = set(Ls)
    elig = meta[(meta.hm == False) | (meta.oldest <= d - pd.Timedelta(days=30))].index
    for user in elig:
        h = ups.get(user, [])
        voted = {p for p, dd in h if p in Lset}
        if not voted or len(voted) == len(Ls):
            continue
        n_pd += 1
        before = [(p, dd) for p, dd in h if dd < d]
        before_ids = {p for p, _ in before}
        teams_voted = set().union(*(post_team.get(p, set()) for p in before_ids)) if before_ids else set()
        cm = [(p, t) for p, t in cms.get(user, []) if t < d]
        cm_ids = {p for p, _ in cm}
        teams_cm = set().union(*(post_team.get(p, set()) for p in cm_ids)) if cm_ids else set()
        tcount = defaultdict(int); tn = 0
        for p, dd in before:
            if dd >= d - pd.Timedelta(days=30) and p in topics:
                tn += 1
                for t in topics[p]:
                    tcount[t] += 1
        mine = made_by.get(user, set())
        fl = follows.get(user, set())
        rows = []
        for L in Ls:
            tm = team.get(L, set()) - {user}
            f = {"follows_team_LATE": len(tm & fl),
                 "upvoted_team_before": len(tm & teams_voted),
                 "commented_team_before": len(tm & teams_cm),
                 "commented_this_launch_before_day": int(L in cm_ids),
                 "topic_share_30d": (max((tcount[t] for t in topics.get(L, ())), default=0) / tn) if tn else 0,
                 "team_member_upvoted_person_before": sum(1 for m in tm for p, dd in ups.get(m, []) if p in mine and dd < d),
                 "LATE_votes_count": votes_count.get(L, 0)}
            rows.append((L in voted, f))
        P = [f for v, f in rows if v]; N = [f for v, f in rows if not v]
        for a in P:
            for b in N:
                pairs.append([np.log1p(a[k]) - np.log1p(b[k]) if k == "LATE_votes_count" else a[k] - b[k] for k in feats])
        for k in feats:
            pos = np.array([f[k] for v, f in rows if v]); neg = np.array([f[k] for v, f in rows if not v])
            if (pos != 0).any() or (neg != 0).any():
                cov[k] += 1
            gt = (pos[:, None] > neg[None, :]).mean(); eq = (pos[:, None] == neg[None, :]).mean()
            auc[k].append(gt + 0.5 * eq)
print(f"person-days with a vote: {n_pd:,} ({d0}..{d1})")
out = pd.DataFrame({k: {"AUC": np.mean(auc[k]), "coverage": cov[k] / max(n_pd, 1),
                        "AUC_where_covered": np.nan} for k in feats}).T
print(out[["AUC", "coverage"]].round(3).to_string())


# conditional logit on pairwise differences (voted minus not-voted), symmetric: does each field add beyond popularity?
X = np.array(pairs, dtype=float)
X = np.vstack([X, -X]); y = np.r_[np.ones(len(pairs)), np.zeros(len(pairs))]
sd = X.std(0); sd[sd == 0] = 1; Xs = X / sd
w = np.zeros(X.shape[1])
for _ in range(25):  # Newton
    pr = 1 / (1 + np.exp(-Xs @ w)); g = Xs.T @ (y - pr); H = (Xs * (pr * (1 - pr))[:, None]).T @ Xs + 1e-6 * np.eye(len(w))
    w += np.linalg.solve(H, g)
se = np.sqrt(np.diag(np.linalg.inv(H)))
print(f"\npairwise conditional logit, {len(pairs):,} pairs (standardised coef, z; pairs within a person-day are not independent, z is optimistic)")
print(pd.DataFrame({"coef": w, "z": w / se}, index=feats).round(3).to_string())
