"""T1 (orchestrator Nov 11): split each launch's complete-people voters into ARRIVALS and BROWSERS.
Rows: it8 base rows (rows_tl_cp_unc/X_<d>: every complete person active in the 30 days before d x the day's line-up,
label-filtered), Oct 20 - Nov 8. Per person-day n_up = upvotes on the line-up that day; regular = active on >= 5 of the
prior 30 days (w_act * 30); tied to L = backed > 0 or tie_maker > 0 or tie_hunter > 0 (team ties before d).
  browser vote   n_up >= 3, regular, not tied to L
  arrival vote   n_up == 1, or tied to L, or dormant (days_since > 30) or new (tenure < 30 days)
  other          the rest (reported, not used in the two shares)
Per launch: arrival share = arrival votes / sample votes; browser pick rate = browser votes / browsers that day not tied to L.
(a) within-day Spearman of final votes with: sample votes, arrival votes, browser votes, browser pick rate.
(b) browser pick rate as a non-personal ranker of each browser's picks (leave-that-person-out rate), Hit@1 / Hit@3 on
    browser person-days, against the final-votes order (oracle) and random.
usage: SIMBT=<dir> python t1_arrivals.py -> results/t1_arrivals.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.special import comb
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2:
        return [round(float(x.mean()), 3) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 3), [round(float(v), 3) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def main():
    import two_level as T
    from pipeline import warehouse as W
    ok, _ = T._label_maps()
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(L.id, L.daily_rank)); vt = dict(zip(L.id, L.votes))
    cols = ["person", "id", "y", "backed", "tie_maker", "tie_hunter", "w_act", "days_since", "tenure"]
    per_launch, per_day, hits = [], [], []
    for f in sorted(glob.glob(f"{WORK}/rows_tl_cp_unc/X_*.parquet")):
        d = os.path.basename(f)[2:12]
        if not ("2026-10-20" <= d <= "2026-11-08"):
            continue
        X = pd.read_parquet(f, columns=cols); X["id"] = X.id.astype(str); X = X[ok(X.person, d)].copy()
        X["votes"] = X.id.map(vt); X["rank"] = X.id.map(rk)
        if X.votes.notna().sum() == 0:
            continue
        n_up = X.groupby("person").y.transform("sum"); regular = X.w_act * 30 >= 5
        # makers only by default: prolific hunters (one poster hunts many launches) make nearly everyone "tied" through
        # the hunter, which leaves top launches with no eligible browsers (first run, kept as t1_arrivals_tie_incl_hunter.json)
        tied = (X.tie_maker > 0) if os.environ.get("T1_TIE", "maker") == "maker" else ((X.backed > 0) | (X.tie_maker > 0) | (X.tie_hunter > 0))
        dormant = (X.days_since > 30) | (X.tenure < 30)
        X["browser_elig"] = (n_up >= 3) & regular & ~tied      # a browser who could pick L
        X["bb"] = (n_up >= 3) & regular                        # T1b (2): behaviour-only browser, no tie exclusion
        X["one_vote"] = (X.y == 1) & (n_up == 1); X["dorm_new"] = (X.y == 1) & dormant & ~(n_up == 1)
        X["tied_v"] = (X.y == 1) & tied & ~(n_up == 1) & ~dormant
        X["bv"] = X.browser_elig & (X.y == 1)
        X["av"] = (X.y == 1) & ((n_up == 1) | tied | dormant)
        g = X.groupby("id")
        nbb = int(X.drop_duplicates("person").bb.sum())
        Lr = pd.DataFrame({"sample_votes": g.y.sum(), "arrival_votes": g.av.sum(), "browser_votes": g.bv.sum(), "browsers": g.browser_elig.sum(),
                           "bb_votes": (X.bb & (X.y == 1)).groupby(X.id).sum(), "one_vote": g.one_vote.sum(), "dorm_new": g.dorm_new.sum(), "tied_v": g.tied_v.sum(),
                           "votes": g.votes.first(), "rank": g["rank"].first()}).reset_index()
        Lr["bb_rate"] = Lr.bb_votes / max(1, nbb)
        Lr["browser_rate"] = Lr.browser_votes / Lr.browsers.clip(lower=1); Lr["arrival_share"] = Lr.arrival_votes / Lr.sample_votes.clip(lower=1)
        Lr["day"] = d; per_launch.append(Lr)
        Lv = Lr.dropna(subset=["votes"])
        row = {"day": d, "launches": len(Lv)}
        for c in ("sample_votes", "arrival_votes", "browser_votes", "browser_rate"):
            row[f"sp_{c}"] = spearmanr(Lv[c], Lv.votes).correlation
        E = Lv[Lv.browsers >= 20]   # T1b (1): launches with >= 20 eligible browsers only
        row["n_elig20"] = int(len(E))
        row["sp20_rate_votes"] = spearmanr(E.browser_rate, E.votes).correlation if len(E) >= 5 else np.nan
        row["sp20_rate_arrivals"] = spearmanr(E.browser_rate, E.arrival_votes).correlation if len(E) >= 5 else np.nan
        row["sp_bb_rate_votes"] = spearmanr(Lv.bb_rate, Lv.votes).correlation
        row["bb_share_top3"] = float(Lv[Lv["rank"] <= 3].bb_votes.sum() / max(1, Lv.bb_votes.sum()))
        row["sample_share_top3"] = float(Lv[Lv["rank"] <= 3].sample_votes.sum() / max(1, Lv.sample_votes.sum()))
        row["top3_frac_of_lineup"] = float((Lv["rank"] <= 3).sum() / max(1, len(Lv)))
        row["arrival_share_mean"] = float(Lv.arrival_votes.sum() / max(1, Lv.sample_votes.sum()))
        row["browser_share_mean"] = float(Lv.browser_votes.sum() / max(1, Lv.sample_votes.sum()))
        per_day.append(row)
        # (b): browsers' picks ranked by the leave-this-person-out browser pick rate
        B = X[X.browser_elig].copy()
        B = B[B.groupby("person").y.transform("sum") > 0]
        if len(B):
            tot_v = B.groupby("id").y.transform("sum"); tot_n = B.groupby("id").y.transform("size")
            B["loo"] = (tot_v - B.y) / (tot_n - 1).clip(lower=1)
            B["oracle"] = B.votes.fillna(-1)
            B["jit"] = np.random.default_rng(0).random(len(B)) * 1e-9
            n = B.groupby("person").size(); k = B.groupby("person").y.sum()
            h = {"day": d, "browser_person_days": int(B.person.nunique()),
                 "random_hit1": float((k / n).mean()), "random_hit3": float((1 - comb(n - k, 3) / comb(n, 3)).mean())}
            for m in ("loo", "oracle"):
                r = (B[m] + B.jit).groupby(B.person).rank(ascending=False, method="first")
                h[f"{m}_hit1"] = float(B[r <= 1].groupby("person").y.max().mean()); h[f"{m}_hit3"] = float(B[r <= 3].groupby("person").y.max().mean())
            hits.append(h)
    P = pd.DataFrame(per_day); H = pd.DataFrame(hits); Lall = pd.concat(per_launch); rng = np.random.default_rng(0)
    res = {"days": int(len(P)), "launches": int(len(Lall)),
           "definitions": {"tie": os.environ.get("T1_TIE", "maker"), "browser": "n_up>=3, active >=5 of prior 30 days, not tied to L", "arrival": "n_up==1 or tied to L or dormant (>30 d) / new (<30 d tenure)"},
           "vote_mix": {"arrival_share_of_sample_votes": boot(P.arrival_share_mean, rng), "browser_share_of_sample_votes": boot(P.browser_share_mean, rng)},
           "a_within_day_spearman_vs_final_votes": {c: boot(P[f"sp_{c}"], rng) for c in ("sample_votes", "arrival_votes", "browser_votes", "browser_rate")},
           "b_browser_choice": {"browser_person_days": int(H.browser_person_days.sum()),
                                **{m: {"hit1": boot(H[f"{m}_hit1"], rng), "hit3": boot(H[f"{m}_hit3"], rng)} for m in ("random", "loo", "oracle")}},
           "note": "loo = browser pick rate of the other browsers that day (non-personal, uses outcomes of others); oracle = final votes"}
    res["t1b"] = {"1_launches_with_ge20_eligible_browsers": {"per_day_n_median": float(P.n_elig20.median()),
                                                             "spearman_rate_vs_final_votes": boot(P.sp20_rate_votes, rng),
                                                             "spearman_rate_vs_arrival_votes": boot(P.sp20_rate_arrivals, rng)},
                  "2_behaviour_only_browsers": {"spearman_pick_rate_vs_final_votes": boot(P.sp_bb_rate_votes, rng),
                                                "share_of_their_votes_on_top3": boot(P.bb_share_top3, rng),
                                                "share_of_all_sample_votes_on_top3": boot(P.sample_share_top3, rng),
                                                "top3_share_of_lineup": boot(P.top3_frac_of_lineup, rng)}}
    Lv = Lall.dropna(subset=["rank"]).copy()
    for c in ("one_vote", "dorm_new", "tied_v"):
        Lv[c + "_sh"] = Lv[c] / Lv.sample_votes.clip(lower=1)
    Lv["other_sh"] = 1 - Lv[["one_vote_sh", "dorm_new_sh", "tied_v_sh"]].sum(1)
    grp = {"top3": Lv["rank"] <= 3, "rank4_5": (Lv["rank"] > 3) & (Lv["rank"] <= 5), "rest": Lv["rank"] > 5}
    res["t1b"]["3_voter_profile_share_of_sample_votes"] = {g: {c: round(float(Lv[m][c + "_sh"].median()), 3) for c in ("one_vote", "dorm_new", "tied_v", "other")}
                                                           | {"launches": int(m.sum())} for g, m in grp.items()}
    res["t1b"]["3_note"] = "exclusive classes in order: one-vote-that-day, then dormant/new, then maker-tied; other = the rest (regular, untied, multi-vote)"
    top = Lall[Lall["rank"] <= 5]
    res["top5_launches_arrival_share_median"] = round(float(top.arrival_share.median()), 3)
    res["other_launches_arrival_share_median"] = round(float(Lall[Lall["rank"] > 5].arrival_share.median()), 3)
    Lall.to_parquet(os.path.join(WORK, "t1_launch_table.parquet"))
    json.dump(res, open(os.path.join(HERE, "results", "t1_arrivals.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
