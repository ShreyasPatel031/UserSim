"""Data-quality check of every person pull (population agent; counts only in the report, per-person rows in GCS).

Scope: people_live/vm_pgql/_run_*/*.json (fast c32 list pulls) and people_live/vm/*.json (full + deep) finished since --since.
Per person and tab:
  complete      got >= 98% of the profile header (or header 0)
  ph_limit      short of the header but PH's server ended the list (complete_not_visible / paging ended at the server)
  FAIL_short    short of the header with no server end recorded (no-caps rule: our code stopped)
  partial       marked partial / truncated_budget (deep_list resume)
  no_header     header count missing (fast pulls skip the profile page; deep must fill it)
  missing_tab   tab absent
  +dup          duplicate ids inside the tab
Deep-fill checks (what pgql leaves for deep): header present, reviews items, collection items (items inside each collection),
forum threads opened (thread_full), product-page fields on upvotes/hunted (description/votes), activity comment times.
For people with a fast pull AND a later vm/ pull: did the later pull fill each of those?
Usage: python quality.py DATA_DIR SINCE_UTC OUT_MD OUT_ROWS_JSONL
"""
import glob, json, os, re, sys
from collections import Counter, defaultdict

D, SINCE, OUT_MD, OUT_ROWS = sys.argv[1:5]
TABS = ("upvotes", "hunted", "following", "followers", "collections", "stacks", "reviews", "activity", "forums")
IDK = {"upvotes": "post_id", "hunted": "post_id", "following": "ph_user_id", "followers": "ph_user_id",
       "collections": "collection_id", "stacks": "url", "reviews": "review_id", "activity": "comment_id", "forums": "url"}
SERVER_END = {"hasNextPage_false", "server_end", "server_end_offset", "empty_page", "no_endCursor", "complete"}
HANDLE = re.compile(r"producthunt\.com/@([A-Za-z0-9_\.\-]+)")


def handle_of(d, path):
    m = HANDLE.search(str(d.get("profile") or ""))
    return (m.group(1) if m else os.path.basename(path).split(".")[0]).lower()


NOBUDGET_SINCE = "2026-11-05T00:30:00Z"  # Shreyas: no per-person budget from here on; partial after this is a FAIL


def tab_state(d, k):
    t = d.get(k)
    if not isinstance(t, dict):
        return "missing_tab", 0
    items = t.get("items") or []
    got = t.get("count", len(items))
    h = t.get("header", (d.get("header") or {}).get(k))
    ids = [x.get(IDK[k]) or x.get("url") for x in items if isinstance(x, dict)]
    ids = [i for i in ids if i]
    dup = len(ids) - len(set(ids))
    ended = (t.get("paging") or {}).get("ended") or (((d.get("run") or {}).get("paging") or {}).get(k) or {}).get("ended")
    if t.get("status") in ("partial", "truncated_budget") or t.get("truncated_budget"):
        fin = (d.get("run") or {}).get("finished_utc") or ""
        v = "FAIL_partial" if fin >= NOBUDGET_SINCE else "partial"
    elif k in ("activity", "forums"):
        v = "complete"  # no header shown for these tabs
    elif h is None:
        v = "no_header"
    elif h == 0 or got >= 0.98 * h:
        v = "complete"
    elif k == "reviews":
        v = "rating_only"  # header counts rating-only reviews PH never lists; not a stop of ours
    elif (t.get("complete_not_visible") and not t.get("capped_large")) or ended in SERVER_END:
        v = "ph_limit"
    else:
        v = "FAIL_short"
    return v + ("+dup" if dup else ""), dup


def deep_fill(d):
    """what a complete record has that a lists-only pull lacks; None = not applicable"""
    hdr = d.get("header") or {}
    # header complete = the four core counts read (fast pulls often skip the profile page; deep must fill them)
    out = {"header": all(hdr.get(k) is not None for k in ("followers", "following", "hunted", "collections"))}
    rv = (d.get("reviews") or {}).get("items") or []
    rh = (d.get("reviews") or {}).get("header", hdr.get("reviews"))
    out["reviews_items"] = None if not rh else bool(rv)
    cols = (d.get("collections") or {}).get("items") or []
    need = [c for c in cols if (c.get("products_count") or 0) > 0]
    out["collection_items"] = None if not need else all(c.get("items") for c in need)
    fo = (d.get("forums") or {}).get("items") or []
    out["forum_threads"] = None if not fo else all(x.get("thread_full") for x in fo)
    ups = ((d.get("upvotes") or {}).get("items") or []) + ((d.get("hunted") or {}).get("items") or [])
    out["product_fields"] = None if not ups else sum(1 for x in ups if x.get("description") or x.get("votes") is not None) >= 0.9 * len(ups)
    cm = [x for x in (d.get("activity") or {}).get("items") or [] if "comment" in (x.get("type") or x.get("raw_type") or "").lower()]
    out["comment_times"] = None if not cm else all(x.get("datetime") for x in cm)
    return out


rows, people = [], {}
# kind comes from the pull's method (pgql pulls are also written to vm/<h>.json), not from the folder
files = [(p, "fast_c32") for p in glob.glob(f"{D}/people_live/vm_pgql/_run_*/*.json")] + \
        [(p, "vm") for p in glob.glob(f"{D}/people_live/vm/*.json")]
unreadable = 0
for p, src in files:
    try:
        d = json.load(open(p))
    except Exception:
        unreadable += 1
        continue
    if not isinstance(d, dict) or ("upvotes" not in d and "header" not in d):
        continue
    fin = (d.get("run") or {}).get("finished_utc") or d.get("fetched_at") or ""
    if fin < SINCE:
        continue
    meth = str(d.get("method") or "").lower()
    kind = "fast_c32" if (src == "fast_c32" or "pgql" in meth) else ("deep" if (d.get("run") or {}).get("deep_passes") else "full")
    h = handle_of(d, p)
    req_missing = [f for f in ("ph_user_id", "header", "run") if not d.get(f)]
    states = {k: tab_state(d, k)[0] for k in TABS}
    fill = deep_fill(d)
    rows.append({"handle": h, "kind": kind, "finished": fin, "states": states, "fill": fill, "req_missing": req_missing,
                 "pkg_md5": (d.get("run") or {}).get("pkg_md5")})
    people.setdefault(h, []).append(rows[-1])

by_kind = Counter(r["kind"] for r in rows)
lines = [f"# Person-pull data quality since {SINCE} (population agent; counts only)", "",
         f"Pulls checked: {len(rows):,} ({dict(by_kind)}); people {len(people):,}; unreadable files {unreadable}.", ""]
flags = []
for kind in ("fast_c32", "full", "deep"):
    rs = [r for r in rows if r["kind"] == kind]
    if not rs:
        continue
    lines += [f"## {kind}: {len(rs):,} pulls", "", "| Tab | complete | ph_limit | rating_only | FAIL_short | partial | no_header | missing_tab | dup |", "|---|---|---|---|---|---|---|---|---|"]
    for k in TABS:
        c = Counter(r["states"][k].split("+")[0] for r in rs); dup = sum(1 for r in rs if "+dup" in r["states"][k])
        lines.append(f"| {k} | {c['complete']} | {c['ph_limit']} | {c['rating_only']} | {c['FAIL_short']} | {c['partial']} | {c['no_header']} | {c['missing_tab']} | {dup} |")
        if c["FAIL_partial"]:
            flags.append((kind, k, "partial after no-budget build", c["FAIL_partial"], "a per-person budget/timeout still cut this tab (should not exist after 00:30Z)"))
        if c["FAIL_short"]:
            flags.append((kind, k, "FAIL_short", c["FAIL_short"], "list stopped short of the header with no server end recorded (paging/cap in our code)"))
        if dup:
            flags.append((kind, k, "duplicate ids", dup, "merge or paging repeated items"))
        if kind != "fast_c32" and c["no_header"]:
            flags.append((kind, k, "no_header", c["no_header"], "header not read (deep must load the profile page)"))
    req = Counter(f for r in rs for f in r["req_missing"])
    fills = defaultdict(Counter)
    for r in rs:
        for f, v in r["fill"].items():
            fills[f]["n/a" if v is None else ("ok" if v else "missing")] += 1
    lines += ["", f"Required fields missing: {dict(req) or 'none'}", "",
              "| Deep-fill item | ok | missing | n/a |", "|---|---|---|---|"]
    for f, c in fills.items():
        lines.append(f"| {f} | {c['ok']} | {c['missing']} | {c['n/a']} |")
        if kind != "fast_c32" and c["missing"]:
            flags.append((kind, f, "not filled", c["missing"], "full/deep pull left a field a complete record needs"))
    if req and kind != "fast_c32":
        flags.append((kind, "required", "missing fields", sum(req.values()), str(dict(req))))
    lines.append("")

# did a later vm/ pull fill what the fast pull left?
pairs = Counter(); still = Counter()
for h, rs in people.items():
    fast = [r for r in rs if r["kind"] == "fast_c32"]; later = [r for r in rs if r["kind"] != "fast_c32"]
    if not fast or not later:
        continue
    f0 = max(fast, key=lambda r: r["finished"]); l0 = max(later, key=lambda r: r["finished"])
    if l0["finished"] <= f0["finished"]:
        continue
    pairs["people"] += 1
    for f, v in l0["fill"].items():
        if f0["fill"].get(f) is False:
            pairs[f] += 1
            if v is False:
                still[f] += 1
lines += ["## Fast pull followed by a later full/deep pull", "",
          f"People: {pairs['people']}. Items the fast pull lacked and the later pull still lacks: {dict(still) or 'none'} "
          f"(of {dict((k, v) for k, v in pairs.items() if k != 'people')})", ""]
for f, n in still.items():
    flags.append(("deep_after_fast", f, "deep did not fill", n, "deep pass skipped this item"))
lines += ["## Flags", ""] + ([f"- {k} / {t}: {what} x{n} — {cause}" for k, t, what, n, cause in flags] or ["- none"])
open(OUT_MD, "w").write("\n".join(lines) + "\n")
with open(OUT_ROWS, "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")
print("\n".join(lines[-(len(flags) + 2):]))
print(f"FLAGS={len(flags)}")
