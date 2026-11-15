"""Backer prediction, three arms side by side under STRICT rules (orchestrator 22:34Z Nov 14, E5's one experiment).
For target day D, everything comes from held people's reads fetched before 00:00 PT of D (H_D):
  CF-only : logistic on ln(1+n30), ln(1+n90), ln(1+days since last upvote), cf; trained on the 30 days before D
            cf = cosine between the person's SVD factor (k=32, fit on H_D upvotes on launches dated before D) and the launch's audience centroid
            (earlier backers of the hunter / first maker; if < 5, people who upvoted same-topic launches in the 30 days before D)
  A7      : logistic on n30, n90, last, topic taste, is-hunter, backed-before (dated), trained on the 7 days before D
  raw     : the most active held people (upvotes on launches of the 30 days before D, from H_D), built at scoring time
No follow lists in either fitted arm (no undated follows). Training labels for day t < D: upvotes on t visible in H_D.
Frozen lists (top 2000 per launch per arm, salted person ids, PRIVATE): gs://.../tmp/e5/private/backer_arms/<D>.parquet
    python backer_arms.py <store dir> <scratchpad> <day> [<day> ...] [--no-upload]"""
import json, os, subprocess, sys, tempfile, time
import numpy as np, pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from pipeline import warehouse  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]; ST, SP, TDAYS = args[0], args[1], args[2:]; UP = "--no-upload" not in sys.argv
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
t0 = time.time()
# launches table + the target days' 00:05 line-ups (ranks unknown for today: rank 0 placeholder, never used as a label)
tmp = tempfile.mkdtemp(); ld = os.path.join(tmp, "launches"); os.makedirs(ld)
WA = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); WA["id"] = WA.id.astype(str)
LINE = {}
for D in TDAYS:
    try: LINE[D] = json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json"))
    except Exception: LINE[D] = []
add = []
for D, line in LINE.items():
    for p in line:
        if str(p["id"]) in set(WA.id): continue
        add.append({"id": str(p["id"]), "slug": p.get("slug"), "day": D, "topics": json.dumps([e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or [])]),
                    "poster": (p.get("user") or {}).get("username"), "makers": json.dumps([m.get("username") for m in (p.get("makers") or []) if m.get("username")]),
                    "daily_rank": 0.0, "votes": np.nan, "updated_at": "9999"})
WA2 = pd.concat([WA, pd.DataFrame(add)], ignore_index=True) if add else WA
WA2[["id", "slug", "day", "topics", "poster", "makers", "daily_rank", "votes", "updated_at"]].assign(daily_rank=lambda x: x.daily_rank.fillna(0.0)).astype(
    {"daily_rank": float, "updated_at": str}).to_parquet(os.path.join(ld, "l.parquet"))
pd.DataFrame({"id": [str(p["id"]) for D in TDAYS for p in LINE[D]], "day": [D for D in TDAYS for p in LINE[D]]}).to_parquet(os.path.join(tmp, "clean.parquet"))
os.environ["EDGES"] = "hunter_maker"; argv0 = sys.argv
sys.argv = ["voter_harness.py", ST, os.path.join(tmp, "clean.parquet"), ld, os.path.join(SP, "early"), os.path.join(tmp, "o")]
VH = open(os.path.join(HERE, "voter_harness.py")).read(); i0 = VH.index("DAYS = ["); i1 = VH.index("\n", i0)
VH = VH[:i0] + "DAYS = " + json.dumps(TDAYS) + VH[i1:]
g = {"__name__": "vh", "__file__": "voter_harness.py"}; exec(VH[:VH.index("FOLL = {}")], g); sys.argv = argv0
U, L, feats, pair_X, LT, ltop, lhun, lmak, start = (g[k] for k in ("U", "L", "feats", "pair_X", "LT", "ltop", "lhun", "lmak", "start"))
lday = dict(zip(L.id, L.day))
by_team = {}
for i in L.id:
    for t in (lhun.get(i), lmak.get(i)):
        if t: by_team.setdefault(t, set()).add(i)
lineup_of = lambda d: [str(p["id"]) for p in LINE[d]] if d in LINE and LINE[d] else L[L.day == d].id.tolist()
print("setup", round(time.time() - t0), flush=True)


def day_cols(t, H, UF, pi):
    act, tv, _ = feats(t, H); lu = lineup_of(t) if t in LINE else L[L.day == t].id.tolist(); Ht = H[H.lday < t]
    if not len(act) or not lu: return None
    base = pair_X(act, tv, lu, {})   # n30, n90, last, taste, (follows = 0: none passed), is_hunter
    rows = np.array([pi.get(p, -1) for p in act.index]); have = rows >= 0; d0 = pd.Timestamp(t); out = []
    tot_up = Ht.groupby("person_id").size().reindex(act.index).fillna(0).values   # all upvotes before t (for bk_share)
    for i, X in zip(lu, base):
        ls = set().union(*[by_team.get(x, set()) for x in (lhun.get(i), lmak.get(i)) if x]) - {i}
        bk = set(Ht[Ht.target_id.isin(ls)].person_id) if ls else set()
        aud = [pi[p] for p in bk if p in pi]
        if len(aud) < 5:
            tops = set(ltop.get(i, [])); d30 = (d0 - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            tl = set(LT[LT.j.isin(tops)].target_id) & set(Ht[Ht.lday >= d30].target_id) if tops else set()
            aud = [pi[p] for p in Ht[Ht.target_id.isin(tl)].person_id.unique() if p in pi] if tl else []
        cf = np.zeros(len(act))
        if aud:
            c = UF[aud].mean(0); c /= max(np.linalg.norm(c), 1e-9); cf[have] = UF[rows[have]] @ c
        # backing intensity (arm 5, pre-registered 23:16Z): only upvotes on the team's launches dated before t, from reads before the cut
        bkr = np.zeros(len(act)); bkn = np.zeros(len(act)); bkd = np.full(len(act), np.log1p(365.0)); bks = np.zeros(len(act))
        if ls:
            tb = Ht[Ht.target_id.isin(ls)]
            if len(tb):
                recent = max(ls, key=lambda x: lday.get(x, ""))
                cnt = tb.groupby("person_id").target_id.nunique(); last = tb.groupby("person_id").lday.max()
                ix_ = pd.Index(act.index)
                bkr = ix_.isin(set(tb[tb.target_id == recent].person_id)).astype(float)
                bkn = np.log1p(cnt.reindex(ix_).fillna(0).values)
                dd = (d0 - pd.to_datetime(last.reindex(ix_))).dt.days
                bkd = np.where(dd.notna(), np.log1p(dd.fillna(365).clip(lower=0)), np.log1p(365.0))
                bks = np.where(tot_up > 0, tb.groupby("person_id").size().reindex(ix_).fillna(0).values / np.maximum(tot_up, 1), 0.0)
        out.append((i, np.column_stack([X, act.index.isin(bk).astype(float), cf, bkr, bkn, bkd, bks])))
    return act, out
COLS = ["n30", "n90", "last", "taste", "fol", "hun", "back", "cf", "bk_recent", "bk_n", "bk_days", "bk_share"]; ci = {c: k for k, c in enumerate(COLS)}
ARMS = {"CF-only": (30, ["n30", "n90", "last", "cf"]), "A7": (7, ["n30", "n90", "last", "taste", "hun", "back"]),
        "CF+back": (30, ["n30", "n90", "last", "cf", "back"]),
        "CF+intensity": (30, ["n30", "n90", "last", "cf", "bk_recent", "bk_n", "bk_days", "bk_share"])}   # arm 5, pre-registered a01f8b96   # 4th arm (miss anatomy 22:54Z: 43% of CF-only misses had backed this team before)
if os.environ.get("ARMS_ONLY"): ARMS = {k: v for k, v in ARMS.items() if k in os.environ["ARMS_ONLY"].split(",")}
if os.environ.get("RING") == "1": ARMS = {k + "/ring": v for k, v in ARMS.items()}
rng = np.random.default_rng(0)
for D in TDAYS:
    cut = start(D); H = U[U.fetched_at < cut]
    n_ring = None
    if os.environ.get("RING") == "1":   # remove likely-discounted (ring) people's upvotes from CF training (dated flag: reads before cut, launches before D-1)
        import ringlib
        Wv = WA.assign(votes=pd.to_numeric(WA.votes, errors="coerce"), day=WA.day.astype(str).str[:10])[["id", "day", "votes"]]
        RF, n_oc_l = ringlib.dated_flags(H[["person_id", "target_id", "lday"]], Wv, (pd.Timestamp(D) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        H = H[~H.person_id.isin(RF)]; n_ring = len(RF)
    H0 = H[H.lday < D]; pi = {p: k for k, p in enumerate(H0.person_id.unique())}; li = {l: k for k, l in enumerate(H0.target_id.unique())}
    M = csr_matrix((np.ones(len(H0)), (H0.person_id.map(pi).values, H0.target_id.map(li).values)), shape=(len(pi), len(li)))
    uu, ss, _ = svds(M.astype(float), k=32); UF = uu * ss; UF /= np.maximum(np.linalg.norm(UF, axis=1, keepdims=True), 1e-9)
    tr_days = sorted(d for d in L.day.unique() if d < D)[-30:]; TRAIN = {}
    for t in tr_days:
        r = day_cols(t, H, UF, pi)
        if r is None: continue
        act, out = r; voted = H[H.lday == t].groupby("target_id").person_id.agg(set).to_dict(); Xs, ys = [], []
        for i, X in out:
            y = act.index.isin(voted.get(i, set())).astype(int); m = (y == 1) | (rng.random(len(y)) < 0.1); Xs.append(X[m]); ys.append(y[m])
        if Xs: TRAIN[t] = (np.vstack(Xs), np.concatenate(ys))
    test = day_cols(D, H, UF, pi)
    if test is None: print(json.dumps({"day": D, "status": "no test features"})); continue
    act, out = test; frames = []
    for arm, (win, cols) in ARMS.items():
        tr = [t for t in sorted(TRAIN)][-win:]
        X = np.vstack([TRAIN[t][0] for t in tr])[:, [ci[c] for c in cols]]; y = np.concatenate([TRAIN[t][1] for t in tr])
        if y.sum() < 20: print(json.dumps({"day": D, "arm": arm, "status": "too few training upvotes", "n_pos": int(y.sum())})); continue
        m = LogisticRegression(max_iter=400).fit(X, y, sample_weight=np.where(y == 1, 1.0, 10.0))
        for i, Xi in out:
            p = m.predict_proba(Xi[:, [ci[c] for c in cols]])[:, 1]; o = np.argsort(-p)[:2000]
            frames.append(pd.DataFrame({"launch_id": i, "arm": arm, "person_id": act.index[o], "p": p[o], "rank": np.arange(1, len(o) + 1)}))
    if not frames: continue
    FR = pd.concat(frames, ignore_index=True).assign(day=D, frozen_at=pd.Timestamp.now(tz="UTC").isoformat(), n_active=len(act), svd_rows=len(pi),
                                                       svd_max_lday=str(H0.lday.max()), reads_before=str(cut), train_days=len(TRAIN))
    fp = os.path.join(SP, "bp", f"backer_arms_{D}.parquet"); os.makedirs(os.path.dirname(fp), exist_ok=True)
    if os.environ.get("ARMS_ONLY") and os.path.exists(fp):
        old_ = pd.read_parquet(fp); FR = pd.concat([old_[~old_.arm.isin(FR.arm.unique())], FR], ignore_index=True)
    FR.to_parquet(fp)
    if UP: subprocess.run(["gsutil", "-q", "cp", fp, f"{B}/tmp/e5/private/backer_arms/{D}.parquet"], check=True)
    print(json.dumps({"day": D, "launches": int(FR.launch_id.nunique()), "arms": sorted(FR.arm.unique()), "n_active": len(act), "train_days": len(TRAIN),
                      "svd_max_lday": str(H0.lday.max()), "reads_before": str(cut), "ring_flagged": n_ring, "sec": round(time.time() - t0)}), flush=True)
