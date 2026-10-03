"""Section 2.5 between-cluster share vs predefined label groups, on each target's local neighbour matrix.

Share = between-group sum of squares / total, over cells x per-option answer columns of the target's neighbour
questions (never the target). Discovered groups = k-means with the SAME number of groups as the label partition, on
the SAME cells; null = k-means on the matrix with every column shuffled across cells. Cell-level, so not the same
construct as the earlier respondent-level 1.4% within/between split."""

from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
from sklearn.cluster import KMeans

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

MIN_OBS_COLS = 2  # a cell must have answered >= 2 neighbour questions to count


def share(Z, labels):
    mu = Z.mean(0)
    sst = ((Z - mu) ** 2).sum()
    ssb = sum((labels == g).sum() * ((Z[labels == g].mean(0) - mu) ** 2).sum() for g in np.unique(labels))
    return float(ssb / sst) if sst > 0 else np.nan


def kshare(Z, k, seed=0):
    k = max(2, min(k, len(Z) - 1))
    return share(Z, KMeans(n_clusters=k, n_init=5, random_state=seed).fit_predict(Z))


def ci(d):
    d = np.asarray([x for x in d if np.isfinite(x)], float)
    if len(d) < 3:
        return (None, None)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 3), round(float(b[1949]), 3)


def main(K=19):
    held = L.held_rows()
    sv_all = L.build_surveys(held)
    F = L.Fitter(sv_all)
    rng = np.random.default_rng(0)
    seen, out = set(), defaultdict(lambda: defaultdict(list))
    for which in ("dev", "eval"):
        for t in L.targets(which):
            if t["split"] != "Grouped":
                continue
            ds = t["q"]["dataset"]
            key = (ds, t["stem"])
            if key in seen:
                continue
            seen.add(key)
            f = F.get(ds, t["text"], t["stem"], K, "raw", 0)
            if f is None:
                continue
            X, rows, cols = f["X"], f["rows"], f["cols"]
            nobs = np.array([sum(not np.isnan(X[i, sl.start]) for sl in cols.values()) for i in range(len(rows))])
            keep = nobs >= MIN_OBS_COLS
            if keep.sum() < 10:
                continue
            Xk = X[keep]
            mu = np.nanmean(Xk, 0)
            Z = np.where(np.isnan(Xk), np.where(np.isnan(mu), 0, mu), Xk)
            rk = [rows[i] for i in np.where(keep)[0]]
            countries = np.array([c[1] for c in rk])
            if len(set(countries)) > 1:
                kc = len(set(countries))
                out[ds]["label: country"].append(share(Z, countries))
                out[ds]["clusters, k = #countries"].append(kshare(Z, kc))
            by_attr = defaultdict(list)
            for i, c in enumerate(rk):
                if c[2]:
                    by_attr[c[2][0][0]].append(i)
            best_lab, best_cl, best_null = np.nan, np.nan, np.nan
            for a, idx in by_attr.items():
                vals = np.array([rk[i][2][0][1] for i in idx])
                if len(idx) < 10 or len(set(vals)) < 2:
                    continue
                Za = Z[idx]
                lab = share(Za, vals)
                cl = kshare(Za, len(set(vals)))
                Zp = np.column_stack([rng.permutation(Za[:, j]) for j in range(Za.shape[1])])
                nl = kshare(Zp, len(set(vals)))
                out[ds][f"label: {a}"].append(lab)
                if not np.isfinite(best_lab) or lab > best_lab:
                    best_lab, best_cl, best_null = lab, cl, nl
            if np.isfinite(best_lab):
                out[ds]["best single attribute (label)"].append(best_lab)
                out[ds]["clusters, same k and cells as best attribute"].append(best_cl)
                out[ds]["null: clusters on shuffled columns"].append(best_null)
    rep = {}
    print("between-group share of cell-level variance on the target's neighbour questions (mean over target questions, 95% CI)")
    for ds, d in out.items():
        rep[ds] = {}
        print(f"-- {ds}")
        for name in ("best single attribute (label)", "clusters, same k and cells as best attribute", "null: clusters on shuffled columns",
                     "label: country", "clusters, k = #countries"):
            if d.get(name):
                rep[ds][name] = {"N_questions": len(d[name]), "mean": float(np.nanmean(d[name])), "ci": ci(d[name])}
                print(f"   {name:48s} N {len(d[name]):3d}  {np.nanmean(d[name]):.3f} {ci(d[name])}")
        rep[ds]["per_attribute_label_share"] = {k[7:]: float(np.nanmean(v)) for k, v in d.items() if k.startswith("label: ") and k != "label: country"}
    (M.OUT / "structure_between_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
