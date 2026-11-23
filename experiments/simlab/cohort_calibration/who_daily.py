"""Daily WHO line (cohort scorecard): published P3 topic-neighbour prior vs the 30-day base mix (shadow), against real held backers
(complete, held before the day's start, re-read after the close). Group labels: the segment cut in force on D. Aggregates only.
    python who_daily.py <store dir> <out json> <min backers> <day> [<day> ...]"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP
from pipeline import warehouse
ST, OUT, MINB = sys.argv[1], sys.argv[2], int(sys.argv[3]); DAYS = sys.argv[4:]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
CUTS = sorted(x.split("/")[-1][:10] for x in subprocess.run(["gsutil", "ls", f"{B}/tmp/e5/private/segments/"], capture_output=True, text=True).stdout.split() if x.endswith(".parquet") and "latest" not in x)
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete"]); COMPLETE = set(P[P.complete == True].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["rank"] = pd.to_numeric(W.daily_rank, errors="coerce"); U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
TOP = {i: set(json.loads(t) if isinstance(t, str) and t.startswith("[") else []) for i, t in zip(W.id, W.topics)}; RANK = dict(zip(W.id, W["rank"]))
first = U.groupby("person_id").ft.min(); last = U.groupby("person_id").ft.max()
def jsd(p, q):
    ks = sorted(set(p) | set(q)); a = np.array([p.get(k, 0) for k in ks], float); b = np.array([q.get(k, 0) for k in ks], float); a, b = a / a.sum(), b / b.sum(); m = (a + b) / 2
    kl = lambda x, y: np.sum(np.where(x > 0, x * np.log2(np.where(x > 0, x, 1) / np.where(y > 0, y, 1)), 0)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
rows, cov = [], {}
for D in DAYS:
    cut = max([c for c in CUTS if c <= D] or [CUTS[0]]); G = pd.read_parquet(io.BytesIO(gcat(f"{B}/tmp/e5/private/segments/{cut}.parquet"))).set_index("person_id").group.to_dict()
    close = PP.close_utc(D); start = close - pd.Timedelta(days=1); d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    obs = {p for p in COMPLETE if first.get(p, close) < start and last.get(p, start) > close}
    past = U[(U.lday < D) & (U.lday >= d30) & (U.ft < start)].assign(g=lambda x: x.person_id.map(G)).dropna(subset=["g"]); past["g"] = past.g.astype(int)
    base = past.g.value_counts(normalize=True).to_dict(); PM = {l: x.g.value_counts(normalize=True).to_dict() for l, x in past.groupby("target_id") if len(x) >= 5}
    real = U[(U.lday == D) & U.person_id.isin(obs)].assign(g=lambda x: x.person_id.map(G)).dropna(subset=["g"])
    cov[D] = {"observed_held_people": len(obs), "held_backer_rows": int(len(real)), "cut": cut}
    for lid, x in real.groupby("target_id"):
        if len(x) < MINB: continue
        mix = x.g.astype(int).value_counts(normalize=True).to_dict(); tp = TOP.get(lid, set()); acc, ws = {}, 0.0
        for l, m in PM.items():
            w = len(tp & TOP.get(l, set()))
            if w:
                ws += w
                for g, s in m.items(): acc[g] = acc.get(g, 0) + w * s
        p3 = {g: a / ws for g, a in acc.items()} if ws else base
        rows.append({"day": D, "n": len(x), "rank": RANK.get(lid), "jsd_base": jsd(base, mix), "jsd_p3": jsd(p3, mix), "top_share": max(mix.values())})
R = pd.DataFrame(rows); R["d"] = R.jsd_p3 - R.jsd_base
def boot(col, df):
    d = sorted(df.day.unique()); bs = [pd.concat([df[df.day == z] for z in rng.choice(d, len(d))])[col].mean() for _ in range(2000)]
    return [round(float(df[col].mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(df)), len(d)]
out = {"days": DAYS, "min_held_backers_per_launch": MINB, "coverage": cov, "launches_scored": int(len(R)),
       "JSD base (shadow)": boot("jsd_base", R) if len(R) else None, "JSD P3 (published)": boot("jsd_p3", R) if len(R) else None, "P3 minus base (paired)": boot("d", R) if len(R) else None,
       "per_day": R.groupby("day").agg(launches=("n", "size"), backers=("n", "sum"), jsd_base=("jsd_base", "mean"), jsd_p3=("jsd_p3", "mean")).round(3).reset_index().to_dict("records") if len(R) else [],
       "note": "[mean, day-bootstrap 2.5%, 97.5%, launches, days]; real mix = held complete backers re-read after close; target JSD <= 0.10"}
json.dump(out, open(OUT, "w"), indent=1, default=str); print(json.dumps(out, indent=1, default=str))
