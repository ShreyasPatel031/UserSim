"""Experiment C pilot (orchestrator Nov 11): do product-only taste signals separate "uses it" from "only upvoted it"?
Labels from store_v3 (complete people): stack / review / collection events on products that match a launch we hold
product info for (product slug = launch slug without a trailing -<n>; 87 / 135 / 836 products). For each person with
>= 1 such positive, candidates = the positive launch(es) + launches the person upvoted (in our launch set) but did not
stack / review / collect. Scores (no PH context, no outcomes of the candidates):
  centroid   cosine of the launch's cleaned description embedding vs the person's upvote-history centroid, the
             candidate itself left out
  attr_lift  sum of the person's log lift over the launch's it9b attributes (attr_feats prefs on all their upvotes
             except the candidate; base = global attribute rates)
Per person AUC (positives vs negatives), averaged; random = 0.5; day-free, so a person bootstrap CI.
Caveat: stacks / collections are undated snapshots, so this is not a forecast; it asks whether the signal exists.
usage: SIMBT=<dir> python c_pilot_uses.py -> results/c_pilot_uses.json"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"


def main():
    from attr_feats import AttrFeats, BIN
    AF = AttrFeats(WORK); A = AF.A
    I = pd.read_parquet(f"{WORK}/items.parquet"); I["id"] = I.id.astype(str)
    I["ps"] = I.slug.str.replace(r"-\d+$", "", regex=True)
    slug2id = {}
    for r in I.sort_values("day").itertuples():   # the earliest launch of a product slug
        slug2id.setdefault(r.ps, r.id); slug2id.setdefault(r.slug, r.id)
    tmp = tempfile.mkdtemp()
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/population/store_v3/events.parquet", tmp], check=True)
    V = pd.read_parquet(f"{tmp}/events.parquet", columns=["person_id", "kind", "target_id"])
    comp = set(pd.read_parquet(f"{WORK}/events_cp.parquet", columns=["person"]).person)
    U = V[(V.kind == "upvote") & V.person_id.isin(comp)].assign(id=lambda x: x.target_id.astype(str))
    U = U[U.id.isin(A.index)][["person_id", "id"]].drop_duplicates()
    Z = np.load(f"{WORK}/product_attrs/emb_fields.npz"); ix = {str(i): k for k, i in enumerate(Z["ids"])}; Dv = Z["desc"]
    gbase = A[BIN].mean().values
    ups_by = U.groupby("person_id").id.apply(list).to_dict()
    res = {"note": "pilot; undated stacks/collections; positives vs upvoted-not-used negatives; person bootstrap"}
    rng = np.random.default_rng(0)
    for kind in ("stack", "review", "collection"):
        P = V[(V.kind == kind) & V.person_id.isin(comp)].copy()
        P["id"] = P.target_id.str.replace("product:", "", regex=False).map(slug2id)
        P = P.dropna(subset=["id"])[["person_id", "id"]].drop_duplicates()
        aucs = {"centroid": [], "attr_lift": []}; npos = 0
        for p, pos in P.groupby("person_id"):
            ups = ups_by.get(p, [])
            neg = sorted(set(ups) - set(pos.id))
            cand = sorted(set(pos.id) | set(neg))
            if len(neg) < 3 or not len(pos):
                continue
            y = np.array([c in set(pos.id) for c in cand], float); npos += int(y.sum())
            hist = [c for c in ups if c in ix]
            sc_c, sc_a = [], []
            for c in cand:
                h = [ix[x] for x in hist if x != c]
                if c in ix and h:
                    cen = Dv[h].mean(0); v = Dv[ix[c]]
                    sc_c.append(float(v @ cen / (np.linalg.norm(cen) + 1e-9)))
                else:
                    sc_c.append(np.nan)
                hh = [x for x in ups if x != c and x in A.index]
                if hh and c in A.index:
                    sh = (A.loc[hh, BIN].values.sum(0) + 5 * gbase) / (len(hh) + 5)
                    lift = np.log((sh + 1e-3) / (gbase + 1e-3))
                    sc_a.append(float((A.loc[c, BIN].values * lift).sum()))
                else:
                    sc_a.append(np.nan)
            for nm, sc in (("centroid", sc_c), ("attr_lift", sc_a)):
                s = np.array(sc, float); k = ~np.isnan(s)
                if k.sum() >= 4 and 0 < y[k].sum() < k.sum():
                    aucs[nm].append(roc_auc_score(y[k], s[k]))
        out = {"products_matched": int(P.id.nunique()), "persons": int(P.person_id.nunique()), "positives_scored": npos}
        for nm, a in aucs.items():
            a = np.array(a)
            if len(a) > 1:
                b = [a[rng.integers(0, len(a), len(a))].mean() for _ in range(5000)]
                out[nm] = [round(float(a.mean()), 3), [round(float(x), 3) for x in np.percentile(b, [2.5, 97.5])], int(len(a))]
            else:
                out[nm] = [None, None, int(len(a))]
        res[kind] = out
    json.dump(res, open(os.path.join(HERE, "results", "c_pilot_uses.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
