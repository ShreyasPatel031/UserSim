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
# During a live day the ranking changes between pages, so RANKING paging repeats some launches and skips others
# (Oct 31: SKI and Specsight twice, Godwit and AwaitIO missing). NEWEST is a stable order for live days.
Q_NEWEST = Q.replace("order:RANKING", "order:NEWEST")


def on_day(nodes, d):
    """Keep the launches featured on Pacific day d. The API window filters on when a post was created, so a post
    created on d but scheduled for 00:00 PT on d + 1 came back for d as well (204 launches in Apr-May sat in two files)."""
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
    keep = lambda n: not n.get("featuredAt") or dt.datetime.fromisoformat(n["featuredAt"].replace("Z", "+00:00")).astimezone(PT).date() == d
    return [n for n in nodes if keep(n)]


def window(d):
    """[00:00 PT on d, 00:00 PT on d + 1) as ISO strings, with the right offset on both sides of DST."""
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
    return (dt.datetime.combine(d, dt.time(0), PT).isoformat(), dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT).isoformat())


def gql(variables, query=None):
    while True:
        req = urllib.request.Request(URL, json.dumps({"query": query or Q, "variables": variables}).encode(),
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
            a, b = window(d)
            nodes, cur = [], None
            while True:
                p, rem = gql({"a": a, "b": b, "c": cur})
                nodes += [e["node"] for e in p["edges"]]
                if not p["pageInfo"]["hasNextPage"]:
                    break
                cur = p["pageInfo"]["endCursor"]
            seen = set(); nodes = [n for n in nodes if not (str(n["id"]) in seen or seen.add(str(n["id"])))]   # keep each launch once
            nodes = on_day(nodes, d)
            f.write_text(json.dumps(nodes))
            print(d, len(nodes), "remaining", rem, flush=True)
        d -= dt.timedelta(days=1)


if __name__ == "__main__":
    main(dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2]))
