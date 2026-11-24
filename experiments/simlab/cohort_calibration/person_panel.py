"""Person-built panel (WHAT-PANEL-3 deploy, orchestrator 14:29Z Nov 24). For day D, per launch on the 00:05 line-up: the reference selection
(simharness/run_what_panel.py build: held complete people with >= 3 comments before D and >= 1 upvote in the 60 days before D, ranked by topic
share, ties by 30-day upvotes; top 30), a fixed-seed draw of 15 (order = permutation seeded by md5(launch id + D)), one gemini-2.5-flash call
each at temperature 0.7 on FT_PROMPT with the last sentence replaced by a privacy line and the JSON instruction. Privacy guard: drop a comment
that the maker-like regex flags or that names a launch from that person's own rendered history (then take the next person in the draw).
Writes say.person_built_panel (comments only, no person keys) into results/web/explain/<D>.json and a private file with ids, prompts and raw.
    python person_panel.py <D> <scratchpad> [--rehearsal] [--no-upload]"""
import concurrent.futures as cf, hashlib, json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import sim_model  # noqa: E402
D, SP = sys.argv[1:3]; REH = "--rehearsal" in sys.argv; UP = "--no-upload" not in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; CV = os.path.join(SP, "cv"); BENCH = os.path.join(SP, "bench_v0", "data"); W = os.path.join(SP, f"person_panel_{D}")
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
os.makedirs(W, exist_ok=True); LU = os.path.join(W, "lineup.json"); open(LU, "w").write(gcat(f"{B}/raw/daily/{D}/today_0005.json"))
r = subprocess.run([sys.executable, "-m", "simharness.run_what_panel", "build", "--bench", BENCH, "--lineup", LU, "--day", D, "--out", W], cwd=CV, capture_output=True, text=True)
if r.returncode: sys.exit("selection failed: " + r.stderr[-800:])
ROWS = [json.loads(l) for l in open(os.path.join(W, "eval.jsonl"))]
PEOPLE = pd.read_parquet(os.path.join(BENCH, "people.parquet"), columns=["person_idx", "person_id"]).set_index("person_idx").person_id.to_dict()
SLUG2ID = {str(x.get("slug")): str(x["id"]) for x in json.load(open(LU))}
OLD = "This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\nkind of question or praise, as their past comments show. Reply with the comment only."
NEW = ("This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\nkind of question or praise, as their past comments show. "
       "Do not mention your own name, employer or products. Answer in JSON only: {\"comment\": \"...\"}")
MAKER = re.compile(r"\b(we built|we('| a)re (excited|thrilled|launching)|our (team|launch|product)|thanks for (the )?(support|hunting)|i built|we launched|hunting us|my (startup|company|product)|co-?founder|founder of|maker of|(hey|hi|hello) product hunt|i'?m \w+,? (the )?(co-?founder|founder|maker|ceo|cto)|we('ve| have) (built|been building)|our (users|customers|app|tool|platform))\b", re.I)
SELFNAME = re.compile(r"\b[A-Z][a-z]{2,} here\b|\b(I'?m|I am|my name is) [A-Z][a-z]{2,}\b(?! (excited|glad|happy|curious|interested|impressed))")
def own_names(prompt):   # launch names in the person's rendered history: "- YYYY-MM-DD: Name | ..." and "- on Name: ..."
    h = prompt.split("TODAY'S LAUNCH:")[0]; names = set()
    for m in re.finditer(r"^- \d{4}-\d{2}-\d{2}: (.+?) \|", h, re.M): names.add(m.group(1).strip())
    for m in re.finditer(r'^- on (.+?): "', h, re.M): names.add(m.group(1).strip())
    out = set()
    for n in names:   # also the leading word of multi-word names (e.g. "Hindsight" in "Hindsight 1.0 + Memlake") when it is distinctive
        out.add(n); w = re.split(r"[\s:+|-]", n)[0]
        if len(w) >= 5 and w.lower() not in {"smart", "super", "simple", "better", "first", "agent", "open", "cloud", "build", "magic"}: out.add(w)
    return {n for n in out if len(n) >= 4}
by_launch = {}
for row in ROWS: by_launch.setdefault(row["meta"]["slug"], []).append(row)
def gen(row):
    prompt = row["messages"][0]["content"]; p2 = prompt.replace(OLD, NEW) if OLD in prompt else prompt + "\n\nDo not mention your own name, employer or products. Answer in JSON only: {\"comment\": \"...\"}"
    raw = None
    try: raw = sim_model.call(p2, 300, temperature=0.7); c = str(json.loads(raw).get("comment", "")).strip()
    except Exception: c = ""
    c = re.sub(r"@[A-Za-z0-9_.-]+", "@someone", " ".join(c.split()))
    why = "empty" if not c else "maker_like" if MAKER.search(c) else "self_named" if SELFNAME.search(c) else "names_own_history_product" if any(n.lower() in c.lower() for n in own_names(prompt)) else None
    return {"prompt": p2, "raw": raw, "comment": c, "drop": why}
OUTW, PRIV, STATS = {}, [], {"launches": 0, "calls": 0, "dropped": {}}
for slug, rows in by_launch.items():
    lid = SLUG2ID.get(slug)
    if not lid: continue
    order = list(np.random.default_rng(int(hashlib.md5((lid + D).encode()).hexdigest()[:8], 16)).permutation(len(rows)))
    kept, pos = [], 0
    while len(kept) < 15 and pos < len(order):
        need = min(15 - len(kept), len(order) - pos); batch = [rows[i] for i in order[pos:pos + need]]; pos += need
        with cf.ThreadPoolExecutor(8) as ex: res = list(ex.map(gen, batch))
        STATS["calls"] += len(batch)
        for row, g in zip(batch, res):
            PRIV.append({"day": D, "launch_id": lid, "person_id": PEOPLE.get(row["meta"]["person_idx"]), "prompt": g["prompt"], "raw": g["raw"], "comment": g["comment"], "drop": g["drop"]})
            if g["drop"]: STATS["dropped"][g["drop"]] = STATS["dropped"].get(g["drop"], 0) + 1
            else: kept.append(g["comment"])
    OUTW[lid] = kept[:15]; STATS["launches"] += 1
LABEL = ("Person-built panel: 15 comments per launch, each written by Gemini 2.5 Flash from one real held member's own history before the day "
         "(their latest upvotes and comments) and the launch's 00:05 line-up fields only; members chosen by how closely their upvotes match the "
         "launch's topics. Tested on Nov 21-23 (24 launches): added to the persona panel it raised theme precision +8.5 [+0.3, +16.5] and complaint "
         "recall +8.7 [+2.9, +14.7] points with recall not lower. Not for display without Shreyas's decision (individual-history text).")
p = os.path.join(SP, "explain", f"{D}.json"); J = json.loads(gcat(f"{B}/results/web/explain/{D}.json") or "{}")
if not J.get("launches"): sys.exit("no explain file for D")
for lid, cm in OUTW.items():
    if lid in J["launches"]:
        J["launches"][lid].setdefault("say", {})["person_built_panel"] = {"comments": cm, "n": len(cm), "model": sim_model.MODEL, "temperature": 0.7,
                                                                           "rehearsal_late_unscored": bool(REH), "label": LABEL}
os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(J, open(p, "w"), indent=1)
pv = os.path.join(tempfile.gettempdir(), f"person_panel_{D}.parquet"); pd.DataFrame(PRIV).to_parquet(pv, index=False)
STATS.update({"usd": sim_model.usd(), "day": D, "rehearsal": REH})
if UP:
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/explain/{D}.json"], check=True)
    subprocess.run(["gsutil", "-q", "cp", pv, f"{B}/tmp/e5/private/person_panel/{D}.parquet"], check=True)
    open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a").write(json.dumps({"t": "person_panel", "day": D, "provider": "gcp", "usd": STATS["usd"]}) + "\n")
print(json.dumps(STATS))
