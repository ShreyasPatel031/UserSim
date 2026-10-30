"""Daily list (news.ycombinator.com/front?day=D) forecast, v2. Per (day, story) candidate rows (stories posted in the
72 h before the end of D), per-day LGBMRanker on the real list (graded: rank 1..30 -> 30..1). Test months 2026-05..09,
each trained on earlier days (lists from Jan 2025).

New inputs (all known when the forecast is made):
  prev_list_rank   the story's place on the previous day's list (published at 00:00 UTC of D), 999 if absent
  day_age_h        hours between posting and the end of D; posted_before_d
  comments by the forecast time T on day D: all, distinct people, in the last 3 h before T, first-comment delay
Forecast times T: 06:00, 12:00, 18:00 UTC of day D and the end of D (the end-of-day row is the upper bound for a
forecast made with the day's full comment activity but without votes).

    python daily2.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T
import top100 as H

TEST = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
WINDOW_H = 72
L = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True, dtype={"day": str})
               for f in ("frontday.jsonl", "frontday_old.jsonl")]).drop_duplicates(["day", "rank"])
p = H.stories()
p = p[p.month >= "2023-03"].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
born = p.created_at_i.to_numpy()

rows = []
for d in sorted(L.day.unique()):
    t1 = pd.Timestamp(d, tz="UTC").timestamp() + 86400
    idx = np.flatnonzero((born >= t1 - WINDOW_H * 3600) & (born < t1))
    rows.append(pd.DataFrame({"day": d, "i": idx}))
C = pd.concat(rows, ignore_index=True)
C["post_id"] = p.post_id.to_numpy()[C.i]
C["t1"] = pd.to_datetime(C.day, utc=True).map(lambda x: x.timestamp()).to_numpy() + 86400
C["day_age_h"] = (C.t1 - born[C.i]) / 3600
C["posted_before_d"] = (C.day_age_h > 24).astype(int)
real = L[L["rank"] <= 30].set_index(["day", "post_id"])["rank"]
allrank = L.set_index(["day", "post_id"])["rank"]
C["real_rank"] = [real.get((d, x), 999) for d, x in zip(C.day, C.post_id)]
prev = (pd.to_datetime(C.day) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
C["prev_list_rank"] = [allrank.get((d, x), 999) for d, x in zip(prev, C.post_id)]
C["month"] = C.day.str[:7]
print("rows", len(C), "positives", int((C.real_rank <= 30).sum()), "with a previous-day rank",
      int((C.prev_list_rank < 999).sum()), flush=True)

# comments by forecast time T (per row), from the BigQuery comment table
cm = H.comments()[["story_id", "person", "created_at_i"]]
cm = cm[cm.story_id.isin(set(C.post_id))].sort_values(["story_id", "created_at_i"])
ct = {k: v.to_numpy() for k, v in cm.groupby("story_id").created_at_i}
cp = {k: v.to_numpy() for k, v in cm.groupby("story_id").person}


def by_time(T_off):
    """comment features for each row at time t1 - T_off hours."""
    out = np.zeros((len(C), 4))
    for r, (pid, t1) in enumerate(zip(C.post_id.to_numpy(), C.t1.to_numpy())):
        ts = ct.get(pid)
        if ts is None:
            out[r] = (0, 0, 0, 99)
            continue
        T_ = t1 - T_off * 3600
        n = np.searchsorted(ts, T_)
        n3 = n - np.searchsorted(ts, T_ - 3 * 3600)
        out[r] = (n, len(set(cp[pid][:n])) if n else 0, n3, (ts[0] - born[C.i.iat[r]]) / 3600 if n else 99)
    return pd.DataFrame(out, columns=["c_all", "c_people", "c_last3h", "c_first_h"])


blk = {b: pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
       .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in ["post", "who30", "who60", "submitter"]}
base = pd.concat([blk[b] for b in blk], axis=1).iloc[C.i].reset_index(drop=True)
rng = np.random.default_rng(0)
out_rows = []
for label, T_off in (("forecast at 06:00 UTC", 18), ("forecast at 12:00 UTC", 12), ("forecast at 18:00 UTC", 6),
                     ("end of day (comments only, upper bound)", 0)):
    F = by_time(T_off)
    # a story not yet posted at the forecast time is not visible: its row is dropped from scoring
    visible = (C.t1 - T_off * 3600 > born[C.i]).to_numpy()
    X = pd.concat([base, F], axis=1).assign(day_age_h=C.day_age_h.to_numpy() - T_off, posted_before_d=C.posted_before_d,
                                            prev_list_rank=C.prev_list_rank)
    res = []
    for m in TEST:
        tr_s, te_s = (p.month < m).to_numpy(), (p.month == m).to_numpy()
        oof, txt = T.text_scores(p, y, tr_s, te_s)
        ts = np.full(len(p), np.nan)
        ts[tr_s], ts[te_s] = oof, txt
        X["text_score"] = ts[C.i]
        tr = (C.month < m).to_numpy() & visible
        te = (C.month == m).to_numpy() & visible
        o = np.argsort(C.day.to_numpy()[tr], kind="stable")
        dtr = C.day.to_numpy()[tr][o]
        grp = np.diff(np.flatnonzero(np.r_[True, dtr[1:] != dtr[:-1], True]))
        lab = np.clip(31 - C.real_rank.to_numpy()[tr][o], 0, 30).astype(int)
        rnk = lgb.LGBMRanker(**{**H.GBM, "n_estimators": 500}, label_gain=list(range(31)))
        rnk.fit(X[tr].iloc[o], lab, group=grp)
        res.append(C[te][["day", "post_id", "real_rank"]].assign(s=rnk.predict(X[te])))
        print(label, m, flush=True)
    P = pd.concat(res, ignore_index=True)
    r = {}
    for k, n in ((30, 30), (10, 10), (10, 30), (30, 100)):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(n, "s").post_id)) / k for _, g in P.groupby("day")]
        r[f"real{k}_in_top{n}"] = R.boot(v)
    print(label, json.dumps(r), flush=True)
    out_rows += [{"kind": "daily_list_v2", "variant": label, "metric": k, "value": v[0], "lo": v[1], "hi": v[2],
                  "days": int(P.day.nunique()), "made_on": S.now()} for k, v in r.items()]
S.write("hn_scores", pd.DataFrame(out_rows))
