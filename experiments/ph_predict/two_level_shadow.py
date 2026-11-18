"""Daily shadow of the two-level person simulation, it8 = choice model on the cp_unc base (orchestrator Nov 11 02:05Z:
log its EV beside the launch model, no ranking change). Runs on usersim-exp-1 after 01:00 PT, outside the pipeline;
writes only to gs://.../usersim_sim/results/shadow_it8/.

Steps for day d (default: today in PT), all from data known before d plus d's line-up (warehouse launches, written by the
00:05 PT run):
  items      warehouse launches -> items.parquet; line-up of d must have >= 5 launches, else stop
  emb        launch vectors for launches the cache lacks (bge-small, the same text as the backtest)
  store      store_v3 events/persons -> events_cp (complete people, salted ids); tabs -> tabs_v3 (label filter)
  model      cp_unc person model for d's month (trained on the previous month if missing)
  X          feature rows for every previous-month day missing them (choice-model fits), then for d
  choice     A x K x S parts fitted on the previous month, scored on d -> EV per launch
  publish    ev_<d>.parquet (id, ev, ev_rank, lm_rank if the forecast exists) + ev_<d>.json (counts and timings)
usage: SIMBT=~/tl_shadow python two_level_shadow.py [YYYY-MM-DD]   (counts only; no handles)"""
import glob, json, os, subprocess, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.setdefault("SIMBT", os.path.expanduser("~/tl_shadow"))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
OUT = f"{B}/results/shadow_it8"
PY = sys.executable


def run(*args, env=None):
    t = time.time()
    r = subprocess.run([PY, os.path.join(HERE, "two_level.py"), *args], capture_output=True, text=True,
                       env={**os.environ, **(env or {})}, cwd=HERE)
    if r.returncode:
        raise RuntimeError(f"two_level {' '.join(args)} failed: {r.stderr[-2000:]}")
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", round(time.time() - t, 1)


def items():
    sys.path.insert(0, os.path.dirname(HERE))
    from pipeline import warehouse as W
    I = W.query("""SELECT CAST(id AS VARCHAR) AS id, slug, day::VARCHAR AS day, name, tagline, coalesce(description, '') AS description,
                   coalesce(topics, '[]') AS topics, poster, coalesce(makers, '[]') AS makers FROM launches""")
    I.to_parquet(f"{WORK}/items.parquet")
    return I


def embed(I):
    os.makedirs(f"{WORK}/live", exist_ok=True)
    p = f"{WORK}/live/emb.npz"
    Z = dict(np.load(p))
    have = set(map(str, Z["launch_ids"])); new = I[~I.id.isin(have)]
    if len(new):
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
        V = m.encode([f"{r.name}. {r.tagline}. {(r.description or '')[:600]}" for r in new.itertuples()], batch_size=64,
                     normalize_embeddings=True, show_progress_bar=False).astype(np.float32)
        Z["launch_ids"] = np.array([str(x) for x in Z["launch_ids"]] + list(new.id), dtype=str)
        Z["launch"] = np.vstack([Z["launch"], V]); np.savez(p, **Z)
    return int(len(new))


def main(d):
    t0 = time.time(); log = {"day": d, "steps": {}}
    os.makedirs(WORK, exist_ok=True)
    I = items(); log["lineup"] = int((I.day == d).sum())
    if log["lineup"] < 5:
        raise SystemExit(f"line-up for {d} not in the warehouse yet ({log['lineup']} launches)")
    log["embedded_new"] = embed(I)
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/population/store_v3/tabs.parquet", f"{WORK}/tabs_v3.parquet"], check=True)
    log["steps"]["prepare"] = run("prepare")
    unc = {"TL_TAG": "cp_unc", "TL_UNCOND": "1"}
    mon = d[:7]; prev = (pd.Timestamp(d[:7] + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
    for m in (prev, mon):
        if not os.path.exists(f"{WORK}/models_tl_cp_unc/model_{m}.pkl"):
            log["steps"][f"train_{m}"] = run("train", m, env=unc)
    days_prev = pd.date_range(prev + "-01", periods=pd.Period(prev).days_in_month).strftime("%Y-%m-%d")
    missing = [x for x in days_prev if not os.path.exists(f"{WORK}/rows_tl_cp_unc/X_{x}.parquet")]
    for x in missing:   # backfill the previous month's feature rows (the choice parts are fitted on them)
        run("day", x, env=unc)
    log["backfilled_days"] = len(missing)
    log["steps"]["day"] = run("day", d, env=unc)
    log["steps"]["choice"] = run("choice", env={"TL_TAG": "cp_choice", "TL_BASE": "cp_unc", "TL_FROM": d, "TL_TO": d})
    R = pd.read_parquet(f"{WORK}/rows_tl_cp_choice/{d}.parquet")
    ev = R.assign(e=R.w * R.p).groupby("id").e.sum().rename("ev").reset_index()
    ev["ev_rank"] = ev.ev.rank(ascending=False, method="first").astype(int)
    try:
        sys.path.insert(0, os.path.dirname(HERE))
        from pipeline import warehouse as W
        F = W.query(f"SELECT CAST(launch_id AS VARCHAR) AS id, predicted_rank AS lm_rank FROM forecasts WHERE model = 'launch_model' AND forecast_date = '{d}'", do_sync=False)
        ev = ev.merge(F, on="id", how="left")
    except Exception as e:   # the shadow never depends on the forecast; it is only logged beside it
        log["lm_join_error"] = str(e)[:200]
    ev["day"] = d
    loc = f"{WORK}/ev_{d}.parquet"; ev.to_parquet(loc, index=False)
    log.update(launches_scored=int(len(ev)), people=int(R.person.nunique()), rows=int(len(R)),
               lm_matched=int(ev["lm_rank"].notna().sum()) if "lm_rank" in ev else 0, seconds=round(time.time() - t0, 1))
    log["written_at"] = pd.Timestamp.now(tz="UTC").isoformat()   # E5: provably written before d's outcomes settle
    json.dump(log, open(f"{WORK}/ev_{d}.json", "w"), indent=1, default=str)
    for f in (loc, f"{WORK}/ev_{d}.json"):
        subprocess.run(["gsutil", "-q", "cp", f, f"{OUT}/"], check=True)
    print(json.dumps({k: v for k, v in log.items() if k != "steps"}, default=str))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d"))
