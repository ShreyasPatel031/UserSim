"""Shadow fix for placeholder maker ids at 00:05 (parity_live.md, Nov 11). Runs by hand on the pipeline VM after 01:00 PT
(never 00:05-01:00 PT), read-only for everything deployed. Same training as the live forecast (days < d, model.LIVE_SOURCES,
live_sources() on the 00:05 rows, LIVE_PARAMS, 5 seeds); test rows = data/today/<d>.json (the 00:05 snapshot) only.
  unfixed   the 00:05 rows as they are (a replay of live with today's code)
  makerfix  for launches whose 00:05 maker ids include a placeholder ("0", empty, None), every maker-derived input
            (hist_maker*, hist_dayrank_hist_maker*, ph_maker*, ph_n_makers*, ph_dayrank_ph_n_makers, x_n_makers*) is set
            to missing (LightGBM's missing branch) instead of the value joined on the placeholder id
  nollm     (orchestrator 04:45Z Nov 12) the deployed model WITHOUT the llm and promo sources (else as unfixed): the
            replay's "live minus LLM judgements / promo" condition, scored forward next to published and makerfix
usage (VM): /opt/exp/bin/python3 makerfix_shadow.py <day> -> results/shadow_makerfix/<day>.json (prints its path)"""
import json, os, sys
import numpy as np, pandas as pd
import features as F, model as M, run as RN

MAKER = lambda c: c.startswith(("hist_maker", "hist_dayrank_hist_maker", "ph_maker", "ph_n_makers", "ph_dayrank_ph_n_makers", "x_n_makers"))


def main(d):
    now = pd.Timestamp.now(tz="America/Los_Angeles")
    if now.strftime("%Y-%m-%d") == d and now.hour < 1:
        print(json.dumps({"day": d, "status": "before 01:00 PT; not running"})); return
    df = RN.load_llm(F.build(include_today=True))
    tr = df[(~df.is_today) & (df.day < d) & (~df.known)]
    a = df[df.is_today & (df.day == d) & (~df.known)].copy()
    if a.empty:
        print(json.dumps({"day": d, "status": "no 00:05 rows"})); return
    ph = a.maker_ids.apply(lambda m: (not m) or any(str(x) in ("0", "", "None") for x in m))
    tr2, te = M.add_fold_feats(tr, a)
    src, dropped = M.live_sources(tr2, te, M.LIVE_SOURCES)
    cols = M.cols(tr2, src); mc = [c for c in cols if MAKER(c)]
    fx = te.copy(); fx.loc[ph.values, mc] = np.nan
    models = [M.fit_predict(tr2, te, src, seed=s, **M.LIVE_PARAMS)[1] for s in range(5)]
    p0 = np.mean([m.predict(te[cols]) for m in models], axis=0); p1 = np.mean([m.predict(fx[cols]) for m in models], axis=0)
    src_n = [x for x in src if x not in ("llm", "promo")]
    p2 = np.mean([M.fit_predict(tr2, te, src_n, seed=s, **M.LIVE_PARAMS)[0] for s in range(5)], axis=0)
    out = pd.DataFrame({"id": te.id.astype(str).values, "pred_unfixed": p0, "pred_makerfix": p1, "pred_nollm": p2, "placeholder": ph.values})
    out["rank_unfixed"] = out.pred_unfixed.rank(ascending=False, method="first").astype(int)
    out["rank_makerfix"] = out.pred_makerfix.rank(ascending=False, method="first").astype(int)
    out["rank_nollm"] = out.pred_nollm.rank(ascending=False, method="first").astype(int)
    res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "inputs": "data/today/<d>.json (00:05 snapshot) only",
           "launches": int(len(out)), "placeholder_launches": int(ph.sum()), "maker_cols": mc, "sources": src, "dropped": dropped,
           "sources_nollm": src_n, "llm_in_unfixed": "llm" in src, "promo_in_unfixed": "promo" in src,
           "forecast": out.sort_values("rank_makerfix").round(4).to_dict("records")}
    os.makedirs(f"{RN.OUT}/shadow_makerfix", exist_ok=True)
    p = f"{RN.OUT}/shadow_makerfix/{d}.json"; json.dump(res, open(p, "w"), indent=1, default=bool)
    print(p)


if __name__ == "__main__":
    main(sys.argv[1])
