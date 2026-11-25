"""PRODUCT-USE-0 scorer (PREREG addendum 12). Per product: the 3 users' non-artefact problems and likes are merged (one Gemini call,
temperature 0) into at most 6 complaints and 6 likes, the same shape as the homepage-only baseline (REVIEW-TRUTH-1 BASELINE: <= 6 + 6).
Both arms are judged here, in the same run, on the frozen review truth with the same prompts (complaints_eval.CJ for complaints,
reactions_eval.JUDGE for likes), 3 runs averaged; the baseline arm reuses its cached predictions (review_truth_wip/llm_cache.jsonl).
Paired differences (sim - homepage) with bootstrap intervals over products (2,000 draws, seed 0).
Artefact check: the share of the sim's complaints that are about access (signup, login, verification, captcha, blocked) vs the share of
truth complaints about access.
  python pu0_score.py  ->  results/calibration/pu0/product_use/pu0_score.json
"""
import concurrent.futures as cf, io, json, os, re, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); SIMLAB = os.path.join(HERE, ".."); sys.path.insert(0, os.path.join(SIMLAB, "cohort_calibration"))
import sim_model  # noqa: E402
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; TX = f"{B}/simharness/taxonomy"; PUB = f"{B}/results/calibration/pu0/product_use"
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
T = pd.read_parquet(io.BytesIO(cat(f"{TX}/review_truth.parquet"))).set_index("product")
OUT = json.loads(cat(f"{PUB}/outputs.json")); F = pd.DataFrame(OUT["findings"])
BL = {}
for l in cat(f"{TX}/review_truth_wip/llm_cache.jsonl").decode().splitlines():
    x = json.loads(l)
    if x["k"].startswith("baseline|"): BL[x["k"].split("|", 1)[1]] = x["v"] or {}
CE, RE = open(os.path.join(SIMLAB, "complaints_eval.py")).read(), open(os.path.join(SIMLAB, "reactions_eval.py")).read()
CJ = re.search(r'CJ = """(.*?)"""', CE, re.S).group(1); JUDGE = re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1)
def g(p, mt):
    r = sim_model.call(p, max_tokens=mt, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
    try: return json.loads(m.group(0))
    except Exception: return None
MERGE = """Several people each tried the product {p} and noted problems and likes. Merge their notes into the product's distinct complaints
and distinct likes (paraphrases of the same point count once; keep the most frequent first). Product-level points only.
Problems:\n{a}\nLikes:\n{b}\nJSON only: {{"complaints": ["<under 16 words>", ... at most 6], "likes": ["<under 16 words>", ... at most 6]}}"""
ACCESS = re.compile(r"sign ?up|signup|log ?in|login|verif|captcha|account creat|blocked|access denied|email code|sms|phone number", re.I)
def judge(tc, tl, pc, pl):
    runs = []
    for _ in range(3):
        x = {}
        if tc and pc:
            j = g(CJ.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(tc)), b="\n".join(f"{i + 1}. {t}" for i, t in enumerate(pc))), 1200)
            if j and len(j.get("a_covered", [])) == len(tc):
                x["complaint_recall"] = float(np.mean([bool(v) for v in j["a_covered"]]))
                bm = j.get("b_matches", [])[:len(pc)]
                if bm: x["complaint_precision"] = float(np.mean([bool(v) for v in bm]))
        if tl and pl:
            j = g(JUDGE.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(tl)), b="\n".join(f"{i + 1}. {t}" for i, t in enumerate(pl))), 900)
            if j and len(j.get("a_covered", [])) == len(tl):
                x["like_recall"] = float(np.mean([bool(v) for v in j["a_covered"]])); x["like_precision"] = float(np.mean([bool(v) for v in j.get("b_present", [])[:len(pl)]]))
        runs.append(x)
    return {m: (float(np.mean([r[m] for r in runs if m in r])) if any(m in r for r in runs) else np.nan)
            for m in ("complaint_recall", "complaint_precision", "like_recall", "like_precision")}
def one(prod):
    g_ = F[(F.launch_id == prod) & (F.slot == "launch")]; ok = g_[g_.artefact == "none"]
    row = {"product": prod, "n_users": int(len(g_)), "n_clean": int(len(ok)), "artefact_rate": float((g_.artefact != "none").mean()) if len(g_) else None,
           "would_use": float(ok.would_use.astype(float).mean()) if len(ok) else None}
    tc, tl = list(T.loc[prod, "complaints"]), list(T.loc[prod, "likes"])
    if not len(ok) or prod not in BL: return row
    probs = [p for ps in ok.problems for p in (ps or [])]; likes = [p for ps in ok.likes for p in (ps or [])]
    mg = g(MERGE.format(p=prod, a="\n".join(f"- {x}" for x in probs) or "-", b="\n".join(f"- {x}" for x in likes) or "-"), 900) or {}
    pc, pl = [str(x) for x in (mg.get("complaints") or [])][:6], [str(x) for x in (mg.get("likes") or [])][:6]
    bc, bl = [str(x) for x in (BL[prod].get("complaints") or [])][:6], [str(x) for x in (BL[prod].get("likes") or [])][:6]
    s, h = judge(tc, tl, pc, pl), judge(tc, tl, bc, bl)
    row.update({f"sim_{k}": v for k, v in s.items()}); row.update({f"home_{k}": v for k, v in h.items()})
    row.update(sim_access_share=float(np.mean([bool(ACCESS.search(x)) for x in pc])) if pc else None,
               truth_access_share=float(np.mean([bool(ACCESS.search(x)) for x in tc])) if tc else None, n_sim_c=len(pc), n_sim_l=len(pl))
    return row
prods = list(dict.fromkeys(F.launch_id)) if len(F) else []
with cf.ThreadPoolExecutor(8) as ex: R = pd.DataFrame(list(ex.map(one, prods)))
rng = np.random.default_rng(0); res = {}
for m in ("complaint_recall", "complaint_precision", "like_recall", "like_precision"):
    d = R[["sim_" + m, "home_" + m]].dropna() if "sim_" + m in R else pd.DataFrame()
    if len(d) < 5: res[m] = {"n": int(len(d))}; continue
    diff = (d["sim_" + m] - d["home_" + m]).to_numpy(); bs = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)]
    res[m] = {"n": int(len(d)), "sim": round(100 * d["sim_" + m].mean(), 1), "home": round(100 * d["home_" + m].mean(), 1),
              "diff": round(100 * diff.mean(), 1), "ci95": [round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]}
S = {"arm": "PRODUCT-USE-0", "scored_at": pd.Timestamp.now(tz="UTC").isoformat(), "products_run": len(prods), "products_scored": int(R.get("sim_complaint_recall", pd.Series(dtype=float)).notna().sum()),
     "clean_session_rate": float(R.n_clean.sum() / max(R.n_users.sum(), 1)) if len(R) else None, "paired": res,
     "artefact_check": {"sim_access_share": float(R.sim_access_share.mean()) if "sim_access_share" in R else None,
                        "truth_access_share": float(R.truth_access_share.mean()) if "truth_access_share" in R else None},
     "model_usd_sessions": OUT.get("model_usd_sessions"), "rows": R.to_dict("records")}
p = "/tmp/pu0_score.json"; json.dump(S, open(p, "w"), indent=1, default=str); subprocess.run(["gsutil", "-q", "cp", p, f"{PUB}/pu0_score.json"])
print(json.dumps({k: v for k, v in S.items() if k != "rows"}, default=str))
