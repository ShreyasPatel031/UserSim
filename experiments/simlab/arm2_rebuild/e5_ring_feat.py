"""Does "ring votes received before launch" help or hurt arm 2? (orchestrator 00:51Z Nov 15, item 3). 2026 test months 2026-04..10,
month-forward, same harness as e5_makers0 / e5_faithful (deployed columns, TW.P0, 5 seeds, rows sorted by (day, id), train from 2025-01-01).
Features per launch (team = hunter_id and first maker id; earlier = launches of the team dated before the launch's day):
  ring_share = flagged people among held voters of the team's earlier launches / held voters of those launches
  ring_n     = ln(1 + flagged held voters of the team's earlier launches)
  flags      = ringlib.dated_flags with over-count launches dated before the test MONTH's first day (monthly, conservative)
DATING: only upvotes on launches dated before the launch day enter. The profile reads behind them were fetched in Nov 2026 (the store starts
Nov 1), so for Apr-Oct test days this is dated by LAUNCH DAY, not by read time (a person's later activity can only change whether they are
flagged through launches dated before the cut). Columns: arm2, ring (arm2 + ring_share + ring_n).
    usage: RING_STORE=<store dir> python e5_ring_feat.py <out parquet>"""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
sys.path.insert(0, "/home/user/UserSim/experiments/simlab"); import ringlib  # noqa: E402
t0 = time.time(); OUT = sys.argv[1]; SEEDS = range(5)
df, _ = HR.build(os.environ["H25_SRC"]); X = df.reset_index(drop=True); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).reset_index(drop=True)
E = pd.read_parquet(os.path.join(os.environ["RING_STORE"], "events.parquet"), columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); lday = dict(zip(X.id, X.day.astype(str).str[:10])); U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()]
Wv = pd.DataFrame({"id": X.id, "day": X.day.astype(str).str[:10], "votes": X.votes.astype(float)}).drop_duplicates("id", keep="last")
voters = U.groupby("target_id").person_id.agg(set).to_dict()
first_mk = X.maker_ids.map(lambda m: (list(m)[0] if m is not None and len(m) else None))
team_of = {i: {t for t in (h, m) if t is not None and str(t) not in ("", "0", "nan")} for i, h, m in zip(X.id, X.hunter_id, first_mk)}
by_team = {}
for i, d in zip(X.id, X.day.astype(str).str[:10]):
    for t in team_of[i]: by_team.setdefault(t, []).append((d, i))
def ring_feats(rows, flags):
    sh, nn = [], []
    for i, d in zip(rows.id, rows.day.astype(str).str[:10]):
        earlier = {j for t in team_of.get(i, ()) for (dj, j) in by_team.get(t, ()) if dj < d}
        vs = set().union(*[voters.get(j, set()) for j in earlier]) if earlier else set()
        k = len(vs & flags); sh.append(k / len(vs) if vs else np.nan); nn.append(np.log1p(k))
    return np.array(sh), np.array(nn)
P = dict(TW.P0, n_jobs=int(os.environ["LGB_THREADS"]))
def fit(tr, te, cols): return np.array([lgb.LGBMRegressor(random_state=s, **P).fit(tr[cols], tr.logv).predict(te[cols]) for s in SEEDS]).mean(0)
rows = []
for m in [f"2026-{k:02d}" for k in range(4, 11)]:
    flags, n_oc = ringlib.dated_flags(U[["person_id", "target_id", "lday"]], Wv, m + "-01")
    te0 = X[X.mon == m]; tr0 = X[(X.mon < m) & (X.day >= "2025-01-01")]
    tr, te, cols = TW.prep(tr0, te0); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    tr, te = tr.sort_values(["day", "id"]).copy(), te.sort_values(["day", "id"]).copy()
    tr["ring_share"], tr["ring_n"] = ring_feats(tr, flags); te["ring_share"], te["ring_n"] = ring_feats(te, flags)
    o = te[["id", "day", "dailyRank"]].copy(); o["year"] = "2026"; o["arm2"] = fit(tr, te, base); o["fix"] = fit(tr, te, base + ["ring_share", "ring_n"])
    o["ring_share"] = te.ring_share.values
    rows.append(o); print(json.dumps({"month": m, "n_test": len(te), "flags": len(flags), "over_count_launches": n_oc,
                                      "test rows with ring_share > 0": int((te.ring_share > 0).sum()), "s": round(time.time() - t0)}), flush=True)
pd.concat(rows).assign(zero_makers=False).to_parquet(OUT); print("done", flush=True)
