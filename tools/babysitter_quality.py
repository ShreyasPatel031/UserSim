#!/usr/bin/env python3
"""Babysitter data-quality check of person pulls (no usernames printed; counts only).
Reads every person JSON written since --since from people_live/vm_pgql/_run_*/ (fast c32 lists) and people_live/vm/*.json
(full + deep), and scores each tab:
  complete      got >= 98% of the profile header, or the server ended the list (hasNextPage false / complete_not_visible)
  ph_limit      shorter than the header but PH's server ended it (allowed: e.g. ~200 signed-out upvotes)
  FAIL_short    shorter than the header with no server end recorded (no-caps rule: FAIL)
  no_header     header count missing (fast pull skipped the page load; deep fills it)
  partial       marked partial / truncated_budget (on deep_list for a resume)
Also: required fields present (ph_user_id, header, run), duplicate items by id within a tab, empty person files.
Usage: babysitter_quality.py [--since 2026-11-04T21:00Z] [--max 400] [--out report.json]"""
import argparse, collections, json, subprocess, sys

ROOT = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/people_live"
TABS = ("upvotes", "hunted", "following", "followers", "collections", "stacks", "reviews")
IDK = {"upvotes": "post_id", "hunted": "post_id", "following": "ph_user_id", "followers": "ph_user_id",
       "collections": "collection_id", "stacks": "url", "reviews": "review_id"}


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True).stdout


def ls_since(pattern, since):
    out = []
    for line in sh("gsutil", "ls", "-l", pattern).splitlines():
        p = line.split()
        if len(p) == 3 and p[2].endswith(".json") and p[1] >= since and "summary" not in p[2]:
            out.append((p[1], p[2]))
    return sorted(out)


def score(d, pgql_paging):
    res = {}
    hdr = d.get("header") or {}
    for k in TABS:
        t = d.get(k)
        if not isinstance(t, dict):
            res[k] = "missing_tab"; continue
        items = t.get("items") or []
        got = t.get("count", len(items)); h = t.get("header", hdr.get(k))
        ids = [x.get(IDK[k]) or x.get("url") for x in items if isinstance(x, dict)]
        ids = [i for i in ids if i]
        dup = len(ids) - len(set(ids))
        ended = (pgql_paging.get(k) or {}).get("ended") or ((t.get("paging") or {}).get("ended"))
        if t.get("status") in ("partial", "truncated_budget") or t.get("truncated_budget"):
            v = "partial"
        elif h is None:
            v = "no_header"
        elif h == 0 or got >= 0.98 * h:
            v = "complete"
        elif t.get("complete_not_visible") or ended in ("hasNextPage_false", "server_end", "server_end_offset", "empty_page"):
            v = "ph_limit"
        else:
            v = "FAIL_short"
        res[k] = v + ("+dup" if dup else "")
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--since", default="2026-11-04T21:00:00Z")
    ap.add_argument("--max", type=int, default=400); ap.add_argument("--out")
    a = ap.parse_args()
    files = ls_since(f"{ROOT}/vm_pgql/_run_*/*.json", a.since)[-a.max:] + ls_since(f"{ROOT}/vm/*.json", a.since)[-a.max:]
    per_tab = collections.defaultdict(collections.Counter); src = collections.Counter(); hdr_src = collections.Counter()
    bad_fields = 0; empty = 0; fails = []; n = 0
    for ts, u in files:
        try: d = json.loads(sh("gsutil", "cat", u))
        except Exception: empty += 1; continue
        n += 1; kind = "fast_c32" if "/vm_pgql/" in u else ("deep_or_full" if d.get("run", {}).get("deep_passes") else "vm_json")
        src[kind] += 1; hdr_src[(d.get("header_source") or "ssr_full_pull")[:40]] += 1
        if not d.get("ph_user_id") or not isinstance(d.get("header"), dict) or not d.get("run"): bad_fields += 1
        sc = score(d, (d.get("run") or {}).get("paging") or {})
        for k, v in sc.items():
            per_tab[k][v] += 1
            if v.startswith("FAIL"): fails.append({"file": u.rsplit("/", 2)[-2] + "/<person>", "tab": k, "kind": kind})
    rep = {"since": a.since, "people_checked": n, "unreadable": empty, "by_source": dict(src), "header_source": dict(hdr_src),
           "missing_required_fields": bad_fields, "tabs": {k: dict(v) for k, v in per_tab.items()},
           "FAIL_short_total": len(fails), "FAIL_short_by_tab": dict(collections.Counter(f["tab"] for f in fails))}
    print(json.dumps(rep, indent=1))
    if a.out: json.dump({**rep, "fails": fails}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
