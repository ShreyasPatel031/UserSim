"""Paired backtest (orchestrator, Nov 10 18:45Z): the live person simulation (pipeline.sim_daily: TIE2 person model, no page
inputs) fed with the warehouse people data (as deployed: upvotes up to Nov 3) vs the same plus store_v3's COMPLETE people.

Variants (one event table each, rows person / item / date / kind):
  wh   warehouse events (kind upvote / comment), as pipeline.sim_daily.frames reads them
  v3   wh + store_v3 events of persons with complete=True (kind upvote / comment on known launches). A store person is keyed
       by handle when the handle is known (so a warehouse person and the same store person merge), else by salted id.
       Dates follow the warehouse convention: an upvote is dated on the launch's day (warehouse: 233k of 235k upvotes);
       a comment on its own timestamp when exact / bounded / day quality, else on the launch's day.
Honesty: for each test day d only events dated before d enter (as in sim_daily); the person model is the live
model_2026-11.pkl (trained on October), so only November days are honest test days (an October test needs a
September-trained TIE2 model, not on disk).
Score: within each day, launches ranked by the simulation's expected votes (pnx_ev) vs final daily_rank: top 3/5/10 hits,
paired bootstrap over days (10,000). Weekly: ISO weeks fully inside the scored days, ranked by pnx_ev vs weekly_rank.
usage: python sim_v3_backtest.py prepare | day <variant> <d> | score [d0 d1]    (counts only; no usernames printed)"""
import glob, hashlib, json, os, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(HERE); sys.path.insert(0, EXP)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
WORK = os.environ.get("SIMBT", os.path.join(tempfile.gettempdir(), "simbt"))
MODEL = os.environ.get("SIMBT_MODEL", os.path.join(WORK, "models", "model_2026-11.pkl"))
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range(os.environ.get("D0", "2026-11-01"), os.environ.get("D1", "2026-11-09"))]


def sh(*a, check=False):
    return subprocess.run(list(a), capture_output=True, text=True, check=check)


def hid(sl, u):
    return "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]


def prepare():
    from pipeline import warehouse as W
    con = W.connect()
    I = con.execute("""SELECT CAST(id AS VARCHAR) AS id, slug, day::VARCHAR AS day, name, tagline, coalesce(description, '') AS description,
                       coalesce(topics, '[]') AS topics, poster, coalesce(makers, '[]') AS makers FROM launches""").df()
    E = con.execute("""SELECT DISTINCT lower(person) AS person, CAST(launch_id AS VARCHAR) AS item, date, kind FROM events
                       WHERE kind IN ('upvote', 'comment') AND person IS NOT NULL AND person <> '[REDACTED]'""").df()
    E = E[E.item.isin(set(I.id))]
    people = set(con.execute("SELECT DISTINCT lower(person) AS p FROM people").df().p)
    sl = sh("gsutil", "cat", f"{B}/raw/population/_salt", check=True).stdout.strip()
    tmp = tempfile.mkdtemp(prefix="simbt_")
    for f in ("events", "persons"):
        sh("gsutil", "-q", "cp", f"{B}/raw/population/store_v3/{f}.parquet", tmp, check=True)
    Pv = pd.read_parquet(f"{tmp}/persons.parquet")
    comp = set(Pv[Pv.complete.astype(bool)].person_id)
    V = pd.read_parquet(f"{tmp}/events.parquet", columns=["person_id", "kind", "target_id", "ts_hi", "ts_quality"])
    V = V[V.kind.isin(["upvote", "comment"]) & V.person_id.isin(comp)].copy()
    V["item"] = V.target_id.astype(str); V = V[V.item.isin(set(I.id))]
    lday = dict(zip(I.id, I.day))
    own = V.ts_quality.isin(["exact", "bounded", "day"]) & (V.kind == "comment")
    V["date"] = np.where(own, V.ts_hi.dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d"), V.item.map(lday))
    names = people | set(E.person)
    r = sh("gsutil", "cat", f"{B}/raw/_babysitter/quality/latest_complete.txt")
    names |= {l.split("\t")[0].strip().lower() for l in r.stdout.splitlines() if l.strip()}
    h2u = {hid(sl, u): u for u in names if u}
    V["person"] = V.person_id.map(h2u).fillna(V.person_id)
    E3 = pd.concat([E, V[["person", "item", "date", "kind"]]]).drop_duplicates(["person", "item", "kind"])
    os.makedirs(WORK, exist_ok=True)
    I.to_parquet(f"{WORK}/items.parquet"); E.to_parquet(f"{WORK}/events_wh.parquet"); E3.to_parquet(f"{WORK}/events_v3.parquet")
    pd.DataFrame({"person": sorted(people)}).to_parquet(f"{WORK}/people_wh.parquet")
    rep = {"items": len(I), "wh_events": len(E), "wh_people": int(E.person.nunique()), "v3_complete_persons": len(comp),
           "v3_added_events": int(len(E3) - len(E)), "v3_events": len(E3), "v3_people": int(E3.person.nunique()),
           "v3_store_people_mapped_to_handle": int(V.person.ne(V.person_id).sum() and V[V.person != V.person_id].person_id.nunique()),
           "newest_upvote": {"wh": E[E.kind == "upvote"].date.max(), "v3": E3[E3.kind == "upvote"].date.max()}}
    json.dump(rep, open(f"{WORK}/prepare.json", "w"), indent=1); print(json.dumps(rep))


def day(variant, d):
    os.environ["TIE2"] = "1"
    for k in ("PAGE", "TASTE", "HERD", "PRESENCE", "TWIN", "COMP", "RECIP", "UPV_LAG"):
        os.environ.pop(k, None)
    I = pd.read_parquet(f"{WORK}/items.parquet"); I = I[I.day <= d]
    E = pd.read_parquet(f"{WORK}/events_{variant}.parquet"); E = E[(E.date < d) & E.item.isin(set(I.id))]
    P = pd.DataFrame({"person": sorted(set(pd.read_parquet(f"{WORK}/people_wh.parquet").person) | set(E.person))}).assign(follows="[]")
    from simlab import store, harness, popscore as PS
    live = os.path.join(WORK, "live"); store.RAW = live
    store.load = lambda: (P, I, E)
    harness.baseline = lambda: pd.DataFrame({"id": I.id, "day": I.day, "base": 0.5})
    PS.WORK = os.path.join(WORK, f"work_{variant}_{d}"); os.makedirs(PS.WORK, exist_ok=True)
    shutil.copy(MODEL, os.path.join(PS.WORK, f"model_{d[:7]}.pkl"))
    out = os.path.join(PS.WORK, f"day_{d}.parquet")
    if os.path.exists(out):
        os.remove(out)
    PS.load(); _, n = PS.score_day(d)
    S = pd.read_parquet(out); S["variant"] = variant
    os.makedirs(f"{WORK}/scores", exist_ok=True); S.to_parquet(f"{WORK}/scores/{variant}_{d}.parquet")
    print(json.dumps({"variant": variant, "day": d, "events": len(E), "people": len(P), "rows": int(n), "launches": len(S)}))


def boot(x, rng, n=10000):
    x = np.asarray(x, float)
    if len(x) < 2:
        return [round(float(x.mean()), 1) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 1), [round(float(v), 1) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def score(d0=None, d1=None):
    from pipeline import warehouse as W
    S = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{WORK}/scores/*.parquet")])
    S["id"] = S.id.astype(str)
    if d0:
        S = S[(S.day >= d0) & (S.day <= (d1 or d0))]
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank, weekly_rank FROM launches WHERE daily_rank IS NOT NULL")
    S = S.merge(L, on="id")
    days = sorted(set(S[S.variant == "wh"].day) & set(S[S.variant == "v3"].day))
    rng = np.random.default_rng(0); res = {"days": days, "metric": "pnx_ev (psn_ev) rank vs final rank"}
    for k in (3, 5, 10):
        a, b = [], []
        for d in days:
            g = S[S.day == d]; top = set(g[g.daily_rank <= k].id)
            if len(top) < k:
                continue
            ga, gb = g[g.variant == "wh"], g[g.variant == "v3"]
            a.append(len(set(ga.nlargest(k, "psn_ev").id) & top) / k * 100); b.append(len(set(gb.nlargest(k, "psn_ev").id) & top) / k * 100)
        res[f"day top{k}"] = {"warehouse": round(float(np.mean(a)), 1) if a else None, "store_v3": round(float(np.mean(b)), 1) if b else None,
                              "delta": boot(np.array(b) - np.array(a), rng)}
    S["week"] = pd.to_datetime(S.day).dt.strftime("%G-W%V")
    full = [w for w, g in S.groupby("week") if g.day.nunique() == 7]
    wk = {}
    for w in full:
        g = S[S.week == w]
        for k in (3, 5, 10):
            top = set(g[g.weekly_rank <= k].id)
            ga, gb = g[g.variant == "wh"], g[g.variant == "v3"]
            wk[f"{w} top{k}"] = {"warehouse": len(set(ga.nlargest(k, "psn_ev").id) & top) / k * 100,
                                 "store_v3": len(set(gb.nlargest(k, "psn_ev").id) & top) / k * 100}
    res["weekly"] = wk or "no full ISO week in the scored days"
    res["monthly"] = "not enough November days for a monthly list"
    res["label"] = f"PROVISIONAL ({len(days)} days)"
    json.dump(res, open(os.path.join(HERE, "results", "sim_v3_backtest.json"), "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prepare":
        prepare()
    elif cmd == "day":
        day(sys.argv[2], sys.argv[3])
    else:
        score(*sys.argv[2:4])
