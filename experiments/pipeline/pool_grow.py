"""Grow the simulated population beyond people who comment: Product Hunt accounts followed by people we already know
(most-followed first: makers, hunters and regulars who upvote without commenting). For each new person, fetch their
upvotes page (their recent upvotes, the choice labels) and following page, the same way the daily people step does
(pipeline.fetch: direct, then the residential proxy; never Apify), and append to the warehouse.
usage: python -m pipeline.pool_grow N [--dry-run] -> events, follows, people, fetch_state, spend"""
import datetime as dt, json, os, subprocess, sys
import pandas as pd
from . import warehouse as W, fetch as F, incremental as INC

PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ph_predict")
BATCH = 400


def candidates(con, n):
    return con.execute(f"""SELECT followee AS person, count(DISTINCT f.person) AS followed_by FROM follows f
                           WHERE followee NOT IN (SELECT person FROM people) AND followee NOT LIKE '%[%'
                           GROUP BY 1 ORDER BY 2 DESC LIMIT {n}""").df().person.tolist()


def parse(script, recs):
    out = subprocess.run(["python3", script], cwd=PH, capture_output=True, text=True,
                         input="\n".join(json.dumps({"url": r["url"], "status": r["status"], "route": r["route"], "html": r["body"]}) for r in recs))
    return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]


def main(n, dry):
    d = dt.date.today().isoformat()
    con = W.connect()
    todo = candidates(con, n)
    print("new people to fetch:", len(todo), flush=True)
    tot = {"people": 0, "events": 0, "follows": 0, "usd": 0.0, "bytes": 0}
    for k in range(0, len(todo), BATCH):
        b = todo[k:k + BATCH]
        ru = F.get_many([f"https://www.producthunt.com/@{u}/upvotes" for u in b], threads=8, start_route=1)
        rf = F.get_many([f"https://www.producthunt.com/@{u}/following" for u in b], threads=8, start_route=1)
        U, Fo = parse("parse_upvotes.py", ru), parse("parse_following.py", rf)
        ok = sorted({r["username"] for r in U if r.get("upvotes") is not None})
        ev, st_u, _ = INC.merge_upvotes(con, U, d)
        fo, st_f = INC.merge_follows(con, Fo, d)
        usd, nbytes = F.cost(ru + rf)
        if not dry:
            for t, df in (("events", ev), ("fetch_state", st_u), ("follows", fo), ("fetch_state", st_f)):
                W.write(t, df)
            if ok:
                W.write("people", pd.DataFrame({"person": ok, "first_seen": d}))
            W.write("spend", pd.DataFrame([{"step": "pool_grow", "provider": p, "usd": v, "note": f"{len(b)} people", "logged_on": d}
                                           for p, v in usd.items() if v]))
        blocked = sum(r["status"] != 200 for r in ru)
        tot["people"] += len(ok); tot["events"] += len(ev); tot["follows"] += len(fo); tot["usd"] += sum(usd.values()); tot["bytes"] += nbytes
        print(json.dumps({"batch": k // BATCH, "fetched": len(b), "ok": len(ok), "blocked": blocked, "new_upvotes": len(ev), **tot}), flush=True)
        if blocked > len(b) / 2:
            print("more than half blocked: stopping", flush=True); break
        con = W.connect(do_sync=False)
    print("done", json.dumps(tot), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200, "--dry-run" in sys.argv)
