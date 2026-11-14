"""Per-launch explanation file for the website (orchestrator 21:59Z Nov 14, Shreyas's request: "who are the predicted voters, what they like,
what they didn't, what the competitors are, what they like about them"). Only data already held; no Product Hunt requests; no Gemini.
No usernames, no person ids, no commenter names: people appear only as segments of >= 20 held people.
  python explain_writer.py <day> <store dir> <scratchpad> <out dir> [--no-upload]
Output: <out>/<day>.json and gs://.../results/web/explain/<day>.json
Blocks per launch id:
  who          predicted backers as segments (keyword rule on each held person's own headline + bio), expected votes per segment from the
               voter_harness pair model (strict timing: reads fetched before 00:00 PT), n held people behind each, topics the likely backers
               upvoted in the 90 days before, coverage (measured share of a launch's votes cast by held people) + this launch's concentration
  say          predicted reactions / top concern / top question from tmp/e5/forward_sim/<day>/predictions_frozen.json + measured accuracy
  competitors  5 most similar earlier launches (local bge-small embedding of name. tagline. description over the reactions_retrieval_v1
               pool, Jan 1 - Oct 24) with launch date, final daily rank, votes, and their real commenters' themes (praise / objection),
               paraphrased by flash-lite when the pool was built (not quotes, no names)
  why          top 3 inputs of the readable explanation model from results/web/why/<day>_0005.json + its measured accuracy
"""
import json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
DAY, ST, SP, OUT = sys.argv[1:5]; UP = "--no-upload" not in sys.argv; os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"; MIN = 20
sys.path.insert(0, os.path.join(HERE, "..")); from pipeline import warehouse  # noqa: E402
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
NA = "not available"
line = json.loads(gcat(f"{B}/raw/daily/{DAY}/today_0005.json")); ids = [str(p["id"]) for p in line]

# ---------------- who ----------------
SEG = [("investors / VCs", r"\b(investor|vc|venture|angel invest|partner at)\b"),
       ("designers", r"(design|\bux\b|\bui\b|figma|illustrat|creative director)"),
       ("developers / engineers", r"(engineer|developer|\bdev\b|software|full[- ]?stack|backend|frontend|programm|coder|\bcto\b|devops|data scien|machine learning|\bml\b)"),
       ("marketers / growth", r"(marketing|marketer|growth|\bseo\b|content|brand|social media|copywrit|community manager)"),
       ("product managers", r"(product manager|\bpm\b|product lead|product owner|head of product|product @|product at)"),
       ("founders / indie makers", r"(founder|\bceo\b|indie|maker|solopreneur|bootstrap|entrepreneur|building )"),
       ("students", r"(student|university|college)")]
def seg_of(t):
    t = (t or "").lower()
    if not t.strip(): return "no headline or bio"
    for name, rx in SEG:
        if re.search(rx, t): return name
    return "other roles"
WHO, COV = {}, {}
try:
    PP = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id")
    segmap = dict(zip(PP.person_id, (PP.headline.fillna("") + " " + PP.bio.fillna("")).map(seg_of)))
    tmp = tempfile.mkdtemp(); ld = os.path.join(tmp, "launches"); os.makedirs(ld)
    WA = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); WA["id"] = WA.id.astype(str); WA = WA[~WA.id.isin(ids)]
    add = pd.DataFrame([{"id": str(p["id"]), "slug": p.get("slug"), "day": DAY, "topics": json.dumps([e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or [])]),
                         "poster": (p.get("user") or {}).get("username"), "makers": json.dumps([m.get("username") for m in (p.get("makers") or []) if m.get("username")]),
                         "daily_rank": 0.0, "votes": np.nan, "updated_at": "9999"} for p in line])
    pd.concat([WA, add], ignore_index=True)[["id", "slug", "day", "topics", "poster", "makers", "daily_rank", "votes", "updated_at"]].astype({"daily_rank": float, "updated_at": str}).to_parquet(os.path.join(ld, "l.parquet"))
    pd.DataFrame({"id": ids, "day": DAY}).to_parquet(os.path.join(tmp, "clean.parquet"))
    os.environ["EDGES"] = "hunter_maker"; argv0 = sys.argv; sys.argv = ["voter_harness.py", ST, os.path.join(tmp, "clean.parquet"), ld, os.path.join(SP, "early"), os.path.join(tmp, "o")]
    VH = open(os.path.join(HERE, "voter_harness.py")).read(); g = {"__name__": "vh", "__file__": "voter_harness.py"}
    exec(VH[:VH.index("FOLL = {}")] + "FOLL = {}\n", g); sys.argv = argv0; g["C"] = pd.DataFrame({"id": ids, "day": DAY})
    src = VH[VH.index("def expected("):VH.index("FOLL = {}")]
    src = src.replace("def expected(", "def expected_pp(").replace(
        "return {i: float(m.predict_proba(X_)[:, 1].sum()) for i, X_ in zip(lu, pair_X(act, tv, lu, follows))}, len(act)",
        "return {i: pd.Series(m.predict_proba(X_)[:, 1], index=act.index) for i, X_ in zip(lu, pair_X(act, tv, lu, follows))}, len(act), act, tv")
    exec(src, g)
    res = g["expected_pp"](DAY, "strict")
    PPROB, nact, act, tv = res if len(res) == 4 else (res[0], res[1], None, None)
    TOPN = list(g["TOP"]) if "TOP" in g else None
    seg_all = pd.Series([segmap.get(p, "no headline or bio") for p in act.index], index=act.index) if act is not None else None
    for i in ids:
        p = PPROB.get(i)
        if p is None or not isinstance(p, pd.Series) or nact < MIN: WHO[i] = {"status": NA, "reason": "vote model not fitted (fewer than 20 held active people or training upvotes)"}; continue
        df = pd.DataFrame({"p": p.values, "seg": seg_all.values}, index=p.index); tot = df.p.sum()
        rows = []
        for s, gg in df.groupby("seg"):
            if len(gg) < MIN: continue
            rows.append({"segment": s, "expected_votes": round(float(gg.p.sum()), 1), "share_of_held_expected_votes": round(float(gg.p.sum() / tot), 3) if tot > 0 else None,
                         "n_held_people_scored": int(len(gg)), "n_likely (chance >= 5%)": int((gg.p >= 0.05).sum())})
        rows.sort(key=lambda r: -r["expected_votes"])
        top = df.p.sort_values(ascending=False).index[:200]
        likes = None
        if tv is not None and TOPN:
            ix = pd.Series(np.arange(len(act)), index=act.index); w = df.p.loc[top].values
            dist = (tv[ix[top].values] * w[:, None]).sum(0) / max(w.sum(), 1e-9); o = np.argsort(-dist)[:5]
            likes = [{"topic": TOPN[j], "share_of_their_recent_upvotes": round(float(dist[j]), 3)} for j in o if dist[j] > 0]
        WHO[i] = {"segments": rows, "expected_held_votes": round(float(tot), 1), "n_held_active_people": int(nact),
                  "what_likely_backers_upvote": likes, "what_likely_backers_dislike": NA + " (we observe upvotes and follows, not dislikes)",
                  "likely_backers_definition": "the 200 held people with the highest chance of upvoting this launch; topics weighted by that chance, from their upvotes in the 90 days before the day"}
except Exception as e:
    print("who failed:", repr(e)[:300]); WHO = {i: {"status": NA, "reason": f"vote model step failed: {type(e).__name__}"} for i in ids}
WHY = json.loads(gcat(f"{B}/results/web/why/{DAY}_0005.json") or "{}")
WHO_LABEL = {"segment_rule": "keyword rule on each held person's own headline and bio (first match in this order: investors, designers, developers, marketers, product managers, founders/indie makers, students)",
             "model": "voter_harness pair model (held people's recent upvotes, topic taste, follows of the hunter and first maker; trained on the 7 previous days; reads fetched before 00:00 PT)",
             "predictive_value": "summed per launch it gave 0.0 top-3 gain over the clean forecast on 10 forward test days (Oct 29 - Nov 11): descriptive, not a vote forecast",
             "coverage": "held people cast about 41-57% of a launch's votes (measured on past launches; this is the share of real upvoters whose whole profile we hold)"}

# ---------------- say ----------------
PF = json.loads(gcat(f"{B}/tmp/e5/forward_sim/{DAY}/predictions_frozen.json") or "{}")
SAY = {}
for i in ids:
    r = PF.get(f"sim|{i}")
    if not r: SAY[i] = {"status": NA, "reason": "no frozen /try prediction for this launch"}; continue
    SAY[i] = {"reactions": r.get("RX|ph") or NA, "top_concerns": r.get("RC|ph|b20") or r.get("RC|ph|dep") or NA,
              "top_questions": r.get("RQ|ph|b20") or r.get("RQ|ph|dep") or NA, "predicted_at": r.get("pred_at"),
              "per_item_confidence": NA + " (the simulator gives no per-item score; accuracy is measured for the list)"}
SAY_LABEL = {"reactions": "precision 47.9% (backtest)", "top_concerns": "p@3 37.2% (backtest)", "top_questions": "p@3 33.7% (backtest, optimistic)",
             "source": "accuracy of the deployed /try simulator (orchestrator figures; judged against real comments by a blinded judge). These items were generated from the launch's own text and frozen at predicted_at (launch day, before any comments were used); real comments are never an input"}

# ---------------- competitors ----------------
COMP = {}
try:
    os.environ.setdefault("HF_HOME", "/tmp/hf"); os.environ["HF_HUB_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer
    M = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    pool = json.load(open(f"{SP}/rbundle/reactions_retrieval_v1.json")); NB = json.load(open(f"{SP}/why/try_neighbours_v1.json"))["rows"]
    W = warehouse.table("launches", do_sync=False)[["id", "slug", "day", "name", "tagline", "description"]].drop_duplicates("slug", keep="last")
    W["day"] = W.day.astype(str).str[:10]; bykey = {(s, d): r for s, d, r in zip(W.slug, W.day, W.itertuples())}
    txt, keep = [], []
    for j, r in enumerate(pool):
        w = bykey.get((r["slug_stem"], r["day"])) or next((v for (s, d), v in bykey.items() if d == r["day"] and str(s).startswith(r["slug_stem"])), None)
        if w is None: continue
        txt.append(f"{w.name}. {w.tagline}. {str(w.description or '')[:800]}"); keep.append((j, w))
    PE = M.encode(txt, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    QE = M.encode([f"{p.get('name')}. {p.get('tagline')}. {str(p.get('description') or '')[:800]}" for p in line], normalize_embeddings=True, show_progress_bar=False)
    S = QE @ PE.T
    for qi, i in enumerate(ids):
        o = np.argsort(-S[qi])[:5]; L_ = []
        for k in o:
            j, w = keep[k]; th = pool[j]["themes"]; nb = NB.get(str(j), {})
            kind = lambda t: t.split(":")[0].strip().lower()
            L_.append({"name": w.name, "launch_date": pool[j]["day"], "final_daily_rank": nb.get("daily_rank"), "final_votes": nb.get("final_votes"),
                       "similarity": round(float(S[qi, k]), 3),
                       "commenters_praised": [t.split(":", 1)[1].strip() for t in th if kind(t) == "praise"][:3] or NA,
                       "commenters_complained": [t.split(":", 1)[1].strip() for t in th if kind(t) in ("objection", "complaint", "concern")][:3] or NA})
        COMP[i] = L_
    COMP_LABEL = {"method": f"cosine similarity of local bge-small embeddings (name. tagline. description) against {len(keep)} earlier launches with >= 5 non-team comments (Jan 1 - Oct 24, 2026)",
                  "themes": "paraphrased by flash-lite from the launch's real non-team comments when the pool was built; not quotes; no names",
                  "predictive_value": "descriptive: a forecast band built from similar launches did not sharpen the forecast (try_neighbours note); similarity is not a rank prediction"}
except Exception as e:
    print("competitors failed:", repr(e)[:300]); COMP = {i: NA for i in ids}; COMP_LABEL = {"status": NA, "reason": f"{type(e).__name__}"}

# ---------------- why ----------------
NS = json.loads(gcat(f"{B}/results/web/north_star_table.json") or "{}")
rv = next((r for r in NS.get("rows", []) if r.get("model") == "readable_v2"), None)
WHY_LABEL = {"model": "readable explanation model (readable v2 stumps), not the published 00:05 model",
             "predictive_value": (f"{rv['top3']} / {rv['top5']} / {rv['top10']} top 3 / 5 / 10 on {rv['n_days']} backtest days ({rv['rule']})" if rv else NA),
             "fidelity": NA + " (agreement between these drivers and the published model's order has not been re-measured for the current published model)"}
WHYB = {}
for i in ids:
    f = (WHY.get("launches", {}).get(i) or {}).get("forecast_drivers")
    if not f: WHYB[i] = {"status": NA}; continue
    pts = f.get("points") or {}
    WHYB[i] = {"top_drivers": [{"input": k, "points": pts.get(k)} for k in (f.get("top_inputs") or [])[:3]], "rank_in_explanation_model": f.get("rank_explanation_model")}

names = {str(p["id"]): p.get("name") for p in line}
def lab_text(L): return "; ".join(f"{k}: {v}" for k, v in L.items()) if isinstance(L, dict) else str(L)
def with_label(b, L):   # the website reads each block's "accuracy_label" (orchestrator 22:04Z)
    if isinstance(b, list): return {"items": b, "accuracy_label": lab_text(L)}
    if isinstance(b, dict): return {**b, "accuracy_label": lab_text(L)}
    return {"status": NA, "accuracy_label": lab_text(L)}
def blocks(i):
    return {"name": names.get(i), "who": with_label(WHO.get(i), WHO_LABEL), "say": with_label(SAY.get(i), SAY_LABEL),
            "competitors": with_label(COMP.get(i), COMP_LABEL), "why": with_label(WHYB.get(i), WHY_LABEL)}
out = {"day": DAY, "version": "explain_v1", "written_at": pd.Timestamp.now(tz="UTC").isoformat(),
       "READ_ME": "Per launch: who (predicted backers as segments of held people), say (predicted comments), competitors (similar earlier launches "
                  "and what their commenters said), why (explanation-model drivers). Every block has its own measured value; 'not available' means we "
                  "do not have it, never a guess. No usernames or person ids.",
       "labels": {"who": WHO_LABEL, "say": SAY_LABEL, "competitors": COMP_LABEL, "why": WHY_LABEL},
       "launches": {i: blocks(i) for i in ids}}
p = os.path.join(OUT, f"{DAY}.json"); json.dump(out, open(p, "w"), indent=1, default=float)
if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/explain/{DAY}.json"], check=True)
print(json.dumps({"day": DAY, "launches": len(ids), "who_ok": sum("segments" in (v or {}) for v in WHO.values()), "say_ok": sum("reactions" in v for v in SAY.values()),
                  "competitors_ok": sum(isinstance(v, list) for v in COMP.values()), "why_ok": sum("top_drivers" in v for v in WHYB.values())}))
