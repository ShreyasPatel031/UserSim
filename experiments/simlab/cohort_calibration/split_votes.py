"""E5-SPLIT (orchestrator 04:52Z Nov 23, asked by Shreyas): where each launch's real votes come from.
Per launch: displayed PH votes split into (a) held people the frozen backer list named (top N within the observed held population, N = observed held backers),
(b) held people it did not name, (c) votes not observed among held people (not held, or held but not re-read after the close).
Observed held population = complete people held before the day's start AND re-read after the day's close (only they show whether they voted).
Baseline on the same N and population: the N most active (upvotes on launches in the 30 days before D, read before the day's start).
    python split_votes.py <store dir> <out json> <day> [<day> ...]"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP
from pipeline import warehouse
ST, OUT = sys.argv[1:3]; DAYS = sys.argv[3:]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); COMPLETE = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["votes"] = pd.to_numeric(W.votes, errors="coerce"); W["rank"] = pd.to_numeric(W.daily_rank, errors="coerce"); U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
first = U.groupby("person_id").ft.min(); last = U.groupby("person_id").ft.max()
FROZEN = {"2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"}   # written live on the day (inputs cut 00:00 PT); Nov 8-13 = as-of replays written Nov 14
rows = []
for D in DAYS:
    raw = gcat(f"{B}/tmp/e5/private/backer_pred/{D}.parquet")
    if not raw: continue
    L = pd.read_parquet(io.BytesIO(raw)); L["launch_id"] = L.launch_id.astype(str)
    close = PP.close_utc(D); start = close - pd.Timedelta(days=1); d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    pop = {p for p in COMPLETE if first.get(p, close) < start and last.get(p, start) > close}
    if not pop: continue
    act = U[(U.lday < D) & (U.lday >= d30) & (U.ft < start) & U.person_id.isin(pop)].person_id.value_counts()
    act = act.reindex(sorted(pop)).fillna(0).sort_values(ascending=False, kind="stable")
    V = U[(U.lday == D) & U.person_id.isin(pop)].groupby("target_id").person_id.agg(set).to_dict()
    for lid, g in L.groupby("launch_id"):
        votes = W.loc[W.id == lid, "votes"]; rank = W.loc[W.id == lid, "rank"]
        if votes.empty or pd.isna(votes.iloc[0]) or votes.iloc[0] <= 0: continue
        real = V.get(lid, set()); n = len(real); tot = float(votes.iloc[0])
        if n == 0: rows.append({"day": D, "lid": lid, "votes": tot, "rank": (float(rank.iloc[0]) if not rank.empty and pd.notna(rank.iloc[0]) else np.nan), "n": 0, "a": 0.0, "b": 0.0, "c": 1.0, "rec_m": np.nan, "rec_b": np.nan, "frozen": D in FROZEN}); continue
        named = list(g[g.person_id.isin(pop)].sort_values("p", ascending=False).person_id.head(n)); base = list(act.index[:n])
        hit = len(set(named) & real); hb = len(set(base) & real); n_eff = min(n, tot)
        rows.append({"day": D, "lid": lid, "votes": tot, "rank": (float(rank.iloc[0]) if not rank.empty and pd.notna(rank.iloc[0]) else np.nan), "n": n, "a": hit / tot, "b": (n_eff - hit) / tot if n_eff >= hit else 0.0, "c": max(0.0, 1 - n_eff / tot),
                     "rec_m": hit / n, "rec_b": hb / n, "frozen": D in FROZEN, "pop": len(pop)})
R = pd.DataFrame(rows)
def boot(df, f):
    d = sorted(df.day.unique())
    if not d: return None
    bs = [f(pd.concat([df[df.day == z] for z in rng.choice(d, len(d))])) for _ in range(2000)]
    return [round(float(f(df)), 4), round(float(np.nanpercentile(bs, 2.5)), 4), round(float(np.nanpercentile(bs, 97.5)), 4), int(len(df)), len(d)]
vw = lambda k: (lambda x: float((x[k] * x.votes).sum() / x.votes.sum()))
def block(df):
    s = df.dropna(subset=["rec_m"])
    return {"launches": int(len(df)), "days": int(df.day.nunique()), "observed held population median": int(df["pop"].median()) if "pop" in df and df["pop"].notna().any() else None,
            "(a) held, named by the frozen list": boot(df, vw("a")), "(b) held, not named": boot(df, vw("b")), "(c) not observed among held (not held, or held and not re-read)": boot(df, vw("c")),
            "recall@N model (vote-weighted)": boot(s, lambda x: float((x.rec_m * x.n).sum() / x.n.sum())), "recall@N most-active baseline (vote-weighted)": boot(s, lambda x: float((x.rec_b * x.n).sum() / x.n.sum())),
            "model minus baseline (paired by day)": boot(s, lambda x: float(((x.rec_m - x.rec_b) * x.n).sum() / x.n.sum()))}
out = {"experiment": "E5-SPLIT v1", "days": sorted(R.day.unique()), "note": "[value, day-bootstrap 2.5%, 97.5%, launches, days]; shares are vote-weighted means of per-launch shares of displayed PH votes; recall@N weighted by N",
       "definitions": __doc__.split("\n")[1:5],
       "all launches": block(R), "top-3 launches": block(R[R["rank"] <= 3]),
       "frozen-on-the-day days only (Nov 14+)": {"all": block(R[R.frozen]), "top-3": block(R[R.frozen & (R["rank"] <= 3)])},
       "per_day": R.groupby("day").apply(lambda x: {"launches": int(len(x)), "observed_held_pop": int(x["pop"].max()) if x["pop"].notna().any() else 0, "held_backers": int(x.n.sum()), "displayed_votes": int(x.votes.sum()),
                                                    "a": round(float((x.a * x.votes).sum() / x.votes.sum()), 4), "recall_model": round(float(x.dropna(subset=['rec_m']).pipe(lambda s: (s.rec_m * s.n).sum() / max(1, s.n.sum()))), 3),
                                                    "recall_baseline": round(float(x.dropna(subset=['rec_b']).pipe(lambda s: (s.rec_b * s.n).sum() / max(1, s.n.sum()))), 3), "frozen": bool(x.frozen.iloc[0])}).to_dict(),
       "leak checks": {"predictions": "tmp/e5/private/backer_pred/<D>.parquet only (inputs cut at 00:00 PT of D; Nov 8-13 are as-of replays written Nov 14, Nov 14+ written on the day)",
                       "held": "complete in the store with a read before the day's start", "truth": "upvotes on D's launches by people re-read after D's close; displayed votes from the warehouse (final)",
                       "baseline": "upvotes on launches in the 30 days before D, read before the day's start"}}
json.dump(out, open(OUT, "w"), indent=1, default=str); print(json.dumps({k: v for k, v in out.items() if k not in ("per_day", "definitions", "leak checks")}, indent=1, default=str))
