"""Data-quality check of every person pull (population agent; counts only in the report, per-person rows in GCS).

Scope: people_live/vm_pgql/_run_*/*.json (fast c32 list pulls) and people_live/vm/*.json (full + deep) finished since --since.
Per person and tab:
  complete      got >= 98% of the profile header (or header 0)
  ph_limit      short of the header but PH's server ended the list (complete_not_visible / paging ended at the server)
  FAIL_short    short of the header with no server end recorded (no-caps rule: our code stopped)
  FAIL_repeat   followers/following short of the header after a repeated page chain, with no server_end_offset end
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


PAGE_SIZE = 20  # PH followers/following GraphQL page size (pages x 20 tracks the header on full chains)


def _chain_repeated(t, run, k, got, dup):
    """True if the follower/following page chain recorded repeated pages: a dups counter > 0 in any paging record,
    duplicate item ids, or more pages than the items read can fill (pages x 20 >= items + 20)."""
    recs = [t.get("paging") or {}, (run.get("paging") or {}).get(k) or {}, ((run.get("timing") or {}).get(k) or {}).get("paging") or {}]
    if dup or any((r.get("dups") or 0) > 0 for r in recs):
        return True
    pages = max((r.get("pages") or 0) for r in recs)
    return bool(pages) and pages * PAGE_SIZE >= got + PAGE_SIZE


def tab_state(d, k):
    t = d.get(k)
    if not isinstance(t, dict):
        return "missing_tab", 0
    items = t.get("items") or []
    got = t.get("count", len(items))
    h = t.get("header") if t.get("header") is not None else (d.get("header") or {}).get(k)  # tab header may be an explicit null
    # activity: pgql saves raw nodes (no "type"/comment_id at top level) and full pulls save items; count a comment once per id
    ids = [x.get(IDK[k]) or x.get("url") or (x.get("comment") or {}).get("id") or x.get("id") for x in items if isinstance(x, dict)]
    ids = [i for i in ids if i]
    dup = len(ids) - len(set(ids))
    run = d.get("run") or {}
    ended = (t.get("paging") or {}).get("ended") or ((run.get("paging") or {}).get(k) or {}).get("ended") or \
        ((((run.get("timing") or {}).get(k) or {}).get("paging") or {}).get("ended"))  # full pulls record the end under run.timing
    if run.get("exh", {}).get(k) is True:
        ended = ended or "server_end"
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
    elif k in ("followers", "following") and _chain_repeated(t, run, k, got, dup):
        # E5 / orchestrator 22:15Z Nov 7: a repeated endCursor chain is not PH's own end. Short of the header, the tab
        # passes only on the offset re-page end (server_end_offset); complete_not_visible or server_end are not enough.
        v = "ph_limit" if ended == "server_end_offset" else "FAIL_repeat"
    elif (t.get("complete_not_visible") and not t.get("capped_large")) or ended in SERVER_END:
        v = "ph_limit"
    else:
        v = "FAIL_short"
    return v + ("+dup" if dup else ""), dup


def comment_time_ok(x):
    """A comment time is real unless it is PH's launch stamp (00:01:00 PT) or marked unknown. Checked 04:50Z against
    2,291 API comment createdAt: feed.occurredAt (not the launch stamp) matched 29/29 to the second; launch stamps 0/19."""
    t, src = x.get("datetime"), x.get("datetime_source")
    if not t or x.get("comment_time_unknown") or src in ("feed.occurredAt_launch_stamp", "unknown"):
        return False
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        lt = datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles"))
        return str(src).startswith("comment.createdAt") or src == "api_match" or lt.strftime("%H:%M:%S") != "00:01:00"
    except Exception:
        return False


def deep_fill(d):
    """what a complete record has that a lists-only pull lacks; None = not applicable"""
    hdr = d.get("header") or {}
    # header complete = the four core counts read (fast pulls often skip the profile page; deep must fill them)
    out = {"header": all(hdr.get(k) is not None for k in ("followers", "following", "hunted", "collections"))}
    rv = (d.get("reviews") or {}).get("items") or []
    rh = (d.get("reviews") or {}).get("header", hdr.get("reviews"))
    # rating-only reviews are never listed by PH: 0 items passes only on a recorded end (run.exh.reviews from SSR pageInfo)
    out["reviews_items"] = None if not rh else (bool(rv) or ((d.get("run") or {}).get("exh") or {}).get("reviews") is True)
    cols = (d.get("collections") or {}).get("items") or []
    need = [c for c in cols if (c.get("products_count") or 0) > 0]
    out["collection_items"] = None if not need else all(c.get("items") for c in need)
    fo = (d.get("forums") or {}).get("items") or []
    out["forum_threads"] = None if not fo else all(x.get("thread_full") for x in fo)
    ups = ((d.get("upvotes") or {}).get("items") or []) + ((d.get("hunted") or {}).get("items") or [])
    out["product_fields"] = None if not ups else sum(1 for x in ups if x.get("description") or x.get("votes") is not None) >= 0.9 * len(ups)
    cm = [x for x in (d.get("activity") or {}).get("items") or [] if "comment" in (x.get("type") or x.get("raw_type") or "").lower()]
    out["comment_times"] = None if not cm else all(comment_time_ok(x) for x in cm)
    return out


# deep_list entries (vm/deep_list/<handle>.<tag>.json): which tabs are already queued for the deep pass per person
queued = defaultdict(set)
for p_ in glob.glob(f"{D}/people_live/deep_list/*.json"):
    try:
        for l in open(p_):
            e = json.loads(l)
            queued[(e.get("handle") or "").lower()] |= set(e.get("tabs") or ["*"])
    except Exception:
        pass

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
    q = queued.get(h, set())
    for k in TABS:  # a short fast tab already on the person's deep_list is pending deep, not an open gap
        if kind == "fast_c32" and states[k].startswith("FAIL_short") and ("*" in q or k in q):
            states[k] = states[k].replace("FAIL_short", "queued_deep")
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
    lines += [f"## {kind}: {len(rs):,} pulls", "", "| Tab | complete | ph_limit | rating_only | FAIL_short | FAIL_repeat | queued_deep | partial | no_header | missing_tab | dup |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in TABS:
        c = Counter(r["states"][k].split("+")[0] for r in rs); dup = sum(1 for r in rs if "+dup" in r["states"][k])
        lines.append(f"| {k} | {c['complete']} | {c['ph_limit']} | {c['rating_only']} | {c['FAIL_short']} | {c['FAIL_repeat']} | {c['queued_deep']} | {c['partial']} | {c['no_header']} | {c['missing_tab']} | {dup} |")
        if c["FAIL_partial"]:
            flags.append((kind, k, "partial after no-budget build", c["FAIL_partial"], "a per-person budget/timeout still cut this tab (should not exist after 00:30Z)"))
        if c["FAIL_short"]:
            flags.append((kind, k, "FAIL_short", c["FAIL_short"], "list stopped short of the header with no server end recorded, and NOT on the person's deep_list (paging/cap in our code; nobody will fix it)"))
        if c["FAIL_repeat"]:
            flags.append((kind, k, "FAIL_repeat", c["FAIL_repeat"], "follower/following page chain repeated pages and stopped short of the header; needs the offset re-page (server_end_offset)"))
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


# ---------- person-level OUTPUT check (Shreyas, Nov 5 03:00Z): every saved person scored against the full definition ----------
# A saved person (latest vm/<h>.json) is COMPLETE only if: all 10 tabs present; header has followers, following, hunted,
# collections, stacks, reviews, upvotes; every list tab complete or server-ended (no FAIL_short / partial / no_header);
# collection items present for every collection with products; every forum thread opened; review items present if the header
# says reviews > 0; comment times present. Anything else = INCOMPLETE, and the report says why.
ALL_TABS = ("about", "forums", "activity", "upvotes", "hunted", "collections", "stacks", "reviews", "followers", "following")
HDR_KEYS = ("followers", "following", "hunted", "collections", "stacks", "reviews", "upvotes")


# signed-in upvotes queue: report.py's deep_list_latest.tsv (handle \t labels, "needs_signed_in:<tabs>") or a deep_list entry
signed_in_q = set()
if os.path.exists(f"{D}/deep_list_latest.tsv"):
    for l in open(f"{D}/deep_list_latest.tsv"):
        h_, _, lab = l.rstrip("\n").partition("\t")
        if re.search(r"needs_signed_in:[^;]*upvotes", lab):
            signed_in_q.add(h_.lower())
for p_ in glob.glob(f"{D}/people_live/deep_list/*.json"):
    try:
        for l in open(p_).read().replace("}{", "}\n{").splitlines():
            e = json.loads(l) if l.strip() else {}
            if "upvotes" in (e.get("tabs") or []) and re.search(r"signed.?in", str(e.get("reason") or "") + str(e.get("note") or ""), re.I):
                signed_in_q.add((e.get("handle") or "").lower())
    except Exception:
        pass


for p_ in glob.glob(f"{D}/signedin_upvotes/*.json"):  # babysitter queue raw/_babysitter/signedin_upvotes/<h>.json (bsit_full5)
    signed_in_q.add(os.path.basename(p_)[:-5].lower())


def signed_out_end(d):
    """Upvotes stopped at PH's signed-out ~200 end: tagged upvotes_capped (or 190-210 items short of the header) AND the
    paging record shows PH's end. Orchestrator 03:36Z: whole for the signed-out pass only if also queued for signed-in."""
    t = d.get("upvotes") or {}
    if not isinstance(t, dict):
        return False
    n = t.get("count", len(t.get("items") or []))
    h = t.get("header") if t.get("header") is not None else (d.get("header") or {}).get("upvotes")
    if not h or n >= 0.98 * h:
        return False
    run = d.get("run") or {}
    ended = (t.get("paging") or {}).get("ended") or ((run.get("paging") or {}).get("upvotes") or {}).get("ended") or \
        ((((run.get("timing") or {}).get("upvotes") or {}).get("paging") or {}).get("ended"))
    tagged = bool(t.get("upvotes_capped") or d.get("upvotes_capped") or 190 <= n <= 210)
    return tagged and (ended in SERVER_END or bool(t.get("complete_not_visible") and not t.get("capped_large")))


def person_complete(d, h=None):
    why = []
    if signed_out_end(d) and (h or "").lower() not in signed_in_q:
        why.append("upvotes:signed_out_end_not_queued_signed_in")
    for t in ALL_TABS:
        if not isinstance(d.get(t), dict):
            why.append(f"missing_tab:{t}")
    hdr = d.get("header") or {}
    miss = [k for k in HDR_KEYS if hdr.get(k) is None]
    if miss:
        why.append("header_missing:" + ",".join(miss))
    for k in TABS:
        st = tab_state(d, k)[0].split("+")[0]
        if st in ("FAIL_short", "FAIL_partial", "FAIL_repeat", "partial", "no_header", "queued_deep"):
            why.append(f"{k}:{st}")
    f = deep_fill(d)
    for k in ("collection_items", "forum_threads", "reviews_items", "comment_times"):
        if f.get(k) is False:
            why.append(f"not_filled:{k}")
    # products the person made: each needs its product-page fields (description or launches)
    mh = (d.get("about") or {}).get("maker_history") or []
    if isinstance(mh, list) and any(isinstance(x, dict) and not (x.get("description") or x.get("launches")) for x in mh):
        why.append("not_filled:maker_product_pages")
    # collections index vs header
    ch = (d.get("header") or {}).get("collections")
    cn = len((d.get("collections") or {}).get("items") or [])
    if ch and cn < ch and tab_state(d, "collections")[0].split("+")[0] != "ph_limit":  # short only with no recorded PH end
        why.append("collections:index_short")
    return not why, why


latest = {}
for p in glob.glob(f"{D}/people_live/vm/*.json"):
    try:
        d = json.load(open(p))
    except Exception:
        continue
    if isinstance(d, dict) and ("upvotes" in d or "header" in d):
        latest[handle_of(d, p)] = d
pc = Counter(); reasons = Counter(); origin = Counter(); so = Counter()
for h, d in latest.items():
    ok, why = person_complete(d, h)
    o = "pgql_lists_only" if "pgql" in str(d.get("method") or "").lower() and not (d.get("run") or {}).get("deep_passes") else \
        ("deep" if (d.get("run") or {}).get("deep_passes") else "full")
    pc[(o, ok)] += 1; origin[o] += 1
    if ok and signed_out_end(d):
        so[o] += 1
    for w in why:
        reasons[(o, w.split(":")[0] + ":" + w.split(":")[1].split(",")[0] if ":" in w else w)] += 1
inc = sum(v for (o, ok), v in pc.items() if not ok)
out = ["", "## PERSON-LEVEL OUTPUT CHECK (every saved person vs the full definition)", "",
       f"Saved people (latest vm/<h>.json): {len(latest):,}; COMPLETE {len(latest) - inc:,} (whole {len(latest) - inc - sum(so.values()):,}; "
       f"whole, signed-out {sum(so.values()):,} = upvotes at PH's signed-out end, queued for the signed-in pass); **INCOMPLETE {inc:,}**", "",
       "| Origin | saved | whole | whole, signed-out | INCOMPLETE |", "|---|---|---|---|---|"]
for o in ("full", "deep", "pgql_lists_only"):
    out.append(f"| {o} | {origin[o]:,} | {pc[(o, True)] - so[o]:,} | {so[o]:,} | {pc[(o, False)]:,} |")
out += ["", "Top reasons (origin, reason): " + "; ".join(f"{o} {w} x{n:,}" for (o, w), n in reasons.most_common(20))]
# merged pace-test people (raw/_pacetest/merged_ledger.txt): any later FAIL goes to Shreyas as GROKBOT URGENT
mled = set()
if os.path.exists(f"{D}/merged_ledger.txt"):
    mled = {l.strip().lower() for l in open(f"{D}/merged_ledger.txt") if l.strip() and not l.startswith("#")}
m_in = {h: d for h, d in latest.items() if h.lower() in mled}
m_bad = Counter(w.split(":")[0] + ":" + w.split(":")[1] if ":" in w else w for h, d in m_in.items() for w in person_complete(d, h)[1])
m_inc = sum(1 for h, d in m_in.items() if not person_complete(d, h)[0])
out += ["", f"Merged pace-test people: ledger {len(mled):,}; in vm/ {len(m_in):,}; **MERGED_INCOMPLETE {m_inc:,}**" + (f" (reasons: {dict(m_bad.most_common(6))})" if m_inc else "")]
open(OUT_MD, "a").write("\n".join(out) + "\n")
print("\n".join(out))
print(f"PERSON_INCOMPLETE={inc}")
print(f"MERGED_INCOMPLETE={m_inc} MERGED_IN_VM={len(m_in)}")
