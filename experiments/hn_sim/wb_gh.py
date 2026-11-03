"""GitHub traction as a 15-min input (orchestrator, 2026-11-02): for posts linking a github.com repo, from Data Feeder's
daily new-star counts (raw/github_stargazers/; starred_at is admin-only on GitHub since July 2026): stars on the day
before, the 7 and 30 days before the posting day (never the posting day itself), acceleration, repo age. Coverage among winners by type, then Caught at 15 min per post
with these inputs added to the current 15-min model (votes + who + exposure), Oct 2-14 forward daily retrain, paired.

    python wb_gh.py      # downloads raw/github_stargazers/ (star_history_*.jsonl, repo_status.jsonl)
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import caught1h as C1
import fine_io
import odds_live as OL
import pj_eval
import top100 as H
import wb15 as W15
import wb_caught as W

GHC = ["gh_d1", "gh_d7", "gh_d30", "gh_accel", "gh_age_days", "gh_known", "gh_link"]
RAW = "usersim_sim/raw/github_stargazers/"


def load_history():
    """Data Feeder's daily new-star counts (GitHub stopped showing starred_at to non-admins in July 2026):
    star_history_*.jsonl rows {repo, date, stars}; repo_status.jsonl for created_at / gone."""
    import json
    import store as S
    d = os.path.join(H.CACHE, "github_stargazers")
    os.makedirs(d, exist_ok=True)
    b = S._bucket()
    dedup = b.get_blob(RAW + "dedup/star_history_dedup.jsonl")      # Data Feeder's deduplicated history, if present
    for x in b.list_blobs(prefix=RAW):
        n = x.name.split("/")[-1]
        if "/dedup/" in x.name or not n.endswith(".jsonl"):
            continue
        if n == "repo_status.jsonl" or (dedup is None and n.startswith("star_history_")):
            x.download_to_filename(os.path.join(d, n))
    if dedup is not None:
        dedup.download_to_filename(os.path.join(d, "star_history_dedup.jsonl"))
    files = ["star_history_dedup.jsonl"] if dedup is not None else sorted(f for f in os.listdir(d) if f.startswith("star_history_"))
    hist = [pd.read_json(os.path.join(d, f), lines=True) for f in files]
    Hh = pd.concat(hist, ignore_index=True) if hist else pd.DataFrame(columns=["repo", "date", "stars"])
    Hh["repo"] = Hh.repo.str.lower()
    Hh["date"] = pd.to_datetime(Hh.date).dt.strftime("%Y-%m-%d")
    Hh = Hh.drop_duplicates(["repo", "date"], keep="last")         # a second fetcher ran ~1 min: ~19 repos twice
    st = os.path.join(d, "repo_status.jsonl")
    Rs = pd.read_json(st, lines=True) if os.path.exists(st) else pd.DataFrame(columns=["repo"])
    if len(Rs):
        Rs["repo"] = Rs.repo.str.lower()
        Rs = Rs.drop_duplicates("repo", keep="last")
    return Hh, Rs


def gh_feats(Q):
    """Per post (repo linked), from days strictly before the posting day (the posting day includes post-HN stars):
    new stars the day before, in the 7 and 30 days before, acceleration (7-day rate minus the rate of days 8-30),
    repo age at posting."""
    Hh, Rs = load_history()
    repo = Q.url.fillna("").str.extract(r"github\.com/([^/]+/[^/#?]+)")[0].str.lower().str.replace(r"\.git$", "", regex=True)
    by = {r: g.set_index("date").stars for r, g in Hh.groupby("repo")}
    created = {}
    if len(Rs) and "created_at" in Rs:
        created = dict(zip(Rs.repo, pd.to_datetime(Rs.created_at, utc=True, errors="coerce")))
    rows = []
    for r, day, t in zip(repo, Q.day, Q.created_at_i):
        f = {c: np.nan for c in GHC}
        f["gh_link"] = int(isinstance(r, str))
        s = by.get(r) if isinstance(r, str) else None
        if s is not None:
            D = pd.Timestamp(day)
            win = lambda a, b: float(s.reindex([(D - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(a, b + 1)]).fillna(0).sum())
            f["gh_d1"], f["gh_d7"], f["gh_d30"] = win(1, 1), win(1, 7), win(1, 30)
            f["gh_accel"] = f["gh_d7"] / 7 - (f["gh_d30"] - f["gh_d7"]) / 23
            f["gh_known"] = 1
        c = created.get(r) if isinstance(r, str) else None
        if c is not None and not pd.isna(c):
            f["gh_age_days"] = (t - c.timestamp()) / 86400
        rows.append(f)
    return pd.DataFrame(rows, index=Q.index)


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    vis60 = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()
    C1.Q = Q
    CM, WHO = C1.comments(15)
    base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], W15.votes15(Q), WHO], axis=1)   # votes + who (28.4%)
    G = gh_feats(Q)
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    sel = Q.day.isin(days).to_numpy()
    has = (G.gh_known == 1).to_numpy()
    print("posts with GitHub star data, Oct 2-14: " + ", ".join(
        f"{t} {int((has & sel & (kind == t)).sum())}/{int((sel & (kind == t)).sum())}" for t in ("fast", "late", "reup", "none")), flush=True)
    X1 = pd.concat([base, G], axis=1)
    s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        s0[te] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], y[tr]).predict_proba(base[te])[:, 1]
        s1[te] = lgb.LGBMClassifier(**W15.PRM).fit(X1[tr], y[tr]).predict_proba(X1[te])[:, 1]
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    c0, c1 = W.caught_on(T, s0[sel]), W.caught_on(T, s1[sel])
    print(f"Caught at 15 min, Oct 2-14: votes + who {W.ci2(c0)}; + GitHub stars {W.ci2(c1)}; difference {W.ci2(c1, c0)}", flush=True)
    g = has[sel]
    if g.any() and T.y[g].sum() > 0:
        c0g, c1g = W.caught_on(T[g], s0[sel][g]), W.caught_on(T[g], s1[sel][g])
        print(f"   GitHub-linked posts only ({int(g.sum())}, {int(T.y[g].sum())} winners): {W.ci2(c0g)} -> {W.ci2(c1g)}", flush=True)


if __name__ == "__main__":
    main()
