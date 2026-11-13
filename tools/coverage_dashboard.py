#!/usr/bin/env python3
"""Build the datasets behind the UserSim collection-coverage dashboard
(https://claude.ai/artifact/WV14WeCEQQmV1PB8psDfit) from the GCS files. Counts only; no usernames leave this script.

Usage: python3 -I tools/coverage_dashboard.py <out_dir>   (then upload each JSON as an asset and update the dataset docs)
Inputs (GCS): raw/ph_population/people_live/{have_index,need_list}.jsonl, raw/ph_at_launch/live/route4_pages*.jsonl,
raw/ph_at_launch/<today PT>/live/coverage_ts.jsonl, raw/population_data/x/_checkpoint.
"""
import collections, datetime, json, os, subprocess, sys

B = "gs://usersim-bakeoff-347838016394/usersim_sim/raw"
TABS = ["about", "upvotes", "activity", "forums", "reviews", "collections", "stacks", "hunted", "followers", "following"]  # "made" is not a tab in the rebuilt index
KINDS = ["whole", "whole_signed_out"]
TIER = {"likely": "likely", "active_rest": "active"}

def fetch(path, dest):
    subprocess.run(["gsutil", "-q", "cp", path, dest], check=False)
    return dest if os.path.exists(dest) else None

def rows(fn):
    if not fn: return
    with open(fn) as f:
        for l in f:
            if l.strip(): yield json.loads(l)

def parse(ts):
    d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)

def main(out):
    os.makedirs(out, exist_ok=True); tmp = os.path.join(out, "_in"); os.makedirs(tmp, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    pt_day = (now - datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
    have = sys.argv[2] if len(sys.argv) > 2 else fetch(f"{B}/ph_population/people_live/have_index.jsonl", f"{tmp}/have.jsonl")
    need = fetch(f"{B}/ph_population/people_live/need_list.jsonl", f"{tmp}/need.jsonl")
    r4a = fetch(f"{B}/ph_at_launch/live/route4_pages.jsonl", f"{tmp}/r4.jsonl")
    r4b = fetch(f"{B}/ph_at_launch/live/route4_pages_backfill.jsonl", f"{tmp}/r4b.jsonl")
    cov = fetch(f"{B}/ph_at_launch/{pt_day}/live/coverage_ts.jsonl", f"{tmp}/cov.jsonl")
    ck = fetch(f"{B}/population_data/x/_checkpoint", f"{tmp}/ck.json")

    tier_n, full, recent, store, kind = (collections.Counter() for _ in range(5))
    tab_cov = collections.defaultdict(collections.Counter)
    for r in rows(have):
        t = TIER.get(r.get("tier") or "other", "other"); tier_n[t] += 1
        tabs = r.get("tabs") or {}; last = None
        if tabs: store[t] += 1; store["all"] += 1
        for tb in TABS:
            x = tabs.get(tb) or {}; n = x.get("n") or 0
            if n > 0: tab_cov[tb][t] += 1; tab_cov[tb]["all"] += 1
            if (x.get("status") or "") in ("complete", "complete_not_visible", "capped_large"): tab_cov[tb + "_complete"]["all"] += 1
            lp = x.get("last_pulled_at")
            if lp and (last is None or lp > last): last = lp
        ok = r.get("complete") is True  # store's whole-person rule (complete_kind whole / whole_signed_out)
        if ok:
            k = r.get("complete_kind") or "unknown"; full[t] += 1; full["all"] += 1; kind[(t, k)] += 1; kind[("all", k)] += 1
        if last:
            d = (now - parse(last)).total_seconds() / 86400
            recent["24h" if d <= 1 else "7d" if d <= 7 else "older"] += 1
        else: recent["never"] += 1
    total = sum(tier_n.values()) or 1
    json.dump([{"tab": tb, "people_with_items": tab_cov[tb]["all"], "complete": tab_cov[tb + "_complete"]["all"], "likely": tab_cov[tb]["likely"],
                "active": tab_cov[tb]["active"], "other": tab_cov[tb]["other"], "share_pct": round(100 * tab_cov[tb]["all"] / total, 1)} for tb in TABS],
              open(f"{out}/coverage_tabs.json", "w"))
    tier_n["all"] = total
    json.dump([{"tier": t, "people": tier_n[t], "in_store": store[t], "all_tabs_pulled": full[t], "pct_full": round(100 * full[t] / max(tier_n[t], 1), 2),
                "pct_of_store": round(100 * full[t] / max(store[t], 1), 2), **{k: kind[(t, k)] for k in KINDS}} for t in ["likely", "active", "other", "all"]],
              open(f"{out}/coverage_tiers.json", "w"))
    json.dump([{"bucket": k, "people": recent[k]} for k in ["24h", "7d", "older", "never"]], open(f"{out}/recency.json", "w"))
    miss = collections.Counter()
    for r in rows(need):
        for tb in r.get("missing_tabs", []): miss[tb] += 1
    json.dump([{"tab": k, "people_missing": v} for k, v in miss.most_common()], open(f"{out}/need_missing.json", "w"))
    r4 = collections.Counter()
    for fn in (r4b, r4a):
        for r in rows(fn): r4[(r["ts"][:10], r.get("job", "?"), str(r.get("status")))] += 1
    json.dump([{"day": d, "job": j, "status": s, "pages": c} for (d, j, s), c in sorted(r4.items())], open(f"{out}/route4_daily.json", "w"))
    json.dump([{"snapshot_ts": c["snapshot_ts"], "launches_expected": c["launches_expected"], "fetched_200": c["fetched_200"], "failed": c["failed"],
                "late_s": round(c.get("late_s") or 0), "source": c["source"]} for c in rows(cov)], open(f"{out}/live_capture.json", "w"))
    c = json.load(open(ck)) if ck else {"next_index": 0, "queue_len": 1}
    json.dump([{"metric": "handles_done", "value": c["next_index"]}, {"metric": "handles_total", "value": c["queue_len"]},
               {"metric": "pct_done", "value": round(100 * c["next_index"] / max(c["queue_len"], 1), 1)}], open(f"{out}/x_rollout.json", "w"))
    print(json.dumps({"people": total, "store": dict(store), "kind": {f"{a}/{b}": v for (a, b), v in kind.items()}, "full": dict(full), "tiers": dict(tier_n), "recency": dict(recent), "pt_day": pt_day}))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/coverage_dashboard")
