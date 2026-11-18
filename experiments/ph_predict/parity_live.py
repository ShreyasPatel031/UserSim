"""Live vs backtest parity of the 00:05 launch-model forecast (orchestrator 21:50Z Nov 11). Runs on the pipeline VM
(reads data/today/<d>.json = the 00:05 snapshot the live forecast used, data/days/<d>.json = the later re-read, and
results/forecast_<d>.parquet = the live prediction). Nothing deployed is changed; output is a local parquet/json.

For each live day d (today/<d>.json exists and days/<d>.json has final ranks):
  live_pub   the published live prediction (forecast_<d>.parquet "pred")
  replay_a   today's code, trained on days < d, predicting d's 00:05 rows (today/<d>.json view) - the live condition
  replay_b   same model, predicting d's rows as re-read later (days/<d>.json view, the offline/backtest condition)
  oof_b_all  replay_b but over the FINAL ranked line-up (launches missing at 00:05 included)
Sources: model.LIVE_SOURCES with live_sources() drops computed on the 00:05 rows (as live does); 5 seeds; HONEST as in
model.py. Also writes, per launch, the 00:05 and later values of every model column (for the swap attribution).
usage (VM): nice python3 parity_live.py -> results/parity_live_rows.parquet, results/parity_live_feats.parquet"""
import json, os, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

SEEDS = int(os.environ.get("SEEDS", "5"))


def main():
    df0 = F.build(include_today=True)
    df = RN.load_llm(df0)
    days = sorted({os.path.basename(f)[:10] for f in os.listdir(f"{F.D}/today")})
    final = df[~df.is_today]
    rows, feats = [], []
    for d in days:
        fin = final[final.day == d]
        if fin.empty or fin.dailyRank.isna().all():
            continue
        lp = f"{RN.OUT}/forecast_{d}.parquet"
        tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
        a = df[df.is_today & (df.day == d)]
        b_all = fin.copy()
        a_known = a.known.copy()
        a = a[~a.known]
        b = b_all[b_all.id.isin(a.id)]
        tr2, te = M.add_fold_feats(tr, pd.concat([a.assign(view="a"), b.assign(view="b"), b_all.assign(view="b_all")], ignore_index=True))
        src, dropped = M.live_sources(tr2, te[te.view == "a"], M.LIVE_SOURCES)
        preds = np.mean([M.fit_predict(tr2, te, src, seed=s, **M.LIVE_PARAMS)[0] for s in range(SEEDS)], axis=0)
        te["pred"] = preds
        cols = M.cols(tr2, src)
        live = pd.read_parquet(lp) if os.path.exists(lp) else pd.DataFrame({"id": [], "pred": []}); live["id"] = live.id.astype(str)
        rk = fin.set_index(fin.id.astype(str)).dailyRank
        for v, g in te.groupby("view"):
            for i, p in zip(g.id.astype(str), g.pred):
                rows.append({"day": d, "id": i, "view": v, "pred": float(p), "rank": rk.get(i, np.nan)})
        for i, p in zip(live.id, live.pred):
            rows.append({"day": d, "id": i, "view": "live_pub", "pred": float(p), "rank": rk.get(i, np.nan)})
        A = te[te.view == "a"].set_index(te[te.view == "a"].id.astype(str))[cols]
        Bv = te[te.view == "b"].set_index(te[te.view == "b"].id.astype(str))[cols]
        for i in A.index.intersection(Bv.index):
            feats.append({"day": d, "id": i, **{f"a::{c}": A.at[i, c] for c in cols}, **{f"b::{c}": Bv.at[i, c] for c in cols}})
        print(json.dumps({"day": d, "a": int((te.view == "a").sum()), "b_all": int((te.view == "b_all").sum()), "known_dropped": int(a_known.sum()),
                          "live_pub": int(len(live)), "sources": src, "dropped": dropped, "n_cols": len(cols)}), flush=True)
    pd.DataFrame(rows).to_parquet(f"{RN.OUT}/parity_live_rows.parquet")
    pd.DataFrame(feats).to_parquet(f"{RN.OUT}/parity_live_feats.parquet")


if __name__ == "__main__":
    main()
