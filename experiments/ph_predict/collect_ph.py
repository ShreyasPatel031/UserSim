"""Pull every featured Product Hunt launch per day (Pacific days), newest first, into data/days/<date>.json.

Labels (votesCount, commentsCount, daily/weekly/monthlyRank) are stored but never used as features.
Waits out the API's complexity budget (6,250 per 15 min) instead of failing."""
import datetime as dt, json, os, sys, time, pathlib, urllib.request

OUT = pathlib.Path(__file__).parent / "data" / "days"
URL = "https://api.producthunt.com/v2/api/graphql"
FIELDS = """id name tagline slug createdAt featuredAt website votesCount commentsCount dailyRank weeklyRank monthlyRank
description topics(first:6){edges{node{name}}} media{type}
makers{id username name headline followersCount twitterUsername websiteUrl createdAt}
user{id username name headline followersCount twitterUsername createdAt}"""
Q = """query($a:DateTime!,$b:DateTime!,$c:String){ posts(first:20, after:$c, featured:true, postedAfter:$a,
postedBefore:$b, order:RANKING){ totalCount pageInfo{hasNextPage endCursor} edges{node{%s}}}}""" % FIELDS


def gql(variables):
    while True:
        req = urllib.request.Request(URL, json.dumps({"query": Q, "variables": variables}).encode(),
                                     {"Authorization": "Bearer " + os.environ["PH_TOKEN"],
                                      "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body, rem = json.load(r), r.headers.get("x-rate-limit-remaining")
        except urllib.error.HTTPError as e:
            body, rem = json.loads(e.read() or b"{}"), e.headers.get("x-rate-limit-remaining")
        except Exception as e:  # noqa: BLE001
            print("net error", e, flush=True); time.sleep(10); continue
        errs = body.get("errors") or []
        if errs and errs[0].get("error") == "rate_limit_reached":
            wait = int(errs[0]["details"]["reset_in"]) + 5
            print(f"rate limited, sleeping {wait}s", flush=True); time.sleep(wait); continue
        if errs:
            raise RuntimeError(errs)
        return body["data"]["posts"], rem


def main(start, end):
    d = end
    while d >= start:
        f = OUT / f"{d}.json"
        if not f.exists():
            a, b = f"{d}T00:00:00-07:00", f"{d + dt.timedelta(days=1)}T00:00:00-07:00"
            if d < dt.date(2026, 3, 8):  # PST before DST
                a, b = a.replace("-07:00", "-08:00"), b.replace("-07:00", "-08:00")
            nodes, cur = [], None
            while True:
                p, rem = gql({"a": a, "b": b, "c": cur})
                nodes += [e["node"] for e in p["edges"]]
                if not p["pageInfo"]["hasNextPage"]:
                    break
                cur = p["pageInfo"]["endCursor"]
            seen = set(); nodes = [n for n in nodes if not (str(n["id"]) in seen or seen.add(str(n["id"])))]   # keep each launch once
            f.write_text(json.dumps(nodes))
            print(d, len(nodes), "remaining", rem, flush=True)
        d -= dt.timedelta(days=1)


if __name__ == "__main__":
    main(dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2]))
