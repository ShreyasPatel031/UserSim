"""Live daily forecast of the Hacker News top 100 / top 10 (all stories, by final points per UTC day), refreshed hourly.

One code path for past and live: training rows and live rows get their features from the same functions here
(top10.feats for the post block; early_block / who_block for early comments and who wrote them), on the same kind of
input. Each story is scored by the model that matches how old it is:
  post   any age         title, domain / author records (2+ day old stories only), timing, volume
  v30    35+ min old      + comments in its first 30 min and each early commenter's past record
  v60    65+ min old      + the same for its first 60 min
A story younger than a window never gets that window's features (no input emptier live than in training).
Early points (hn_early_points, recorded live since Oct 30) have no history to train on yet; they are shown next to
the forecast, and the scorer reports how a plain points-at-60-min ranking does, side by side.

Data: BigQuery history (bq_stories / bq_comments, through Oct 17 2026) + Algolia for every story after that
(stories and their first-hour comments). Model trained on days before CAL0, calibrated (isotonic, P(top 100),
P(top 10)) on CAL0..CAL1, which is also the out-of-sample scoreboard.

Outputs each hour: hn_scores kind=forecast_top100 (frozen, made_on), gs://.../hn_jobs/forecast/latest.json and
latest.html. Daily: hn_scores kind=forecast_score for each finished day (2+ days old) against final points and the
recorded live front page (ever in the live top 10).

    python forecast_live.py train          # fit and save the models (once; ~20 min on hn-sim-1)
    python forecast_live.py once           # one forecast + scoring pass
    python forecast_live.py loop           # train if needed, then every hour
"""
from __future__ import annotations

import datetime as dt
import html as H
import json
import os
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge

import rank as R
import store as S
import top10 as T
from fetch import ALGOLIA, get, text_of
from stories import rows as algolia_rows

C = S.LOCAL
HIST0 = os.environ.get("FL_HIST0", "2023-01-01")    # history start
TRAIN0 = os.environ.get("FL_TRAIN0", "2023-03")     # first training month (records need 2 months of history)
CAL0, CAL1 = "2026-09-01", "2026-10-15"             # calibration / scoreboard window (BigQuery is final up to here)
GBM = dict(n_estimators=300, learning_rate=0.05, num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0, n_jobs=8)
MODEL = os.path.join(C, "fl_model.pkl")
GS = "usersim_sim/hn_jobs/forecast"
DRY = bool(os.environ.get("FL_DRY"))                 # test runs: no warehouse / GCS writes
GRACE = 5 * 60                                       # Algolia indexing slack before a window counts as complete


# ---------------------------------------------------------------- data

def wr(df: pd.DataFrame) -> None:
    if DRY:
        print("[dry] would write", len(df), "rows to hn_scores", flush=True)
    else:
        S.write("hn_scores", df)


def host_of(u) -> str:
    return urlparse(u if isinstance(u, str) else "").netloc.lower().removeprefix("www.")


def bq_stories() -> pd.DataFrame:
    s = pd.read_parquet(os.path.join(C, "bq_stories.parquet"))
    s = s[s.title.notna() & (s.day >= HIST0)]
    s["text"] = s.text.map(lambda x: text_of(x) if isinstance(x, str) else "")                  # BigQuery keeps HTML; Algolia rows are plain text (text_of)
    return s[["post_id", "day", "created_at_i", "title", "url", "text", "author", "points"]]


def recent_stories(since_ts: int, refetch_days: int = 3) -> pd.DataFrame:
    """Algolia stories from since_ts to now. Days older than refetch_days are fetched once and cached (points final);
    newer days are refetched every call."""
    path = os.path.join(C, "fl_recent.parquet")
    old = pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame(columns=["post_id", "day"])
    today = dt.datetime.now(dt.timezone.utc).date()
    keep_days = {d for d in old.day.unique() if dt.date.fromisoformat(d) < today - dt.timedelta(days=refetch_days)}
    old = old[old.day.isin(keep_days)]
    d = dt.datetime.fromtimestamp(since_ts, dt.timezone.utc).date()
    new = []
    while d <= today:
        if d.isoformat() not in keep_days:
            t0 = max(int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp()), since_ts)
            new += algolia_rows(t0, int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp()) + 86400 - t0)
        d += dt.timedelta(days=1)
    N = pd.DataFrame(new)
    if len(N):
        N = N[["post_id", "day", "created_at_i", "title", "url", "text", "author", "points"]]
    out = pd.concat([old, N], ignore_index=True).drop_duplicates("post_id", keep="last")
    out.to_parquet(path, index=False)
    return out


def all_stories() -> pd.DataFrame:
    b = bq_stories()
    r = recent_stories(int(b.created_at_i.max()) - 3600)
    p = pd.concat([b, r[~r.post_id.isin(b.post_id)]], ignore_index=True)
    p = p[p.title.notna()].drop_duplicates("post_id").sort_values("created_at_i").reset_index(drop=True)
    p["points"] = pd.to_numeric(p.points, errors="coerce").fillna(0).astype(float)
    p["month"] = p.day.str[:7]
    p["text"] = p.text.fillna("")
    p["link_kind"] = ""
    p["created_at_i"] = p.created_at_i.astype(np.int64)
    return p


def bq_early_comments(born: pd.Series) -> pd.DataFrame:
    """BigQuery comments within 60 min of their story (only what the early blocks need); cached after the first read."""
    path = os.path.join(C, "fl_bq_early.parquet")
    if os.path.exists(path):
        c = pd.read_parquet(path)
        c = c[c.story_id.isin(born.index)].copy()
        c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
        return c[(c.age >= 0) & (c.age <= 3600)].reset_index(drop=True)
    c = pd.read_parquet(os.path.join(C, os.environ.get("FL_COMMENTS", "bq_comments.parquet")),
                        columns=["person", "created_at_i", "story_id", "top_level"])
    c = c[c.story_id.notna()]
    c["story_id"] = c.story_id.astype(np.int64)
    c = c[c.story_id.isin(born.index)]
    c["age"] = c.created_at_i - c.story_id.map(born).to_numpy()
    c = c[(c.age >= 0) & (c.age <= 3600)].reset_index(drop=True)
    c.drop(columns="age").to_parquet(path, index=False)
    return c


def algolia_early(pid: int, born: int, window_s: int = 3600) -> list[dict]:
    j = get(f"{ALGOLIA}/search", {"tags": f"comment,story_{pid}", "hitsPerPage": 1000,
                                  "numericFilters": f"created_at_i<={born + window_s}"})
    return [{"person": h["author"], "created_at_i": h["created_at_i"], "story_id": pid,
             "top_level": int(h.get("parent_id") == pid)} for h in (j or {}).get("hits", []) if h.get("author")]


def recent_early_comments(p: pd.DataFrame, after_ts: int) -> pd.DataFrame:
    """First-hour comments (Algolia) for stories posted after after_ts. Stories 65+ min old are fetched once and
    cached; 35-65 min old ones are fetched fresh each call (only their 30-min window is used)."""
    path = os.path.join(C, "fl_recent_comments.parquet")
    cache = pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame(columns=["person", "created_at_i", "story_id",
                                                                                      "top_level"])
    done_path = os.path.join(C, "fl_recent_done.json")
    done = set(json.load(open(done_path))) if os.path.exists(done_path) else set()
    now = time.time()
    r = p[p.created_at_i > after_ts]
    full = r[(now - r.created_at_i >= 3600 + GRACE) & ~r.post_id.isin(done)]
    part = r[(now - r.created_at_i >= 1800 + GRACE) & (now - r.created_at_i < 3600 + GRACE)]
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda x: algolia_early(int(x[0]), int(x[1])), zip(full.post_id, full.created_at_i)))
        gp = list(ex.map(lambda x: algolia_early(int(x[0]), int(x[1]), 1800), zip(part.post_id, part.created_at_i)))
    add = pd.DataFrame([x for xs in got for x in xs])
    if len(add):
        cache = pd.concat([cache, add], ignore_index=True)
    done |= set(int(x) for x in full.post_id)
    cache.to_parquet(path, index=False)
    json.dump(sorted(done), open(done_path, "w"))
    out = pd.concat([cache, pd.DataFrame([x for xs in gp for x in xs])], ignore_index=True)
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    out = out[out.story_id.isin(born.index)].copy()
    out["created_at_i"] = out.created_at_i.astype(np.int64)
    out["age"] = out.created_at_i - out.story_id.map(born).to_numpy()
    return out[(out.age >= 0) & (out.age <= 3600)]


# ---------------------------------------------------------------- feature blocks (same for training and live)

def labels(p: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    rk = p.groupby("day").points.rank(ascending=False, method="first")
    return (pd.Series((rk <= 100).to_numpy(), index=p.post_id), pd.Series((rk <= 10).to_numpy(), index=p.post_id))


def early_block(c: pd.DataFrame, ids, W: int) -> pd.DataFrame:
    e = c[c.age <= W * 60].astype({"top_level": int, "age": float})
    g = e.groupby("story_id")
    b = pd.DataFrame({f"e{W}_all": g.size(), f"e{W}_top": g.top_level.sum(), f"e{W}_people": g.person.nunique(),
                      f"e{W}_first_s": g.age.min()}).reindex(ids)
    b[[f"e{W}_all", f"e{W}_top", f"e{W}_people"]] = b[[f"e{W}_all", f"e{W}_top", f"e{W}_people"]].fillna(0)
    b[f"e{W}_first_s"] = b[f"e{W}_first_s"].fillna(W * 60 * 2)
    return b.astype(float)


def person_records(pairs: pd.DataFrame, t0: int):
    """Each person's smoothed record of commenting early on stories that made the day's top 100 / top 10, from
    stories at least 2 days old at t0 (final points), over the 730 days before t0."""
    past = pairs[(pairs.t < t0 - 2 * 86400) & (pairs.t >= t0 - 730 * 86400)]
    pr100, pr10 = past.h100.mean(), past.h10.mean()
    rec = past.groupby("person").agg(n=("h100", "size"), s100=("h100", "sum"), s10=("h10", "sum"))
    return ((rec.s100 + 10 * pr100) / (rec.n + 10) / pr100, (rec.s10 + 10 * pr10) / (rec.n + 10) / pr10, rec.n)


def who_block(cur: pd.DataFrame, recs, ids, W: int) -> pd.DataFrame:
    l100, l10, n = recs
    cur = cur.copy()
    cur["l100"] = cur.person.map(l100).fillna(1.0).to_numpy()
    cur["l10"] = cur.person.map(l10).fillna(1.0).to_numpy()
    cur["n"] = cur.person.map(n).fillna(0).to_numpy()
    cur["scout"] = ((cur.l100 > 1.5) & (cur.n >= 20)).astype(float)
    cur["reg"] = (cur.n >= 50).astype(float)
    cur["new"] = (cur.n == 0).astype(float)
    g = cur.groupby("story_id")
    return pd.DataFrame({f"w{W}_l100_sum": g.l100.sum(), f"w{W}_l100_max": g.l100.max(), f"w{W}_l100_mean": g.l100.mean(),
                         f"w{W}_l10_sum": g.l10.sum(), f"w{W}_l10_max": g.l10.max(), f"w{W}_scouts": g.scout.sum(),
                         f"w{W}_regulars": g.reg.sum(), f"w{W}_new_people": g.new.sum()}).reindex(ids).fillna(0)


def early_pairs(c: pd.DataFrame, W: int, born: pd.Series, h100: pd.Series, h10: pd.Series) -> pd.DataFrame:
    e = c[c.age <= W * 60].drop_duplicates(["person", "story_id"])[["person", "story_id"]].copy()
    e["t"] = e.story_id.map(born).to_numpy()
    e["h100"] = e.story_id.map(h100).astype(float).to_numpy()
    e["h10"] = e.story_id.map(h10).astype(float).to_numpy()
    return e


def doc(p: pd.DataFrame) -> pd.Series:
    return p.title.fillna("") + " " + p.url.fillna("").str.replace(r"https?://(www\.)?", "", regex=True).str.split("/").str[0]


# ---------------------------------------------------------------- training

def train() -> None:
    t_start = time.time()
    p = all_stories()
    p = p[p.created_at_i < int(pd.Timestamp(CAL1, tz="UTC").timestamp())].reset_index(drop=True)   # final points only
    print("stories", len(p), p.day.min(), p.day.max(), flush=True)
    F = T.feats(p)
    print("post block", F.shape, f"{time.time() - t_start:.0f}s", flush=True)
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    c = bq_early_comments(born)
    h100, h10 = labels(p)
    blocks = {}
    for W in (30, 60):
        E = early_block(c, p.post_id, W)
        pairs = early_pairs(c, W, born, h100, h10)
        out = []
        for m in sorted(x for x in p.month.unique() if x >= TRAIN0):
            t0 = int(pd.Timestamp(m + "-01", tz="UTC").timestamp())
            ids = p.post_id[p.month == m]
            out.append(who_block(pairs[pairs.story_id.isin(ids)], person_records(pairs, t0), ids, W))
        Wb = pd.concat(out).reindex(p.post_id).fillna(0)
        blocks[W] = pd.concat([E, Wb], axis=1).reset_index(drop=True)
        print(f"early/who {W} built", f"{time.time() - t_start:.0f}s", flush=True)
    tr = ((p.month >= TRAIN0) & (p.day < CAL0)).to_numpy()
    cal = ((p.day >= CAL0) & (p.day < CAL1)).to_numpy()
    y = np.log1p(p.points.to_numpy())
    rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
    tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True, max_features=300000)
    D = doc(p)
    Xt = tf.fit_transform(D[tr])
    folds = np.arange(tr.sum()) % 5
    oof = np.zeros(tr.sum())
    for k in range(5):
        oof[folds == k] = Ridge(alpha=3.0).fit(Xt[folds != k], y[tr][folds != k]).predict(Xt[folds == k])
    ridge = Ridge(alpha=3.0).fit(Xt, y[tr])
    txt_cal = ridge.predict(tf.transform(D[cal]))
    print("text model", f"{time.time() - t_start:.0f}s", flush=True)
    cols = {"post": list(F.columns)}
    cols["v30"] = cols["post"] + list(blocks[30].columns)
    cols["v60"] = cols["v30"] + list(blocks[60].columns)
    X = pd.concat([F.reset_index(drop=True), blocks[30], blocks[60]], axis=1)
    keep = (rk <= 100) | (np.random.default_rng(0).random(len(p)) < 0.25)
    models, iso, board = {}, {}, []
    rng = np.random.default_rng(0)
    for v, cs in cols.items():
        m = lgb.LGBMClassifier(**{**GBM, "scale_pos_weight": 2})
        m.fit(X[tr & keep][cs].assign(text_score=oof[keep[tr]]), (rk[tr & keep] <= 100).astype(int))
        s = m.predict_proba(X[cal][cs].assign(text_score=txt_cal))[:, 1]
        iso[v] = {k: IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(s, (rk[cal] <= k).astype(float))
                  for k in (100, 10)}
        models[v] = m
        P = pd.DataFrame({"day": p.day[cal].to_numpy(), "y": y[cal], "s": s})
        r = {k: R.boot(T.day_hits(P, "s", k, rng)) for k in (100, 30, 10)}
        board += [{"kind": "forecast_board", "variant": v, "k": k, "recall": x[0], "lo": x[1], "hi": x[2],
                   "window": f"{CAL0}..{CAL1}", "days": int(P.day.nunique()), "made_on": S.now()} for k, x in r.items()]
        print(v, json.dumps(r), f"{time.time() - t_start:.0f}s", flush=True)
    rand = {k: round(float(np.mean([k / len(g) for _, g in P.groupby("day")])), 4) for k in (100, 30, 10)}
    pickle.dump({"tf": tf, "ridge": ridge, "models": models, "iso": iso, "cols": cols, "board": board, "random": rand,
                 "trained_on": S.now(), "train": f"{TRAIN0}..{CAL0}", "cal": f"{CAL0}..{CAL1}"}, open(MODEL, "wb"))
    wr(pd.DataFrame(board))
    print("saved model", f"{time.time() - t_start:.0f}s", flush=True)


# ---------------------------------------------------------------- live forecast

def early_points() -> pd.DataFrame:
    try:
        S.sync(("hn_early_points",))
        e = S.read("hn_early_points")
        return e.pivot_table(index="item_id", columns="age_min", values="points", aggfunc="last")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def forecast(M: dict) -> dict:
    now = int(time.time())
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    days = [(today - dt.timedelta(days=1)).isoformat(), today.isoformat()]
    p = all_stories()
    target = p.day.isin(days)
    F = T.feats(p)[target.to_numpy()]               # full frame, exactly as in training (day ranks need whole days)
    L = p[target].copy()
    L["age_min"] = (now - L.created_at_i) / 60
    born = pd.Series(p.created_at_i.to_numpy(), index=p.post_id)
    bq_end = int(pd.read_parquet(os.path.join(C, "bq_stories.parquet"), columns=["created_at_i"]).created_at_i.max())
    cb = bq_early_comments(born)
    cr = recent_early_comments(p, bq_end - 3600)
    c = pd.concat([cb, cr[~cr.story_id.isin(cb.story_id.unique())]], ignore_index=True)
    final = p.created_at_i < now - 2 * 86400            # records use stories with final points only
    h100, h10 = labels(p[final])
    blocks = {}
    for W in (30, 60):
        pairs = early_pairs(c[c.story_id.isin(h100.index)], W, born, h100, h10)
        cur = c[c.story_id.isin(L.post_id) & (c.age <= W * 60)].drop_duplicates(["person", "story_id"])
        E = early_block(c[c.story_id.isin(L.post_id)], L.post_id, W)
        Wb = who_block(cur, person_records(pairs, now), L.post_id, W)
        blocks[W] = pd.concat([E, Wb], axis=1).reset_index(drop=True)
    X = pd.concat([F.reset_index(drop=True), blocks[30], blocks[60]], axis=1)
    X["text_score"] = M["ridge"].predict(M["tf"].transform(doc(L)))
    variant = np.where(L.age_min * 60 >= 3600 + GRACE, "v60", np.where(L.age_min * 60 >= 1800 + GRACE, "v30", "post"))
    p100, p10 = np.zeros(len(L)), np.zeros(len(L))
    for v in ("post", "v30", "v60"):
        m = variant == v
        if m.any():
            s = M["models"][v].predict_proba(X[m][M["cols"][v] + ["text_score"]])[:, 1]
            p100[m], p10[m] = M["iso"][v][100].predict(s), M["iso"][v][10].predict(s)
    L["variant"], L["p100"], L["p10"] = variant, p100, p10
    # tie-break within equal calibrated odds by the raw ordering of a single model is not needed for display;
    # rank by p10 then p100
    ep = early_points()
    for a in (30, 60):
        L[f"pts_{a}"] = L.post_id.map(ep[a]) if a in getattr(ep, "columns", []) else np.nan
    out = {"made_on": S.now(), "model": {k: M[k] for k in ("trained_on", "train", "cal", "random")},
           "board": M["board"], "days": {}}
    rows = []
    for d in days:
        g = L[L.day == d].sort_values(["p10", "p100"], ascending=False)
        g = g.assign(rank=np.arange(1, len(g) + 1))
        out["days"][d] = {"n_stories": int(len(g)), "complete": d != today.isoformat(),
                          "top": [{"rank": int(r.rank), "post_id": int(r.post_id), "title": r.title, "url": r.url,
                                   "host": host_of(r.url), "age_min": round(float(r.age_min)), "model": r.variant,
                                   "p_top100": round(float(r.p100), 3), "p_top10": round(float(r.p10), 3),
                                   "points_at_30": None if pd.isna(r.pts_30) else int(r.pts_30),
                                   "points_at_60": None if pd.isna(r.pts_60) else int(r.pts_60)}
                                  for r in g.head(100).itertuples()]}
        rows.append(g.head(100).assign(kind="forecast_top100", forecast_day=d, made_on=out["made_on"])[
            ["kind", "forecast_day", "rank", "post_id", "title", "variant", "p100", "p10", "made_on"]])
    wr(pd.concat(rows, ignore_index=True))
    return out


# ---------------------------------------------------------------- scoring finished days

def score_days(max_days: int = 7) -> list[dict]:
    """Score the final forecast of each finished day (2+ days old) not yet scored."""
    S.sync(("hn_scores", "hn_frontpage"))
    sc = S.read("hn_scores")
    if not len(sc) or "forecast_day" not in sc:
        return []
    fc = sc[sc.kind == "forecast_top100"]
    done = set(sc.loc[sc.kind == "forecast_score", "forecast_day"]) if "forecast_day" in sc else set()
    today = dt.datetime.now(dt.timezone.utc).date()
    todo = sorted(d for d in fc.forecast_day.unique() if d not in done and dt.date.fromisoformat(d) <= today - dt.timedelta(days=2))
    fp = S.read("hn_frontpage")
    ep = early_points()
    out = []
    for d in todo[-max_days:]:
        f = fc[(fc.forecast_day == d) & (fc.made_on.str[:10] == d)]
        if not len(f):
            f = fc[fc.forecast_day == d]
        f = f[f.made_on == f.made_on.max()].sort_values("rank")
        t0 = int(pd.Timestamp(d, tz="UTC").timestamp())
        A = pd.DataFrame(algolia_rows(t0, 86400))
        if not len(A):
            continue
        A = A.sort_values("points", ascending=False)
        row = {"kind": "forecast_score", "forecast_day": d, "made_on": S.now(), "forecast_made_on": f.made_on.max(),
               "n_stories": len(A)}
        pred = f.post_id.tolist()
        for k in (100, 30, 10):
            row[f"recall_{k}"] = len(set(pred[:k]) & set(A.post_id.head(k))) / k
            row[f"random_{k}"] = k / len(A)
        if len(fp):
            day_items = set(A.post_id)
            live10 = set(fp[(fp["rank"] <= 10) & fp.item_id.isin(day_items)].item_id)
            row["live_top10_n"] = len(live10)
            if live10:
                row["live_top10_recall_at_30"] = len(set(pred[:30]) & live10) / len(live10)
                row["live_top10_recall_at_n"] = len(set(pred[:len(live10)]) & live10) / len(live10)
        if len(ep) and 60 in ep.columns:
            e60 = A.assign(p60=A.post_id.map(ep[60])).dropna(subset=["p60"])
            if len(e60) > 0.5 * len(A):                 # recorder covered most of the day
                by60 = e60.sort_values("p60", ascending=False).post_id.tolist()
                for k in (100, 10):
                    row[f"points60_recall_{k}"] = len(set(by60[:k]) & set(A.post_id.head(k))) / k
        out.append(row)
    if out:
        wr(pd.DataFrame(out))
    return out


# ---------------------------------------------------------------- page

def page(out: dict, scores: pd.DataFrame) -> str:
    def lst(d, n):
        g = out["days"].get(d)
        if not g:
            return "<p>No stories yet.</p>"
        rows = "".join(
            f"<tr><td>{x['rank']}</td><td><a href='{H.escape(x['url'] or 'https://news.ycombinator.com/item?id=' + str(x['post_id']))}'>"
            f"{H.escape(x['title'])}</a> <span class=h>{H.escape(x['host'])}</span></td><td>{x['p_top10']:.0%}</td>"
            f"<td>{x['p_top100']:.0%}</td><td>{x['age_min'] // 60}h{x['age_min'] % 60:02d}</td><td>{x['model']}</td>"
            f"<td>{'' if x['points_at_60'] is None else x['points_at_60']}</td></tr>" for x in g["top"][:n])
        return (f"<p>{g['n_stories']} stories so far.</p><table><tr><th>#</th><th>Story</th><th>P(top 10)</th>"
                f"<th>P(top 100)</th><th>Age</th><th>Model</th><th>Pts @60m</th></tr>{rows}</table>")
    days = sorted(out["days"])
    board = pd.DataFrame(out["board"])
    bt = "".join(f"<tr><td>{v}</td>" + "".join(
        f"<td>{board[(board.variant == v) & (board.k == k)].recall.iloc[0]:.1%}</td>" for k in (100, 30, 10)) + "</tr>"
        for v in ("post", "v30", "v60"))
    sc = ""
    if len(scores):
        sc = "".join(f"<tr><td>{r.forecast_day}</td><td>{r.recall_100:.0%}</td><td>{r.recall_10:.0%}</td></tr>"
                     for r in scores.sort_values("forecast_day").itertuples())
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>HN top 10 forecast</title><style>body{{font:14px system-ui;margin:16px;max-width:980px}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:4px 6px;border-bottom:1px solid #ddd;text-align:left}}.h{{color:#888;font-size:12px}}</style>
<h1>Hacker News daily top 10 forecast</h1><p>Updated {out['made_on']} (UTC). Odds are calibrated on Sep 1 - Oct 14 2026.</p>
<h2>Today ({days[-1]})</h2>{lst(days[-1], 30)}<h2>Yesterday ({days[0]})</h2>{lst(days[0], 10)}
<h2>Backtest (Sep 1 - Oct 14 2026, held out)</h2><table><tr><th>Model</th><th>top 100</th><th>top 30</th><th>top 10</th></tr>{bt}
<tr><td>random</td>{''.join(f"<td>{out['model']['random'][k]:.1%}</td>" for k in (100, 30, 10))}</tr></table>
<h2>Live scorecard</h2><table><tr><th>Day</th><th>top 100 found</th><th>top 10 found</th></tr>{sc}</table>"""


def once() -> dict:
    M = pickle.load(open(MODEL, "rb"))
    out = forecast(M)
    try:
        if not DRY:
            score_days()
    except Exception as exc:  # noqa: BLE001
        print("score error:", exc, flush=True)
    sc = S.read("hn_scores")
    sc = sc[sc.kind == "forecast_score"] if len(sc) else sc
    if DRY:
        open(os.path.join(C, "fl_latest.html"), "w").write(page(out, sc))
        json.dump(out, open(os.path.join(C, "fl_latest.json"), "w"), default=str)
        return out
    b = S._bucket()
    b.blob(f"{GS}/latest.json").upload_from_string(json.dumps(out, default=str), content_type="application/json")
    b.blob(f"{GS}/latest.html").upload_from_string(page(out, sc), content_type="text/html")
    d = sorted(out["days"])[-1]
    print(S.now(), d, out["days"][d]["n_stories"], "stories; top 5:",
          [x["title"][:50] for x in out["days"][d]["top"][:5]], flush=True)
    return out


def loop() -> None:
    if not os.path.exists(MODEL):
        train()
    while True:
        t = time.time()
        try:
            once()
        except Exception as exc:  # noqa: BLE001
            print("forecast error:", repr(exc)[:500], flush=True)
        time.sleep(max(60, 3600 - (time.time() - t)))


if __name__ == "__main__":
    {"train": train, "once": once, "loop": loop}[sys.argv[1]]()
