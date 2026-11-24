"""WHAT-PANEL-3 (orchestrator 14:23Z Nov 24): full persona panel plus 0 / 8 / 11 / 15 person-built Flash comments (3 seeds). Based on WHAT-PANEL-2 (orchestrator 14:14Z Nov 24): persona panel vs person-built Flash comments vs mixes, equal size 22, 5 subsample seeds, frozen
consensus truth for Nov 21-23, 3 judge runs per launch and arm-seed. Aggregates only.
    python what_panel2.py <scratchpad> <out json>"""
import concurrent.futures as cf, json, os, re, subprocess, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); SIM = os.path.dirname(HERE); SP, OUT = sys.argv[1:3]; DAYS = ["2026-11-21", "2026-11-22", "2026-11-23"]
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
RE = open(os.path.join(SIM, "reactions_eval.py")).read(); CE = open(os.path.join(SIM, "complaints_eval.py")).read()
JUDGE = re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1); CJ = re.search(r'CJ = """(.*?)"""', CE, re.S).group(1)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
def g(p, mt):
    try: return json.loads(llm.gemini_call(p, mt))
    except Exception: return None
def judge(th, ct, cand):
    Bt = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(cand)); r = {}
    j = g(JUDGE.format(a="\n".join(f"{i + 1}. {t['theme']}" for i, t in enumerate(th)), b=Bt), 900) if th else None
    if j and len(j.get("a_covered", [])) == len(th):
        ac = np.array([bool(v) for v in j["a_covered"]]); w = np.array([t["n"] for t in th], float)
        r.update({"recall": float(ac.mean()), "recall_w": float((ac * w).sum() / w.sum()), "precision": float(np.mean([bool(v) for v in j.get("b_present", [])[:len(cand)]]))})
    if ct:
        j2 = g(CJ.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(ct)), b=Bt), 1200)
        if j2 and len(j2.get("a_covered", [])) == len(ct): r["complaint_recall"] = float(np.mean([bool(v) for v in j2["a_covered"]]))
    return r
ARMS = {"panel": (999, 0), "panel + 8": (999, 8), "panel + 11": (999, 11), "panel + 15": (999, 15)}; NSEED = 3
jobs, launches = [], {}
for D in DAYS:
    TR = json.load(open(os.path.join(SIM, "reports", "forward_sim", "truth", f"truth_{D}.v1.json")))["launches"]
    FS = [r["id"] for r in json.load(open(os.path.join(SIM, "reports", "forward_sim", f"forward_says_{D}.v1.json")))["per_launch"] if r.get("scored")]
    EX = json.loads(gcat(f"gs://usersim-bakeoff-347838016394/usersim_sim/results/web/explain/{D}.json"))["launches"]
    T0 = {str(x["id"]): x for x in json.loads(gcat(f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{D}/today_0005.json"))}
    s2i = {str(x.get("slug")): i for i, x in T0.items() if x.get("slug")}
    fl = os.path.join(SP, "what_panel" if D == "2026-11-23" else f"what_panel_{D[-2:]}", "gemini_flash.json"); FL = json.load(open(fl))["launches"]
    for lid in FS:
        slug = next((s for s, i in s2i.items() if i == lid), None); pb = [str(x)[:300] for x in (FL.get(slug) or []) if str(x).strip()]
        pan = ((EX.get(lid) or {}).get("say") or {}).get("persona_panel") or {}
        pp = [f"{x.get('reaction', '')} Concern: {x.get('concern', '')} Question: {x.get('question', '')}" for x in pan.get("items", [])]
        if not pb or not pp or lid not in TR: continue
        launches[(D, lid)] = {"n_panel": len(pp), "n_person": len(pb)}
        for arm, (a, b) in ARMS.items():
            for seed in range(NSEED):
                rg = np.random.default_rng(seed * 1000 + int(lid) % 997)
                cand = [pp[i] for i in sorted(rg.choice(len(pp), min(a, len(pp)), replace=False))] + [pb[i] for i in sorted(rg.choice(len(pb), min(b, len(pb)), replace=False))]
                rg.shuffle(cand)
                for run in range(3): jobs.append(((D, lid, arm, seed, run), TR[lid]["themes"], TR[lid]["complaints"], cand))
print("launches", len(launches), "jobs", len(jobs), flush=True)
with cf.ThreadPoolExecutor(12) as ex: RES = list(ex.map(lambda j: (j[0], judge(j[1], j[2], j[3])), jobs))
M = ("recall", "recall_w", "precision", "complaint_recall"); V = {}
for (D, lid, arm, seed, run), r in RES:
    for m in M:
        if m in r: V.setdefault((D, lid, arm, seed, m), []).append(r[m])
def lv(D, lid, arm, m):   # launch value: mean over seeds of (mean over judge runs)
    s = [np.mean(V[(D, lid, arm, sd, m)]) for sd in range(NSEED) if V.get((D, lid, arm, sd, m))]; return float(np.mean(s)) if s else np.nan
def seed_spread(arm, m, keys):   # spread across seeds of the pooled mean
    per = [np.nanmean([np.mean(V[(D, l, arm, sd, m)]) if V.get((D, l, arm, sd, m)) else np.nan for (D, l) in keys]) for sd in range(NSEED)]
    return [round(100 * float(min(per)), 1), round(100 * float(max(per)), 1)]
rng = np.random.default_rng(0)
def ci(v):
    v = np.asarray([x for x in v if x == x], float)
    if len(v) < 2: return None
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return [round(100 * float(v.mean()), 1), round(100 * float(np.percentile(b, 2.5)), 1), round(100 * float(np.percentile(b, 97.5)), 1), int(len(v))]
def block(keys):
    out = {}
    for arm in ARMS:
        a = {m: ci([lv(D, l, arm, m) for (D, l) in keys]) for m in M}
        a["seed spread of pooled mean [min, max]"] = {m: seed_spread(arm, m, keys) for m in M}
        if arm != "panel": a["minus panel (paired)"] = {m: ci([lv(D, l, arm, m) - lv(D, l, "panel", m) for (D, l) in keys]) for m in M}
        r, p = a["recall"], a["precision"]
        a["meets recall>=70 & precision>=50"] = {"point": bool(r and p and r[0] >= 70 and p[0] >= 50), "lower ends": bool(r and p and r[1] >= 70 and p[1] >= 50)}
        out[arm] = a
    return out
keys = sorted(launches)
out = {"days": DAYS, "launches_scored": len(keys), "per_day_launches": {D: sum(1 for k in keys if k[0] == D) for D in DAYS},
       "panel size per launch (mean)": round(float(np.mean([v["n_panel"] for v in launches.values()])), 1),
       "note": "[mean %, launch-bootstrap 2.5%, 97.5%, launches]; launch value = mean over 3 seeds of the added draw of the mean over 3 judge runs; frozen consensus truth v1",
       "pooled": block(keys), "per day": {D: block([k for k in keys if k[0] == D]) for D in DAYS}}
out["usd"] = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 3)
json.dump(out, open(OUT, "w"), indent=1)
open(os.path.join(SIM, "spend.jsonl"), "a").write(json.dumps({"t": "what_panel3", "provider": "gcp", "usd": out["usd"]}) + "\n")
for arm, a in out["pooled"].items(): print(arm, {m: a[m] for m in M}, a.get("minus panel (paired)"), a["meets recall>=70 & precision>=50"], a["seed spread of pooled mean [min, max]"])
print("usd", out["usd"])
