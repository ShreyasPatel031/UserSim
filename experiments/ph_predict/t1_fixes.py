"""T1 fixes (E5 review, Nov 11). Same rows and definitions as t1_arrivals.py (maker ties), plus:
1. Truly dormant arrivals: complete people NOT active in the 30 days before d (absent from the it8 rows) who upvoted a
   day-d launch (events_cp, label filter applied). Counted as dormant arrivals and added to each launch's sample votes.
   Also: how many dorm_new hits in the it8 rows come from days_since > 30 (expected ~0).
2. Selection by the >= 20-eligible-browsers filter: per day, how many of the real top 3 / top 5 survive; the rank
   distribution of included launches; browser-rate Spearman on top-10 launches only (no eligibility filter).
3. Voter-profile shares non-exclusive (each flag alone, plus overlaps) and in the reverse order (tied -> dormant/new ->
   one-vote), for top 3 / ranks 4-5 / rest.
4. Browser-choice (b) is labelled non-personal and uses other people's same-day votes; it is not a forecast.
Days Oct 29 - Nov 4 (the complete set was selected from their voters) reported apart from the clean days.
usage: SIMBT=<dir> python t1_fixes.py -> results/t1_fixes.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]
SELECTED = {d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-29", "2026-11-04")}


def main():
    import two_level as T
    from pipeline import warehouse as W
    ok, Eu = T._label_maps()
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(L.id, L.daily_rank)); vt = dict(zip(L.id, L.votes))
    Eu = Eu.assign(item=Eu.item.astype(str))
    cols = ["person", "id", "y", "tie_maker", "w_act", "days_since", "tenure"]
    launch_rows, day_rows, dorm_days_since = [], [], []
    for f in sorted(glob.glob(f"{WORK}/rows_tl_cp_unc/X_*.parquet")):
        d = os.path.basename(f)[2:12]
        if not ("2026-10-20" <= d <= "2026-11-08"):
            continue
        X = pd.read_parquet(f, columns=cols); X["id"] = X.id.astype(str); X = X[ok(X.person, d)].copy()
        if not X.id.map(vt).notna().any():
            continue
        n_up = X.groupby("person").y.transform("sum"); regular = X.w_act * 30 >= 5
        tied = X.tie_maker > 0; dorm = (X.days_since > 30) | (X.tenure < 30); one = n_up == 1
        dorm_days_since.append(int(((X.y == 1) & (X.days_since > 30)).sum()))
        v = X.y == 1
        X["f_one"], X["f_dorm"], X["f_tied"] = v & one, v & dorm, v & tied
        X["fwd_one"] = v & one; X["fwd_dorm"] = v & dorm & ~one; X["fwd_tied"] = v & tied & ~one & ~dorm
        X["rev_tied"] = v & tied; X["rev_dorm"] = v & dorm & ~tied; X["rev_one"] = v & one & ~tied & ~dorm
        X["elig"] = (n_up >= 3) & regular & ~tied; X["bv"] = X.elig & v
        # 1: complete people not active in the 30 days before d who voted on d (absent from the rows)
        lineup = set(X.id); inrows = set(X.person)
        D = Eu[(Eu.date.astype(str).str[:10] == d) & Eu.item.isin(lineup) & ~Eu.person.isin(inrows)]
        D = D[ok(D.person, d)] if len(D) else D
        extra = D.groupby("item").size()
        g = X.groupby("id")
        Lr = pd.DataFrame({k: g[k].sum() for k in ("y", "f_one", "f_dorm", "f_tied", "fwd_one", "fwd_dorm", "fwd_tied", "rev_tied", "rev_dorm", "rev_one", "bv", "elig")})
        Lr["dormant_absent"] = extra.reindex(Lr.index).fillna(0)
        Lr["sample_votes_plus"] = Lr.y + Lr.dormant_absent
        Lr["rank"] = Lr.index.map(rk); Lr["votes"] = Lr.index.map(vt); Lr["day"] = d; Lr["browser_rate"] = Lr.bv / Lr.elig.clip(lower=1)
        launch_rows.append(Lr.reset_index())
        Lv = Lr.dropna(subset=["rank"])
        E20 = Lv[Lv.elig >= 20]; T10 = Lv[Lv["rank"] <= 10]
        day_rows.append({"day": d, "selected": d in SELECTED, "launches": len(Lv),
                         "top3_in_elig20": int((E20["rank"] <= 3).sum()), "top5_in_elig20": int((E20["rank"] <= 5).sum()),
                         "elig20_n": int(len(E20)), "elig20_median_rank": float(E20["rank"].median()) if len(E20) else np.nan,
                         "sp_top10_browser_rate_votes": spearmanr(T10.browser_rate, T10.votes).correlation if len(T10) >= 5 else np.nan,
                         "dormant_absent_votes": int(Lv.dormant_absent.sum()), "sample_votes": int(Lv.y.sum())})
    P = pd.DataFrame(day_rows); A = pd.concat(launch_rows)
    A = A.dropna(subset=["rank"]).copy()
    grp = {"top3": A["rank"] <= 3, "rank4_5": (A["rank"] > 3) & (A["rank"] <= 5), "rest": A["rank"] > 5}

    def shares(M, prefix, base):
        return {k: round(float((M[f"{prefix}_{k}"] / M[base].clip(lower=1)).median()), 3) for k in ("one", "dorm", "tied")}
    res = {"days_clean": P[~P.selected].day.tolist(), "days_selected": P[P.selected].day.tolist(),
           "fix1_dorm_hits_with_days_since_gt30_in_rows": int(sum(dorm_days_since)),
           "fix1_absent_dormant_votes_share": {s: round(float(P[P.selected == s].dormant_absent_votes.sum() / max(1, (P[P.selected == s].sample_votes + P[P.selected == s].dormant_absent_votes).sum())), 3)
                                               for s in (False, True)},
           "fix2": {"per_day": P[["day", "selected", "elig20_n", "top3_in_elig20", "top5_in_elig20", "elig20_median_rank", "sp_top10_browser_rate_votes"]].round(3).to_dict("records"),
                    "top3_survival_rate": round(float(P.top3_in_elig20.sum() / (3 * len(P))), 3),
                    "top5_survival_rate": round(float(P.top5_in_elig20.sum() / (5 * len(P))), 3),
                    "sp_top10_mean_clean": round(float(P[~P.selected].sp_top10_browser_rate_votes.mean()), 3),
                    "sp_top10_mean_selected": round(float(P[P.selected].sp_top10_browser_rate_votes.mean()), 3)},
           "fix3": {}}
    A["dorm_abs_share"] = A.dormant_absent / A.sample_votes_plus.clip(lower=1)
    for gname, m in grp.items():
        M = A[m]
        res["fix3"][gname] = {"launches": int(m.sum()),
                              "non_exclusive": {k: round(float((M[f"f_{k}"] / M.y.clip(lower=1)).median()), 3) for k in ("one", "dorm", "tied")},
                              "overlap_one_and_tied": round(float(((M.f_one + M.f_tied - M.y).clip(lower=0) / M.y.clip(lower=1)).median()), 3),
                              "forward_order": shares(M, "fwd", "y"), "reverse_order": shares(M, "rev", "y"),
                              "regular_untied_forward": round(float((1 - (M.fwd_one + M.fwd_dorm + M.fwd_tied) / M.y.clip(lower=1)).median()), 3),
                              "regular_untied_reverse": round(float((1 - (M.rev_one + M.rev_dorm + M.rev_tied) / M.y.clip(lower=1)).median()), 3),
                              "absent_dormant_share_of_votes_plus": round(float(M.dorm_abs_share.median()), 3)}
    res["fix4"] = "browser-choice (b) ranks a browser's options by OTHER people's same-day votes: non-personal, uses outcomes, not a forecast"
    json.dump(res, open(os.path.join(HERE, "results", "t1_fixes.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "fix2"}, indent=1))
    print(json.dumps({k: v for k, v in res["fix2"].items() if k != "per_day"}))


if __name__ == "__main__":
    main()
