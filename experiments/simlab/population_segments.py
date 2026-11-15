"""Data-driven population segments (Shreyas, Nov 15: replace the keyword role labels; groups and subgroups labelled with who they are, what
they likely say and who they likely vote for; keep recalibrating).

DATING: everything uses launches dated before the cut C and reads fetched before C (default: now). Re-run nightly; segments keep stable ids.
1. Groups (taste). People with >= MIN_UP upvotes on launches of the 730 days before C. Features = TF-IDF topic profile (L2) of
   the launches they upvoted (launch co-vote SVD factors were tried and dropped: they grouped people by active weeks, not taste). MiniBatchKMeans, K groups. People with 1..MIN_UP-1 upvotes are assigned to the nearest
   group by their topic profile (flag low_signal). People with no upvote in the window: group "not active in the last 180 days".
2. Subgroups (style, within each group). Standardised [ln(1+upvotes 30d), comment rate, made/hunted a launch, reviews+stacks, follows,
   role keywords (multi-hot; no headline/bio is its own column)]; KMeans with k = 2..4 by group size, each subgroup >= 20 people.
3. Descriptors (computed, aggregate only): size, activity, role mix, share commenting / making, topics by lift vs the whole population,
   products most upvoted (share of the group and lift), and up to 60 of the group's own comments (text matched by comment id from the
   launch-page dump, condensed by Gemini into themes, never quoted).
4. Names: Gemini 2.5 Flash names ALL groups in one comparative call (then each group's subgroups in one call) from the descriptors only,
   told that shared traits (developer / founder / AI) do not distinguish and names must differ; topic-lift fallback if the call fails.
   Stable ids: new centroids are matched to the previous run's (Hungarian, cosine); a matched group keeps its id and name unless its
   descriptors drift (top-10 lifted topics overlap < 5), then it is renamed.
5. Calibration (every run): cut C' = C - 7 days, refit groups on data before C', then for each launch dated in [C', C) with >= 20 held
   backers compare the backers' group mix with (a) the model mix (group sizes x each group's affinity for the launch's topics) and
   (b) the population mix (group shares of upvotes in the 30 days before C'). Metric = mean total-variation distance (lower is better), launch bootstrap. Also: per group, the upvote-rate
   lift on launches whose first topic is one of the group's top-5 lifted topics (does "votes_for" hold out of sample?). Appended to
   history so drift is visible.
Outputs: PRIVATE person -> group/subgroup (salted ids) gs://.../tmp/e5/private/segments/<C>.parquet; PUBLIC (aggregates, groups/subgroups
>= 20 people, no ids/usernames/headlines): results/web/segments/<C>.json and results/web/segments/latest.json; calibration history
results/web/segments/calibration_history.jsonl. Launch topics: warehouse (2026) + H25_SRC daily files (2025) when set.
    H25_SRC=<dir> python population_segments.py <store dir> <cf dir> <scratchpad> [--cut YYYY-MM-DD] [--k 12] [--no-upload] [--no-llm]"""
import gzip, glob, html, json, os, re, subprocess, sys, time
import numpy as np, pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfTransformer
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from pipeline import warehouse  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, CFD, SP = args[:3]
opt = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
CUT = opt("--cut", pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")); K = int(opt("--k", 12)); UP = "--no-upload" not in sys.argv; LLM = "--no-llm" not in sys.argv
MIN_UP, MIN_N, WIN = 5, 20, 730
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; OUTD = os.path.join(SP, "segments"); os.makedirs(OUTD, exist_ok=True)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
rng = np.random.default_rng(0); t0 = time.time(); log = lambda *a: print(round(time.time() - t0), *a, flush=True)

# ---------- data (dated)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at", "extra", "ts_lo"])
E["ft"] = pd.to_datetime(E.fetched_at, utc=True)
if E.ft.min() < pd.Timestamp(CUT, tz="UTC"): E = E[E.ft < pd.Timestamp(CUT, tz="UTC")]
else: print("historical cut: reads were all fetched after the cut; dating by launch day (upvotes) and comment time instead", flush=True)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["tops"] = W.topics.map(lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else [])
if os.environ.get("H25_SRC"):   # 2025 featured launches (daily API files): the warehouse starts 2026-01-01
    x25 = [(str(e["id"]), os.path.basename(f)[:10], e.get("name"), [t["node"]["name"] for t in ((e.get("topics") or {}).get("edges") or [])] if isinstance(e.get("topics"), dict) else (e.get("topics") or []))
           for f in glob.glob(os.path.join(os.environ["H25_SRC"], "*.json")) for e in json.load(open(f))]
    W = pd.concat([pd.DataFrame(x25, columns=["id", "day", "name", "tops"]), W[["id", "day", "name", "tops"]]]).drop_duplicates("id", keep="last")
lday = dict(zip(W.id, W.day)); ltops = dict(zip(W.id, W.tops)); lname = dict(zip(W.id, W.name))
U0 = E[E.kind == "upvote"][["person_id", "target_id"]].copy(); U0["target_id"] = U0.target_id.astype(str); U0["lday"] = U0.target_id.map(lday); U0 = U0[U0.lday.notna()].drop_duplicates(["person_id", "target_id"])
PJ = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id").set_index("person_id")
cnt = lambda k: E[E.kind == k].groupby("person_id").size()
STYLE_RAW = {"comments": cnt("comment"), "made": cnt("launched").add(cnt("hunted"), fill_value=0), "reviews_stacks": cnt("review").add(cnt("stack"), fill_value=0),
             "follows": cnt("follows")}
ROLES = [("investor", r"\b(investor|vc|venture|angel)\b"), ("designer", r"(design|\bux\b|\bui\b|figma|illustrat)"),
         ("developer", r"(engineer|developer|\bdev\b|software|full[- ]?stack|backend|frontend|programm|devops|data scien|machine learning|\bml\b|\bai\b)"),
         ("marketer", r"(marketing|marketer|growth|\bseo\b|content|brand|social media|copywrit|community)"),
         ("product", r"(product manager|\bpm\b|product lead|product owner|head of product)"),
         ("founder", r"(founder|\bceo\b|indie|maker|solopreneur|bootstrap|entrepreneur)"), ("student", r"(student|university|college)")]
txt = (PJ.headline.fillna("") + " " + PJ.bio.fillna("")).str.lower()
RM = pd.DataFrame({r: txt.str.contains(rx, regex=True) for r, rx in ROLES}, index=PJ.index).astype(float); RM["no headline or bio"] = (txt.str.strip() == "").astype(float)
log("data", len(U0))
cmt_ids = E[(E.kind == "comment") & (pd.to_datetime(E.ts_lo, utc=True) < pd.Timestamp(CUT, tz="UTC"))][["person_id", "extra"]].copy()   # comments written before the cut only
cmt_ids["cid"] = cmt_ids.extra.map(lambda e: json.loads(e).get("comment_id") if isinstance(e, str) and e.startswith("{") else None)
want = dict(zip(cmt_ids.cid.dropna().astype(str), cmt_ids.dropna(subset=["cid"]).person_id)); ctext = {}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_: continue
        def walk(nd):
            i = str(nd.get("id"))
            if i in want:
                t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", nd.get("bodyHtml") or ""))).strip()
                if len(t) > 25: ctext.setdefault(want[i], []).append(t[:400])
            for e in ((nd.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
log("comment texts for people", len(ctext))


PH = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "joined", "badges_count", "links_json", "maker_history_json", "header_json"]).drop_duplicates("person_id").set_index("person_id")
HD = PH.header_json.map(lambda h: json.loads(h) if isinstance(h, str) and h.startswith("{") else {})
hv = lambda k_: pd.to_numeric(HD.map(lambda h: h.get(k_)), errors="coerce").fillna(0).clip(lower=0).astype(float)
LK = PH.links_json.map(lambda h: " ".join(json.loads(h)) if isinstance(h, str) and h.startswith("[") else "").str.lower()
from sklearn.decomposition import TruncatedSVD  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
CTX = pd.Series({p_: " ".join(v) for p_, v in ctext.items()})
_tv = TfidfVectorizer(min_df=5, max_features=20000, stop_words="english", sublinear_tf=True).fit(CTX.values)
CT = pd.DataFrame(TruncatedSVD(8, random_state=0).fit_transform(_tv.transform(CTX.values)), index=CTX.index, columns=[f"ctext{i}" for i in range(8)])
PROFILE = pd.DataFrame({   # UNDATED profile state (read Nov 2026): kind-of-user descriptors, not used as vote labels
    "ln_lifetime_upvotes": np.log1p(hv("upvotes")), "ln_followers": np.log1p(hv("followers")),
    "ln_following": np.log1p(hv("following")), "ln_products": np.log1p(hv("products")),
    "ln_hunted": np.log1p(hv("hunted")), "ln_reviews": np.log1p(hv("reviews")),
    "ln_stacks": np.log1p(hv("stacks")), "ln_collections": np.log1p(hv("collections")),
    "ln_badges": np.log1p(PH.badges_count.fillna(0).astype(float)),
    "account_years": ((pd.Timestamp(CUT, tz="UTC") - pd.to_datetime(PH.joined, utc=True, errors="coerce")).dt.days / 365.25).clip(0, 15).fillna(0),
    "ln_maker_history": np.log1p(PH.maker_history_json.map(lambda h: len(json.loads(h)) if isinstance(h, str) and h.startswith("[") else 0).astype(float)),
    "has_x": LK.str.contains(r"twitter\.com|x\.com/").astype(float), "has_linkedin": LK.str.contains("linkedin").astype(float),
    "has_github": LK.str.contains("github").astype(float), "has_website": (LK.str.len() > 0).astype(float)}, index=PH.index)
BLOCKS = {"activity": ["ln_up90", "ln_up730", "ln_lifetime_upvotes", "ln_comments", "has_dated_upvote"], "making": ["ln_products", "ln_hunted", "ln_maker_history"],
          "social": ["ln_followers", "ln_following", "account_years"], "curation": ["ln_reviews", "ln_stacks", "ln_collections", "ln_badges"],
          "links": ["has_x", "has_linkedin", "has_github", "has_website"], "comment_text": [f"ctext{i}" for i in range(8)] + ["has_comment_text"],
          "role": [r for r, _ in ROLES] + ["no headline or bio"]}
VOTERS = bool(os.environ.get("VOTERS")); VOTERS_DAYS = int(os.environ.get("VOTERS_DAYS", 180)); VOTERS_MIN = int(os.environ.get("VOTERS_MIN", 3))
TASTE_W = float(os.environ.get("TASTE_W", 3.0 if VOTERS else 2.0))   # taste weighted up: segments are used to say who votes for what


def fit_groups(cut, k, seed=0, topics=None):   # v2: every held person, kind-of-user features (dated taste + activity; undated profile state)
    d0 = (pd.Timestamp(cut) - pd.Timedelta(days=WIN)).strftime("%Y-%m-%d"); d90 = (pd.Timestamp(cut) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    U = U0[(U0.lday < cut) & (U0.lday >= d0)]; n = U.groupby("person_id").size()
    TP = U.assign(t=U.target_id.map(ltops)).explode("t").dropna(subset=["t"])
    tc = TP.t.value_counts(); topics = topics or list(tc[tc >= 200].index)
    ti = {t: i for i, t in enumerate(topics)}; TP = TP[TP.t.isin(ti)]
    ppl = list(PJ.index)
    if VOTERS:   # v4: cluster only people who vote (>= VOTERS_MIN dated upvotes in the VOTERS_DAYS before the cut); everyone else is "rare voters" (group -1, not split)
        dv = (pd.Timestamp(cut) - pd.Timedelta(days=VOTERS_DAYS)).strftime("%Y-%m-%d"); nv = U[U.lday >= dv].groupby("person_id").size()
        act = set(nv[nv >= VOTERS_MIN].index); ppl = [p for p in ppl if p in act]
    pi = {p: i for i, p in enumerate(ppl)}; TP = TP[TP.person_id.isin(pi)]
    M = csr_matrix((np.ones(len(TP)), (TP.person_id.map(pi), TP.t.map(ti))), shape=(len(ppl), len(topics)))
    Tt = TfidfTransformer().fit(M[np.asarray(M.sum(1)).ravel() >= MIN_UP]).transform(M).toarray(); Tt /= np.linalg.norm(Tt, axis=1, keepdims=True) + 1e-9
    conf = np.minimum(1.0, n.reindex(ppl).fillna(0).values / 10.0)[:, None]   # taste weight grows with evidence: full at >= 10 dated upvotes
    X = pd.DataFrame(index=ppl)
    X["ln_up90"] = np.log1p(U[U.lday >= d90].groupby("person_id").size().reindex(ppl).fillna(0)); X["ln_up730"] = np.log1p(n.reindex(ppl).fillna(0))
    X["ln_comments"] = np.log1p(STYLE_RAW["comments"].reindex(ppl).fillna(0)); X["has_dated_upvote"] = (n.reindex(ppl).fillna(0) > 0).astype(float)
    X = X.join(PROFILE.reindex(ppl).fillna(0)).join(CT.reindex(ppl).fillna(0)); X["has_comment_text"] = X.index.isin(CT.index).astype(float)
    X = X.join(RM.reindex(ppl).fillna(0))
    Z = (X - X.mean()) / (X.std() + 1e-9)
    parts = [Tt * conf * TASTE_W] + [Z[c].values / np.sqrt(len(c)) for b, c in BLOCKS.items() if not (VOTERS and b == "activity")]   # v4: activity level left out
    F = np.hstack(parts); bad = ~np.isfinite(F)
    if bad.any(): log("non-finite feature cells set to 0:", int(bad.sum()), "columns:", sorted({c for c in X.columns if not np.isfinite(Z[c].values).all()})[:8]); F[bad] = 0
    km = MiniBatchKMeans(k, random_state=seed, n_init=5, batch_size=8192).fit(F)
    g = pd.Series(km.labels_, index=ppl)
    TC = np.array([(Tt * conf)[(km.labels_ == j)].mean(0) for j in range(k)]); TC /= np.linalg.norm(TC, axis=1, keepdims=True) + 1e-9
    return {"core": g, "weak": pd.Series(dtype=int), "U": U, "topics": topics, "TC": TC, "n": n, "X": X, "centroids": km.cluster_centers_, "F": F}


def nest(Gk, kf, seed=0):   # subgroups: k-means on the full feature vector inside each group, ~kf in total (proportional to size), each >= MIN_N
    lab_, F = Gk["core"], Gk["F"]; fine = pd.Series(0, index=lab_.index); N = len(lab_)
    for g in sorted(lab_.unique()):
        ix = np.flatnonzero(lab_.values == g); k = int(max(1, min(round(kf * len(ix) / N), len(ix) // MIN_N)))
        lb = MiniBatchKMeans(k, random_state=seed, n_init=3, batch_size=4096).fit_predict(F[ix]) if k > 1 else np.zeros(len(ix), int)
        vc = pd.Series(lb).value_counts(); small = set(vc[vc < MIN_N].index)
        if small: lb = np.array([vc.index[0] if x in small else x for x in lb])
        fine.iloc[ix] = lb
    return fine


def heldout_ll(Gc, cp, cut, alpha=1.0):   # mean log P(voter) per held-out vote: P = mix_g(launch) / n_g, mix from vote share x topic affinity
    labc = Gc["core"]; Ux = Gc["U"].assign(g=lambda x: x.person_id.map(labc), t=lambda x: x.target_id.map(ltops)).explode("t").dropna(subset=["t"]).reset_index(drop=True)
    A = pd.crosstab(Ux.g, Ux.t).reindex(range(labc.max() + 1)).fillna(0)
    pop = A.sum(0) / A.values.sum(); A = (A + alpha * 50 * pop).div((A + alpha * 50 * pop).sum(1), axis=0); Ar = A / pop
    r30 = (pd.Timestamp(cp) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    vs = Gc["U"][Gc["U"].lday >= r30].person_id.map(labc).value_counts().reindex(range(labc.max() + 1)).fillna(0) + 1; vs = vs / vs.sum()
    ng = labc.value_counts().reindex(range(labc.max() + 1)).fillna(0)
    Un = U0[(U0.lday >= cp) & (U0.lday < cut) & U0.person_id.isin(labc.index)]; per = []
    for lid, g_ in Un.groupby("target_id"):
        if len(g_) < 20: continue
        tps = [t for t in (ltops.get(lid) or []) if t in Ar.columns]
        mix = vs * (Ar[tps].mean(axis=1) if tps else 1.0); mix = mix / mix.sum()
        gv = g_.person_id.map(labc).values; per.append(float(np.mean(np.log(mix.values[gv] / ng.values[gv]))))
    return np.array(per)


def topic_aff(G, U):   # group x topic propensity: share of the group's upvotes on launches with that topic
    lab = pd.concat([G["core"], G["weak"]]); Ux = U[U.person_id.isin(lab.index)].assign(g=lambda x: x.person_id.map(lab), t=lambda x: x.target_id.map(ltops)).explode("t").dropna(subset=["t"]).reset_index(drop=True)
    A = pd.crosstab(Ux.g, Ux.t); return A.div(A.sum(1), axis=0)


# ---------- choose k (Shreyas, Nov 15: "keep 3-5, then 3-5 subgroups if necessary"): top level k in 3..5 by held-out fit (fit at C - 7 days,
# score last week's voters); k = 12 reported for the trade-off. Subgroups: 3..5 per group only where splitting adds held-out fit.
cp0 = (pd.Timestamp(CUT) - pd.Timedelta(days=7)).strftime("%Y-%m-%d"); KSEL = {}
def bsd(d):
    b_ = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(1000)]
    return [round(float(d.mean()), 4), round(float(np.percentile(b_, 2.5)), 4), round(float(np.percentile(b_, 97.5)), 4)]
base = heldout_ll(fit_groups(cp0, 1), cp0, CUT)
for k_ in (3, 4, 5, 12):
    ll = np.mean([heldout_ll(fit_groups(cp0, k_, seed=sd), cp0, CUT) for sd in (0, 1)], axis=0)
    KSEL[k_] = {"mean_log_lik_per_vote": round(float(ll.mean()), 4), "gain_vs_k1 [95% launch bootstrap]": bsd(ll - base), "launches": int(len(ll))}
    log("k", k_, KSEL[k_])
if "--k" not in sys.argv: K = max((3, 4, 5), key=lambda k_: KSEL[k_]["mean_log_lik_per_vote"])
Gn = fit_groups(cp0, K); lln = heldout_ll(Gn, cp0, CUT)


def split(Gk, g, ks, seed=0):   # split group g of fit Gk into ks k-means subgroups (each >= MIN_N); returns per-person sub index (0 elsewhere)
    lab_, F = Gk["core"], Gk["F"]; out = pd.Series(0, index=lab_.index); ix = np.flatnonzero(lab_.values == g)
    if ks <= 1 or len(ix) < ks * MIN_N: return out
    lb = KMeans(ks, random_state=seed, n_init=5).fit_predict(F[ix]); vc = pd.Series(lb).value_counts(); small = set(vc[vc < MIN_N].index)
    if small: lb = np.array([vc.index[0] if x in small else x for x in lb])
    out.iloc[ix] = pd.factorize(lb)[0]; return out


SUBK_cp, SUBSEL = {}, {}
for g in range(K):
    best = (1, None)
    for ks in (3, 4, 5):
        sg_ = split(Gn, g, ks); lab2 = pd.Series(pd.factorize(Gn["core"].astype(str) + "." + sg_.astype(str))[0], index=sg_.index)
        d = heldout_ll({"core": lab2, "U": Gn["U"]}, cp0, CUT) - lln; b_ = bsd(d)
        SUBSEL[f"{g}:{ks}"] = {"gain_vs_unsplit [95% launch bootstrap]": b_}
        if b_[1] > 0 and (best[1] is None or b_[0] > best[1][0]): best = (ks, b_)
    SUBK_cp[g] = best[0]
nest_lab = pd.Series(0, index=Gn["core"].index)
for g in range(K): nest_lab = nest_lab + split(Gn, g, SUBK_cp[g])
labn = pd.Series(pd.factorize(Gn["core"].astype(str) + "." + nest_lab.astype(str))[0], index=nest_lab.index)
lln2 = heldout_ll({"core": labn, "U": Gn["U"]}, cp0, CUT)
KSEL["chosen"] = {"groups": K, "subgroups per group (fit 7 days earlier)": SUBK_cp, "gain_vs_k1 groups": bsd(lln - base), "gain_vs_k1 groups+subgroups": bsd(lln2 - base),
                  "chosen minus k=12 (log-lik per vote)": round(KSEL[K]["mean_log_lik_per_vote"] - KSEL[12]["mean_log_lik_per_vote"], 4),
                  "groups+subgroups minus k=12": round(float(lln2.mean()) - KSEL[12]["mean_log_lik_per_vote"], 4), "subgroup splits tested": SUBSEL}
log("chosen", json.dumps({k: v for k, v in KSEL["chosen"].items() if k != "subgroup splits tested"}))

# ---------- fit at the cut; stable ids by member overlap with the previous run
G = fit_groups(CUT, K); lab = pd.concat([G["core"], G["weak"]]); log("groups", lab.value_counts().sort_index().to_dict())
def overlap_map(cur, prv, thr=0.5):   # Hungarian on Jaccard of member sets; returns {cur label: prev label} for pairs with J >= thr, and the J values
    cur, prv = cur.dropna(), prv.dropna()   # v4: the voter set changes between the fit and the cut
    cl, pl = sorted(cur.unique()), sorted(prv.unique()); cs = {a: set(cur.index[cur == a]) for a in cl}; ps = {b: set(prv.index[prv == b]) for b in pl}
    J = np.array([[len(cs[a] & ps[b]) / max(1, len(cs[a] | ps[b])) for b in pl] for a in cl]); r, c = linear_sum_assignment(-J)
    return {cl[a]: pl[b] for a, b in zip(r, c) if J[a, b] >= thr}, {cl[a]: round(float(J[a, b]), 3) for a, b in zip(r, c)}
prev = json.loads(gcat(f"{B}/results/web/segments/latest.json") or "{}") if UP else (json.load(open(os.path.join(OUTD, "latest.json"))) if os.path.exists(os.path.join(OUTD, "latest.json")) else {})
if "--rename" in sys.argv: prev = {}   # segmentation design changed; do not inherit old ids or names
prevM = None
if prev.get("groups"):
    raw = subprocess.run(["gsutil", "cat", f"{B}/tmp/e5/private/segments/latest.parquet"], capture_output=True).stdout if UP else None
    import io  # noqa: E402
    prevM = pd.read_parquet(io.BytesIO(raw)) if raw else (pd.read_parquet(os.path.join(OUTD, f"members_{prev['cut']}.parquet")) if os.path.exists(os.path.join(OUTD, f"members_{prev['cut']}.parquet")) else None)
remap, JG, prev_names = {j: j for j in range(K)}, {}, {}
if prevM is not None:
    pm, JG = overlap_map(lab, prevM.set_index("person_id").group.reindex(lab.index).fillna(-1).astype(int))
    pm = {a: b for a, b in pm.items() if b >= 0}; used = set(pm.values()); free = [i for i in range(100) if i not in used and i not in {g["id"] for g in prev["groups"]}]
    remap = {a: (pm[a] if a in pm else free.pop(0)) for a in range(K)}; prev_names = {g["id"]: g for g in prev["groups"]}
JG = {remap[a]: v for a, v in JG.items()}
lab = lab.map(remap); G["core"] = G["core"].map(remap); G["weak"] = G["weak"].map(remap)
inv = {v: k for k, v in remap.items()}

# ---------- subgroups at the cut: the number chosen on the earlier fit, carried to the matching current group (member overlap)
gmap_cp, _ = overlap_map(lab, Gn["core"].reindex(lab.index), thr=0.0)
c30 = (pd.Timestamp(CUT) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); n30 = G["U"][G["U"].lday >= c30].groupby("person_id").size()
ST_ = pd.DataFrame(index=lab.index)
ST_["ln_up30"] = np.log1p(n30.reindex(lab.index).fillna(0)); ST_["comment_rate"] = (STYLE_RAW["comments"].reindex(lab.index).fillna(0) / (G["n"].reindex(lab.index).fillna(0) + 1)).clip(0, 3)
ST_["made"] = (STYLE_RAW["made"].reindex(lab.index).fillna(0) > 0).astype(float); ST_["reviews_stacks"] = np.log1p(STYLE_RAW["reviews_stacks"].reindex(lab.index).fillna(0))
ST_["ln_follows"] = np.log1p(STYLE_RAW["follows"].reindex(lab.index).fillna(0))
ST_ = ST_.join(RM.reindex(lab.index).fillna(0))
ST_ = ST_.fillna(0); Zs = (ST_ - ST_.mean()) / (ST_.std() + 1e-9)
sub = pd.Series(0, index=lab.index); SUBK = {}
for g in sorted(lab.unique()):
    SUBK[g] = SUBK_cp.get(gmap_cp.get(g), 1); sub = sub + split({"core": G["core"], "F": G["F"]}, g, SUBK[g])
# stable subgroup ids within a kept group
if prevM is not None:
    for g in sorted(lab.unique()):
        ix = lab.index[lab == g]; ps_ = prevM.set_index("person_id").subgroup.reindex(ix).fillna("-1")
        ps_ = ps_[ps_.str.startswith(f"{g}.")]
        if len(ps_) and sub.loc[ix].nunique() > 1:
            sm, _ = overlap_map(sub.loc[ix], ps_.map(lambda x: int(x.split(".")[1])))
            used = set(sm.values()); free = [i for i in range(20) if i not in used]
            sub.loc[ix] = sub.loc[ix].map(lambda x: sm[x] if x in sm else free[x % len(free)])
log("subgroups", SUBK)

# ---------- descriptors
pop_t = G["U"].assign(t=G["U"].target_id.map(ltops)).explode("t").dropna(subset=["t"]); pop_share = pop_t.t.value_counts(normalize=True)
pop_prod = G["U"].groupby("target_id").person_id.nunique() / max(1, G["U"].person_id.nunique())



POP_ROLE = RM.reindex(lab.index).fillna(0); POP_ROLE = POP_ROLE[POP_ROLE["no headline or bio"] == 0].mean()
POP_ACT = float(G["n"].reindex(lab.index).fillna(0).median())


def describe(people):
    people = list(people); Ug = G["U"][G["U"].person_id.isin(set(people))]
    tg = Ug.assign(t=Ug.target_id.map(ltops)).explode("t").dropna(subset=["t"]).t.value_counts(normalize=True)
    lift = (tg / pop_share.reindex(tg.index)).dropna(); lift = lift[tg.reindex(lift.index) >= 0.01].sort_values(ascending=False)
    pr = Ug.groupby("target_id").person_id.nunique() / len(people); pl = (pr / pop_prod.reindex(pr.index)).dropna()
    top_prod = pr[pr >= 0.05].sort_values(ascending=False).head(8)
    dist = pl[(pr.reindex(pl.index) >= 0.03)].sort_values(ascending=False).head(8)   # distinctive: most over-represented vs the population
    rm = RM.reindex(people).fillna(0); hasbio = rm["no headline or bio"] == 0
    cm = [t for p in rng.permutation(people)[:4000] for t in ctext.get(p, [])[:2]][:60]
    return {"n_people": len(people), "median_upvotes_last_30_days": float(n30.reindex(people).fillna(0).median()),
            "median_upvotes_in_window": float(G["n"].reindex(people).fillna(0).median()),
            "share_commenting": round(float((STYLE_RAW["comments"].reindex(people).fillna(0) > 0).mean()), 3),
            "share_made_or_hunted_a_launch": round(float((STYLE_RAW["made"].reindex(people).fillna(0) > 0).mean()), 3),
            "share_no_headline_or_bio": round(float(1 - hasbio.mean()), 3),
            "profile_medians": {k_: round(float(np.expm1(PROFILE[k_].reindex(people).median()) if k_.startswith("ln_") else PROFILE[k_].reindex(people).median()), 1)
                                for k_ in ("ln_lifetime_upvotes", "ln_followers", "ln_following", "ln_products", "account_years")},
            "share_with_link": {k_: round(float(PROFILE[k_].reindex(people).mean()), 3) for k_ in ("has_x", "has_linkedin", "has_github")},
            "roles_among_people_with_bio": {r: round(float(rm.loc[hasbio, r].mean()), 3) for r, _ in ROLES} if hasbio.any() else {},
            "role_lift_vs_population": {r: round(float(rm.loc[hasbio, r].mean() / POP_ROLE[r]), 2) for r, _ in ROLES if POP_ROLE[r] > 0} if hasbio.any() else {},
            "topics_by_lift": [{"topic": t, "share": round(float(tg[t]), 3), "lift": round(float(v), 2)} for t, v in lift.head(10).items()],
            "products_most_upvoted": [{"product": lname.get(i, "?"), "share_of_group": round(float(v), 3), "lift": round(float(pl.get(i, np.nan)), 2)} for i, v in top_prod.items()],
            "products_distinctive": [{"product": lname.get(i, "?"), "share_of_group": round(float(pr[i]), 3), "lift": round(float(v), 2)} for i, v in dist.items()],
            "_comments": cm}


sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict"))
NAMEP = """You name and describe audience segments of Product Hunt users for a launch-analytics site. The segments below were found by
clustering real users on what they upvote and what KIND of user they are (activity, making, followers, curation, links, comments) ({level}). Almost everyone on Product Hunt is a developer or founder interested in AI, so those
traits do NOT distinguish segments: a name must come from what is DISTINCTIVE for that segment versus the others (topics and products with
high lift, role lift > 1.3, activity level relative to the population median of {pop_act:.0f} upvotes, commenting / making rates).
Every name must be clearly different from every other name (including the fixed names listed). Do not use the words "AI", "builders",
"native", "fluent" or "explorers" unless that segment's own lift data justifies it uniquely. Comment samples are members' own comments:
summarise recurring themes, never quote, never name people.
{parent}
SEGMENTS:
{segs}
Return JSON only: {{"segments": [{{"id": "<id>", "name": "<2-5 words>", "who": "<one sentence: who they are, from the data>",
"says": ["<recurring theme in what they say on launches>", "<another>", "<another>"], "votes_for": "<one sentence: which launches they back, naming topic areas>"}}, ...]}}
Return an entry for every segment that is not marked FIXED."""


def seg_block(sid, d, fixed=None, style=None):
    st = {k: d[k] for k in ("n_people", "median_upvotes_in_window", "median_upvotes_last_30_days", "share_commenting", "share_made_or_hunted_a_launch",
                            "share_no_headline_or_bio", "role_lift_vs_population", "profile_medians", "share_with_link")}
    st["topics_by_lift"] = [(t["topic"], t["lift"]) for t in d["topics_by_lift"][:8]]; st["products_distinctive"] = [(x["product"], x["lift"]) for x in d["products_distinctive"][:6]]
    if style: st["engagement_style_vs_population_z"] = style
    head = f"[{sid}] FIXED NAME: {fixed}" if fixed else f"[{sid}]"
    return head + " " + json.dumps(st) + "\n  comments: " + (" | ".join(c[:220] for c in d["_comments"][:20]) or "(none)")


def name_batch(items, level, parent=""):   # items: [(id, desc, fixed_name_or_None, style)]
    fallback = {sid: {"name": " & ".join(t["topic"] for t in d["topics_by_lift"][:2]) + (" (very active)" if d["median_upvotes_in_window"] > 3 * POP_ACT else ""),
                      "who": None, "says": None, "votes_for": "launches in " + ", ".join(t["topic"] for t in d["topics_by_lift"][:4])} for sid, d, _, _ in items}
    if not LLM or all(f for _, _, f, _ in items): return fallback
    import llm
    out = llm.gemini_call(NAMEP.format(level=level, pop_act=POP_ACT, parent=parent, segs="\n".join(seg_block(*x) for x in items)), 6000)
    try: R = {str(r["id"]): r for r in json.loads(out)["segments"]}
    except Exception: return fallback
    return {sid: ({k: R[sid].get(k) for k in ("name", "who", "says", "votes_for")} if sid in R and R[sid].get("name") else fallback[sid]) for sid, _, _, _ in items}


GD, SD, keepg = {}, {}, {}
for g in sorted(lab.unique()):
    ppl = lab.index[lab == g]; GD[g] = describe(ppl); pv = prev_names.get(int(g))
    keepg[g] = pv if pv and pv.get("name") and JG.get(g, 0) >= 0.5 else None   # same id and >= 50% member overlap keeps the name
    for s_ in sorted(sub.loc[ppl].unique()):
        sp_ = ppl[sub.loc[ppl].values == s_]
        if len(sp_) < MIN_N: continue
        ds = describe(sp_); sty = Zs.loc[sp_].mean().round(2).to_dict(); ds["style_vs_population_z"] = {k: v for k, v in sty.items() if abs(v) >= 0.3}
        SD[(g, s_)] = ds
log("descriptors done")
GN = name_batch([(str(int(g)), GD[g], (keepg[g] or {}).get("name"), None) for g in GD], "top-level groups (3-5), clustered on what kind of user people are")
for g in GD:
    if keepg[g]: GN[str(int(g))] = {k: keepg[g].get(k) for k in ("name", "who", "says", "votes_for")}
groups = []
for g in sorted(GD):
    nm = GN[str(int(g))]; pv = keepg[g]
    items = []
    for (g2, s_), ds in SD.items():
        if g2 != g: continue
        pm_ = next((x for x in (pv or {}).get("subgroups", []) if x.get("id") == f"{int(g)}.{int(s_)}"), None)
        items.append((f"{int(g)}.{int(s_)}", ds, (pm_ or {}).get("name"), ds["style_vs_population_z"]))
    SN = {} if len(items) <= 1 else name_batch(items, "subgroups of ONE group, split by engagement style (activity, commenting, making, reviews, follows, role); name them by how "
                    "they differ from each other within the group", f"PARENT GROUP: {nm.get('name')} - {nm.get('who')}") if items else {}
    for sid, ds, fx, _ in items:
        if fx: pm_ = next(x for x in pv["subgroups"] if x.get("id") == sid); SN[sid] = {k: pm_.get(k) for k in ("name", "who", "says", "votes_for")}
    subs = [{"id": sid, **SN[sid], **{k: v for k, v in ds.items() if not k.startswith("_")}, "n_comment_samples": len(ds["_comments"])} for sid, ds, _, _ in items] if len(items) > 1 else []
    tc = G["TC"][inv[g]]; d = GD[g]
    groups.append({"id": int(g), **nm, **{k: v for k, v in d.items() if not k.startswith("_")}, "n_comment_samples": len(d["_comments"]),
                   "renamed_this_run": not pv, "member_overlap_with_previous_run": JG.get(g), "subgroups": subs, "_topic_centroid": [round(float(x), 5) for x in tc], "_topics": G["topics"]})
    log("group", g, nm.get("name"), "|", [x["name"] for x in subs])
inactive = sorted(set(PJ.index) - set(lab.index))

# ---------- calibration (out of sample, every run)
cp = cp0; Gc = Gn; labc = Gc["core"]
Ac = topic_aff(Gc, Gc["U"]); r30 = (pd.Timestamp(cp) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
size = Gc["U"][(Gc["U"].lday >= r30) & Gc["U"].person_id.isin(labc.index)].person_id.map(labc).value_counts(normalize=True).reindex(sorted(labc.unique())).fillna(0)
popt = (Ac.mul(size.reindex(Ac.index).fillna(0), axis=0)).sum(0); Ar = Ac / popt
Un = U0[(U0.lday >= cp) & (U0.lday < CUT)]; tv_m, tv_p = [], []
for lid, g_ in Un.groupby("target_id"):
    bk = g_.person_id[g_.person_id.isin(labc.index)]
    if len(bk) < 20: continue
    act = labc.reindex(bk).value_counts(normalize=True).reindex(size.index).fillna(0)
    tps = [t for t in (ltops.get(lid) or []) if t in Ac.columns]
    if not tps: continue
    mod = size * Ar[tps].mean(axis=1).reindex(size.index).fillna(1); mod = mod / mod.sum()
    tv_m.append(0.5 * np.abs(act - mod).sum()); tv_p.append(0.5 * np.abs(act - size).sum())
tv_m, tv_p = np.array(tv_m), np.array(tv_p)
bs = lambda v: [round(float(v.mean()), 3)] + [round(float(np.percentile([v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)], q)), 3) for q in (2.5, 97.5)]
ULn = Un.target_id.unique()
def vf_lift(lbl):   # per unit: top-5 lifted topics from upvotes before cp; upvote-rate lift on last week's launches in those topics (relative, 1 = none)
    Ux = Gc["U"].assign(g=lambda x: x.person_id.map(lbl), t=lambda x: x.target_id.map(ltops)).explode("t").dropna(subset=["t", "g"]).reset_index(drop=True)
    A_ = pd.crosstab(Ux.g, Ux.t); A_ = A_.div(A_.sum(1), axis=0); pop_ = Ux.t.value_counts(normalize=True); out = {}
    for u in A_.index:
        mem = set(lbl.index[lbl == u])
        if len(mem) < MIN_N: continue
        top5 = list((A_.loc[u] / pop_.reindex(A_.columns))[A_.loc[u] >= 0.01].sort_values(ascending=False).head(5).index)
        L_in = [l for l in ULn if set(ltops.get(l) or []) & set(top5)]; L_out = [l for l in ULn if l not in set(L_in)]; oth = set(lbl.index) - mem
        if not L_in or not L_out: continue
        r_ = lambda Ls, P: len(Un[Un.target_id.isin(set(Ls)) & Un.person_id.isin(P)]) / max(1, len(P) * len(Ls))
        num = r_(L_in, mem) / max(1e-12, r_(L_in, oth)); den = r_(L_out, mem) / max(1e-12, r_(L_out, oth))
        nv = len(Un[Un.target_id.isin(set(L_in)) & Un.person_id.isin(mem)])
        out[u] = {"votes_for_lift_out_of_sample": round(num / max(1e-12, den), 2), "launches_in_its_topics_last_7_days": len(L_in), "member_votes_on_them": int(nv),
                  "votes_for_holds": bool(num / max(1e-12, den) >= 1.2 and len(L_in) >= 10 and nv >= 20)}
    return out
VG = vf_lift(labc); gm, _ = overlap_map(lab, labc.reindex(lab.index), thr=0.0)
cur_sub = (lab.astype(str) + "." + sub.reindex(lab.index).astype(str)); cp_sub = (labc.astype(str) + "." + nest_lab.astype(str)).reindex(lab.index).dropna()
VS = vf_lift((labc.astype(str) + "." + nest_lab.astype(str))); sm_all, _ = overlap_map(cur_sub, cp_sub, thr=0.0)
per_g = {g: VG[gm[g]] for g in gm if gm[g] in VG}; per_s = {u: VS[sm_all[u]] for u in sm_all if sm_all[u] in VS}
NOTE = ("upvote rate on last week's launches in this unit's top-5 topics vs its rate on other launches, relative to everyone else (1 = no signal); "
        "units fit on data up to 7 days earlier and matched by member overlap; holds = lift >= 1.2 with >= 10 such launches and >= 20 member votes")
cal = {"cut": CUT, "fit_cut": cp, "launches": int(len(tv_m)),
       "backer_group_mix_total_variation (lower better) [mean, 95% launch bootstrap]": {"segments model": bs(tv_m) if len(tv_m) else None, "population mix": bs(tv_p) if len(tv_p) else None,
                                                                                 "model minus population (paired)": bs(tv_m - tv_p) if len(tv_m) else None},
       "votes_for holdout median lift (groups)": float(np.median([v["votes_for_lift_out_of_sample"] for v in VG.values()])) if VG else None,
       "groups where votes_for holds": f"{sum(v['votes_for_holds'] for v in per_g.values())} of {len(per_g)}",
       "subgroups where votes_for holds": f"{sum(v['votes_for_holds'] for v in per_s.values())} of {len(per_s)}"}
log("calibration", json.dumps(cal)[:500])
for g_ in groups:
    g_["calibration"] = {**per_g.get(g_["id"], {"votes_for_holds": False, "note_missing": "no out-of-sample match"}), "note": NOTE}
    for s_ in g_["subgroups"]: s_["calibration"] = per_s.get(s_["id"], {"votes_for_holds": False, "note_missing": "no out-of-sample match"})
def segment_label(cal):
    tv = cal["backer_group_mix_total_variation (lower better) [mean, 95% launch bootstrap]"]
    return (f"Segments: {K} top-level groups of all held Product Hunt users by KIND of user (activity, making, followers, curation, links, comments, "
            f"taste), k chosen in 3-5 by held-out fit, with 3-5 subgroups only where they add held-out fit; every unit >= 20 people; names and 'says' are "
            f"Gemini summaries of measured statistics and members' own past comments (paraphrased). PLAIN CALIBRATION: at the group level these "
            f"segments do NOT predict which launches people vote for better than 'everyone votes like the average' (last week's {cal['launches']} "
            f"launches: group-mix distance {tv['segments model'][0]} vs {tv['population mix'][0]} for the population mix, paired "
            f"{tv['model minus population (paired)']}); 'votes for' held out of sample for {cal['groups where votes_for holds']} groups and "
            f"{cal['subgroups where votes_for holds']} subgroups (votes_for_holds flags). Per launch, expected-voter mix vs base (leave-one-day-out, "
            f"Nov 8-12): groups -0.011 [-0.026, +0.008] (not better), subgroups -0.063 [-0.086, -0.041] (better); the earlier 12-group version "
            f"scored -0.054 [-0.075, -0.032] - the 3-5 grouping (Shreyas, Nov 15) trades that predictive edge for readability.")


pub = {"cut": CUT, "how": __doc__.split("\n    python")[0], "k": K, "k_rule": "top level 3-5 (Shreyas, Nov 15), chosen by held-out log-likelihood per vote; subgroups 3-5 only where they add held-out fit", "k_selection (held-out log-likelihood per vote, fit 7 days earlier)": KSEL, "people_segmented": int(len(lab)), "people_low_signal (1-4 upvotes, assigned by topics)": int(len(G["weak"])),
       "people_not_active_in_window": len(inactive), "groups": groups, "calibration": cal,
       "accuracy_label": segment_label(cal)}
p = os.path.join(OUTD, f"{CUT}.json"); json.dump(pub, open(p, "w"), indent=1, default=float); json.dump(pub, open(os.path.join(OUTD, "latest.json"), "w"), indent=1, default=float)
pp = os.path.join(OUTD, f"members_{CUT}.parquet")
pd.DataFrame({"person_id": list(lab.index) + inactive, "group": list(lab.values) + [-1] * len(inactive), "subgroup": [f"{int(g)}.{int(s)}" for g, s in zip(lab.values, sub.reindex(lab.index).values)] + ["-1"] * len(inactive),
              "low_signal": [p_ in set(G["weak"].index) for p_ in lab.index] + [False] * len(inactive)}).to_parquet(pp)
hist = os.path.join(OUTD, "calibration_history.jsonl"); open(hist, "a").write(json.dumps(cal, default=float) + "\n")
if UP:
    for a, b in ((p, f"results/web/segments/{CUT}.json"), (p, "results/web/segments/latest.json"), (pp, f"tmp/e5/private/segments/{CUT}.parquet"), (pp, "tmp/e5/private/segments/latest.parquet")):
        subprocess.run(["gsutil", "-q", "cp", a, f"{B}/{b}"], check=True)
    old = gcat(f"{B}/results/web/segments/calibration_history.jsonl"); open(os.path.join(OUTD, "_h.jsonl"), "w").write(old + json.dumps(cal, default=float) + "\n")
    subprocess.run(["gsutil", "-q", "cp", os.path.join(OUTD, "_h.jsonl"), f"{B}/results/web/segments/calibration_history.jsonl"], check=True)
print(json.dumps({"groups": [(g["id"], g.get("name"), g["n_people"], len(g["subgroups"])) for g in groups], "calibration": cal}, default=float))
