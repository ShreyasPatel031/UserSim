"""Midnight (00:05) forecast miss anatomy at top 10, arm 3 rebuild, month-forward. Each miss is assigned to the input group that pushed it
the wrong way most (LightGBM contributions, centred on the day's mean for that group): for a false negative the group with the most negative
centred contribution, for a false positive the most positive. Ring (classification only, measured after the day) is checked first. On live
days with a before-reveal replay, misses where even the 03:00 hidden order was wrong are labelled late surge / fade."""
import json, sys, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/mna/out"
R = pd.read_parquet(f"{OUT}/arm3_oos_contrib.parquet"); R = R[R.dailyRank.notna()].copy(); R["id"] = R.id.astype(str)
n = R.groupby("day").size(); R = R[R.day.isin(n[n >= 10].index)]
cols = [c[2:] for c in R.columns if c.startswith("c_") and c != "c_bias"]
def grp(c):
    if c.startswith(("hist_hunter", "ph_hunter", "hist_dayrank")): return "hunter record"
    if c.startswith("C_") or c in ("ph_n_makers", "ph_dayrank_ph_n_makers", "x_company_has_x"): return "maker team (size, earlier launches)"
    if c.startswith("A_") or c in ("ph_day_n_launches", "busy_same_day", "busy_7d", "ph_weekday"): return "launch-day crowding (line-up, weekday)"
    if c.startswith(("topic_", "comp_nn", "B_")): return "topic prior (topic, nearest past launches)"
    if c.startswith(("llm_", "txt_ridge")) or c in ("ph_desc_len", "ph_tagline_len", "ph_name_len", "ph_n_media", "ph_has_video", "ph_n_topics", "ph_dayrank_ph_n_media"): return "pitch and page (Gemini pitch score, text, media)"
    if c.startswith("promo_"): return "launch-day promotion"
    return "other inputs"
G = {}
for c in cols: G.setdefault(grp(c), []).append("c_" + c)
for g, cs in G.items(): R["g_" + g] = R[cs].sum(1); R["g_" + g] = R["g_" + g] - R.groupby("day")["g_" + g].transform("mean")
R["pr"] = R.groupby("day").pred3.rank(ascending=False, method="first")
RING = pd.read_parquet(f"{SP}/ring/ph_discounted_likely.parquet"); ringp = set(RING[RING.ph_discounted_likely].person_id)
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); E = E[E.kind == "upvote"]; E["target_id"] = E.target_id.astype(str)
E = E[E.target_id.isin(set(R.id))]; rs = E.assign(r=E.person_id.isin(ringp)).groupby("target_id").r.agg(["mean", "size"])
R["ring_share"] = R.id.map(rs["mean"]); R["held_voters"] = R.id.map(rs["size"]).fillna(0)
H = pd.read_parquet(f"{SP}/pra/out/launch_rows.parquet")[["id", "pos"]]; H["id"] = H.id.astype(str); R = R.merge(H, on="id", how="left")
rows = []
for d, g in R.groupby("day"):
    for r in g.itertuples(index=False):
        fn = r.dailyRank <= 10 and r.pr > 10; fp = r.pr <= 10 and r.dailyRank > 10
        if not (fn or fp): continue
        s = pd.Series({k: getattr(r, "g_" + k.replace(" ", "_")) if False else g.loc[g.id == r.id, "g_" + k].iloc[0] for k in G})
        wrong = (-s if fn else s); top = wrong.idxmax()
        if r.ring_share == r.ring_share and r.ring_share >= 0.30 and r.held_voters >= 20: c = "ring or vote spike (30%+ of held voters ring-flagged)"
        elif r.pos == r.pos and ((fn and r.pos > 10) or (fp and r.pos <= 10)): c = "late surge or fade (wrong even in the 03:00 hidden order)"
        elif wrong.max() < 0.05: c = "no input pushed it far (near tie or unexplained)"
        else: c = top
        rows.append({"day": d, "id": r.id, "type": "FN" if fn else "FP", "class": c, "final": int(r.dailyRank), "pred_rank": int(r.pr), "n_day": len(g),
                     "hunter_n": r.hist_hunter_n, "hunter_top5": r.hist_hunter_top5, "n_makers": r.ph_n_makers, "llm_pitch": r.llm_pitch, "ring_share": r.ring_share,
                     "hidden_0300": r.pos, **{"wrong_push_" + k: round(float(wrong[k]), 3) for k in G}})
M = pd.DataFrame(rows); M.to_parquet(f"{OUT}/misses.parquet")
D = sorted(R.day.unique()); slots = 10 * len(D); hits = sum(((g.pr <= 10) & (g.dailyRank <= 10)).sum() for _, g in R.groupby("day"))
O = {"days": len(D), "window": [D[0], D[-1]], "top10": round(hits / slots * 100, 1), "misses": len(M)}
tab = M.groupby("class").agg(FN=("type", lambda s: int((s == "FN").sum())), FP=("type", lambda s: int((s == "FP").sum()))).sort_values("FN", ascending=False)
tab["oracle_top10"] = ((hits + tab.FN) / slots * 100).round(1); O["classes"] = tab.reset_index().to_dict("records")
L = R[R.pos.notna()]; Dl = sorted(L.day.unique()); O["live_overlap_days_with_0300_read"] = Dl
O["hunter_missing_share_by_month"] = R.assign(m=R.day.str[:7]).groupby("m").apply(lambda g: round(float((g.hist_hunter_n.fillna(0) == 0).mean()), 3)).to_dict()
json.dump(O, open(f"{OUT}/anatomy.json", "w"), indent=1, default=str); print(json.dumps(O, indent=1, default=str)); print(tab)
