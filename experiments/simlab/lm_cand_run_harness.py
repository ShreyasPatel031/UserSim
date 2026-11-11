"""Run D1/D2 through the PH agent's lm_breakout harness unchanged (same folds, seeds, bootstrap, keep rule)."""
import os, sys, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "git"))
import lm_breakout as LB, model as M
from ctrl import fit
F = pd.read_parquet(os.environ["D_FEATS"]); F["id"] = F.id.astype(str)
D1C = ["aud_backers", "aud_backers_act30", "aud_commenters", "aud_team_in_store", "aud_backers_pct", "aud_backers_act30_pct", "aud_commenters_pct"]
D2C = ["ev_e5", "ev_e5_pct"]
def load(cols, pre):
    def f(df):
        x = F[["id"] + cols].copy(); x.columns = ["id"] + [pre + c for c in cols]
        x["id"] = x.id.astype(df.id.dtype); return x
    return f
LB.CANDS["D1"] = load(D1C, "d1_"); LB.CANDS["D2"] = load(D2C, "d2_")
PREF = {"C1": "tm_", "C2": "hc_", "C3": "tt_", "D1": "d1_", "D2": "d2_", "D12": None}
def job(a):
    m, tr, te, seed, names = a
    tr, te = M.add_fold_feats(tr, te)
    base = [c for c in M.cols(tr, M.LIVE_SOURCES) if c != "llm_full"]
    out = {"id": te.id.values, "seed": seed, "base": fit(tr, te, base, seed)}
    for n in names:
        extra = [c for c in tr.columns if (c.startswith("d1_") or c.startswith("d2_"))] if n == "D12" else [c for c in tr.columns if c.startswith(PREF[n])]
        out[n] = fit(tr, te, base + extra, seed)
    return pd.DataFrame(out), len(base)
LB.job = job
names = sys.argv[1:]
LB.CANDS["D12"] = lambda df: pd.DataFrame({"id": df.id.values})
LB.main(names)
