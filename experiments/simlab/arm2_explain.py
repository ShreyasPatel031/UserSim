"""Explain arm 2 from arm 2 itself: tree-SHAP groups vs the readable stumps (orchestrator 23:36Z Nov 13). Counts only.
Inputs: PH ops' dump tmp/ph_ops/arm2_explain (X, seed-mean pred_contrib SHAP, 35 boosters + rescore, stump points, group map).
SHAP groups (40 inputs): hunter record (hist_hunter_*, ph_hunter_age_d, ph_hunter_n_same_day, dayrank hunter transforms), pitch (llm_pitch),
brand (llm_brand), topic (topic_*, ph_n_topics), competition (comp_nn_*), media (ph_n_media, ph_has_video, dayrank media), team size
(ph_n_makers, dayrank makers), promotion (promo_*, x_company_has_x), text (txt_ridge, desc/tagline/name length), day/lineup (weekday,
day_n_launches, busy_*). Stumps: 10 inputs in 7 groups (PH ops map); stated drivers = top3_groups (by |summed points|, as the why file).
SHAP drivers of a pick = groups ranked by within-day-centred contribution (contribution minus the day mean; only differences move ranks).
Picks = arm 2's top 3 per day (214 days). (a) fidelity: set the stated driver group's inputs (top 1, or top 3 groups) to the day median and
re-score with the deployed boosters (other launches unchanged); share of picks that drop out of the top 3; baseline = a random SHAP group.
(b) agreement: SHAP top group == stump top group. (c) usefulness: pick accuracy (official rank <= 3) by dominant group and by
concentration (top group's share of the positive centred contribution), day bootstrap.
    python arm2_explain.py <dump dir> <out dir>
"""
import json, os, sys
import numpy as np, pandas as pd
D, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); sys.path.insert(0, D)
from rescore import rescore
X = pd.read_parquet(f"{D}/X.parquet"); X["id"] = X.id.astype(str); S = pd.read_parquet(f"{D}/shap.parquet"); S["id"] = S.id.astype(str)
ST = pd.read_parquet(f"{D}/stumps.parquet"); ST["id"] = ST.id.astype(str); SG = json.load(open(f"{D}/stump_groups.json"))["input_to_group"]
INP = [c for c in X.columns if c not in ("id", "day", "mon", "dailyRank", "both")]
def grp(c):
    if c.startswith("hist_") or "hunter" in c: return "hunter record"
    if c == "llm_pitch": return "pitch"
    if c == "llm_brand": return "brand"
    if c.startswith("topic_") or c == "ph_n_topics": return "topic"
    if c.startswith("comp_"): return "competition"
    if "media" in c or c == "ph_has_video": return "media"
    if "makers" in c: return "team size"
    if c.startswith("promo_") or c == "x_company_has_x": return "promotion"
    if c in ("txt_ridge", "ph_desc_len", "ph_tagline_len", "ph_name_len"): return "text"
    return "day/lineup"
GM = {c: grp(c) for c in INP}; GROUPS = sorted(set(GM.values()))
norm = lambda g: {"pitch (Gemini)": "pitch"}.get(g, g)
SGn = {c: norm(g) for c, g in SG.items()}
M = X.merge(S[["id"] + INP].rename(columns={c: "s_" + c for c in INP}), on="id").merge(ST[["id", "top3_groups"] + list(SG)].rename(columns={c: "p_" + c for c in SG}), on="id", how="left")
M = pd.concat([M, pd.DataFrame({"G_" + g: M[["s_" + c for c in INP if GM[c] == g]].sum(1) for g in GROUPS})], axis=1)
for g in GROUPS: M["C_" + g] = M["G_" + g] - M.groupby("day")["G_" + g].transform("mean")
M["a2rank"] = M.groupby("day").both.rank(ascending=False, method="first")
P = M[M.a2rank <= 3].copy(); P["right"] = (P.dailyRank <= 3).astype(float)
C = P[["C_" + g for g in GROUPS]].values; order = np.argsort(-C, 1)
P["shap1"] = [GROUPS[o[0]] for o in order]; P["shap3"] = [[GROUPS[j] for j in o[:3]] for o in order]
pos = np.clip(C, 0, None); P["conc"] = pos.max(1) / np.maximum(pos.sum(1), 1e-9)
P["st3"] = [[norm(g) for g in (list(t) if t is not None else [])] for t in P.top3_groups]; P["st1"] = [t[0] if t else None for t in P.st3]
med = M.groupby("day")[INP].median()
def fid(groups_per_pick, inputs_of):
    Z = []
    for (_, r), gs in zip(P.iterrows(), groups_per_pick):
        z = r[["id", "day", "mon"] + INP].copy(); cols = [c for g in gs for c in inputs_of(g)]
        for c in cols: z[c] = med.loc[r.day, c]
        Z.append(z)
    Z = pd.DataFrame(Z); Z[INP] = Z[INP].astype(float); new = rescore(Z, f"{D}/models", f"{D}/cols.json"); drop = []
    for (_, r), v in zip(P.iterrows(), new):
        others = M[(M.day == r.day) & (M.id != r.id)].both.values; drop.append(float((others > v).sum() >= 3))
    return np.array(drop)
shap_inp = lambda g: [c for c in INP if GM[c] == g]; st_inp = lambda g: [c for c, gg in SGn.items() if gg == g]
def lb(v, dd=None):
    v = np.asarray(v, float); dd = P.day.values if dd is None else np.asarray(dd); ud = np.unique(dd); idx = {d: np.flatnonzero(dd == d) for d in ud}
    bs = [v[np.concatenate([idx[d] for d in rng.choice(ud, len(ud))])].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
res = {"design": __doc__.split("\n    python")[0], "days": int(P.day.nunique()), "picks": len(P), "pick accuracy (rank <= 3)": lb(P.right)}
rg = [[GROUPS[rng.integers(len(GROUPS))]] for _ in range(len(P))]
f = {"SHAP top-1 group": fid([[g] for g in P.shap1], shap_inp), "SHAP top-3 groups": fid(P.shap3, shap_inp),
     "stumps top-1 stated group": fid([[g] if g else [] for g in P.st1], st_inp), "stumps top-3 stated groups": fid(P.st3, st_inp),
     "stumps top-1 stated group, all arm-2 inputs of that group": fid([[g] if g else [] for g in P.st1], shap_inp),
     "random SHAP group (baseline)": fid(rg, shap_inp)}
res["(a) fidelity: share of picks dropping out of top 3 when the stated drivers are set to the day median"] = {k: lb(v) for k, v in f.items()}
res["(a) paired SHAP top-1 - stumps top-1"] = lb(f["SHAP top-1 group"] - f["stumps top-1 stated group"])
res["(a) paired SHAP top-3 - stumps top-3"] = lb(f["SHAP top-3 groups"] - f["stumps top-3 stated groups"])
res["(b) agreement: SHAP top group == stumps top group"] = lb((P.shap1 == P.st1).astype(float))
res["(b) SHAP top group in stumps' top 3"] = lb([a in b for a, b in zip(P.shap1, P.st3)])
res["(b) SHAP top-group distribution"] = P.shap1.value_counts().to_dict(); res["(b) stumps top-group distribution"] = P.st1.value_counts().to_dict()
u = {}
for nm, col in (("SHAP dominant group", "shap1"), ("stumps top group", "st1")):
    u[nm] = {g: lb(P[P[col] == g].right, P[P[col] == g].day) for g in P[col].dropna().unique() if (P[col] == g).sum() >= 15}
P["concb"] = pd.cut(P.conc, [0, .4, .6, 1.01], labels=["<0.4 spread", "0.4-0.6", ">0.6 single driver"])
u["SHAP concentration"] = {str(g): lb(P[P.concb == g].right, P[P.concb == g].day) for g in P.concb.cat.categories if (P.concb == g).sum() >= 15}
res["(c) pick accuracy by explanation"] = u
json.dump(res, open(os.path.join(OUT, "arm2_explain.json"), "w"), indent=1, default=str); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=str))
