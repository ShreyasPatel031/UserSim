"""1 h checkpoint, live (Shreyas, 2026-11-10): the biggest miss bucket at 1 h on full-coverage days Nov 2-9 is late
risers (70 of 115 missed winners were not on the front page by 1 h). Within those off-front posts the at-posting odds
separate winners (AUC 0.80) while first-hour votes barely do (0.66), but the one joint model ranks almost all of them
below front-page posts. Variants, all leave-one-posting-day-out on the recorder's own data (out/live_minute_feats.parquet
from live15.py), flags per day = that day's winners:
  V0  current: one model, per-minute 1 h inputs + at-posting odds
  V1  two models (on / off the front page by 1 h), merged by predicted probability
  V2  V1, off-front model on at-posting odds + /newest votes only (no exposure / hour noise)
  V3  fixed two-pool split: off-front pool gets the share of winners that were off-front on the training days,
      ranked by at-posting odds; the rest go to front-page posts ranked by V0
  V4  V0 with monotone constraints (more points / earlier front page / higher odds never lowers the score)
Choice rule (set before looking at Nov 9 / Nov 10): best Caught on Nov 2-8; then Nov 9 and Nov 10 reported per post.

    python late60_live.py
"""
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

PRM = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, verbose=-1, random_state=0)
path = sys.argv[1] if len(sys.argv) > 1 else "out/live_minute_feats.parquet"
F = pd.read_parquet(path).reset_index(drop=True)
F = F[F.day >= "2026-11-02"].reset_index(drop=True)                 # full-coverage days only
ALL = [c for c in F.columns if c.startswith("m60_") and c != "m60_seen"] + ["p_post"]
OFFC = ["p_post", "m60_pts", "m60_cm", "m60_t2", "m60_t3", "m60_rate", "m60_new_pos", "m60_new_push", "m60_new_seen_min"]
off = (F.m60_front_best >= 999).to_numpy()
y = F.y.to_numpy()
days = sorted(F.day.unique())
mono = {"m60_pts": 1, "m60_front_min": 1, "m60_front_t": -1, "m60_front_best": -1, "p_post": 1, "m60_rate": 1}


def fit(tr, cols, **kw):
    return lgb.LGBMClassifier(**PRM, **kw).fit(F.loc[tr, cols], y[tr])


S = {k: np.zeros(len(F)) for k in ("V0", "V1", "V2", "V4")}
V3 = np.zeros(len(F), bool)
for d in days:
    te = (F.day == d).to_numpy()
    tr = ~te
    S["V0"][te] = fit(tr, ALL).predict_proba(F.loc[te, ALL])[:, 1]
    S["V4"][te] = fit(tr, ALL, monotone_constraints=[mono.get(c, 0) for c in ALL]).predict_proba(F.loc[te, ALL])[:, 1]
    for name, oc in (("V1", ALL), ("V2", OFFC)):
        s = np.zeros(te.sum())
        on_te, off_te = ~off[te], off[te]
        s[on_te] = fit(tr & ~off, ALL).predict_proba(F.loc[te & ~off, ALL])[:, 1]
        s[off_te] = fit(tr & off, oc).predict_proba(F.loc[te & off, oc])[:, 1]
        S[name][te] = s
    k = int(y[te].sum())
    share = y[tr & off].sum() / y[tr].sum()
    ko = int(round(share * k))
    g = F[te]
    r_on = pd.Series(np.where(~off[te], S["V0"][te], -np.inf)).rank(ascending=False, method="first").to_numpy()
    r_off = pd.Series(np.where(off[te], g.p_post.to_numpy(), -np.inf)).rank(ascending=False, method="first").to_numpy()
    V3[te] = (~off[te] & (r_on <= k - ko)) | (off[te] & (r_off <= ko))


def flags(s):
    out = np.zeros(len(F), bool)
    for d in days:
        te = (F.day == d).to_numpy()
        out[te] = pd.Series(s[te]).rank(ascending=False, method="first").to_numpy() <= y[te].sum()
    return out


FL = {k: flags(v) for k, v in S.items()}
FL["V3"] = V3
dev = (F.day <= "2026-11-08").to_numpy()
print(f"{'variant':6s} {'Nov 2-8':>12s} {'late risers':>12s} " + " ".join(f"{d[5:]:>7s}" for d in days))
for k in ("V0", "V1", "V2", "V3", "V4"):
    fl = FL[k]
    w = y == 1
    by = " ".join(f"{int((fl & w & (F.day == d).to_numpy()).sum()):>3d}/{int((w & (F.day == d).to_numpy()).sum()):<3d}" for d in days)
    print(f"{k:6s} {int((fl & w & dev).sum()):>4d}/{int((w & dev).sum())} {(fl & w & dev).sum() / (w & dev).sum():5.1%} "
          f"{int((fl & w & off & dev).sum()):>4d}/{int((w & off & dev).sum()):<4d}   " + by)
best = max(("V1", "V2", "V3", "V4"), key=lambda k: (FL[k] & (y == 1) & dev).sum())
print(f"chosen on Nov 2-8: {best} vs V0: {(FL[best] & (y == 1) & dev).sum()} vs {(FL['V0'] & (y == 1) & dev).sum()}")
F.assign(s_v0=S["V0"], flag_v0=FL["V0"], flag_best=FL[best], off_front=off).to_parquet("out/late60_live_scores.parquet", index=False)
