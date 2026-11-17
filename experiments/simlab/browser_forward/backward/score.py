"""Score the backward browser test. Arms on the same launches: browser findings; plain prompt on the pitch (arm B of ../complaint_recall,
reused unchanged); the two merged. Truth, strict same-issue rule and blind pooled judge are those of ../complaint_recall."""
import json, os, re, sys, glob, threading, numpy as np, pandas as pd, concurrent.futures as cf
SP = sys.argv[1]; OUT = f"{SP}/bw"; CR = f"{SP}/cr"
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
usd = lambda: llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5; lock = threading.Lock(); scrub = lambda s: re.sub(r"@\w+", "", str(s)); rng = np.random.default_rng(0)
ld = lambda p: {json.loads(l)["id"]: json.loads(l)["v"] for l in open(p)}
T = ld(f"{CR}/truth.jsonl"); B = ld(f"{CR}/armB.jsonl")
X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "day", "name", "tagline", "description", "topics"]); X["id"] = X.id.astype(str); X = X.drop_duplicates("id").set_index("id")
L = {}
for f in glob.glob(f"{OUT}/launches/*.json"):
    d = json.load(open(f))
    if d.get("cells") and sum(c["outcome"] != "error" for c in d["cells"]) >= 4: L[d["launch_id"]] = d
ids = sorted(i for i in L if i in T and i in B); print("launches run", len(L), "scorable", len(ids))
def cache(name, keys, fn, workers=10):
    path = f"{OUT}/{name}.jsonl"; done = {json.loads(l)["id"]: json.loads(l)["v"] for l in open(path)} if os.path.exists(path) else {}
    def w(i):
        try:
            v = fn(i)
            with lock: open(path, "a").write(json.dumps({"id": i, "v": v}) + "\n"); done[i] = v
        except Exception as e:
            with lock: open(f"{OUT}/score_err.log", "a").write(f"{name} {i} {type(e).__name__} {str(e)[:120]}\n")
    with cf.ThreadPoolExecutor(workers) as ex: list(ex.map(w, [i for i in keys if i not in done]))
    print(name, len(done), "usd", round(usd(), 2), flush=True); return {i: done[i] for i in keys if i in done}
J = lambda t: json.loads(re.search(r"\{.*\}", t, re.S).group(0))
pitch = lambda i: f"Product: {X.name[i]} — {X.tagline[i]}\nTopics: {', '.join(list(X.topics[i])[:4])}\nDescription: {(X.description[i] or '')[:600]}"
FMT = 'Return JSON only: {"complaints": ["<under 18 words>", ... exactly 10, most likely first], "questions": ["<under 18 words>", ... exactly 10, most likely first]}'
ASK = "Predict what real Product Hunt commenters will say on launch day: the 10 complaints, doubts or worries they are most likely to raise, and the 10 questions they are most likely to ask the makers. Be specific to this product."
lst = lambda v: {"complaints": [scrub(x) for x in v.get("complaints", [])][:10], "questions": [scrub(x) for x in v.get("questions", [])][:10]}
def ftxt(i):
    out = []
    for c in L[i]["cells"]:
        out.append(f"Task: {c['task']}\n  Ended: {c['outcome']}. {c['notes']}" + "".join(f"\n  - [{f['kind']}] {f['what']}" for f in c["findings"]))
    return "\n".join(out)
BR = cache("armBrowser", ids, lambda i: lst(J(llm.gemini_call(f"Product: {X.name[i]} — {X.tagline[i]}\n\nSix first-time visitors each tried one task on this product's live website, without creating an account. What happened:\n\n{ftxt(i)}\n\nFrom what these visitors ran into, and only from that, list the 10 complaints, doubts or worries and the 10 questions that real Product Hunt commenters are most likely to raise about this product.\n{FMT}", 1500))))
MG = cache("armMerged", ids, lambda i: lst(J(llm.gemini_call(f"{pitch(i)}\n\nSix first-time visitors each tried one task on this product's live website, without creating an account. What happened:\n\n{ftxt(i)}\n\n{ASK} Use what the visitors ran into as evidence.\n{FMT}", 1500))))
ARMS = {"Browser": BR, "B": {i: B[i] for i in ids}, "Merged": MG}
def judge(key):
    i, kind = key.split("|"); real = T[i][kind]
    if not real: return {"m": {}}
    items = sorted({x for a in ARMS.values() if i in a for x in a[i][kind]}); items = [items[k] for k in np.random.default_rng(abs(hash(key)) % 2**32).permutation(len(items))]
    r = J(llm.gemini_call(f"A product launched on Product Hunt.\n{pitch(i)}\n\nREAL {kind} raised by commenters:\n" + "\n".join(f"R{k + 1}: {x['theme']}" for k, x in enumerate(real)) + f"\n\nPREDICTED {kind} (written before launch):\n" + "\n".join(f"P{k + 1}: {x}" for k, x in enumerate(items)) +
        "\n\nFor each predicted item, say which real item it matches, if any. MATCH only if the prediction names the same specific issue: a reader of the real comment would agree the prediction anticipated it. The same broad topic alone (for example both mention pricing, but one asks about a free tier and the other about enterprise billing) is NOT a match. Most predictions match nothing.\n"
        "Return JSON only: {\"matches\": {\"P1\": \"R3\" or null, ...}} with every predicted item.", 60 * len(items) + 300))["matches"]
    return {"m": {items[int(k[1:]) - 1]: (int(v[1:]) - 1 if isinstance(v, str) and v[1:].isdigit() and 0 < int(v[1:]) <= len(real) else None) for k, v in r.items() if k[1:].isdigit() and 0 < int(k[1:]) <= len(items)}}
JG = cache("judge", [f"{i}|{k}" for i in ids for k in ("complaints", "questions")], judge)
rows = []
for i in ids:
    for kind in ("complaints", "questions"):
        real = T[i][kind]; m = (JG.get(f"{i}|{kind}") or {}).get("m")
        if not real or m is None or any(i not in a for a in ARMS.values()): continue
        for a, P in ARMS.items():
            for k in (5, 10):
                hit = [m.get(x) for x in P[i][kind][:k]]; rows.append({"id": i, "kind": kind, "arm": a, "k": k, "recall": len({h for h in hit if h is not None}) / len(real), "precision": float(np.mean([h is not None for h in hit])) if hit else np.nan})
R = pd.DataFrame(rows)
def ci(v, d=False):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; f = "+.1f" if d else ".1f"
    return f"{v.mean()*100:{f}} [{np.percentile(b,2.5)*100:{f}}, {np.percentile(b,97.5)*100:{f}}]"
O = {"launches_run": len(L), "launches_scored": len(ids), "tables": {}, "paired": {}}
for kind in ("complaints", "questions"):
    for k in (5, 10):
        g = R[(R.kind == kind) & (R.k == k)]; p = g.pivot(index="id", columns="arm", values="recall"); q = g.pivot(index="id", columns="arm", values="precision")
        O["tables"][f"{kind} top {k}"] = {a: {"n": int(p[a].notna().sum()), "recall": ci(p[a]), "precision": ci(q[a])} for a in ARMS}
        O["paired"][f"{kind} top {k}"] = {"Browser minus B": ci(p.Browser - p.B, True), "Merged minus B": ci(p.Merged - p.B, True), "Merged minus Browser": ci(p.Merged - p.Browser, True)}
cells = [c for d in L.values() for c in d["cells"]]; oc = pd.Series([c["outcome"] for c in cells]).value_counts()
bt = pd.DataFrame([{"task": k, "outcome": c["outcome"], "steps": c["steps"], "findings": len(c["findings"]), "seconds": c["seconds"]} for d in L.values() for k, c in enumerate(d["cells"])])
O["operations"] = {"cells": len(cells), "outcomes_pct": (oc / len(cells) * 100).round(1).to_dict(), "finished_on_their_own_pct": round(float(bt.outcome.isin(["completed", "gave_up", "blocked"]).mean() * 100), 1), "completed_pct": round(float((bt.outcome == "completed").mean() * 100), 1),
    "minutes_per_launch_median": float(np.median([d["minutes"] for d in L.values()])), "minutes_per_launch_p90": float(np.percentile([d["minutes"] for d in L.values()], 90)), "browser_seconds_per_launch_mean (sum over 6 cells)": round(float(bt.groupby(np.arange(len(bt)) // 6).seconds.sum().mean()), 0),
    "steps_per_launch_mean": round(float(np.mean([sum(c["steps"] for c in d["cells"]) for d in L.values()])), 1), "findings_per_launch_mean": round(float(np.mean([sum(len(c["findings"]) for c in d["cells"]) for d in L.values()])), 1),
    "launches_with_any_bug_finding_pct": round(float(np.mean([any(f["kind"] == "bug" for c in d["cells"] for f in c["findings"]) for d in L.values()]) * 100), 1),
    "by_task": {int(k): {"completed_pct": round(float((g.outcome == "completed").mean() * 100)), "step_cap_pct": round(float((g.outcome == "step_cap").mean() * 100)), "error_pct": round(float((g.outcome == "error").mean() * 100)), "mean_steps": round(float(g.steps.mean()), 1)} for k, g in bt.groupby("task")},
    "producthunt_requests_blocked": int(sum(c.get("ph_requests_blocked", 0) for c in cells)), "finding_kinds": pd.Series([f["kind"] for c in cells for f in c["findings"]]).value_counts().to_dict()}
json.dump(O, open(f"{OUT}/results.json", "w"), indent=1); print(json.dumps(O, indent=1))
S = []
for key, v in JG.items():
    i, kind = key.split("|"); real = T[i][kind]; br = set(BR.get(i, {}).get(kind, [])) | set(MG.get(i, {}).get(kind, []))
    for p, r in v["m"].items():
        if p in br: S.append((int(r is not None), X.name[i], kind, p, real[r]["theme"] if r is not None else " || ".join(x["theme"] for x in real)[:400]))
S = pd.DataFrame(S, columns=["match", "product", "kind", "pred", "real"]); pd.concat([S[S.match == 1].sample(min(15, int(S.match.sum())), random_state=2), S[S.match == 0].sample(15, random_state=2)]).to_json(f"{OUT}/handcheck.json", orient="records", indent=1)
print("score usd", round(usd(), 2), "match rate", round(S.match.mean(), 3))
