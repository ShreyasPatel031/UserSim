"""showdead check (orchestrator, 2026-11-03): are any 15-min false flags (Oct 2-14, votes + who) dead or deleted on HN?
HN item API, today = upper bound on what was knowable at 15 min."""
import sys, time, json
sys.path.insert(0, "/home/user/UserSim/experiments/hn_sim")
import pandas as pd, requests
import top100 as H, odds_live as OL
S = pd.read_parquet(H.CACHE + "/wb15_scores.parquet")
p = H.stories()[["post_id", "day"]]
S = S.merge(p, on="post_id")
S = S[(S.day >= "2026-10-02") & (S.day <= "2026-10-14")].reset_index(drop=True)
L = OL.lists()
S["y"] = S.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)
k = int(S.y.sum())
S["flag"] = S["+ votes + who"].rank(ascending=False, method="first") <= k
fn = S[S.flag & (S.y == 0)]
dead = {}
for pid in fn.post_id:
    try:
        it = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{int(pid)}.json", timeout=20).json() or {}
        dead[pid] = (bool(it.get("dead")), bool(it.get("deleted")))
    except Exception:
        dead[pid] = (None, None)
    time.sleep(0.25)
d = pd.DataFrame([(a, b[0], b[1]) for a, b in dead.items()], columns=["post_id", "dead", "deleted"])
print(f"Oct 2-14: winners {k}, flags {int(S.flag.sum())}, flagged winners {int((S.flag & (S.y == 1)).sum())}, flagged non-winners {len(fn)}")
print(f"flagged non-winners dead now: {int(d.dead.sum())}, deleted: {int(d.deleted.sum())}, unknown: {int(d.dead.isna().sum())}")
