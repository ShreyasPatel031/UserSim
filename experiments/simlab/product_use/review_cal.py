"""PRODUCT-USE-1 calibration on competitors (PREREG addendum 11, metric 3): simulated users' problems / likes on a competitor vs that
competitor's real PH reviews dated after Gemini 2.5 Flash's training cutoff (2025-01-31); and the simulated preference between the two
competitors vs their post-cutoff mean review rating. Reviews: raw/ph_predict_data/competitor_reviews.jsonl.gz (+ any file in
raw/ph_reviews/*.jsonl.gz delivered later). Reviewer names are never read.
  python review_cal.py D [--rehearsal]  ->  results/calibration/D/product_use/review_cal.json
"""
import glob, gzip, json, os, re, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "cohort_calibration"))
import sim_model  # noqa: E402
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; D = [a for a in sys.argv[1:] if not a.startswith("--")][0]; REH = "--rehearsal" in sys.argv
PUB = f"{B}/{'_rehearsal/' if REH else ''}results/calibration/{D}/product_use"; CUTOFF = "2025-02-01"
gj = lambda p: json.loads(subprocess.run(["gsutil", "cat", p], capture_output=True).stdout or b"null")
LU, OUT = gj(f"{PUB}/lineup.json"), gj(f"{PUB}/outputs.json")
RV = {}
srcs = [f"{B}/raw/ph_predict_data/competitor_reviews.jsonl.gz"] + subprocess.run(["gsutil", "ls", f"{B}/raw/ph_reviews/*.jsonl.gz"], capture_output=True, text=True).stdout.split()
for s in srcs:
    raw = subprocess.run(["gsutil", "cat", s], capture_output=True).stdout
    for l in (gzip.decompress(raw).decode().splitlines() if raw else []):
        x = json.loads(l); R = x.get("reviews") or []
        R = eval(R) if isinstance(R, str) else R
        keep = [{"rating": r.get("rating"), "text": (r.get("text") or "")[:500], "pros": r.get("pros"), "cons": r.get("cons"), "date": r.get("date")}
                for r in R if str(r.get("date") or "") >= CUTOFF and (r.get("text") or r.get("pros") or r.get("cons"))]
        for k in {str(x.get("competitor") or "").lower(), str(x.get("slug") or "").lower()} - {""}: RV.setdefault(k, []).extend(keep)
F = pd.DataFrame((OUT or {}).get("findings", []))
def J(p, mt):
    r = sim_model.call(p, max_tokens=mt, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
    try: return json.loads(m.group(0))
    except Exception: return {}
rows, prefs = [], []
for l in LU["launches"]:
    for k, c in enumerate(l.get("competitors") or []):
        rv = RV.get(c["name"].lower(), [])
        sim = F[(F.launch_id == l["id"]) & (F.slot == f"comp{k + 1}") & (F.artefact == "none")] if len(F) else F
        row = {"launch_id": l["id"], "competitor": c["name"], "category": l["category"], "n_reviews_post_cutoff": len(rv), "n_sim_users": int(len(sim))}
        if len(rv) >= 5 and len(sim):
            txt = "\n".join(f"- ({r['rating']}/5) {r['text']} Pros: {r['pros'] or ''} Cons: {r['cons'] or ''}"[:600] for r in rv[:40])
            tr = J(f"Real user reviews of {c['name']}:\n{txt}\n\nList the distinct problems and the distinct likes these reviewers report (product-level themes). "
                   'JSON only: {"problems": ["<under 14 words>", ...up to 6], "likes": ["<under 14 words>", ...up to 6]}', 900)
            cand = [p for ps in sim.problems for p in (ps or [])] + [p for ps in sim.likes for p in (ps or [])]
            real = (tr.get("problems") or []) + (tr.get("likes") or [])
            if real and cand:
                j = J("List A (real reviewers' themes):\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(real)) + "\n\nList B (simulated users' findings):\n"
                      + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(cand)) + "\n\nFor each item of A: is it covered by some item of B (same point, paraphrase allowed)? "
                      "For each item of B: is it present in A? JSON only: {\"a_covered\": [true|false, ...], \"b_present\": [true|false, ...]}", 900)
                if len(j.get("a_covered", [])) == len(real):
                    row.update(recall=float(np.mean(j["a_covered"])), precision=float(np.mean(j.get("b_present", [])[:len(cand)] or [0])),
                               n_real=len(real), n_cand=len(cand))
            row["review_rating_mean"] = float(np.mean([float(r["rating"]) for r in rv if str(r["rating"]).replace(".", "").isdigit()] or [np.nan]))
        rows.append(row)
    a = [r for r in rows if r["launch_id"] == l["id"] and r.get("review_rating_mean") is not None and not np.isnan(r.get("review_rating_mean", np.nan))]
    if len(a) == 2 and len(F):
        g = F[(F.launch_id == l["id"]) & (F.artefact == "none") & F.slot.isin(["comp1", "comp2"])].groupby("slot").pref_rank.mean()
        if len(g) == 2 and g["comp1"] != g["comp2"]:
            prefs.append({"launch_id": l["id"], "agree": bool((g["comp1"] < g["comp2"]) == (a[0]["review_rating_mean"] > a[1]["review_rating_mean"]))})
R = pd.DataFrame(rows)
S = {"day": D, "rehearsal": REH, "cutoff": CUTOFF, "competitors": len(R), "with_5plus_post_cutoff_reviews": int((R.n_reviews_post_cutoff >= 5).sum()) if len(R) else 0,
     "scored": int(R["recall"].notna().sum()) if "recall" in R else 0, "recall_mean": float(R["recall"].mean()) if "recall" in R and R["recall"].notna().any() else None,
     "precision_mean": float(R["precision"].mean()) if "precision" in R and R["precision"].notna().any() else None,
     "preference_vs_rating_agree": (float(np.mean([p["agree"] for p in prefs])) if prefs else None), "n_pref_pairs": len(prefs), "rows": rows}
p = f"/tmp/pu_rc_{D}.json"; json.dump(S, open(p, "w"), indent=1, default=str); subprocess.run(["gsutil", "-q", "cp", p, f"{PUB}/review_cal.json"])
print(json.dumps({k: v for k, v in S.items() if k != "rows"}))
