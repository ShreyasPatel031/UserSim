"""SIM-RERANK-1 Stage B v2 "pick k" (PREREG addendum 8). One call per person over the whole shortlist.
    python rerank_b2.py <store dir> <scratchpad> <D> [--dry]"""
import concurrent.futures as cf, hashlib, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.argv_b = list(sys.argv)
src = open(os.path.join(HERE, "rerank_b.py")).read().split("jobs, src_page = [], {}")[0]   # reuse inputs (shortlist, people, histories, page text)
G = {"__file__": os.path.join(HERE, "rerank_b.py"), "__name__": "rb2"}; exec(src, G)
D, SP, short, V2, active, HB, CM, INFO, topics, page, VR, sim_model, NDAY, B, deadline = (G[k] for k in ("D", "SP", "short", "V2", "active", "HB", "CM", "INFO", "topics", "page", "VR", "sim_model", "NDAY", "B", "deadline"))
lines, src_page = {}, {}
for x in short:
    lid = str(x["id"]); t, s = page(lid); src_page[lid] = s; head = t.split("\n"); lines[lid] = (head[0][:140] + (" | " + head[1][:160] if len(head) > 1 else ""))
people = []
for x in short:
    lid = str(x["id"]); rng = np.random.default_rng(int(lid)); top = V2[V2.launch_id == lid].sort_values("p", ascending=False).person_id.head(200).tolist()
    people += [(p, "backer_top") for p in (rng.choice(top, min(50, len(top)), replace=False) if top else [])] + [(p, "random_active") for p in rng.choice(active, 20, replace=False)]
seen, P = set(), []
for p, s in people:
    if p not in seen: seen.add(p); P.append((p, s))
PROMPT = """You are simulating one specific, real Product Hunt user. Everything you know about them is their own activity below.
Launches they upvoted recently (newest first):
{ups}
{cms}
Today these launches are on Product Hunt:
{lst}

On days they are active this person upvotes about {k} launch(es). Pick exactly the {k} launch(es) above this person would most likely upvote today.
JSON only: {{"picks": [<launch numbers>], "comment_on_first_pick": "<one line in their voice>"}}"""
ids = [str(x["id"]) for x in short]
def agent(arg):
    pid, srcp = arg; order = ids[:]; np.random.default_rng(int(hashlib.md5(pid.encode()).hexdigest()[:8], 16)).shuffle(order)
    k = int(min(5, max(1, round(VR.get(pid, 1.0)))))
    ups = "\n".join(f"- {INFO[i][0]} - {INFO[i][1]} [{', '.join(topics(i))}]" for i in HB.get(pid, []) if i in INFO) or "- (no upvotes visible)"
    cms = ("Their own past comments:\n" + "\n".join(f"- {c}" for c in CM.get(pid, []))) if CM.get(pid) else ""
    lst = "\n".join(f"{n + 1}. {lines[l]}" for n, l in enumerate(order))
    try: j = json.loads(sim_model.call(PROMPT.format(ups=ups, cms=cms, lst=lst, k=k), 300)); picks = [order[int(n) - 1] for n in j.get("picks", []) if 1 <= int(n) <= len(order)][:k]
    except Exception: j, picks = {}, None
    return {"person_id": pid, "panel": srcp, "k": k, "picks": picks, "comment": G["scrub"](j.get("comment_on_first_pick", ""))[:200] if j else ""}
with cf.ThreadPoolExecutor(12) as ex: A = pd.DataFrame(list(ex.map(agent, P)))
ok = A[A.picks.notna()]; n = len(ok); rows = []
for x in short:
    lid = str(x["id"]); c = sum(lid in p for p in ok.picks)
    rows.append({"id": lid, "structural_rank": x["structural_rank"], "pick_share": c / max(1, n), "picks": int(c),
                 "pick_share_backer_top": sum(lid in p for p in ok[ok.panel == "backer_top"].picks) / max(1, (ok.panel == "backer_top").sum()), "page_source": src_page[lid]})
R = pd.DataFrame(rows); zz = (R.pick_share - R.pick_share.mean()) / (R.pick_share.std() + 1e-9); R["key"] = R.structural_rank - 2 * zz
R = R.sort_values(["key", "structural_rank"]); R["rerank"] = np.arange(1, len(R) + 1)
out = {"day": D, "arm": "v2 pick-k", "frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "before_0345_pt": bool(pd.Timestamp.now(tz="UTC") < deadline), "prereg": "PREREG.md addendum 8",
       "model": sim_model.MODEL, "agents": int(n), "agent_calls": int(len(A)), "usd": sim_model.usd(), "shortlist_source": G["SL_SRC"], "launches": R.drop(columns=["key"]).to_dict("records")}
DRY = "--dry" in sys.argv_b
cal = os.path.join(tempfile.gettempdir(), f"rerank2_{D}.json"); json.dump(out, open(cal, "w"), indent=1, default=float)
pv = os.path.join(tempfile.gettempdir(), f"agents2_{D}.parquet"); A.assign(picks=A.picks.map(lambda p: json.dumps(p) if p is not None else None)).to_parquet(pv, index=False)
if not DRY:
    subprocess.run(["gsutil", "-q", "cp", cal, f"{B}/results/calibration/{D}/rerank_frozen_v2pick.json"], check=True)
    subprocess.run(["gsutil", "-q", "cp", pv, f"{B}/tmp/e5/private/agents/{D}_v2pick.parquet"], check=True)
    open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a").write(json.dumps({"t": "sim_rerank_b2", "day": D, "provider": "gcp", "usd": out["usd"], "calls": len(A)}) + "\n")
print(json.dumps({k: v for k, v in out.items() if k != "launches"}, default=float)); print(R[["structural_rank", "rerank", "pick_share", "picks"]].to_string(index=False))
