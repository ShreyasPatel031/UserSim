"""GitHub audience pilot: are a launch's real Product Hunt voters in its makers' GitHub audience (followers, stargazers
of their top repos), more than people active the same day who did not vote for it? Public GitHub API, no login, from
the VM's own IP (60 requests/hour, paced by the rate-limit headers). Input: jobs JSON (launch, makers' GitHub handles,
voters and control people with their GitHub handles, from Product Hunt profile links).
usage: python -m simlab.gh_pilot jobs.json out.jsonl"""
import json, sys, time, urllib.request, urllib.error

UA = {"User-Agent": "usersim-research", "Accept": "application/vnd.github+json"}


def get(url):
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                left, reset = int(r.headers.get("X-RateLimit-Remaining", 1)), int(r.headers.get("X-RateLimit-Reset", 0))
                body = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
                time.sleep(max(5, int(e.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time() + 5)); continue
            return None
        except Exception:  # noqa: BLE001
            return None
        if left == 0:
            time.sleep(max(5, reset - time.time() + 5))
        return body


def audience(h):
    f = set()
    for p in (1, 2, 3):
        b = get(f"https://api.github.com/users/{h}/followers?per_page=100&page={p}") or []
        f |= {x["login"].lower() for x in b}
        if len(b) < 100:
            break
    repos = sorted(get(f"https://api.github.com/users/{h}/repos?per_page=100&type=owner") or [], key=lambda r: -r.get("stargazers_count", 0))[:2]
    s = set()
    for r in repos:
        if r.get("stargazers_count"):
            for p in (1, 2):
                b = get(f"https://api.github.com/repos/{h}/{r['name']}/stargazers?per_page=100&page={p}") or []
                s |= {x["login"].lower() for x in b}
                if len(b) < 100:
                    break
    return f, s, [r["name"] for r in repos]


def main(jobs, out):
    J = json.load(open(jobs)); cache = {}
    with open(out, "a") as o:
        for j in J:
            F, S, R = set(), set(), []
            for h in j["makers"]:
                if h not in cache:
                    cache[h] = audience(h)
                F |= cache[h][0]; S |= cache[h][1]; R += cache[h][2]
            rec = {"id": j["id"], "name": j["name"], "makers": j["makers"], "repos": R, "followers": len(F), "stargazers": len(S)}
            for grp in ("voters", "control"):
                ppl = {u: g.lower() for u, g in j[grp].items()}
                rec[grp] = {"n": len(ppl), "follower": [u for u, g in ppl.items() if g in F], "stargazer": [u for u, g in ppl.items() if g in S]}
            o.write(json.dumps(rec) + "\n"); o.flush(); print(rec["name"], rec["followers"], rec["stargazers"], len(rec["voters"]["follower"]), len(rec["control"]["follower"]), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
