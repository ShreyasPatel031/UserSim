"""Simulation-only forecast for today (model "simulation" in the forecasts table), the live twin of newsim_eval.py
NOPAGE=1 STAGE=2 STAGE3=1 "+day standing" with SIM_SRC=pnx. Inputs per launch: the person simulation summed per
launch (pnx_, tie strength + extensions, no page), outside reach (makers' and hunter's Product Hunt followers, makers'
X followers), the audience blocks known before launch (hist_, promo_, fol_, x_), and each of those as a standing
within the day's line-up. No page or text inputs, no launch-model prediction. LightGBM on log votes, 3 seeds, trained
on every finished day that has simulation rows (backtest pnx_features.json, plus live data/sim_live/pnx_<day>.json once
the day is final), predicting today.
usage: python sim_forecast.py <YYYY-MM-DD>   -> results/sim_forecast_<day>.md, results/dash/sim_forecast.json"""
import glob, gzip, json, math, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
import features as F
import model as M, run as RN

D = "data"
LIVE = os.environ.get("SIM_LIVE", f"{D}/sim_live")   # live simulation rows (pipeline.sim_daily)


def reach(day):
    """nsa_ph_makers / nsa_ph_hunter / nsa_x_makers as newsim_audience.py computes them, for every launch file."""
    xf = {}
    if os.path.exists(f"{D}/x_people.jsonl.gz"):
        for l in gzip.open(f"{D}/x_people.jsonl.gz", "rt"):
            r = json.loads(l)
            if r.get("profile"):
                xf[r["handle"].lower()] = r["profile"].get("followers") or 0
    out = {}
    for f in sorted(glob.glob(f"{D}/days/*.json")) + [f"{D}/today/{day}.json"]:
        for p in json.load(open(f)):
            mk = [m for m in p.get("makers") or [] if isinstance(m, dict)]; h = p.get("user") or {}
            out[str(p["id"])] = {"nsa_ph_makers": math.log1p(sum(m.get("followersCount") or 0 for m in mk)),
                                 "nsa_ph_hunter": math.log1p(h.get("followersCount") or 0),
                                 "nsa_x_makers": math.log1p(sum(xf.get((m.get("twitterUsername") or "").lower(), 0) for m in mk))}
    return pd.DataFrame.from_dict(out, orient="index").rename_axis("id").reset_index()


def sim_rows(day):
    S = json.load(open(f"{D}/pnx_features.json"))
    for f in sorted(glob.glob(f"{LIVE}/pnx_*.json")):
        S.update(json.load(open(f)))
    T = pd.DataFrame.from_dict(S, orient="index").rename_axis("id").reset_index()
    for c in [c for c in T if c.startswith("pnx_") and not c.endswith("pmax")]:
        T[c] = np.log1p(T[c])
    return T


def main(day):
    B = RN.load_llm(F.build(include_today=True)); B["id"] = B.id.astype(str)   # as forecast.py: drop "known" launches
    B = B[~B.known]
    blocks = [c for c in B if c.startswith(("hist_", "promo_", "fol_"))] + [c for c in ("x_maker_max_followers", "x_company_followers") if c in B]
    A = B[["id", "day", "is_today", "logv"] + blocks].merge(sim_rows(day), on="id").merge(reach(day), on="id", how="left")
    sim = [c for c in A if c.startswith("pnx_")]
    aud = sim + ["nsa_ph_makers", "nsa_ph_hunter", "nsa_x_makers"] + blocks
    if M.HONEST:   # honest pre-launch set (model.py): no follower counts (nsa_ reach included), no fol_, no undated promo_
        aud = [c for c in aud if not (M.honest_drop(c) or c.startswith("nsa_"))]
    for c in aud:
        A[c + "_dayr"] = A.groupby("day")[c].rank(pct=True)
    cols = aud + [c + "_dayr" for c in aud]
    tr, te = A[~A.is_today & A.logv.notna()], A[A.is_today & (A.day == day)].copy()
    if not len(te):
        raise SystemExit(f"no simulation rows for {day}: run pipeline.sim_daily first")
    te["score"] = np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                             colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=4).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(3)], 0)
    te = te.sort_values("score", ascending=False)
    names = {str(p["id"]): (p["name"], p.get("tagline") or "") for p in json.load(open(f"{D}/today/{day}.json"))}
    n_today = len(names)
    L = [f"# Simulation-only forecast for {day} (made before results; {len(te)} of {n_today} launches scored; trained on "
         f"{tr.day.nunique()} finished days, {tr.day.min()} to {tr.day.max()})\n", "| Predicted rank | Product | Tagline |", "|---|---|---|"]
    for i, r in enumerate(te.itertuples()):
        L.append(f"| {i + 1} | {names.get(r.id, ('?', ''))[0]} | {names.get(r.id, ('?', ''))[1]} |")
    os.makedirs("results/dash", exist_ok=True)
    open(f"results/sim_forecast_{day}.md", "w").write("\n".join(L) + "\n")
    json.dump([{"rank": i + 1, "product": names.get(r.id, ("?",))[0], "id": r.id} for i, r in enumerate(te.itertuples())],
              open("results/dash/sim_forecast.json", "w"))
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1])
