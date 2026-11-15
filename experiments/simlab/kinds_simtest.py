"""Validity test of simulated users (pre-registered here): can a Gemini persona built from ONE real person's earlier upvotes tell which of a day's
launches that person really upvoted?  Days 2026-11-03/04/05; 60 real voters per day (>= 10 earlier votes, >= 1 vote that day). Persona sees only
upvotes dated before the day. It rates every launch of the day 0-10. Metric: within-person AUC vs the person's real votes that day.
Baselines: (a) cosine of the person's mean earlier-launch embedding with each launch (no LLM); (b) the launch's final vote count (same for everyone).
Useful = simulated AUC lower bound > 0.5 AND simulated minus embedding (paired) lower bound > 0."""
import json, sys, numpy as np, pandas as pd, concurrent.futures as cf
from sklearn.metrics import roc_auc_score
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0)
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
from pipeline import warehouse
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); PU = pd.read_parquet(f"{OUT}/people_units2.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); votes = pd.to_numeric(W.set_index("id").votes, errors="coerce")
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(set(L.id)) & U.person_id.isin(set(PU.index))]; day = dict(zip(L.id, L.day)); U["d"] = U.target_id.map(day); li = dict(zip(L.id, L.i))
ROLE = ["developer", "founder", "marketer", "designer", "investor", "student", "product manager"]
PROMPT = """You simulate ONE real Product Hunt user. Everything known about them:
Role keywords from their profile: {roles}
The launches they upvoted most recently (newest first):
{hist}

Today's launches:
{today}

For EACH of today's launches, rate 0-10 how likely THIS user is to upvote it, judging only from their history (what kinds of products, makers and problems they back). Use the full scale; most users upvote only a few.
Return JSON only: {{"scores": [<one integer per launch, in the order given>]}}"""
jobs = []
for D in ("2026-11-03", "2026-11-04", "2026-11-05"):
    LD = L[L.day == D].reset_index(drop=True); ids = list(LD.id); hv = U[U.d < D].groupby("person_id").size(); td = U[U.d == D]
    ok = [p for p in td.person_id.unique() if hv.get(p, 0) >= 10]; pick = rng.choice(ok, min(60, len(ok)), replace=False)
    for p in pick:
        h = U[(U.person_id == p) & (U.d < D)].sort_values("d", ascending=False); hid = list(h.target_id[:25])
        hist = "\n".join(f"- {L.name[li[t]]}: {L.tagline[li[t]]}" for t in hid); order = list(rng.permutation(len(ids)))
        today = "\n".join(f"{k + 1}. {LD.name[j]} - {LD.tagline[j]}. {(LD.description[j] or '')[:180]}" for k, j in enumerate(order))
        y = np.array([ids[j] in set(td[td.person_id == p].target_id) for j in order]); tv = X[[li[t] for t in h.target_id]].mean(0)
        emb = X[[li[ids[j]] for j in order]] @ tv; pop = np.array([votes.get(ids[j], np.nan) for j in order])
        jobs.append({"day": D, "p": p, "prompt": PROMPT.format(roles=", ".join(r for r in ROLE if A.loc[p, r]) or "none given", hist=hist, today=today), "y": y, "emb": emb, "pop": np.nan_to_num(pop), "n": len(order)})
def run(j):
    try:
        s = json.loads(llm.gemini_call(j["prompt"], 600))["scores"]; return np.array(s[:j["n"]], float) if len(s) >= j["n"] else None
    except Exception: return None
with cf.ThreadPoolExecutor(8) as ex: R = list(ex.map(run, jobs))
rows = []
for j, s in zip(jobs, R):
    if s is None or j["y"].all() or not j["y"].any(): continue
    rows.append({"day": j["day"], "sim": roc_auc_score(j["y"], s + 1e-6 * j["emb"]), "emb": roc_auc_score(j["y"], j["emb"]), "pop": roc_auc_score(j["y"], j["pop"]),
                 "blend": roc_auc_score(j["y"], pd.Series(s).rank().values + pd.Series(j["emb"]).rank().values), "n_voted": int(j["y"].sum()), "top3_hits": int(j["y"][np.argsort(-(s + 1e-6 * j["emb"]))[:3]].sum()), "emb_top3_hits": int(j["y"][np.argsort(-j["emb"])[:3]].sum())})
T = pd.DataFrame(rows)
def ci(v): b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(3000)]; return [round(float(v.mean()), 3), round(float(np.percentile(b, 2.5)), 3), round(float(np.percentile(b, 97.5)), 3)]
out = {"people_scored": len(T), "people_asked": len(jobs), "launches_per_day": {d: int((L.day == d).sum()) for d in ("2026-11-03", "2026-11-04", "2026-11-05")},
       "within_person_auc": {k: ci(T[k].values) for k in ("sim", "emb", "pop", "blend")}, "sim minus emb (paired)": ci((T.sim - T.emb).values), "blend minus emb (paired)": ci((T.blend - T.emb).values),
       "sim minus pop (paired)": ci((T.sim - T["pop"]).values), "top3 picks that were real votes: sim / embedding / votes cast": [int(T.top3_hits.sum()), int(T.emb_top3_hits.sum()), int(T.n_voted.sum())],
       "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}
json.dump(out, open(f"{OUT}/simtest.json", "w"), indent=1); print(json.dumps(out, indent=1))
