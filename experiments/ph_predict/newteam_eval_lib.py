"""First-time teams: no maker had an earlier launch in our data (starts Jan 2026); the hunter is not counted, since a
hunter posts for many teams. Shared by newteam_eval.py and newsim_eval.py."""
import glob, json


def first_time():
    L = []
    for f in sorted(glob.glob("data/days/*.json")):
        for p in json.load(open(f)):
            mk = [m.get("username") for m in p.get("makers") or [] if isinstance(m, dict)]
            L.append((str(p["id"]), f[-15:-5], set(filter(None, mk))))
    L.sort(key=lambda r: r[1]); seen, out = set(), {}
    for i, d, team in L:
        out[i] = not (team & seen) if team else None
        seen |= team
    return out
