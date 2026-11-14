"""03:45 hybrid replay by read-time band (orchestrator 15:36Z Nov 14). Frozen deployed weights (results/frozen/hybrid_vmonly_P345_20261114.json,
all-day fit on Nov 2-12); recorder reads (raw/vote_snapshots) at 01:00 / 02:00 / 03:00 PT (latest read <= T within 65 min); move = log pos
at 01:00 minus at T; nc = log1p recorder comments; clean = 00:05 parquet pred. Lines: hybrid (hidden top 5 + ridge 6+), hidden rank alone,
00:05 model alone (pred), ridge alone (hr_clean-vm), slots6 by the 00:05 prior. Truth dailyRank, >= 10 ranked rule. Counts only.
usage: python3 hybrid_bands.py <first day> <last day> <out.json>"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [os.path.dirname(HERE), HERE]
from pipeline import warehouse as W
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
Wt = json.load(open(f"{HERE}/results/frozen/hybrid_vmonly_P345_20261114.json"))["coef"]
R = W.query("SELECT CAST(id AS VARCHAR) id, CAST(day AS VARCHAR) AS d, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False).rename(columns={"d": "day"})
TWn = pd.read_parquet(f"{HERE}/results/tw_nosite.parquet"); TWn["id"] = TWn.id.astype(str)
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
out = {}
for d in pd.date_range(sys.argv[1], sys.argv[2]).strftime("%Y-%m-%d"):
    txt = subprocess.run(["gsutil", "cat", f"{B}/raw/vote_snapshots/{d}.jsonl"], capture_output=True, text=True).stdout
    if not txt.strip(): continue
    V = pd.DataFrame([json.loads(l) for l in txt.splitlines() if l.strip()]); V["launch_id"] = V.launch_id.astype(str)
    V["a"] = pd.to_datetime(V["at"], utc=True); V = V.drop_duplicates(["launch_id", "at"]).dropna(subset=["rank_now"])
    fc = tempfile.mkdtemp() + "/f.parquet"; subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", fc], capture_output=True)
    if os.path.exists(fc):
        F = pd.read_parquet(fc); F["id"] = F.id.astype(str); src = "parquet"
    else:   # as hybrid_vmonly.py: month-fold clean_nosite stand-in where the 00:05 parquet is absent (Nov 5-7)
        F = TWn[TWn.id.isin(set(V.launch_id))].rename(columns={"clean_v3_nosite": "pred"}); src = "tw_nosite stand-in"
    pr = dict(zip(F.id, F.pred))
    truth = R[R.day == d].sort_values("daily_rank").id.tolist()
    if len(truth) < 10: continue
    t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
    def at(h):
        T = t0 + pd.Timedelta(hours=h); s = V[(V.a <= T + pd.Timedelta(seconds=90)) & (V.a >= T - pd.Timedelta(minutes=65)) & (V.a >= t0 - pd.Timedelta(minutes=5))]
        return s.sort_values("a").groupby("launch_id").last() if len(s) else None
    s1 = at(1.0); out[d] = {"n_ranked": len(truth), "clean_src": src}
    for band, h in (("01", 1.0), ("02", 2.0), ("03", 3.0)):
        sT = at(h)
        if sT is None: continue
        ids = list(sT.index); pos = sT.rank_now.rank(method="first"); hid = sorted(ids, key=lambda i: (pos[i], i))
        pos1 = (s1.rank_now.reindex(ids).fillna(999) if s1 is not None else pd.Series(999, index=ids)).rank(method="first")
        Z = pd.DataFrame({"lpos": np.log(pos), "move": np.log(pos1) - np.log(pos), "nc_rec": np.log1p(sT.comments.fillna(0).astype(float))}, index=ids)
        Z["clean"] = Z.index.map(pr).astype(float); Z["clean"] = Z.clean.fillna(Z.clean.min() - 0.1)
        sc = sum(zf(Z[f.replace("z_", "")]) * c for f, c in Wt.items())
        hyb = hid[:5] + [i for i in sc.sort_values(ascending=False).index if i not in set(hid[:5])]
        s6 = hid[:5] + [i for i in Z.clean.sort_values(ascending=False).index if i not in set(hid[:5])]
        out[d][band] = {"read": sT.a.max().tz_convert("America/Los_Angeles").strftime("%H:%M"), "launches": len(ids),
                        "hybrid": hits(hyb, truth), "hidden": hits(hid, truth), "ridge": hits(list(sc.sort_values(ascending=False).index), truth),
                        "slots6_prior": hits(s6, truth)}
    out[d]["model_0005"] = hits(F.sort_values(["pred", "id"], ascending=[False, True]).id.tolist(), truth)
json.dump(out, open(sys.argv[3], "w"), indent=1)
rng = np.random.default_rng(0)
for band in ("01", "02", "03"):
    for sub, days in (("all", [d for d in out if band in out[d]]), ("outside fit (Nov 13+)", [d for d in out if band in out[d] and d > "2026-11-12"])):
        if not days: continue
        line = f"band {band}:00 {sub} n={len(days)}: "
        for k in ("hybrid", "hidden", "ridge", "slots6_prior"):
            a = np.array([out[d][band][k] for d in days]); line += f"{k} {a.mean(0).round(1).tolist()}; "
        a = np.array([out[d]["model_0005"] for d in days]); line += f"00:05 {a.mean(0).round(1).tolist()}"
        print(line)
    days = [d for d in out if band in out[d]]
    if len(days) > 1:
        x = np.array([np.array(out[d][band]["hybrid"]) - np.array(out[d][band]["hidden"]) for d in days]); bs = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
        print(f"  hybrid - hidden band {band}: " + " / ".join(f"{x[:, k].mean():+.1f} [{np.percentile(bs[:, k], 2.5):+.1f}, {np.percentile(bs[:, k], 97.5):+.1f}]" for k in range(3)))
