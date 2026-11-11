import sys, numpy as np, pandas as pd
W = sys.argv[1]; ROWS = sys.argv[2]
src = open("/home/user/UserSim/experiments/simlab/two_level_baseline.py").read().split("report = {")[0]
sys.argv = ["x", W]; g = {"__name__": "tlb"}; exec(compile(src, "tlb", "exec"), g)
R = pd.read_parquet(ROWS); lid = g["lid"]; R["li"] = R.launch_id.map(lid)
print("rows", len(R), "launch matched", R.li.notna().mean(), flush=True)
out = []
for name, tr0, tr1, te0, te1 in g["FOLDS"]:
    days_all = set(g["Lday"])
    tr_days = [str(x.date()) for x in pd.date_range(tr0, tr1) if str(x.date()) in days_all]
    Xtr, Ytr, wtr = g["build"](tr_days, sorted(g["comp"]), False, True)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(C=1.0, max_iter=2000).fit((Xtr - mu) / sd, Ytr, sample_weight=wtr)
    sub = R[(R.d >= te0) & (R.d <= te1)]
    for (p, d), x in sub.groupby(["person_id", "d"]):
        r = g["day_rows"](p, d, False)
        if r is None:   # not active in my 60-day sense (no dated history): score with zero history
            idx = np.where(g["Lday"] == d)[0]; feats = np.zeros((len(idx), len(g["FEATS"])), np.float32)
        else:
            idx, feats = r
        ph = dict(zip(idx, clf.predict_proba((feats - mu) / sd)[:, 1]))
        out.append(pd.DataFrame({"i": x.index, "p_e5": x.li.map(ph).to_numpy()}))
    print(name, "scored", flush=True)
S = pd.concat(out).set_index("i"); R["p_e5"] = S.p_e5
R.to_parquet(W + "/out/their_rows_scored.parquet")
def rprec(df, score):
    v = []
    for _, x in df.groupby(["d", "launch_id"]):
        n = int(x.y.sum())
        if n: v.append(x.nlargest(n, score).y.sum() / n)
    return np.mean(v), v
from sklearn.metrics import roc_auc_score
R = R.dropna(subset=["p_e5"]); R["wp"] = R.w * R.p_e5
for lab, s in (("P", "p_e5"), ("w*P", "wp")):
    m, _ = rprec(R, s); print(f"E5 baseline on PH rows: R-precision by {lab}: {m:.4f}")
print("AUC", roc_auc_score(R.y, R.p_e5))
for part, x in (("Oct clean", R[R.d < "2026-11"]), ("Nov clean", R[R.d >= "2026-11"])):
    print(part, "R-prec(w*P)", round(rprec(x, "wp")[0], 4), "R-prec(P)", round(rprec(x, "p_e5")[0], 4))
