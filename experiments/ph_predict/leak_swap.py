"""Which source's cached (re-read) values carry the outcome leak? (orchestrator 05:20Z Nov 12). On the live days the honest
month-forward model scores its #1 pick in the final top 3 on 12/14 days from cached rows (build_cached) but 7/14 from the
00:05 rows (data/today/<d>.json via features.build). Here: one model per (test month, seed) trained exactly as the honest
backtest (build_cached rows of earlier months, honest_cols(LIVE + PAGE), ctrl.fit settings); test rows = the 00:05 rows,
with ONE source group at a time replaced by the cached values of the same launch (and the reverse: cached rows with one
group set to the 00:05 values). Source group = column prefix.
usage (VM, from ph_predict): PYTHONPATH=~/w/mk nice python3 leak_swap.py -> results/leak_swap_rows.parquet"""
import json, os
import numpy as np, pandas as pd
import features as F, model as M, run as RN
from buildcache import build_cached
from ctrl import fit
from honest import honest_cols

GROUPS = ["ph_", "hist_", "txt_", "x_", "comp_", "topic_", "llm_", "fol_", "seg_", "promo_", "busy_", "ps_", "vs_", "pf_"]
# second pass (SWAP=cols): single ph_ columns / small sets that differ between the 00:05 rows and the cache
COLSETS = {"hunter_n_same_day": ["ph_hunter_n_same_day"], "dayrank": ["ph_dayrank_ph_hunter_age_d", "ph_dayrank_ph_n_makers", "ph_dayrank_ph_n_media"],
           "day_n_launches": ["ph_day_n_launches"], "maker_age": ["ph_maker_max_age_d", "ph_maker_min_age_d"],
           "maker_counts": ["ph_n_makers", "ph_n_makers_new", "ph_maker_has_headline", "ph_self_hunted"],
           "text_lens": ["ph_tagline_len", "ph_desc_len", "ph_name_len", "ph_n_media", "ph_has_video", "ph_n_topics"]}


def main():
    C = build_cached(); C = C[~C.known].copy(); C["id"] = C.id.astype(str); C["mon"] = C.day.str[:7]
    T = RN.load_llm(F.build(include_today=True)); T["id"] = T.id.astype(str)
    days = sorted({os.path.basename(f)[:10] for f in os.listdir(f"{F.D}/today")})
    out = []
    for m in sorted({d[:7] for d in days}):
        tr0 = C[C.mon < m]
        for d in [x for x in days if x[:7] == m]:
            a = T[T.is_today & (T.day == d) & ~T.known].drop_duplicates("id").set_index("id")
            b = C[C.day == d].drop_duplicates("id").set_index("id")
            j = a.index.intersection(b.index)
            if len(j) < 10:
                continue
            tr, te = M.add_fold_feats(tr0, pd.concat([a.loc[j].reset_index().assign(view="a"), b.loc[j].reset_index().assign(view="b")], ignore_index=True))
            cols = honest_cols(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES))
            A = te[te.view == "a"].set_index("id").loc[j]; Bv = te[te.view == "b"].set_index("id").loc[j]
            variants = {"a_0005": A, "b_cache": Bv}
            sets = ({k: [c for c in v if c in cols] for k, v in COLSETS.items()} if os.environ.get("SWAP") == "cols"
                    else {g: [c for c in cols if c.startswith(g)] for g in GROUPS})
            for g, gc in sets.items():
                if not gc:
                    continue
                x = A.copy(); x[gc] = Bv[gc].values; variants[f"a+cache:{g}"] = x
                y = Bv.copy(); y[gc] = A[gc].values; variants[f"b+0005:{g}"] = y
            names = list(variants); X = pd.concat([variants[n][cols] for n in names])
            P = np.mean([fit(tr, X.reset_index(drop=True), cols, s) for s in range(5)], axis=0)
            for k, n in enumerate(names):
                for i, p in zip(j, P[k * len(j):(k + 1) * len(j)]):
                    out.append({"day": d, "id": i, "variant": n, "pred": float(p), "rank": float(b.at[i, "dailyRank"]) if pd.notna(b.at[i, "dailyRank"]) else np.nan})
            diff = {g: int(((A[[c for c in cols if c.startswith(g)]].fillna(-9e9) != Bv[[c for c in cols if c.startswith(g)]].fillna(-9e9)).any(axis=1)).sum())
                    for g in GROUPS if any(c.startswith(g) for c in cols)}
            print(json.dumps({"day": d, "launches": len(j), "launches_with_changed_values_by_group": diff}), flush=True)
    pd.DataFrame(out).to_parquet("results/leak_swap_cols_rows.parquet" if os.environ.get("SWAP") == "cols" else "results/leak_swap_rows.parquet")
    print("done", flush=True)


if __name__ == "__main__":
    main()
