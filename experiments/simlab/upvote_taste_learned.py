"""Learned taste scorer (the uses S4np recipe) applied to upvoting launches - product-only (orchestrator Nov 11 08:15Z, (1)).
No popularity, no team/maker/hunter/follow features. Per (person p, day d, launch L in the line-up):
  kNN features vs the person's upvote history (launches dated <= d-2 with text): top-1 / top-5 mean / mean cosine for
  bge-small and bge-base embeddings of cleaned launch text, recency-weighted top-5 (half-life 60 d), log history size,
  topic rate (share of history launches sharing a topic with L); who the person is: headline+bio similarity (small, base),
  9 role flags.
Training: LightGBM binary on voting person-days of complete people (labels: upvotes of that day's line-up), honest monthly:
  Oct test days (Oct 20-31) <- train days Sep 18-Oct 18; Nov test days (Nov 1-7) <- train days Oct 1-Oct 30.
Test: the PH agent's 19-day rows (tl_cp_all19_rows.parquet). Shuffled control: each test person-day scored with a random
  other person's history and who-features. Metrics within each person's line-up: Hit@1, Hit@3 on voting person-days,
  within-line-up AUC; day-bootstrap 95% CIs; paired vs the E5 taste logistic (product_only) on the same rows; cold-only
  line-ups (launches whose real makers have no launch dated <= d-2 in the launches table).
    python upvote_taste_learned.py <workdir with v3/ launches/ salt> <rows19.parquet> <e5_ref_rows19.parquet> <person files dir> <out.json>
"""
import glob, hashlib, json, os, re, sys
import numpy as np, pandas as pd

W, ROWS, REF, PF, OUTF = sys.argv[1:6]
rng = np.random.default_rng(0)
SALT = open(os.path.join(W, "salt")).read().strip()
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
real = lambda h: bool(h) and not str(h).startswith("[")

# ---------- launches, cleaned text, embeddings, topics, makers
L = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(W, "launches", "*.parquet")))], ignore_index=True)
L = L.sort_values("updated_at").drop_duplicates("id", keep="last").reset_index(drop=True)
BAD = re.compile(r"[^.!?\n]*(product of the (day|week|month)|golden kitty|thank(s| you) (for|everyone)|upvot|hunt(ed)? us|we('re| are) live|launch day)[^.!?\n]*[.!?]?", re.I)
NUM = re.compile(r"(#\s*\d+|\d[\d,.]*\s*(upvotes?|votes?|comments?|rank))", re.I)
cl = lambda t: NUM.sub(" ", BAD.sub(" ", str(t or "")))
tp = L.topics.map(lambda s: json.loads(s) if isinstance(s, str) and s.startswith("[") else [])
text = (L.name.fillna("") + ". " + L.tagline.fillna("").map(cl) + ". " + L.description.fillna("").map(cl).str[:800] + " Topics: " + tp.map(", ".join)).tolist()
lid = {x: i for i, x in enumerate(L.id)}; Lday = L.day.to_numpy(); TOP = [set(x) for x in tp]
mk = [[m for m in (json.loads(s) if isinstance(s, str) and s.startswith("[") else []) if real(m)] for s in L.makers]
first_launch = {}
for i in np.argsort(Lday):
    for m in mk[i]: first_launch.setdefault(m, Lday[i])
from sentence_transformers import SentenceTransformer
cache = os.path.join(W, "out", "launch_emb_{}.npy")
def emb(name, key, texts):
    f = cache.format(key)
    if os.path.exists(f) and np.load(f).shape[0] == len(texts): return np.load(f)
    e = SentenceTransformer(name, device="cpu").encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False); np.save(f, e); return e
ES = emb("BAAI/bge-small-en-v1.5", "small", text); EB = emb("BAAI/bge-base-en-v1.5", "base", text)
print("launches", len(L), flush=True)

# ---------- people: upvote history (launch-dated), coverage, who
P = pd.read_parquet(os.path.join(W, "v3", "persons.parquet")); comp = set(P[P.complete].person_id)
Tb = pd.read_parquet(os.path.join(W, "v3", "tabs.parquet")); Tb = Tb[Tb.tab == "upvotes"].set_index("person_id")
ev = pd.read_parquet(os.path.join(W, "v3", "events.parquet"), columns=["person_id", "kind", "target_id"])
up = ev[(ev.kind == "upvote") & ev.target_id.isin(lid)].drop(columns="kind"); del ev
up["li"] = up.target_id.map(lid); up["vday"] = Lday[up.li.to_numpy()]
H = {p: (g.vday.to_numpy(), g.li.to_numpy()) for p, g in up.groupby("person_id")}
fetched = Tb.fetched_at.dt.strftime("%Y-%m-%d").to_dict(); short = (Tb["count"] < Tb.header).to_dict()
cover = {p: (H[p][0].min() if short.get(p) else "2000-01-01") for p in H}
ROLES = [r"develop|engineer|programm|coder|software|full.?stack|backend|frontend|devops|\bcto\b", r"design|\bux\b|\bui\b|creative|artist",
         r"market|growth|seo|content|brand|social media", r"founder|\bceo\b|entrepreneur|indie ?hacker|maker|builder|bootstrap",
         r"product manager|\bpm\b|product lead|head of product", r"\bai\b|machine learning|\bml\b|data scien|llm|research",
         r"sales|\bbd\b|business develop|revenue", r"student|universit|college|learning", r"invest|\bvc\b|angel|partner at"]
who = {}
for f in glob.glob(os.path.join(PF, "*.json")):
    try: x = json.load(open(f))
    except Exception: continue
    h = str(x.get("profile", "")).rstrip("/").split("/")[-1].lstrip("@").lower(); a = x.get("about") or {}
    t = " ".join(str(v) for v in (a.get("headline"), a.get("bio")) if v and str(v) != "None")
    if h: who[pid(h)] = t
pw = sorted(set(who) & (comp | set(H))); wix = {p: i for i, p in enumerate(pw)}
WS = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").encode([who[p] or "-" for p in pw], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
WB = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cpu").encode([who[p] or "-" for p in pw], batch_size=128, normalize_embeddings=True, show_progress_bar=False)
RL = {p: [float(bool(re.search(r, who[p], re.I))) for r in ROLES] for p in pw}
print("people with history", len(H), "with who", len(pw), flush=True)
_dc = {}
def dm(d, k):
    if (d, k) not in _dc: _dc[(d, k)] = str((pd.Timestamp(d) + pd.Timedelta(days=k)).date())
    return _dc[(d, k)]

FEATS = ["s_top1", "s_top5", "s_mean", "b_top1", "b_top5", "b_mean", "b_top5_rec", "n_hist", "topic_rate", "who_s", "who_b", "who_len"] + [f"role{k}" for k in range(9)]


def feats(p, d, cand, hp=None, wp=None):
    """features for person p (history of hp, who of wp; defaults p) on day d over candidate launch indices."""
    hp = hp or p; wp = wp or p
    vd, vi = H.get(hp, (np.array([], object), np.array([], int)))
    m = vd <= dm(d, -2); hist = vi[m]; age = (pd.Timestamp(d) - pd.to_datetime(vd[m])).days.to_numpy() if m.any() else np.array([])
    n = len(cand); F = np.full((n, len(FEATS)), np.nan, np.float32)
    if len(hist):
        for j, E in ((0, ES), (3, EB)):
            S = E[cand] @ E[hist].T; Ss = np.sort(S, 1); k = min(5, S.shape[1])
            F[:, j], F[:, j + 1], F[:, j + 2] = Ss[:, -1], Ss[:, -k:].mean(1), S.mean(1)
            if j == 3:
                w = 0.5 ** (age / 60.0); top = np.argsort(-S, 1)[:, :k]
                F[:, 6] = (np.take_along_axis(S, top, 1) * w[top]).sum(1) / (w[top].sum(1) + 1e-9)
        F[:, 7] = np.log1p(len(hist))
        ht = [TOP[i] for i in hist]; nt = sum(1 for t in ht if t) or 1
        F[:, 8] = [sum(1 for t in ht if t & TOP[c]) / nt if TOP[c] else np.nan for c in cand]
    else:
        F[:, 7] = 0
    if wp in wix:
        F[:, 9] = ES[cand] @ WS[wix[wp]]; F[:, 10] = EB[cand] @ WB[wix[wp]]; F[:, 11] = len(who[wp]); F[:, 12:21] = RL[wp]
    return F


# ---------- training rows (voting person-days of complete people, label-filtered)
def train_rows(d0, d1, per_day=1500):
    X, Y = [], []
    days = sorted({x for x in Lday if d0 <= x <= d1})
    people = [p for p in comp if p in H]
    for d in days:
        cand = np.where(Lday == d)[0]
        if len(cand) < 5: continue
        voters = [p for p in people if fetched.get(p, "0") >= dm(d, 2) and cover.get(p, "9") <= d and (H[p][0] == d).any()]
        for p in rng.permutation(voters)[:per_day]:
            y = np.isin(cand, H[p][1][H[p][0] == d]).astype(int)
            if y.sum() == 0 or y.sum() == len(y): continue
            X.append(feats(p, d, cand)); Y.append(y)
    return np.concatenate(X), np.concatenate(Y)


import lightgbm as lgb
R = pd.read_parquet(ROWS); R["li"] = R.launch_id.map(lid); R = R[R.li.notna()].copy(); R["li"] = R.li.astype(int)
REFD = pd.read_parquet(REF)[["d", "person_id", "launch_id", "product_only"]]
R = R.merge(REFD, on=["d", "person_id", "launch_id"], how="left")
R["cold"] = [not any(first_launch.get(m, "9") <= dm(d, -2) for m in mk[i]) for i, d in zip(R.li, R.d)]
plist = R.person_id.unique()
FOLDS = [("oct", "2026-09-18", "2026-10-18", "2026-10-20", "2026-10-31"), ("nov", "2026-10-01", "2026-10-30", "2026-11-01", "2026-11-30")]
R["learned"] = np.nan; R["learned_sh"] = np.nan; meta = {}
for name, a0, a1, t0, t1 in FOLDS:
    Xtr, Ytr = train_rows(a0, a1)
    m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=200, subsample=0.8, subsample_freq=1,
                           colsample_bytree=0.8, verbose=-1).fit(Xtr, Ytr)
    meta[name] = {"train_days": [a0, a1], "train_rows": int(len(Ytr)), "train_pos": int(Ytr.sum())}
    sub = R[(R.d >= t0) & (R.d <= t1)]
    for (p, d), x in sub.groupby(["person_id", "d"]):
        cand = x.li.to_numpy(); o = plist[rng.integers(len(plist))]
        R.loc[x.index, "learned"] = m.predict_proba(feats(p, d, cand))[:, 1]
        R.loc[x.index, "learned_sh"] = m.predict_proba(feats(p, d, cand, hp=o, wp=o))[:, 1]
    print(name, meta[name], flush=True)
R["rand"] = rng.random(len(R))


def per_day(D, s):
    D = D[D.groupby(["d", "person_id"]).y.transform("sum") > 0].copy()
    v = D[s].to_numpy(float) + rng.random(len(D)) * 1e-9; D["v"] = v
    D["r"] = D.groupby(["d", "person_id"]).v.rank(ascending=False, method="first")
    D["n"] = D.groupby(["d", "person_id"]).y.transform("size"); D["k"] = D.groupby(["d", "person_id"]).y.transform("sum")
    h = D.groupby(["d", "person_id"]).apply(lambda g: pd.Series({"h1": float(g.y[g.r <= 1].sum() > 0), "h3": float(g.y[g.r <= 3].sum() > 0),
        "auc": (lambda pos, neg: np.mean(pos[:, None] > neg[None, :]) if len(neg) else np.nan)(g.v[g.y == 1].to_numpy(), g.v[g.y == 0].to_numpy())}))
    return h.groupby(level=0).mean()


def boot(v, B=4000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4), int(len(v))]


res = {"folds": meta, "rows": int(len(R)), "days": int(R.d.nunique()), "cold_share_of_rows": round(float(R.cold.mean()), 3), "sets": {}}
for setname, D in (("full line-up", R), ("cold-only line-up", R[R.cold])):
    out = {}; base = per_day(D, "product_only")
    for s in ("rand", "product_only", "learned", "learned_sh"):
        pdd = per_day(D, s); out[s] = {m: boot(pdd[m]) for m in ("h1", "h3", "auc")}
        if s in ("learned", "learned_sh"): out[s]["minus E5 logistic (paired by day)"] = {m: boot((pdd[m] - base[m]).dropna()) for m in ("h1", "h3", "auc")}
    sh = per_day(D, "learned_sh"); le = per_day(D, "learned")
    out["learned personal (learned - shuffled)"] = {m: boot((le[m] - sh[m]).dropna()) for m in ("h1", "h3", "auc")}
    res["sets"][setname] = out
json.dump(res, open(OUTF, "w"), indent=1); print(json.dumps(res, indent=1))
