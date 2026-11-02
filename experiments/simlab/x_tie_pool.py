"""Pre-launch X ties as a person-model input (Grok Bot, Nov 2; runs on the covered October launches while the X backfill
lands). A pool person is X-tied to launch i if their X account replied to or quoted one of i's team handles' posts, with
the reply / quote dated before 00:00 PT on i's launch day (posts in the 30 days before). Reposts carry no time: dropped.
1. Person level: X-tied people's vote rate on their launch vs the same people's rate on the day's other launches
   (placebo: same people, same day), rate ratio with a bootstrap interval over launches.
2. Pool level: per covered launch, the simulation's expected pool picks S (pna_, page-free, all earlier months) and
   S_x = S + lam * n_xtied, lam = the X-tied conversion rate fitted FORWARD ONLY on earlier covered days. Within-day
   Spearman of S and S_x with the real pool votes (pool people who voted on launch day), paired over days with >= 3
   covered launches; top 3 by pool votes and by final votes among the covered launches.
Decision rule fixed before the run: the X tie helps the pool simulation if the within-day Spearman gain (S_x - S) has a
95% interval above 0.
Inputs (bucket; usernames stay in the local cache, never committed): raw/x/prelaunch_posts.jsonl, prelaunch_engagers.jsonl,
raw/x/prelaunch_wip/dm_gate.json, raw/x_handles_pool.json, tables_v2/events.parquet, tmp/e5/xtest/inputs.tgz (data/days,
people.parquet, items.parquet), deploy/20261102_pna/pnx_features.json (pna_ rows under pnx_ names).
usage: python -m simlab.x_tie_pool [cache_dir] -> simlab/reports/x_tie_pool.json (counts and rates only)"""
import glob, json, os, subprocess, sys, tarfile
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from .x_prelaunch_e1 import utc, snowflake_utc, cutoff_utc, jl

HERE = os.path.dirname(os.path.abspath(__file__))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
FILES = {"posts.jsonl": f"{B}/raw/x/prelaunch_posts.jsonl", "engagers.jsonl": f"{B}/raw/x/prelaunch_engagers.jsonl",
         "dm_gate.json": f"{B}/raw/x/prelaunch_wip/dm_gate.json", "x_handles_pool.json": f"{B}/raw/x_handles_pool.json",
         "events.parquet": f"{B}/tables_v2/events.parquet", "inputs.tgz": f"{B}/tmp/e5/xtest/inputs.tgz",
         "pool.json": f"{B}/deploy/20261102_pna/pnx_features.json"}


def fetch(cache):
    os.makedirs(cache, exist_ok=True)
    for name, url in FILES.items():
        subprocess.run(["gsutil", "-q", "cp", url, os.path.join(cache, name)], check=True)
    with tarfile.open(os.path.join(cache, "inputs.tgz")) as t:
        t.extractall(cache, filter="data")


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if not len(x):
        return None
    bs = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 4), [round(float(v), 4) for v in np.percentile(bs, [2.5, 97.5])], int(len(x))]


def main(cache):
    fetch(cache)
    # team handles and launch days
    team, lday = {}, {}
    for f in sorted(glob.glob(os.path.join(cache, "ph_predict", "data", "days", "*.json"))):
        for p in json.load(open(f)):
            hs = {(m.get("twitterUsername") or "").lower() for m in (p.get("makers") or []) if isinstance(m, dict)}
            hs |= {((p.get("user") or {}).get("twitterUsername") or "").lower()}
            team[str(p["id"])] = hs - {""}; lday[str(p["id"])] = os.path.basename(f)[:10]
    gate = json.load(open(os.path.join(cache, "dm_gate.json")))
    gdays = set(gate.get("open_by_day", {})); open_ids = {x for v in gate.get("open_by_day", {}).values() for x in v}
    covered = {x for x, hs in team.items() if hs and lday[x] in gdays and x not in open_ids}
    # X handle -> PH person
    x2ph = {str(v).lower().lstrip("@"): k for k, v in json.load(open(os.path.join(cache, "x_handles_pool.json"))).items() if v}
    P = pd.read_parquet(os.path.join(cache, "simlab", "data_v2", "people.parquet"))
    x2ph.update({str(t).lower().lstrip("@"): p for p, t in zip(P.person, P.twitter) if isinstance(t, str) and t and t != "None"})
    # dated pre-launch engagers per (handle, launch day)
    posts = jl(os.path.join(cache, "posts.jsonl")); post_hd = {str(r["post_id"]): ((r.get("handle") or "").lower(), (r.get("launch_day") or "")[:10]) for r in posts}
    eng = defaultdict(list)
    for r in jl(os.path.join(cache, "engagers.jsonl")):
        if r.get("kind") not in ("reply", "quote"):
            continue
        t = utc(r["engager_created_at"]) if r.get("engager_created_at") else (pd.Timestamp(snowflake_utc(r["engager_post_id"])) if r.get("engager_post_id") else None)
        hd = post_hd.get(str(r.get("post_id")))
        if t is not None and hd:
            eng[hd].append((t, (r.get("user") or "").lower()))
    tied = {}
    for x in covered:
        d = lday[x]; cut = pd.Timestamp(cutoff_utc(d))
        users = {u for h in team[x] for t, u in eng.get((h, d), []) if t < cut}
        tied[x] = {x2ph[u] for u in users if u in x2ph}
    # real votes on launch day
    E = pd.read_parquet(os.path.join(cache, "events.parquet"))
    E = E[(E.platform == "producthunt") & E.kind.isin(["upvote", "comment"])]
    E = E.assign(person=E.person_id.str.replace("^ph:", "", regex=True), day=E.ts.str[:10], id=E.target_id.astype(str))
    E = E[E.id.map(lday).eq(E.day)]
    voters = E.groupby("id").person.apply(set).to_dict()
    lineup = defaultdict(list)
    for x, d in lday.items():
        lineup[d].append(x)
    # 1. person level
    rr, own_r, plc_r, n_tied = [], [], [], 0
    for x in sorted(covered):
        T_ = tied[x]
        if not T_:
            continue
        n_tied += len(T_)
        own = np.mean([u in voters.get(x, set()) for u in T_])
        others = [y for y in lineup[lday[x]] if y != x]
        plc = np.mean([u in voters.get(y, set()) for u in T_ for y in others]) if others else np.nan
        own_r.append(own); plc_r.append(plc); rr.append(own - plc)
    rng = np.random.default_rng(0)
    res = {"gate": {k: v for k, v in gate.items() if k != "open_by_day"}, "covered_launches": len(covered),
           "covered_with_xtied_pool_people": int(sum(bool(v) for v in tied.values())), "xtied_pool_people_total": n_tied,
           "person_level": {"vote_rate_on_own_launch": boot(own_r, rng), "vote_rate_on_same_day_other_launches": boot(plc_r, rng),
                            "difference": boot(rr, rng)}}
    if own_r and np.nanmean(plc_r) > 0:
        res["person_level"]["rate_ratio"] = round(float(np.mean(own_r) / np.nanmean(plc_r)), 1)
    # 2. pool level
    S = pd.DataFrame.from_dict(json.load(open(os.path.join(cache, "pool.json"))), orient="index")
    I = pd.read_parquet(os.path.join(cache, "simlab", "data_v2", "items.parquet")); I["id"] = I.id.astype(str)
    A = pd.DataFrame({"id": sorted(covered)}); A["day"] = A.id.map(lday)
    A["S"] = A.id.map(S["pnx_ev"]) if "pnx_ev" in S else np.nan
    A["n_xt"] = A.id.map(lambda x: len(tied[x])); A["R"] = A.id.map(lambda x: len(voters.get(x, ())))
    A["tied_votes"] = A.id.map(lambda x: len(tied[x] & voters.get(x, set())))
    A = A.merge(I[["id", "out_votes"]], on="id", how="left"); A = A[A.S.notna()]
    sp0, sp1, t3_pool0, t3_pool1, t3_fin0, t3_fin1, lams = [], [], [], [], [], [], {}
    for d, g in A.groupby("day"):
        prev = A[A.day < d]
        if len(g) < 3 or prev.n_xt.sum() == 0:
            continue
        lam = prev.tied_votes.sum() / prev.n_xt.sum(); lams[d] = round(float(lam), 3)
        g = g.assign(Sx=g.S + lam * g.n_xt)
        if g.R.nunique() > 1:
            sp0.append(spearmanr(g.S, g.R).correlation); sp1.append(spearmanr(g.Sx, g.R).correlation)
        top_pool = set(g.nlargest(3, "R").id); top_fin = set(g.nlargest(3, "out_votes").id)
        t3_pool0.append(len(set(g.nlargest(3, "S").id) & top_pool) / 3); t3_pool1.append(len(set(g.nlargest(3, "Sx").id) & top_pool) / 3)
        t3_fin0.append(len(set(g.nlargest(3, "S").id) & top_fin) / 3); t3_fin1.append(len(set(g.nlargest(3, "Sx").id) & top_fin) / 3)
    gain = np.array(sp1) - np.array(sp0)
    res["pool_level"] = {"days": len(t3_pool0), "launches": int(len(A)), "lambda_forward_by_day": lams,
                         "spearman_S": boot(sp0, rng), "spearman_S_plus_xtied": boot(sp1, rng), "spearman_gain": boot(gain, rng),
                         "pool_top3_S": boot(t3_pool0, rng), "pool_top3_Sx": boot(t3_pool1, rng), "pool_top3_gain": boot(np.array(t3_pool1) - np.array(t3_pool0), rng),
                         "final_top3_among_covered_S": boot(t3_fin0, rng), "final_top3_among_covered_Sx": boot(t3_fin1, rng),
                         "final_top3_gain": boot(np.array(t3_fin1) - np.array(t3_fin0), rng)}
    g = res["pool_level"]["spearman_gain"]
    res["verdict"] = ("not testable yet (no scored days)" if not g else
                      "X tie improves the pool simulation" if g[1][0] > 0 else "X tie does not improve the pool simulation (Spearman gain interval not above 0)")
    json.dump(res, open(os.path.join(HERE, "reports", "x_tie_pool.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), ".cache", "x_tie_pool"))
