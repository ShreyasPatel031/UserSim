"""One scorer for launch-level predictions (any newsim_eval SAVE=1 parquet, or anything with id, day, logv, dailyRank and
prediction columns). Metrics, each with a paired, day-clustered bootstrap of B - A (10,000 resamples, 95% interval):
  top 3 / 5 / 10   share of the real daily top k in the predicted top k (days whose real top k is complete)
  pairwise         within-day accuracy over all pairs of launches with different votes
  competitor pairs launch x vs each competitor launch c on Product Hunt's Similar Products list (ph_comp_lists.py, safe
                   lists only, c at least 2 days before x): is the one with more votes predicted higher? (both must be
                   in the file; scores are log-vote predictions, so pairs across days are comparable); clustered on x's day
  winner of 3      comp_test.py's groups (rebuilt here; the random draws match comp_test only on the same launches) (same day / week / month, sharing a specific topic), clustered on the anchor's day
usage: python pair_score.py A.parquet:colA B.parquet:colB [more file:col ...]   (first one is the reference)"""
import json, sys
import numpy as np, pandas as pd

B_N = 10000


def per_day_topk(T, c, k):
    return {d: len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.dailyRank <= k).sum() == k}


def per_day_pairs(T, c):
    out = {}
    for d, g in T.groupby("day"):
        v, p = g.logv.values, g[c].values
        i, j = np.triu_indices(len(g), 1); m = v[i] != v[j]
        if m.any():
            ok = (np.sign(p[i] - p[j]) == np.sign(v[i] - v[j]))[m]
            out[d] = (ok.sum(), m.sum())
    return out


def comp_pairs(T, c, lists):
    val = dict(zip(T.id, T[c])); lv = dict(zip(T.id, T.logv)); day = dict(zip(T.id, T.day)); out = {}
    for x, r in lists.items():
        if x not in val or not r["safe"]:
            continue
        for y in r["ids"]:
            if y in val and lv[x] != lv[y]:
                s, n = out.get(day[x], (0, 0))
                out[day[x]] = (s + int(np.sign(val[x] - val[y]) == np.sign(lv[x] - lv[y])), n + 1)
    return out


def winner3_groups(T, cols):
    """comp_test.py's groups of 3 -> {window: {col: {day: (correct, n)}}} (day = the anchor launch's day)."""
    import glob
    from collections import Counter
    tops = {}
    for f in glob.glob("data/days/*.json"):
        for p in json.load(open(f)):
            t = p.get("topics") or []
            tops[str(p["id"])] = [e["node"]["name"] for e in t.get("edges", [])] if isinstance(t, dict) else [x["name"] if isinstance(x, dict) else x for x in t]
    T = T.copy(); T["topics"] = T.id.map(lambda i: tops.get(i, []))
    freq = Counter(t for ts in T.topics for t in ts); generic = {t for t, _ in freq.most_common(6)}
    T["spec"] = T.topics.map(lambda ts: [t for t in ts if t not in generic])
    T["week"] = pd.to_datetime(T.day).dt.strftime("%G-W%V"); T["mon"] = T.day.str[:7]
    rng = np.random.default_rng(0); out = {}
    for win in ("day", "week", "mon"):
        acc = {c: {} for c in cols}
        for _, g in T.groupby(win):
            g = g.reset_index(drop=True); bytopic = {}
            for i, ts in enumerate(g.spec):
                for t in ts:
                    bytopic.setdefault(t, []).append(i)
            for i in range(len(g)):
                comp = sorted({j for t in g.spec[i] for j in bytopic[t] if j != i})
                if len(comp) < 2:
                    continue
                js = list(rng.choice(comp, 2, replace=False)); grp = g.loc[[i] + js]
                if grp.logv.nunique() < 3:
                    continue
                d = g.loc[i, "day"]
                for c in cols:
                    s0, n0 = acc[c].get(d, (0, 0)); acc[c][d] = (s0 + int(grp[c].idxmax() == grp.logv.idxmax()), n0 + 1)
        out[win] = acc
    return out


def boot_ratio(a, b, rng):
    """a, b: {day: (successes, n)} on the same items -> B - A with a day-clustered interval."""
    days = sorted(set(a) & set(b))
    sa = np.array([a[d][0] for d in days], float); sb = np.array([b[d][0] for d in days], float); n = np.array([a[d][1] for d in days], float)
    est = (sb.sum() - sa.sum()) / n.sum(); bs = []
    for _ in range(B_N):
        k = rng.integers(0, len(days), len(days)); bs.append((sb[k].sum() - sa[k].sum()) / n[k].sum())
    return sa.sum() / n.sum(), sb.sum() / n.sum(), est, np.percentile(bs, [2.5, 97.5]), len(days)


def boot_mean(a, b, rng):
    days = sorted(set(a) & set(b)); d = np.array([b[x] - a[x] for x in days])
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(B_N)]
    return np.mean([a[x] for x in days]), np.mean([b[x] for x in days]), d.mean(), np.percentile(bs, [2.5, 97.5]), len(days)


def main(specs):
    lists = json.load(open("data/ph_comp_lists.json"))
    cols, T = [], None
    for k, s in enumerate(specs):
        f, c = s.rsplit(":", 1); X = pd.read_parquet(f); X["id"] = X.id.astype(str); name = f"m{k}"
        X = X[["id", "day", "logv", "dailyRank", c]].rename(columns={c: name})
        T = X if T is None else T.merge(X[["id", name]], on="id")
        cols.append(name)
    print(f"launches {len(T)}, days {T.day.nunique()}, {T.day.min()} to {T.day.max()}; reference = {specs[0]}")
    rng = np.random.default_rng(0); res = {}
    metrics = [(f"top {k}", (lambda c, k=k: {d: (v * k, k) for d, v in per_day_topk(T, c, k).items()})) for k in (3, 5, 10)]
    metrics += [("pairwise", lambda c: per_day_pairs(T, c)), ("competitor pairs", lambda c: comp_pairs(T, c, lists))]
    for mname, fn in metrics:
        ref = fn(cols[0]); line = {}
        for spec, c in zip(specs, cols):
            cur = fn(c)
            A, B, d, ci, nd = boot_ratio(ref, cur, rng)
            line[spec] = {"value": round(100 * B, 1), "vs_ref": round(100 * d, 1), "ci": [round(100 * x, 1) for x in ci], "days": nd,
                          "items": int(sum(cur[x][1] for x in cur))}
        res[mname] = line
    W3 = winner3_groups(T, cols)
    for win, acc in W3.items():
        line = {}
        for spec, c in zip(specs, cols):
            A, B, d, ci, nd = boot_ratio(acc[cols[0]], acc[c], rng)
            line[spec] = {"value": round(100 * B, 1), "vs_ref": round(100 * d, 1), "ci": [round(100 * x, 1) for x in ci], "days": nd,
                          "items": int(sum(v[1] for v in acc[c].values()))}
        res[f"winner of 3 ({win})"] = line
    for m, line in res.items():
        print(m)
        for s, v in line.items():
            print("  ", s, v)
    return res


if __name__ == "__main__":
    main(sys.argv[1:])
