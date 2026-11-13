#!/usr/bin/env python3
"""Rebuild the coverage-dashboard indexes and the fleet completion queue from the current store (population agent).

Replaces the Nov 4-8 people_live/build.py output, which used the old >=98%-of-header rule. Everything here follows the
store's own whole-person rule (quality.py person_complete, full18f): a person is complete only if every list reaches its
header or PH's own end.

Inputs (local):
  RAW/.quality_cache.jsonl        per-file summaries written by quality.py (tab states, per-tab counts, reasons)
  COMPLETE                        quality_<UTC>_complete.txt from the same quality run (handle<TAB>whole|whole_signed_out)
  MASTER                          Data Feeder raw/population_data/master/profiles.jsonl.gz (pool person_ids and tiers)
  SALT                            raw/population/_salt (person_id rule shared with the master)
Outputs (local, in OUT):
  have_index.jsonl   one row per person (store people with handles, plus pool people with no whole-person save yet)
  need_list.jsonl    people still needing a pull, ranked: likely tier, then recent upvoters, then the rest
  completion_queue.txt  handle<TAB>tabs needed<TAB>reasons, store people that are saved but incomplete
                        (merged-incomplete first), for the Cursor fleet. Handles stay under raw/.
Counts only to stdout.
Usage: have_index.py RAW COMPLETE MASTER SALT MERGED_LEDGER OUT
"""
import collections
import gzip
import hashlib
import json
import os
import sys

ALL = ["about", "forums", "activity", "upvotes", "hunted", "collections", "stacks", "reviews", "followers", "following"]
OK_STATES = {"complete", "ph_limit", "rating_only"}
FILL_TAB = {"collection_items": "collections", "forum_threads": "forums", "reviews_items": "reviews",
            "comment_times": "activity", "maker_product_pages": "hunted"}


def tab_of(reason):
    k, _, rest = reason.partition(":")
    if k in ALL:
        return k
    if k == "missing_tab":
        return rest
    if k == "header_missing":
        return "about"
    if k == "not_filled":
        return FILL_TAB.get(rest, rest)
    return k


def main():
    raw, complete_f, master_f, salt_f, ledger_f, out = sys.argv[1:7]
    salt = open(salt_f).read().strip()
    pid = lambda u: "p_" + hashlib.sha256((salt + "producthunt:" + u.lower().lstrip("@")).encode()).hexdigest()[:16]
    assert pid("example_user") == "p_97eb5d57c445ef1f"
    cache = {}
    for l in open(os.path.join(raw, ".quality_cache.jsonl")):
        try:
            e = json.loads(l)
        except Exception:
            continue
        cache[e["p"]] = e  # later lines win
    latest = {}
    for p, e in cache.items():
        i = e.get("i")
        if "/people_live/vm/" not in p or not i or i.get("skip") or "tabs" not in i:
            continue
        if i["h"] not in latest or i["fin_run"] >= latest[i["h"]]["fin_run"]:
            latest[i["h"]] = i
    comp = {}
    for l in open(complete_f):
        h, _, k = l.rstrip("\n").partition("\t")
        if h:
            comp[h.lower()] = k
    ledger = {l.strip().lower() for l in open(ledger_f) if l.strip() and not l.startswith("#")} if os.path.exists(ledger_f) else set()
    tier = {}
    for l in gzip.open(master_f, "rt"):
        d = json.loads(l)
        tier[d["person_id"]] = d.get("tier")
    os.makedirs(out, exist_ok=True)
    hv = open(os.path.join(out, "have_index.jsonl"), "w")
    need, queue = [], []
    c = collections.Counter()
    seen = set()
    for h, i in latest.items():
        p = pid(h)
        seen.add(p)
        tabs = {}
        for t in ALL:
            v = (i.get("tabs") or {}).get(t)
            if v is None:
                continue
            st = str((i.get("states") or {}).get(t, "complete")).split("+")[0] if t != "about" else "complete"
            tabs[t] = {"n": v["n"], "header": v["header"], "status": "complete" if st in OK_STATES else st,
                       "last_pulled_at": i["fin_run"] or i["fin"], "source": "people_live/vm"}
            if t == "upvotes":
                tabs[t]["newest_item_launch_ts"] = v["newest"]
            else:
                tabs[t]["newest_item_ts"] = v["newest"]
        is_c = h.lower() in comp
        why = [] if is_c else (list(i.get("why") or []) or (["upvotes:signed_out_end_not_queued_signed_in"] if i.get("so") else ["unknown"]))
        need_tabs = sorted({tab_of(w) for w in why})
        row = {"person_id": p, "ph_user_id": i.get("ph_user_id"), "handle": h, "tier": tier.get(p) or "non-pool",
               "tabs": tabs, "tabs_with_items": sorted(t for t, v in tabs.items() if v["n"]),
               "missing_item_tabs": [t for t in ALL if not (tabs.get(t) or {}).get("n")],
               "complete": is_c, "complete_kind": comp.get(h.lower()), "incomplete_reasons": why, "tabs_needed": need_tabs,
               "merged": h.lower() in ledger, "completeness_rule": "full18f whole person: every list at its header or PH's own end (population quality.py)"}
        hv.write(json.dumps(row) + "\n")
        c["store_people"] += 1
        c["store_complete"] += is_c
        if not is_c:
            up = tabs.get("upvotes", {}).get("newest_item_launch_ts") or ""
            pri = 0 if h.lower() in ledger else (1 if row["tier"] == "likely" else (2 if up >= "2026-10-01" else 3))
            queue.append((pri, -int(up[:10].replace("-", "") or 0) if up[:2] == "20" else 0, h, need_tabs, why))
            need.append(((pri, 0), {"person_id": p, "ph_user_id": i.get("ph_user_id"), "handle": h, "tier": row["tier"],
                                    "missing_tabs": need_tabs, "newest_upvote_launch": up or None,
                                    "reason": "saved but incomplete: " + ", ".join(why[:4]), "merged": row["merged"]}))
    for p, t in tier.items():  # pool people with no whole-person save yet (master holds no handles)
        if p in seen:
            continue
        hv.write(json.dumps({"person_id": p, "ph_user_id": None, "handle": None, "tier": t, "tabs": {}, "tabs_with_items": [],
                             "missing_item_tabs": ALL, "complete": False, "incomplete_reasons": ["no_whole_person_save"],
                             "tabs_needed": ALL, "merged": False}) + "\n")
        c["pool_no_save"] += 1
        need.append(((1 if t == "likely" else 4, 0), {"person_id": p, "ph_user_id": None, "handle": None, "tier": t,
                                                      "missing_tabs": ALL, "newest_upvote_launch": None,
                                                      "reason": "pool person with no whole-person save (handle in master need list)"}))
    hv.close()
    need.sort(key=lambda z: z[0])
    with open(os.path.join(out, "need_list.jsonl"), "w") as f:
        for r_, (s, d) in enumerate(need, 1):
            d["rank"] = r_
            f.write(json.dumps(d) + "\n")
    queue.sort()
    with open(os.path.join(out, "completion_queue.txt"), "w") as f:
        f.write("# handle<TAB>tabs needed<TAB>reasons; saved-but-incomplete people, merged-incomplete first, then likely tier, "
                "then recent upvoters (launch>=2026-10-01), then the rest. Whole-person re-pull; the tabs say what failed.\n")
        for pri, _, h, tabs, why in queue:
            f.write(f"{h}\t{','.join(tabs)}\t{','.join(why)}\n")
    tc = collections.Counter(t for _, _, _, tabs, _ in queue for t in tabs)
    pc = collections.Counter(pri for pri, *_ in queue)
    print(f"HAVE_INDEX rows={c['store_people'] + c['pool_no_save']} store_people={c['store_people']} store_complete={c['store_complete']} "
          f"pool_no_save={c['pool_no_save']}")
    print(f"NEED_LIST rows={len(need)}")
    print(f"COMPLETION_QUEUE people={len(queue)} merged_incomplete={pc[0]} likely={pc[1]} recent={pc[2]} other={pc[3]} tabs={dict(tc.most_common())}")


if __name__ == "__main__":
    main()
