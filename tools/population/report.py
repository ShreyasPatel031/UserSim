"""Daily coverage/depth report from the person store (counts only; no usernames or ids).
Usage: python tools/population/report.py STORE_DIR DAY > coverage.md"""
import sys
import pandas as pd

d, day = sys.argv[1], sys.argv[2]
e = pd.read_parquet(f"{d}/events.parquet")
_pp = pd.read_parquet(f"{d}/persons.parquet")
pool = set(_pp[_pp.in_pool].person_id) if "in_pool" in _pp else set(_pp.person_id)
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
    if "pull_type" not in t:
        t["pull_type"] = "full"
    light_only = set(t.person_id) - set(t[t.pull_type == "full"].person_id)
    lu = t[(t.tab == "upvotes") & t.person_id.isin(light_only)]
    # light pulls were withdrawn (Shreyas, Nov 4 20:23Z): a header + upvotes-only pull is INCOMPLETE and goes on the deep_list
    print(f"\n## Incomplete header+upvotes-only pulls (need the full pull; never coverage): {len(light_only):,} people")
    t = t[t.pull_type == "full"].copy()
    for col in ("complete_not_visible", "capped_large", "signed_out_cap"):
        if col not in t:
            t[col] = False
    # Shreyas standing rule (d9444ee3): every item, no caps. Per tab:
    #   complete       = count >= 98% of the header
    #   server_ended   = short, but PH's server ended the list (complete_not_visible; never capped_large)
    #   FAIL           = short because our code stopped (capped_large, budget, paging, anything else)
    t["state"] = "FAIL"
    t.loc[t.complete & ~t.capped_large, "state"] = "complete"
    t.loc[(t.state == "FAIL") & t.complete_not_visible & ~t.capped_large, "state"] = "server_ended"
    # orchestrator 20:28Z: the signed-out ~200 upvote end is not final -> server_ended_signed_out (counts as server-ended
    # today; deep_list needs_signed_in). Other server-ended tabs go on the deep_list as verify_signed_in.
    t.loc[(t.state == "server_ended") & t.signed_out_cap, "state"] = "server_ended_signed_out"
    tier = {}
    hi = f"{d}/have_index.jsonl"
    if os.path.exists(hi):
        tier = {r["person_id"]: r.get("tier") or "non-pool" for r in map(json.loads, open(hi))}
    per = t.groupby("person_id").state.agg(lambda s: "FAIL" if (s == "FAIL").any() else ("server_ended" if s.isin(["server_ended", "server_ended_signed_out"]).any() else "complete"))
    ntabs = t.groupby("person_id").tab.nunique()
    per = per[ntabs.reindex(per.index) >= 10]
    perdf = pd.DataFrame({"state": per, "tier": per.index.map(lambda x: tier.get(x, "non-pool" if x not in pool else "unknown"))})
    strict = int((perdf.state == "complete").sum()); se = int((perdf.state == "server_ended").sum()); fail = int((perdf.state == "FAIL").sum())
    print(f"\n## HEADLINE: people with every tab complete or server-ended: {strict + se:,} "
          f"(pool {int(((perdf.state != 'FAIL') & perdf.index.isin(pool)).sum()):,}); strict complete {strict:,}; "
          f"server-ended (PH hid items) {se:,}; FAIL (our code stopped) {fail:,}; people with any full pull {t.person_id.nunique():,}\n")
    print("## Full all-tab pulls by tier\n")
    print("| Tier | People in tier | With a full pull | All tabs complete | + server-ended | FAIL (our code stopped) |")
    print("|---|---|---|---|---|---|")
    sizes = pd.Series(tier).value_counts() if tier else pd.Series(dtype=int)
    for tr in ["likely", "active_rest", "other", "non-pool", "unknown"]:
        g = perdf[perdf.tier == tr]
        anyp = len(set(t.person_id) & {k for k, v in tier.items() if v == tr}) if tier else 0
        print(f"| {tr} | {int(sizes.get(tr, 0)):,} | {anyp:,} | {int((g.state == 'complete').sum()):,} | {int((g.state == 'server_ended').sum()):,} | {int((g.state == 'FAIL').sum()):,} |")
    ft = t[t.state == "FAIL"]
    print(f"\nFAIL tabs (our code stopped): {ft.tab.value_counts().to_dict()}; of which capped_large: {int(ft.capped_large.sum())}")
    print(f"Server-ended tabs (PH hid items signed-out): {t[t.state == 'server_ended'].tab.value_counts().to_dict()}; "
          f"server_ended_signed_out (~200 upvote signed-out end, needs signed-in): {int((t.state == 'server_ended_signed_out').sum())}")
    print("deep_list = every person with a FAIL tab (capped_large included).")
    # deep_list file (handles; GCS only, never committed): people with any FAIL tab, and which tabs
    if os.path.exists(hi):
        h_of = {r["person_id"]: r.get("handle") for r in map(json.loads, open(hi))}
        rows = ft.groupby("person_id").tab.apply(lambda s: ",".join(sorted(s)))
        rows = pd.concat([rows, pd.Series("needs_full_pull", index=sorted(light_only - set(rows.index)))])
        for state, label in (("server_ended_signed_out", "needs_signed_in"), ("server_ended", "verify_signed_in")):
            g = t[t.state == state].groupby("person_id").tab.apply(lambda s: label + ":" + ",".join(sorted(s)))
            for pid_, v in g.items():
                rows[pid_] = (rows[pid_] + ";" + v) if pid_ in rows.index else v
        with open(f"{d}/deep_list.tsv", "w") as f:
            for pid, tabs_ in rows.items():
                f.write(f"{h_of.get(pid) or pid}\t{tabs_}\n")
