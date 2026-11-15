"""PREREG_grounded_interviews.md: PERSONA vs PERSONA+REAL vs REAL-ONLY on 40 past launches, strict judge against the launch's own real comments."""
import json, sys, os, re, gzip, glob, html, numpy as np, pandas as pd, concurrent.futures as cf
SP = sys.argv[1]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(0); NL = int(os.environ.get("NL", 40))
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
from pipeline import warehouse
G = json.load(open(f"{OUT}/regroup.json")); SUB = {s["id"]: s for s in G["subgroups"]}
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); PU = pd.read_parquet(f"{OUT}/people_units2.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str)
J_ = lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else []
team = {i: {str(x).lower() for x in J_(m) if x} | ({str(p).lower()} if isinstance(p, str) and p else set()) for i, m, p in zip(W.id, W.makers, W.poster)}
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id", "extra"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates()
CE = E[(E.kind == "comment") & E.person_id.isin(set(PU.index))][["person_id", "extra"]]; del E
CE["cid"] = CE.extra.map(lambda e: str(json.loads(e).get("comment_id")) if isinstance(e, str) and e.startswith("{") else None); c2p = dict(zip(CE.cid, CE.person_id))
U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(set(L.id[L.day < "2026-11-13"])) & U.person_id.isin(set(PU.index))]; U["s"] = U.person_id.map(PU["sub"]); li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day))
ct = pd.crosstab(U.target_id, U.s); ct = ct[ct.sum(1) >= 30]; base = ct.sum(0) / ct.values.sum(); LIFT = ((ct + 20 * base.values).div(ct.sum(1) + 20, axis=0)) / base.values; cand = list(LIFT.index); XC = X[[li[l] for l in cand]]; dc = np.array([day[l] for l in cand])
nvotes = U.groupby("person_id").size(); TC = pd.read_parquet(f"{OUT}/tracked_comments.parquet"); pc = TC.groupby("person_id").size()
# all comments on embedded launches: (launch, is_team, subgroup or -1, text, created order)
cache = f"{OUT}/all_comments.parquet"
if os.path.exists(cache): AC = pd.read_parquet(cache)
else:
    rows = []; want = set(L.id)
    for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
        for line in gzip.open(f):
            try: p_ = json.loads(json.loads(line)["html"])["data"]["post"]
            except Exception: continue
            if not p_ or str(p_.get("id")) not in want: continue
            lid = str(p_["id"]); tm = team.get(lid, set())
            def walk(nd, depth):
                un = str(((nd.get("user") or {}).get("username")) or "").lower(); t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", nd.get("bodyHtml") or ""))).strip()
                t = re.sub(r"@[A-Za-z0-9_]{2,}", "", t)
                if len(t) > 40: rows.append((lid, un in tm or bool(nd.get("isMaker")), int(PU["sub"].get(c2p.get(str(nd.get("id"))), -1)) if c2p.get(str(nd.get("id"))) in PU.index else -1, t[:420], depth))
                for e in ((nd.get("replies") or {}).get("edges") or []): walk(e["node"], depth + 1)
            for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"], 0)
    AC = pd.DataFrame(rows, columns=["launch_id", "team", "sub", "text", "depth"]).drop_duplicates(["launch_id", "text"]); AC.to_parquet(cache)
nt = AC[~AC.team]; cnt = nt.groupby("launch_id").size(); print("launches with comments", AC.launch_id.nunique(), "non-team comments", len(nt), flush=True)
pool = [l for l in L.id[(L.day >= os.environ.get("WIN0", "2026-10-20")) & (L.day <= "2026-11-10")] if cnt.get(l, 0) >= 10 and l in li]; test = list(rng.choice(pool, min(NL, len(pool)), replace=False)); print("pool", len(pool), "test", len(test), flush=True)
ROLE = ["developer", "founder", "marketer", "designer", "investor", "student", "product manager"]
def persona(pid, D):
    h = U[(U.person_id == pid)].assign(d=lambda x: x.target_id.map(day)); h = h[h.d < D].sort_values("d", ascending=False).head(12); cm = TC[(TC.person_id == pid) & (TC.launch_id.map(day).fillna("9") < D)].head(2)
    return ("roles: " + (", ".join(r for r in ROLE if A.loc[pid, r]) or "not stated") + "; recently upvoted: " + "; ".join(f"{L.name[li[t]]} ({L.tagline[li[t]]})" for t in h.target_id) +
            ("; their own past comments: " + " || ".join(f"\"{b[:220]}\"" for b in cm.text) if len(cm) else ""))
FMT = "JSON only: {\"points\": [\"<one specific concern or question, one sentence>\", ... exactly 12]}"
def one(lid):
    i = li[lid]; D = day[lid]; r = L.iloc[i]; mk = AC[(AC.launch_id == lid) & AC.team & (AC.depth == 0)].text.head(1).tolist()
    ptxt = f"NAME: {r['name']}\nTAGLINE: {r['tagline']}\nDESCRIPTION: {(r['description'] or '')[:900]}" + (f"\nMAKER'S LAUNCH NOTE: {mk[0][:1200]}" if mk else "")
    ok = dc < D; s = XC[ok] @ X[i]; order = np.argsort(-s); cl = [c for c, o in zip(cand, ok) if o]; nb30 = [cl[j] for j in order[:30]]; pl = LIFT.loc[nb30].mean(0)
    tops = [s_ for s_ in pl.sort_values(ascending=False).index if "All-round" not in SUB[s_]["name"]][:4]; ppl = []
    for s_ in tops:
        mem = [m for m in PU.index[PU["sub"] == s_] if nvotes.get(m, 0) >= 12]; hc = [m for m in mem if pc.get(m, 0) >= 1]; pl_ = hc if len(hc) >= 3 else mem
        for m in rng.choice(pl_, min(3, len(pl_)), replace=False): ppl.append((s_, m))
    users = "\n".join(f"{k + 1}. subgroup {SUB[s_]['name']} ({SUB[s_]['goes_for']}); {persona(m, D)}" for k, (s_, m) in enumerate(ppl))
    nb12 = [cl[j] for j in order[:60] if cnt.get(cl[j], 0) >= 3][:12]; rc = nt[nt.launch_id.isin(set(nb12))].groupby("launch_id").head(4)
    real = "\n".join(f"- on {L.name[li[a]]} ({L.tagline[li[a]]})" + (f" [by a member of {SUB[b]['name']}]" if b >= 0 else "") + f": \"{t[:240]}\"" for a, b, t in zip(rc.launch_id, rc["sub"], rc.text))
    head = "A founder is about to launch the product below on Product Hunt and wants to know what commenters will raise. "
    PA = (head + "Below are 12 real Product Hunt users (anonymous; known by upvote history and their own past comments). For each user, give the ONE main concern or question that user would raise about THIS product, "
          "specific to its actual features. " + FMT + "\n\nPRODUCT\n" + ptxt + "\n\nUSERS\n" + users)
    PB = (head + "Below are 12 real Product Hunt users, and real comments that users left on similar earlier launches. For each user, give the ONE main concern or question that user would raise about THIS product. "
          "Use the real comments as evidence of what this audience actually asks about products like this; carry a real question over only if it applies to this product's features. " + FMT +
          "\n\nPRODUCT\n" + ptxt + "\n\nREAL COMMENTS ON SIMILAR EARLIER LAUNCHES\n" + real + "\n\nUSERS\n" + users)
    PC = (head + "Below are real comments that users left on similar earlier launches. List the 12 concerns or questions commenters are most likely to raise about THIS product; carry a real question over only if it applies to "
          "this product's features. " + FMT + "\n\nPRODUCT\n" + ptxt + "\n\nREAL COMMENTS ON SIMILAR EARLIER LAUNCHES\n" + real)
    own = nt[nt.launch_id == lid].text.tolist()[:28]
    try:
        truth = json.loads(llm.gemini_call("Real comments on a Product Hunt launch (makers' replies excluded). List the distinct concerns or questions commenters raised (max 10; skip pure praise). "
                                           "JSON only: {\"points\": [\"...\"]}\n\n" + "\n".join("- " + t[:380] for t in own), 1500))["points"][:10]
    except Exception: return None
    if len(truth) < 2: return None
    res = {"launch": r["name"], "day": D, "n_truth": len(truth), "n_neighbour_comments": len(rc)}
    for arm, pr in (("PERSONA", PA), ("PERSONA+REAL", PB), ("REAL-ONLY", PC)):
        try:
            pts = [str(x) for x in json.loads(llm.gemini_call(pr, 2500))["points"]][:12]
            j = json.loads(llm.gemini_call("Two lists about the same product. REAL: points real commenters raised. CANDIDATE: predicted points. A candidate matches a real point only if it raises the same substance (not merely the same topic). "
                                           "JSON only: {\"real_matched\": [true|false per REAL point, in order], \"candidate_matched\": [true|false per CANDIDATE point, in order]}\n\nREAL:\n" +
                                           "\n".join(f"{k + 1}. {t}" for k, t in enumerate(truth)) + "\n\nCANDIDATE:\n" + "\n".join(f"{k + 1}. {t}" for k, t in enumerate(pts)), 800))
            j2 = json.loads(llm.gemini_call("Two lists about the same product. REAL: points real commenters raised. CANDIDATE: predicted points. Here a candidate matches a real point if it is about the same TOPIC or theme (e.g. both about pricing, "
                                            "both about data export, both about platform support), even when the exact question differs. JSON only: {\"real_matched\": [true|false per REAL point, in order], \"candidate_matched\": [true|false per CANDIDATE point, in order]}\n\nREAL:\n" +
                                            "\n".join(f"{k + 1}. {t}" for k, t in enumerate(truth)) + "\n\nCANDIDATE:\n" + "\n".join(f"{k + 1}. {t}" for k, t in enumerate(pts)), 800))
            res[arm] = {"recall": float(np.mean([bool(x) for x in j["real_matched"][:len(truth)]])), "precision": float(np.mean([bool(x) for x in j["candidate_matched"][:len(pts)]])) if pts else 0.0, "n": len(pts),
                        "topic_recall": float(np.mean([bool(x) for x in j2["real_matched"][:len(truth)]])), "topic_precision": float(np.mean([bool(x) for x in j2["candidate_matched"][:len(pts)]])) if pts else 0.0, "points": pts}
            res["truth"] = truth
        except Exception: res[arm] = None
    return res
with cf.ThreadPoolExecutor(6) as ex: R = [r for r in ex.map(one, test) if r and all(r.get(a) for a in ("PERSONA", "PERSONA+REAL", "REAL-ONLY"))]
T = pd.DataFrame([{"launch": r["launch"], **{f"{a}|{m}": r[a][m] for a in ("PERSONA", "PERSONA+REAL", "REAL-ONLY") for m in ("recall", "precision", "topic_recall", "topic_precision")}} for r in R])
def ci(v): b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]; return [round(float(100 * v.mean()), 1), round(float(100 * np.percentile(b, 2.5)), 1), round(float(100 * np.percentile(b, 97.5)), 1)]
out = {"launches": len(T), "real_points": int(sum(r["n_truth"] for r in R)), "arms": {a: {m: ci(T[f"{a}|{m}"].values) for m in ("recall", "precision", "topic_recall", "topic_precision")} for a in ("PERSONA", "PERSONA+REAL", "REAL-ONLY")},
       "paired": {f"{a} minus {b}": {m: ci((T[f"{a}|{m}"] - T[f"{b}|{m}"]).values) for m in ("recall", "precision", "topic_recall", "topic_precision")} for a, b in (("PERSONA+REAL", "PERSONA"), ("PERSONA+REAL", "REAL-ONLY"), ("REAL-ONLY", "PERSONA"))},
       "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}
out["grounding helps (pre-registered)"] = out["paired"]["PERSONA+REAL minus PERSONA"]["recall"][1] > 0; out["personas add value (pre-registered)"] = out["paired"]["PERSONA+REAL minus REAL-ONLY"]["recall"][1] > 0
json.dump({**out, "per_launch": R}, open(f"{OUT}/grounded{os.environ.get('TAG', '')}.json", "w"), indent=1); print(json.dumps(out, indent=1))
