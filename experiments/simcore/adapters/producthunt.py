"""Product Hunt adapter: turns the per-person scores from simlab/popscore.py (person model retrained each month on the
previous month, no popularity input) into simcore Contexts, one per launch day, and exports simcore's per-launch
outputs as launch-model inputs:
  sc_   all channels (dated past backing + undated follow lists)      scd_  dated channels only
Scoring uses the launch harness (daily / weekly / monthly lists).
usage: python -m simcore.adapters.producthunt check   (reproduce simbench's simulation-only numbers)
       python -m simcore.adapters.producthunt export  -> ph_predict/data/{sc,scd}_features.json"""
import json, os, sys
import numpy as np, pandas as pd
from simcore import Context, simulate, exposure

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))
ROWS = os.path.join(EXP, "simlab", "cache", "popscore", "rows")
RAW = os.path.join(EXP, "ph_predict", "data")
SETTINGS = dict(slots=4, tau=25.0, v0=0.5, beta=1.0)   # fitted on Apr-Jun in simlab/simbench.py


def contexts():
    for f in sorted(os.listdir(ROWS)):
        D = pd.read_parquet(f"{ROWS}/{f}")
        ppl = {u: k for k, u in enumerate(D.person.unique())}; items = list(D.id.unique()); ix = {x: k for k, x in enumerate(items)}
        r, c = D.person.map(ppl).values, D.id.map(ix).values
        P = np.zeros((len(ppl), len(items)), np.float32); P[r, c] = D.p.values
        T = {k: np.zeros_like(P) for k in ("backed", "follow")}
        T["backed"][r, c] = D.backed.values > 0; T["follow"][r, c] = D.follow.values > 0
        w = np.zeros(len(ppl), np.float32); w[r] = D.w.values
        yield Context(f[:10], items, w, P, T)


def check():
    sys.path.insert(0, EXP)
    from simlab import harness as H
    B = H.baseline().drop_duplicates("id")
    sim = {}
    for ctx in contexts():
        sim.update(simulate(ctx, **SETTINGS))
    T = B[B.mon.isin(["2026-07", "2026-08", "2026-09", "2026-10"])].copy(); T["sim"] = T.id.map(sim); T = T.dropna(subset=["sim"])
    print({f"day@{k}": round(100 * H.recall(T, "sim", k=k), 1) for k in H.KS})


def export():
    sc, scd = {}, {}
    for ctx in contexts():
        v_all = simulate(ctx, **SETTINGS, channels=("backed", "follow")); v_dat = simulate(ctx, **SETTINGS, channels=("backed",))
        e_all = exposure(ctx, ("backed", "follow")); tot_a, tot_d = sum(v_all.values()) or 1, sum(v_dat.values()) or 1
        for x in ctx.items:
            e = e_all[x]
            sc[str(x)] = {"sc_votes": v_all[x], "sc_share": v_all[x] / tot_a, **{f"sc_{k}": v for k, v in e.items()}}
            scd[str(x)] = {"scd_votes": v_dat[x], "scd_share": v_dat[x] / tot_d,
                           **{f"scd_{k}": v for k, v in e.items() if "follow" not in k}}
    json.dump(sc, open(f"{RAW}/sc_features.json", "w")); json.dump(scd, open(f"{RAW}/scd_features.json", "w"))
    print("exported", len(sc), "launches;", list(next(iter(sc.values()))), list(next(iter(scd.values()))))


if __name__ == "__main__":
    check() if sys.argv[1] == "check" else export()
