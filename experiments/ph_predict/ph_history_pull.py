"""Product Hunt day lists for 2024 and 2023 (same query and file shape as raw/ph_history/2025). PREPARED, NOT STARTED: runs only after
Shreyas's direct yes; start with run_history_pull.sh start.

Query: official PH API v2 posts(featured:true, postedAfter, postedBefore, order:RANKING) per Pacific day, first:20 pages, no page or
item cap; posts kept only if featuredAt falls on that PT day; deduped by id; raw nodes kept as returned (2025 field set).
Output: <WORK>/<year>/<YYYY-MM-DD>.json, copied to $BUCKET/raw/ph_history/<year>/, one manifest.jsonl row per day (same format as 2025).
Resumable: a day is skipped if its file is already in the bucket or in WORK (the 8 landed 2024 days, Jan 1-8, are never rewritten).
Spare complexity only: before every call, if x-rate-limit-remaining minus the last call's cost would fall below RESERVE (3125 of 6250,
the live loop's 50% reserve) it sleeps to the window reset. Hard pauses 23:45-01:00 PT (23:45-00:15 nightly re-read / 00:00-00:07
capture, and nothing on the pipeline VM 00:05-01:00).
Token: PH_TOKEN env only, set by run_history_pull.sh the same way run_daily.sh sets it. Never printed.
usage: python3 ph_history_pull.py [--years 2024,2023] [--dry-run] [--manifest local.jsonl] [--no-gcs]"""
import argparse, datetime as dt, json, math, os, subprocess, sys, time, urllib.error, urllib.request
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
URL = "https://api.producthunt.com/v2/api/graphql"
BUCKET = os.environ.get("BUCKET", "gs://usersim-bakeoff-347838016394/usersim_sim") + "/raw/ph_history"
WORK = os.path.expanduser(os.environ.get("WORK", "~/w/ph_history"))
RESERVE = int(os.environ.get("RESERVE", "3125"))
SOURCE = "PH API v2 official, featured:true, order RANKING, PT day postedAfter/postedBefore"
FIELDS = """id name tagline slug createdAt featuredAt website votesCount commentsCount dailyRank weeklyRank monthlyRank
reviewsCount reviewsRating description topics(first:6){edges{node{name}}} media{type}
makers{id username name headline followersCount twitterUsername websiteUrl createdAt}
user{id username name headline followersCount twitterUsername createdAt}"""
Q = """query($a:DateTime!,$b:DateTime!,$c:String){ posts(first:20, after:$c, featured:true, postedAfter:$a,
postedBefore:$b, order:RANKING){ totalCount pageInfo{hasNextPage endCursor} edges{node{%s}}}}""" % FIELDS
PAGES_PER_DAY_2025 = 434 / 365  # 2025 pull: 434 calls for 365 days
ST = {"remaining": None, "reset": None, "last_cost": 300, "calls": 0}


def log(**k):
    print(json.dumps({"t": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **k}), flush=True)


def pause_left(now=None):
    """Seconds until 01:00 PT if now is inside 23:45-01:00 PT, else 0."""
    now = now or dt.datetime.now(PT)
    hm = now.hour * 60 + now.minute
    if hm >= 23 * 60 + 45:
        end = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(1), PT)
    elif hm < 60:
        end = dt.datetime.combine(now.date(), dt.time(1), PT)
    else:
        return 0
    return max(0, (end - now).total_seconds())


def wait_ok():
    while True:
        s = pause_left()
        if s:
            log(event="pause_pt", sleep_s=int(s) + 30); time.sleep(s + 30); continue
        r = ST["remaining"]
        if r is not None and r - ST["last_cost"] < RESERVE:
            s = (ST["reset"] if ST["reset"] is not None else 900) + 10
            log(event="reserve", remaining=r, last_cost=ST["last_cost"], sleep_s=int(s)); time.sleep(s)
            ST["remaining"] = None; continue
        return


def gql(variables):
    body = json.dumps({"query": Q, "variables": variables}).encode()
    for attempt in range(8):
        wait_ok()
        req = urllib.request.Request(URL, data=body, headers={"Authorization": "Bearer " + os.environ["PH_TOKEN"],
                                                              "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                h = r.headers; out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            h = e.headers; txt = e.read()
            try:
                out = json.loads(txt)
            except Exception:
                log(event="http_error", code=e.code, attempt=attempt); time.sleep(30 * (attempt + 1)); continue
        except Exception as e:
            log(event="net_error", err=type(e).__name__, attempt=attempt); time.sleep(10 * (attempt + 1)); continue
        ST["calls"] += 1
        rem, rst = h.get("x-rate-limit-remaining"), h.get("x-rate-limit-reset")
        if rem is not None:
            rem = int(rem)
            if ST["remaining"] is not None and 0 < ST["remaining"] - rem < 6250:
                ST["last_cost"] = ST["remaining"] - rem
            ST["remaining"] = rem
        if rst is not None:
            ST["reset"] = int(rst)
        errs = out.get("errors") or []
        rl = [e for e in errs if e.get("error") == "rate_limit_reached" or "rate" in str(e.get("message", "")).lower()]
        if rl:
            s = int((rl[0].get("details") or {}).get("reset_in", 900)) + 5
            log(event="rate_limit_reached", sleep_s=s); time.sleep(s); ST["remaining"] = None; continue
        if errs:
            log(event="gql_error", n=len(errs), attempt=attempt); time.sleep(30); continue
        return out["data"]["posts"]
    raise RuntimeError("gql failed 8 times")


def window(d):
    a = dt.datetime.combine(d, dt.time(0), PT); b = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT)
    return a.isoformat(), b.isoformat()


def on_day(n, d):
    f = n.get("featuredAt")
    return bool(f) and dt.datetime.fromisoformat(f.replace("Z", "+00:00")).astimezone(PT).date() == d


def fetch_day(d):
    a, b = window(d); cur = None; seen = {}; pages = 0
    while True:
        p = gql({"a": a, "b": b, "c": cur}); pages += 1
        for e in p["edges"]:
            n = e["node"]
            if on_day(n, d) and n["id"] not in seen:
                seen[n["id"]] = n
        if not p["pageInfo"]["hasNextPage"]:
            break
        cur = p["pageInfo"]["endCursor"]
    return list(seen.values()), pages


def days_for(year):
    d = dt.date(year, 1, 1)
    while d.year == year:
        yield d; d += dt.timedelta(days=1)


def bucket_days(years, no_gcs):
    have = set()
    if no_gcs:
        return have
    for y in years:
        r = subprocess.run(["gsutil", "ls", f"{BUCKET}/{y}/"], capture_output=True, text=True)
        have |= {ln.rsplit("/", 1)[-1][:-5] for ln in r.stdout.split() if ln.endswith(".json")}
    return have


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2024,2023"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--manifest", default=None, help="local manifest copy (default: bucket manifest)")
    ap.add_argument("--no-gcs", action="store_true", help="no bucket reads or writes (WORK + --manifest only)")
    a = ap.parse_args(); years = [int(y) for y in a.years.split(",")]
    os.makedirs(WORK, exist_ok=True); man = a.manifest or f"{WORK}/manifest.jsonl"
    if not a.manifest and not a.no_gcs:
        subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/manifest.jsonl", man], check=True)
    rows = [json.loads(l) for l in open(man) if l.strip()] if os.path.exists(man) else []
    done = {r["day"] for r in rows} | bucket_days(years, a.no_gcs)
    for y in years:
        if os.path.isdir(f"{WORK}/{y}"):
            done |= {f[:-5] for f in os.listdir(f"{WORK}/{y}") if f.endswith(".json")}
    todo = [d for y in years for d in days_for(y) if d.isoformat() not in done]
    p25 = [r["pages"] for r in rows if r.get("year") == 2025]
    ppd = sum(p25) / len(p25) if p25 else PAGES_PER_DAY_2025
    plan = {"years": years, "days_done": sum(1 for y in years for d in days_for(y) if d.isoformat() in done),
            "days_to_fetch": len(todo), "first": todo[0].isoformat() if todo else None, "last": todo[-1].isoformat() if todo else None,
            "per_year": {y: sum(1 for d in todo if d.year == y) for y in years}, "pages_per_day_2025": round(ppd, 3),
            "est_calls": math.ceil(len(todo) * ppd), "est_calls_range": [len(todo), math.ceil(len(todo) * ppd * 1.25)],
            "reserve": RESERVE, "pause_pt": "23:45-01:00", "work": WORK, "bucket": None if a.no_gcs else BUCKET}
    log(event="plan", dry_run=a.dry_run, **plan)
    if a.dry_run:
        return
    if not os.environ.get("PH_TOKEN"):
        sys.exit("PH_TOKEN not set (start through run_history_pull.sh)")
    for d in todo:
        nodes, pages = fetch_day(d); y = d.year; rel = f"{y}/{d.isoformat()}.json"
        os.makedirs(f"{WORK}/{y}", exist_ok=True); tmp = f"{WORK}/{rel}.tmp"
        json.dump(nodes, open(tmp, "w")); os.replace(tmp, f"{WORK}/{rel}")
        row = {"day": d.isoformat(), "year": y, "path": rel, "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "posts": len(nodes), "pages": pages, "source": SOURCE, "status": "DRAFT until agents verify"}
        with open(man, "a") as f:
            f.write(json.dumps(row) + "\n")
        if not a.no_gcs:
            subprocess.run(["gsutil", "-q", "cp", f"{WORK}/{rel}", f"{BUCKET}/{rel}"], check=True)
            subprocess.run(["gsutil", "-q", "cp", man, f"{BUCKET}/manifest.jsonl"], check=True)
        log(event="day", day=d.isoformat(), posts=len(nodes), pages=pages, calls=ST["calls"], remaining=ST["remaining"])
    log(event="done", calls=ST["calls"], days=len(todo))


if __name__ == "__main__":
    main()
