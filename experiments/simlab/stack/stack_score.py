"""STACK-FWD-1 nightly score (PREREG addendum 14): the stack list vs the BACKER-v2 shadow, paired by launch, the north-star rule of
backer_score.py. Observed backers = people held before 00:00 PT of D and re-read after D's close whose own upvote list contains the launch;
both lists are ranked within the re-read people; recall@N with N = that launch's observed backers. Pooled over every scored launch of the
scored days; stack minus BACKER-v2 by launch bootstrap (2,000 draws, seed 0). Days start at 2026-11-27 (first forward stack list).
Aggregates only. Rule 5: paired interval below 0 at >= 7 scored live days -> restore BACKER-v2 as the published line.
    python stack_score.py <store dir> [first day] [last day]   ->  results/calibration/stack_fwd/score.json
"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pipeline import warehouse  # noqa: E402
import period_parts as PP  # noqa: E402  (close_utc)
ST = sys.argv[1]; FIRST = sys.argv[2] if len(sys.argv) > 2 else "2026-11-27"
LAST = sys.argv[3] if len(sys.argv) > 3 else (pd.Timestamp.now(tz="America/Los_Angeles") - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gp = lambda p: (lambda r: pd.read_parquet(io.BytesIO(r)) if r else None)(subprocess.run(["gsutil", "cat", p], capture_output=True).stdout)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id); last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str)
U["lday"] = U.target_id.map(dict(zip(W.id, W.day.astype(str).str[:10])))
rows, days = [], []
for D in [str(d)[:10] for d in pd.date_range(FIRST, LAST)]:
    S, V = gp(f"{B}/tmp/e5/private/backer_pred_stack/{D}.parquet"), gp(f"{B}/tmp/e5/private/backer_pred_v2/{D}.parquet")
    if S is None or V is None: days.append({"day": D, "status": "missing list"}); continue
    close = PP.close_utc(D); reread = set(last_read[last_read > close].index) & held
    frozen = set(first_read[first_read < close - pd.Timedelta(days=1)].index) & held
    obs = {k: v & frozen & reread for k, v in U[(U.lday == D) & U.person_id.isin(held)].groupby("target_id").person_id.agg(set).items()}
    n_day = 0
    for lid in sorted(set(S.launch_id.astype(str)) & set(V.launch_id.astype(str))):
        o = obs.get(lid, set()); n = len(o)
        if n == 0: continue
        hit = {}
        for name, F in (("stack", S), ("backer_v2", V)):
            g = F[(F.launch_id.astype(str) == lid) & F.person_id.astype(str).isin(reread)].sort_values("rank")
            hit[name] = len(set(g.person_id.astype(str).iloc[:n]) & o)
        rows.append({"day": D, "launch_id": lid, "n": n, **hit}); n_day += 1
    days.append({"day": D, "status": "scored" if n_day else "no observed held backers yet", "launches": n_day, "held_reread_after_close": len(reread)})
R = pd.DataFrame(rows); out = {"experiment": "STACK-FWD-1", "rule": "backer_score.py north-star rule, both lists ranked within re-read held people", "days": days}
if len(R):
    pooled = lambda df, c: 100 * df[c].sum() / df.n.sum()
    bs = [(lambda d: pooled(d, "stack") - pooled(d, "backer_v2"))(R.iloc[rng.integers(0, len(R), len(R))]) for _ in range(2000)]
    out.update(launches=int(len(R)), scored_days=int(R.day.nunique()), observed_backers=int(R.n.sum()),
               recall_at_N={"stack": round(pooled(R, "stack"), 1), "backer_v2": round(pooled(R, "backer_v2"), 1)},
               stack_minus_backer_v2=[round(pooled(R, "stack") - pooled(R, "backer_v2"), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)],
               rule5={"scored_live_days": int(R.day.nunique()), "revert": bool(R.day.nunique() >= 7 and np.percentile(bs, 97.5) < 0)})
out["scored_at"] = pd.Timestamp.now(tz="UTC").isoformat()
p = "/tmp/stack_score.json"; json.dump(out, open(p, "w"), indent=1); subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/calibration/stack_fwd/score.json"])
print(json.dumps({k: v for k, v in out.items() if k != "days"}), json.dumps(days[-3:]))
