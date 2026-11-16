"""Lift hidden #4/#5 into the top 3 when the published 00:05 forecast backs it (orchestrator 10:33Z Nov 16). PRE-REGISTERED:
committed before any number was computed.

Current line: the 03:45 hybrid = hidden daily order (recorder rank_now) for the top 5, ridge for 6+; its top 3 is the hidden top 3.
Rule family R(k, m), applied per day to the hidden order at read time T:
  c  = whichever of hidden #4 / #5 has the better (lower) PUBLISHED 00:05 rank (warehouse forecasts, model launch_model)
  if r0005(c) <= k and r0005(hidden #3) > m: swap hidden #3 and c (c enters the top 3; #3 drops to c's slot)
  Grid: k in 1..5, m in 1..10 with m >= k, plus "never" (= the current hybrid). A launch absent from the published forecast
  has r0005 = 999 (never lifted; always "> m").
  The rule only permutes positions 3-5, so the top-5 and top-10 sets are identical to the current line by construction;
  they are reported as such (difference 0) and only top 3 can change.
Choice of (k, m): leave-one-day-out. For each held-out day, pick the grid point (or "never") with the most top-3 hits on the other
  days; ties go to fewer swaps on those days, then smaller k, then larger m. Apply it to the held-out day.
Reads: PRIMARY T = 03:45 PT (latest recorder read <= T + 90 s within 65 min, as miss_anatomy_0345 / the published writer);
  SECONDARY T = 03:00 PT. Every read used is before 04:00 PT (asserted).
Prior: the published 00:05 forecast as written that night (forecasts.updated_at before 00:30 PT of the day, asserted), never refit.
Truth: truth_daily.json final daily ranks; unranked = miss. Days: Nov 2 - Nov 16 with a read at T, a published forecast and truth.
Metric: top-3 hits per day (share of the 3 slots); PRIMARY = LODO rule minus current, paired by day, day bootstrap 95% (10,000), n.
Adoption: deploy only if the PRIMARY interval's lower bound is > 0. Otherwise the rule (all-days choice of (k, m)) becomes a scored
  forward shadow line from the next night. Also reported (not decisive): the all-days in-sample best (k, m), swaps per day.
usage: python lift45.py -> results/lift45.{json,md}"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import prereveal_votes as PV
from early_forecast import B
from pipeline import warehouse as W
R = lambda p: os.path.join(HERE, "results", p)
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-11-02", "2026-11-16")]
TD = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/web/truth_daily.json"], capture_output=True, text=True).stdout or "{}").get("days", {})
FC = W.query("SELECT CAST(forecast_date AS VARCHAR) AS d, CAST(launch_id AS VARCHAR) AS id, predicted_rank, updated_at FROM forecasts "
             "WHERE model = 'launch_model' AND CAST(forecast_date AS VARCHAR) >= '2026-11-02'")
FC["d"] = FC.d.str[:10]
GRID = [(k, m) for k in range(1, 6) for m in range(1, 11) if m >= k]


def day_inputs(d, hm):
    f = PV.get(f"{B}/raw/vote_snapshots/{d}.jsonl")
    if not f: return None, "no recorder file"
    V = pd.DataFrame([json.loads(l) for l in open(f)]); V["id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True)
    V = V.drop_duplicates(["id", "a"])
    T = pd.Timestamp(f"{d} {hm}", tz="America/Los_Angeles").tz_convert("UTC")
    s = V[(V.a <= T + pd.Timedelta(seconds=90)) & (V.a >= T - pd.Timedelta(minutes=65)) & V.rank_now.notna()]
    if not len(s): return None, f"no {hm} read"
    assert s.a.max() < pd.Timestamp(f"{d} 04:00", tz="America/Los_Angeles").tz_convert("UTC"), "read after 04:00 PT"
    r = s.sort_values("a").groupby("id").last()
    hidden = list(r.rank_now.sort_values(kind="stable").index)
    P = FC[FC.d == d]
    if not len(P): return None, "no published 00:05 forecast"
    assert pd.to_datetime(P.updated_at, utc=True).max() < pd.Timestamp(f"{d} 00:30", tz="America/Los_Angeles").tz_convert("UTC"), "prior written after 00:30 PT"
    r05 = dict(zip(P.id, P.predicted_rank.astype(int)))
    if d not in TD: return None, "no truth_daily"
    tr = {str(i): int(v) for i, v in TD[d]["ranks"].items()}
    return {"hidden": hidden, "r05": r05, "true3": {i for i, v in tr.items() if v <= 3}, "read_at": str(s.a.max())}, None


def apply(x, km):
    h = list(x["hidden"])
    if km is None or len(h) < 5: return h, False
    k, m = km; g = lambda i: x["r05"].get(i, 999)
    c = min((3, 4), key=lambda j: (g(h[j]), j))
    if g(h[c]) <= k and g(h[2]) > m:
        h[2], h[c] = h[c], h[2]; return h, True
    return h, False


hits = lambda o, x: len(set(o[:3]) & x["true3"]) / 3


def run(hm):
    X, skip = {}, {}
    for d in DAYS:
        x, why = day_inputs(d, hm)
        if x is None: skip[d] = why
        else: X[d] = x
    days = sorted(X)
    opts = [None] + GRID
    tab = {o: np.array([hits(apply(X[d], o)[0], X[d]) for d in days]) for o in opts}
    sw = {o: np.array([apply(X[d], o)[1] for d in days]) for o in opts}
    lodo, chosen = [], {}
    for i, d in enumerate(days):
        mask = np.arange(len(days)) != i
        key = lambda o: (tab[o][mask].sum(), -sw[o][mask].sum(), -(o[0] if o else 0), (o[1] if o else 99))
        best = max(opts, key=key); chosen[d] = best; lodo.append(tab[best][i])
    lodo = np.array(lodo); cur = tab[None]; D = lodo - cur
    rng = np.random.default_rng(0); n = len(D)
    bs = np.array([D[rng.integers(0, n, n)].mean() for _ in range(10000)]) if n else np.array([0.0])
    allbest = max(opts, key=lambda o: (tab[o].sum(), -sw[o].sum(), -(o[0] if o else 0), (o[1] if o else 99)))
    return {"read": hm, "n_days": n, "days": days, "skipped": skip,
            "top3_current": round(100 * cur.mean(), 1) if n else None, "top3_lodo_rule": round(100 * lodo.mean(), 1) if n else None,
            "lodo_minus_current_top3": [round(100 * D.mean(), 1), round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)] if n else None,
            "top5_top10_difference": "0 by construction (the rule permutes positions 3-5 only)",
            "lodo_choice_per_day": {d: (list(c) if c else "never") for d, c in chosen.items()},
            "lodo_swaps": int(sum(apply(X[d], chosen[d])[1] for d in days)),
            "lodo_changed_days": {d: round(100 * (lodo[i] - cur[i]), 1) for i, d in enumerate(days) if lodo[i] != cur[i]},
            "all_days_best": (list(allbest) if allbest else "never"), "all_days_best_top3": round(100 * tab[allbest].mean(), 1) if n else None,
            "all_days_best_swaps": int(sw[allbest].sum()), "read_at_max_utc": max(X[d]["read_at"] for d in days) if n else None}


if __name__ == "__main__":
    res = {"method": __doc__, "primary_0345": run("03:45"), "secondary_0300": run("03:00")}
    p = res["primary_0345"]["lodo_minus_current_top3"]
    res["decision"] = ("ADOPT (interval clear of 0)" if p and p[1] > 0 else "NOT ADOPTED: forward shadow line with the all-days (k, m)")
    json.dump(res, open(R("lift45.json"), "w"), indent=1, default=str)
    md = ["# Lift hidden #4/#5 with the published 00:05 forecast", ""]
    for key in ("primary_0345", "secondary_0300"):
        r = res[key]
        md += [f"## {key} (read {r['read']} PT)", f"- days {r['n_days']}; skipped {r['skipped']}",
               f"- top 3: current {r['top3_current']} / LODO rule {r['top3_lodo_rule']}; difference [95%] {r['lodo_minus_current_top3']}",
               f"- top 5 / top 10: {r['top5_top10_difference']}", f"- LODO swaps {r['lodo_swaps']}; days changed {r['lodo_changed_days']}",
               f"- all-days best (k, m) {r['all_days_best']} -> top 3 {r['all_days_best_top3']} ({r['all_days_best_swaps']} swaps)", ""]
    md.append(f"Decision: {res['decision']}")
    open(R("lift45.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))
