"""Error anatomy of the 03:45 hybrid's top-3 misses (orchestrator 23:52Z Nov 14). PRE-REGISTERED buckets, run as a detached job.

The published 03:45 order is hybrid_vm = hidden top 5 (recorder rank_now at 03:45) + ridge order for 6+, so its top 3 IS the hidden top 3
at 03:45; the prior can only move ranks 6+. Per day (recorder file raw/vote_snapshots/<d>.jsonl, the writer's source; latest read <= the
point + 90 s within 65 min): hidden position at 01:00 / 02:00 / 03:00 / 03:45, comments at 03:45, rank by votes at the reveal (first read at
or after 04:00 where >= half the launches show votes) and at 04:30; 00:05 rank = the clean_nosite prior order (prereveal_votes.priors);
final rank = truth_daily.json (warehouse fallback, flagged, when the day is not in it yet); final votes from the warehouse.
A miss = a final top-3 launch outside our top 3 (paired with the lowest-placed wrong pick in our top 3). Buckets, first match wins:
  (a) hidden order wrong at 03:45 but right by 04:30: the missed launch is in the 04:30 top 3 by votes
  (b) the 00:05 prior pulled it the wrong way: the missed launch was hidden top 3 at 03:45 but not in our top 3 (0 by construction)
  (c) near-tie at close: final votes of the missed launch and the displaced pick within 5%
  (d) other
Oracle top 3 per bucket: share of top-3 slots hit if every miss in that bucket were fixed (the other misses stay).
usage: python miss_anatomy_0345.py [day ...] -> results/miss_anatomy_0345.{json,md}"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import prereveal_votes as PV
from early_forecast import B
R = lambda p: os.path.join(HERE, "results", p)
DAYS = sys.argv[1:] or ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09",
                        "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
from pipeline import warehouse as W
L = W.query("SELECT CAST(id AS VARCHAR) AS id, CAST(day AS VARCHAR) AS d, daily_rank, votes FROM launches WHERE CAST(day AS VARCHAR) >= '2026-11-01'", do_sync=False)
L["d"] = L.d.str[:10]
TD = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/web/truth_daily.json"], capture_output=True, text=True).stdout or "{}").get("days", {})
prior = PV.priors(); rows, days = [], {}
for d in DAYS:
    f = PV.get(f"{B}/raw/vote_snapshots/{d}.jsonl")
    if not f: days[d] = "no recorder file"; continue
    V = pd.DataFrame([json.loads(l) for l in open(f)]); V["id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True); V = V.drop_duplicates(["id", "a"])
    pt = lambda hm: pd.Timestamp(f"{d} {hm}", tz="America/Los_Angeles").tz_convert("UTC")
    def read(hm):
        T = pt(hm); s = V[(V.a <= T + pd.Timedelta(seconds=90)) & (V.a >= T - pd.Timedelta(minutes=65)) & V.rank_now.notna()]
        return s.sort_values("a").groupby("id").last() if len(s) else None
    rd = {p: read(p) for p in ("01:00", "02:00", "03:00", "03:45")}
    if rd["03:45"] is None: days[d] = "no 03:45 read"; continue
    ids = list(rd["03:45"].index)
    pos = {p: (r.rank_now.reindex(ids).fillna(999).rank(method="first") if r is not None else pd.Series(np.nan, index=ids)) for p, r in rd.items()}
    after = V[V.a >= pt("04:00")]; g = after.groupby("a").votes.apply(lambda x: (x.fillna(0) > 0).mean()).sort_index(); ok = g[g >= 0.5]
    rv = after[after.a == ok.index.min()].groupby("id").votes.last().reindex(ids).fillna(0) if len(ok) else pd.Series(0.0, index=ids)
    v430 = V[(V.a <= pt("04:30") + pd.Timedelta(seconds=90)) & (V.a >= pt("04:00"))].sort_values("a").groupby("id").votes.last().reindex(ids).fillna(0)
    rrk = rv.rank(ascending=False, method="first"); r430 = v430.rank(ascending=False, method="first")
    pr = pd.Series({i: prior.get(d, {}).get(i, np.nan) for i in ids}); r0005 = pr.rank(ascending=False, method="first")
    if d in TD:
        fr = pd.Series({str(i): r for i, r in TD[d]["ranks"].items()}); tsrc = "truth_daily"
    else:
        fr = L[L.d == d].dropna(subset=["daily_rank"]).set_index("id").daily_rank; tsrc = "warehouse (truth_daily missing)"
    fv = L[L.d == d].set_index("id").votes.astype(float)
    true3 = list(fr.sort_values().index[:3]); ours = sorted(ids, key=lambda i: pos["03:45"][i])[:3]
    missed = [i for i in true3 if i not in ours]; wrong = sorted([i for i in ours if i not in true3], key=lambda i: -pos["03:45"][i])
    days[d] = {"truth": tsrc, "hits": 3 - len(missed), "launches": len(ids)}
    for k, m in enumerate(missed):
        w = wrong[k] if k < len(wrong) else None
        fm, fw = fv.get(m, np.nan), (fv.get(w, np.nan) if w else np.nan)
        if m in ids and r430.get(m, 99) <= 3: b = "a"
        elif m in ids and pos["03:45"][m] <= 3: b = "b"
        elif w and fm == fm and fw == fw and abs(fm - fw) / max(fm, fw, 1) <= 0.05: b = "c"
        else: b = "d"
        rows.append({"day": d, "missed": m, "displaced_by": w, "bucket": b, "final_rank": int(fr.get(m, 0)) or None,
                     **{f"hidden_{p}": (float(pos[p].get(m)) if m in ids else None) for p in pos}, "rank_0005": float(r0005.get(m)) if m in ids else None,
                     "comments_0345": float(rd["03:45"].comments.get(m, np.nan)) if m in ids else None,
                     "reveal_rank": float(rrk.get(m)) if m in ids else None, "rank_0430": float(r430.get(m)) if m in ids else None,
                     "climbed_after_reveal": (bool(fr.get(m, 99) < rrk.get(m, 99)) if m in ids else None),
                     "final_votes": fm, "displaced_final_votes": fw, "displaced_hidden_0345": float(pos["03:45"].get(w)) if w else None,
                     "displaced_rank_0005": float(r0005.get(w)) if w else None})
M = pd.DataFrame(rows); scored = [d for d, v in days.items() if isinstance(v, dict)]
base = sum(days[d]["hits"] for d in scored) / (3 * len(scored)) * 100 if scored else None
orac = {b: round((sum(days[d]["hits"] for d in scored) + int((M.bucket == b).sum()) if len(M) else 0) / (3 * len(scored)) * 100, 1) for b in "abcd"} if scored else {}
out = {"method": __doc__, "days": days, "top3_hits_pct": round(base, 1) if base is not None else None, "misses": len(M),
       "by_bucket": M.bucket.value_counts().reindex(list("abcd"), fill_value=0).to_dict() if len(M) else {}, "oracle_top3_if_bucket_fixed": orac,
       "rows": M.to_dict("records")}
json.dump(out, open(R("miss_anatomy_0345.json"), "w"), indent=1, default=lambda x: None if x != x else float(x))
md = ["# 03:45 hybrid: anatomy of the top-3 misses", "", f"Days scored: {len(scored)}; top 3: {out['top3_hits_pct']}%; misses: {len(M)}; by bucket {out['by_bucket']};",
      f"oracle top 3 if a bucket were fixed: {orac}", "",
      "| day | bucket | final | hidden 01/02/03/03:45 | 00:05 rank | comments | reveal rank | 04:30 rank | climbed | votes miss / displaced |", "|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    md.append(f"| {r['day']} | {r['bucket']} | {r['final_rank']} | {r['hidden_01:00']}/{r['hidden_02:00']}/{r['hidden_03:00']}/{r['hidden_03:45']} | {r['rank_0005']} | "
              f"{r['comments_0345']} | {r['reveal_rank']} | {r['rank_0430']} | {r['climbed_after_reveal']} | {r['final_votes']} / {r['displaced_final_votes']} |")
open(R("miss_anatomy_0345.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md[:4]))
