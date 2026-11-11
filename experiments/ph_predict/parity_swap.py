"""Swap attribution for live vs backtest parity (orchestrator 21:50Z Nov 11). Runs on the pipeline VM after
parity_live.py. Per live day: train as live (days < d, LIVE_SOURCES, live_sources() on the 00:05 rows, SEEDS seeds),
predict the 00:05 rows (view a) with each feature group swapped to its later re-read value (view b), one group at a
time, and all groups at once. Groups: each column that differs between the views on any launch, plus the maker-id check
(hist_ / ph_ maker columns together). Also reports how many 00:05 rows carry a placeholder maker id ("0" or empty).
usage (VM): nice python3 parity_swap.py -> results/parity_swap.parquet"""
import json, os
import numpy as np, pandas as pd
import features as F, model as M, run as RN

SEEDS = int(os.environ.get("SEEDS", "3"))


def main():
    df0 = F.build(include_today=True)
    df = RN.load_llm(df0)
    days = sorted({os.path.basename(f)[:10] for f in os.listdir(f"{F.D}/today")})
    final = df[~df.is_today]
    out = []
    for d in days:
        fin = final[final.day == d]
        if fin.empty or fin.dailyRank.isna().all():
            continue
        tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
        a = df[df.is_today & (df.day == d) & (~df.known)]
        b = fin[fin.id.isin(a.id)]
        ph0 = int(sum(any(str(x) in ("0", "", "None") for x in (m or [])) for m in a.maker_ids))
        tr2, te = M.add_fold_feats(tr, pd.concat([a.assign(view="a"), b.assign(view="b")], ignore_index=True))
        src, _ = M.live_sources(tr2, te[te.view == "a"], M.LIVE_SOURCES)
        cols = M.cols(tr2, src)
        A = te[te.view == "a"].copy(); A.index = A.id.astype(str)
        Bv = te[te.view == "b"].copy(); Bv.index = Bv.id.astype(str)
        Bv = Bv.reindex(A.index)
        models = [M.fit_predict(tr2, A, src, seed=s, **M.LIVE_PARAMS)[1] for s in range(SEEDS)]
        pred = lambda X: np.mean([m.predict(X[cols]) for m in models], axis=0)
        rk = fin.set_index(fin.id.astype(str)).dailyRank.reindex(A.index)
        diffc = [c for c in cols if not np.allclose(pd.to_numeric(A[c], errors="coerce").fillna(-9e9), pd.to_numeric(Bv[c], errors="coerce").fillna(-9e9))]
        groups = {"none": [], "all_diff": diffc, "maker_cols": [c for c in diffc if "maker" in c or c.startswith("hist_")]}
        groups.update({c: [c] for c in diffc})
        for gname, gc in groups.items():
            X = A.copy()
            for c in gc:
                X[c] = Bv[c].where(Bv[c].notna(), X[c]) if c in Bv else X[c]
            p = pd.Series(pred(X), index=A.index)
            r = {"day": d, "group": gname, "n": len(A), "placeholder_maker_rows": ph0}
            for k in (3, 5, 10):
                r[f"top{k}"] = len(set(p.nlargest(k).index) & set(rk.nsmallest(k).index)) / k * 100
            out.append(r)
        print(json.dumps({"day": d, "n": len(A), "diff_cols": len(diffc), "placeholder_maker_rows": ph0}), flush=True)
    pd.DataFrame(out).to_parquet(f"{RN.OUT}/parity_swap.parquet")


if __name__ == "__main__":
    main()
