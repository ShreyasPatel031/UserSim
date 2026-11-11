"""Beat the PH agent's comment ridge (claude/ph-ops-agent 55b84206, experiments/ph_predict/comment_forecast.py) on the same days
and cuts (orchestrator 20:55Z Nov 11). Step 1 reproduces its rows/ridge by importing its build()/forward()/score_days() (only the
warehouse query is replaced by the same launches table read from tables/launches). Step 2 adds blocks computed from the same
thread dumps, using only comments with created_at <= T (T = 00:00 PT + h):
  text  (a)  non-team comments: mean bge-small embedding (PCA-8, PCA fitted on comments of the first month only = training-only),
             mean log length, share with "?", congratulation share, feature-request share (regex rules).
  acct  (b)  commenter user ids (monotone in sign-up time): mean log id rank, share of "new" accounts (id above the highest id
             seen commenting before t0 - 7 d), first-ever comment in the dump, in the E5 complete pool, pool prior upvotes
             (launch-day dated <= d-2).
  maker (c)  team replies by T, share of non-team threads with a team reply by T, median team reply latency (h).
  shape (d)  hours to first non-team comment (T if none), non-team comments in the last hour before T, last-hour share.
Kept out (read at fetch time): comment votes, isSticky, isProminent / isAccountVerified / badges, follower counts. The PH ridge
itself uses u_ver / u_prom (fetch-time flags); both the PH ridge as published and its no-flags variant are reported as references.
Models: the PH ridge (alpha 10, log1p counts, standardised, target -log rank, month-forward), with blocks appended.
Metrics: daily top 3/5/10 overlap and within-day Spearman (x100), paired by day vs the PH ridge, 2000 day-bootstrap draws.
    python comment_blocks.py <workdir> <ph_predict dir> <store v3 dir> <salt file> <launches dir>
"""
import glob, gzip, hashlib, html, json, os, re, sys, types
import numpy as np, pandas as pd

W, PHD, V3, SALTF, LDIR = sys.argv[1:6]
os.environ["CF_WORK"] = W
sys.path.insert(0, PHD); sys.path.insert(0, os.path.dirname(PHD))
Lw = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
Lw = Lw[Lw.daily_rank.notna()][["id", "slug", "day", "daily_rank", "makers", "poster"]].copy(); Lw["id"] = Lw.id.astype(str)
wh = types.ModuleType("pipeline.warehouse"); wh.query = lambda *a, **k: Lw.copy()
pk = types.ModuleType("pipeline"); pk.warehouse = wh; sys.modules["pipeline"] = pk; sys.modules["pipeline.warehouse"] = wh
import comment_forecast as CF
rng = np.random.default_rng(0)
CUTS = [int(c) for c in os.environ.get("CUTS", "4,2,1").split(",")]

rows_f = os.path.join(W, "cf_rows.parquet")
if os.path.exists(rows_f):
    X0 = pd.read_parquet(rows_f)
else:
    X0, st = CF.build(); X0.to_parquet(rows_f); print("built", st, flush=True)

# ---------- own parse of the same dumps (text, ids, parents)
rows = []
for f in ("page1", "page1b", "page1c", "page2"):
    for line in gzip.open(os.path.join(W, f + ".jsonl.gz")):
        x = json.loads(line)
        try: post = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not post or not post.get("slug"): continue
        def walk(n, parent, depth):
            u = n.get("user") or {}
            rows.append((post["slug"], n.get("id"), parent, depth, (u.get("username") or "").lower(), u.get("id"), n.get("createdAt"), n.get("bodyHtml") or ""))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"], n.get("id"), depth + 1)
        for e in ((post.get("threads") or {}).get("edges") or []): walk(e["node"], None, 0)
K = pd.DataFrame(rows, columns=["slug", "cid", "parent", "depth", "user", "uid", "created", "body"]).drop_duplicates("cid")
K["ts"] = pd.to_datetime(K.created, utc=True, errors="coerce"); K = K.dropna(subset=["ts"])
K["uid"] = pd.to_numeric(K.uid, errors="coerce")
L = Lw.copy()
L["team"] = [{u.lower() for u in (set(json.loads(m) if isinstance(m, str) and m.startswith("[") else []) | ({p} if p else set())) if u} for m, p in zip(L.makers, L.poster)]
L["t0"] = [pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC") for d in L.day]
K = K.merge(L[["slug", "id", "day", "t0", "team"]], on="slug")
K["is_team"] = [u in t for u, t in zip(K.user, K.team)]
K["h"] = (K.ts - K.t0).dt.total_seconds() / 3600
K["text"] = K.body.map(lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip())
print("parsed comments", len(K), flush=True)

# text features (rules + embeddings for comments within +4h)
CONG = re.compile(r"congrat|well done|great (job|work|launch)|good luck|awesome|amazing|love (it|this)|kudos|looks (great|awesome|amazing)|nice (work|job)|cool", re.I)
FREQ = re.compile(r"would (be|love)|could you|can you add|any plans|plan to|roadmap|feature request|support for|integrat|wish|will (it|you) support|do you (plan|support)", re.I)
K["q"] = K.text.str.contains(r"\?").astype(float); K["cong"] = K.text.str.contains(CONG).astype(float)
K["freq"] = K.text.str.contains(FREQ).astype(float); K["llen"] = np.log1p(K.text.str.len())
E4 = K[(K.h <= max(CUTS)) & ~K.is_team].copy()
ef = os.path.join(W, "emb4.npy")
if os.path.exists(ef) and np.load(ef).shape[0] == len(E4):
    EM = np.load(ef)
else:
    from sentence_transformers import SentenceTransformer
    EM = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").encode(E4.text.str[:500].tolist(), batch_size=128, normalize_embeddings=True, show_progress_bar=False)
    np.save(ef, EM)
from sklearn.decomposition import PCA
m0 = sorted(X0.day.str[:7].unique())[0]
pca = PCA(8, random_state=0).fit(EM[(E4.day.str[:7] == m0).to_numpy()])
PC = pca.transform(EM); emb_cols = [f"e{i}" for i in range(8)]
E4[emb_cols] = PC
cpos = {c: i for i, c in enumerate(E4.cid)}
print("embedded", EM.shape, flush=True)

# account features: new-account frontier, first-ever comment in the dump, pool membership/activity
first_ts = K.groupby("user").ts.min()
Ks = K.sort_values("ts"); cummax = Ks.uid.fillna(0).cummax().to_numpy(); tsv = Ks.ts.dt.tz_convert(None).to_numpy()
def frontier(t):
    i = np.searchsorted(tsv, np.datetime64(t.tz_convert(None)), side="left") - 1
    return cummax[i] if i >= 0 else np.inf
SALT = open(SALTF).read().strip()
pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + h).encode()).hexdigest()[:16]
comp = set(pd.read_parquet(os.path.join(V3, "persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id", "extra"]).query("kind == 'upvote'")
Lday = dict(zip(Lw.id, Lw.day)); ev["vday"] = ev.target_id.astype(str).map(Lday)
ev["vday"] = ev.vday.fillna(ev.extra.str.extract(r'"launched_at": "(\d{4}-\d\d-\d\d)')[0]); ev = ev.dropna(subset=["vday"])
upd = {p: np.sort(g.vday.to_numpy()) for p, g in ev.groupby("person_id")}; del ev
uidr = K.drop_duplicates("user").set_index("user").uid

feat_rows = []
for h in CUTS:
    for lid, g in K[K.h <= h].groupby("id"):
        t0 = g.t0.iloc[0]; d = g.day.iloc[0]; T = t0 + pd.Timedelta(hours=h)
        out = g[~g.is_team]; tm = g[g.is_team]
        r = {"cut": h, "id": lid}
        r["t_cong"] = out.cong.mean() if len(out) else 0; r["t_q"] = out.q.mean() if len(out) else 0
        r["t_freq"] = out.freq.mean() if len(out) else 0; r["t_len"] = out.llen.mean() if len(out) else 0
        if len(out):
            ix = [cpos[c] for c in out.cid if c in cpos]; mv = PC[ix].mean(0) if ix else np.zeros(8)
            for j, c in enumerate(emb_cols): r[c] = float(mv[j])
        else:
            for c in emb_cols: r[c] = 0
        us = out.drop_duplicates("user"); fr = frontier(t0 - pd.Timedelta(days=7))
        r["a_new"] = float((us.uid > fr).sum()); r["a_lid"] = float(np.log(us.uid.dropna()).mean()) if us.uid.notna().any() else 0
        r["a_first"] = float(sum(first_ts.get(u, T) >= t0 for u in us.user))
        ps = [pid(u) for u in us.user if u]; inp = [p for p in ps if p in comp]
        d2 = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        r["a_pool"] = float(len(inp)); r["a_poolup"] = float(sum(np.log1p(np.searchsorted(upd.get(p, np.array([])), d2, side="right")) for p in inp))
        rep = tm[tm.depth > 0]; par = dict(zip(g.cid, g.ts)); outc = set(out.cid)
        rep_out = rep[rep.parent.isin(outc)]
        lat = [(ts - par[p]).total_seconds() / 3600 for p, ts in zip(rep_out.parent, rep_out.ts) if p in par]
        r["m_rep"] = float(len(rep)); r["m_share"] = len(set(rep_out.parent)) / max(1, (out.depth == 0).sum())
        r["m_lat"] = float(np.median(lat)) if lat else float(h)
        r["s_first"] = float(out.h.min()) if len(out) else float(h); r["s_first"] = max(0.0, r["s_first"])
        r["s_last1"] = float((out.h > h - 1).sum()); r["s_lastsh"] = r["s_last1"] / max(1, len(out))
        feat_rows.append(r)
FB = pd.DataFrame(feat_rows)
BLOCKS = {"text": ["t_cong", "t_q", "t_freq", "t_len"] + emb_cols, "acct": ["a_new", "a_lid", "a_first", "a_pool", "a_poolup"],
          "maker": ["m_rep", "m_share", "m_lat"], "shape": ["s_first", "s_last1", "s_lastsh"]}
LOG1P = ["a_new", "a_first", "a_pool", "m_rep", "s_last1"]


def run(Xh, feats):
    Y = Xh.copy()
    for c in LOG1P:
        if c in Y: Y[c] = np.log1p(Y[c])
    return CF.forward(Y, "ridge", feats)


def bootd(D, B_=2000):
    v = D.values; n = len(v); bs = np.array([v[rng.integers(0, n, n)].mean(0) for _ in range(B_)])
    return {k: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)]
            for j, k in enumerate(D.columns)}


res = {"design": __doc__.split("\n    python")[0], "cuts": {}}
NOFLAG = [f for f in CF.FEATS if f not in ("u_ver", "u_prom")]
for h in CUTS:
    Xh = X0[X0.cut == h].merge(FB[FB.cut == h].drop(columns="cut"), on="id", how="left")
    for c in sum(BLOCKS.values(), []): Xh[c] = Xh[c].fillna(float(h) if c in ("s_first", "m_lat") else 0.0)
    variants = {"PH ridge (as published)": CF.FEATS, "PH ridge, no fetch-time flags": NOFLAG}
    allb = sum(BLOCKS.values(), [])
    variants["noflags + all blocks"] = NOFLAG + allb
    for b, cols in BLOCKS.items():
        variants[f"noflags + {b}"] = NOFLAG + cols
        variants[f"noflags + all blocks - {b}"] = NOFLAG + [c for c in allb if c not in cols]
    P = {k: run(Xh, v) for k, v in variants.items()}
    days = sorted(P["PH ridge (as published)"].day.unique())
    S = {k: CF.score_days(p, "pred").loc[days] for k, p in P.items()}
    S["LM only"] = CF.score_days(Xh[Xh.day.isin(days)], "lm").loc[days]
    ref = S["PH ridge (as published)"]
    r = {"days": len(days)}
    for k, D in S.items():
        r[k] = bootd(D)
        if k != "PH ridge (as published)": r[k + " - PH ridge"] = bootd(D - ref)
    res["cuts"][f"+{h}h"] = r
    print(h, json.dumps({k: r[k] for k in ("PH ridge (as published)", "noflags + all blocks - PH ridge")}), flush=True)
    json.dump(res, open(os.path.join(W, "comment_blocks.json"), "w"), indent=1)
print("done", flush=True)
