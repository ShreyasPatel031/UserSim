"""PRODUCT-USE-1 line-up (orchestrator 00:17Z + amendment 00:23Z Nov 25; PREREG addendum 11).

For day D: the structural top N (results/structural/D/shortlist.json), each launch's product URL, PH category, two same-category
competitors, the category's core task, and 4 simulated users from the launch's likely cohort (person-built panel selection).

Inputs are only what exists before results: name / tagline / description / topics from the 00:05 PT line-up (votes, comments and
ranks in that file are never read), the shortlist's structural rank, pre-D person history, category data, PH Similar Products.

  python lineup.py D [--n 15] [--rehearsal]
Writes (private)  tmp/e5/private/product_use/D/lineup_full.json   (users' profiles; person ids hashed, never published)
       (public)   results/calibration/D/product_use/lineup.json    (no person data; frozen_at, code commit, sources, confidences)
"""
import asyncio, hashlib, io, json, os, re, subprocess, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "cohort_calibration"))
import sim_model  # noqa: E402  (Vertex Gemini; the service account's token)

B = "gs://usersim-bakeoff-347838016394/usersim_sim"; PRIV = f"{B}/tmp/e5/private/product_use"
args = [a for a in sys.argv[1:] if not a.startswith("--")]; D = args[0]
N = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 15
REH = "--rehearsal" in sys.argv; PUB = f"{B}/{'_rehearsal/' if REH else ''}results/calibration/{D}/product_use"
MAINWT = os.environ.get("PU_MAINWT") or os.path.join(os.environ.get("PU_WORK", "/tmp/pu"), "mainwt")   # main checkout for mvp/ (safe_fetch, competitor_urls)
sys.path.insert(0, MAINWT)
from mvp.ph_site import safe_fetch  # noqa: E402
from mvp import competitor_urls as cu  # noqa: E402

def gcat(p, ok_missing=True):
    r = subprocess.run(["gsutil", "cat", p], capture_output=True)
    if r.returncode and not ok_missing: sys.exit(f"missing {p}")
    return r.stdout if not r.returncode else None
def gput(obj, p):
    t = f"/tmp/pu_{abs(hash(p))}.json"; json.dump(obj, open(t, "w"), indent=1, ensure_ascii=False); subprocess.run(["gsutil", "-q", "cp", t, p], check=True)
def jl(b): return [json.loads(l) for l in b.decode().splitlines() if l.strip()] if b else []

GU = {"calls": 0, "in": 0, "out": 0}   # grounded calls: tokens at list price + $0.035 per grounded prompt (Vertex grounding with Google Search)
GURL = sim_model._URL.format(m="gemini-2.5-flash")
def grounded(q, tries=3):
    import urllib.request
    body = {"contents": [{"role": "user", "parts": [{"text": q}]}], "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingBudget": 0}}}
    for k in range(tries):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(GURL, json.dumps(body).encode(),
                          {"Authorization": "Bearer " + sim_model._token(), "Content-Type": "application/json"}), timeout=120))
            u = r.get("usageMetadata", {}); GU["calls"] += 1; GU["in"] += u.get("promptTokenCount", 0); GU["out"] += u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
            t = "".join(x.get("text", "") for x in r["candidates"][0]["content"]["parts"]); m = re.search(r"\{.*\}", t, re.S)
            o = json.loads(m.group(0)) if m else {}
            if "producthunt.com" in str(o.get("url") or "").lower(): o = {"url": None, "dropped": "producthunt.com result"}
            return {**o, "queried_at": pd.Timestamp.now(tz="UTC").isoformat()}
        except Exception as e:
            if k == tries - 1: return {"error": repr(e)[:200]}
            time.sleep(5 * (k + 1))

def official_url(name, tagline, desc=""):
    q = (f"Find the official website (the product's own domain; not Product Hunt, not a social profile, not an app-store listing unless the "
         f"product has no site) of this product:\nName: {name}\nTagline: {tagline}\nDescription: {(desc or '')[:400]}\n"
         'Reply with JSON only: {"url": "<https url or null>", "confidence": "high|medium|low"}')
    return grounded(q)

async def live(url):
    """safe_fetch (no producthunt.com, no private hosts) + competitor_urls' same-site / product-page rules on the final URL."""
    try:
        r = await safe_fetch.fetch(url); fu = r.get("final_url") or url
        ok = int(r.get("status") or 0) == 200 and cu.same_site(url, fu) and not cu.is_non_product_host(fu)
        return {"ok": bool(ok), "status": r.get("status"), "final_url": fu}
    except Exception as e:
        return {"ok": False, "error": repr(e)[:160]}

t0 = time.time()
# ---- line-up: structural top N + launch text (only name/tagline/description/topics are read from the 00:05 file) ----
SL = json.loads(gcat(f"{B}/results/structural/{D}/shortlist.json", False))
top = sorted(SL["launches"], key=lambda r: r["structural_rank"])[:N]
T = {str(p["id"]): p for p in json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json", False))}
def topics(p):
    t = p.get("topics"); t = t if isinstance(t, dict) else (eval(t) if isinstance(t, str) and t.startswith("{") else {})
    return [e["node"]["name"] for e in t.get("edges", [])]
L = [{"id": str(r["id"]), "structural_rank": r["structural_rank"], "name": T[str(r["id"])]["name"], "tagline": T[str(r["id"])]["tagline"],
      "description": T[str(r["id"])].get("description") or "", "topics": topics(T[str(r["id"])])} for r in top]

# ---- product URLs (cache; source recorded) ----
UC = json.loads(gcat(f"{PRIV}/url_cache.json") or b"{}")
for l in L:
    if l["id"] not in UC: UC[l["id"]] = dict(official_url(l["name"], l["tagline"], l["description"]), source="gemini_search_grounding", at=pd.Timestamp.now(tz="UTC").isoformat())
    l["url"], l["url_source"], l["url_confidence"], l["url_queried_at"] = UC[l["id"]].get("url"), UC[l["id"]]["source"], UC[l["id"]].get("confidence"), UC[l["id"]].get("queried_at") or UC[l["id"]].get("at")

# ---- categories: CATEGORY-1 table if delivered; else embedding shortlist (12) over every PH category we hold, then a Gemini pick ----
CATS = jl(gcat(f"{B}/simharness/taxonomy/ph_categories_pasted.jsonl", False))
SIM = jl(gcat(f"{B}/raw/ph_alternatives/similar_products_all.jsonl", False))
PROD = {}
for x in SIM:
    for s in x.get("similar_products") or []:
        k = s.get("slug"); q = PROD.setdefault(k, {"name": s.get("name"), "tagline": s.get("tagline"), "reviews_count": 0, "cats": set(), "dead": False})
        q["reviews_count"] = max(q["reviews_count"], int(s.get("reviews_count") or 0)); q["cats"] |= set(s.get("categories") or []); q["dead"] |= bool(s.get("no_longer_online"))
CD = {c["name"]: c["description"] for c in CATS}
BYCAT = {}
for k, q in PROD.items():
    for c in q["cats"]: BYCAT.setdefault(c, []).append(k)
for c, ks in BYCAT.items():
    if c not in CD: CD[c] = "Products such as: " + "; ".join(f"{PROD[k]['name']} ({PROD[k]['tagline']})" for k in sorted(ks, key=lambda k: -PROD[k]["reviews_count"])[:3])
CN = sorted(CD)
# CATEGORY-1 (orchestrator 00:40Z Nov 25): simharness.run_category lineup -> simharness/taxonomy/lineup_<D>.parquet (category: own PH label
# when the slug is known, else the classifier's top 1 of top 3; competitors: most-reviewed online products of the category = category leaders)
C1, C1C = None, {}
_c1 = gcat(f"{B}/simharness/taxonomy/lineup_{D}.parquet") or gcat(f"{B}/simharness/taxonomy/wip/lineup_{D}.parquet")
if _c1:
    _df = pd.read_parquet(io.BytesIO(_c1))
    C1 = {str(r.item_id): {"category": r.primary, "source": r.category_source, "top3": list(r.embedding_top3),
                           "top3_scores": list(r.embedding_top3_scores), "own": list(r.own_categories)} for r in _df.itertuples()}
    C1C = {str(r.item_id): {"competitors": [{"name": c.get("name"), "tagline": c.get("tagline"), "slug": c.get("slug"), "source": "category_leader:" + str(c.get("source"))}
                                            for c in json.loads(r.competitors)]} for r in _df.itertuples()}
# review truth (REVIEW-TRUTH-1; orchestrator 02:01Z): among the 5 competitors, prefer the nearest ones that have post-cutoff review truth
_rt = gcat(f"{B}/simharness/taxonomy/review_truth.parquet")
TRUTH_SLUGS = set(pd.read_parquet(io.BytesIO(_rt))["product"].str.lower()) if _rt else set()
from sentence_transformers import SentenceTransformer  # noqa: E402
EMB = SentenceTransformer("BAAI/bge-small-en-v1.5")
CE = EMB.encode([f"{c}: {CD[c]}" for c in CN], normalize_embeddings=True)
for l in L:
    if C1 and l["id"] in C1 and (C1[l["id"]].get("category")):
        r = C1[l["id"]]; l.update(category=r["category"], category_source="category1:" + str(r.get("source", "")),
                                  category_confidence=("ph_own_label" if r["source"] == "ph_own" else "classifier top1 (41.5% vs majority; top3 64.6%)"),
                                  category_top3=r["top3"], category_top3_scores=r["top3_scores"])
        v = EMB.encode([f"{l['name']}. {l['tagline']}. {l['description'][:500]} Topics: {', '.join(l['topics'])}"], normalize_embeddings=True)[0]; l["_v"] = v
        continue
    v = EMB.encode([f"{l['name']}. {l['tagline']}. {l['description'][:500]} Topics: {', '.join(l['topics'])}"], normalize_embeddings=True)[0]
    l["_v"] = v; o = list(np.argsort(-(CE @ v))[:12])
    opts = "\n".join(f"{k + 1}. {CN[j]}: {CD[CN[j]][:220]}" for k, j in enumerate(o))
    q = (f"Product: {l['name']}\nTagline: {l['tagline']}\nDescription: {l['description'][:600]}\nTopics: {', '.join(l['topics'])}\n\n"
         f"Which Product Hunt category does this product belong to? Choose from:\n{opts}\n\nPick the category whose products a user "
         "would actually compare this product with. Reply JSON only: {\"pick\": <number or 0 if none fits>, \"confidence\": \"high|medium|low\"}")
    r = sim_model.call(q, max_tokens=60, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
    try: g = json.loads(m.group(0)); k = int(g.get("pick") or 0)
    except Exception: g, k = {}, 0
    j = o[k - 1] if 1 <= k <= len(o) else o[0]
    l.update(category=CN[j], category_source="embed12+gemini_pick" if k else "embed_top1(no_pick)", category_confidence=g.get("confidence", "low"),
             category_cos=round(float(CE[j] @ v), 4))

# ---- competitors: nightly PH Similar Products sharing the category > CATEGORY-1 sets > category's most-reviewed live products ----
NIGHT = {str(x.get("launch_id") or x.get("id")): x for x in jl(gcat(f"{B}/raw/ph_at_launch/{D}/launch_competitor_context.jsonl"))}   # fleet nightly Similar Products (from Nov 26)
CC = json.loads(gcat(f"{PRIV}/competitor_url_cache.json") or b"{}")
def cands(l):
    low = lambda s: (s or "").lower(); cat = low(l["category"]); own = low(l["name"])
    if l["id"] in NIGHT:
        out = [(s.get("name"), s.get("tagline"), "ph_similar_nightly") for s in (NIGHT[l["id"]].get("similar_products") or NIGHT[l["id"]].get("competitors") or [])
               if cat in {low(c) for c in s.get("categories") or []} and not s.get("no_longer_online")]
        if len(out) >= 2: return out
    if l["id"] in C1C:
        cs = C1C[l["id"]].get("competitors") or []
        if "_v" in l and cs:                                                   # nearest first, then those with review truth first (stable)
            ev = EMB.encode([f"{c['name']}. {c.get('tagline') or ''}" for c in cs], normalize_embeddings=True); cs = [cs[i] for i in np.argsort(-(ev @ l["_v"]))]
        cs = sorted(cs, key=lambda c: (str(c.get("slug") or "").lower() not in TRUTH_SLUGS))
        out = [(c.get("name"), c.get("tagline"), c["source"] + ("|review_truth" if str(c.get("slug") or "").lower() in TRUTH_SLUGS else "")) for c in cs]
        if len(out) >= 2: return out
    pool = sorted([(q["reviews_count"], k) for k, q in PROD.items() if not q["dead"] and cat in {low(c) for c in q["cats"]}
                   and low(q["name"]) not in own and own not in low(q["name"])], reverse=True)[:10]          # the category's 10 most-reviewed live products
    if "_v" in l and pool:                                                                                    # ... nearest to the launch first
        ev = EMB.encode([f"{PROD[k]['name']}. {PROD[k]['tagline']}" for _, k in pool], normalize_embeddings=True); sim = ev @ l["_v"]
        pool = [pool[i] for i in np.argsort(-sim)]
    return [(PROD[k]["name"], PROD[k]["tagline"], "category_most_reviewed10_nearest") for _, k in pool]
async def pick(l):
    out = []
    for name, tag, src in cands(l):
        key = (name or "").lower()
        if key not in CC: CC[key] = dict(official_url(name, tag), source="gemini_search_grounding")
        u = CC[key].get("url")
        if not u or (l.get("url") and cu.same_site(u, l["url"])): continue
        chk = await live(u)
        if chk["ok"] and not any(cu.same_site(chk["final_url"], o["url"]) for o in out):
            out.append({"name": name, "url": chk["final_url"], "source": src, "url_source": "gemini_search_grounding", "url_confidence": CC[key].get("confidence"), "url_queried_at": CC[key].get("queried_at")})
        if len(out) == 2: break
    return out
async def all_comps():
    for l in L:
        l["competitors"] = await pick(l)
        l["launch_url_live"] = (await live(l["url"])) if l.get("url") else {"ok": False}
asyncio.run(all_comps())

# ---- the category's core task (written once per category, then frozen and reused on every day) ----
TK = json.loads(gcat(f"{PRIV}/category_tasks.json") or b"{}")
for l in L:
    c = l["category"]
    if c not in TK:
        ex = "; ".join(f"{PROD[k]['name']} ({PROD[k]['tagline']})" for k in sorted(BYCAT.get(c, []), key=lambda k: -PROD[k]["reviews_count"])[:6])
        p = (f"Product category: {c}\nCategory description: {CD.get(c, '')}\nExamples of products in this category: {ex}\n\n"
             "Write ONE first-use task that a new user could do on EVERY product in this category (each product does some version of it), "
             "in the first 10 minutes, without paying, and that reaches the category's first moment of value (the point where the user gets "
             "the result this kind of product exists to give). Keep it at the level of the category's shared job, not one product's feature "
             "(for example 'set up your first ad campaign or listing and see where it would run', not 'generate a video ad'). Do not name any "
             "product. Also state, in one sentence, what counts as reaching that moment of value. "
             "Reply as JSON only: {\"task\": \"...\", \"value_moment\": \"...\"}")
        r = sim_model.call(p, max_tokens=400, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
        TK[c] = dict(json.loads(m.group(0)) if m else {"task": None}, written_at=pd.Timestamp.now(tz="UTC").isoformat(), model="gemini-2.5-flash", prompt_version=2)
    l["core_task"], l["value_moment"] = TK[c].get("task"), TK[c].get("value_moment")

# ---- 4 users per launch: the person-built panel's selection (simharness run_what_panel build: held complete people with >= 3 comments before
# D and >= 1 upvote in the 60 days before D, ranked by topic affinity), in the panel's own seeded order (md5(launch id + D)); the first 4.
# Run here from the latest harness build so the line-up does not wait for the panel's comment generation (PREREG 11c). Fallback: the
# person_panel/D.parquet file. Profiles are pre-D history only (quoted comments removed); person ids are hashed with D.
def profile(prompt):
    h = prompt.split("THIS MEMBER'S HISTORY", 1)[-1].split("TODAY'S LAUNCH", 1)[0]
    h = h.split("Recent comments they wrote:", 1)[0]                         # drop quoted comments (names, self-intros)
    return re.sub(r"@\w+", "", h).strip(" :\n")
USERS, users_source = {}, None
CV = os.environ.get("FRESH_SIMHARNESS") or os.environ.get("PU_CV")
if CV and os.path.isdir(os.path.join(CV, "simharness")):
    WB = os.path.join(os.environ.get("PU_WORK", "/tmp/pu"), f"sel_{D}"); os.makedirs(WB + "/builds", exist_ok=True)
    stamp = (gcat(f"{B}/simharness/bench_v0/builds/latest") or b"").decode().strip()
    if stamp:
        os.makedirs(f"{WB}/builds/{stamp}", exist_ok=True)   # gsutil rsync needs the target directory to exist
        subprocess.run(["gsutil", "-m", "-q", "rsync", "-r", f"{B}/simharness/bench_v0/builds/{stamp}", f"{WB}/builds/{stamp}"]); open(f"{WB}/builds/latest", "w").write(stamp)
        LUF = os.path.join(WB, "lineup.json"); open(LUF, "wb").write(gcat(f"{B}/raw/daily/{D}/today_0005.json", False))
        r = subprocess.run([sys.executable, "-m", "simharness.run_what_panel", "build", "--bench", f"{WB}/builds", "--lineup", LUF, "--day", D, "--out", WB], cwd=CV, capture_output=True, text=True)
        if not r.returncode and os.path.exists(os.path.join(WB, "eval.jsonl")):
            PEOPLE = pd.read_parquet(f"{WB}/builds/{stamp}/people.parquet", columns=["person_idx", "person_id"]).set_index("person_idx").person_id.to_dict()
            S2I = {str(x.get("slug")): str(x["id"]) for x in json.load(open(LUF))}; by = {}
            for l2 in open(os.path.join(WB, "eval.jsonl")):
                row = json.loads(l2); lid = S2I.get(row["meta"]["slug"])
                if lid: by.setdefault(lid, []).append(row)
            for l in L:
                rows = by.get(l["id"], [])
                order = list(np.random.default_rng(int(hashlib.md5((l["id"] + D).encode()).hexdigest()[:8], 16)).permutation(len(rows)))
                USERS[l["id"]] = [{"user_key": hashlib.sha256((str(PEOPLE.get(rows[i]["meta"]["person_idx"])) + "|" + D).encode()).hexdigest()[:12],
                                   "profile": profile(rows[i]["messages"][0]["content"])} for i in order[:4]]
            users_source = f"run_what_panel build on harness build {stamp} (panel seeded order, first 4)"
        else: print("WARN selection failed:", (r.stderr or "")[-400:], flush=True)
if not USERS:
    PP = pd.read_parquet(io.BytesIO(gcat(f"{B}/tmp/e5/private/person_panel/{D}.parquet", False)))
    for l in L:
        g = PP[(PP.launch_id.astype(str) == l["id"])]
        g = g[g["drop"].isna() | (g["drop"].astype(str).str.strip() == "")] if "drop" in g else g   # drop = reason the generated comment was dropped
        USERS[l["id"]] = [{"user_key": hashlib.sha256((str(pid) + "|" + D).encode()).hexdigest()[:12], "profile": profile(pr)}
                          for pid, pr in zip(g.person_id.head(4), g.prompt.head(4))]
    users_source = "person_panel/D.parquet (fallback)"
for l in L: l["n_users"] = len(USERS.get(l["id"], []))

commit = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or os.environ.get("PU_COMMIT", "")
frozen = pd.Timestamp.now(tz="UTC"); cut = pd.Timestamp(D + " 03:30", tz="America/Los_Angeles")
cost = {"grounded": {**GU, "usd": round(GU["in"] / 1e6 * 0.30 + GU["out"] / 1e6 * 2.50 + 0.035 * GU["calls"], 4)}, "gemini_other": sim_model.usage()}
cost["usd_measured_total"] = round(cost["grounded"]["usd"] + cost["gemini_other"]["usd"], 4)
meta = {"day": D, "users_source": users_source, "cost": cost, "frozen_at": frozen.isoformat(), "freeze_deadline": cut.tz_convert("UTC").isoformat(), "on_time": bool(frozen <= cut),
        "rehearsal": REH, "code_commit": commit, "structural_model": SL.get("structural_model"), "n": len(L), "sec": round(time.time() - t0),
        "inputs_read": ["structural rank", "00:05 name/tagline/description/topics", "pre-D person history", "category data", "PH Similar Products (up to Nov 1 / nightly)"],
        "inputs_not_read": ["votes", "comments", "ranks of D", "launch-day comments"]}
for l in L: l.pop("_v", None)
gput({**meta, "launches": L, "users": USERS}, f"{PRIV}/{D}{'_rehearsal' if REH else ''}/lineup_full.json")
gput({**meta, "launches": L}, f"{PUB}/lineup.json")
gput(UC, f"{PRIV}/url_cache.json"); gput(CC, f"{PRIV}/competitor_url_cache.json"); gput(TK, f"{PRIV}/category_tasks.json")
print(json.dumps({**meta, "url_ok": sum(bool(l.get("launch_url_live", {}).get("ok")) for l in L), "with_2_comps": sum(len(l["competitors"]) == 2 for l in L),
                  "category_sources": pd.Series([l["category_source"] for l in L]).value_counts().to_dict(),
                  "comp_sources": pd.Series([c["source"] for l in L for c in l["competitors"]]).value_counts().to_dict()}))
