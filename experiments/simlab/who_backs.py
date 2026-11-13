"""Standalone who-backs-it forecast at 00:05 (orchestrator 17:40Z Nov 13; model-selection rule: an explainable model that predicts NOT
WORSE than the black box replaces it). Question: can a people-side model ALONE match clean_v3_nosite?
Store: store_v3 (15:02Z), complete persons. Built on voter_harness.py's pair model (same code, exec'd), extended:
  pair features = ln(1+upvotes 30d), ln(1+upvotes 90d), ln(1+days since last upvote), topic-taste match, follows hunter / first maker
  (only with FOLLOWS=1; follow lists are undated), is the hunter, BACKED BEFORE (upvoted an earlier launch whose hunter or first maker is in
  this launch's team). Trained on the 7 launch days before the test day (history = upvotes on launches dated before each training day).
  LENIENT history = every held upvote on a launch dated before the test day (upvote rows carry no cast time; no target-day votes used).
  Expected backers E(L) = sum over active held people of P(upvote); E_age = same with each person's P x 0.48 if the account was 30-365
  days old at the launch day (measured count discount).
Arms, ranked within day: E, E_age, and (Nov 1-11 only, where live comments give it) E_age + th_n_pre (z-sum, weight leave-one-day-out
from {0.25, 0.5, 1, 2}); reference = clean_v3_nosite on the same days. Top 3/5/10 standalone; paired day difference vs clean, 4,000 day
bootstraps; "not worse" = interval includes 0 AND mean within 1.5 points on top 3.
Coverage (simulation quality): per launch, share of its store-listed voters (complete persons) who were in the scored active population,
and share in the top-N people by P (N = round E(L)); plus E(L) / displayed votes.
    FOLLOWS=0|1 python who_backs.py <store dir> <clean_live_rows_nosite.parquet> <launches dir> <salt dir> <out dir>
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); FOL = os.environ.get("FOLLOWS", "0") == "1"
os.environ["EDGES"] = "hunter_maker" if FOL else "none"
VH = open(os.path.join(HERE, "voter_harness.py")).read()
ALLD = '["2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]'
i0 = VH.index("DAYS = ["); i1 = VH.index("\n", i0); VH = VH[:i0] + "DAYS = " + ALLD + VH[i1:]
exec(VH[:VH.index("FOLL = {}")])
OUTD = OUT
P2 = pd.read_parquet(os.path.join(V3, "persons.parquet")).set_index("person_id"); JD = pd.to_datetime(P2.joined, utc=True, errors="coerce") if "joined" in P2 else pd.Series(dtype="datetime64[ns, UTC]")
by_team = {}
for i in L.id:
    for t in (lhun.get(i), lmak.get(i)):
        if t: by_team.setdefault(t, set()).add(i)
def backers(H, i):
    ls = set().union(*[by_team.get(t, set()) for t in (lhun.get(i), lmak.get(i)) if t]) - {i}
    return set(H[H.target_id.isin(ls)].person_id) if ls else set()
def X2(act, tv, lineup, follows, H):
    return [np.column_stack([X, act.index.isin(backers(H, i)).astype(float)]) for i, X in zip(lineup, pair_X(act, tv, lineup, follows))]
def run_day(day):
    H = U; F = FO; follows = F.groupby("target_id").person_id.agg(set).to_dict() if FOL else {}
    tr_days = sorted(d for d in L.day.unique() if d < day)[-7:]; Xs, ys = [], []
    for t in tr_days:
        Ht = H[H.lday < t]; act, tv, _ = feats(t, H); lu = L[L.day == t].id.tolist()
        if not len(act): continue
        voted = H[H.lday == t].groupby("target_id").person_id.agg(set).to_dict()
        for i, X in zip(lu, X2(act, tv, lu, follows, Ht)):
            y = act.index.isin(voted.get(i, set())).astype(int); m = (y == 1) | (rng.random(len(y)) < 0.1); Xs.append(X[m]); ys.append(y[m])
    X, y = np.vstack(Xs), np.concatenate(ys); m = LogisticRegression(max_iter=300).fit(X, y, sample_weight=np.where(y == 1, 1.0, 10.0))
    act, tv, _ = feats(day, H); lu = C[C.day == day].id.tolist(); Hd = H[H.lday < day]
    d0 = pd.Timestamp(day, tz="America/Los_Angeles").tz_convert("UTC"); age = (d0 - JD.reindex(act.index)).dt.days.values
    aw = np.where((age >= 30) & (age < 365), 0.48, 1.0)
    voters = H[H.lday == day].groupby("target_id").person_id.agg(set).to_dict(); out = {}
    for i, Xi in zip(lu, X2(act, tv, lu, follows, Hd)):
        p = m.predict_proba(Xi)[:, 1]; E = float(p.sum()); Ea = float((p * aw).sum()); v = voters.get(i, set())
        top = set(act.index[np.argsort(-p)[:max(1, int(round(E)))]]) if len(p) else set()
        out[i] = {"E": E, "E_age": Ea, "n_voters_held": len(v), "in_pop": len(v & set(act.index)), "in_topN": len(v & top)}
    return out, len(act), dict(zip(["coef_" + c for c in ("n30", "n90", "last", "taste", "follows", "is_hunter", "backed")], m.coef_[0].round(3).tolist()))
R, NACT, COEF = {}, {}, {}
for d in DAYS:
    o, NACT[d], COEF[d] = run_day(d); R.update(o); print(d, NACT[d], flush=True)
# th_n_pre from live comments (Nov 1+): distinct non-hunter commenters created <= 00:05 PT
import subprocess
TH = {}
for d in DAYS:
    if d < "2026-11-01": continue
    try:
        txt = subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_at_launch/{d}/live/comments_ts.jsonl"], capture_output=True, text=True).stdout
        dj = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{d}/{d}.json"], capture_output=True, text=True).stdout or "[]")
    except Exception: continue
    if not txt.strip(): continue
    import io
    CM = pd.read_json(io.StringIO(txt), lines=True); hun = {str(p["id"]): str((p.get("user") or {}).get("id")) for p in dj}
    CM["t"] = pd.to_datetime(CM.created_at, utc=True, errors="coerce"); cut = pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC") + pd.Timedelta(minutes=5)
    CM = CM[(CM.t <= cut)]; CM["lid"] = CM.launch_id.astype(str); CM["u"] = CM.commenter_user_id.astype(str)
    CM = CM[[u != hun.get(l) for u, l in zip(CM.u, CM.lid)]]
    for lid in C[C.day == d].id: TH[lid] = float(CM[CM.lid == lid].u.nunique())
D = C[C.day.isin(DAYS)].copy(); D["E"] = D.id.map(lambda i: R.get(i, {}).get("E", 0.0)); D["E_age"] = D.id.map(lambda i: R.get(i, {}).get("E_age", 0.0))
D["th"] = D.id.map(TH); D["votes"] = D.id.map(dict(zip(L.id, L.votes)))
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def compare(days, arm_fn, name):
    a = np.array([dm(arm_fn(D[D.day == d]), "s") for d in days]); c = np.array([dm(D[D.day == d], "clean_v3_nosite") for d in days]); df = a - c
    bs = np.array([df[rng.integers(0, len(days), len(days))].mean(0) for _ in range(4000)])
    ci = [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
    nw = ci[0][1] <= 0 <= ci[0][2] and abs(ci[0][0]) <= 1.5
    return {"days": len(days), "arm top3/5/10": a.mean(0).round(1).tolist(), "clean_nosite top3/5/10": c.mean(0).round(1).tolist(), "arm - clean [mean, lo, hi]": ci, "not_worse_on_top3": bool(nw)}
res = {"design": __doc__.split("\n    python")[0], "follows_used": FOL, "active_people_by_day": NACT, "pair_coefs_by_day": COEF}
res["E standalone"] = compare(DAYS, lambda g: g.assign(s=g.E), "E")
res["E_age standalone"] = compare(DAYS, lambda g: g.assign(s=g.E_age), "E_age")
d2 = [d for d in DAYS if d >= "2026-11-01" and D[D.day == d].th.notna().all()]
if d2:
    zz = lambda s: (s - s.mean()) / (s.std() or 1)
    def best_w(dout):
        tr = [d for d in d2 if d != dout]
        return max((0.25, 0.5, 1, 2), key=lambda w: np.mean([dm(D[D.day == d].assign(s=zz(np.log(D[D.day == d].E_age + 0.1)) + w * zz(np.log1p(D[D.day == d].th))), "s")[0] for d in tr]))
    W = {d: best_w(d) for d in d2}
    res["E_age + th_n_pre (2-input)"] = {**compare(d2, lambda g: g.assign(s=zz(np.log(g.E_age + 0.1)) + W[g.day.iat[0]] * zz(np.log1p(g.th))), "2in"), "weights": W}
    res["E_age standalone, same days as 2-input"] = compare(d2, lambda g: g.assign(s=g.E_age), "Ea2")
cv = pd.DataFrame([dict(id=i, **v) for i, v in R.items()]); cv = cv[cv.n_voters_held > 0]; cv["votes"] = cv.id.map(dict(zip(L.id, L.votes))).astype(float)
res["coverage"] = {"launches": len(cv), "share of held voters in scored active population (mean over launches)": round(float((cv.in_pop / cv.n_voters_held).mean()), 3),
                   "share of held voters in top-N by P, N = round(E) (mean)": round(float((cv.in_topN / cv.n_voters_held).mean()), 3),
                   "E / displayed votes (median)": round(float((cv.id.map(lambda i: R[i]["E"]) / cv.votes).median()), 3),
                   "held voters / displayed votes (median)": round(float((cv.n_voters_held / cv.votes).median()), 3)}
json.dump(res, open(os.path.join(OUTD, f"who_backs_follows{int(FOL)}.json"), "w"), indent=1, default=float)
if os.environ.get("DUMP"):   # per-launch scores (launch ids + numbers only) for the segment analysis; scratch, not committed
    D.assign(backed=D.id.map(lambda i: R.get(i, {}).get("in_pop", 0)), n_held=D.id.map(lambda i: R.get(i, {}).get("n_voters_held", 0)),
             hunter=D.id.map(lhun), maker=D.id.map(lmak)).drop(columns=["hunter", "maker"]).to_parquet(os.environ["DUMP"])
print(json.dumps({k: v for k, v in res.items() if k not in ("design", "pair_coefs_by_day")}, default=float))
