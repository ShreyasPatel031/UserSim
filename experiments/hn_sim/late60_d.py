"""1 h checkpoint, live (Shreyas, 2026-11-11): a stronger early signal for winners not on the front page by 1 h (85 of
254 winners on full-coverage days Nov 2-10; the shipped score flags ~none of them; ceiling without them 66.5%).
Candidate signals, all fixed before the post's 1 h mark:
  velocity  first-15-min votes / comments on /newest (recorder, m15_*) and their 15 -> 60 min change
  author    the submitter's past stories created >= 3 days before this post (points settled): count, share >= 100
            points, max points, days since last story, same URL submitted before by anyone (count, best points)
  domain    the link's domain, same window: count, share >= 100 points, median points
History = BigQuery stories to Oct 17 + Algolia stories since (current points; only rows >= 3 days older than the post).
Test, leave one posting day out, flags per day = winners:
  (1) separation within off-front posts: AUC of each signal group alone and with the at-posting odds
  (2) held out: the shipped 1 h score with (a) the new inputs added to its model, (b) the late60_c swap using an
      off-front model with the new inputs; n swaps chosen on Nov 2-6, Nov 7-10 scored once.

    python late60_d.py
"""
import os
import re

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import odds_live as OL
import top100 as H

F = pd.read_parquet("out/live_minute_feats.parquet")
F = F[F.day >= "2026-11-02"].reset_index(drop=True)
R = OL.recent_history()
hist = pd.concat([H.stories()[["post_id", "url", "author", "points", "created_at_i"]],
                  R[["post_id", "url", "author", "points", "created_at_i"]]]).drop_duplicates("post_id", keep="last")
F = F.merge(R[["post_id", "url", "author", "created_at_i"]], on="post_id", how="left")
dom = lambda u: re.sub(r"^www\.", "", re.sub(r"^https?://", "", u or "").split("/")[0].lower())
hist["dom"] = hist.url.fillna("").map(dom)
F["dom"] = F.url.fillna("").map(dom)
hist = hist.sort_values("created_at_i")
H3 = 3 * 86400


def prior(key, col):
    """per post: stats over history rows with the same key created >= 3 days before the post"""
    g = {k: v for k, v in hist[hist[key].fillna("") != ""].groupby(key)}
    n, top, mx, last = [], [], [], []
    for k, t in zip(F[col].fillna(""), F.created_at_i):
        h = g.get(k)
        if h is None or k == "":
            n.append(0); top.append(np.nan); mx.append(np.nan); last.append(np.nan); continue
        h = h[h.created_at_i < t - H3]
        n.append(len(h))
        top.append((h.points >= 100).mean() if len(h) else np.nan)
        mx.append(h.points.max() if len(h) else np.nan)
        last.append((t - h.created_at_i.max()) / 86400 if len(h) else np.nan)
    return np.array(n), np.array(top), np.array(mx), np.array(last)


F["a_n"], F["a_top"], F["a_max"], F["a_days"] = prior("author", "author")
d_n, d_top, d_max, _ = prior("dom", "dom")
F["d_n"], F["d_top"], F["d_max"] = d_n, d_top, d_max
F.loc[F.dom.isin(["", "github.com", "youtube.com", "medium.com", "twitter.com", "x.com"]), ["d_top", "d_max"]] = np.nan
u_n, _, u_max, _ = prior("url", "url")
F["u_n"], F["u_max"] = u_n, u_max
F.loc[F.url.fillna("") == "", ["u_n", "u_max"]] = np.nan
F["v15_60"] = F.m60_pts - F.m15_pts
F["c15_60"] = F.m60_cm - F.m15_cm
VEL = ["m15_pts", "m15_cm", "m15_t2", "m15_t3", "m15_rate", "m15_vpe", "m15_new_pos", "v15_60", "c15_60"]
AUTH = ["a_n", "a_top", "a_max", "a_days", "u_n", "u_max"]
DOM = ["d_n", "d_top", "d_max"]
OFF0 = ["p_post", "m60_pts", "m60_cm", "m60_t2", "m60_t3", "m60_rate", "m60_vpe", "m60_vpe_w", "m60_expo_share",
        "m60_new_pos", "m60_new_push", "m60_new_seen_min", "m60_hour"]
y = F.y.to_numpy()
w = y == 1
days = sorted(F.day.unique())
off = (F.m60_front_best >= 999).to_numpy()
P2 = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40, verbose=-1, random_state=0)
P1 = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, verbose=-1, random_state=0)


def lodo(cols, rows, prm):
    s = np.full(len(F), np.nan)
    for d in days:
        te = (F.day == d).to_numpy()
        s[te] = lgb.LGBMClassifier(**prm).fit(F.loc[~te & rows, cols], y[~te & rows]).predict_proba(F.loc[te, cols])[:, 1]
    return s


print(f"off-front posts {int(off.sum())}, winners {int((off & w).sum())}; coverage: author history "
      f"{(F.a_n[off & w] > 0).mean():.0%} of off-front winners, URL seen before {(F.u_n[off & w] > 0).mean():.0%}")
print("(1) AUC within off-front posts (leave one day out), and precision of each day's top 3:")
G = {"odds + 1 h /newest (late60_c)": OFF0, "velocity alone": VEL, "author + URL alone": AUTH, "domain alone": DOM,
     "odds + 1 h + velocity": OFF0 + VEL, "odds + 1 h + author": OFF0 + AUTH, "odds + 1 h + domain": OFF0 + DOM,
     "odds + 1 h + all three": OFF0 + VEL + AUTH + DOM}
SOFF = {}
for name, cols in G.items():
    s = lodo(cols, off, P2)
    SOFF[name] = s
    top3 = np.mean([y[np.flatnonzero((F.day == d).to_numpy() & off)][np.argsort(-s[(F.day == d).to_numpy() & off])[:3]].mean() for d in days])
    print(f"   {name:32s} AUC {roc_auc_score(y[off], s[off]):.3f}   top-3 precision {top3:.1%}")
ALL0 = [c for c in F.columns if c.startswith("m60_") and c != "m60_seen"] + ["p_post"]
votes = F.m60_pts.to_numpy() + 3 * (~off) + F.m60_cm.to_numpy() * 1e-3


def blend(m):
    out = np.zeros(len(F))
    for d in days:
        te = (F.day == d).to_numpy()
        out[te] = 0.5 * pd.Series(m[te]).rank(pct=True).to_numpy() + 0.5 * pd.Series(votes[te]).rank(pct=True).to_numpy()
    return out


base = blend(lodo(ALL0, np.ones(len(F), bool), P1))
newm = blend(lodo(ALL0 + VEL + AUTH + DOM, np.ones(len(F), bool), P1))


def flags(score, soff=None, n=0):
    fl = np.zeros(len(F), bool)
    for d in days:
        te = np.flatnonzero((F.day == d).to_numpy())
        k = int(y[te].sum())
        if soff is None or n == 0:
            fl[te] = pd.Series(score[te]).rank(ascending=False, method="first").to_numpy() <= k
            continue
        on = ~off[te]
        kept = pd.Series(score[te]).rank(ascending=False, method="first").to_numpy() <= k
        n_on = max(int((kept & on).sum()) - n, 0)
        r_on = pd.Series(np.where(on, score[te], -np.inf)).rank(ascending=False, method="first").to_numpy()
        r_off = pd.Series(np.where(~on, soff[te], -np.inf)).rank(ascending=False, method="first").to_numpy()
        fl[te] = (on & (r_on <= n_on)) | (~on & (r_off <= k - n_on))
    return fl


dev = (F.day <= "2026-11-06").to_numpy()
hold = ~dev
c = lambda fl, m: f"{int((fl & w & m).sum())}/{int((w & m).sum())}"
print("(2) held-out test (choices on Nov 2-6, Nov 7-10 scored once):")
f0 = flags(base)
print(f"   shipped 1 h score                       Nov 2-6 {c(f0, dev)}  Nov 7-10 {c(f0, hold)}  all {c(f0, np.ones(len(F), bool))}")
fa = flags(newm)
print(f"   (a) new inputs in the 1 h model          Nov 2-6 {c(fa, dev)}  Nov 7-10 {c(fa, hold)}  all {c(fa, np.ones(len(F), bool))}  "
      f"off-front caught {int((fa & w & off).sum())}")
so = SOFF["odds + 1 h + all three"]
res = {n: flags(base, so, n) for n in range(0, 9)}
nb = max(res, key=lambda n: ((res[n] & w & dev).sum(), -n))
print("   (b) swap n weakest front flags for top off-front (new inputs): " +
      ", ".join(f"n={n} {c(fl, dev)} | {c(fl, hold)}" for n, fl in res.items()))
fb = res[nb]
print(f"   (b) chosen n = {nb}: Nov 2-6 {c(fb, dev)}  Nov 7-10 {c(fb, hold)}  all {c(fb, np.ones(len(F), bool))}")
for d in days:
    m = (F.day == d).to_numpy()
    if hold[m].all():
        print(f"      {d}: shipped {c(f0, m)}, (a) {c(fa, m)}, (b) {c(fb, m)}")
