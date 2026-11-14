"""ONE truth source for every published number (orchestrator 20:54Z Nov 14). Launch ids, ranks, part names and counts only (no names, no people).
Rule (daily): the FIRST warehouse `launches` part written after the PT day's close that holds rows of that day; ranked = daily_rank not null;
a day counts when >= 10 are ranked; hits@k = our top k that have rank <= k (an unranked pick is a miss).
Weekly / monthly: period_parts.truth (first part after the period's close holding every day of the period with no null rank; else no truth).
Writes results/web/truth_daily.json, results/web/truth_weekly.json, results/web/truth_monthly.json (local copy in <SP>/truth/).
Flags per day: 'initial snapshot' = the first part is the unstamped Oct 28 initial snapshot (no read right after close; days before Oct 26),
'differs from newest part' = the newest part covering the day has a different ranked set or top-10 ranks (a reread changed it; any
number computed from the newest part / 'final daily rank' differs from this file on that day).
  python truth_daily.py [SP] [--no-upload]"""
import json, os, subprocess, sys
import pandas as pd
import period_parts as PP
SP = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
UP = "--no-upload" not in sys.argv; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; FIRST = "2026-04-01"
INIT = pd.Timestamp("2026-10-28T00:00Z")   # period_parts' stamp for the unstamped initial snapshot


def day_rows(f, d):
    x = pd.read_parquet(f, columns=["id", "day", "daily_rank"]); x = x[x.day.astype(str).str[:10] == d]
    return {str(i): int(r) for i, r in zip(x.id, x.daily_rank) if pd.notna(r)}, len(x)


def main():
    P = PP.parts(); now = pd.Timestamp.now(tz="UTC"); today = pd.Timestamp.now(tz=PP.PT).strftime("%Y-%m-%d")
    cover = {}   # day -> [(ts, f)] parts holding rows of that day
    for ts, f in P:
        for d in pd.read_parquet(f, columns=["day"]).day.astype(str).str[:10].unique(): cover.setdefault(d, []).append((ts, f))
    days = {}
    for d in [x.strftime("%Y-%m-%d") for x in pd.date_range(FIRST, today) if x.strftime("%Y-%m-%d") < today]:
        after = [(ts, f) for ts, f in cover.get(d, []) if ts >= PP.close_utc(d)]
        if not after: days[d] = {"status": "pending (no part written after close)", "n_ranked": 0}; continue
        ts, f = after[0]; R, n = day_rows(f, d)
        flags = []
        if ts == INIT and not os.path.basename(f)[:8].isdigit(): flags.append("initial snapshot (unstamped, Oct 28); no read right after close")
        tn, fn = after[-1]
        if fn != f:
            Rn, _ = day_rows(fn, d)
            top = lambda Z: sorted((r, i) for i, r in Z.items() if r <= 10)
            if set(Rn) != set(R) or top(Rn) != top(R):
                flags.append(f"differs from newest part {os.path.basename(fn)}: ranked {len(R)} -> {len(Rn)}, top-10 changed {top(Rn) != top(R)}")
        days[d] = {"status": "counts" if len(R) >= 10 else "excluded: fewer than 10 ranked", "n_ranked": len(R), "n_rows": n,
                   "source_part": os.path.basename(f), "read_time_utc": ts.isoformat(), "hours_after_close": round((ts - PP.close_utc(d)).total_seconds() / 3600, 1),
                   "flags": flags, "ranks": dict(sorted(R.items(), key=lambda t: t[1]))}
    D = {"version": "truth_daily_v1", "written_at": now.isoformat(),
         "rule": "first warehouse part written after the PT day's close holding that day; rank = daily_rank; a day counts with >= 10 ranked; "
                 "hits@k = our top k with rank <= k; unranked picks are misses",
         "reread_history_starts": "parts stamped 2026-10-28T14:00:18Z on (31-day rereads); earlier days read from the initial snapshot",
         "n_days": len(days), "n_counting": sum(v["status"] == "counts" for v in days.values()),
         "n_flag_initial_snapshot": sum(any(x.startswith("initial") for x in v.get("flags", [])) for v in days.values()),
         "n_flag_differs_from_newest": sum(any(x.startswith("differs") for x in v.get("flags", [])) for v in days.values()), "days": days}
    out = {"daily": D}
    for per, name in (("week", "weekly"), ("month", "monthly")):
        rows = {}
        starts = sorted({PP.period(per, x)[0].strftime("%Y-%m-%d") for x in pd.date_range(FIRST, today)})
        for s in starts:
            _, e = PP.period(per, s); es = e.strftime("%Y-%m-%d")
            if es >= today: rows[s] = {"end": es, "status": "open"}; continue
            g, ts, src = PP.truth(per, es)
            if g is None: rows[s] = {"end": es, "status": "no truth" if src is None else "no complete truth read", "detail": src}; continue
            g = g.assign(id=g.id.astype(str), rank=g["rank"].astype(int)).sort_values("rank")
            rows[s] = {"end": es, "status": "ok", "source_part": src, "read_time_utc": ts.isoformat(), "n_ranked": int(len(g)),
                       "flags": ["initial snapshot (unstamped, Oct 28); no read right after close"] if str(src).startswith("initial") else [],
                       "ranks": dict(zip(g.id, g["rank"].astype(int).tolist()))}
        out[name] = {"version": f"truth_{name}_v1", "written_at": now.isoformat(),
                     "rule": f"first part after the {per}'s close holding every PT day of the {per} with no null {per}ly rank (period_parts.truth); else no truth",
                     "periods": rows}
    os.makedirs(f"{SP}/truth", exist_ok=True)
    for name, J in out.items():
        p = f"{SP}/truth/truth_{name}.json"; json.dump(J, open(p, "w"), indent=0, separators=(",", ":"))
        if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/truth_{name}.json"], check=True)
    print(json.dumps({k: v for k, v in D.items() if k != "days"}),
          {n: pd.Series([v["status"] for v in out[n]["periods"].values()]).value_counts().to_dict() for n in ("weekly", "monthly")})


if __name__ == "__main__":
    main()
