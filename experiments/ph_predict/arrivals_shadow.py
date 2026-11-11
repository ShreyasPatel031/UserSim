"""Forward shadow of the pre-registered arrivals-only EV (E5 row (b), Nov 11): for day d (default today PT), from inputs
known at 00:05 PT only. Run after two_level_shadow.py in the same SIMBT (it refreshes items / events_cp / tabs_v3).
  rows   arrivals.build(d, d) -> candidate rows for d's line-up (no labels yet)
  model  P_arr fitted on the previous month's candidate rows (no_dormant, label-filtered), cached per month; if the
         previous month's rows are missing they are built first
  EV     sum of P_arr over candidates with act_30 > 0 (no dormant rows: the decision variant)
  out    gs://.../results/shadow_arrivals/ev_<d>.parquet (id, arr_ev, arr_rank, cand_n) + ev_<d>.json (counts, written_at)
usage: SIMBT=<dir> python arrivals_shadow.py [YYYY-MM-DD]   (counts only)"""
import glob, json, os, pickle, subprocess, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"


def main(d):
    import arrivals as A
    import lightgbm as lgb
    mon = d[:7]; prev = (pd.Timestamp(mon + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
    mp = f"{A.OUT}/model_{mon}.pkl"
    if not os.path.exists(mp):
        days = pd.date_range(prev + "-01", periods=pd.Period(prev).days_in_month).strftime("%Y-%m-%d")
        miss = [x for x in days if not os.path.exists(f"{A.OUT}/{x}.parquet")]
        if miss:
            A.build(miss[0], miss[-1])
        T = pd.concat([pd.read_parquet(f"{A.OUT}/{x}.parquet") for x in days if os.path.exists(f"{A.OUT}/{x}.parquet")])
        T = T[T.lab_ok & (T.act_30 > 0)]
        m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=2).fit(T[A.PF + A.TF], T.y)
        pickle.dump(m, open(mp, "wb"))
    m = pickle.load(open(mp, "rb"))
    A.build(d, d)
    R = pd.read_parquet(f"{A.OUT}/{d}.parquet"); R = R[R.act_30 > 0]
    R["p"] = m.predict_proba(R[A.PF + A.TF])[:, 1]
    ev = R.groupby("id").agg(arr_ev=("p", "sum"), cand_n=("cand_n", "first")).reset_index()
    ev["arr_rank"] = ev.arr_ev.rank(ascending=False, method="first").astype(int); ev["day"] = d
    loc = f"{A.OUT}/ev_{d}.parquet"; ev.to_parquet(loc, index=False)
    log = {"day": d, "launches": int(len(ev)), "candidate_rows": int(len(R)), "model": os.path.basename(mp),
           "written_at": pd.Timestamp.now(tz="UTC").isoformat()}
    json.dump(log, open(f"{A.OUT}/ev_{d}.json", "w"))
    for f in (loc, f"{A.OUT}/ev_{d}.json"):
        subprocess.run(["gsutil", "-q", "cp", f, os.environ.get("SHADOW_OUT", f"{B}/results/shadow_arrivals/")], check=True)
    print(json.dumps(log))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d"))
