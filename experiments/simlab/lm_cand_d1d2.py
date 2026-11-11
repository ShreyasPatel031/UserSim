"""Per-launch candidate features for the LM (pre-registered in docs/RESEARCH_LOG.md 2026-11-11 02:45Z, commit 9b91802f).

D1 warm audience: store_v3 people with full upvote history who upvoted / commented on the team's earlier launches
   (launches dated <= d-2); also those active d-31..d-2, commenters, team members in the pool. log counts + within-day pct.
D2 person-sum EV: the E5 two-level baseline (two_level_baseline.py, no follows), history lag raised to d-2, retrained per
   test month on the 2 previous months, EV = sum P over people active d-61..d-2 (no label filter: features only).
Output: <workdir>/out/lm_cand_d1d2.parquet (id, day, features) - launch ids only, no handles, no person ids.

    python lm_cand_d1d2.py <workdir with v3/ launches/ salt>
"""
import json, os, sys, multiprocessing as mp
import numpy as np, pandas as pd

W = sys.argv[1]
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "two_level_baseline.py")
src = open(SRC).read().split("report = {")[0]
# D2 settings: launches from Jan; history only from launches dated <= d-2; activity window d-61..d-2
src = src.replace('L = L[L.day >= "2026-06-01"]', 'L = L[L.day >= "2026-01-01"]')
src = src.replace("past = vd < d", "past = vd <= dstr(d, -2)")
src = src.replace("rec = (vd >= dstr(d, -60)) & past", "rec = (vd >= dstr(d, -61)) & past")
src = src.replace("n30 = int(((vd >= dstr(d, -30)) & past).sum())", "n30 = int(((vd >= dstr(d, -31)) & past).sum())")
src = src.replace("hc = ci[cd < d]", "hc = ci[cd <= dstr(d, -2)]")
assert src.count("dstr(d, -2)") >= 2
sys.argv = ["x", W]; G = {"__name__": "tlb"}; exec(compile(src, "tlb", "exec"), G)
L, Lday, UPD, CMD, comp, T = G["L"], G["Lday"], G["UPD"], G["CMD"], G["comp"], G["T"]
OUT = os.path.join(W, "out")


def dstr(d, k):
    return G["dstr"](d, k)


# ---------------- D1 warm audience
full = {p for p in comp if p in T.index and not (T.loc[p, "count"] < T.loc[p, "header"])}
up_by_launch, cm_by_launch, act_days = {}, {}, {}
for p in full:
    vd, vi = UPD.get(p, (np.array([], object), np.array([], int)))
    for i in set(vi[vi >= 0]): up_by_launch.setdefault(i, set()).add(p)
    act_days[p] = np.sort(vd.astype(str))
    cd, ci = CMD.get(p, (np.array([], object), np.array([], int)))
    for i in set(ci): cm_by_launch.setdefault(i, set()).add(p)
team = L.team.tolist(); member = {}
for i, tm in enumerate(team):
    for m in tm: member.setdefault(m, []).append(i)
pool = set(pd.read_parquet(os.path.join(W, "v3", "persons.parquet")).person_id)
rows = []
for i in range(len(L)):
    d = Lday[i]; hi = dstr(d, -2); lo30 = dstr(d, -31)
    prior = {j for m in team[i] for j in member.get(m, []) if Lday[j] <= hi and j != i}
    back = set().union(*[up_by_launch.get(j, set()) | cm_by_launch.get(j, set()) for j in prior]) if prior else set()
    cms = set().union(*[cm_by_launch.get(j, set()) for j in prior]) if prior else set()
    act = sum(1 for p in back if np.any((act_days[p] >= lo30) & (act_days[p] <= hi)))
    rows.append({"id": L.id[i], "day": d, "aud_backers": len(back), "aud_backers_act30": act, "aud_commenters": len(cms),
                 "aud_team_in_store": len(team[i] & pool), "aud_prior_launches": len(prior)})
D1 = pd.DataFrame(rows)
for c in ["aud_backers", "aud_backers_act30", "aud_commenters"]:
    D1[c] = np.log1p(D1[c]); D1[c + "_pct"] = D1.groupby("day")[c].rank(pct=True)
print("D1 done", len(D1), D1.describe().T[["mean", "max"]].round(2).to_dict(), flush=True)

# ---------------- D2 person-sum EV, monthly
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]
days_all = sorted(set(Lday))


def month_job(m):
    from sklearn.linear_model import LogisticRegression
    m0 = pd.Timestamp(m + "-01"); tr0 = (m0 - pd.DateOffset(months=2)).strftime("%Y-%m-%d"); tr1 = (m0 - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    te1 = "2026-11-08" if m == "2026-11" else (m0 + pd.DateOffset(months=1) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    tr_days = [d for d in days_all if tr0 <= d <= tr1]; te_days = [d for d in days_all if m0.strftime("%Y-%m-%d") <= d <= te1]
    people = sorted(comp)
    Xtr, Ytr, wtr = G["build"](tr_days, people, False, True)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    clf = LogisticRegression(C=1.0, max_iter=2000).fit((Xtr - mu) / sd, Ytr, sample_weight=wtr)
    ev = {}
    for d in te_days:
        for p in people:
            r = G["day_rows"](p, d, False)
            if r is None: continue
            idx, x = r; ph = clf.predict_proba((x - mu) / sd)[:, 1]
            for i, v in zip(idx, ph): ev[i] = ev.get(i, 0.0) + v
    print(m, "train", len(Ytr), "launches", len(ev), flush=True)
    return {"month": m, "train": [tr0, tr1], "ev": ev}


with mp.get_context("fork").Pool(4) as pool:
    res = pool.map(month_job, MONTHS)
ev = {}
for r in res: ev.update(r["ev"])
D2 = pd.DataFrame({"id": [L.id[i] for i in ev], "ev_e5": [np.log1p(v) for v in ev.values()]})
F = D1.merge(D2, on="id", how="left")
F["ev_e5_pct"] = F.groupby("day").ev_e5.rank(pct=True)
F = F[F.day >= "2026-03-01"]
F.to_parquet(os.path.join(OUT, "lm_cand_d1d2.parquet"), index=False)
json.dump({"months": [{"month": r["month"], "train": r["train"], "n_launch": len(r["ev"])} for r in res], "n": len(F),
           "assert": "D1 and D2 use launches dated <= d-2 only (src patched; asserted)"}, open(os.path.join(OUT, "lm_cand_d1d2_meta.json"), "w"), indent=1)
print("written", len(F), flush=True)
