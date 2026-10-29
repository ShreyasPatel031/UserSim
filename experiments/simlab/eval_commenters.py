"""Who will comment: for each launch, rank every active person by the person model's chance they engage (popscore
rows: model trained on the previous month, inputs dated before the day) and check where the real commenters land.
Baselines: the most active people first (activity weight), and random order.
usage: python -m simlab.eval_commenters -> reports/eval_commenters.json"""
import glob, json, os
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from pipeline import warehouse as W

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    con = W.connect()
    E = con.execute("SELECT DISTINCT person, launch_id FROM events WHERE kind = 'comment'").df()
    com = set(zip(E.person, E.launch_id))
    rng = np.random.default_rng(0)
    res = {k: [] for k in ("model", "activity", "model_x_activity", "random")}; auc = {k: [] for k in ("model", "activity", "model_x_activity")}
    n_launch = n_com = 0
    for f in sorted(glob.glob(f"{HERE}/cache/popscore/rows/*.parquet")):
        D = pd.read_parquet(f, columns=["person", "id", "p", "w"])
        D["id"] = D.id.astype(str)
        D["y"] = [(u, x) in com for u, x in zip(D.person, D.id)]
        for x, g in D.groupby("id"):
            k = int(g.y.sum())
            if k == 0 or len(g) < 200:
                continue
            n_launch += 1; n_com += k
            for name, s in (("model", g.p.values), ("activity", g.w.values), ("model_x_activity", g.p.values * g.w.values), ("random", rng.random(len(g)))):
                top = np.argsort(-s)[:100]
                res[name].append(g.y.values[top].sum() / k)
            auc["model"].append(roc_auc_score(g.y, g.p)); auc["activity"].append(roc_auc_score(g.y, g.w)); auc["model_x_activity"].append(roc_auc_score(g.y, g.p * g.w))
    out = {"launches": n_launch, "known_commenters": n_com,
           "share_of_real_commenters_in_top100": {k: round(float(np.mean(v)), 3) for k, v in res.items()},
           "auc": {k: round(float(np.mean(v)), 3) for k, v in auc.items()}}
    json.dump(out, open(f"{HERE}/reports/eval_commenters.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
