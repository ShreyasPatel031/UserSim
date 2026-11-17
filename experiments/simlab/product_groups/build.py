"""Per-product user groups + hover card (who uses it / competitors / likes and dislikes vs competitors). Shreyas Nov 17.
For each launch of day D:
  people   its top 300 likely backers (explain/backer_pred_<D>.parquet, CF ranking frozen at 00:05)
  groups   clustered INSIDE that launch's people (not the site-wide segments): TF-IDF of headline + bio (handles / urls scrubbed) + share of
           their 2026 upvotes by topic; KMeans k = 2..4 by silhouette, every group >= 25 people (people appear only as groups of 20+)
  names    one Gemini 2.5 Flash call per launch (llm.gemini_call, temperature 0, JSON): short concrete group names from each group's
           distinctive headline words / topics / products (lift vs the launch's other groups), banned generic words
  card     competitors (the 3 most similar earlier launches from the explain file) and one line each for what people like / don't like
           vs those competitors, from the competitors' real comment themes + a few real competitor comments as tone examples (never quoted)
Output: <out>/<D>.json (launch id -> card). Aggregates only: no person ids, names or handles.
    python build.py <D> <scratchpad> <out dir> [max launches]"""
import concurrent.futures as cf, json, os, re, sys
import numpy as np, pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
D, SP, OUT = sys.argv[1:4]; LIM = int(sys.argv[4]) if len(sys.argv) > 4 else 999; os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
from pipeline import warehouse as W  # noqa: E402
SCRUB = lambda s: "" if s is None or (isinstance(s, float) and s != s) else re.sub(r"\s+", " ", re.sub(r"(@\w+|https?://\S+|\S+@\S+\.\S+|www\.\S+)", " ", str(s))).strip()
STOP = {"and", "the", "of", "at", "in", "for", "to", "a", "an", "on", "with", "i", "my", "we", "is", "am", "&", "|", "-", "who", "that", "love", "building"}

L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L["day"] = L.day.astype(str).str[:10]
TOP = {i: (json.loads(t) if isinstance(t, str) and t.startswith("[") else []) for i, t in zip(L.id, L.topics)}; NAME = dict(zip(L.id, L.name))
EX = json.load(open(f"{SP}/explain/{D}.json")); LAUNCH = EX["launches"]; LAUNCH = LAUNCH if isinstance(LAUNCH, dict) else {str(r.get("id")): r for r in LAUNCH}
line = {str(r["id"]): r for r in json.load(open(f"{SP}/t17/today_0005.json"))} if D == "2026-11-17" else {}
BP = pd.read_parquet(f"{SP}/explain/backer_pred_{D}.parquet"); BP["launch_id"] = BP.launch_id.astype(str)
# product-specific audience: people ranked high for THIS launch relative to how high they rank for every launch of the day
# (the plain top 300 is the same very active people for every launch); spec = log p - mean log p over the day's launches
BP["lp"] = np.log(BP.p.clip(lower=1e-9)); mu = BP.groupby("person_id").lp.mean(); BP["spec"] = BP.lp - BP.person_id.map(mu)
BP = BP[BP["rank"] <= 1500].sort_values(["launch_id", "spec"], ascending=[True, False]).groupby("launch_id").head(300)
BP["rank"] = BP.groupby("launch_id").cumcount() + 1
P = pd.read_parquet(f"{SP}/store_live/persons.parquet", columns=["person_id", "headline", "bio"]).set_index("person_id")
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"])
E = E[(E.kind == "upvote") & E.person_id.isin(set(BP.person_id))]; E["target_id"] = E.target_id.astype(str); E = E[E.target_id.isin(TOP)]
UP = E.groupby("person_id").target_id.apply(list).to_dict()
C = pd.read_parquet(f"{SP}/kinds/all_comments.parquet"); C = C[(~C.team) & C.text.str.len().between(25, 260)]; C["launch_id"] = C.launch_id.astype(str)
CBY = C.groupby("launch_id").text.apply(list).to_dict()
BYND = {(n.strip().lower(), d): i for i, n, d in zip(L.id, L.name.astype(str), L.day)}

FEATS = os.environ.get("FEATS", "roles"); DIAG = {}; ROLE_OF = {}; ROLE_LIFT = {}; BASE_ROLE = {}
ROLES = [("investor", r"\b(investor|vc|venture|angel|partner at .*capital)\b"), ("product", r"\b(product manager|pm|product lead|head of product|product owner)\b"),
         ("designer", r"\b(designer|design|ux|ui|figma)\b"), ("sales", r"\b(sales|sdr|bdr|account executive|business development|revenue)\b"),
         ("marketer", r"\b(marketing|marketer|growth|seo|content|brand|gtm|go-to-market|social media|community manager)\b"),
         ("creator", r"\b(creator|youtuber|writer|filmmaker|video|podcast|artist|photographer)\b"), ("student", r"\b(student|university|college)\b"),
         ("data", r"\b(data scientist|data engineer|analyst|machine learning|ml engineer|researcher)\b"),
         ("developer", r"\b(developer|engineer|dev|programmer|coder|full ?-?stack|backend|frontend|software|cto)\b"),
         ("founder", r"\b(founder|co-?founder|ceo|entrepreneur|solopreneur|indie ?hacker|owner)\b")]
def role_of(t):
    t = t.lower()
    for r, pat in ROLES:
        if re.search(pat, t): return r
    return "other"
LE = np.load(f"{SP}/rb/abc_emb.npy"); LI = {str(i): k for k, i in enumerate(pd.read_parquet(f"{SP}/rb/abc_emb_ids.parquet").id.astype(str))}; LE_MEAN = LE.mean(0)
_EC = {}
def embed_people(ppl, txt):
    if "m" not in _EC:
        os.environ.setdefault("HF_HUB_OFFLINE", "1"); from sentence_transformers import SentenceTransformer
        _EC["m"] = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    miss = [(p, t) for p, t in zip(ppl, txt) if p not in _EC]
    if miss:
        with _LOCK:
            V = _EC["m"].encode([t for _, t in miss], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
            for (p, _), v in zip(miss, V): _EC[p] = v
    return np.array([_EC[p] for p in ppl])
import threading; _LOCK = threading.Lock()

def base_roles():   # role mix of every profiled person on any launch's list today (the comparison for lift)
    ids = BP.person_id.unique(); t = [(SCRUB(P.headline.get(p)) + " " + SCRUB(P.bio.get(p))).strip() for p in ids]
    rl = pd.Series([role_of(x) for x in t if len(x) >= 12]); return rl.value_counts(normalize=True).to_dict()

def groups_for(lid):
    ppl = BP[BP.launch_id == lid].sort_values("rank").person_id.tolist()
    txt0 = [(SCRUB(P.headline.get(p)) + " " + SCRUB(P.bio.get(p))).strip()[:400] for p in ppl]
    keep = [i for i, t in enumerate(txt0) if len(t) >= 12]; n_blank = len(ppl) - len(keep)   # no profile text: not grouped (counted)
    ppl = [ppl[i] for i in keep]; txt = [txt0[i] for i in keep]
    tops = [[t for x in UP.get(p, []) for t in TOP.get(x, [])] for p in ppl]
    allt = pd.Series([t for ts in tops for t in ts]).value_counts(); vocab = list(allt.index[:60])
    T = np.array([[ts.count(v) / max(len(ts), 1) for v in vocab] for ts in tops]) if vocab else np.zeros((len(ppl), 1))
    tv = TfidfVectorizer(min_df=4, stop_words="english", max_features=3000); Xt = tv.fit_transform([t or "none" for t in txt])
    Z = TruncatedSVD(min(20, Xt.shape[1] - 1), random_state=0).fit_transform(Xt) if Xt.shape[1] > 2 else np.zeros((len(ppl), 1))
    X_old = np.hstack([(Z - Z.mean(0)) / (Z.std(0) + 1e-9), (T - T.mean(0)) / (T.std(0) + 1e-9) * 0.7])
    # v2 (Shreyas Nov 17: weak separation): who they are = bge-small embedding of headline + bio; what they like = mean embedding of the
    # launches they upvoted (2026 launches with a stored embedding). Each block PCA to 12 dims, standardised, equal weight.
    H = embed_people(ppl, txt); TA = np.array([LE[[LI[x] for x in UP.get(p, []) if x in LI]].mean(0) if any(x in LI for x in UP.get(p, [])) else LE_MEAN for p in ppl])
    from sklearn.decomposition import PCA
    def blk(M): Q = PCA(12, random_state=0).fit_transform(M); return (Q - Q.mean(0)) / (Q.std(0) + 1e-9)
    X_new = np.hstack([blk(H), blk(TA)]); X = X_new if FEATS == "v2" else X_old
    best = None
    for k in (2, 3, 4):
        lab = KMeans(k, n_init=10, random_state=0).fit_predict(X)
        if np.bincount(lab).min() < 25: continue
        s = silhouette_score(X, lab)
        if best is None or s > best[0]: best = (s, k, lab)
    lab = best[2] if best else np.zeros(len(ppl), int)
    if FEATS == "roles":   # crisp groups by stated role (headline / bio), roles with >= 25 people, at most 4; others counted, not shown
        rl = np.array([role_of(t) for t in txt]); vc = pd.Series(rl[rl != "other"]).value_counts()
        lift = (vc / max(len(rl), 1)) / pd.Series(BASE_ROLE).reindex(vc.index).clip(lower=1e-3)   # over-representation vs the day's backers
        ok = vc[vc >= 20].index; keep_r = list(lift[ok].sort_values(ascending=False).index[:3])
        if len(keep_r) < 2: keep_r = list(vc.index[:2])
        ROLE_LIFT[lid] = {r: round(float(lift[r]), 2) for r in keep_r}
        lab = np.array([keep_r.index(r) if r in keep_r else -1 for r in rl]); ROLE_OF[lid] = {i: r for i, r in enumerate(keep_r)}
        best = (silhouette_score(X_new[lab >= 0], lab[lab >= 0]) if len(set(lab[lab >= 0])) > 1 else 0.0, len(keep_r), lab)
    # separation diagnostics in a neutral space (both feature sets together), for this labelling and for the other feature set's labelling
    both = np.hstack([X_old, X_new]); other = X_new if FEATS != "v2" else X_old; ob = None
    for k in (2, 3, 4):
        l2 = KMeans(k, n_init=10, random_state=0).fit_predict(other)
        if np.bincount(l2).min() >= 25:
            s2 = silhouette_score(other, l2); ob = (s2, l2) if ob is None or s2 > ob[0] else ob
    DIAG[lid] = {"feats": FEATS, "k": int(len(set(lab))), "silhouette_own_space": round(float(best[0]), 3) if best else None,
                 "silhouette_neutral_space": round(float(silhouette_score(both[lab >= 0], lab[lab >= 0])), 3) if len(set(lab[lab >= 0])) > 1 else None,
                 "share_in_shown_groups": round(float((lab >= 0).mean()), 2),
                 "other_feats_silhouette_neutral_space": round(float(silhouette_score(both, ob[1])), 3) if ob else None}
    vec = TfidfVectorizer(min_df=3, stop_words="english", ngram_range=(1, 2), binary=True, max_features=4000); B = vec.fit_transform([t or "none" for t in txt]) > 0
    words = np.array(vec.get_feature_names_out()); out = []
    for g in sorted(set(lab) - {-1}):
        m = lab == g; inr = np.asarray(B[m].mean(0)).ravel(); outr = np.asarray(B[~m].mean(0)).ravel() if (~m).any() else np.asarray(B.mean(0)).ravel()
        lift = (inr + 0.01) / (outr + 0.01); okw = [w for w in words[np.argsort(-(lift * (inr > 0.06)))][:12] if w not in STOP]
        gt = pd.Series([t for i in np.where(m)[0] for t in tops[i]]).value_counts(normalize=True); at = pd.Series([t for i in np.where(~m)[0] for t in tops[i]]).value_counts(normalize=True)
        tl = ((gt + 0.005) / (at.reindex(gt.index).fillna(0) + 0.005)).sort_values(ascending=False)
        pr = pd.Series([NAME.get(x) for i in np.where(m)[0] for x in UP.get(ppl[i], [])]).value_counts()
        heads = [h for h in (txt[i] for i in np.where(m)[0][:60]) if len(h) > 12][:12]
        rr = ROLE_OF.get(lid, {}).get(int(g))
        out.append({"gid": int(g), "n": int(m.sum()), "share": round(float(m.mean()), 2), "role": rr, "role_lift": ROLE_LIFT.get(lid, {}).get(rr), "headline_words": okw[:10],
                    "topics_by_lift": [t for t in tl.index[:6] if gt[t] > 0.02], "products_upvoted": list(pr.index[:8]), "sample_headlines": heads})
    return out, len(ppl) + n_blank, (round(float(best[0]), 3) if best else None), n_blank

BAN = re.compile(r"\b(products?|utilit(y|ies)|tools?|tech|enthusiasts?|innovators?|evaluators?|curators?|observers?|builders?|makers?|creators?|users?|adopters?|savvy|digital|professionals?|people|folks|community)\b", re.I)
PROMPT = """You write a small hover card for a product on a Product Hunt forecasting site. Plain, short, specific. JSON only.

PRODUCT: {name} — {tagline}
{desc}
Topics: {topics}

1) USER GROUPS. These groups are the people most likely to upvote THIS product, split by who they are (from their profile headlines and
what they upvote). Give each a name of 2-3 words that a person would actually say, naming a real role, trade, platform, stack or industry
taken from the group's distinctive words, e.g. "Shopify store owners", "Rust backend devs", "Indie iOS devs", "Agency SEO leads",
"Growth marketers", "Solo SaaS founders", "Data engineers", "Design leads".
Never use these words: product, products, utility, utilities, tool, tools, tech, enthusiast(s), innovator(s), evaluator(s), curator(s),
observer(s), builder(s), maker(s), creator(s), user(s), adopter(s), savvy, digital, professional(s), people, folks, community.
Each name must describe a kind of PERSON (never a technology, e.g. not "AI agents"); keep to the group's stated role when one is given, and
add ONE qualifier that ties it to this product's world, taken from the group's own distinctive topics, products or headline words
(e.g. "Video-ad marketers", "API-first devs", "Fintech founders", "Docs-minded engineers"). A bare role ("Software engineers") is not enough.
Names must be clearly different from each other, and specific to this product's audience (not a name that would fit any launch). Then "who": one short plain sentence (max 14 words) on who they are.
{groups}

2) COMPETITORS: the most similar earlier launches (pick up to 3 that really compete; keep their names exactly).
{comps}

3) Two lines comparing THIS product with those competitors, as a sharp human reader would say it:
"like": what people will probably like here vs the competitors. "dislike": what they won't like or will push back on vs the competitors.
Each max 16 words, casual, concrete, no hype, written as a statement (not a question). Don't open with "People", "They", "Users", "It might" or "Might"; lead with the specific thing itself, the way one person types a comment. No stock openers: never start with "Love that", "Shame", "Finally", "Nice that", "Great", "It's", "Only". Every fact must come from THIS product's text or the competitor themes above; never invent platforms, prices or limits. Do NOT use: seamless, game-changer, robust, leverage, powerful, innovative, streamline,
revolutionize, cutting-edge, users, commenters. Write them the way these real Product Hunt comments sound (tone only; never copy them):
{tone}
What people said about the competitors (themes): {themes}
Likely questions about this product: {concerns}

Return {{"groups": [{{"gid": <int>, "name": "...", "who": "..."}}], "competitors": ["..."], "like": "...", "dislike": "..."}}"""

def comp_block(lid):
    items = ((LAUNCH.get(lid) or {}).get("competitors") or {}).get("items") or []
    if not isinstance(items, list): items = []
    comps, themes, tone = [], [], []
    me = re.sub(r"[^a-z0-9]", "", str((LAUNCH.get(lid) or {}).get("name", "")).lower())
    items = [c for c in items if re.sub(r"[^a-z0-9]", "", c["name"].lower()) != me]   # its own earlier launch is not a competitor
    for c in items[:5]:
        comps.append(f"- {c['name']} (launched {c.get('launch_date')}, finished #{c.get('final_daily_rank')})")
        for k in ("commenters_praised", "commenters_complained"):
            if isinstance(c.get(k), list): themes += [f"{c['name']} {'+' if 'praised' in k else '-'}: {t}" for t in c[k][:2]]
        cid = BYND.get((c["name"].strip().lower(), c.get("launch_date")))
        tone += [SCRUB(t) for t in (CBY.get(cid) or [])[:3]]
    if len(tone) < 4: tone += [SCRUB(t) for t in C.sample(6, random_state=int(lid) % 1000).text]
    return "\n".join(comps) or "(none found)", "; ".join(themes[:10]) or "(none)", "\n".join(f'- "{t}"' for t in tone[:8])

def one(lid):
    p = line.get(lid) or {}
    try: G, n, sil, n_blank = groups_for(lid)
    except Exception as e: return lid, {"status": f"groups failed: {type(e).__name__}"}
    comps, themes, tone = comp_block(lid)
    say = (LAUNCH.get(lid) or {}).get("say") or {}
    gtxt = "\n".join(f"[gid {g['gid']}] {int(g['share']*100)}% of them. stated role: {g.get('role') or 'mixed'}. distinctive headline words: {', '.join(g['headline_words'])}; topics: {', '.join(g['topics_by_lift'])}; "
                     f"products they upvoted: {', '.join(map(str, g['products_upvoted'][:6]))}; sample headlines: {' / '.join(g['sample_headlines'][:8])}" for g in G)
    topics = ", ".join(e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or [])) if p else ""
    PROMPT_FULL = PROMPT.format(name=p.get("name") or (LAUNCH.get(lid) or {}).get("name"), tagline=p.get("tagline", ""), desc=str(p.get("description") or "")[:600], topics=topics,
                                        groups=gtxt, comps=comps, tone=tone, themes=themes, concerns="; ".join((say.get("top_concerns") or [])[:3]) if isinstance(say.get("top_concerns"), list) else "")
    txt = llm.gemini_call(PROMPT_FULL, 1500)
    try: J = json.loads(txt)
    except Exception: return lid, {"status": "model reply not parseable"}
    bad = [g.get("name", "") for g in J.get("groups", []) if BAN.search(g.get("name", ""))]
    for _ in range(2):   # up to two retries naming the offending words
        bad = [g.get("name", "") for g in J.get("groups", []) if BAN.search(g.get("name", ""))]
        if not bad: break
        txt = llm.gemini_call(PROMPT_FULL + f"\n\nYour names {bad} contain banned words ({', '.join(sorted({m.group(0).lower() for n in bad for m in BAN.finditer(n)}))}). "
                              "Give new names for ALL groups without any banned word: name the role or trade instead (e.g. 'Ad buyers', 'Video editors', 'Backend devs').", 1500)
        try: J = json.loads(txt)
        except Exception: break
    for g in J.get("groups", []):   # last resort: strip any banned word that survived the retries
        if BAN.search(g.get("name", "")):
            w = BAN.sub("", g["name"]).split(); g["name"] = " ".join(w + (["crowd"] if len(w) < 2 else []))
    nm = {int(g["gid"]): g for g in J.get("groups", [])}
    return lid, {"name": p.get("name") or (LAUNCH.get(lid) or {}).get("name"), "tagline": p.get("tagline"), "people_scored": n, "no_profile_text": n_blank, "silhouette": sil,
                 "groups": [{"name": nm.get(g["gid"], {}).get("name"), "who": nm.get(g["gid"], {}).get("who"), "share": g["share"], "n_people": g["n"], "role": g.get("role"), "role_lift_vs_todays_backers": g.get("role_lift"),
                             "evidence": {"headline_words": g["headline_words"][:6], "topics": g["topics_by_lift"][:4]}} for g in G],
                 "competitors": J.get("competitors", []), "like": J.get("like"), "dislike": J.get("dislike")}

BASE_ROLE.update(base_roles())
pub = pd.read_parquet(f"{SP}/par/forecast_{D}.parquet"); pub["id"] = pub.id.astype(str)
order = pub.sort_values("pred_arm3" if "pred_arm3" in pub else "pred", ascending=False).id.tolist()
ids = [i for i in order if i in set(BP.launch_id)][:LIM]
with cf.ThreadPoolExecutor(6) as ex: R = dict(ex.map(one, ids))
# board pass (Shreyas Nov 17: repetitive openers): lines whose first two words repeat across today's cards are rewritten in one call
def opener(x): return " ".join(re.findall(r"[a-z']+", (x or "").lower())[:2])
LINES = [(i, k, R[i][k]) for i in R if "groups" in R[i] for k in ("like", "dislike") if R[i].get(k)]
cnt = pd.Series([opener(t) for _, _, t in LINES]).value_counts()
BADSTART = re.compile(r"^(love|shame|finally|nice|great|only|it|it's|people|they|users|might)\b", re.I)
rep = [(i, k, t) for i, k, t in LINES if cnt[opener(t)] > 1 or BADSTART.search(t.strip())]
if rep:
    REW = """These short one-line takes about different products all start the same way, which reads robotic. Rewrite each so that no two start with
the same two words and none starts with "Love", "Shame", "Finally", "Nice", "Great", "Only", "It", "It's", "People", "They", "Might". Keep every fact, the
like/dislike direction and the product names exactly; max 16 words; casual, specific, like one person typing a comment. JSON only:
{"lines": [{"n": <n>, "text": "..."}]}
""" + "\n".join(f"[{n}] ({k}) {t}" for n, (_, k, t) in enumerate(rep))
    try:
        new = {int(x["n"]): x["text"] for x in json.loads(llm.gemini_call(REW, 4000))["lines"]}
        for n, (i, k, t) in enumerate(rep):
            if new.get(n): R[i][k] = new[n]
    except Exception as e: print("opener pass failed:", repr(e)[:200])
for i in R:
    if i in DIAG and "groups" in R[i]: R[i]["separation"] = DIAG[i]
usd = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)
open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a").write(json.dumps({"t": f"product_groups_{D}", "provider": "gcp", "usd": usd, "note": f"{len(ids)} Gemini 2.5 Flash calls"}) + "\n")
json.dump({"day": D, "order": ids, "cards": R, "usd": usd,
           "method": "groups clustered inside each launch's top-300 likely backers (headline/bio words + upvote topics), named by Gemini; competitors = most similar earlier launches; like/dislike lines written by Gemini from competitors' real comment themes"},
          open(f"{OUT}/{D}.json", "w"), indent=1)
print(json.dumps({"day": D, "launches": len(ids), "ok": sum(1 for v in R.values() if "groups" in v), "usd": usd}))
