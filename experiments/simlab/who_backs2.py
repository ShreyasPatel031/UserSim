"""Raise the simulation-quality number of the who-backs-it model (orchestrator 18:00Z Nov 13). Same 15 days as who_backs.py
(Oct 25 - Nov 11, clean_v3_nosite days), lenient as-of-date history (upvotes on launches dated before the day; never target-day votes).
Pair model P(person upvotes launch), logistic, negatives subsampled 10% and re-weighted. Feature columns:
  base : ln(1+n30), ln(1+n90), ln(1+days since last upvote), topic taste            (voter_harness.py feats/pair_X)
  fol  : follows the hunter or first maker (UNDATED follow lists)
  hun  : is the hunter
  back : backed before = upvoted an earlier launch whose hunter / first maker is in this team (DATED)
  wk   : weekday base rate = share of the 12 previous same weekdays with >= 1 upvote
  cf   : co-upvote neighbour score = cosine between the person's SVD factor (k=32, upvotes on launches dated before Oct 25 only, so
         no test-period data) and the launch's audience centroid (team's earlier backers; if < 5, people who upvoted same-topic
         launches in the 30 days before the day)
Arms: A7 = base+hun+back trained on 7 prior days (the who_backs.py set without follows); a) A30 / A60 = same on 30 / 60 days;
b) +cf (feature) and CF-only (base activity + cf); c) +wk; d) +fol (undated) vs back-only; FULL = everything on the best window.
Metrics per arm: voter recall at N and 2N (N = round expected backers; share of the launch's held voters among the N / 2N most likely
people; mean over launches with >= 1 held voter, launch bootstrap); calibration (median E / displayed votes, Spearman E vs votes);
top 3/5/10 vs clean_v3_nosite and vs the PLACEBO (held team count), paired day bootstrap. Counts only.
    python who_backs2.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__)); os.environ["EDGES"] = "hunter_maker"
VH = open(os.path.join(HERE, "voter_harness.py")).read()
ALLD = '["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]'
ALLD = os.environ.get("DAYS_OVERRIDE", ALLD)
i0 = VH.index("DAYS = ["); i1 = VH.index("\n", i0); VH = VH[:i0] + "DAYS = " + ALLD + VH[i1:]
exec(VH[:VH.index("FOLL = {}")])
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds
from scipy.stats import spearmanr
t0 = time.time(); OUTD = OUT
follows = FO.groupby("target_id").person_id.agg(set).to_dict()
by_team = {}
for i in L.id:
    for t in (lhun.get(i), lmak.get(i)):
        if t: by_team.setdefault(t, set()).add(i)
team_n = {i: sum(1 for t in {lhun.get(i), lmak.get(i)} - {None} if t in COV) for i in L.id}
# CF factors from upvotes on launches dated before the first test day
H0 = U[U.lday < DAYS[0]]; pi = {p: k for k, p in enumerate(H0.person_id.unique())}; li = {l: k for k, l in enumerate(H0.target_id.unique())}
M = csr_matrix((np.ones(len(H0)), (H0.person_id.map(pi).values, H0.target_id.map(li).values)), shape=(len(pi), len(li)))
uu, ss, _ = svds(M.astype(float), k=32); UF = uu * ss; UF /= np.maximum(np.linalg.norm(UF, axis=1, keepdims=True), 1e-9); print("svd", UF.shape, round(time.time() - t0), flush=True)
lday_s = U.groupby("person_id").lday.apply(lambda s: set(s))
def day_cols(t):
    """feature blocks for every active person x every launch of day t (history = launches dated before t)."""
    act, tv, _ = feats(t, U); lu = L[L.day == t].id.tolist(); Ht = U[U.lday < t]
    if not len(act): return None
    base = pair_X(act, tv, lu, follows)   # n30, n90, last, taste, follows, is_hunter
    d0 = pd.Timestamp(t); wds = [(d0 - pd.Timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(1, 13)]
    wk = np.array([sum(w in lday_s.get(p, ()) for w in wds) / 12 for p in act.index])
    rows = np.array([pi.get(p, -1) for p in act.index]); have = rows >= 0
    out = []
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
        out.append((i, np.column_stack([X, act.index.isin(bk).astype(float), wk, cf])))
    return act, out
COLS = ["n30", "n90", "last", "taste", "fol", "hun", "back", "wk", "cf"]; ci = {c: k for k, c in enumerate(COLS)}
need = sorted(d for d in L.day.unique() if d < DAYS[-1]); first = DAYS[0]; prior = [d for d in need if d < first][-60:]
TRAIN = {}
for t in prior + [d for d in need if d >= first]:
    r = day_cols(t)
    if r is None: continue
    act, out = r; voted = U[U.lday == t].groupby("target_id").person_id.agg(set).to_dict(); Xs, ys = [], []
    for i, X in out:
        y = act.index.isin(voted.get(i, set())).astype(int); m = (y == 1) | (rng.random(len(y)) < 0.1); Xs.append(X[m]); ys.append(y[m])
    if Xs: TRAIN[t] = (np.vstack(Xs), np.concatenate(ys))
print("train days cached", len(TRAIN), round(time.time() - t0), flush=True)
TEST = {d: day_cols(d) for d in DAYS}; print("test cached", round(time.time() - t0), flush=True)
ARMS = {"A7": (7, ["n30", "n90", "last", "taste", "hun", "back"]), "A30": (30, ["n30", "n90", "last", "taste", "hun", "back"]),
        "A60": (60, ["n30", "n90", "last", "taste", "hun", "back"]), "A30+cf": (30, ["n30", "n90", "last", "taste", "hun", "back", "cf"]),
        "CF-only": (30, ["n30", "n90", "last", "cf"]), "A30+wk": (30, ["n30", "n90", "last", "taste", "hun", "back", "wk"]),
        "A30+fol (undated)": (30, ["n30", "n90", "last", "taste", "hun", "back", "fol"]), "A30 back-only team tie": (30, ["n30", "n90", "last", "taste", "back"]),
        "FULL": (30, COLS)}
voters = U[U.lday.isin(DAYS)].groupby("target_id").person_id.agg(set).to_dict()
votes = dict(zip(L.id, pd.to_numeric(L.votes, errors="coerce")))
def run_arm(win, cols):
    E, rec = {}, []
    for d in DAYS:
        tr = [t for t in sorted(TRAIN) if t < d][-win:]
        X = np.vstack([TRAIN[t][0] for t in tr])[:, [ci[c] for c in cols]]; y = np.concatenate([TRAIN[t][1] for t in tr])
        m = LogisticRegression(max_iter=400).fit(X, y, sample_weight=np.where(y == 1, 1.0, 10.0))
        act, out = TEST[d]
        for i, Xi in out:
            if i not in set(C[C.day == d].id): continue
            p = m.predict_proba(Xi[:, [ci[c] for c in cols]])[:, 1]; E[i] = float(p.sum()); v = voters.get(i, set())
            if v:
                o = np.argsort(-p); N = max(1, int(round(E[i]))); r1 = len(v & set(act.index[o[:N]])) / len(v); r2 = len(v & set(act.index[o[:2 * N]])) / len(v)
                rec.append((r1, r2))
    return E, np.array(rec)
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def pdiff(a, b):
    df = a - b; bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
def lb(v):
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
D = C[C.day.isin(DAYS)].copy(); D["plac"] = D.id.map(team_n).fillna(0) + rng.random(len(D)) * 1e-3
CL = np.array([dm(D[D.day == d], "clean_v3_nosite") for d in DAYS]); PL = np.array([dm(D[D.day == d], "plac") for d in DAYS])
res = {"design": __doc__.split("\n    python")[0], "days": DAYS, "train_days_cached": len(TRAIN), "first_train_day": min(TRAIN),
       "placebo top3/5/10": PL.mean(0).round(1).tolist(), "clean_nosite top3/5/10": CL.mean(0).round(1).tolist(), "placebo - clean": pdiff(PL, CL)}
for a, (win, cols) in ARMS.items():
    E, rec = run_arm(win, cols); D["E"] = D.id.map(E).fillna(0); A = np.array([dm(D[D.day == d], "E") for d in DAYS])
    cal = D[D.E > 0].assign(v=D.id.map(votes).astype(float)); cal = cal[cal.v > 0]
    res[a] = {"train_days": win, "features": cols, "recall@N": lb(rec[:, 0]), "recall@2N": lb(rec[:, 1]),
              "calibration: median E / displayed votes, Spearman(E, votes)": [round(float((cal.E / cal.v).median()), 3), round(float(spearmanr(cal.E, cal.v).correlation), 3)],
              "top3/5/10": A.mean(0).round(1).tolist(), "vs placebo": pdiff(A, PL), "vs clean": pdiff(A, CL)}
    print(a, json.dumps(res[a]), round(time.time() - t0), flush=True)
    json.dump(res, open(os.path.join(OUTD, "who_backs2.json"), "w"), indent=1, default=float)
