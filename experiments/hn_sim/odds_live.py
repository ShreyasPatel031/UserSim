"""Calibrated odds for new HN posts: P(the post makes its day's daily-list top 30 / top 10), at posting and, once it is
up, at 15 / 30 / 60 min / 2 h with its Quality News vote series. Same inputs and code as the backtest (odds.py),
minus the crowd-simulation inputs (they added nothing measurable and need the whole person panel).

    python odds_live.py train                          # fit + calibrate (Jul 1 - Aug 15 fit, Aug 16-31 calibrate,
                                                         # Sep 1 - Oct 14 test, reported); saves <cache>/odds_live.pkl
    python odds_live.py score --title "Show HN: ..." --url https://... [--author pg] [--at 2026-11-01T17:30Z]
    python odds_live.py score --id 50311686            # a live post: title/url/author/time from HN, votes so far
                                                         # from Quality News at the ages it has reached

Inputs per post (all known at posting): post features (top10.feats on the full story history + the new posts:
hour, weekday, title words, domain / author records, same link / domain / words in the hours before), title text
score (TF-IDF ridge on log points), title embedding (Vertex text-embedding-005, PCA 64) and the outcomes of the 30
most similar earlier titles. History: BigQuery stories to Oct 17 + Algolia since then (cached per day).
"""
import argparse
import json
import os
import pickle
import time
from urllib.parse import urlsplit

import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge
from sklearn.metrics import brier_score_loss, roc_auc_score

import emb_io
import top10 as T
import top100 as H

MODEL = os.path.join(H.CACHE, "odds_live.pkl")
AGES = {"at posting": 0, "15 min": 15, "30 min": 30, "1 h": 60, "2 h": 120, "3 h": 180}
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
VOTES = ["points", "rank_now", "best_rank", "gain30", "rate"]


def lists():
    return pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True, dtype={"day": str})
                      for f in ("frontday.jsonl", "frontday_old.jsonl")])


def doc(df):
    return df.title.fillna("") + " " + df.url.fillna("").str.replace(r"https?://(www\.)?", "", regex=True).str.split("/").str[0]


def vote_feats(rows, q_by_id, ages_min):
    """Votes and rank at each age from Quality News 10-minute series (qn.parse with QN_FINE)."""
    out = {}
    for a in ages_min:
        f = {c: np.full(len(rows), np.nan) for c in VOTES}
        for i, (pid, born) in enumerate(zip(rows.post_id, rows.created_at_i)):
            s = q_by_id.get(pid)
            if s is None:
                f["points"][i], f["rank_now"][i], f["best_rank"][i], f["gain30"][i] = 1, 91, 91, 0
                continue
            k = int(np.clip((born + a * 60 - s["qn_f0"]) // 600, 0, 216))
            rk = np.array([x if x is not None else 91 for x in s["qn_rank_10m"]], float)
            up = pd.Series(s["qn_up_10m"], dtype=float).ffill().fillna(1).to_numpy()
            ex = pd.Series(s["qn_exp_10m"], dtype=float).ffill().fillna(0).to_numpy()
            if k == 0:
                f["points"][i], f["rank_now"][i], f["best_rank"][i], f["gain30"][i] = 1, 91, 91, 0
                continue
            f["points"][i], f["rank_now"][i], f["best_rank"][i] = up[k - 1], rk[k - 1], rk[:k].min()
            f["gain30"][i] = up[k - 1] - (up[k - 4] if k > 3 else 1)
            f["rate"][i] = up[k - 1] / ex[k - 1] if ex[k - 1] > 0.5 else np.nan
        out[a] = pd.DataFrame(f, index=rows.index)
    return out


# ------------------------------------------------------------------------------------------------- training
def train():
    import fine_io
    p = H.stories()
    q = p[(p.day >= "2026-07-01") & (p.day <= "2026-10-14")].reset_index(drop=True)
    B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
    bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
    B = B[["post_id"] + bcols].drop_duplicates("post_id")
    A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))[["post_id"] + KNN + [f"emb{j}" for j in range(64)]]
    Q = q.merge(B, on="post_id", how="left").merge(A, on="post_id", how="left")
    # title text score: fit on stories before the training window, applied to everything after (no outcome leak)
    past = p[p.day < "2026-07-01"]
    tf = TfidfVectorizer(min_df=5, ngram_range=(1, 2), sublinear_tf=True, max_features=300000).fit(doc(past))
    rid = Ridge(alpha=3.0).fit(tf.transform(doc(past)), np.log1p(past.points.to_numpy()))
    Q["text_live"] = rid.predict(tf.transform(doc(Q)))
    L = lists()
    Q["list_rank"] = Q.post_id.map(L.groupby("post_id")["rank"].min()).fillna(999)
    # PCA of the title embedding, as audience.py (refit here so the live tool owns it)
    emb, ei = emb_io.load()
    E = np.asarray(emb[ei.reindex(Q.post_id).fillna(0).astype(int).to_numpy()], np.float32)
    fit, cal, te = (Q.day < "2026-08-16").to_numpy(), ((Q.day >= "2026-08-16") & (Q.day < "2026-09-01")).to_numpy(), (Q.day >= "2026-09-01").to_numpy()
    pca = PCA(64, random_state=0).fit(E[fit])
    Z = pd.DataFrame(pca.transform(E), columns=[f"pc{j}" for j in range(64)])
    Q = pd.concat([Q, Z], axis=1)
    BASE = ["text_live"] + bcols + KNN + list(Z.columns)
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    V = vote_feats(Q, q_by_id, [a for a in AGES.values() if a > 0])
    models, report = {}, []
    for name, a in AGES.items():
        X = Q[BASE] if a == 0 else pd.concat([Q[BASE], V[a]], axis=1)
        for top in (30, 10):
            y = (Q.list_rank <= top).to_numpy()
            m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                                   subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[fit], y[fit])
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(m.predict_proba(X[cal])[:, 1], y[cal])
            s = iso.predict(m.predict_proba(X[te])[:, 1])
            sc = iso.predict(m.predict_proba(X[cal])[:, 1])
            # live "will make it" threshold: max F1 on the calibration days, then applied unchanged to the test days
            grid = np.unique(np.round(sc, 4))
            f1 = [2 * ((sc >= g) & y[cal]).sum() / max((sc >= g).sum() + y[cal].sum(), 1) for g in grid]
            thr = float(grid[int(np.argmax(f1))])
            call = s >= thr
            prec = float(y[te][call].mean()) if call.any() else float("nan")
            rec = float(call[y[te]].mean())
            dec = pd.DataFrame({"p": s, "y": y[te]}).assign(d=lambda d: pd.qcut(d.p.rank(method="first"), 10, labels=False))
            dec = dec.groupby("d").agg(predicted=("p", "mean"), realized=("y", "mean"))
            models[(a, top)] = (m, iso, list(X.columns))
            report.append({"age": name, "top": top, "AUC": round(roc_auc_score(y[te], s), 3), "threshold": round(thr, 3),
                           "precision": round(prec, 3), "recall": round(rec, 3), "flagged": int(call.sum()),
                           "deciles_pred": dec.predicted.round(4).tolist(), "deciles_real": dec.realized.round(4).tolist(),
                           "Brier": round(brier_score_loss(y[te], s), 4), "base_Brier": round(brier_score_loss(y[te], np.full(te.sum(), y[fit].mean())), 4),
                           "mean_forecast": round(float(s.mean()), 4), "actual": round(float(y[te].mean()), 4)})
            print(json.dumps(report[-1]), flush=True)
    pickle.dump({"models": models, "tfidf": tf, "ridge": rid, "pca": pca, "bcols": bcols, "report": report}, open(MODEL, "wb"))
    print("saved", MODEL, flush=True)


# ------------------------------------------------------------------------------------------------- live scoring
def recent_history():
    """Stories since the BigQuery snapshot (Oct 17), from Algolia, cached per UTC day; current points."""
    path = os.path.join(H.CACHE, "algolia_recent.parquet")
    old = pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()
    t0 = int(pd.Timestamp("2026-10-17", tz="UTC").timestamp())
    since = max(t0, int(old.created_at_i.max()) - 6 * 3600) if len(old) else t0
    rows = []
    for lo in range(since, int(time.time()), 3 * 3600):
        r = requests.get("https://hn.algolia.com/api/v1/search_by_date", timeout=30, params={
            "tags": "story", "hitsPerPage": 1000, "numericFilters": f"created_at_i>={lo},created_at_i<{lo + 3 * 3600}"}).json()
        rows += [{"post_id": int(h["objectID"]), "title": h.get("title"), "url": h.get("url") or "", "author": h.get("author"),
                  "points": h.get("points") or 1, "created_at_i": h["created_at_i"], "text": h.get("story_text") or ""} for h in r.get("hits", [])]
    new = pd.DataFrame(rows)
    out = pd.concat([old, new]).drop_duplicates("post_id", keep="last") if len(new) else old
    out.to_parquet(path, index=False)
    return out


def embed(texts):
    import google.auth.transport.requests
    from auth import vertex_credentials
    import embed as EM
    cred = vertex_credentials()
    cred.refresh(google.auth.transport.requests.Request())
    r = requests.post(EM.URL, headers={"Authorization": f"Bearer {cred.token}"}, timeout=60,
                      json={"instances": [{"content": t[:2000], "task_type": "SEMANTIC_SIMILARITY"} for t in texts]})
    E = np.array([x["embeddings"]["values"] for x in r.json()["predictions"]], np.float32)
    return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


def score(rows: pd.DataFrame, now: float | None = None) -> pd.DataFrame:
    """rows: post_id (negative for drafts), title, url, author, created_at_i, text. Returns P(top 30 / top 10) at the
    latest age each post has reached by `now` (at posting for drafts / brand-new posts)."""
    M = pickle.load(open(MODEL, "rb"))
    now = now or time.time()
    hist = pd.concat([H.stories()[["post_id", "title", "url", "author", "points", "created_at_i", "text"]], recent_history()])
    hist = hist[~hist.post_id.isin(rows.post_id)]
    allp = pd.concat([hist, rows.assign(points=1)]).sort_values("created_at_i").reset_index(drop=True)
    allp["day"] = pd.to_datetime(allp.created_at_i, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    lo = allp.created_at_i.min()
    F = T.feats(allp)
    F.columns = [f"b_{c}" for c in F.columns]
    F["post_id"] = allp.post_id.to_numpy()
    X = rows[["post_id"]].merge(F, on="post_id", how="left")
    # submitter as a commenter (as top100.build): comments before the post, days since their first comment
    cc = H.comments()[["person", "created_at_i"]]
    cc = cc[cc.person.isin(set(rows.author.dropna()))]
    X["b_sub_comments_before"] = [int((cc.person.eq(a) & (cc.created_at_i < t)).sum()) for a, t in zip(rows.author, rows.created_at_i)]
    first = cc.groupby("person").created_at_i.min()
    X["b_sub_days_since_first_comment"] = [(t - first[a]) / 86400 if a in first.index else -1 for a, t in zip(rows.author, rows.created_at_i)]
    X["text_live"] = M["ridge"].predict(M["tfidf"].transform(doc(rows.reset_index(drop=True))))
    E = embed((rows.title.fillna("") + " (" + rows.url.map(lambda u: urlsplit(u).netloc.lower().removeprefix("www.") if u else "") + ")").tolist())
    Z = M["pca"].transform(E)
    for j in range(64):
        X[f"pc{j}"] = Z[:, j]
    # 30 most similar earlier titles: their log points, share 100+, share on a daily top 30
    emb, ei = emb_io.load()
    P = H.stories()
    past = P[P.post_id.isin(ei.index) & (P.points >= 3)]
    past = past.assign(_r=ei[past.post_id].to_numpy()).sort_values("_r")
    PE = np.asarray(emb[past._r.to_numpy()], np.float32)
    S = E @ PE.T
    k = np.argpartition(-S, 30, axis=1)[:, :30]
    lp = np.log1p(past.points.to_numpy(np.float32))
    t30 = past.post_id.isin(set(lists().query("rank <= 30").post_id)).to_numpy().astype(np.float32)
    X["knn_lp"], X["knn_100"] = lp[k].mean(1), (past.points.to_numpy()[k] >= 100).mean(1)
    X["knn_t30"], X["knn_sim"] = t30[k].mean(1), np.take_along_axis(S, k, 1).mean(1)
    # votes so far, for posts already up (Quality News series)
    age_min = (now - rows.created_at_i.to_numpy()) / 60
    reached = [max([a for a in AGES.values() if a <= m] or [0]) if pid > 0 else 0 for m, pid in zip(age_min, rows.post_id)]
    q_by_id = {}
    if any(a > 0 for a in reached):
        import qn
        os.environ["QN_FINE"] = "1"
        from concurrent.futures import ThreadPoolExecutor

        def one(job):
            pid, born = job
            try:
                r = requests.get(f"https://news.social-protocols.org/stats?id={pid}", timeout=150, headers=qn._s.headers)
                return pid, (qn.parse(r.text, int(born)) if r.status_code == 200 else None)
            except requests.RequestException:
                return pid, None
        jobs = [(pid, born) for pid, born, a in zip(rows.post_id, rows.created_at_i, reached) if pid > 0 and a > 0]
        with ThreadPoolExecutor(4) as ex:
            q_by_id = {pid: s for pid, s in ex.map(one, jobs) if s is not None}
    V = vote_feats(rows.reset_index(drop=True), q_by_id, sorted({a for a in reached if a > 0}))
    out = []
    for i, a in enumerate(reached):
        row = {"post_id": int(rows.post_id.iat[i]), "title": rows.title.iat[i], "age": [n for n, v in AGES.items() if v == a][0]}
        for top in (30, 10):
            m, iso, cols = M["models"][(a, top)]
            x = X.iloc[[i]].copy()
            if a > 0:
                for c in VOTES:
                    x[c] = V[a][c].iat[i]
            row[f"p_top{top}"] = float(iso.predict(m.predict_proba(x[cols])[:, 1])[0])
        out.append(row)
    return pd.DataFrame(out)


def recent(hours=3):
    """Score every story posted in the last `hours` at the age it has reached; one JSON per run for live scoring
    (score_live.py) -> <cache>/odds_live/<day>/<HHMM>.json and the bucket."""
    import store as S
    now = time.time()
    r = requests.get("https://hn.algolia.com/api/v1/search_by_date", timeout=30, params={
        "tags": "story", "hitsPerPage": 1000, "numericFilters": f"created_at_i>={int(now - hours * 3600)}"}).json()
    rows = pd.DataFrame([{"post_id": int(h["objectID"]), "title": h.get("title"), "url": h.get("url") or "", "author": h.get("author"),
                          "created_at_i": h["created_at_i"], "text": h.get("story_text") or ""} for h in r.get("hits", [])])
    out = score(rows, now)
    day, hm = time.strftime("%Y-%m-%d", time.gmtime(now)), time.strftime("%H%M", time.gmtime(now))
    path = os.path.join(H.CACHE, "odds_live", day, f"{hm}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.assign(made_at=int(now)).to_json(path, orient="records")
    S._bucket().blob(f"usersim_sim/hn_jobs/cache/odds_live/{day}/{hm}.json").upload_from_filename(path)
    print(len(out), "posts scored ->", path, flush=True)
    print(out.sort_values("p_top30", ascending=False).head(10).to_string(index=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "score", "recent"])
    ap.add_argument("--title")
    ap.add_argument("--url", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--at")
    ap.add_argument("--id", type=int)
    a = ap.parse_args()
    if a.cmd == "train":
        return train()
    if a.cmd == "recent":
        return recent()
    if a.id:
        it = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{a.id}.json", timeout=30).json()
        rows = pd.DataFrame([{"post_id": a.id, "title": it.get("title"), "url": it.get("url") or "", "author": it.get("by"),
                              "created_at_i": it["time"], "text": it.get("text") or ""}])
    else:
        t = int(pd.Timestamp(a.at).timestamp()) if a.at else int(time.time())
        rows = pd.DataFrame([{"post_id": -1, "title": a.title, "url": a.url, "author": a.author or None, "created_at_i": t, "text": ""}])
    r = score(rows)
    for x in r.itertuples():
        print(f"{x.title}\n  {x.age}: P(daily top 30) {x.p_top30:.1%}   P(top 10) {x.p_top10:.1%}")


if __name__ == "__main__":
    main()
