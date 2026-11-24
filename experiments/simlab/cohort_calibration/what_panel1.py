"""WHAT-PANEL-1 (orchestrator 14:07Z Nov 24): history-built comment arms (Qwen2.5-7B tuned / untuned, Gemini Flash) vs the persona panel and the plain
prompt on Nov 23, with E5's frozen consensus truth (reports/forward_sim/truth/truth_2026-11-23.v1.json) and the same 3-run judge as forward_says.
Scored twice: all 30 comments, and a fixed-seed subsample equal to the persona panel's size per launch (primary). Aggregates only.
    python what_panel1.py <scratchpad> <out json>"""
import concurrent.futures as cf, json, os, re, subprocess, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); SIM = os.path.dirname(HERE); SP, OUT = sys.argv[1:3]; D = "2026-11-23"
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
RE = open(os.path.join(SIM, "reactions_eval.py")).read(); CE = open(os.path.join(SIM, "complaints_eval.py")).read()
JUDGE = re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1); CJ = re.search(r'CJ = """(.*?)"""', CE, re.S).group(1)
TR = json.load(open(os.path.join(SIM, "reports", "forward_sim", "truth", f"truth_{D}.v1.json")))["launches"]
FS = {r["id"]: r for r in json.load(open(os.path.join(SIM, "reports", "forward_sim", f"forward_says_{D}.v1.json")))["per_launch"] if r.get("scored")}
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
EX = json.loads(gcat(f"gs://usersim-bakeoff-347838016394/usersim_sim/results/web/explain/{D}.json"))["launches"]
T0 = {str(x["id"]): x for x in json.loads(gcat(f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{D}/today_0005.json"))}
slug2id = {str(x.get("slug")): i for i, x in T0.items() if x.get("slug")}
ARMS = {a: json.load(open(os.path.join(SP, "what_panel", f"{a}.json")))["launches"] for a in ("qwen7b_tuned", "qwen7b_untuned", "gemini_flash")}
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
MAKER = re.compile(r"\b(we built|we('| a)re (excited|thrilled|launching)|our (team|launch|product)|thanks for (the )?(support|hunting)|i built|we launched|hunting us)\b", re.I)
jobs, info = [], {}
for lid in FS:
    slug = next((s for s, i in slug2id.items() if i == lid), None); n = FS[lid]["n_personas"]; tr = TR[lid]
    for a, L in ARMS.items():
        c = [str(x) for x in (L.get(slug) or []) if str(x).strip()]
        if not c: continue
        sub = [c[i] for i in sorted(np.random.default_rng(0).choice(len(c), min(n, len(c)), replace=False))]
        info.setdefault(a, {})[lid] = {"n_all": len(c), "n_eq": len(sub), "maker_like": sum(bool(MAKER.search(x)) for x in c)}
        for size, cand in (("all", c), ("equal", sub)):
            for run in range(3): jobs.append((lid, a, size, run, tr["themes"], tr["complaints"], [x[:300] for x in cand]))
with cf.ThreadPoolExecutor(8) as ex: RES = list(ex.map(lambda j: (j[:4], judge(j[4], j[5], j[6])), jobs))
M = ("recall", "recall_w", "precision", "complaint_recall"); S = {}
for (lid, a, size, run), r in RES:
    for m in M:
        if m in r: S.setdefault((a, size), {}).setdefault(lid, {}).setdefault(m, []).append(r[m])
val = lambda a, size, lid, m: (np.mean(S[(a, size)][lid][m]) if lid in S.get((a, size), {}) and S[(a, size)][lid].get(m) else np.nan)
ref = {"persona_panel": lambda lid, m: FS[lid].get(m, np.nan), "plain_prompt": lambda lid, m: FS[lid].get("plain_" + m, np.nan)}
rng = np.random.default_rng(0)
def ci(v):
    v = np.asarray([x for x in v if x == x], float)
    if len(v) < 2: return None
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return [round(100 * float(v.mean()), 1), round(100 * float(np.percentile(b, 2.5)), 1), round(100 * float(np.percentile(b, 97.5)), 1), int(len(v))]
L = list(FS); out = {"day": D, "launches": len(L), "truth": "frozen consensus truth v1 (3 extractions, >= 2 of 3)", "judge": "same JUDGE/CJ prompts, 3 runs per launch, mean",
                     "note": "[mean %, launch-bootstrap 2.5%, 97.5%, launches]; persona panel and plain prompt from forward_says_2026-11-23.v1.json (same truth, same 3-run protocol)",
                     "per_arm": {}, "paired (equal size, primary)": {}, "paired (all 30)": {}, "maker-like comments (all 30, regex)": {a: sum(v["maker_like"] for v in info[a].values()) for a in info},
                     "comments per launch": {a: {"all": int(np.mean([v["n_all"] for v in info[a].values()])), "equal": int(np.mean([v["n_eq"] for v in info[a].values()]))} for a in info}}
for nm, f in ref.items(): out["per_arm"][nm] = {m: ci([f(l, m) for l in L]) for m in M}
for a in ARMS:
    for size in ("equal", "all"): out["per_arm"][f"{a} ({size})"] = {m: ci([val(a, size, l, m) for l in L]) for m in M}
for size, key in (("equal", "paired (equal size, primary)"), ("all", "paired (all 30)")):
    for a in ARMS:
        for nm, f in ref.items(): out[key][f"{a} minus {nm}"] = {m: ci([val(a, size, l, m) - f(l, m) for l in L]) for m in M}
    out[key]["tuned minus untuned"] = {m: ci([val("qwen7b_tuned", size, l, m) - val("qwen7b_untuned", size, l, m) for l in L]) for m in M}
    out[key]["tuned minus flash"] = {m: ci([val("qwen7b_tuned", size, l, m) - val("gemini_flash", size, l, m) for l in L]) for m in M}
out["usd"] = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 3)
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out["paired (equal size, primary)"], indent=0)[:3000]); print("usd", out["usd"], out["maker-like comments (all 30, regex)"], out["comments per launch"])
open(os.path.join(SIM, "spend.jsonl"), "a").write(json.dumps({"t": "what_panel1", "provider": "gcp", "usd": out["usd"]}) + "\n")
