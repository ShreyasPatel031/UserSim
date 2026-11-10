"""Independent reference baseline for the two-level simulation (docs/SIM_TWO_LEVEL_PLAN.md on claude/cool-volta-l5nuo4).

Person level: P(person p upvotes featured launch L on day d) by a plain logistic regression on taste + ties + activity,
trained only on complete people (store_v3 complete=True), whose non-votes are real.
Population level: a launch's expected votes = sum_p w_p * P(p, L) over the complete people active before d; rank the day.

Honesty rules (E5 review checklist, binding on both this baseline and the PH agent's model):
  * every feature uses only events of launches dated before d (history), and people's follows only in the "follow" arm
    (follow lists are November snapshots with no follow date: a follow may come after the upvote -> reported separately)
  * a person enters day d only if active before d: >= 1 upvote of a launch in [d-60, d-1]
  * labels on day d only for people whose upvote list was read >= 2 days after d, and on or after their coverage start
    (oldest listed vote when the list is shorter than the header, e.g. PH's signed-out ~200 cap)
  * monthly retrain: the September model (train days Aug 1 - Sep 30) scores Oct 20-31; the October model (train days
    Sep 1 - Oct 31) scores Nov 1-7. Training labels end before the first test day.
Weights: post-stratification of complete people to the whole tracked pool (complete + incomplete, store_v3 persons) by
pre-d activity tier. The plan's target (voter lists read in full across all ranks) is not in the store; the pool is the
nearest available and is itself biased toward voters seen on launches - stated, not hidden.

Inputs (bucket): raw/population/store_v3/{events,persons,tabs}.parquet, raw/population/_salt, tables/launches/*.parquet.
Handles from the launches table are hashed to person ids in memory only; nothing with a handle is written.

    python two_level_baseline.py <workdir with v3/ launches/ salt>  -> results in <workdir>/out/
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, log_loss
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

W = sys.argv[1]
OUT = os.path.join(W, "out"); os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(0)
SALT = open(os.path.join(W, "salt")).read().strip()
NEG_PER_POS = 8           # training negatives sampled per positive (intercept corrected for the sampling)
FOLDS = [("sep", "2026-08-01", "2026-09-30", "2026-10-20", "2026-10-31"),
         ("oct", "2026-09-01", "2026-10-31", "2026-11-01", "2026-11-07")]


def pid(handle):
    return "p_" + hashlib.sha256((SALT + "producthunt:" + str(handle).lower()).encode()).hexdigest()[:16]


# ---------------- launches (featured, with day, team, topics, text)
L = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(W, "launches", "*.parquet")))], ignore_index=True)
L = L.sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.day >= "2026-06-01"].reset_index(drop=True)
L["topics_l"] = L.topics.map(lambda s: json.loads(s) if isinstance(s, str) and s.startswith("[") else [])
L["team"] = [({pid(m) for m in (json.loads(mk) if isinstance(mk, str) and mk.startswith("[") else [])} | ({pid(po)} if po else set()))
             for mk, po in zip(L.makers, L.poster)]
L["votes"] = pd.to_numeric(L.votes, errors="coerce"); L["daily_rank"] = pd.to_numeric(L.daily_rank, errors="coerce")
lid = {x: i for i, x in enumerate(L.id)}; Lday = L.day.to_numpy()
topics = sorted({t for ts in L.topics_l for t in ts}); tix = {t: k for k, t in enumerate(topics)}
TOP = np.zeros((len(L), len(topics)), np.float32)
for i, ts in enumerate(L.topics_l):
    for t in ts: TOP[i, tix[t]] = 1
TOP /= np.linalg.norm(TOP, axis=1, keepdims=True) + 1e-9
txt = (L.name.fillna("") + ". " + L.tagline.fillna("") + ". " + L.description.fillna("")).tolist()
EMB = TruncatedSVD(48, random_state=0).fit_transform(TfidfVectorizer(min_df=2, max_features=30000, ngram_range=(1, 2), sublinear_tf=True).fit_transform(txt))
EMB /= np.linalg.norm(EMB, axis=1, keepdims=True) + 1e-9
print("launches", len(L), "topics", len(topics), flush=True)

# ---------------- people
P = pd.read_parquet(os.path.join(W, "v3", "persons.parquet")); pool = set(P.person_id); comp = set(P[P.complete].person_id)
T = pd.read_parquet(os.path.join(W, "v3", "tabs.parquet")); T = T[T.tab == "upvotes"].set_index("person_id")
E = pd.read_parquet(os.path.join(W, "v3", "events.parquet"), columns=["person_id", "kind", "target_id", "extra"])
E = E[E.person_id.isin(pool)]
up = E[E.kind == "upvote"].copy()
up["lday"] = up.target_id.map(lambda x: Lday[lid[x]] if x in lid else None)
la = up.extra.str.extract(r'"launched_at": "(\d{4}-\d\d-\d\d)')[0]
up["vday"] = up.lday.fillna(la)                 # launch day of the upvoted post (featured table, else launched_at)
up = up.dropna(subset=["vday"])
cm = E[(E.kind == "comment") & E.target_id.isin(lid)].copy(); cm["vday"] = cm.target_id.map(lambda x: Lday[lid[x]])
fol = E[E.kind == "follows"].groupby("person_id").target_id.agg(set).to_dict()
del E
print("upvotes with a day", len(up), "pool people", len(pool), "complete", len(comp), flush=True)

# coverage: labels for d only if the upvote list was read >= 2 days after d, and from the oldest listed vote when short
fetched = T.fetched_at.dt.strftime("%Y-%m-%d").to_dict()
short = (T["count"] < T.header).to_dict()
oldest = up.groupby("person_id").vday.min().to_dict()
cover_from = {p: (oldest.get(p, "9999") if short.get(p, False) else "2000-01-01") for p in comp}

UPD = up.groupby("person_id").apply(lambda g: (g.vday.to_numpy(), g.target_id.map(lid).fillna(-1).astype(int).to_numpy())).to_dict()
CMD = cm.groupby("person_id").apply(lambda g: (g.vday.to_numpy(), g.target_id.map(lid).astype(int).to_numpy())).to_dict()
team_of = L.team.tolist()


_DC = {}
def dstr(d, k):
    key = (d, k)
    if key not in _DC: _DC[key] = str((pd.Timestamp(d) + pd.Timedelta(days=k)).date())
    return _DC[key]


def day_rows(p, d, follow_arm):
    """Feature rows for person p and every featured launch of day d, from events dated before d. None if not active."""
    vd, vi = UPD.get(p, (np.array([], object), np.array([], int)))
    past = vd < d
    rec = (vd >= dstr(d, -60)) & past
    if not rec.any():
        return None
    n30 = int(((vd >= dstr(d, -30)) & past).sum())
    tenure = (pd.Timestamp(d) - pd.Timestamp(vd[past].min())).days
    hi = vi[past & (vi >= 0)]
    cd, ci = CMD.get(p, (np.array([], object), np.array([], int)))
    hc = ci[cd < d]
    tv = TOP[hi].sum(0) if len(hi) else np.zeros(len(topics), np.float32); tv /= np.linalg.norm(tv) + 1e-9
    ev = EMB[hi].sum(0) if len(hi) else np.zeros(EMB.shape[1]); ev /= np.linalg.norm(ev) + 1e-9
    backed = {}
    for j in list(hi) + list(hc):
        for m in team_of[j]: backed[m] = backed.get(m, 0) + 1
    fo = fol.get(p, set()) if follow_arm else set()
    idx = np.where(Lday == d)[0]
    rows = []
    for i in idx:
        tm = team_of[i]
        rows.append((float(TOP[i] @ tv), float(EMB[i] @ ev), np.log1p(sum(backed.get(m, 0) for m in tm)),
                     float(p in tm), float(len(tm & fo) > 0), np.log1p(n30), np.log1p(len(hi)), np.log1p(max(tenure, 0)), np.log1p(len(hc))))
    return idx, np.array(rows, np.float32)


FEATS = ["taste_topic", "taste_text", "tie_backed_team", "is_team", "follows_team", "act_30d", "act_hist", "tenure", "comments_hist"]


def labels(p, d, idx):
    vd, vi = UPD.get(p, (np.array([], object), np.array([], int)))
    got = set(vi[vd == d])
    return np.array([int(i in got) for i in idx], np.int8)


def eligible(p, d):
    return fetched.get(p, "0000") >= dstr(d, 2) and cover_from.get(p, "9999") <= d


def build(days, people, follow_arm, train):
    X, Y, meta = [], [], []
    for d in days:
        for p in people:
            if not eligible(p, d):
                continue
            r = day_rows(p, d, follow_arm)
            if r is None: continue
            idx, x = r; y = labels(p, d, idx)
            if train:
                pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]
                if len(pos) == 0:
                    if rng.random() > 0.05: continue         # most person-days have no vote; keep 5%, re-weighted below
                    keep = rng.choice(neg, min(len(neg), NEG_PER_POS), replace=False); wts = np.full(len(keep), 1 / 0.05 * len(neg) / max(len(keep), 1))
                    X.append(x[keep]); Y.append(y[keep]); meta.append(np.c_[np.full(len(keep), 0), wts]); continue
                keep_n = rng.choice(neg, min(len(neg), NEG_PER_POS * len(pos)), replace=False)
                keep = np.r_[pos, keep_n]
                wts = np.r_[np.ones(len(pos)), np.full(len(keep_n), len(neg) / max(len(keep_n), 1))]
                X.append(x[keep]); Y.append(y[keep]); meta.append(np.c_[np.full(len(keep), 0), wts])
            else:
                X.append(x); Y.append(y); meta.append(np.c_[np.full(len(idx), 0), np.ones(len(idx))])
                meta[-1] = pd.DataFrame({"p": p, "d": d, "launch": idx})
    if train:
        M = np.concatenate(meta); return np.concatenate(X), np.concatenate(Y), M[:, 1]
    return np.concatenate(X), np.concatenate(Y), pd.concat(meta, ignore_index=True)


def tiers(n30):
    return np.digitize(n30, [1, 3, 10, 30])


def weights(day, people_used):
    """post-stratify complete people to the pool by 30-day activity tier before d."""
    def n30(p):
        vd, _ = UPD.get(p, (np.array([], object), None))
        return int(((vd < day) & (vd >= dstr(day, -30))).sum())
    pool_t = pd.Series([tiers(n30(p)) for p in pool if p in UPD]).value_counts(normalize=True)
    used_t = pd.Series({p: tiers(n30(p)) for p in people_used})
    share = used_t.value_counts(normalize=True)
    w = used_t.map(lambda t: pool_t.get(t, 0) / share[t])
    return w


def run(follow_arm):
    res = {"arm": "with follows" if follow_arm else "no follows", "folds": {}}
    allP = []
    people = sorted(comp)
    for name, tr0, tr1, te0, te1 in FOLDS:
        tr_days = [str(x.date()) for x in pd.date_range(tr0, tr1) if str(x.date()) in set(Lday)]
        te_days = [str(x.date()) for x in pd.date_range(te0, te1) if str(x.date()) in set(Lday)]
        Xtr, Ytr, wtr = build(tr_days, people, follow_arm, True)
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
        clf = LogisticRegression(C=1.0, max_iter=2000).fit((Xtr - mu) / sd, Ytr, sample_weight=wtr)
        Xte, Yte, meta = build(te_days, people, follow_arm, False)
        meta["y"] = Yte; meta["p_hat"] = clf.predict_proba((Xte - mu) / sd)[:, 1]
        meta["fold"] = name
        res["folds"][name] = {"train_days": [tr_days[0], tr_days[-1]], "test_days": [te_days[0], te_days[-1]],
                              "train_rows": int(len(Ytr)), "train_pos": int(Ytr.sum()), "max_train_label_day": tr_days[-1],
                              "coef": dict(zip(FEATS, np.round(clf.coef_[0], 3).tolist()))}
        allP.append(meta)
        print(name, "train", len(Ytr), "test rows", len(meta), flush=True)
    M = pd.concat(allP, ignore_index=True)
    M["pid"] = M.p
    return res, M


def person_metrics(M):
    out = {"rows": int(len(M)), "people": int(M.p.nunique()), "person_days": int(M.groupby(["p", "d"]).ngroups), "positives": int(M.y.sum())}
    out["auc"] = round(roc_auc_score(M.y, M.p_hat), 4); out["logloss"] = round(log_loss(M.y, M.p_hat.clip(1e-6, 1 - 1e-6)), 5)
    g = M[M.groupby(["p", "d"]).y.transform("sum") > 0]
    r = g.groupby(["p", "d"]).p_hat.rank(ascending=False, method="first")
    out["hit@3 (person-days with a vote)"] = round(float(g.assign(r=r).groupby(["p", "d"]).apply(lambda x: (x.y[x.r <= 3].sum() > 0)).mean()), 4)
    # recall of each launch's real voters (in the sample) among its top-N predicted voters, N = real count
    rr = []
    for (d, l), x in M.groupby(["d", "launch"]):
        n = int(x.y.sum())
        if n: rr.append(x.nlargest(n, "p_hat").y.sum() / n)
    out["voter R-precision (mean over launches)"] = round(float(np.mean(rr)), 4)
    return out


def boot_days(vals, B=2000):
    vals = np.asarray(vals, float); m = vals.mean()
    bs = [vals[rng.integers(0, len(vals), len(vals))].mean() for _ in range(B)]
    return [round(m, 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]


def population_metrics(M):
    rows = []
    for d, x in M.groupby("d"):
        w = weights(d, x.p.unique())
        x = x.assign(w=x.p.map(w))
        E_ = x.groupby("launch").apply(lambda g: pd.Series({"ev_w": (g.w * g.p_hat).sum(), "ev_u": g.p_hat.sum(), "obs_w": (g.w * g.y).sum()}))
        E_ = E_.join(L[["daily_rank", "votes"]], how="left")
        E_ = E_[E_.daily_rank.notna()]
        r = {"d": d, "n_launch": len(E_), "people": x.p.nunique()}
        for s in ("ev_w", "ev_u", "obs_w"):
            for k in (3, 5, 10):
                pred = set(E_.nlargest(k, s).index); real = set(E_.nsmallest(k, "daily_rank").index)
                r[f"{s}_top{k}"] = len(pred & real) / k
            r[f"{s}_spearman"] = spearmanr(E_[s], E_.votes).correlation
        rows.append(r)
    R = pd.DataFrame(rows)
    out = {"days": int(len(R)), "people_per_day_median": int(R.people.median())}
    for s, lab in (("ev_w", "baseline, weighted"), ("ev_u", "baseline, unweighted"), ("obs_w", "REFERENCE: real votes of the sample, weighted (ceiling of a perfect person model on this sample)")):
        out[lab] = {f"top{k}": boot_days(R[f"{s}_top{k}"]) for k in (3, 5, 10)}
        out[lab]["spearman"] = boot_days(R[f"{s}_spearman"].fillna(0))
    return out, R


report = {"made_utc": str(pd.Timestamp.now("UTC")), "split": FOLDS, "weights": "post-stratified to the store_v3 pool by 30-day activity tier before d (target = pool, not full voter lists; see doc)"}
for arm in (False, True):
    res, M = run(arm)
    res["person"] = person_metrics(M)
    res["population"], R = population_metrics(M)
    R.to_csv(os.path.join(OUT, f"pop_by_day_{'fol' if arm else 'nofol'}.csv"), index=False)
    M[["d", "launch", "y", "p_hat", "fold"]].to_parquet(os.path.join(OUT, f"person_rows_{'fol' if arm else 'nofol'}.parquet"))  # no person ids written
    report["follows" if arm else "no_follows"] = res
    print(json.dumps(res, indent=1, default=str), flush=True)
json.dump(report, open(os.path.join(OUT, "two_level_baseline.json"), "w"), indent=1, default=str)
