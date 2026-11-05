"""Data completeness watch (Shreyas, Nov 4 ~20:30 UTC: "we will pull every piece of information we get on every single
person"; alert him if any agent caps or truncates a pull). Counts only: no usernames are printed or written.

Checks, each against the previous run's state (STATE file), so only NEW truncation alerts:
  store_v3 tabs.parquet   per tab: short pulls split into PH server end (complete_not_visible, or upvotes ending at
                          PH's ~200), near complete (deleted items) and code_stop (our code stopped): only code_stop alerts
  ph_at_launch makers     today's and yesterday's makers.jsonl: followers_cap set, followers_capped, followers_complete False
  mailbox from_grokbot    new or changed files whose text mentions a cap / limit on what is pulled
                          (cap, capped, limit to, limited, newest N, first N, max_*, truncat, skip, only page 1)
Prints one JSON line; "alerts" lists every new finding (empty = nothing new).
usage: python completeness_watch.py [state.json]"""
import datetime as dt, json, os, re, subprocess, sys, tempfile
import pandas as pd

B = "gs://usersim-bakeoff-347838016394/usersim_sim"
STATE = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.completeness_watch.json")
CAP_RE = re.compile(r"(--[\w-]*(?:cap|max)[\w-]*[ =]\d+|\bcap(?:ped)?\s*(?:at|to|=|:)\s*\d|\blimit(?:ed)?\s+(?:to|at)\s+\d|(?<!/)\bnewest\s+\d{2,}\b(?!\s*(?:stories|posts))|\bmax[_-][a-z_]+\s*=\s*\d+|\b(?:LIST_CAP|CAP_MB|max_pages|max_items)\b\s*=?\s*\d+|\bfirst\s+\d{2,}\s+(?:people|items|pages|followers|upvotes)|\bskip(?:s|ped)?\s+(?:people|handles|tabs|pages)|\bcap\b:?\s*(?:above|over|of)\s+[\d,]+|only page ?1\b|truncat\w*)", re.I)  # explicit limits only


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)


def tabs():
    d = tempfile.mkdtemp(prefix="cw_"); f = f"{d}/tabs.parquet"
    if sh("gsutil", "-q", "cp", f"{B}/raw/population/store_v3/tabs.parquet", f).returncode:
        return {}
    T = pd.read_parquet(f)
    out = {}
    # Shreyas's whole-person rule (Nov 5 ~03:00Z, AGENTS.md): no lists-only / light / fast / two-pass pulls. Track people
    # whose pull_type is not a full pull, so any new one alerts.
    pt = T.drop_duplicates("person_id").pull_type.astype(str) if "pull_type" in T else pd.Series(dtype=str)
    out["_pull_types"] = {k: int(v) for k, v in pt.value_counts().items()}
    # breach tail closed at 04:05:37Z Nov 5 (VM-2 STOP; babysitter logs): only non-full pulls fetched after it count
    cut = pd.Timestamp(os.environ.get("RULE_CUTOFF", "2026-11-05T04:05:37Z"))
    P = T.groupby("person_id").agg(pt=("pull_type", "first"), f=("fetched_at", "max")) if "pull_type" in T else pd.DataFrame(columns=["pt", "f"])
    late = P[(P.pt.astype(str) != "full") & (pd.to_datetime(P.f, utc=True) > cut)]
    out["_after_rule"] = {k: int(v) for k, v in late.pt.astype(str).value_counts().items()}
    for t, g in T.groupby("tab"):
        inc = g[~g.complete.astype(bool)]
        cls = inc.apply(short_kind, axis=1) if len(inc) else pd.Series(dtype=str)
        out[t] = {"people": int(len(g)), "incomplete": int(len(inc)), "stopped_early": int(g.stopped_early.astype(bool).sum()),
                  "header_total": int(g.header.fillna(0).sum()), "rows_got": int(g["count"].sum()),
                  "server_end": int((cls == "server_end").sum()), "near_complete": int((cls == "near_complete").sum()),
                  "code_stop": int((cls == "code_stop").sum()),
                  "unclear": int((cls == "unclear").sum()),
                  "code_stop_rows_missing": int((inc.header.fillna(0) - inc["count"])[cls == "code_stop"].sum()) if len(inc) else 0}
    return out


def short_kind(r):
    """Why a tab is short of its header count (orchestrator, Nov 4 20:24 UTC: alert Shreyas only on our code stopping).
    server_end: PH's server stopped listing (the pull flags complete_not_visible, or an upvote list ends at PH's ~200
    limit, 185-205 rows); near_complete: within max(3, 2%) of the header (deleted / hidden items); code_stop: anything
    else, i.e. our code stopped early."""
    h, c = float(r.header or 0), float(r["count"] or 0)
    if bool(r.get("complete_not_visible")) or (r.tab == "upvotes" and 185 <= c <= 205 and h > c):
        return "server_end"
    # babysitter (Nov 4 23:36Z, from paging records): PH's signed-out ~200-slot upvote cap counts hidden / de-listed
    # posts as slots, so lists of 140-185 rows with headers above 200 end at the same PH cap; small lists miss up to
    # ~10% to posts PH counts in the header but won't list
    if r.tab == "upvotes" and h > 205 and 140 <= c < 185:
        return "server_end"
    if r.tab == "upvotes" and h - c <= 0.10 * h:
        return "near_complete"
    # pgql fast pulls carry no budget / partial / truncated field (population agent paging records, Nov 4 23:31Z): their
    # lists end at PH's server (signed-out ~200 upvotes, header counting hidden / de-listed posts). Exception under
    # review: upvote headers above 200 that end before page 10 (unclear: reported, not alerted).
    if str(r.get("pull_type")) == "pgql":
        return "unclear" if (r.tab == "upvotes" and h > 205 and c < 185) else "server_end"
    if h - c <= max(3, 0.02 * h):
        return "near_complete"
    # population agent (Nov 5 09:30Z): small follower / following lists that PH ends on page 1 (hasNextPage false) below
    # the header are PH's own end; tabs.parquet carries no paging trail, so report these as unclear, not code stops
    if r.tab in ("followers", "following") and h <= 50 and c < 20 + 1:
        return "unclear"
    return "code_stop"


def makers():
    out = {}
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-8))).date()
    for d in (today, today - dt.timedelta(days=1)):
        r = sh("gsutil", "cat", f"{B}/raw/ph_at_launch/{d}/makers.jsonl")
        if r.returncode:
            continue
        R = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        out[str(d)] = {"makers": len(R), "cap_set": sum(1 for x in R if x.get("followers_cap") not in (None, 0)),
                       "capped": sum(1 for x in R if x.get("followers_capped")),
                       "caps": sorted({x.get("followers_cap") for x in R if x.get("followers_cap") not in (None, 0)})}
    return out


def mailbox(prev):
    r = sh("gsutil", "ls", "-l", f"{B}/mailbox/from_grokbot/")
    seen, hits = dict(prev or {}), []
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) < 3 or not p[2].startswith("gs://"):
            continue
        key, stamp = p[2], p[1]
        if seen.get(key) == stamp:
            continue
        seen[key] = stamp
        if prev is None:   # first run: record, don't alert on history
            continue
        txt = sh("gsutil", "cat", key).stdout
        # a mention counts only if it is not about removing a cap or about a spend / concurrency limit
        NOT_DATA = re.compile(r"remov|gone|no[- ]?caps?|nocap|lifted|dropped the|concurren|rate cap|\$|usd|budget|29e9|bytes|c\d+\b|ports?", re.I)
        live = [x for x in CAP_RE.finditer(txt) if not NOT_DATA.search(txt[max(0, x.start() - 120): x.end() + 120])]
        m = [x.group(0) for x in live]
        if m:
            ctx = []
            for x in live[:3]:
                s = txt[max(0, x.start() - 90): x.end() + 90].replace("\n", " ")
                ctx.append(re.sub(r"@\w+", "@<user>", s))
            hits.append({"file": key.rsplit("/", 1)[-1], "matches": sorted(set(m))[:8], "context": ctx})
    return seen, hits


def main():
    prev = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = {"tabs": tabs(), "makers": makers()}
    seen, mail = mailbox(prev.get("mail_seen"))
    alerts = []
    for k, v in (now["tabs"].get("_after_rule") or {}).items():
        was = ((prev.get("tabs") or {}).get("_after_rule") or {}).get(k, 0)
        if v > was:
            alerts.append(f"whole-person rule: {v - was} new people with pull_type '{k}' fetched after the 04:05Z Nov 5 cutoff ({was} -> {v})")
    for t, v in now["tabs"].items():
        if t.startswith("_"):
            continue
        p = (prev.get("tabs") or {}).get(t, {})
        # alert only on our code stopping (server ends at PH's limits and near-complete lists are reported, not alerted)
        if v["code_stop"] > p.get("code_stop", 0):
            alerts.append(f"store_v3 {t}: code stopped early on {v['code_stop']} people (was {p.get('code_stop', 0)}), "
                          f"{v['code_stop_rows_missing']} rows missing vs headers; PH server end {v['server_end']}, near complete {v['near_complete']}")
    for d, v in now["makers"].items():
        p = (prev.get("makers") or {}).get(d, {})
        if v["cap_set"] or v["capped"]:
            if (v["cap_set"], v["capped"]) != (p.get("cap_set"), p.get("capped")):
                alerts.append(f"makers {d}: follower cap set on {v['cap_set']} of {v['makers']} (caps {v['caps']}), capped {v['capped']}")
    for h in mail:
        alerts.append(f"mailbox {h['file']}: mentions {h['matches']}")
    json.dump({**now, "mail_seen": seen, "at": dt.datetime.now(dt.timezone.utc).isoformat()}, open(STATE, "w"))
    print(json.dumps({"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "alerts": alerts, "mail_context": [h["context"] for h in mail],
                      "tabs": now["tabs"], "makers": now["makers"]}))


if __name__ == "__main__":
    main()
