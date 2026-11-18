"""Experiment A (orchestrator Nov 11): choice WITHIN the seen set. A person's vote is scored only among the launches
they most likely saw, approximated by the day's final top 10 / top 20 (vote times are unknown for complete people).
For each voting person-day with >= 1 pick inside the set: Hit@1 / Hit@3 by the model's score among the set's launches,
within-set AUC, and the random reference (k_in_set / |set|; 1 - C(n-k,3)/C(n,3)). Label filter as it8 (lists read >= d+2,
capped lists from the oldest vote).
Models (scores per person x launch, all known at 00:05):
  it8_full         rows_tl_cp_choice (A x K x S, with PH context)
  it8_product      rows_tl_cp_choice_noctx (PH context off)
  centroid         `meaning` = launch embedding vs the person's upvote-history centroid (rows_tl_cp_unc/X_<d>)
  topic            `topic` = the launch's topics vs the person's topic history
  + any extra tag passed as argv (e.g. it9b rows tags)
Reference (uses outcomes, not a model): final-rank order inside the set (non-personal).
usage: SIMBT=<dir> python exposure_choice.py [extra_tag ...] -> results/exposure_choice.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.special import comb
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2:
        return [round(float(x.mean()), 3) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 3), [round(float(v), 3) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def main(extra):
    os.environ.setdefault("SIMBT", WORK)
    import two_level as T
    from pipeline import warehouse as W
    ok, _ = T._label_maps()
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(L.id, L.daily_rank))
    tags = {"it8_full": "cp_choice", "it8_product": "cp_choice_noctx", **{t: t for t in extra}}
    days = sorted(os.path.basename(f)[:10] for f in glob.glob(f"{WORK}/rows_tl_cp_choice_noctx/20*.parquet"))
    per = []
    for d in days:
        X = pd.read_parquet(f"{WORK}/rows_tl_cp_unc/X_{d}.parquet", columns=["person", "id", "meaning", "topic", "y"])
        X["id"] = X.id.astype(str); X = X[ok(X.person, d)]
        for nm, tg in tags.items():
            p = f"{WORK}/rows_tl_{tg}/{d}.parquet"
            if os.path.exists(p):
                R = pd.read_parquet(p, columns=["person", "id", "w", "p"]); R["id"] = R.id.astype(str)
                X = X.merge(R.assign(**{nm: R.w * R.p})[["person", "id", nm]], on=["person", "id"], how="left")
        X["rank"] = X.id.map(rk)
        models = ["centroid", "topic"] + list(tags)
        X = X.rename(columns={"meaning": "centroid"})
        for top in (10, 20):
            S = X[X["rank"] <= top]
            if S.id.nunique() < top:
                continue
            S = S[S.groupby("person").y.transform("sum") > 0]
            row = {"day": d, "set": top, "persons": int(S.person.nunique())}
            n = S.groupby("person").size(); k = S.groupby("person").y.sum()
            row["random_hit1"] = float((k / n).mean()); row["random_hit3"] = float((1 - comb(n - k, 3) / comb(n, 3)).mean())
            S = S.assign(oracle=-S["rank"])
            for m in models + ["oracle"]:
                if m not in S or S[m].isna().all():
                    continue
                r = S.groupby("person")[m].rank(ascending=False, method="first")
                row[f"{m}_hit1"] = float(S[r <= 1].groupby("person").y.max().mean())
                row[f"{m}_hit3"] = float(S[r <= 3].groupby("person").y.max().mean())
                au = [roc_auc_score(g.y, g[m].fillna(g[m].min())) for _, g in S.groupby("person") if 0 < g.y.sum() < len(g)]
                row[f"{m}_auc"] = float(np.mean(au)) if au else np.nan
            per.append(row)
    P = pd.DataFrame(per); rng = np.random.default_rng(0); res = {"days": days, "note": "seen set = final top 10 / top 20 (vote times unknown); oracle = final rank, uses outcomes"}
    for top in (10, 20):
        Q = P[P["set"] == top]; r = {"days": int(len(Q)), "voting_person_days": int(Q.persons.sum()),
                                      "random": {"hit1": boot(Q.random_hit1, rng), "hit3": boot(Q.random_hit3, rng)}}
        for m in ["centroid", "topic"] + list(tags) + ["oracle"]:
            if f"{m}_hit1" in Q:
                r[m] = {x: boot(Q[f"{m}_{x}"], rng) for x in ("hit1", "hit3", "auc")}
                r[m]["hit1_minus_random"] = boot(Q[f"{m}_hit1"] - Q.random_hit1, rng)
        res[f"top{top}"] = r
    json.dump(res, open(os.path.join(HERE, "results", "exposure_choice.json"), "w"), indent=1)
    for top in (10, 20):
        r = res[f"top{top}"]; print(f"top{top}", r["days"], r["voting_person_days"], "random", r["random"]["hit1"][0], r["random"]["hit3"][0])
        for m in [x for x in r if x not in ("days", "voting_person_days", "random")]:
            print("  ", m, r[m]["hit1"][:2], r[m]["hit3"][0], r[m]["auc"][0])


if __name__ == "__main__":
    main(sys.argv[1:])
