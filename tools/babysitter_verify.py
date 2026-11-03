"""Babysitter verification pass over Data Feeder feeds (run with python3 -I; data dir passed as argv[1]).
Prints per-feed: rows, schema check, timestamp check, dedupe, coverage. Never prints usernames."""
import sys, os, json, re, collections, datetime as dt, glob, csv

D = sys.argv[1]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

def rows(path):
    out = []
    bad = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                bad += 1
    return out, bad

def ts_check(rs, key):
    missing = sum(1 for r in rs if not r.get(key))
    notiso = sum(1 for r in rs if r.get(key) and not ISO.match(str(r[key])))
    nonutc = sum(1 for r in rs if r.get(key) and ISO.match(str(r[key])) and not str(r[key]).endswith("Z") and "+00:00" not in str(r[key]))
    vals = sorted(str(r[key]) for r in rs if r.get(key))
    return dict(missing=missing, not_iso=notiso, non_utc=nonutc, min=vals[0] if vals else None, max=vals[-1] if vals else None)

def dupes(rs, keys):
    c = collections.Counter(tuple(str(r.get(k)) for k in keys) for r in rs)
    return sum(v - 1 for v in c.values() if v > 1)

def section(name):
    print("\n" + "=" * 8, name)

# ---------- ph_at_launch 2026-11-03 ----------
section("ph_at_launch/2026-11-03")
cov = json.load(open(f"{D}/atl/coverage.json"))
print("coverage.json:", {k: cov[k] for k in ("launches", "posts_200", "people", "profiles_200", "followers_complete", "followers_paging_errors", "ph_followers_rows", "wire_MB_metered", "proxy_usd_est", "first_fetch", "last_fetch")})
for fn, keys, dk in [("posts.jsonl", ["slug", "fetched_at", "makers", "hunter", "votes", "hide_votes_count"], ["slug"]),
                     ("makers.jsonl", ["username", "role", "fetched_at", "followers_total", "followers_complete"], ["username", "role"]),
                     ("products.jsonl", ["fetched_at"], None),
                     ("external.jsonl", ["fetched_at"], None)]:
    rs, bad = rows(f"{D}/atl/{fn}")
    ks = collections.Counter(k for r in rs for k in r.keys())
    present = {k: ks.get(k, 0) for k in keys}
    print(f"{fn}: rows={len(rs)} badjson={bad} key_presence={present}")
    print("   fetched_at:", ts_check(rs, "fetched_at"))
    if dk:
        print("   dupes on", dk, "=", dupes(rs, dk))
    if fn == "posts.jsonl":
        hv = collections.Counter(str(r.get("hide_votes_count")) for r in rs)
        votes = [r.get("votes") for r in rs]
        print("   hide_votes_count:", dict(hv), "votes>0:", sum(1 for v in votes if isinstance(v, (int, float)) and v > 0), "makers_empty:", sum(1 for r in rs if not r.get("makers")))
        print("   sample keys:", sorted(rs[0].keys())[:40])
    if fn == "makers.jsonl":
        print("   roles:", dict(collections.Counter(r.get("role") for r in rs)), "complete:", sum(1 for r in rs if r.get("followers_complete")), "capped:", sum(1 for r in rs if r.get("followers_capped")), "paging_err:", sum(1 for r in rs if r.get("followers_paging_err")))
    if fn == "external.jsonl":
        print("   sources:", dict(collections.Counter(f"{r.get('source')}:{r.get('status')}" for r in rs)))

# ---------- ph_people_daily 2026-11-03 ----------
section("ph_people_daily/2026-11-03")
rs, bad = rows(f"{D}/ppd/upvotes_page1.jsonl")
ks = collections.Counter(k for r in rs for k in r.keys())
need = ["username", "position", "post_id", "post_slug", "product_slug", "launched_at", "votes_total", "has_more", "source", "fetched_at"]
print("upvotes_page1.jsonl rows", len(rs), "badjson", bad, "people", len({r.get("username") for r in rs}), "missing keys:", {k: len(rs) - ks.get(k, 0) for k in need if ks.get(k, 0) != len(rs)})
print("   fetched_at:", ts_check(rs, "fetched_at"), "dupes(username,post_id):", dupes(rs, ["username", "post_id"]))
per = collections.Counter(r.get("username") for r in rs)
print("   rows/person: min", min(per.values()), "max", max(per.values()), "people with 20:", sum(1 for v in per.values() if v == 20))
fs, bad = rows(f"{D}/ppd/fetch_state_rows.jsonl")
print("fetch_state_rows rows", len(fs), "status:", dict(collections.Counter(str(r.get("status")) for r in fs)), "source:", dict(collections.Counter(r.get("source") for r in fs)))
print("following_page1.jsonl size", os.path.getsize(f"{D}/ppd/following_page1.jsonl"))

# ---------- rota ----------
section("ph_people_daily/2026-11-03_full_rota (attempt 1)")
rs, bad = rows(f"{D}/rota/attempt1_out_following.jsonl")
print("rows", len(rs), "status:", dict(collections.Counter(r.get("status") for r in rs)), "fetched_at:", ts_check(rs, "fetched_at"), "mean_wire_MB:", round(sum(r.get("wire_bytes", 0) for r in rs) / max(1, len(rs)) / 1e6, 2), "mean_secs:", round(sum(r.get("secs", 0) for r in rs) / max(1, len(rs)), 1))

# ---------- ph_userbase wayback_profiles ----------
section("ph_userbase/wayback_profiles.jsonl (v1 final)")
rs, bad = rows(f"{D}/ub/wayback_profiles.jsonl")
ks = collections.Counter(k for r in rs for k in r.keys())
need = ["launch_id", "source", "metric", "as_of_date", "count", "url", "capture_url", "username", "role", "launch_day", "capture_ts", "parse_route"]
print("rows", len(rs), "badjson", bad, "missing keys:", {k: len(rs) - ks.get(k, 0) for k in need if ks.get(k, 0) != len(rs)})
print("   metric:", dict(collections.Counter(r.get("metric") for r in rs)), "role:", dict(collections.Counter(r.get("role") for r in rs)), "parse_route:", dict(collections.Counter(r.get("parse_route") for r in rs)))
print("   count null:", sum(1 for r in rs if r.get("count") is None), "launches:", len({r.get("launch_id") for r in rs}), "people:", len({r.get("username") for r in rs}), "pairs:", len({(r.get("launch_id"), r.get("username")) for r in rs}))
print("   dupes (launch_id,username,metric):", dupes(rs, ["launch_id", "username", "metric"]))
# pre-launch rule: capture_ts (14-digit UTC) < 00:00 PT of launch_day
import zoneinfo
PT = zoneinfo.ZoneInfo("America/Los_Angeles")
viol = 0; chk = 0; ages = []
for r in rs:
    ct = str(r.get("capture_ts") or "")
    ld = r.get("launch_day")
    if len(ct) == 14 and ld:
        chk += 1
        c = dt.datetime.strptime(ct, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
        l0 = dt.datetime.strptime(ld, "%Y-%m-%d").replace(tzinfo=PT)
        if c >= l0:
            viol += 1
        ages.append((l0 - c).total_seconds() / 86400)
ages.sort()
print(f"   pre-launch rule checked {chk}, violations {viol}; age days median {ages[len(ages)//2]:.1f} p25 {ages[len(ages)//4]:.1f} p75 {ages[3*len(ages)//4]:.1f}" if ages else "   no capture_ts")
print("   launch_day range:", min(r.get("launch_day") for r in rs), max(r.get("launch_day") for r in rs))
print("   coverage.json:", json.load(open(f"{D}/ub/wayback_profiles_coverage.json")))
print("   done.json:", open(f"{D}/ub/wayback_profiles_done.json").read().strip())

# ---------- hn_early_votes_2025 ----------
def snap_stats(paths, label):
    section(label)
    tot = 0; ok = 0; items = 0; caps = set(); dup = 0; months = collections.Counter(); bad_total = 0; ts_bad = 0
    item_rows = 0; item_bad_created = 0; ranks = collections.Counter()
    for p in paths:
        rs, bad = rows(p)
        bad_total += bad
        for r in rs:
            tot += 1
            ct = str(r.get("capture_ts") or "")
            if not re.match(r"^\d{14}$", ct) and not ISO.match(ct):
                ts_bad += 1
            if ct in caps:
                dup += 1
            caps.add(ct)
            months[ct[:6]] += 1
            if r.get("ok"):
                ok += 1
                its = r.get("items") or []
                items += len(its)
                for it in its[:3]:
                    item_rows += 1
                    if not it.get("created_at"):
                        item_bad_created += 1
        print(f"  {os.path.basename(p)}: rows={len(rs)} badjson={bad}")
    print(f"TOTAL captures={tot} ok={ok} ({100*ok/max(1,tot):.1f}%) items={items} dup_capture_ts={dup} ts_bad={ts_bad} badjson={bad_total}; sampled items missing created_at: {item_bad_created}/{item_rows}")
    print("  by month:", dict(sorted(months.items())))
    return caps

cdx = [l.split()[1] if " " in l else l.strip() for l in open(f"{D}/hnev/cdx_newest.txt", encoding="utf-8", errors="replace") if l.strip()]
print("\ncdx_newest.txt lines:", len(cdx), "sample:", cdx[0][:80])
cdx_ts = []
for l in cdx:
    m = re.search(r"(\d{14})", l)
    if m:
        cdx_ts.append(m.group(1))
cm = collections.Counter(t[:6] for t in cdx_ts)
print("cdx by month:", dict(sorted(cm.items())))
caps1 = snap_stats(sorted(glob.glob(f"{D}/hnev/snapshots_*.jsonl")), "hn_early_votes_2025 Jan-Jun (work/snapshots_*.jsonl, shards + month queues)")
caps2 = snap_stats(sorted(glob.glob(f"{D}/hnev_jd/snapshots_*.jsonl")), "hn_early_votes_2025/jul_dec")
h1 = {t for t in cdx_ts if t[:6] <= "202506"}
h2 = {t for t in cdx_ts if t[:6] >= "202507"}
print(f"\nJan-Jun: cdx {len(h1)}, fetched distinct {len(caps1 & h1)} ({100*len(caps1&h1)/max(1,len(h1)):.1f}%), fetched not in cdx {len(caps1 - h1)}")
print(f"Jul-Dec: cdx {len(h2)}, fetched distinct {len(caps2 & h2)} ({100*len(caps2&h2)/max(1,len(h2)):.1f}%), fetched not in cdx {len(caps2 - h2)}")
print("overlap of the two sets (should be 0):", len(caps1 & caps2))
try:
    print("bq_month_counts.csv:", open(f"{D}/hnev/bq_month_counts.csv").read().strip().replace("\n", " | ")[:400])
except Exception as e:
    print("bq_month_counts", e)

# ---------- hn_qn_series ----------
section("hn_qn_series/2026-09/status.jsonl")
rs, bad = rows(f"{D}/qn/status.jsonl")
last = {}
for r in rs:
    last[r.get("story_id")] = r
print("lines", len(rs), "distinct stories", len(last), "badjson", bad)
print("   has_page:", dict(collections.Counter(str(r.get("has_page")) for r in last.values())), "fetched:", dict(collections.Counter(str(r.get("fetched")) for r in last.values())))
print("   http:", dict(collections.Counter(str(r.get("http")) for r in last.values() if r.get("http") is not None)))
print("   points>=3:", sum(1 for r in last.values() if (r.get("points_final") or 0) >= 3), "of which fetched:", sum(1 for r in last.values() if (r.get("points_final") or 0) >= 3 and r.get("fetched")))
print("   fetched_at:", ts_check([r for r in last.values() if r.get("fetched_at")], "fetched_at"))
cr = sorted(str(r.get("created_at")) for r in last.values() if r.get("created_at"))
print("   created_at range:", cr[0] if cr else None, cr[-1] if cr else None)

# ---------- ph_makers_resolved ----------
section("ph_makers_resolved/makers_by_product.jsonl")
rs, bad = rows(f"{D}/mk/makers_by_product.jsonl")
print("rows", len(rs), "badjson", bad, "dupes slug:", dupes(rs, ["slug"]), "fetched_at:", ts_check(rs, "fetched_at"))
print("   parse_status:", dict(collections.Counter(r.get("parse_status") for r in rs)), "fetch_status:", dict(collections.Counter(str(r.get("fetch_status")) for r in rs)))
print("   resolved (makers non-empty):", sum(1 for r in rs if r.get("makers")), "parser:", dict(collections.Counter(r.get("parser") for r in rs)))
print("   summary.json:", json.load(open(f"{D}/mk/summary.json")).get("resolved"))

# ---------- ph_team_history ----------
section("ph_team_history")
rs, bad = rows(f"{D}/team/ph_team_history.jsonl")
ks = collections.Counter(k for r in rs for k in r.keys())
need = ["username", "role", "post_id", "slug", "name", "featuredAt", "createdAt", "votesCount", "dailyRank", "fetched_at"]
print("rows", len(rs), "badjson", bad, "missing keys:", {k: len(rs) - ks.get(k, 0) for k in need if ks.get(k, 0) != len(rs)})
print("   posts:", len({r.get("post_id") for r in rs}), "people:", len({r.get("username") for r in rs}), "roles:", dict(collections.Counter(r.get("role") for r in rs)), "dupes(username,post_id,role):", dupes(rs, ["username", "post_id", "role"]))
print("   fetched_at:", ts_check(rs, "fetched_at"))
fa = sorted(str(r.get("featuredAt")) for r in rs if r.get("featuredAt"))
print("   featuredAt range:", fa[0], fa[-1], "redacted usernames:", sum(1 for r in rs if "REDACTED" in str(r.get("username"))))
st, bad = rows(f"{D}/team/status.jsonl")
print("   status.jsonl lines", len(st), dict(collections.Counter(str(r.get("status") or r.get("ok")) for r in st)))

# ---------- github_stargazers dedup ----------
section("github_stargazers/dedup/star_history_dedup.jsonl")
n = 0; bad = 0; repos = set(); pairs = set(); dup = 0; neg = 0; dates = []; nonint = 0
with open(f"{D}/gh/star_history_dedup.jsonl", encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            bad += 1; continue
        n += 1
        k = (r.get("repo"), r.get("date"))
        if k in pairs:
            dup += 1
        pairs.add(k)
        repos.add(r.get("repo"))
        s = r.get("stars")
        if not isinstance(s, int):
            nonint += 1
        elif s < 0:
            neg += 1
        if n % 50 == 0:
            dates.append(str(r.get("date")))
dates.sort()
print("rows", n, "badjson", bad, "repos", len(repos), "dupes(repo,date)", dup, "stars non-int", nonint, "negative", neg, "date range (sampled)", dates[0] if dates else None, dates[-1] if dates else None)
rs, bad = rows(f"{D}/gh/repo_status.jsonl")
print("repo_status.jsonl rows", len(rs), dict(collections.Counter(str(r.get("status"))[:12] for r in rs).most_common(6)))
exp = sum(r.get("stars_expected") or 0 for r in rs if r.get("status") == "ok"); got = sum(r.get("stars_fetched") or 0 for r in rs if r.get("status") == "ok")
print("   ok repos: stars_expected", exp, "stars_fetched", got, f"({100*got/max(1,exp):.1f}%)")
rs2, bad = rows(f"{D}/gh/repo_status_ph.jsonl")
print("repo_status_ph.jsonl rows", len(rs2), dict(collections.Counter(str(r.get("status"))[:12] for r in rs2).most_common(6)))
print("progress.json:", open(f"{D}/gh/progress.json").read().strip())
