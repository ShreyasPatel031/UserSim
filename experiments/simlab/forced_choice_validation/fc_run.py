"""Forced-choice panel on every held featured launch of 30 days (Sep 18 - Nov 5 2026). As run for the launch plan: one persona per distinct
segment of the launch's same-topic backer pool (30 days strictly before the day), the real line-up of that day (name, tagline, first 160
characters of the maker's description; order shuffled per call), each persona picks 3 and places the target launch in its ordering.
argv: SP PASS(seed) [days json]. Appends to fcv/fc_pass<PASS>.jsonl (resumable). Stops at USD_STOP."""
import json, os, re, sys, importlib.util, numpy as np, pandas as pd, concurrent.futures as cf, threading
SP, PASS = sys.argv[1], int(sys.argv[2]); OUT = f"{SP}/fcv"; HERE = "/home/user/UserSim/experiments/simlab"; STOP = float(os.environ.get("USD_STOP", 9))
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
L = pd.read_parquet(f"{OUT}/launches.parquet"); cards = json.load(open(f"{OUT}/cards.json")); days = json.loads(sys.argv[3]) if len(sys.argv) > 3 else sorted(L.day.unique())
sp_ = importlib.util.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = importlib.util.module_from_spec(sp_); sp_.loader.exec_module(pm)
FCP = re.search(r'FCP = """(.*?)"""', open(f"{SP}/chain/run.py").read(), re.S).group(1)
usd = lambda: llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5; path = f"{OUT}/fc_pass{PASS}.jsonl"; lock = threading.Lock()
done = {json.loads(l)["id"] for l in open(path)} if os.path.exists(path) else set()
def one(r):
    if usd() > STOP: return
    P_ = list({p["segment"]: p for p in (cards.get(f"l-{r.id}") or {}).get("personas") or []}.values())
    if not P_: return
    g = L[L.day == r.day]; order = np.random.default_rng(abs(hash((r.id, PASS))) % 2**32).permutation(len(g)); g = g.iloc[order].reset_index(drop=True)
    code = f"L{int(np.where(g.id == r.id)[0][0]) + 1}"; items = "\n".join(f"[L{k + 1}] {x['name']} — {x.tagline}. {(x.description or '')[:160]}" for k, x in g.iterrows())
    try:
        res = json.loads(re.search(r"\{.*\}", llm.gemini_call(FCP.format(code=code, groups="\n".join(pm.gtxt(k, gg) for k, gg in enumerate(P_)), n=len(g), items=items), 4500), re.S).group(0))["personas"]
        rows = []
        for x in res:
            k = int(x.get("group", 0)) - 1
            if not 0 <= k < len(P_): continue
            pk = [g.id[int(str(c).strip("[]L")) - 1] for c in x.get("picks", []) if str(c).strip("[]L").isdigit() and 0 < int(str(c).strip("[]L")) <= len(g)]
            rows.append({"seg": P_[k]["segment_profile"].get("segment_id"), "group": P_[k]["segment"].split(" / ")[0], "n_people": P_[k]["n_people"], "picked": r.id in pk, "place": min(max(float(x.get("place") or len(g)), 1), len(g)) / len(g), "picks": pk})
        with lock: open(path, "a").write(json.dumps({"id": r.id, "day": r.day, "n": len(g), "rows": rows}) + "\n")
    except Exception as e:
        with lock: open(f"{OUT}/fc_err{PASS}.log", "a").write(f"{r.id} {type(e).__name__} {str(e)[:120]}\n")
todo = [r for r in L[L.day.isin(days)].itertuples() if r.id not in done]; print("todo", len(todo), flush=True)
with cf.ThreadPoolExecutor(12) as ex:
    for i, _ in enumerate(ex.map(one, todo)):
        if i % 100 == 0: print(i, round(usd(), 2), flush=True)
print("done usd", round(usd(), 3), "rows", sum(1 for _ in open(path)))
