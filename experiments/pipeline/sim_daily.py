"""The person simulation for one day, live (step `simforecast` of pipeline.daily). It scores every person active in the 30
days before the day on every launch in the day's line-up with the backtested person model (simlab.popscore TIE2=1,
no page inputs: the live pipeline has no page scores, the same as the live launch model), and sums the choices per
launch. Output rows have the same columns as the backtest's pnx_features.json, so the launch-level simulation
forecast (ph_predict/sim_forecast.py) can train on backtest days and predict today.

Inputs, all dated before the day:
  people, launches, events   the warehouse (not the frozen simlab store), so new launches and comments are included.
                             Upvotes stop at the newest upvote fetch (Oct 29 until the signed-in refresh lands).
  embeddings                 ph_predict/data/sim_live/emb.npz = the backtest's emb.npz plus every newer launch, encoded
                             the same way (bge-small, "name. tagline. description[:600]").
  person model               ph_predict/data/sim_models/model_<month>.pkl (trained on the previous month); if the
                             month's model is missing, the newest earlier one, and the log says which.
usage: python -m pipeline.sim_daily <YYYY-MM-DD>   -> ph_predict/data/sim_live/pnx_<day>.json, prints timing"""
import glob, json, os, shutil, sys, time
os.environ.setdefault("TIE2", "1")   # popscore reads its flags at import
for k in ("PAGE", "TASTE", "HERD", "PRESENCE", "TWIN", "COMP", "RECIP", "UPV_LAG"):
    os.environ.pop(k, None)
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.join(os.path.dirname(HERE), "ph_predict")
LIVE = os.environ.get("SIM_LIVE", os.path.join(PH, "data", "sim_live"))        # outputs (override for dry runs)
MODELS = os.environ.get("SIM_MODELS", os.path.join(PH, "data", "sim_models"))


def frames(d):
    """(people, items, events) in the simlab store's shape, from the warehouse, as known before day d."""
    from . import warehouse as W
    con = W.connect()
    I = con.execute(f"""SELECT CAST(id AS VARCHAR) AS id, slug, day, name, tagline, coalesce(description, '') AS description,
                               coalesce(topics, '[]') AS topics, poster, coalesce(makers, '[]') AS makers
                        FROM launches WHERE day <= '{d}'""").df()
    E = con.execute(f"""SELECT DISTINCT person, CAST(launch_id AS VARCHAR) AS item, date, kind FROM events
                        WHERE date < '{d}' AND person IS NOT NULL AND person <> '[REDACTED]'""").df()
    E = E[E.item.isin(set(I.id))]
    P = con.execute("SELECT DISTINCT person FROM people").df().assign(follows="[]")
    return P, I, E


def embeddings(I):
    """The backtest's launch vectors plus vectors for every launch they lack (encoded here, same model and text)."""
    os.makedirs(LIVE, exist_ok=True)
    src = os.path.join(LIVE, "emb.npz") if os.path.exists(os.path.join(LIVE, "emb.npz")) else os.path.join(PH, "data", "emb.npz")
    Z = dict(np.load(src))
    have = set(map(str, Z["launch_ids"]))
    new = I[~I.id.isin(have)]
    if len(new):
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
        txt = [f"{r.name}. {r.tagline}. {(r.description or '')[:600]}" for r in new.itertuples()]
        V = m.encode(txt, batch_size=64, normalize_embeddings=True, show_progress_bar=False).astype(np.float32)
        Z["launch_ids"] = np.concatenate([Z["launch_ids"].astype(str), new.id.values.astype(str)])
        Z["launch"] = np.vstack([Z["launch"], V])
        np.savez(os.path.join(LIVE, "emb.npz"), **Z)
    return len(new)


def model_for(d):
    want = f"model_{d[:7]}.pkl"
    have = sorted(os.path.basename(p) for p in glob.glob(f"{MODELS}/model_*.pkl") if os.path.basename(p) <= want)
    if not have:
        raise RuntimeError(f"no person model in {MODELS} for {d}")
    return have[-1]


def run(d):
    t0 = time.time(); log = {"day": d}
    P, I, E = frames(d)
    log.update(launches_today=int((I.day == d).sum()), events=len(E), newest_upvote=E[E.kind == "upvote"].date.max(),
               newest_comment=E[E.kind == "comment"].date.max())
    if not log["launches_today"]:
        raise RuntimeError(f"no launches for {d} in the warehouse")
    log["embedded_new"] = embeddings(I); log["t_inputs_s"] = round(time.time() - t0, 1)
    from simlab import store, harness, popscore as PS
    store.RAW = LIVE                                   # emb.npz and outputs live apart from the backtest files
    store.load = lambda: (P, I, E)
    harness.baseline = lambda: pd.DataFrame({"id": I.id, "day": I.day, "base": 0.5})   # line-ups only; `pop` is not a person-model input
    PS.WORK = os.path.join(LIVE, "work"); os.makedirs(PS.WORK, exist_ok=True)
    m = model_for(d); log["person_model"] = m
    shutil.copy(os.path.join(MODELS, m), os.path.join(PS.WORK, f"model_{d[:7]}.pkl"))
    out = os.path.join(PS.WORK, f"day_{d}.parquet")
    if os.path.exists(out):
        os.remove(out)
    PS.load()
    _, n = PS.score_day(d)
    S = pd.read_parquet(out).rename(columns=lambda c: "pnx_" + c[4:] if c.startswith("psn_") else c)
    cols = [c for c in S if c.startswith("pnx_")]
    rows = {str(r["id"]): {c: float(r[c]) for c in cols} for r in S.to_dict("records")}
    json.dump(rows, open(os.path.join(LIVE, f"pnx_{d}.json"), "w"))
    log.update(person_launch_rows=int(n), launches_scored=len(rows), seconds=round(time.time() - t0, 1))
    print(json.dumps(log), flush=True)
    return log


if __name__ == "__main__":
    run(sys.argv[1])
