import os, sys
sys.path.insert(0, "/home/user/UserSim/experiments/hn_sim"); os.chdir("/home/user/UserSim/experiments/hn_sim")
import numpy as np, pandas as pd
import caught as C, top100 as H
rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
T = C.Q[C.te][["post_id"]].reset_index(drop=True)
base = C.model(C.POST + C.KNN + C.EMB + C.CROWD)
h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
sc = {p: T.post_id.map(pd.read_parquet(os.path.join(H.CACHE, f"content_scores_{p}aug30.parquet")).drop_duplicates("post_id").set_index("post_id").s).fillna(-99).to_numpy()
      for p in ("", "author_", "large_")}
c = {p: C.caught((rk(base) + rk(h) + rk(v)) / 3) for p, v in sc.items()}
print("3-way at posting: base", C.ci(c[""]), "| author", C.ci(c["author_"]), "| large", C.ci(c["large_"]))
print("author vs base content (paired):", C.diff(c["author_"], c[""]), " pairwise", C.pairwise((rk(base)+rk(h)+rk(sc["author_"]))/3, (rk(base)+rk(h)+rk(sc[""]))/3))
print("large vs base content (paired):", C.diff(c["large_"], c[""]))
