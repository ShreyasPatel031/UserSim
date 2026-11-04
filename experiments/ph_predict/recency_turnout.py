"""Honest recency in the person model (orchestrator, Nov 4 01:30 UTC). Does a person's dated activity in the last 1-7 days,
known before the day, predict who turns up and so improve per-launch pool turnout over pnx?

Honest dated activity exists only from Oct 28 (daily page-1 upvote first-seen; API comments from Nov 1; day-only
comments usable at day resolution), so the person model cannot be retrained with it (its training months predate it).
The test is therefore a turnout reweighting of the live person model:
  pnx (live, pipeline.sim_daily): per (pool person, launch) p from model_<month>.pkl, person weight w (share of the 30
  days before d with any activity); per launch ev = sum w * p.
  recency: per person, from raw/population/store_v2 events KNOWN before d (first_seen_at < 00:00 PT of d) and TIMED
  before d (ts_hi < 00:00 PT of d): days since last activity, upvotes and comments in the last 1 / 7 days, active days in
  the last 7. A logistic model of "acted on any of d's launches" on [log w, recency] is fitted leave-one-day-out over the
  test days (out of sample by day); w_rec = its predicted probability; per launch ev_rec = sum w_rec * p.
Scores per day (Oct 29 - Nov 3): within-day Spearman over launches of ev vs real pool turnout (pool people acting on
the launch), pnx vs recency, paired by day, bootstrap over people (500); person-level AUC of w vs w_rec for "acted";
person-level top-3 hit (an acted launch among the person's top 3 by p): the same for both, since recency weights
people, not launches; reported for completeness.
Person ids: store_v2 is keyed on salted hashes ("p_" + sha256(salt + "producthunt:" + lower(username))[:16]); the salt
(raw/population/_salt) is read to match and never printed. Counts only: no usernames are written.
usage: python recency_turnout.py 2026-10-29 2026-11-03 -> results/recency_turnout.json"""
import hashlib, json, os, pickle, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(HERE)
sys.path.insert(0, EXP)
BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim"
WORK = os.environ.get("RT_WORK", os.path.expanduser("~/rt_work"))


def stage():
    """Live person model and launch vectors (copied from usersim-pipeline to tmp/ph_ops/sim_copy), and store_v2."""
    os.makedirs(f"{WORK}/live", exist_ok=True); os.makedirs(f"{WORK}/models", exist_ok=True)
    for src, dst in ((f"{BUCKET}/tmp/ph_ops/sim_copy/emb.npz", f"{WORK}/live/emb.npz"),
                     (f"{BUCKET}/tmp/ph_ops/sim_copy/sim_models/model_2026-11.pkl", f"{WORK}/models/model_2026-11.pkl"),
                     (f"{BUCKET}/raw/population/store_v2/events.parquet", f"{WORK}/events_v2.parquet")):
        if not os.path.exists(dst):
            subprocess.run(["gsutil", "-q", "cp", src, dst], check=True)
    # the October days use the model trained on October's store rows (to ~Oct 24): out of sample for Oct 29+
    m10 = f"{WORK}/models/model_2026-10.pkl"
    if not os.path.exists(m10):
        shutil.copy(f"{WORK}/models/model_2026-11.pkl", m10)


def salt():
    return subprocess.run(["gsutil", "cat", f"{BUCKET}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()


def person_rows(d):
    """(person, id, w, p) for every active pool person x launch of day d, from the live person model."""
    os.environ["SIM_LIVE"] = f"{WORK}/live"; os.environ["SIM_MODELS"] = f"{WORK}/models"
    from pipeline import sim_daily as SD
    SD.LIVE, SD.MODELS = f"{WORK}/live", f"{WORK}/models"
    P, I, E = SD.frames(d)
    Z = dict(np.load(f"{WORK}/live/emb.npz")); have = set(map(str, Z["launch_ids"]))
    miss = set(I[I.day <= d].id) - have
    if miss & set(I[I.day == d].id):
        raise SystemExit(f"{d}: {len(miss & set(I[I.day == d].id))} of the day's launches lack vectors in emb.npz")
    from simlab import store, harness, popscore as PS
    store.RAW = f"{WORK}/live"; store.load = lambda: (P, I, E)
    harness.baseline = lambda: pd.DataFrame({"id": I.id, "day": I.day, "base": 0.5})
    PS.G.clear(); PS.load()
    art = pickle.load(open(f"{WORK}/models/{SD.model_for(d)}", "rb"))
    D = PS.choice.rows(day_from=d, day_to=d, all_people=True)
    D = PS.featurize(D, art["cf"], art["prior_cut"])
    D, pc = PS.page_cols(D)
    D["p"] = art["model"].predict_proba(D[PS.FEATS + pc])[:, 1]
    lineup = set(I[I.day == d].id)
    from pipeline import warehouse as W   # labels: who acted on the day's launches (all later information, final)
    q = ",".join(repr(x) for x in lineup)
    A = W.query(f"SELECT DISTINCT person, launch_id::VARCHAR AS id FROM events WHERE launch_id::VARCHAR IN ({q}) AND kind IN ('upvote','comment')")
    act = set(zip(A.person, A.id))
    D = D[["person", "id", "w", "p"]].copy(); D["id"] = D.id.astype(str)
    D["y"] = [int((u, x) in act) for u, x in zip(D.person, D.id)]
    return D


def recency(people, d, EV, sl):
    """Per person: recency features from store_v2 events known and timed before 00:00 PT of d."""
    d0 = pd.Timestamp(f"{d} 00:00", tz="America/Los_Angeles").tz_convert("UTC")
    h = {u: "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16] for u in people}
    X = EV[(EV.first_seen_at < d0) & (EV.ts_hi < d0) & (EV.person_id.isin(set(h.values())))]
    out = {}
    g = {pid: q for pid, q in X.groupby("person_id")}
    for u, pid in h.items():
        q = g.get(pid)
        if q is None or not len(q):
            out[u] = (99.0, 0, 0, 0, 0, 0); continue
        age = (d0 - q.ts_hi).dt.total_seconds() / 86400
        up, cm = q.kind == "upvote", q.kind == "comment"
        days7 = q[age <= 7].ts_hi.dt.tz_convert("America/Los_Angeles").dt.date.nunique()
        out[u] = (float(age.min()), int((up & (age <= 1)).sum()), int((up & (age <= 7)).sum()),
                  int((cm & (age <= 1)).sum()), int((cm & (age <= 7)).sum()), int(days7))
    cols = ["rec_days_since", "rec_up1", "rec_up7", "rec_cm1", "rec_cm7", "rec_active7"]
    return pd.DataFrame.from_dict(out, orient="index", columns=cols).rename_axis("person").reset_index(), cols


def launch_rho(D, wcol):
    L = D.assign(ev=D[wcol] * D.p).groupby("id").agg(ev=("ev", "sum"), y=("y", "sum"))
    return spearmanr(L.ev, L.y).correlation if L.y.nunique() > 1 else np.nan


def main(d_from, d_to):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    stage(); sl = salt()
    EV = pd.read_parquet(f"{WORK}/events_v2.parquet", columns=["person_id", "kind", "ts_hi", "first_seen_at"])
    EV = EV[EV.kind.isin(["upvote", "comment"])]
    EV["ts_hi"] = pd.to_datetime(EV.ts_hi, utc=True, errors="coerce", format="ISO8601")
    EV["first_seen_at"] = pd.to_datetime(EV.first_seen_at, utc=True, errors="coerce", format="ISO8601")
    days = [x.strftime("%Y-%m-%d") for x in pd.date_range(d_from, d_to)]
    per = {}
    for d in days:
        D = person_rows(d)
        R, cols = recency(D.person.unique(), d, EV, sl)
        per[d] = D.merge(R, on="person", how="left")
        print(json.dumps({"day": d, "rows": len(D), "people": int(D.person.nunique()), "launches": int(D.id.nunique()),
                          "people_acting": int(D.groupby("person").y.max().sum()),
                          "people_with_recent_activity": int((R.rec_days_since < 7).sum())}), flush=True)
    # person-level turnout model, leave one day out
    Pp = {d: D.groupby("person").agg(w=("w", "first"), y=("y", "max"), **{c: (c, "first") for c in cols}).reset_index() for d, D in per.items()}
    feat = lambda T: np.c_[np.log(T.w.clip(lower=1e-3)), np.log1p(T[cols[1:]].values), np.minimum(T.rec_days_since.values, 30) / 30]
    res = {"days": days, "per_day": {}, "reference": "pnx (live person model, TIE2) on the same days"}
    rng = np.random.default_rng(0); diffs = []
    for d in days:
        tr = pd.concat([Pp[x] for x in days if x != d]); te = Pp[d]
        m = LogisticRegression(max_iter=2000).fit(feat(tr), tr.y)
        wr = dict(zip(te.person, m.predict_proba(feat(te))[:, 1]))
        D = per[d].assign(w_rec=lambda x: x.person.map(wr))
        r0, r1 = launch_rho(D, "w"), launch_rho(D, "w_rec")
        auc0 = roc_auc_score(te.y, te.w) if te.y.nunique() > 1 else np.nan
        auc1 = roc_auc_score(te.y, te.person.map(wr)) if te.y.nunique() > 1 else np.nan
        act = D[D.y == 1].person.unique()
        top3 = D[D.person.isin(act)].assign(rk=lambda x: x.groupby("person").p.rank(ascending=False, method="first"))
        hit = float(top3.groupby("person").apply(lambda g: bool(((g.rk <= 3) & (g.y == 1)).any()), include_groups=False).mean()) if len(act) else np.nan
        ppl = D.person.unique(); byp = {u: g for u, g in D.groupby("person")}; bs = []
        for _ in range(int(os.environ.get("BOOT", "500"))):
            S = pd.concat([byp[u] for u in rng.choice(ppl, len(ppl))])
            bs.append(launch_rho(S, "w_rec") - launch_rho(S, "w"))
        res["per_day"][d] = {"launch_rho_pnx": round(float(r0), 3), "launch_rho_recency": round(float(r1), 3), "diff": round(float(r1 - r0), 3),
                             "diff_ci95_people_boot": [round(float(x), 3) for x in np.nanpercentile(bs, [2.5, 97.5])],
                             "person_auc_pnx_w": round(float(auc0), 3), "person_auc_recency": round(float(auc1), 3),
                             "person_top3_hit": round(hit, 3), "launches": int(D.id.nunique()), "people_acting": int(len(act))}
        diffs.append(r1 - r0)
    res["mean_diff"] = round(float(np.mean(diffs)), 3)
    res["days_recency_better"] = int(sum(x > 0 for x in diffs))
    res["note"] = "person top-3 hit is identical for both arms: recency reweights people, not their choice of launch"
    json.dump(res, open(os.environ.get("OUT", os.path.join(HERE, "results", "recency_turnout.json")), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
