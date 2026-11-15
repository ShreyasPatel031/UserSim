"""Step 1: launches of the last 150 days with >= 30 tracked voters + today's 15; Gemini embeddings of name+tagline+description; k-means product kinds."""
import json, os, sys, re, time, urllib.request, subprocess, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/kinds"; D = "2026-11-15"
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict")
from pipeline import warehouse
import llm
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
print(list(W.columns))
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); U["target_id"] = U.target_id.astype(str)
nv = U.groupby("target_id").size(); d0 = (pd.Timestamp(D) - pd.Timedelta(days=150)).strftime("%Y-%m-%d")
H = W[(W.day >= d0) & (W.day < "2026-11-13") & (W.id.map(nv).fillna(0) >= 30)].copy()
T = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{D}/today_0005.json"], capture_output=True, text=True).stdout)
T = pd.DataFrame([{"id": str(x["id"]), "day": D, "name": x["name"], "tagline": x.get("tagline"), "description": x.get("description"),
                   "topics": json.dumps([e["node"]["name"] for e in ((x.get("topics") or {}).get("edges") or [])])} for x in T])
desc = "description" if "description" in H.columns else None
L = pd.concat([H[["id", "day", "name", "tagline"] + ([desc] if desc else []) + ["topics"]], T]).drop_duplicates("id", keep="last").reset_index(drop=True)
L["txt"] = [f"{n}. {t}. {(d if isinstance(d, str) else '')[:900]}" for n, t, d in zip(L.name, L.tagline, L.get("description", [""] * len(L)))]
print("launches", len(L), "hist", len(H), "with description", int(L.get("description", pd.Series(dtype=str)).notna().sum()))
tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
RV = open("/home/user/UserSim/experiments/simlab/reactions_v2.py").read(); EMB = re.search(r'EMB = "([^"]+)"', RV).group(1)
def embed(texts):
    out = []
    for i in range(0, len(texts), 100):
        for a in range(4):
            try:
                req = urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "CLUSTERING"} for t in texts[i:i + 100]], "parameters": {"outputDimensionality": 256}}).encode(),
                                             {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
                j = json.load(urllib.request.urlopen(req, timeout=180)); break
            except Exception as e: print("retry", str(e)[:200], flush=True); time.sleep(5 * (a + 1)); j = None
        out.append(np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32)); print(i, flush=True)
    X = np.vstack(out); return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
X = embed(list(L.txt)); np.save(f"{OUT}/launch_emb.npy", X); L.drop(columns=["txt"]).to_parquet(f"{OUT}/launches.parquet")
print("saved", X.shape, "approx usd", round(sum(len(t) for t in L.txt) / 4 / 1e6 * 0.15, 3))
