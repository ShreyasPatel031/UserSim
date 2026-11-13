"""Displayed votes vs distinct store upvoters (orchestrator 11:54Z Nov 13). No LLM; counts only.
Store = official raw/population/store_v3 (all upvote rows, any person). Displayed votes = warehouse launches.votes (latest read; the
official rank orders by it). Launch set: ranked launches Oct 1 - Nov 10.
(1) R = displayed / distinct store upvoters, by final rank, month and size; how many launches have store upvoters > displayed.
(2) Voter cells (traits from the person's own tabs, complete people only): upvotes-tab header bucket (<10, 10-99, 100-999, 1000+) x
    burst (>= 50% of the person's dated upvotes on one launch day) x has followers (followers header > 0); plus one cell for upvoters
    who are not complete (no traits). No account-age field exists in the store. Non-negative least squares displayed_L = sum_k w_k n_k(L)
    on NEAR-COMPLETE launches (store upvoters >= 0.9 x displayed: stated selection), 5-fold CV by launch; vs one constant weight.
    Timing alternative: vote_snapshots' last read of the launch day vs the latest displayed count (Oct 31 - Nov 12).
(3) Share of zero-weight-cell upvoters on top-3 launches; within-day partial correlation of that share with final rank beyond clean.
(4) Weighted coverage = sum of fitted weights of COMPLETE upvoters / displayed, seeded week (Oct 29 - Nov 4) and Oct 1 - 24.
    python vote_weight.py <store dir> <scratchpad> <out dir>
"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.optimize import nnls
ST, SP, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str); W = W.sort_values("updated_at").drop_duplicates("id", keep="last")
W = W[W.daily_rank.notna() & (W.day >= "2026-10-01") & (W.day <= "2026-11-10")].copy(); W["votes"] = pd.to_numeric(W.votes, errors="coerce").astype(float); W["rank"] = W.daily_rank.astype(float)
P = pd.read_parquet(os.path.join(ST, "persons.parquet")); C = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(ST, "events.parquet"), columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy(); U["target_id"] = U.target_id.astype(str)
T = pd.read_parquet(os.path.join(ST, "tabs.parquet")); hd = T.pivot_table(index="person_id", columns="tab", values="header", aggfunc="first")
for c in ("upvotes", "followers"): hd[c] = pd.to_numeric(hd.get(c), errors="coerce")
WL = warehouse.table("launches", do_sync=False); WL["id"] = WL.id.astype(str); lday = dict(zip(WL.id, WL.day))
Uc = U[U.person_id.isin(C)].copy(); Uc["d"] = Uc.target_id.map(lday); burst = Uc[Uc.d.notna()].groupby("person_id").d.agg(lambda s: s.value_counts(normalize=True).iloc[0] if len(s) else 0)
def cell(p):
    if p not in C: return "not complete"
    u = hd.upvotes.get(p, np.nan); f = hd.followers.get(p, np.nan)
    ub = "<10" if not u == u or u < 10 else ("10-99" if u < 100 else ("100-999" if u < 1000 else "1000+"))
    return f"up {ub} | {'burst' if burst.get(p, 0) >= 0.5 else 'spread'} | {'followers' if f == f and f > 0 else 'no followers'}"
U = U[U.target_id.isin(set(W.id))]; U["cell"] = [cell(p) for p in U.person_id]
N = U.groupby(["target_id", "cell"]).size().unstack(fill_value=0); W = W.set_index("id"); W["store_up"] = N.sum(1).reindex(W.index).fillna(0); W = W[W.store_up > 0]
W["R"] = W.votes / W.store_up; W["over"] = W.store_up > W.votes; W["rb"] = pd.cut(W["rank"], [0, 3, 10, 1000], labels=["1-3", "4-10", "11+"]); W["mon"] = W.day.str[:7]
W["size"] = pd.qcut(W.votes, 4, labels=["Q1 small", "Q2", "Q3", "Q4 large"])
res = {"design": __doc__.split("\n    python")[0], "launches": len(W),
       "(1) displayed / store upvoters": {"median R": round(float(W.R.median()), 3), "launches with store upvoters > displayed": int(W.over.sum()),
           "by final rank (median R, n over / n)": {str(k): [round(float(g.R.median()), 3), int(g.over.sum()), len(g)] for k, g in W.groupby("rb", observed=True)},
           "by month": {k: [round(float(g.R.median()), 3), int(g.over.sum()), len(g)] for k, g in W.groupby("mon")},
           "by displayed-votes quartile": {str(k): [round(float(g.R.median()), 3), int(g.over.sum()), len(g)] for k, g in W.groupby("size", observed=True)}}}
# (2) NNLS on near-complete launches
S = W[W.store_up >= 0.9 * W.votes]; cells = list(N.columns); X = N.reindex(S.index)[cells].fillna(0).to_numpy(float); y = S.votes.to_numpy()
w_all, _ = nnls(X, y); folds = rng.integers(0, 5, len(S)); pred = np.zeros(len(S)); predc = np.zeros(len(S))
for k in range(5):
    tr, te = folds != k, folds == k; w_, _ = nnls(X[tr], y[tr]); pred[te] = X[te] @ w_; c_ = y[tr].sum() / X[tr].sum(); predc[te] = X[te].sum(1) * c_
r2 = lambda p: 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum(); mape = lambda p: float(np.median(np.abs(p - y) / y))
share = N.reindex(S.index)[cells].sum() / N.reindex(S.index)[cells].sum().sum()
res["(2) weights (NNLS, near-complete launches)"] = {"selection": f"store upvoters >= 0.9 x displayed: {len(S)} launches", "weights": {c: [round(float(w), 3), round(float(share[c]), 3)] for c, w in zip(cells, w_all)},
    "cv R2 cells / constant": [round(r2(pred), 3), round(r2(predc), 3)], "cv median abs % error cells / constant": [round(mape(pred), 3), round(mape(predc), 3)], "note": "weights: [w, share of upvoters]"}
# timing alternative
V = warehouse.table("vote_snapshots", do_sync=False); V["at"] = pd.to_datetime(V["at"], utc=True).dt.tz_convert(PT); V["launch_id"] = V.launch_id.astype(str); tm = []
for d, g in V.groupby("day"):
    end = pd.Timestamp(d).tz_localize(PT) + pd.Timedelta(days=1); g2 = g[(g["at"] < end) & g.votes.notna() & (g.votes > 0)]
    if g2.empty: continue
    last = g2[g2["at"] == g2["at"].max()]
    for i, v in zip(last.launch_id, last.votes):
        if i in WL.set_index("id").index: tm.append((d, float(v), float(pd.to_numeric(WL.set_index("id").votes.get(i), errors="coerce"))))
TM = pd.DataFrame(tm, columns=["day", "dayend", "now"]); TM = TM[TM.dayend > 0]
res["timing check (last read before day end vs latest)"] = {"launches": len(TM), "median now/dayend": round(float((TM.now / TM.dayend).median()), 3), "share now < dayend": round(float((TM.now < TM.dayend).mean()), 3), "share now > dayend * 1.1": round(float((TM.now > TM.dayend * 1.1).mean()), 3)}
# (3) zero-weight cells
zc = [c for c, w in zip(cells, w_all) if w < 0.2]; W["zero_share"] = N.reindex(W.index)[zc].sum(1) / W.store_up if zc else 0.0
H = pd.read_parquet(os.path.join(SP, "honest_preds_v2.parquet"))[["id", "honest"]]; H["id"] = H.id.astype(str); Wh = W.reset_index().merge(H, on="id")
rk = lambda a: pd.Series(a).rank().to_numpy()
def partial(yv, b, x):
    yv, b, x = rk(yv), rk(b), rk(x); return float(np.corrcoef(yv - np.polyval(np.polyfit(b, yv, 1), b), x - np.polyval(np.polyfit(b, x, 1), b))[0, 1])
pc = np.array([partial(-g["rank"].to_numpy(), g.honest.to_numpy(), -g.zero_share.to_numpy()) for _, g in Wh.groupby("day") if len(g) >= 8 and g.zero_share.nunique() > 1]); pc = pc[pc == pc]
bs = [pc[rng.integers(0, len(pc), len(pc))].mean() for _ in range(2000)] if len(pc) else [np.nan]
res["(3) zero-weight cells (w < 0.2)"] = {"cells": zc, "share of listed upvoters on top-3 launches (median)": round(float(W[W["rank"] <= 3].zero_share.median()), 3) if zc else 0,
    "partial of (-zero share) with rank beyond clean": [round(float(np.mean(pc)), 3) if len(pc) else None, round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(pc)]}
# (4) weighted coverage of complete upvoters
wc = dict(zip(cells, w_all)); Nc = N.reindex(W.index).fillna(0); comp_cells = [c for c in cells if c != "not complete"]
W["wexp"] = (Nc[comp_cells] * np.array([wc[c] for c in comp_cells])).sum(1); W["raw_c"] = Nc[comp_cells].sum(1)
for nm, a, b in (("seeded week Oct 29 - Nov 4", "2026-10-29", "2026-11-04"), ("Oct 1 - 24", "2026-10-01", "2026-10-24")):
    g = W[(W.day >= a) & (W.day <= b)]; t3 = g["rank"] <= 3
    res.setdefault("(4) coverage of displayed votes by complete people", {})[nm] = {"raw all / top3": [round(float(g.raw_c.sum() / g.votes.sum()), 3), round(float(g[t3].raw_c.sum() / g[t3].votes.sum()), 3)],
        "weighted all / top3": [round(float(g.wexp.sum() / g.votes.sum()), 3), round(float(g[t3].wexp.sum() / g[t3].votes.sum()), 3)]}
json.dump(res, open(os.path.join(OUT, "vote_weight.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float, indent=0)[:5000])
