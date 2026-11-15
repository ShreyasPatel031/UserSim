"""Per product of a day's top 10: pull (lift) per parent group and subgroup from the real voters of its 30 most similar past launches; its closest
competitors with their REAL audience lifts; opportunities = subgroups a competitor drew far above what this product is predicted to draw, sized by the
subgroup's share of all votes; the real comments those subgroup members left on the competitor."""
import json, sys, os, re, gzip, glob, html, subprocess, urllib.request, numpy as np, pandas as pd
SP, DAY, LIVE = sys.argv[1:4]; OUT = f"{SP}/kinds"
sys.path.insert(0, "/home/user/UserSim/experiments"); from pipeline import warehouse
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); G = json.load(open(f"{OUT}/regroup.json")); PU = pd.read_parquet(f"{OUT}/people_units2.parquet").set_index("person_id")
SN = {s["id"]: s["name"] for s in G["subgroups"]}; SPAR = {s["id"]: s["parent_name"] for s in G["subgroups"]}; O = json.load(open(f"{OUT}/analysis.json")); kn = {k["id"]: k["name"] for k in O["kinds"]}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id", "extra"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates()
CE = E[(E.kind == "comment") & E.person_id.isin(set(PU.index))][["person_id", "extra"]]; del E
U["target_id"] = U.target_id.astype(str); hist = set(L.id[L.day < "2026-11-13"]); U = U[U.target_id.isin(hist) & U.person_id.isin(set(PU.index))]; U["s"] = U.person_id.map(PU["sub"])
ct = pd.crosstab(U.target_id, U.s); ct = ct[ct.sum(1) >= 30]; base = ct.sum(0) / ct.values.sum(); a = 20.0
MIX = (ct + a * base.values).div(ct.sum(1) + a, axis=0); LIFT = MIX / base.values; cand = list(MIX.index); li = dict(zip(L.id, L.i)); XC = X[[li[l] for l in cand]]
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W = W.set_index("id")
# comments by tracked people on past launches: comment id -> person
CE["cid"] = CE.extra.map(lambda e: str(json.loads(e).get("comment_id")) if isinstance(e, str) and e.startswith("{") else None); c2p = dict(zip(CE.cid, CE.person_id))
def comments_on(lids):
    out = {l: [] for l in lids}; want = set(lids)
    for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
        for line in gzip.open(f):
            if not any(l in line[:400].decode("utf8", "ignore") or True for l in ()): pass
            try: p_ = json.loads(json.loads(line)["html"])["data"]["post"]
            except Exception: continue
            if not p_ or str(p_.get("id")) not in want: continue
            def walk(nd):
                i = str(nd.get("id")); t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", nd.get("bodyHtml") or ""))).strip()
                if i in c2p and len(t) > 30: out[str(p_["id"])].append((int(PU["sub"][c2p[i]]), t[:420]))
                for e in ((nd.get("replies") or {}).get("edges") or []): walk(e["node"])
            for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
    return out
S = sorted([json.loads(l) for l in open(f"{LIVE}/snap.jsonl")], key=lambda r: -(r.get("votesCount") or 0))[:10]
T0 = {str(x["id"]): x for x in json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{DAY}/today_0005.json"], capture_output=True, text=True).stdout)}
CM = pd.DataFrame([json.loads(l) for l in open(f"{LIVE}/comments_ts.jsonl")]).sort_values("snapshot_ts").drop_duplicates("comment_id", keep="last")
SITES = json.load(open(f"{OUT}/sites14.json")) if os.path.exists(f"{OUT}/sites14.json") and DAY == "2026-11-14" else {}
ids = [str(r["id"]) for r in S if str(r["id"]) in T0]
tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
EMB = re.search(r'EMB = "([^"]+)"', open("/home/user/UserSim/experiments/simlab/reactions_v2.py").read()).group(1)
tx = [f"{T0[l]['name']}. {T0[l].get('tagline')}. {(T0[l].get('description') or '')[:900]}" for l in ids]
j = json.load(urllib.request.urlopen(urllib.request.Request(EMB, json.dumps({"instances": [{"content": t[:2000], "task_type": "CLUSTERING"} for t in tx], "parameters": {"outputDimensionality": 256}}).encode(),
              {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}), timeout=180))
Z = np.array([p["embeddings"]["values"] for p in j["predictions"]], np.float32); Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9; np.save(f"{OUT}/top10_emb_{DAY}.npy", Z)
clean = lambda b: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b or ""))).strip()
prods, need = [], set()
for r in S:
    lid = str(r["id"]); t0 = T0.get(lid)
    if not t0: continue
    z = Z[ids.index(lid)]; sim = XC @ z; order = np.argsort(-sim); nb = order[:30]
    pl = LIFT.values[nb].mean(0); pm = MIX.values[nb].mean(0); pl = pd.Series(pl, index=LIFT.columns); pm = pd.Series(pm, index=LIFT.columns)
    par = {}
    for s in LIFT.columns: par.setdefault(SPAR[s], [0.0, 0.0]); par[SPAR[s]][0] += pm[s]; par[SPAR[s]][1] += base[s]
    comps = []
    for jx in order[:10]:
        c = cand[jx]; row = L.iloc[li[c]]; w = W.loc[c] if c in W.index else None
        comps.append({"id": c, "name": row["name"], "tagline": row["tagline"], "day": row["day"], "similarity": round(float(sim[jx]), 3), "kind": kn[int(row["kind"])],
                      "votes": None if w is None else (None if pd.isna(pd.to_numeric(w.votes, errors="coerce")) else int(pd.to_numeric(w.votes))), "daily_rank": None if w is None or pd.isna(pd.to_numeric(w.daily_rank, errors="coerce")) else int(pd.to_numeric(w.daily_rank)),
                      "tracked_voters": int(ct.loc[c].sum()), "lift": {int(s): round(float(LIFT.loc[c, s]), 2) for s in LIFT.columns}, "n": {int(s): int(ct.loc[c, s]) for s in LIFT.columns},
                      "description": (row.get("description") or "")[:700]})
    opp = []
    for c in comps:
        for s in LIFT.columns:
            gap = c["lift"][int(s)] - float(pl[s])
            if c["n"][int(s)] >= 8 and c["lift"][int(s)] >= 1.5 and gap >= 0.5:
                opp.append({"subgroup": SN[s], "sub_id": int(s), "parent": SPAR[s], "competitor": c["name"], "competitor_id": c["id"], "competitor_lift": c["lift"][int(s)], "product_lift": round(float(pl[s]), 2),
                            "subgroup_share_of_all_votes": round(float(base[s]), 3), "gain_points_of_voter_share": round(float(base[s] * gap) * 100, 1), "competitor_votes_from_subgroup": c["n"][int(s)]})
    opp.sort(key=lambda o: -o["gain_points_of_voter_share"]); seen, best = set(), []
    for o in opp:
        if o["sub_id"] in seen: continue
        seen.add(o["sub_id"]); best.append(o)
    best = best[:4]; need |= {o["competitor_id"] for o in best} | {c["id"] for c in comps[:4]}
    cm = CM[CM.launch_id.astype(str) == lid].sort_values("created_at"); bodies = [clean(b) for b in cm.body.dropna()]
    prods.append({"id": lid, "rank": r.get("dailyRank"), "name": r["name"], "votes": r["votesCount"], "comments": r["commentsCount"], "tagline": t0.get("tagline"), "description": t0.get("description"),
                  "topics": [e["node"]["name"] for e in ((t0.get("topics") or {}).get("edges") or [])], "maker_intro": bodies[0][:1800] if bodies else None, "real_comments": bodies[1:26],
                  "site_text": (SITES.get(lid) or {}).get("text"), "site_url": (SITES.get(lid) or {}).get("url"),
                  "parent_pull": {g: {"lift": round(v[0] / v[1], 2), "share": round(v[0], 3)} for g, v in par.items()},
                  "subgroup_pull": [{"sub_id": int(s), "subgroup": SN[s], "parent": SPAR[s], "lift": round(float(pl[s]), 2), "share": round(float(pm[s]), 3)} for s in pl.sort_values(ascending=False).index],
                  "competitors": comps, "opportunities": best})
CC = comments_on(need)
for p in prods:
    for o in p["opportunities"]: o["subgroup_members_comments_on_competitor"] = [t for s, t in CC.get(o["competitor_id"], []) if s == o["sub_id"]][:8]; o["all_tracked_comments_on_competitor"] = len(CC.get(o["competitor_id"], []))
    for c in p["competitors"]: c["tracked_comments"] = [{"subgroup": SN[s], "text": t} for s, t in CC.get(c["id"], [])][:12]
json.dump({"day": DAY, "base_share": {SN[s]: round(float(base[s]), 3) for s in base.index}, "products": prods}, open(f"{OUT}/compete_{DAY}.json", "w"), indent=1)
for p in prods:
    print("\n#", p["rank"], p["name"], "| parents", {g: v["lift"] for g, v in p["parent_pull"].items()})
    print("   top subgroups:", [(x["subgroup"], x["lift"], f"{round(100 * x['share'], 1)}%") for x in p["subgroup_pull"][:3]], "| lowest:", [(x["subgroup"], x["lift"]) for x in p["subgroup_pull"][-2:]])
    print("   competitors:", [(c["name"], c["similarity"], c["votes"], c["daily_rank"]) for c in p["competitors"][:6]])
    for o in p["opportunities"]: print("   OPP:", o["subgroup"], "| via", o["competitor"], o["competitor_lift"], "vs", o["product_lift"], "| +", o["gain_points_of_voter_share"], "pts | comments by them:", len(o["subgroup_members_comments_on_competitor"]), "/", o["all_tracked_comments_on_competitor"])
