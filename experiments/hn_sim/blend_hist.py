"""Checkpoint 3 (at posting): rank blend of the Jul-Aug model (all at-posting inputs) and the 2025+ history model
(caught.py history2 test scores). 50/50 is the pre-set weight; 0.3 / 0.7 are shown for reference only (chosen on test)."""
import os, sys
sys.path.insert(0, "/home/user/UserSim/experiments/hn_sim")
os.chdir("/home/user/UserSim/experiments/hn_sim")
import numpy as np, pandas as pd
import caught as C, top100 as H
h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
b = C.model(C.POST + C.KNN + C.EMB + C.CROWD)
base = C.caught(b); print("base Jul-Aug full", C.ci(base))
hh = C.caught(h); print("2025+ history + emb", C.ci(hh), C.diff(hh, base))
rb, rh = pd.Series(b).rank(pct=True).to_numpy(), pd.Series(h).rank(pct=True).to_numpy()
for w in (0.3, 0.5, 0.7):
    s = C.caught((1 - w) * rb + w * rh); print(f"rank blend w_hist={w}", C.ci(s), "vs base", C.diff(s, base))
