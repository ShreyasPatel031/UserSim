"""Team-audience pull pilot (orchestrator 06:50Z Nov 11): UPPER BOUND with a known LEAK. Follow edges come from the
store_v3 follow lists (Nov snapshots, undated: some edges were made after launch day d, possibly because of L).
Edge P -> M (P follows M) from either side's held list (complete followers' 'following' tab or complete makers'
'followers' tab). Team of L = real makers (clean_handles) + hunter, hashed with the population salt (never printed).
  held(L)   >= 1 team member whose followers tab is in store_v3 (whole follower list held)
  (a) arrivals: base = it10 candidate rows C(L) (arrivals/<d>.parquet); fol = C(L) + complete people (events_cp
      population) who follow a team member, with person features as in arrivals.build and new features
      fnov_n (log count of team members followed), fnov (any); team features tcf (log # complete followers of the team),
      ttot (log of the team's summed follower counts, followers-tab header). Monthly honest fits (Sep -> Oct, Oct -> Nov),
      no_dormant (act_30 > 0), label-filtered. Scored Oct 20 - Nov 8 on held launches (top-k among held launches by
      votes) and on all launches; person Hit@1 on candidate person-days (>= 1 pick, >= 2 candidate launches).
  (b) writes <SIMBT>/arrivals_fol/launch_feats.parquet (day, id, held, tcf, ttot, arr_ev_fol) for launch_mult_diag.py
      (TFOL=1) to add to the m_L ridge.
usage: SIMBT=<dir> python team_fol_pilot.py [build|score]  -> results/team_fol_pilot.json (counts only)"""
import glob, hashlib, json, os, subprocess, sys
from collections import defaultdict
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; OUT = f"{WORK}/arrivals_fol"; os.makedirs(OUT, exist_ok=True)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
STORE = os.environ.get("STORE", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/fol")
NEWF = ["fnov_n", "fnov", "tcf", "ttot"]


def build():
    from simlab.handles import clean_handles
    import arrivals as A
    sl = subprocess.run(["gsutil", "cat", f"{B}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()
    hid = lambda u: "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]
    V = pd.read_parquet(f"{STORE}/events.parquet", columns=["person_id", "kind", "target_id"])
    V = V[V.kind == "follows"][["person_id", "target_id"]].drop_duplicates()
    fol_of = V.groupby("target_id").person_id.apply(set).to_dict()          # followee -> followers
    T = pd.read_parquet(f"{STORE}/tabs.parquet"); Tf = T[T.tab == "followers"]
    held_pid = set(Tf.person_id); ftot = dict(zip(Tf.person_id, Tf.header.fillna(Tf["count"]).astype(float)))
    I = pd.read_parquet(f"{WORK}/items.parquet"); I["id"] = I.id.astype(str)
    team = {}
    for r in I.itertuples():
        mk = clean_handles(json.loads(r.makers or "[]")); h = r.poster if r.poster and not str(r.poster).startswith("[") else None
        team[r.id] = {hid(x) for x in mk} | ({hid(h)} if h else set())
    E = pd.read_parquet(f"{WORK}/events_cp.parquet"); E["date"] = E.date.astype(str).str[:10]; E["item"] = E.item.astype(str)
    pop = set(E.person); first = E.groupby("person").date.min().to_dict()
    adates = E[["person", "date"]].drop_duplicates()
    up = E[E.kind == "upvote"]
    import two_level as TL
    ok, _ = TL._label_maps()
    lf = []
    for f in sorted(glob.glob(f"{A.OUT}/2026-*.parquet")):
        d = os.path.basename(f)[:10]
        if not ("2026-09-01" <= d <= "2026-11-08"):
            continue
        R = pd.read_parquet(f); R["id"] = R.id.astype(str)
        act = adates[adates.date < d]; cut30 = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        a30 = act[act.date >= cut30].groupby("person").size().to_dict(); alll = act.groupby("person").size().to_dict()
        lastact = act.groupby("person").date.max().to_dict()
        lab = up[up.date == d]; pos = set(zip(lab.person, lab.item))
        new = []; R["fnov_n"] = 0.0
        tf = {}
        for L, g in R.groupby("id"):
            tm = team.get(L, set())
            cnt = defaultdict(int)
            for m in tm:
                for p in fol_of.get(m, ()):
                    if p in pop and p not in tm:
                        cnt[p] += 1
            tcf = len(cnt); ttot = sum(ftot.get(m, 0.0) for m in tm)
            tf[L] = (bool(tm & held_pid), np.log1p(tcf), np.log1p(ttot))
            have = set(g.person)
            R.loc[g.index, "fnov_n"] = [np.log1p(cnt.get(p, 0)) for p in g.person]
            t0 = g.iloc[0]
            for p, c in cnt.items():
                if p in have:
                    continue
                new.append({"person": p, "id": L, "tie_mk": 0.0, "tie_hu": 0.0, "tie_days": 999.0, "fol_mk": 0.0, "fol_hu": 0.0,
                            "past_arr": 0.0, "act_30": float(a30.get(p, 0)),
                            "days_since": float((pd.Timestamp(d) - pd.Timestamp(lastact[p])).days) if p in lastact else 999.0,
                            "tenure": float((pd.Timestamp(d) - pd.Timestamp(first[p])).days) if p in first and first[p] < d else 0.0,
                            "log_act_all": np.log1p(alll.get(p, 0)), "n_makers_real": t0.n_makers_real, "team_prev": t0.team_prev,
                            "team_arr_mean": t0.team_arr_mean, "cand_n": t0.cand_n, "lineup_n": t0.lineup_n,
                            "y": int((p, L) in pos), "day": d, "fnov_n": np.log1p(c), "new": True})
        R["new"] = False
        X = pd.concat([R, pd.DataFrame(new)], ignore_index=True) if new else R
        X.loc[X.new, "lab_ok"] = ok(X.loc[X.new, "person"], d)
        X["lab_ok"] = X.lab_ok.astype(bool)
        X["fnov"] = (X.fnov_n > 0).astype(float)
        X["held"] = X.id.map(lambda L: tf.get(L, (False, 0, 0))[0]); X["tcf"] = X.id.map(lambda L: tf.get(L, (0, 0, 0))[1])
        X["ttot"] = X.id.map(lambda L: tf.get(L, (0, 0, 0))[2])
        X["cand_n_fol"] = X.groupby("id").person.transform("size").astype(float)
        X.to_parquet(f"{OUT}/{d}.parquet")
        print(json.dumps({"day": d, "base_rows": len(R), "new_rows": len(new), "new_pos": int(sum(r["y"] for r in new)),
                          "launches": int(X.id.nunique()), "held": int(sum(v[0] for v in tf.values()))}), flush=True)


def score():
    import lightgbm as lgb
    from scipy.stats import spearmanr
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    vt = dict(zip(L.id, L.votes))
    files = {os.path.basename(f)[:10]: f for f in glob.glob(f"{OUT}/2026-*.parquet")}
    test = sorted(d for d in files if "2026-10-20" <= d <= "2026-11-08")
    import arrivals as A
    V = {"base": (A.PF + A.TF, False), "fol": (A.PF + A.TF + NEWF + ["cand_n_fol"], True)}
    rng = np.random.default_rng(0); per = []; hit = []; feats = []; pooled = []
    D = {d: pd.read_parquet(files[d]) for d in files}
    for d in D:
        D[d] = D[d][D[d].act_30 > 0]
    for nm, (cols, use_new) in V.items():
        models = {}
        for mon in sorted({d[:7] for d in test}):
            prev = (pd.Timestamp(mon + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
            Tr = pd.concat([D[d] for d in sorted(D) if d[:7] == prev]); Tr = Tr[Tr.lab_ok & (use_new | ~Tr.new)]
            models[mon] = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=4).fit(Tr[cols], Tr.y)
        for d in test:
            X = D[d] if use_new else D[d][~D[d].new]
            X = X.assign(p=models[d[:7]].predict_proba(X[cols])[:, 1])
            ev = X.groupby("id").agg(ev=("p", "sum"), held=("held", "first"))
            ev["votes"] = ev.index.map(vt); ev = ev.dropna(subset=["votes"])
            if nm == "fol":
                feats.append(ev.reset_index()[["id"]].assign(day=d, arr_ev_fol=np.log1p(ev.ev.values)))
            ev["ev_rk"] = ev.ev.rank(ascending=False, method="first"); ev["v_rk"] = ev.votes.rank(ascending=False, method="first")
            ev["ev_pct"] = ev.ev.rank(pct=True); ev["v_pct"] = ev.votes.rank(pct=True)
            pooled.append(ev[ev.held].reset_index().assign(day=d, variant=nm))
            for sub, G in (("all", ev),):
                row = {"day": d, "variant": nm, "sub": sub, "n": len(G)}
                for k in (3, 5, 10):
                    top = set(G.nlargest(k, "votes").index)
                    row[f"top{k}"] = len(set(G.nlargest(k, "ev").index) & top) / k * 100 if len(G) >= k + 2 else np.nan
                row["sp"] = spearmanr(G.ev, G.votes).correlation if len(G) >= 5 else np.nan
                per.append(row)
            Lb = X[X.lab_ok]
            vot = Lb.groupby("person").y.transform("sum"); nl = Lb.groupby("person").id.transform("size")
            Q = Lb[(vot > 0) & (nl >= 2)].copy(); Q["p"] = Q.p + rng.random(len(Q)) * 1e-9
            top = Q.loc[Q.groupby("person").p.idxmax()]; allnew = Q.groupby("person").new.all()
            for r in top.itertuples():
                hit.append({"day": d, "variant": nm, "person": r.person, "new": bool(allnew[r.person]), "hit1": float(r.y)})
    P = pd.DataFrame(per); H = pd.DataFrame(hit)

    def b(x, r=1):
        x = np.asarray(x, float); x = x[~np.isnan(x)]
        bs = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(4000)]
        return [round(float(x.mean()), r), [round(float(v), r) for v in np.percentile(bs, [2.5, 97.5])], int(len(x))]
    res = {"LEAK": "follow lists are Nov snapshots (undated); edges may postdate launch day: UPPER BOUND only",
           "days": test, "held_launches": int(len(pd.concat(pooled).query("variant == 'base'"))),
           "all_launches": int(P[(P["sub"] == "all") & (P.variant == "base")].n.sum()), "table": {}}
    Hp = pd.concat(pooled)
    for nm in V:
        g = Hp[Hp.variant == nm]
        res["table"][f"held pooled | {nm}"] = {"spearman_within_day_pct": round(float(spearmanr(g.ev_pct, g.v_pct).correlation), 3),
            **{f"recall_top{k}": [int(((g.v_rk <= k) & (g.ev_rk <= k)).sum()), int((g.v_rk <= k).sum())] for k in (3, 5, 10)},
            "mean_abs_rank_err": round(float((g.ev_rk - g.v_rk).abs().mean()), 2)}
    for sub in ("all",):
        for nm in V:
            Q = P[(P["sub"] == sub) & (P.variant == nm)]
            res["table"][f"{sub} | {nm}"] = {**{f"top{k}": b(Q[f"top{k}"]) for k in (3, 5, 10)}, "spearman": b(Q.sp, 3)}
        a = P[(P["sub"] == sub) & (P.variant == "fol")].set_index("day"); z = P[(P["sub"] == sub) & (P.variant == "base")].set_index("day")
        res["table"][f"{sub} | fol - base"] = {**{f"top{k}": b((a[f"top{k}"] - z[f"top{k}"]).values) for k in (3, 5, 10)}, "spearman": b((a.sp - z.sp).values, 3)}
    for nm in V:
        for grp, m in (("base_people", ~H.new), ("new_people", H.new)):
            g = H[(H.variant == nm) & m]
            if len(g):
                res["table"][f"person Hit@1 | {nm} | {grp}"] = b(g.hit1, 3)
    pv = H[~H.new].pivot_table(index=["day", "person"], columns="variant", values="hit1").dropna()
    res["table"]["person Hit@1 | fol - base | same base person-days"] = b((pv["fol"] - pv["base"]).values, 3)
    pd.concat(feats).to_parquet(f"{OUT}/launch_ev_fol.parquet")
    tf = pd.concat([D[d].groupby("id")[["held", "tcf", "ttot"]].first().reset_index().assign(day=d) for d in test])
    tf.merge(pd.concat(feats), on=["day", "id"], how="left").to_parquet(f"{OUT}/launch_feats.parquet")
    json.dump(res, open(os.path.join(HERE, "results", "team_fol_pilot.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    build() if sys.argv[1] == "build" else score()
