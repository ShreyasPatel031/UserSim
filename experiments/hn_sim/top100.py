"""Daily top-100 forecast with a growing feature set ("the scoreboard"). Stories and comments since 2023 from BigQuery
(history_bq.py). Features are built once and cached; each scoreboard step adds one block of data and is scored on the
same held-out months (rolling: test month M trained only on stories before M). Recall@k per UTC day by final points,
95% bootstrap over days. Rows go to hn_scores (kind=ladder).

Blocks (all known by the forecast time; votes are never inputs):
  post        title text score, domain / author records (stories 2+ days old only), timing, volume  (top10.feats)
  early{W}    comments in the first W minutes: all comments, top-level, distinct people, delay to first comment
  who{W}      WHO commented in the first W minutes: each person's past record (stories finished 2+ days before the
              test month): how often stories they commented on early made the day's top 100 / top 10, how many early
              comments they make; summed / maxed over the story's early commenters
  submitter   the submitter as a commenter: comments written before the post, early-comment record
  people2     early commenters' account age, new accounts, usual comment speed, past record on this domain

    python top100.py build
    python top100.py ladder post early30 who30 early60 who60 submitter
"""
from __future__ import annotations

import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T

CACHE = S.LOCAL
TEST = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
TARGET = 100
GBM = dict(n_estimators=300, learning_rate=0.05, num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0, n_jobs=4)


def stories() -> pd.DataFrame:
    s = pd.read_parquet(os.path.join(CACHE, "bq_stories.parquet"))
    s = s[s.title.notna()].drop_duplicates("post_id").sort_values("created_at_i").reset_index(drop=True)
    s["points"] = s.points.fillna(0).astype(float)
    s["month"] = s.day.str[:7]
    s["text"] = s.text.fillna("")
    s["link_kind"] = ""
    return s


def comments() -> pd.DataFrame:
    c = pd.read_parquet(os.path.join(CACHE, "bq_comments.parquet"))
    c = c[c.story_id.notna()]
    c["story_id"] = c.story_id.astype(np.int64)
    return c


def month_t0(m: str) -> int:
    return int(pd.Timestamp(m + "-01", tz="UTC").timestamp())


def build() -> None:
    p = stories()
    print("stories", len(p), flush=True)
    F = T.feats(p)
    F.insert(0, "post_id", p.post_id.to_numpy())
    F.to_parquet(os.path.join(CACHE, "f_post.parquet"), index=False)
    print("post block", F.shape, flush=True)
    c = comments()
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    c = c[c.story_id.isin(born.index)]
    c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
    c = c[c.age >= 0]
    rk = p.groupby("day").points.rank(ascending=False, method="first")
    hit100 = pd.Series((rk <= 100).to_numpy(), index=p.post_id)
    hit10 = pd.Series((rk <= 10).to_numpy(), index=p.post_id)
    months = sorted(m for m in p.month.unique() if m >= "2023-03")
    for W in (15, 30, 60):
        e = c[c.age <= W * 60]
        g = e.groupby("story_id")
        blk = pd.DataFrame({f"e{W}_all": g.size(), f"e{W}_top": g.top_level.sum(), f"e{W}_people": g.person.nunique(),
                            f"e{W}_first_s": g.age.min()})
        blk = blk.reindex(p.post_id).reset_index().rename(columns={"index": "post_id", "story_id": "post_id"})
        blk[[f"e{W}_all", f"e{W}_top", f"e{W}_people"]] = blk[[f"e{W}_all", f"e{W}_top", f"e{W}_people"]].fillna(0)
        blk[f"e{W}_first_s"] = blk[f"e{W}_first_s"].fillna(W * 60 * 2)
        blk.to_parquet(os.path.join(CACHE, f"f_early{W}.parquet"), index=False)
        # who: person records from stories finished 2+ days before each month
        pairs = e.drop_duplicates(["person", "story_id"])[["person", "story_id"]].copy()
        pairs["t"] = pairs.story_id.map(born).to_numpy()
        pairs["h100"] = pairs.story_id.map(hit100).astype(float).to_numpy()
        pairs["h10"] = pairs.story_id.map(hit10).astype(float).to_numpy()
        out = []
        for m in months:
            t0 = month_t0(m)
            past = pairs[(pairs.t < t0 - 2 * 86400) & (pairs.t >= t0 - 730 * 86400)]
            pr100, pr10 = past.h100.mean(), past.h10.mean()
            rec = past.groupby("person").agg(n=("h100", "size"), s100=("h100", "sum"), s10=("h10", "sum"))
            l100 = (rec.s100 + 10 * pr100) / (rec.n + 10) / pr100
            l10 = (rec.s10 + 10 * pr10) / (rec.n + 10) / pr10
            cur = pairs[pairs.story_id.isin(p.post_id[p.month == m])].copy()
            cur["l100"] = cur.person.map(l100).fillna(1.0).to_numpy()
            cur["l10"] = cur.person.map(l10).fillna(1.0).to_numpy()
            cur["n"] = cur.person.map(rec.n).fillna(0).to_numpy()
            cur["scout"] = ((cur.l100 > 1.5) & (cur.n >= 20)).astype(float)
            g = cur.groupby("story_id")
            out.append(pd.DataFrame({f"w{W}_l100_sum": g.l100.sum(), f"w{W}_l100_max": g.l100.max(),
                                     f"w{W}_l100_mean": g.l100.mean(), f"w{W}_l10_sum": g.l10.sum(),
                                     f"w{W}_l10_max": g.l10.max(), f"w{W}_scouts": g.scout.sum(),
                                     f"w{W}_regulars": (g.n.apply(lambda x: (x >= 50).sum())),
                                     f"w{W}_new_people": g.n.apply(lambda x: (x == 0).sum())}))
        who = pd.concat(out).reindex(p.post_id).fillna(0).reset_index().rename(columns={"story_id": "post_id",
                                                                                         "index": "post_id"})
        who.to_parquet(os.path.join(CACHE, f"f_who{W}.parquet"), index=False)
        print(f"early/who {W} min built", flush=True)
    # submitter as a commenter: comments before the post (all time in the data), early-comment record
    cc = c.sort_values("created_at_i")
    first = cc.groupby("person").created_at_i.min()
    sub = pd.DataFrame({"post_id": p.post_id, "author": p.author, "t": p.created_at_i})
    ct = cc[["person", "created_at_i"]].sort_values(["person", "created_at_i"])
    grp = {k: v.to_numpy() for k, v in ct.groupby("person").created_at_i}
    sub["sub_comments_before"] = [np.searchsorted(grp.get(a, np.array([])), t) for a, t in zip(sub.author, sub.t)]
    sub["sub_days_since_first_comment"] = (sub.t - sub.author.map(first)).fillna(-1) / 86400
    sub[["post_id", "sub_comments_before", "sub_days_since_first_comment"]].to_parquet(
        os.path.join(CACHE, "f_submitter.parquet"), index=False)
    print("submitter block built", flush=True)


def build_people2(W: int = 60) -> None:
    """More per-person data on each story's early commenters (first W minutes), all from before the story:
    account age (HN profile), share of brand-new accounts, how fast each person usually comments (past median delay),
    and each person's past early record on this story's domain."""
    from urllib.parse import urlparse
    p = stories()
    c = comments()
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    host = pd.Series(p.url.fillna("").map(lambda u: urlparse(u).netloc.lower().removeprefix("www.")).to_numpy(),
                     index=p.post_id)
    c = c[c.story_id.isin(born.index)]
    c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
    e = c[(c.age >= 0) & (c.age <= W * 60)].sort_values("age").drop_duplicates(["person", "story_id"]).copy()
    e["t"] = e.story_id.map(born).to_numpy()
    e["host"] = e.story_id.map(host).to_numpy()
    rk = p.groupby("day").points.rank(ascending=False, method="first")
    e["h100"] = e.story_id.map(pd.Series((rk <= 100).to_numpy(), index=p.post_id)).astype(float).to_numpy()
    prof = pd.read_parquet(os.path.join(CACHE, "hn_profiles.parquet")).set_index("person")
    e["acct_days"] = (e.t - e.person.map(prof.created)) / 86400
    out = []
    for m in sorted(m for m in p.month.unique() if m >= "2023-03"):
        t0 = month_t0(m)
        past = e[(e.t < t0 - 2 * 86400) & (e.t >= t0 - 730 * 86400)]
        lat = past.groupby("person").age.median()
        prior = past.h100.mean()
        ph = past.groupby(["person", "host"]).h100.agg(["sum", "count"])
        ph_l = ((ph["sum"] + 3 * prior) / (ph["count"] + 3) / prior)
        cur = e[e.story_id.isin(p.post_id[p.month == m])].copy()
        cur["lat"] = cur.person.map(lat)
        cur["fast"] = (cur.lat < 600).astype(float)
        cur["dom_l"] = pd.Series(list(zip(cur.person, cur.host))).map(ph_l).fillna(1.0).to_numpy()
        cur["dom_seen"] = pd.Series(list(zip(cur.person, cur.host))).map(ph["count"]).fillna(0).to_numpy()
        g = cur.groupby("story_id")
        out.append(pd.DataFrame({"p2_acct_days_med": g.acct_days.median(),
                                 "p2_new_accts": g.acct_days.apply(lambda x: (x < 30).sum()),
                                 "p2_lat_med": g.lat.median(), "p2_fast": g.fast.sum(),
                                 "p2_dom_l_max": g.dom_l.max(), "p2_dom_l_sum": g.dom_l.sum(),
                                 "p2_dom_regulars": g.dom_seen.apply(lambda x: (x >= 3).sum())}))
    f = pd.concat(out).reindex(p.post_id).reset_index().rename(columns={"story_id": "post_id", "index": "post_id"})
    f.to_parquet(os.path.join(CACHE, "f_people2.parquet"), index=False)
    print("people2 block built", f.shape, flush=True)


BLOCK_FILES = {"reach": "f_reach", "reach_x": "f_reach_x", "lobsters": "f_lobsters", "tranco": "f_tranco", "favtaste": "f_favtaste", "people2": "f_people2","post": "f_post", "early15": "f_early15", "early30": "f_early30", "early60": "f_early60",
               "who15": "f_who15", "who30": "f_who30", "who60": "f_who60", "submitter": "f_submitter"}


def ladder(steps: list[str], neg_frac: float = 0.25) -> None:
    p = stories()
    p = p[p.month <= TEST[-1]].reset_index(drop=True)
    y = np.log1p(p.points.to_numpy())
    rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
    blocks = {}
    for b in set(steps):
        f = pd.read_parquet(os.path.join(CACHE, BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
        blocks[b] = f.set_index("post_id").reindex(p.post_id).reset_index(drop=True)
    rng = np.random.default_rng(0)
    keep = (rk <= TARGET) | (rng.random(len(p)) < neg_frac)          # train on all positives, a sample of negatives
    texts = {}
    for m in TEST:
        tr, te = (p.month < m).to_numpy() & (p.month >= "2023-03").to_numpy(), (p.month == m).to_numpy()
        texts[m] = T.text_scores(p, y, tr, te)
        print("text", m, flush=True)
    rows, cols = [], []
    for i, b in enumerate(steps):
        cols = cols + [b]
        if os.environ.get("LADDER_LAST") and i < len(steps) - 1:   # score only the full set (base is scored elsewhere)
            continue
        X = pd.concat([blocks[x] for x in cols], axis=1)
        res = []
        for m in TEST:
            tr = (p.month < m).to_numpy() & (p.month >= "2023-03").to_numpy()
            te = (p.month == m).to_numpy()
            oof, txt = texts[m]
            trk = tr & keep
            Xtr = X[tr].assign(text_score=oof)[keep[tr]]
            c = lgb.LGBMClassifier(**{**GBM, "scale_pos_weight": 2}).fit(Xtr, (rk[trk] <= TARGET).astype(int))
            res.append(pd.DataFrame({"day": p.day[te].to_numpy(), "y": y[te],
                                     "s": c.predict_proba(X[te].assign(text_score=txt))[:, 1]}))
        P = pd.concat(res, ignore_index=True)
        r = {k: R.boot(T.day_hits(P, "s", k, rng)) for k in (100, 30, 10)}
        name = "+".join(cols)
        rows += [{"kind": "ladder", "variant": name, "k": k, "recall": v[0], "lo": v[1], "hi": v[2], "data": "bq2023",
                  "test": f"{TEST[0]}..{TEST[-1]}", "days": int(P.day.nunique()), "made_on": S.now()} for k, v in r.items()]
        print(name, json.dumps(r), flush=True)
    print("random", {k: round(float(np.mean([k / len(g) for _, g in P.groupby("day")])), 3) for k in (100, 30, 10)})
    S.write("hn_scores", pd.DataFrame(rows))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build()
    elif sys.argv[1] == "build_people2":
        build_people2()
    else:
        ladder(sys.argv[2:])
