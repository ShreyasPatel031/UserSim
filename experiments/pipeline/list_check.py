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
    if path is None:
        names = subprocess.run(["gsutil", "ls", f"{BUCKET}/raw/leaderboard/{day}_*.json"], capture_output=True, text=True).stdout.split()
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
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
