"""PH-MISS1 (orchestrator 09:51Z Nov 23): anatomy of the 00:05 top-3 misses, Nov 10-22.
Miss = a launch with final daily rank <= 3 (truth_daily) that the frozen 00:05 forecast did not put in its top 3. Forecast column:
pred_arm3 where filled, else pred_arm2 where filled, else pred (the published launch model before arm 2 existed).
Each miss gets its FIRST matching cause, in this order:
  (a) featured after the forecast: not in the frozen 00:05 forecast parquet.
  (b) team network unseen: in the newest store_v3 copy published before d 00:05 PT, no team member (hunter + named makers in
      today_0005.json) is complete AND no complete person follows a team member. Needs a leak-free copy: Nov 14-22 only.
  (c) votes from people we don't hold (E5's who_backs split): held-voter share = complete persons in the newest store with an upvote
      on the launch / final votes; cause if the launch is in the bottom third of its day. Attribution only (post-day store). A day
      counts only if the store has its voters (day median share >= 0.2; other days sit at 0.4-1.1, a day the store has not re-pulled sits near 0).
  (d) inputs right, model under-weighted: a leave-day-out 15-nearest-neighbour rule on the same frozen inputs in the parquet
      (log1p of hunter followers, maker X followers, company X followers, promo reactions, promo posts; z-scored) ranks each launch by
      its neighbours' mean final within-day percentile; cause if that rule puts the launch in its day's top 3.
  (e) unexplained.
Leak checks: forecasts, line-ups and team/follower inputs are the frozen pre-00:05 files (written before 03:45 PT); post-day truth and
the newest store are used only to label causes, never fed to a model.
Shares: share of misses per cause with a 95% day bootstrap (10,000 draws, seed 0). Oracle: fixing a miss swaps it for one of the
forecast's wrong top-3 picks, so each fixed miss adds exactly one top-3 hit: points = 100 * misses / (3 * days).
Counts and launch ids only; the salt is read only to hash.
usage: python miss_anatomy_fwd.py <work dir with f_<d>.parquet> <dir of store_store_v3_<gen> copies> <salt dir> -> results/miss_anatomy_v1.json"""
import hashlib, json, os, subprocess, sys
import numpy as np, pandas as pd
import pyarrow.dataset as ds
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
DAYS = [f"2026-11-{d}" for d in range(10, 23)]
STORE_PRE = {"2026-11-14": "1794599890116312", "2026-11-15": "1794599890116312", "2026-11-16": "1794599890116312",
             "2026-11-17": "1794599890116312", "2026-11-18": "1794907785119506", "2026-11-19": "1794992427530859",
             "2026-11-20": "1795078491861133", "2026-11-21": "1795165796085945", "2026-11-22": "1795251832586019"}
STORE_POST = "1795346332862574"                       # events 11:18Z Nov 22: newest copy, attribution only
FEAT = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]
K = 15; NB = 10000; CAUSES = ["a_featured_late", "b_team_unseen", "c_unheld_voters", "d_underweighted", "e_unexplained"]


def main(work, stores, salt_dir):
    salt = open(os.path.join(salt_dir, "salt")).read().strip()
    pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    T = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/web/truth_daily.json"], capture_output=True, text=True).stdout)["days"]
    from pipeline import warehouse
    W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str)
    votes = W.sort_values("updated_at").drop_duplicates("id", keep="last").set_index("id").votes.astype(float)
    F, R = {}, {}
    for d in DAYS:
        if T.get(d, {}).get("status") != "counts": continue
        X = pd.read_parquet(os.path.join(work, f"f_{d}.parquet")); X["id"] = X.id.astype(str)
        col = next(c for c in ("pred_arm3", "pred_arm2", "pred") if c in X and X[c].notna().mean() >= 0.9)
        X["col"] = col; X["prank"] = X[col].rank(ascending=False, method="first"); F[d] = X
        R[d] = pd.Series({str(k): float(v) for k, v in T[d]["ranks"].items()})
    # (d) leave-day-out kNN on the frozen parquet inputs
    A = pd.concat([F[d].assign(day=d) for d in F], ignore_index=True)
    A["final"] = [R[d].get(i) for d, i in zip(A.day, A.id)]
    A["pct"] = A.final / A.day.map({d: len(R[d]) for d in R})
    Z = np.log1p(A[FEAT].apply(pd.to_numeric, errors="coerce").clip(lower=0)); Z = ((Z - Z.mean()) / Z.std(ddof=0)).fillna(0).values
    A["knn"] = np.nan
    for d in F:
        me, other = (A.day == d).values, ((A.day != d) & A.pct.notna()).values
        dist = ((Z[me][:, None, :] - Z[other][None, :, :]) ** 2).sum(-1)
        nn = np.argsort(dist, 1)[:, :K]; A.loc[me, "knn"] = A.pct.values[other][nn].mean(1)
    A["knn_rank"] = A.groupby("day").knn.rank(method="first")
    # (c) held-voter share from the newest store (attribution only)
    post = os.path.join(stores, f"store_store_v3_{STORE_POST}")
    comp_post = set(pd.read_parquet(os.path.join(post, "persons.parquet"), columns=["person_id", "complete"]).query("complete").person_id)
    ids = {i for d in R for i in R[d].index}
    U = ds.dataset(os.path.join(post, "events.parquet")).to_table(columns=["person_id", "target_id"], filter=(ds.field("kind") == "upvote")).to_pandas()
    U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(ids) & U.person_id.isin(comp_post)].drop_duplicates()
    nheld = U.groupby("target_id").person_id.nunique()
    share = {d: pd.Series({i: nheld.get(i, 0) / votes[i] if votes.get(i, 0) > 0 else np.nan for i in R[d].index}) for d in R}
    c_ok = {d: bool(share[d].median() >= 0.2) for d in R}; c_med = {d: round(float(share[d].median()), 3) for d in R}
    # (b) team network at 00:05 from the leak-free pre-00:05 copy
    team_seen, cache = {}, {}
    for d in R:
        g = STORE_PRE.get(d)
        if not g: continue
        if g not in cache:
            p = os.path.join(stores, f"store_store_v3_{g}")
            comp = set(pd.read_parquet(os.path.join(p, "persons.parquet"), columns=["person_id", "complete"]).query("complete").person_id)
            fo = ds.dataset(os.path.join(p, "events.parquet")).to_table(columns=["person_id", "target_id"], filter=(ds.field("kind") == "follows")).to_pandas()
            fo = fo[fo.person_id.isin(comp)]; cache[g] = (comp, fo.groupby("target_id").person_id.nunique())
        comp, nf = cache[g]
        L = json.loads(subprocess.run(["gsutil", "cat", f"{B}/raw/daily/{d}/today_0005.json"], capture_output=True, text=True).stdout)
        L = L.get("posts", L) if isinstance(L, dict) else L
        real = lambda u: bool(u.get("username")) and not str(u["username"]).startswith("[") and str(u.get("id")) != "0"
        for x in L:
            ms = list(dict.fromkeys(pid(u["username"]) for u in [x.get("user") or {}] + (x.get("makers") or []) if real(u)))
            team_seen[(d, str(x["id"]))] = {"n_team": len(ms), "n_team_complete": sum(m in comp for m in ms),
                                            "held_followers": int(sum(nf.get(m, 0) for m in ms))}
    misses = []
    for d in R:
        top3 = R[d][R[d] <= 3].index; X = F[d].set_index("id")
        for i in top3:
            if i in X.index and X.prank[i] <= 3: continue
            m = {"day": d, "launch_id": i, "final_rank": int(R[d][i]), "model_col": F[d].col.iloc[0],
                 "model_rank": (int(X.prank[i]) if i in X.index else None), "lineup_n": len(X)}
            ts = team_seen.get((d, i)); m["team"] = ts
            m["held_voter_share"] = (round(float(share[d].get(i)), 3) if pd.notna(share[d].get(i)) else None)
            m["held_share_tercile_low"] = (bool(share[d].rank(pct=True).get(i, 1) <= 1 / 3) if c_ok[d] else None)
            kr = A[(A.day == d) & (A.id == i)].knn_rank; m["knn_rank"] = (int(kr.iloc[0]) if len(kr) and pd.notna(kr.iloc[0]) else None)
            if i not in X.index: m["cause"] = CAUSES[0]
            elif ts is not None and ts["n_team_complete"] == 0 and ts["held_followers"] == 0: m["cause"] = CAUSES[1]
            elif m["held_share_tercile_low"]: m["cause"] = CAUSES[2]
            elif m["knn_rank"] is not None and m["knn_rank"] <= 3: m["cause"] = CAUSES[3]
            else: m["cause"] = CAUSES[4]
            misses.append(m)
    M = pd.DataFrame(misses); dl = sorted(R); rng = np.random.default_rng(0)
    cnt = {d: M[M.day == d].cause.value_counts() for d in dl}
    def stat(pick):
        tot = sum(int(cnt[d].sum()) for d in pick)
        return {c: (sum(int(cnt[d].get(c, 0)) for d in pick) / tot if tot else np.nan, 100 * sum(int(cnt[d].get(c, 0)) for d in pick) / (3 * len(pick))) for c in CAUSES}
    base = stat(dl); bs = [stat(list(rng.choice(dl, len(dl)))) for _ in range(NB)]
    ci = lambda c, j: [round(float(np.nanpercentile([b[c][j] for b in bs], q)) * (100 if j == 0 else 1), 1) for q in (2.5, 97.5)]
    out = {c: {"misses": int(sum(int(cnt[d].get(c, 0)) for d in dl)), "share_pct": round(base[c][0] * 100, 1), "share_ci95": ci(c, 0),
               "oracle_top3_pts": round(base[c][1], 1), "oracle_ci95": ci(c, 1)} for c in CAUSES}
    hits = {d: int(3 - cnt[d].sum()) for d in dl}
    res = {"experiment": "PH-MISS1", "asked": "orchestrator 09:51Z Nov 23", "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
           "days": dl, "n_days": len(dl), "n_misses": int(len(M)), "top3_hit_pct": round(100 * sum(hits.values()) / (3 * len(dl)), 1),
           "model_col_by_day": {d: F[d].col.iloc[0] for d in dl}, "causes": out,
           "coverage": {"b_days_with_leak_free_store": sorted(d for d in dl if d in STORE_PRE),
                        "c_days_with_voters_in_store": sorted(d for d in dl if c_ok[d]), "c_day_median_held_share": c_med,
                        "d_inputs": FEAT, "d_k": K},
           "leak_checks": "forecasts, line-ups and team/follower inputs are frozen pre-00:05 files (written before 03:45 PT); the store copy for (b) "
                          "was published before d 00:05 PT; truth and the newest store label causes only and are never fed to a model",
           "misses": misses}
    json.dump(res, open(os.path.join(HERE, "results", "miss_anatomy_v1.json"), "w"), indent=1, default=str)
    print(json.dumps({k: res[k] for k in ("n_days", "n_misses", "top3_hit_pct", "causes", "coverage")}, default=str))
    print(M[["day", "final_rank", "model_rank", "lineup_n", "held_voter_share", "knn_rank", "cause"]].to_string())


if __name__ == "__main__":
    main(*sys.argv[1:4])
