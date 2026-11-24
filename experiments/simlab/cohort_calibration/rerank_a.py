"""SIM-RERANK-1 Stage A (PREREG addendum 6). Aggregates only.
    python rerank_a.py <store dir> <out json> <day> [<day> ...]"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP
from pipeline import warehouse
ST, OUT = sys.argv[1:3]; DAYS = sys.argv[3:]; NS = int(os.environ.get('SHORTLIST', '20')); B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
CUTS = sorted(x.split("/")[-1][:10] for x in subprocess.run(["gsutil", "ls", f"{B}/tmp/e5/private/segments/"], capture_output=True, text=True).stdout.split() if x.endswith(".parquet") and "latest" not in x)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["rank"] = pd.to_numeric(W.daily_rank, errors="coerce"); RANK = dict(zip(W.id, W["rank"])); U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
LATE = {}
def feats(D):
    raw = gcat(f"{B}/tmp/e5/private/backer_pred_v2/{D}.parquet"); fc = gcat(f"{B}/results/structural/backtest/{D}.json")
    if not raw or not fc: return None
    L = pd.read_parquet(io.BytesIO(raw)); L["launch_id"] = L.launch_id.astype(str)
    start = PP.close_utc(D) - pd.Timedelta(days=1); d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    H = U[(U.lday < D) & (U.lday >= d30) & (U.ft < start)]
    act = (H.groupby("person_id").lday.nunique() / 30.0).to_dict()
    cut = max([c for c in CUTS if c <= D] or [CUTS[0]]); G = pd.read_parquet(io.BytesIO(gcat(f"{B}/tmp/e5/private/segments/{cut}.parquet"))).set_index("person_id").group.to_dict()
    hg = H.assign(g=H.person_id.map(G), r=H.target_id.map(RANK)).dropna(subset=["g"])
    allsh = hg.g.value_counts(normalize=True); topsh = hg[hg.r <= 3].g.value_counts(normalize=True)
    prone = {g for g in allsh.index if topsh.get(g, 0) >= 1.1 * allsh[g]}
    L["a"] = L.person_id.map(act).fillna(0.0); L["prone"] = L.person_id.map(G).isin(prone)
    sm = json.loads(gcat(f"{B}/tmp/e5/private/backer_pred_v2/{D}_launch_sums.json") or b'{"launches": {}}')["launches"]
    F = L.groupby("launch_id").apply(lambda x: pd.Series({"F1": x.p.sum(), "F2": (x.p * x.a).sum(), "F3": x.p[x.prone].sum()}))
    fj = json.loads(fc); LATE[D] = len(set(W[(W.day == D) & (W["rank"] <= 10)].id) - {str(x["id"]) for x in fj["launches"]}); S = pd.DataFrame(fj["launches"]).rename(columns={"id": "lid", "structural_rank": "srank"})[["lid", "srank"]]; S["lid"] = S.lid.astype(str)
    F["F4"] = [sm.get(l, {}).get("expected_voters_full_pool", 0.0) for l in F.index]; F["F5"] = [sm.get(l, {}).get("expected_voters_active7", 0.0) for l in F.index]
    S = S.sort_values("srank").head(NS).copy(); S = S.join(F, on="lid").fillna(0.0); S["final"] = S.lid.map(RANK)
    S["day"] = D; S["prone_groups"] = str(sorted(int(g) for g in prone)); return S
def z(v): v = np.asarray(v, float); return (v - v.mean()) / (v.std() + 1e-9)
def order(S, w, f): return S.assign(sc=z(-S.srank) + w * z(np.log1p(S[f])) if w else -S.srank).sort_values("sc", ascending=False).lid.tolist()
def caps(S, ordl):
    real = S.dropna(subset=["final"]).sort_values("final"); out = {}
    for k in (3, 5, 10):
        rk = set(W[(W.day == S.day.iloc[0]) & (W["rank"] <= k)].id); out[k] = len(set(ordl[:k]) & rk) / k
    st3 = set(S.sort_values("srank").lid[:3]); top3 = set(W[(W.day == S.day.iloc[0]) & (W["rank"] <= 3)].id); new3 = set(ordl[:3])
    near = set(S[(S.srank >= 4) & (S.srank <= 6)].lid) & top3
    out["near_miss"] = len(near); out["near_recovered"] = len(near & new3); out["cost"] = len((st3 & top3) - new3); return out
DS = {D: feats(D) for D in DAYS}; DS = {d: v for d, v in DS.items() if v is not None}; days = sorted(DS)
GRID = [0, 0.1, 0.25, 0.5, 1, 2, 4]; rows = []; chosen = {}
for f in ("F1", "F2", "F3", "F4", "F5"):
    for i, D in enumerate(days):
        prev = days[:i]
        if len(prev) < 3: w = 0
        else: w = GRID[int(np.argmax([np.mean([np.mean([caps(DS[p], order(DS[p], g, f))[k] for k in (3, 5, 10)]) for p in prev]) for g in GRID]))]
        chosen.setdefault(f, {})[D] = w
        c = caps(DS[D], order(DS[D], w, f)); s = caps(DS[D], order(DS[D], 0, f))
        rows.append({"cand": f, "day": D, "w": w, **{f"c{k}": c[k] for k in (3, 5, 10)}, **{f"s{k}": s[k] for k in (3, 5, 10)}, "near_miss": c["near_miss"], "near_rec": c["near_recovered"], "cost": c["cost"]})
R = pd.DataFrame(rows)
def boot(df, col):
    d = sorted(df.day.unique()); bs = [pd.concat([df[df.day == z_] for z_ in rng.choice(d, len(d))])[col].mean() for _ in range(2000)]
    return [round(100 * float(df[col].mean()), 1), round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1), int(len(df))]
out = {"prereg": "PREREG.md addendum 6", "days": days, "shortlist size": NS, "structural source": "results/structural/backtest/<D>.json (PH agent, b9613465)", "real top-10 launches absent from the structural file (featured after 00:05; misses for both orders) per day": LATE,
       "labels": {d: ("v2 list walk-forward replay; 00:05 forecast as then published" if d >= "2026-11-08" else "v2 list built later as replay (upvote/follow history before the day); 00:05 forecast file re-written Nov 11") for d in days},
       "ceiling (share of real top k inside structural top 20)": {k: round(100 * float(np.mean([len(set(DS[d].lid) & set(W[(W.day == d) & (W['rank'] <= k)].id)) / k for d in days])), 1) for k in (3, 5, 10)},
       "candidates": {}}
for f, x in R.groupby("cand"):
    x = x.copy()
    for k in (3, 5, 10): x[f"d{k}"] = x[f"c{k}"] - x[f"s{k}"]
    out["candidates"][{"F1": "expected held voters", "F2": "propensity-weighted expected voters", "F3": "expected voters in top-3-prone groups", "F4": "expected voters, full held pool (no list truncation)", "F5": "expected voters, full pool, active last 7 days"}[f]] = {
        **{f"top{k} capture structural": boot(x, f"s{k}") for k in (3, 5, 10)}, **{f"top{k} capture re-ranked": boot(x, f"c{k}") for k in (3, 5, 10)},
        **{f"top{k} re-ranked minus structural (paired)": boot(x, f"d{k}") for k in (3, 5, 10)},
        "near-miss launches (structural 4-6 that finished top 3)": int(x.near_miss.sum()), "recovered into top 3": int(x.near_rec.sum()), "cost: real top 3 pushed out": int(x.cost.sum()),
        "blend weight by day (walk-forward)": chosen[f],
        "Nov 8-22 only: top3 / top5 minus structural": [boot(x[x.day >= "2026-11-08"], "d3"), boot(x[x.day >= "2026-11-08"], "d5")]}
out["exploratory (NOT a test): fixed-w paired top3/top5 minus structural over all days"] = {f: {str(g): [round(100 * float(np.mean([caps(DS[d], order(DS[d], g, f))[k] - caps(DS[d], order(DS[d], 0, f))[k] for d in days])), 1) for k in (3, 5)] for g in GRID[1:]} for f in ("F1", "F2", "F3", "F4", "F5")}
json.dump(out, open(OUT, "w"), indent=1, default=str); print(json.dumps(out, indent=1, default=str))
