"""A1 fetch: every featured Product Hunt post per Pacific day, DAY_FROM..DAY_TO (default 2024-01-01..2025-12-31,
newest first), with its makers and hunter, from the official API, giving each team's launch history before our data
starts (Jan 2026). user.madePosts / submittedPosts return nothing for other users (tested Nov 2 on makers with 20+
launches), so history is rebuilt from the posts list instead. Maker usernames come back as [REDACTED] for about 40% of
makers (privacy setting); those rows are skipped. Output rows are per (username, post) in the a1_team_history.py schema. Runs on usersim-pipeline as agent with the pipeline's own key in
PH_TOKEN (never printed). Read-only.
Budget: the API allows 6,250 complexity per 15 min and the hourly vote recorder (pipeline.hourly) uses the same key at
the top of each hour, so this job
  - keeps at least RESERVE (default 1,500) of the budget free, waiting for the reset below it;
  - pauses from minute 56 to minute 8 of every hour;
  - waits out rate_limit_reached (reset_in + 5 s) and network errors;
  - stops at STOP_UTC (default 07:30, before the 00:05 PT run) and resumes from where it stopped on the next start.
Output (local, then copied to the bucket every UPLOAD_EVERY users and at the end):
  ~/a1_fetch/ph_team_history.jsonl  one row per (username, post): username, role (maker | hunter), post_id, slug, name,
                                    featuredAt, createdAt, votesCount, dailyRank, fetched_at
  ~/a1_fetch/status.jsonl           one row per day: day, status, posts, rows, calls
  -> gs://.../raw/ph_team_history/ (+ README.md at the end)
usage: PH_TOKEN=... python3 a1_fetch.py"""
import datetime as dt, json, os, subprocess, sys, time, urllib.error, urllib.request

URL = "https://api.producthunt.com/v2/api/graphql"
BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_team_history"
OUT = os.path.expanduser("~/a1_fetch"); os.makedirs(OUT, exist_ok=True)
RESERVE = int(os.environ.get("RESERVE", "1500"))
STOP_UTC = os.environ.get("STOP_UTC", "07:30")
UPLOAD_EVERY = int(os.environ.get("UPLOAD_EVERY", "60"))
DAY_FROM, DAY_TO = os.environ.get("DAY_FROM", "2024-01-01"), os.environ.get("DAY_TO", "2025-12-31")
Q = """query($a:DateTime!,$b:DateTime!,$c:String){ posts(first:20, after:$c, featured:true, postedAfter:$a, postedBefore:$b,
 order:NEWEST){ pageInfo{hasNextPage endCursor} edges{node{ id slug name featuredAt createdAt votesCount dailyRank
 makers{username} user{username} }}}}"""
STATS = {"calls": 0, "cost_samples": []}
SEEN = set()


def now():
    return dt.datetime.now(dt.timezone.utc)


def past_stop():
    h, m = map(int, STOP_UTC.split(":"))
    t = now()
    return (t.hour, t.minute) >= (h, m) and t.hour < 12   # the stop is in the early UTC morning (PT night)


def hour_pause():
    while now().minute >= 56 or now().minute < 8:
        time.sleep(30)


def gql(variables):
    while True:
        hour_pause()
        req = urllib.request.Request(URL, json.dumps({"query": Q, "variables": variables}).encode(),
                                     {"Authorization": "Bearer " + os.environ["PH_TOKEN"], "Content-Type": "application/json",
                                      "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body, h = json.load(r), r.headers
        except urllib.error.HTTPError as e:
            body, h = (json.loads(e.read() or b"{}") if e.code != 429 else {"errors": [{"error": "rate_limit_reached", "details": {"reset_in": e.headers.get("x-rate-limit-reset") or 60}}]}), e.headers
        except Exception as e:  # noqa: BLE001
            print("net error", str(e)[:120], flush=True); time.sleep(15); continue
        STATS["calls"] += 1
        errs = body.get("errors") or []
        if errs and errs[0].get("error") == "rate_limit_reached":
            wait = int(float(errs[0].get("details", {}).get("reset_in", 60))) + 5
            print(f"rate limited, sleeping {wait}s", flush=True); time.sleep(wait); continue
        rem, reset = h.get("x-rate-limit-remaining"), h.get("x-rate-limit-reset")
        if rem is not None and int(rem) < RESERVE:
            wait = int(float(reset or 60)) + 5
            print(f"budget {rem} < reserve {RESERVE}, sleeping {wait}s", flush=True); time.sleep(wait)
        return body, rem


def window(d):
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
    return (dt.datetime.combine(d, dt.time(0), PT).isoformat(), dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT).isoformat())


def fetch_day(d):
    a, b = window(d); cur, rows, posts, calls = None, [], 0, 0
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
    while True:
        body, rem = gql({"a": a, "b": b, "c": cur}); calls += 1
        if body.get("errors"):
            return rows, posts, "error:" + json.dumps(body["errors"])[:200], calls
        c = (body.get("data") or {}).get("posts") or {}
        for e in c.get("edges") or []:
            n = e["node"]   # no day filter: the window is on creation time, so a post can show up under the day before its
            if str(n["id"]) in SEEN:   # feature day; keep it once wherever it appears (the analysis dates it by featuredAt)
                continue
            SEEN.add(str(n["id"])); posts += 1
            base = {"post_id": str(n["id"]), "slug": n.get("slug"), "name": n.get("name"), "featuredAt": n.get("featuredAt"),
                    "createdAt": n.get("createdAt"), "votesCount": n.get("votesCount"), "dailyRank": n.get("dailyRank"),
                    "fetched_at": now().strftime("%Y-%m-%dT%H:%M:%SZ")}
            people = [("maker", m.get("username")) for m in (n.get("makers") or [])] + [("hunter", (n.get("user") or {}).get("username"))]
            for role, u in people:
                if u and u != "[REDACTED]":
                    rows.append({"username": u, "role": role, **base})
        pi = c.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            return rows, posts, "ok", calls
        cur = pi.get("endCursor")


def upload(final=False):
    for f in ("ph_team_history.jsonl", "status.jsonl"):
        subprocess.run(["gsutil", "-q", "cp", os.path.join(OUT, f), f"{BUCKET}/{f}"], check=False)
    if final:
        st = [json.loads(l) for l in open(os.path.join(OUT, "status.jsonl"))]
        from collections import Counter
        c = Counter(s["status"].split(":")[0] for s in st)
        txt = (f"# ph_team_history (PH ops, A1)\nRoute: official PH API v2 posts(featured, per Pacific day {DAY_FROM}..{DAY_TO}, NEWEST), run on usersim-pipeline as "
               f"agent with the pipeline's key, paced (reserve {RESERVE} of 6,250 per 15 min, paused :56-:08 for the hourly recorder).\n"
               f"user.madePosts / submittedPosts return nothing for other users, so history comes from the posts list; [REDACTED] makers skipped.\n"
               f"Days done {len(st)}: {dict(c)}. Posts {sum(s['posts'] for s in st)}, rows {sum(s['rows'] for s in st)}, calls {sum(s['calls'] for s in st)}.\n"
               f"Files: ph_team_history.jsonl (username, role, post_id, slug, name, featuredAt, createdAt, votesCount, dailyRank, "
               f"fetched_at), status.jsonl. votesCount is read now; the analysis uses only posts dated before each launch's day.\n"
               f"Finished {now().strftime('%Y-%m-%dT%H:%MZ')}. Usernames: never commit this data.\n")
        open(os.path.join(OUT, "README.md"), "w").write(txt)
        subprocess.run(["gsutil", "-q", "cp", os.path.join(OUT, "README.md"), f"{BUCKET}/README.md"], check=False)


def main():
    d0, d1 = dt.date.fromisoformat(DAY_FROM), dt.date.fromisoformat(DAY_TO)
    days = [d1 - dt.timedelta(days=k) for k in range((d1 - d0).days + 1)]
    sf = os.path.join(OUT, "status.jsonl")
    done = {json.loads(l)["day"] for l in open(sf)} if os.path.exists(sf) else set()
    hf = os.path.join(OUT, "ph_team_history.jsonl")
    if os.path.exists(hf):
        SEEN.update(json.loads(l)["post_id"] for l in open(hf) if l.strip())
    todo = [d for d in days if d.isoformat() not in done]
    print(f"{len(days)} days, {len(done)} done, {len(todo)} to go; start {now():%H:%M} UTC", flush=True)
    t0 = time.time(); n = 0
    with open(os.path.join(OUT, "ph_team_history.jsonl"), "a") as fo, open(sf, "a") as fs:
        for d in todo:
            if past_stop():
                print(f"stop time {STOP_UTC} UTC reached; resumable", flush=True); break
            rows, posts, status, calls = fetch_day(d)
            for r in rows:
                fo.write(json.dumps(r) + "\n")
            fs.write(json.dumps({"day": d.isoformat(), "status": status, "posts": posts, "rows": len(rows), "calls": calls}) + "\n")
            fo.flush(); fs.flush(); n += 1
            if n % 20 == 0:
                rate = n / (time.time() - t0) * 3600
                print(f"{len(done) + n}/{len(days)} days (at {d}), {STATS['calls']} calls, {rate:.0f} days/h, ETA {(len(todo) - n) / max(rate, 1):.1f} h", flush=True)
            if n % UPLOAD_EVERY == 0:
                upload()
    upload(final=len(done) + n >= len(days))
    print(f"finished {len(done) + n}/{len(days)} days, {STATS['calls']} calls", flush=True)


if __name__ == "__main__":
    main()
