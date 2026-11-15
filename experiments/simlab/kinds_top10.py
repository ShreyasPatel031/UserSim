"""Today's top 10 (12:15 PT snapshot): product kind, predicted audience mix over the 5 taste groups = mean REAL voter mix of the 30 most similar
earlier launches (embedding kNN), lift vs the typical launch; held-out check of that predictor on the last 30 days; team's earlier backers; real comments so far."""
import json, sys, os, subprocess, numpy as np, pandas as pd
SP = sys.argv[1]; DAY = sys.argv[2]; LIVE = sys.argv[3]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0); K = 5
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
from pipeline import warehouse
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
O = json.load(open(f"{OUT}/analysis.json")); kn = {k["id"]: k["name"] for k in O["kinds"]}
NAMES = {0: "AI business & growth crowd", 1: "Model & coding-tool developers", 2: "Occasional business-tool voters", 3: "Indie app & Mac utility fans", 4: "AI creative-tool crowd"}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); U["target_id"] = U.target_id.astype(str)
Uall = U.copy(); U = U[U.target_id.isin(set(L.id)) & U.person_id.isin(set(P.index))]; U["t"] = U.person_id.map(P[f"t{K}"])
ct = pd.crosstab(U.target_id, U.t); ct = ct[ct.sum(1) >= 30]; MIX = ct.div(ct.sum(1), axis=0); base = (ct.sum(0) / ct.values.sum())
pos = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day))
def knn_mix(i, before, k=30):
    cand = [l for l in MIX.index if day[l] < before]; s = X[[pos[l] for l in cand]] @ X[i]; top = np.argsort(-s)[:k]
    return MIX.loc[[cand[j] for j in top]].mean(0), [cand[j] for j in top[:5]]
# held-out check: launches of the last 30 days of history, neighbours strictly earlier
tv_m, tv_b = [], []
for l in [l for l in MIX.index if day[l] >= "2026-10-13"]:
    m, _ = knn_mix(pos[l], day[l]); b = MIX.loc[[x for x in MIX.index if day[x] < day[l]]].mean(0)
    tv_m.append(0.5 * (MIX.loc[l] - m).abs().sum()); tv_b.append(0.5 * (MIX.loc[l] - b).abs().sum())
tv_m, tv_b = np.array(tv_m), np.array(tv_b); d = tv_m - tv_b; bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
VAL = {"launches": len(d), "distance model": round(float(tv_m.mean()), 3), "distance typical-mix": round(float(tv_b.mean()), 3),
       "paired": [round(float(d.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)]}
print("VAL", VAL, flush=True)
# today
S = sorted([json.loads(l) for l in open(f"{LIVE}/snap.jsonl")], key=lambda r: -(r.get("votesCount") or 0))[:10]
T0 = {str(x["id"]): x for x in json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{DAY}/today_0005.json"], capture_output=True, text=True).stdout)}
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
J_ = lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else []
W["team"] = [{str(x).lower() for x in J_(m) if x} | ({str(p).lower()} if isinstance(p, str) and p else set()) for m, p in zip(W.makers, W.poster)]
CM = pd.DataFrame([json.loads(l) for l in open(f"{LIVE}/comments_ts.jsonl")]).sort_values("snapshot_ts").drop_duplicates("comment_id", keep="last")
import re, urllib.request
miss = [str(r["id"]) for r in S if str(r["id"]) not in pos and str(r["id"]) in T0]
if miss:
    tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
    EMB = re.search(r'EMB = "([^"]+)"', open("/home/user/UserSim/experiments/simlab/reactions_v2.py").read()).group(1)
    tx = [f"{T0[l]['name']}. {T0[l].get('tagline')}. {(T0[l].get('description') or '')[:900]}" for l in miss]
    j = json.load(urllib.request.urlopen(urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "CLUSTERING"} for t in tx], "parameters": {"outputDimensionality": 256}}).encode(),
                  {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}), timeout=180))
    Z = np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32); Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
    C_ = np.load(f"{OUT}/kind_centroids.npy"); kd = ((Z[:, None, :] - C_[None]) ** 2).sum(2).argmin(1)
    for a, l in enumerate(miss): pos[l] = len(X) + a; day[l] = DAY
    X = np.vstack([X, Z]); KIND = {l: int(k) for l, k in zip(miss, kd)}
else: KIND = {}
rows = []
for r in S:
    lid = str(r["id"]); t0 = T0.get(lid)
    row = {"id": lid, "rank": r.get("dailyRank"), "name": r["name"], "votes": r["votesCount"], "comments": r["commentsCount"], "tagline": (t0 or {}).get("tagline")}
    if lid in pos:
        i = pos[lid]; row["kind"] = kn[KIND[lid]] if lid in KIND else kn[int(L.kind[i])]; m, nb = knn_mix(i, DAY); row["mix"] = {NAMES[c]: round(float(m[c]), 3) for c in range(K)}
        row["lift"] = {NAMES[c]: round(float(m[c] / base[c]), 2) for c in range(K)}; row["similar_past_launches"] = [L.name[pos[x]] for x in nb]; row["topics"] = [e["node"]["name"] for e in ((t0.get("topics") or {}).get("edges") or [])]
        team = {str((t0.get("user") or {}).get("username") or "").lower()} | {str(m_.get("username")).lower() for m_ in (t0.get("makers") or []) if m_.get("username")}; team.discard("")
        earlier = set(W[(W.day < DAY) & W.team.map(lambda s: bool(s & team)) & (W.id != lid)].id); bk = set(Uall[Uall.target_id.isin(earlier)].person_id)
        row["team_earlier_launches"] = len(earlier); row["team_earlier_backers_tracked"] = len(bk)
        inp = [p for p in bk if p in P.index]
        if len(inp) >= 20:
            bm = P.loc[inp, f"t{K}"].value_counts(normalize=True); pb = P[f"t{K}"].value_counts(normalize=True)
            row["team_backers_lift"] = {NAMES[c]: round(float(bm.get(c, 0) / pb[c]), 2) for c in range(K)}
            ra = A.loc[inp].mean() / A.mean(); row["team_backers_roles_lift"] = {c: round(float(ra[c]), 2) for c in ("developer", "founder", "marketer", "designer", "investor", "has launched a product", "veteran (5+ years)")}
    else: row["note"] = "not in the 00:05 list (added later); no text held"
    c = CM[CM.launch_id.astype(str) == lid]; row["real_comments_captured"] = len(c); row["_bodies"] = [b[:300] for b in c.body.dropna().tolist()][:25]
    rows.append(row)
pr = ("For each product below are real Product Hunt comments from today (some are the makers' own replies - ignore those). For each product return what "
      "commenters are actually saying: JSON only {\"products\": [{\"id\": \"<id>\", \"praise\": \"<short>\", \"concerns_or_questions\": \"<short, the specific things asked or doubted>\", \"tone\": \"<3-6 words>\"}]}. "
      "Never name people.\n\n" + "\n\n".join(f"[{r['id']}] {r['name']} - {r.get('tagline')}\n" + "\n".join("- " + b for b in r["_bodies"]) for r in rows if r["_bodies"]))
R = {str(x["id"]): x for x in json.loads(llm.gemini_call(pr, 4000))["products"]}
for r in rows: r["real_comment_themes"] = R.get(r["id"]); r.pop("_bodies")
out = {"day": DAY, "taste_groups": {NAMES[c]: {"people": int((P[f"t{K}"] == c).sum()), "share_of_votes": round(float(base[c]), 3)} for c in range(K)}, "validation_knn_mix": VAL, "top10": rows,
       "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 4)}
json.dump(out, open(f"{OUT}/top10_{DAY}.json", "w"), indent=1); 
