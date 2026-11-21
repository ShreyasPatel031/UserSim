"""Forward score, part 1 (orchestrator 06:43Z Nov 15): the persona panel frozen in results/web/explain/<day>.json vs the day's real comments from
the official PH API live capture (raw/ph_at_launch/<day>/api_comments + live/comments_ts; no fetch). Team comments dropped (hunter / maker user ids,
and a maker's first top-level comment). Same prompts as the harness: reactions_eval TRUTH + JUDGE, complaints_eval CT + CJ. Launches with >= 5
non-team comments. Launch bootstrap. No usernames read or written (ids only).
    python forward_says.py <day> <scratchpad>"""
import glob, html, json, os, re, subprocess, sys, numpy as np, pandas as pd, concurrent.futures as cf
D, SP = sys.argv[1:3]; HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"; W = os.path.join(SP, f"fs_{D}"); os.makedirs(W + "/api", exist_ok=True)
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm
rng = np.random.default_rng(0); gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
subprocess.run(f"gsutil -q -m cp '{B}/raw/ph_at_launch/{D}/api_comments/*.jsonl' {W}/api/; gsutil -q cp {B}/raw/ph_at_launch/{D}/live/comments_ts.jsonl {W}/", shell=True)
RE = open(os.path.join(HERE, "reactions_eval.py")).read(); CE = open(os.path.join(HERE, "complaints_eval.py")).read()
TRUTH = re.search(r'TRUTH = """(.*?)"""', RE, re.S).group(1); JUDGE = re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1)
CT = re.search(r'CT = """(.*?)"""', CE, re.S).group(1); CJ = re.search(r'CJ = """(.*?)"""', CE, re.S).group(1)
rows = []
for f in glob.glob(W + "/api/*.jsonl"):
    for l in open(f):
        if l.strip(): x = json.loads(l); rows.append((str(x["post_id"]), str(x["comment_id"]), str(x.get("commenter_user_id")), x.get("parentId"), x.get("createdAt"), x.get("snapshot_at"), x.get("body") or ""))
if os.path.exists(W + "/comments_ts.jsonl"):
    for l in open(W + "/comments_ts.jsonl"):
        if l.strip(): x = json.loads(l); rows.append((str(x["launch_id"]), str(x["comment_id"]), str(x.get("commenter_user_id")), x.get("parent_id"), x.get("created_at"), x.get("snapshot_ts"), x.get("body") or ""))
C = pd.DataFrame(rows, columns=["post", "cid", "uid", "parent", "created", "snap", "body"]).sort_values("snap").drop_duplicates("cid", keep="last")
T0 = {str(x["id"]): x for x in json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json"))}
team = {i: {str((x.get("user") or {}).get("id"))} | {str(m.get("id")) for m in (x.get("makers") or [])} for i, x in T0.items()}
C["team"] = [u in team.get(p, set()) for p, u in zip(C.post, C.uid)]
clean = lambda b: re.sub(r"@[A-Za-z0-9_]{2,}", "", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b)))).strip()
C["text"] = C.body.map(clean); NT = C[~C.team & (C.text.str.len() > 25)]
EX = json.loads(gcat(f"{B}/results/web/explain/{D}.json"))["launches"]
def g(p, mt):
    try: return json.loads(llm.gemini_call(p, mt))
    except Exception: return None
PLAIN = """Here is a product launching on Product Hunt today.
Name: {n}
Tagline: {t}
Description: {d}
Write {k} short comments that Product Hunt users would leave on this launch. JSON only: {{"comments": ["...", ...]}}"""
def judge(th, ct, cand):
    Bt = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(cand)); r = {}
    j = g(JUDGE.format(a="\n".join(f"{i + 1}. {t['theme']}" for i, t in enumerate(th)), b=Bt), 900) if th else None
    if j and len(j.get("a_covered", [])) == len(th):
        ac = np.array([bool(v) for v in j["a_covered"]]); w = np.array([t["n"] for t in th], float)
        r.update({"scored": True, "recall": float(ac.mean()), "recall_w": float((ac * w).sum() / w.sum()), "precision": float(np.mean([bool(v) for v in j.get("b_present", [])[:len(cand)]])), "n_themes": len(th)})
    if ct:
        j2 = g(CJ.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(ct)), b=Bt), 1200)
        if j2 and len(j2.get("a_covered", [])) == len(ct): r["complaint_recall"] = float(np.mean([bool(v) for v in j2["a_covered"]])); r["n_complaints"] = len(ct)
    return r
def one(lid):
    cm = NT[NT.post == lid].sort_values("created").text.tolist(); pan = ((EX.get(lid) or {}).get("say") or {}).get("persona_panel") or {}
    cand = [f"{x.get('reaction', '')} Concern: {x.get('concern', '')} Question: {x.get('question', '')}" for x in pan.get("items", [])]
    if len(cm) < 5 or not cand: return {"id": lid, "n_comments": len(cm), "scored": False, "why": "fewer than 5 non-team comments" if len(cm) < 5 else "no panel"}
    c = "\n".join(f"- {t[:400]}" for t in cm[:40]); th = [{"theme": str(t.get("theme", "")), "n": max(1, int(t.get("n_comments", 1) or 1))} for t in ((g(TRUTH.format(c=c), 2000) or {}).get("themes") or []) if isinstance(t, dict) and t.get("theme")][:8]
    ct = [str(t) for t in ((g(CT.format(c=c), 1200) or {}).get("themes") or [])][:6]
    r = {"id": lid, "n_comments": len(cm), "n_personas": len(cand), "scored": False}; r.update(judge(th, ct, cand))
    t0 = T0.get(lid) or {}; pl = (g(PLAIN.format(n=t0.get("name", ""), t=t0.get("tagline", ""), d=str(t0.get("description") or "")[:800], k=len(cand)), 3000) or {}).get("comments") or []
    pl = [str(x) for x in pl if x][:len(cand)]
    if pl: r.update({"plain_" + k: v for k, v in judge(th, ct, pl).items()})
    return r
ids = [i for i in EX if i in T0]
with cf.ThreadPoolExecutor(6) as ex: R = list(ex.map(one, ids))
S = pd.DataFrame([r for r in R if r.get("scored")])
def ci(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) < 2: return [round(float(100 * v.mean()), 1), None, None] if len(v) else None
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]; return [round(float(100 * v.mean()), 1), round(float(100 * np.percentile(b, 2.5)), 1), round(float(100 * np.percentile(b, 97.5)), 1)]
out = {"day": D, "source": "official PH API v2 live capture (api_comments + live/comments_ts), no fetch", "launches_in_explain": len(ids), "comments_unique": int(len(C)), "non_team_comments": int(len(NT)),
       "launches_scored (>= 5 non-team comments)": int(len(S)), "not_scored": {k: int(v) for k, v in pd.Series([r.get("why") for r in R if not r.get("scored")]).fillna("judge reply unusable").value_counts().items()},
       "recall [95% launch bootstrap]": ci(S.recall) if len(S) else None, "recall_w": ci(S.recall_w) if len(S) else None, "precision": ci(S.precision) if len(S) else None,
       "complaint_recall": ci(S.complaint_recall.dropna()) if len(S) and "complaint_recall" in S else None, "launches_with_complaints": int(S.complaint_recall.notna().sum()) if len(S) and "complaint_recall" in S else 0,
       "plain_recall": ci(S.plain_recall.dropna()) if "plain_recall" in S else None, "plain_precision": ci(S.plain_precision.dropna()) if "plain_precision" in S else None,
       "plain_complaint_recall": ci(S.plain_complaint_recall.dropna()) if "plain_complaint_recall" in S else None,
       "harness reference (276 past launches, 24-persona panel)": {"recall": 62.8, "recall_w": 73.3, "precision": 54.2, "complaint_recall": 24.8},
       "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3), "per_launch": [{k: v for k, v in r.items()} for r in R]}
os.makedirs(os.path.join(HERE, "reports", "forward_sim"), exist_ok=True); json.dump(out, open(os.path.join(HERE, "reports", "forward_sim", f"forward_says_{D}.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "per_launch"}, indent=1))
