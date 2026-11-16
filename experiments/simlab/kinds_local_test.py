"""(1) Are 'Mac & Productivity Apps' and 'Coding & Mac Productivity' really different? (2) Per-product (local) groups vs the shared groups:
on past launches, does grouping the launch's market (people who voted for any of its 30 most similar EARLIER launches) locally predict who
in that market votes for the launch better than the shared parents / subgroups?  2-fold CV within each launch's market: group vote rate from
fold A predicts fold B; Brier skill vs fold A's overall rate. (3) The 'ours not theirs' score d = taste . (z_launch - mean z_competitors),
with the launch removed from each person's taste: within-market AUC for who really voted, vs plain similarity taste . z_launch."""
import json, sys, numpy as np, pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import roc_auc_score
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0)
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id")
PU = pd.read_parquet(f"{OUT}/people_units2.parquet").set_index("person_id"); G = json.load(open(f"{OUT}/regroup.json")); SN = {s["id"]: s["name"] for s in G["subgroups"]}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str); li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day)); U = U[U.target_id.isin(set(L.id[L.day < "2026-11-13"])) & U.person_id.isin(set(P.index))].reset_index(drop=True)
pid = {p: i for i, p in enumerate(P.index)}; U["pi"] = U.person_id.map(pid); U["li"] = U.target_id.map(li)
S = np.zeros((len(P), X.shape[1]), np.float32); np.add.at(S, U.pi.values, X[U.li.values]); N = np.bincount(U.pi.values, minlength=len(P)).astype(np.float32)
mu = (S / N[:, None]).mean(0)
voters = {k: np.unique(v) for k, v in U.groupby("target_id").pi.apply(list).items()}; nv = {k: len(v) for k, v in voters.items()}
big = [l for l in L.id if nv.get(l, 0) >= 30]; XB = X[[li[l] for l in big]]; dB = np.array([day[l] for l in big])
sub = PU.reindex(P.index)["sub"].values; par = PU.reindex(P.index)["parent"].values
# ---- (1) the two subgroups
names = {v: k for k, v in SN.items()}; a, b = names["Mac & Productivity Apps"], names["Coding & Mac Productivity"]
ct = pd.crosstab(U.target_id, U.pi.map(lambda i: sub[i])); ct = ct[ct.sum(1) >= 30]; base = ct.sum(0) / ct.values.sum(); lift = (ct.div(ct.sum(1), axis=0) / base)
cen = np.array([(S[sub == s] / N[sub == s, None]).mean(0) - mu for s in range(len(SN))]); cen /= np.linalg.norm(cen, axis=1, keepdims=True)
cc = cen @ cen.T; np.fill_diagonal(cc, -1)
Q1 = {"lift correlation across launches (a vs b)": round(float(np.corrcoef(lift[a], lift[b])[0, 1]), 2),
      "median lift correlation, all subgroup pairs": round(float(np.median(np.corrcoef(lift.T.values)[np.triu_indices(len(SN), 1)])), 2),
      "taste-centroid cosine (a vs b)": round(float(cc[a, b]), 2), "nearest subgroup to a": SN[int(cc[a].argmax())], "nearest subgroup to b": SN[int(cc[b].argmax())],
      "launches where one is >= 1.5x and the other <= 0.8x": int(((lift[a] >= 1.5) & (lift[b] <= 0.8)).sum() + ((lift[b] >= 1.5) & (lift[a] <= 0.8)).sum()), "launches": int(len(lift)),
      "examples a high, b low": [L.name[li[t]] for t in lift[(lift[a] >= 1.8) & (lift[b] <= 0.8)].sort_values(a, ascending=False).index[:6]],
      "examples b high, a low": [L.name[li[t]] for t in lift[(lift[b] >= 1.8) & (lift[a] <= 0.8)].sort_values(b, ascending=False).index[:6]]}
print(json.dumps(Q1, indent=1), flush=True)
# ---- (2)+(3) past launches
tests = [l for l in big if "2026-09-01" <= day[l] < "2026-11-13"]; tests = list(rng.choice(tests, min(300, len(tests)), replace=False)); R = []
def brier_skill(g, y, fold):
    A, Bm = fold == 0, fold == 1; r0 = y[A].mean(); rates = pd.Series(y[A]).groupby(g[A]).agg(["sum", "count"])
    rg = ((rates["sum"] + 5 * r0) / (rates["count"] + 5)).reindex(np.unique(g)).fillna(r0)   # shrunk group rates
    p = rg.reindex(g[Bm]).fillna(r0).values; return 1 - np.mean((p - y[Bm]) ** 2) / np.mean((r0 - y[Bm]) ** 2)
for l in tests:
    j = li[l]; ok = dB < day[l]; s = XB[ok] @ X[j]; cm = [c for c, o in zip(big, ok) if o]; comp = [cm[k] for k in np.argsort(-s)[:30]]
    mk = np.unique(np.concatenate([voters[c] for c in comp])); y = np.isin(mk, voters.get(l, [])).astype(float)
    if y.sum() < 10 or len(mk) < 200: continue
    t = S[mk].copy(); n = N[mk].copy(); t[y == 1] -= X[j]; n[y == 1] -= 1; keep = n > 0; mk, y, t, n = mk[keep], y[keep], t[keep], n[keep]
    t = t / n[:, None] - mu; t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-9
    zc = X[[li[c] for c in comp]].mean(0); d = t @ (X[j] - zc); sim = t @ X[j]
    fold = rng.integers(0, 2, len(mk)); r = {"launch": l, "market": len(mk), "voters_in_market": int(y.sum()), "auc_d": roc_auc_score(y, d), "auc_sim": roc_auc_score(y, sim)}
    q = np.quantile(d, [0.15, 0.85]); r["rate_top15_d"] = float(y[d >= q[1]].mean()); r["rate_bottom15_d"] = float(y[d <= q[0]].mean()); r["rate_market"] = float(y.mean())
    for nm, g in (("shared parents (3)", par[mk]), ("shared subgroups (16)", sub[mk])): r[nm] = brier_skill(g, y, fold)
    for k in (3, 6, 16):
        g = KMeans(k, random_state=0, n_init=3).fit_predict(t); r[f"local k={k}"] = brier_skill(g, y, fold)
    g = np.digitize(d, np.quantile(d, [1 / 3, 2 / 3])); r["local: 3 bands of d"] = brier_skill(g, y, fold)
    R.append(r)
T = pd.DataFrame(R)
def ci(v): v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(3000)]; return [round(float(v.mean()), 4), round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]
cols = ["shared parents (3)", "shared subgroups (16)", "local k=3", "local k=6", "local k=16", "local: 3 bands of d"]
out = {"Q1": Q1, "launches": len(T), "median market size": float(T.market.median()), "median voters in market": float(T.voters_in_market.median()),
       "within-market AUC: d (ours-not-theirs)": ci(T.auc_d), "within-market AUC: plain similarity": ci(T.auc_sim), "d minus similarity (paired)": ci(T.auc_d - T.auc_sim),
       "vote rate: top 15% d / market / bottom 15% d": [ci(T.rate_top15_d), ci(T.rate_market), ci(T.rate_bottom15_d)],
       "Brier skill vs market rate (2-fold CV, higher is better)": {c: ci(T[c]) for c in cols},
       "paired vs shared subgroups (16)": {c: ci(T[c] - T["shared subgroups (16)"]) for c in cols if c != "shared subgroups (16)"}}
json.dump(out, open(f"{OUT}/local_test.json", "w"), indent=1); print(json.dumps({k: v for k, v in out.items() if k != "Q1"}, indent=1))
