"""Daily coverage/depth report from the person store (counts only; no usernames or ids).
Usage: python tools/population/report.py STORE_DIR DAY > coverage.md"""
import sys
import pandas as pd

d, day = sys.argv[1], sys.argv[2]
e = pd.read_parquet(f"{d}/events.parquet")
pool = set(pd.read_parquet(f"{d}/persons.parquet").person_id)
e["in_pool"] = e.person_id.isin(pool)
n = len(pool)
print(f"# Population store coverage, {day} (pool {n:,}; counts only)\n")
print("| Kind | Source | Quality | Events | Pool people | % pool | Items/person med / p90 | Window width days med / p90 | Oldest |")
print("|---|---|---|---|---|---|---|---|---|")
for (k, s, q), g in e[e.in_pool].groupby(["kind", "source", "ts_quality"]):
    per = g.groupby("person_id").size()
    w = ((g.ts_hi - g.ts_lo).dt.total_seconds() / 86400).dropna()
    ws = f"{w.median():.1f} / {w.quantile(.9):.1f}" if len(w) else "–"
    old = g.ts_lo.min() if g.ts_lo.notna().any() else g.ts_hi.min()
    print(f"| {k} | {s} | {q} | {len(g):,} | {per.size:,} | {per.size / n:.1%} | {per.median():.0f} / {per.quantile(.9):.0f} | {ws} | {str(old)[:10]} |")
up = e[(e.kind == "upvote") & e.in_pool]
w = (up.ts_hi - up.ts_lo).dt.total_seconds() / 86400
print(f"\nUpvotes dated within 1 day: {(w <= 1).mean():.1%}; within 7 days: {(w <= 7).mean():.1%} (window = [lo, first seen]).")
print(f"People with any event: {e[e.in_pool].person_id.nunique():,} ({e[e.in_pool].person_id.nunique() / n:.1%}). "
      f"Events from people outside the pool: {(~e.in_pool).sum():,} ({e[~e.in_pool].person_id.nunique():,} people; pool-growth candidates).")

# full all-tab pulls, by tier (tier from people_live/have_index.jsonl when present next to the store)
import json, os
tp = f"{d}/tabs.parquet"
if os.path.exists(tp):
    t = pd.read_parquet(tp)
    per = t.groupby("person_id").agg(tabs=("tab", "nunique"), complete=("complete", "sum"))
    tier = {}
    hi = f"{d}/have_index.jsonl"
    if os.path.exists(hi):
        tier = {r["person_id"]: r.get("tier") or "non-pool" for r in map(json.loads, open(hi))}
    per["tier"] = per.index.map(lambda x: tier.get(x, "unknown"))
    allt = pd.Series({k: (n if k != "_" else 0) for k, n in [("_", 0)]})
    print("\n## Full all-tab pulls by tier\n")
    print("| Tier | People in tier | With a full pull | All 10 tabs complete |")
    print("|---|---|---|---|")
    sizes = pd.Series(tier).value_counts() if tier else pd.Series(dtype=int)
    for tr in ["likely", "active_rest", "other", "non-pool", "unknown"]:
        g = per[per.tier == tr]
        print(f"| {tr} | {int(sizes.get(tr, 0)):,} | {len(g):,} | {int((g.complete >= 10).sum()):,} |")
    inc = t[~t.complete].tab.value_counts().to_dict()
    print(f"\nIncomplete tabs across full pulls: {inc}")
