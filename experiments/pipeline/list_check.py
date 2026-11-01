"""Check the day's launch list from the API against Product Hunt's own daily leaderboard page (read by Grok Bot,
docs/handoff/grokbot_leaderboard.md). On Oct 31 the API's RANKING paging repeated 2 launches and missed 2.
Matches by product slug, then by normalized name. Prints launches missing from the API list and launches repeated in
it; exits 1 if any are missing.
usage: python -m pipeline.list_check <YYYY-MM-DD> [leaderboard.json]   (default: newest raw/leaderboard/<day>_*.json in GCS)"""
import glob, json, os, re, subprocess, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.join(os.path.dirname(HERE), "ph_predict")
BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def leaderboard(day, path=None):
    if path is None:   # the featured tab (Grok Bot's <day>_<HHMM>PT_featured.json) when there is one, else the newest read
        names = subprocess.run(["gsutil", "ls", f"{BUCKET}/raw/leaderboard/{day}_*.json"], capture_output=True, text=True).stdout.split()
        feat = [n for n in names if n.endswith("_featured.json")]
        names = feat or names
        if not names:
            return None
        path = os.path.join(PH, "data", "leaderboard", os.path.basename(sorted(names)[-1]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["gsutil", "-q", "cp", sorted(names)[-1], path], check=True)
    return json.load(open(path))


def main(day, path=None):
    api = json.load(open(os.path.join(PH, "data", "today", f"{day}.json")))
    lb = leaderboard(day, path)
    if lb is None:
        print(day, "no leaderboard read yet"); return 0
    ids = Counter(str(n["id"]) for n in api)
    dup = [n["name"] for n in api if ids[str(n["id"])] > 1]
    have = {norm(n.get("slug")) for n in api} | {norm(n.get("name")) for n in api}
    miss = [x for x in lb["launches"] if norm(x.get("slug")) not in have and norm(x.get("name")) not in have]
    print(json.dumps({"day": day, "api": len(ids), "leaderboard": len(lb["launches"]), "complete": lb.get("complete"),
                      "missing_from_api": [(x.get("name"), x.get("votes")) for x in miss], "repeated_in_api": sorted(set(dup))}))
    return len(miss)


def refetch(day):
    """Page the day again in both API orders and add any launch the first pass missed to data/today/<day>.json
    (on Oct 31 one ordering repeated 2 launches and missed 2). Returns the names added."""
    sys.path.insert(0, PH)
    import collect_ph as C, datetime as dt
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles"); d = dt.date.fromisoformat(day)
    a = dt.datetime.combine(d, dt.time(0), PT).isoformat(); b = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), PT).isoformat()
    f = os.path.join(PH, "data", "today", f"{day}.json"); api = json.load(open(f)); have = {str(n["id"]) for n in api}
    added = []
    for q in (C.Q, C.Q_NEWEST):
        cur = None
        while True:
            p, _ = C.gql({"a": a, "b": b, "c": cur}, q)
            for e in p["edges"]:
                if str(e["node"]["id"]) not in have:
                    api.append(e["node"]); have.add(str(e["node"]["id"])); added.append(e["node"]["name"])
            if not p["pageInfo"]["hasNextPage"]:
                break
            cur = p["pageInfo"]["endCursor"]
    if added:
        json.dump(api, open(f, "w"))
    return added


def step(day):
    """For pipeline.daily: check today's list against today's featured read if there is one yet, else yesterday's list
    against yesterday's newest read. Missing launches today: page the day again and add them. -> dict for the run log."""
    import datetime as dt
    y = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    for d in (day, y):
        if not os.path.exists(os.path.join(PH, "data", "today", f"{d}.json")) or leaderboard(d) is None:
            continue
        miss = main(d)
        out = {"checked_day": d, "missing": int(miss)}
        if miss and d == day:
            out["added"] = refetch(d)
            miss = main(d)
        out["status"] = f"failed: featured launches missing from the API list for {d}" if miss else "ok"
        return out
    return {"checked_day": None, "status": "ok"}


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None) else 0)
