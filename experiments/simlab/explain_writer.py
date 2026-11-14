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
    # BACKER PREDICTION (north star, Shreyas Nov 14): freeze each launch's ranked held people (salted person ids only; PRIVATE bucket path,
    # never on the site), scored later by backer_score.py as who_actually fills in
    fr = [pd.DataFrame({"launch_id": i, "person_id": p.sort_values(ascending=False).index[:2000], "p": p.sort_values(ascending=False).values[:2000]}).assign(rank=lambda x: range(1, len(x) + 1))
          for i, p in PPROB.items() if isinstance(p, pd.Series)]
    if fr:
        FR = pd.concat(fr, ignore_index=True).assign(day=DAY, frozen_at=pd.Timestamp.now(tz="UTC").isoformat(), n_active=int(nact))
        fp = os.path.join(OUT, f"backer_pred_{DAY}.parquet"); FR.to_parquet(fp)
        if UP or "--freeze" in sys.argv: subprocess.run(["gsutil", "-q", "cp", fp, f"{B}/tmp/e5/private/backer_pred/{DAY}.parquet"], check=True)
    if "--who-only" in sys.argv: print(json.dumps({"day": DAY, "frozen_launches": len(fr), "n_active": int(nact)})); sys.exit(0)
    TOPN = list(g["TOP"]) if "TOP" in g else None
    seg_all = pd.Series([segmap.get(p, "no headline or bio") for p in act.index], index=act.index) if act is not None else None
    names = {str(p_["id"]): p_.get("name") for p_ in line}; WHY = json.loads(gcat(f"{B}/results/web/why/{DAY}_0005.json") or "{}")
    TEAMPOOL = {}
    try:
        L_, lh_, lm_ = g["L"], g["lhun"], g["lmak"]; bt_ = {}
        for l_ in L_.id:
            for t_ in (lh_.get(l_), lm_.get(l_)):
                if t_: bt_.setdefault(t_, set()).add(l_)
        Hs = g["U"][(g["U"].fetched_at < g["start"](DAY)) & (g["U"].lday < DAY)]
        HUNTPOOL, MAKERPOOL, HUNTER_OF = {}, {}, {}
        for i_ in ids:
            team_ = [x for x in (lh_.get(i_), lm_.get(i_)) if x]
            ls_ = set().union(*[bt_.get(x, set()) for x in team_]) - {i_} if team_ else set()
            TEAMPOOL[i_] = Hs[Hs.target_id.isin(ls_)].person_id.unique().tolist() if ls_ else []
            h_, m_ = lh_.get(i_), lm_.get(i_); HUNTER_OF[i_] = h_
            lh_s = (bt_.get(h_, set()) - {i_}) if h_ else set(); lm_s = (bt_.get(m_, set()) - {i_}) if (m_ and m_ != h_) else set()
            HUNTPOOL[i_] = Hs[Hs.target_id.isin(lh_s)].person_id.unique().tolist() if lh_s else []
            MAKERPOOL[i_] = Hs[Hs.target_id.isin(lm_s)].person_id.unique().tolist() if lm_s else []
        n30_ = Hs[Hs.lday >= (pd.Timestamp(DAY) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")].groupby("person_id").size()
        HEAVY = set(n30_[n30_ >= n30_.quantile(0.8)].index); BASE_HEAVY = len(HEAVY) / max(len(n30_), 1)
    except Exception as e:
        print("team pool failed:", repr(e)[:200])
    # orchestrator 22:54Z Nov 14: "who" segments come from the CF-only backer lists (forward line, 25.2% of held backers named) when frozen
    CFL = None
    try:
        raw_cf = subprocess.run(["gsutil", "cat", f"{B}/tmp/e5/private/backer_arms/{DAY}.parquet"], capture_output=True).stdout
        lp_cf = os.path.join(SP, "bp", f"backer_arms_{DAY}.parquet")
        if raw_cf: os.makedirs(os.path.dirname(lp_cf), exist_ok=True); open(lp_cf, "wb").write(raw_cf)
        if os.path.exists(lp_cf):
            A_ = pd.read_parquet(lp_cf); A_ = A_[A_.arm == "CF-only"]
            CFL = {str(l): pd.Series(g.p.values, index=g.person_id.values) for l, g in A_.groupby("launch_id")}
    except Exception as e:
        print("CF-only lists not used:", repr(e)[:200])
    for i in ids:
        p = CFL.get(i) if CFL else PPROB.get(i)
        if CFL and p is not None and seg_all is not None:
            seg_all_i = pd.Series([segmap.get(q, "no headline or bio") for q in p.index], index=p.index)
        else:
            seg_all_i = seg_all.reindex(p.index) if (p is not None and isinstance(p, pd.Series) and seg_all is not None) else None
        if p is None or not isinstance(p, pd.Series) or nact < MIN: WHO[i] = {"status": NA, "reason": "vote model not fitted (fewer than 20 held active people or training upvotes)"}; continue
        df = pd.DataFrame({"p": p.values, "seg": seg_all_i.values}, index=p.index); tot = df.p.sum()
        rows = []
        for s, gg in df.groupby("seg"):
            if len(gg) < MIN: continue
            rows.append({"segment": s, "expected_votes": round(float(gg.p.sum()), 1), "share_of_held_expected_votes": round(float(gg.p.sum() / tot), 3) if tot > 0 else None,
                         "n_held_people_scored": int(len(gg)), "n_likely (chance >= 5%)": int((gg.p >= 0.05).sum())})
        rows.sort(key=lambda r: -r["expected_votes"])
        top = df.p.sort_values(ascending=False).index[:200]
        likes = None; lift_rows = None
        # launch-specific view (website item 1, orchestrator 23:19Z): the TOP 200 of the ranking vs all held active people (base), with lift
        base_seg = seg_all.value_counts(normalize=True) if seg_all is not None else None
        if base_seg is not None:
            ts_ = pd.Series([segmap.get(q, "no headline or bio") for q in top]).value_counts()
            lift_rows = sorted([{"segment": s_, "n_in_top_200": int(n_), "share_in_top_200": round(n_ / len(top), 3), "share_of_all_held_active": round(float(base_seg.get(s_, 0)), 3),
                                 "lift": round((n_ / len(top)) / float(base_seg.get(s_, np.nan)), 2) if base_seg.get(s_, 0) > 0 else None}
                                for s_, n_ in ts_.items() if n_ >= MIN], key=lambda r: -(r["lift"] or 0))
        if tv is not None and TOPN:
            ix = pd.Series(np.arange(len(act)), index=act.index); top_i = [q for q in top if q in ix.index]
            dist = tv[ix[top_i].values].mean(0) if top_i else np.zeros(len(TOPN)); base_t = tv.mean(0)
            cand = [j for j in range(len(TOPN)) if dist[j] >= 0.02 and base_t[j] > 0]
            o = sorted(cand, key=lambda j: -dist[j] / base_t[j])[:5]
            likes = [{"topic": TOPN[j], "share_of_their_recent_upvotes": round(float(dist[j]), 3), "share_for_all_held_active": round(float(base_t[j]), 3),
                      "lift": round(float(dist[j] / base_t[j]), 2), "n_people": len(top_i)} for j in o]
        def pool_block(tp, shared_note=None):
            b_ = {"n_held_people": len(tp)}
            if len(tp) < MIN: b_["note"] = "fewer than 20 held people; not shown"; return b_
            if shared_note: b_["shared_with"] = shared_note
            b_["heavy_upvoter_share"] = round(len(set(tp) & HEAVY) / len(tp), 3); b_["heavy_upvoter_share_all_held_active"] = round(BASE_HEAVY, 3)
            if base_seg is not None:
                ts2 = pd.Series([segmap.get(q, "no headline or bio") for q in tp]).value_counts()
                b_["segments_by_lift"] = sorted([{"segment": s_, "n": int(n_), "share": round(n_ / len(tp), 3), "share_of_all_held_active": round(float(base_seg.get(s_, 0)), 3),
                                                  "lift": round((n_ / len(tp)) / float(base_seg.get(s_)), 2) if base_seg.get(s_, 0) > 0 else None}
                                                 for s_, n_ in ts2.items() if n_ >= MIN], key=lambda r: -(r["lift"] or 0))
            if tv is not None and TOPN:
                tpi = [q for q in tp if q in ix.index]
                if len(tpi) >= MIN:
                    d2 = tv[ix[tpi].values].mean(0); bt = tv.mean(0); c2 = [j for j in range(len(TOPN)) if d2[j] >= 0.02 and bt[j] > 0]
                    b_["topics_by_lift"] = [{"topic": TOPN[j], "share": round(float(d2[j]), 3), "share_for_all_held_active": round(float(bt[j]), 3), "lift": round(float(d2[j] / bt[j]), 2), "n_people": len(tpi)}
                                            for j in sorted(c2, key=lambda j: -d2[j] / bt[j])[:5]]
            return b_
        same_h = [names.get(j) for j in ids if j != i and HUNTER_OF.get(j) and HUNTER_OF.get(j) == HUNTER_OF.get(i)]
        hunter_block = pool_block(HUNTPOOL.get(i, []), (f"identical for today's other launches by the same hunter: {', '.join(n for n in same_h if n)}" if same_h else None))
        maker_block = pool_block(MAKERPOOL.get(i, []))
        wl = (WHY.get("launches", {}).get(i) or {}) if isinstance(WHY, dict) else {}
        network = {k: (wl.get(k) or {}).get("value") for k in ("follow_ties", "follow_ties_active", "hunter_followers")}
        network["note"] = "follows of the hunter or makers among held people (reads before 00:00 PT) and the hunter's follower count; network size varies far more between launches than role mix does"
        WHO[i] = {"network": network, "hunter_past_backers": hunter_block, "maker_past_backers": maker_block, "segments_by_lift": lift_rows, "segments": rows, "expected_held_votes": round(float(tot), 1), "n_held_active_people": int(nact),
                  "what_likely_backers_upvote": likes, "what_likely_backers_dislike": NA + " (we observe upvotes and follows, not dislikes)",
                  "likely_backers_definition": "the 200 held people ranked highest for this launch by the CF-only backer model; segments and topics are shown by lift = their share among these 200 / their share among all held active people that day (lift > 1: over-represented); groups under 20 people hidden"}
except Exception as e:
    print("who failed:", repr(e)[:300]); WHO = {i: {"status": NA, "reason": f"vote model step failed: {type(e).__name__}"} for i in ids}
WHY = json.loads(gcat(f"{B}/results/web/why/{DAY}_0005.json") or "{}")

WHO_LABEL = {"segment_rule": "keyword rule on each held person's own headline and bio (first match in this order: investors, designers, developers, marketers, product managers, founders/indie makers, students)",
             "model": "voter_harness pair model (held people's recent upvotes, topic taste, follows of the hunter and first maker; trained on the 7 previous days; reads fetched before 00:00 PT)",
             "predictive_value": "summed per launch it gave 0.0 top-3 gain over the clean forecast on 10 forward test days (Oct 29 - Nov 11): descriptive, not a vote forecast",
             "coverage": "held people cast about 41-57% of a launch's votes (measured on past launches; this is the share of real upvoters whose whole profile we hold)"}
try:
    if CFL:
        WHO_LABEL = {**WHO_LABEL, "model": "CF-only backer model (activity + co-upvote neighbour score, SVD k=32 on upvotes dated before the day; reads before 00:00 PT; no follows); segments and expected votes over each launch's 2,000 most likely held people",
                     "predictive_value": "25.2% of held backers named, 128 launches, forward (Nov 8-12, strict; +4.0 points [+1.9, +5.9] over a most-active list)",
                     "launch_specificity": ("TESTED, NOT LAUNCH-SPECIFIC: a launch's top 200 overlap 90% with other launches' top 200 the same day, and a launch's own list "
                                            "fits its actual held backers no better than other launches' lists (roles +0.09 TV points, 95% interval -0.43 to +0.52; 44 launches, "
                                            "1,450 backers, Nov 8-12 forward). 'segments_by_lift' describes today's generally likely backers, not this launch's."),
                     "hunter_past_backers": ("held people who upvoted an earlier launch by this hunter (reads before 00:00 PT). 50% of actual held backers came from the "
                                             "hunter-or-maker pool (Nov 8-12, 1,450 backers); its role mix fits its own launch better than other launches' pools by +1.7 TV points "
                                             "(95% interval -1.0 to +4.9), topics +1.5 (-0.1 to +2.6). Identical for launches sharing a hunter (it is the hunter's audience, not the product's)"),
                     "maker_past_backers": ("held people who upvoted an earlier launch by this launch's first maker (other than the hunter). Rarely available: 9 of 44 test "
                                            "launches had >= 20 such people, holding 2.3% of actual held backers; topics +2.1 TV points (-0.2 to +5.6)"),
                     "heavy_upvoter_share": "share of the pool in the top 20% of held people by upvotes in the 30 days before the day (base = 20% by construction among people active in those 30 days)"}
except NameError:
    pass

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
# input definitions (from PH ops' code: readable_shadow.py X10, features.py, model.py, history_retrain.py, llm.py, promo_features.py)
DEF = {"hist_hunter_rel": ("hunter track record (relative)", "mean, over the hunter's earlier launches, of log(1+votes) minus that day's mean log(1+votes); 0 = average"),
       "hist_hunter_n": ("hunter launches before", "number of earlier launches by this hunter in our history (strictly earlier days)"),
       "hist_hunter_top5": ("hunter top-5 rate before", "share (0-1) of this hunter's earlier launches that finished in the day's top 5 (a rate, not a count)"),
       "llm_pitch": ("Gemini pitch score", "Gemini's estimated chance (0-100 %) that the launch finishes in the day's top 5, judged from the pitch only (name, tagline, description, topics), all of the day's launches in one call"),
       "topic_prior_mean": ("topic prior", "average over the launch's topics of how those topics' launches did relative to their day (log-vote scale, shrunk towards 0 for rare topics)"),
       "txt_ridge": ("text model score", "a word-based model (TF-IDF ridge) of the name, tagline and description, trained on past launches, predicting log votes relative to the day's mean; 0 = average"),
       "ph_n_media": ("media items", "number of images and videos on the launch page"),
       "ph_n_makers": ("team size", "number of makers listed on the launch"),
       "ph_hunter_age_d": ("hunter account age", "days between the hunter's Product Hunt account creation and the launch day"),
       "promo_cov": ("pre-launch coverage", "number of press / Hacker News / Reddit / other coverage items dated before launch day (Gemini + Google Search read)")}
RD = json.loads(gcat(f"{B}/results/shadow_readable/{DAY}.json") or "{}")
lab2key = {v: k for k, v in (RD.get("labels") or {}).items()}
VALS = {str(r.get("id")): r.get("values") or {} for r in RD.get("forecast", [])}   # PH ops' readable_shadow 'values' (when written)
def _snap_vals(p_):   # exact from the 00:05 snapshot, same formulas as features.py
    v = {"ph_n_makers": len(p_.get("makers") or []), "ph_n_media": len(p_.get("media") or [])}
    ca = (p_.get("user") or {}).get("createdAt")
    if ca:
        c_ = pd.Timestamp(ca); c_ = c_.tz_convert("UTC").tz_localize(None) if c_.tzinfo else c_
        v["ph_hunter_age_d"] = int((pd.Timestamp(DAY) - c_).days)
    return v
SNAP = {str(p_["id"]): _snap_vals(p_) for p_ in line}
WHYB = {}
for i in ids:
    f = (WHY.get("launches", {}).get(i) or {}).get("forecast_drivers")
    if not f: WHYB[i] = {"status": NA}; continue
    pts = f.get("points") or {}
    vals = {**SNAP.get(i, {}), **VALS.get(i, {})}
    def _drv(lbl):
        key = lab2key.get(lbl); d_ = DEF.get(key, (lbl, NA))
        v = vals.get(key) if key else None
        rv = (round(float(v), 3) if isinstance(v, (int, float)) else NA + " (not yet written by the readable model's daily file)")
        if key == "ph_n_makers" and isinstance(v, (int, float)):
            pm = next((p_ for p_ in line if str(p_["id"]) == i), {}); hid = sum(str(m.get("id")) == "0" for m in (pm.get("makers") or []))
            if v == 0: rv = "0: makers not shown by Product Hunt (the model reads this as the smallest possible team, which lowers the score; not a solo team)"
            elif hid: rv = f"{int(v)} (including {hid} whose names Product Hunt hides)"
        return {"input": d_[0], "points": pts.get(lbl), "raw_value": rv,
                "definition": d_[1]}
    WHYB[i] = {"top_drivers": [_drv(k) for k in (f.get("top_inputs") or [])[:3]], "rank_in_explanation_model": f.get("rank_explanation_model"),
               "all_inputs": [_drv(DEF[k][0] if False else (RD.get("labels") or {}).get(k, k)) for k in DEF]}

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
