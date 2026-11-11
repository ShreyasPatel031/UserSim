"""1 h checkpoint, live (Shreyas, 2026-11-11): biggest miss bucket under the shipped 1 h score (rank blend of the
per-minute model and votes) = winners NOT on the front page by 1 h: 85 of 254 winners on full-coverage days Nov 2-10,
almost no flags. Front-page-by-1 h posts hold 169 winners, so perfect ranking there alone caps 1 h Caught at 66.5%.
One fix, tested on held-out days: swap the n weakest front-page flags of each day for the n strongest off-front posts,
off-front posts scored by a model trained on off-front posts only (at-posting odds + /newest vote inputs at 1 h).
n is chosen on Nov 2-6 only (0..8, maximising caught there); Nov 7-10 are held out and scored once.
All scores leave one posting day out (training never sees the scored day). Flags per day = that day's winners.

    python late60_c.py [feats.parquet]
"""
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

F = pd.read_parquet(sys.argv[1] if len(sys.argv) > 1 else "out/live_minute_feats.parquet")
F = F[F.day >= "2026-11-02"].reset_index(drop=True)
y = F.y.to_numpy()
days = sorted(F.day.unique())
ALL = [c for c in F.columns if c.startswith("m60_") and c != "m60_seen"] + ["p_post"]
OFFC = ["p_post", "m60_pts", "m60_cm", "m60_t2", "m60_t3", "m60_rate", "m60_vpe", "m60_vpe_w", "m60_expo_share",
        "m60_new_pos", "m60_new_push", "m60_new_seen_min", "hour"]
OFFC = [c if c in F.columns else "m60_" + c for c in OFFC]
off = (F.m60_front_best >= 999).to_numpy()
P1 = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, verbose=-1, random_state=0)
P2 = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40, verbose=-1, random_state=0)
votes = F.m60_pts.to_numpy() + 3 * (~off) + F.m60_cm.to_numpy() * 1e-3
base, soff = np.zeros(len(F)), np.zeros(len(F))
for d in days:
    te = (F.day == d).to_numpy()
    m = lgb.LGBMClassifier(**P1).fit(F.loc[~te, ALL], y[~te]).predict_proba(F.loc[te, ALL])[:, 1]
    base[te] = 0.5 * pd.Series(m).rank(pct=True).to_numpy() + 0.5 * pd.Series(votes[te]).rank(pct=True).to_numpy()
    soff[te] = lgb.LGBMClassifier(**P2).fit(F.loc[~te & off, OFFC], y[~te & off]).predict_proba(F.loc[te, OFFC])[:, 1]


def flags(n):
    fl = np.zeros(len(F), bool)
    for d in days:
        te = np.flatnonzero((F.day == d).to_numpy())
        k = int(y[te].sum())
        b = pd.Series(base[te]).rank(ascending=False, method="first").to_numpy()
        on = ~off[te]
        r_on = pd.Series(np.where(on, base[te], -np.inf)).rank(ascending=False, method="first").to_numpy()
        r_off = pd.Series(np.where(~on, soff[te], -np.inf)).rank(ascending=False, method="first").to_numpy()
        kept = b <= k                                   # shipped flags
        n_on = int((kept & on).sum())
        fl[te] = (on & (r_on <= max(n_on - n, 0))) | (~on & (r_off <= k - max(n_on - n, 0)))
    return fl


w = y == 1
dev = (F.day <= "2026-11-06").to_numpy()
hold = ~dev
res = {n: flags(n) for n in range(0, 9)}
print("n swaps | Nov 2-6 caught | Nov 7-10 caught | off-front caught (all)")
for n, fl in res.items():
    print(f"{n:7d} | {int((fl & w & dev).sum()):4d}/{int((w & dev).sum())} | {int((fl & w & hold).sum()):4d}/{int((w & hold).sum())} | "
          f"{int((fl & w & off).sum())}/{int((w & off).sum())}")
nb = max(res, key=lambda n: ((res[n] & w & dev).sum(), -n))
fl0, fl1 = res[0], res[nb]
print(f"chosen on Nov 2-6: n = {nb}")
print("held out Nov 7-10, per day (shipped -> fix):")
for d in days:
    m = (F.day == d).to_numpy()
    if hold[m].all():
        print(f"   {d}: {int((fl0 & w & m).sum())}/{int((w & m).sum())} -> {int((fl1 & w & m).sum())}/{int((w & m).sum())}")
print(f"held out total: {int((fl0 & w & hold).sum())}/{int((w & hold).sum())} -> {int((fl1 & w & hold).sum())}/{int((w & hold).sum())}")
print(f"all full-coverage days Nov 2-10: {int((fl0 & w).sum())}/{int(w.sum())} -> {int((fl1 & w).sum())}/{int(w.sum())}")
pw = []
for d in days:
    te = np.flatnonzero((F.day == d).to_numpy() & off)
    top = te[np.argsort(-soff[te])[:3]]
    pw.append(y[top].mean())
print(f"precision of each day's top-3 off-front picks: {np.mean(pw):.1%}")
